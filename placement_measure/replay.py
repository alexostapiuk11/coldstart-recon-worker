"""Trace replay on one GPU: tenants sharing it by process-level swap, at the
trace's exact arrival times. August §9's validation gate, amendment §1e item 7.

`vllm bench serve` cannot do this. It sends a dataset at a rate, not a recorded
schedule at its timestamps, and it has no notion of a request waiting for its
model to be swapped in. So the driver is artifact 4's own.

The policy is the simulator's swap-LRU for a pool of one GPU
(`placement/sim.py`), restated here because this package may not import
`placement`:

- A request for the resident tenant is sent at once if fewer than
  `max_in_flight` are in flight, and queued first-in first-out otherwise. The
  cap is the solo curve's top measured concurrency, the simulator's capacity.
- A request for any other tenant queues. If no swap is under way, the GPU stops
  admitting the resident's requests (they queue too), drains the ones in
  flight, and swaps: teardown, memory release, eviction of the incoming
  checkpoint from the page cache when `cold`, and the incoming engine up to
  `/health`.
- When a swap completes, the incoming tenant's queue is sent up to the cap.
  Then, if another tenant is waiting, the next swap starts at once, for the
  tenant whose oldest request has waited longest -- as the simulator's
  `schedule_swaps` runs after every `swap_done`.
- With one GPU the victim is always the resident, so LRU's choice across GPUs
  is not exercised. Unit tests cover it on the simulator (amendment §7).

Latency runs from a request's arrival, as in the simulator, so time queued
behind a swap counts. Arrival is the driver's clock when it handled the
scheduled arrival; how far that lags the schedule is the send jitter
`placement.validation` bounds. Every time in the output is seconds since the
replay's start, `t0`, which is taken once the first engine is healthy.

One event loop owns all state. Requests run on a thread pool and swaps on
their own thread; both report back through one queue, so no state is shared
between threads.
"""

import contextlib
import queue
import random
import threading
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import requests

from placement_measure.engine import EngineSpec, engine_facts, log_tail
from placement_measure.swap import ENGINE_ENV, PORT

__all__ = ["ReplayDeps", "ReplaySpec", "complete", "prompt_ids", "replay"]

# Token ids drawn for a prompt: well inside every Qwen3 vocabulary, and past the
# low ids where special tokens live. Ids rather than text, so the prompt is
# exactly `input_len` tokens without a tokenizer in the driver.
PROMPT_ID_RANGE = (1000, 30000)
PROMPT_SEED_STRIDE = 1_000_003
REQUEST_TIMEOUT_S = 600.0
# A swap still running at the deadline is waited for this long, so its engine
# can be stopped: an engine left running holds the port and the memory the
# worker's next job needs. `placement_measure.jobs` reserves this much of the
# job budget on top of its teardown reserve, so the wait cannot outlast the
# platform's timeout.
SWAP_WAIT_S = 240.0


@dataclass(frozen=True)
class ReplaySpec:
    tenants: tuple[EngineSpec, ...]
    schedule: tuple[tuple[float, int], ...]  # (seconds after t0, tenant index), ascending
    until: float
    input_len: int
    output_len: int
    max_in_flight: int
    cold: bool
    seed: int
    hf_home: str
    release_tolerance_mib: float
    release_timeout_s: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenants", tuple(self.tenants))
        object.__setattr__(self, "schedule", tuple((float(t), int(m)) for t, m in self.schedule))
        if len(self.tenants) < 2:
            raise ValueError("a replay needs at least two tenants, or nothing is ever swapped")
        if not self.schedule:
            raise ValueError("an empty schedule replays nothing")
        previous = 0.0
        for t, m in self.schedule:
            if not (previous <= t <= self.until):
                raise ValueError(
                    f"schedule entry at {t!r} is not ascending or falls past until={self.until!r}; "
                    "the simulator would refuse to replay it"
                )
            if not 0 <= m < len(self.tenants):
                raise ValueError(f"schedule names tenant {m}, but there are {len(self.tenants)}")
            previous = t
        if type(self.max_in_flight) is not int or self.max_in_flight < 1:
            raise ValueError(f"max_in_flight must be a positive int, got {self.max_in_flight!r}")

    @classmethod
    def from_payload(cls, p: dict) -> "ReplaySpec":
        return cls(
            tenants=tuple(EngineSpec.from_dict(t) for t in p["tenants"]),
            schedule=tuple((t, m) for t, m in p["schedule"]),
            until=float(p["until"]), input_len=int(p["input_len"]),
            output_len=int(p["output_len"]), max_in_flight=int(p["max_in_flight"]),
            cold=bool(p["cold"]), seed=int(p["seed"]), hf_home=p["hf_home"],
            release_tolerance_mib=float(p["release_tolerance_mib"]),
            release_timeout_s=float(p["release_timeout_s"]),
        )


def prompt_ids(seed: int, index: int, input_len: int) -> list[int]:
    """The prompt of request `index`: fixed by the seed, so every repeat of a
    replay sends identical prompts, and distinct per request, so a prompt is
    never served from a cache of an earlier one."""
    rng = random.Random(seed * PROMPT_SEED_STRIDE + index)
    return [rng.randrange(*PROMPT_ID_RANGE) for _ in range(input_len)]


def complete(base_url: str, model: str, ids: list[int], max_tokens: int,
             *, post: Callable = requests.post) -> dict:
    """One completion of exactly `max_tokens` tokens. `ignore_eos` is vLLM's
    own request field; without it a model that stops early makes service time
    depend on which checkpoint answered (amendment §3)."""
    try:
        r = post(f"{base_url}/v1/completions",
                 json={"model": model, "prompt": ids, "max_tokens": max_tokens,
                       "ignore_eos": True, "temperature": 0.0},
                 timeout=REQUEST_TIMEOUT_S)
        tokens = None
        if r.status_code == 200:
            tokens = (r.json().get("usage") or {}).get("completion_tokens")
        ok = r.status_code == 200 and tokens == max_tokens
        return {"ok": ok, "status": r.status_code, "completion_tokens": tokens,
                "error": None if ok else r.text[:300]}
    except Exception as e:  # noqa: BLE001 -- a failed request is data; the replay must finish
        return {"ok": False, "status": None, "completion_tokens": None, "error": repr(e)[:300]}


@dataclass
class ReplayDeps:
    """The effects, injectable so tests replay without an engine or a GPU.
    None means the real one, resolved lazily so importing needs no vLLM."""

    served: Callable | None = None
    complete: Callable = complete
    read_memory: Callable | None = None
    wait_for_release: Callable | None = None
    make_cold: Callable | None = None
    weight_files: Callable | None = None
    clock: Callable[[], float] = field(default=time.monotonic)


def _resolve(d: ReplayDeps) -> ReplayDeps:
    if d.served is None:
        from harness.serve import served

        d.served = served
    if d.read_memory is None or d.wait_for_release is None:
        from placement_measure import gpu_memory

        d.read_memory = d.read_memory or gpu_memory.read_memory
        d.wait_for_release = d.wait_for_release or gpu_memory.wait_for_release
    if d.make_cold is None or d.weight_files is None:
        from placement_measure import pagecache

        d.make_cold = d.make_cold or pagecache.make_cold
        d.weight_files = d.weight_files or pagecache.weight_files
    return d


def _engine_part(spec: EngineSpec, server, startup_s: float) -> dict:
    lines = list(server.log_lines)
    return {"spec": spec.to_dict(), "healthy": bool(server.healthy), "startup_s": startup_s,
            "facts": engine_facts(lines), **log_tail(lines)}


class _Engine:
    """One running engine, entered in one thread and stopped in another."""

    def __init__(self, d: ReplayDeps, spec: EngineSpec):
        self.spec = spec
        self.stack = contextlib.ExitStack()
        self.closed = False
        try:
            t = d.clock()
            self.server = self.stack.enter_context(
                d.served(spec.model, args=spec.serve_args(), env=dict(ENGINE_ENV), port=PORT))
            self.part = _engine_part(spec, self.server, d.clock() - t)
        except BaseException:
            # An engine that started but whose record could not be built must
            # still be stopped, or it holds the GPU with nothing tracking it.
            self.stack.close()
            raise

    def stop(self) -> float:
        teardown_s = self.server.stop()
        self.close()
        return teardown_s

    def close(self) -> None:
        """Exit the engine's context once; safe after `stop` and after a failed stop."""
        if not self.closed:
            self.closed = True
            self.stack.close()


def replay(spec: ReplaySpec, *, deadline: float, deps: ReplayDeps | None = None) -> dict:
    """Replay `spec.schedule` and return every request's times and every swap.

    `deadline` is on `deps.clock`. Past it nothing new is sent or swapped,
    and requests still waiting or in flight are reported unfinished (None),
    because a job the platform kills returns nothing at all.
    """
    d = _resolve(deps or ReplayDeps())
    n = len(spec.schedule)
    arrived: list[float | None] = [None] * n
    sent: list[float | None] = [None] * n
    done: list[float | None] = [None] * n
    ok: list[bool] = [False] * n
    errors: list[str | None] = [None] * n
    swaps: list[dict] = []
    baseline = d.read_memory()
    # The schedule is echoed so the stored record is self-contained: the
    # validation checks that every repeat replayed the same trace from the
    # records alone.
    out = {"tenants": [t.to_dict() for t in spec.tenants], "until": spec.until,
           "schedule": [[t, m] for t, m in spec.schedule], "baseline_memory": baseline}

    def unreplayed(failure: str, initial=None) -> dict:
        return {**out, "initial": initial, "healthy": False, "failure": failure,
                "arrived": arrived, "sent": sent, "done": done, "ok": ok, "errors": errors,
                "swaps": swaps, "deadline_hit": False, "unsent": n}

    if baseline.get("used_mib") is None:
        return unreplayed("the idle memory reading failed, so a swap's release has no target")
    engine: _Engine | None = _Engine(d, spec.tenants[0])
    if not engine.part["healthy"]:
        engine.stop()
        return unreplayed("the first engine never answered /health", engine.part)
    out["initial"] = engine.part

    events: queue.Queue = queue.Queue()
    pool = ThreadPoolExecutor(max_workers=spec.max_in_flight)
    t0 = d.clock()

    def now() -> float:
        return d.clock() - t0

    resident = 0
    state = "serving"  # | "draining" | "swapping"
    target: int | None = None
    in_flight = 0
    waiting: dict[int, deque[int]] = {m: deque() for m in range(len(spec.tenants))}
    failure: str | None = None

    def send(i: int) -> None:
        nonlocal in_flight
        in_flight += 1
        sent[i] = now()
        base_url, model = engine.server.base_url, engine.spec.model
        ids = prompt_ids(spec.seed, i, spec.input_len)

        def work() -> None:
            result = d.complete(base_url, model, ids, spec.output_len)
            events.put(("done", i, d.clock() - t0, result))

        pool.submit(work)

    def dispatch() -> None:
        q = waiting[resident]
        while state == "serving" and q and in_flight < spec.max_in_flight:
            send(q.popleft())

    def run_swap(outgoing: int, incoming: int, previous: "_Engine") -> None:
        record = {"from": outgoing, "to": incoming, "swap_start": now()}
        try:
            record["teardown_s"] = previous.stop()
            release = d.wait_for_release(baseline["used_mib"] + spec.release_tolerance_mib,
                                         timeout_s=spec.release_timeout_s)
            record["release"] = release
            b = spec.tenants[incoming]
            record["cache"] = (d.make_cold(d.weight_files(spec.hf_home, b.model, b.revision))
                               if spec.cold else {"requested": False})
            new = _Engine(d, b)
            record["b"] = new.part
            record["ready"] = now()
            events.put(("swap_done", record, new))
        except Exception as e:  # noqa: BLE001 -- the loop must hear about it, not hang
            record["error"] = f"{type(e).__name__}: {e}"[:400]
            # If the outgoing engine's stop raised, its context is still open.
            try:
                previous.close()
            except Exception as cleanup:  # noqa: BLE001 -- reported, never raised from here
                record["cleanup_error"] = repr(cleanup)[:300]
            events.put(("swap_done", record, None))

    def start_swap() -> None:
        nonlocal state
        state = "swapping"
        threading.Thread(target=run_swap, args=(resident, target, engine), daemon=True).start()

    def schedule_swap() -> None:
        # One swap at a time on one GPU. The oldest waiter among the tenants
        # that are not resident goes first.
        nonlocal state, target
        if state != "serving":
            return
        others = [m for m, q in waiting.items() if q and m != resident]
        if not others:
            return
        target = min(others, key=lambda m: spec.schedule[waiting[m][0]][0])
        state = "draining"
        if in_flight == 0:
            start_swap()

    k = 0
    deadline_hit = False
    while True:
        if k == n and in_flight == 0 and state == "serving" and not any(waiting.values()):
            break
        if d.clock() >= deadline:
            deadline_hit = True
            break
        timeout = deadline - d.clock()
        if k < n:
            timeout = min(timeout, max(0.0, t0 + spec.schedule[k][0] - d.clock()))
        try:
            event = events.get(timeout=max(0.0, timeout))
        except queue.Empty:
            event = None
        if event is not None and event[0] == "done":
            _, i, t_done, result = event
            in_flight -= 1
            done[i], ok[i] = t_done, bool(result["ok"])
            errors[i] = result.get("error")
            if state == "draining" and in_flight == 0:
                start_swap()
            else:
                dispatch()
        elif event is not None and event[0] == "swap_done":
            _, record, new = event
            swaps.append(record)
            engine, state = new, "serving"
            if new is None or not new.part["healthy"] or not record["release"]["released"]:
                failure = record.get("error") or (
                    "the incoming engine never answered /health" if new is None
                    or not new.part["healthy"]
                    else "the outgoing engine's memory was not released within the timeout")
                break
            resident, target = record["to"], None
            dispatch()
            schedule_swap()
        while k < n and t0 + spec.schedule[k][0] <= d.clock():
            m = spec.schedule[k][1]
            arrived[k] = now()
            waiting[m].append(k)
            if m == resident:
                dispatch()
            schedule_swap()
            k += 1

    pool.shutdown(wait=False, cancel_futures=True)
    engine_left_running = False
    if state == "swapping":
        # The deadline fell mid-swap. The swap thread owns the outgoing engine
        # and will start the incoming one; wait for it, then stop that. Nothing
        # else is in flight while swapping, so the next event is the swap's.
        engine = None
        try:
            _, record, engine = events.get(timeout=SWAP_WAIT_S)
            swaps.append(record)
        except queue.Empty:
            engine_left_running = True
    if engine is not None:
        engine.stop()
    return {
        **out,
        "healthy": failure is None,
        "failure": failure,
        "arrived": arrived, "sent": sent, "done": done, "ok": ok, "errors": errors,
        "swaps": swaps,
        "deadline_hit": deadline_hit,
        "engine_left_running": engine_left_running,
        "unsent": sum(1 for s in sent if s is None),
    }
