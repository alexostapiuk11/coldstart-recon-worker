"""What artifact 2's LB probe and validation driver share: where, what and how to send.

The request is the service curve's shape: 13 prompt tokens, 16 output tokens,
generation not stopped early. The prompt is a list of token IDs, which the
OpenAI completions API accepts, so its length is exact without a tokenizer
here (a tokenizer would add a dependency and could still disagree with the
curve's 13 by one). No sampling parameters are sent: the sweep's bench
requests sent none, so both use the server's defaults (the model's
generation_config).
"""

import resource
import sys
import time
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.open_loop import http_sender, max_jitter, replay

WORKER = "x-a2-worker"
SERVER_LATENCY = "x-a2-server-latency-ms"
# Added by the driver, never by a server, to a request it retried (below). Its
# value is "<first status>:<seconds the first attempt took>".
RETRY_MARK = "a2-driver-lb-retry"
LB_RETRY_STATUS = 502
MODEL = "Qwen/Qwen3-8B"
PROMPT_TOKEN_IDS = tuple(range(1000, 1013))
OUTPUT_TOKENS = 16
REQUEST_TIMEOUT_S = 120.0
# Each pool thread keeps one keep-alive socket, so a replay with up to POOL_THREADS
# threads needs about that many descriptors plus the process's own files. macOS
# defaults to a soft limit of 256. The probe's ladder and the validation driver
# both run at 4096 in flight (their own constants); this is the shared check.
POOL_THREADS = 4096
MIN_OPEN_FILES = 8192


def ensure_fd_limit(needed: int = MIN_OPEN_FILES, res=resource) -> None:
    """Raise the soft open-files limit to `needed`, or refuse before the pin.

    Refusing after the workers are pinned was rejected: the replay would hit
    "Too many open files" on the first few hundred sockets and the run would
    be billed for nothing. Only the soft limit is raised, up to the hard one.
    """
    soft, hard = res.getrlimit(res.RLIMIT_NOFILE)
    if soft >= needed:
        return
    target = needed if hard in (res.RLIM_INFINITY, -1) else min(hard, needed)
    try:
        res.setrlimit(res.RLIMIT_NOFILE, (target, hard))
    except (ValueError, OSError):
        pass
    soft, _ = res.getrlimit(res.RLIMIT_NOFILE)
    if soft < needed:
        raise SystemExit(
            f"the open-files soft limit is {soft} and could not be raised to {needed}: the "
            f"replay's {POOL_THREADS} pool threads each hold a socket, so the run "
            "would fail with 'Too many open files' after the workers were pinned and billing. "
            f"Run `ulimit -n {needed}` in this shell and start again")


def retry_lb_502(send):
    """`send`, retrying once a 502 that never reached a worker.

    The second probe (2026-10-05) saw 13 of 31,500 requests answered 502 by the
    load balancer itself: no `x-a2-worker` header, back in 0.1-0.3 s, in bursts
    as the rate stepped up. Under the void rule as first signed, any one of them
    voids a repeat, so a repeat would be voided for a platform hiccup that
    never touched the engine the gate is about. Owner decision, amendment
    2026-10-05: such a 502 is retried once, at once, and marked; a retry that
    fails again is returned as it is, and still voids. Only that case: a 502
    WITH the worker header came from the engine, and other statuses were never
    seen, so neither is retried. Rejected: retrying until success, which turns
    an open-loop replay into a closed loop around a failing path and hides how
    often it failed.
    """
    def wrapped(i: int) -> tuple[int, dict]:
        t0 = time.monotonic()
        status, headers = send(i)
        if status == LB_RETRY_STATUS and not headers.get(WORKER):
            first = time.monotonic() - t0
            status, headers = send(i)
            headers = {**headers, RETRY_MARK: f"{LB_RETRY_STATUS}:{first:.3f}"}
        return status, headers
    return wrapped


def lb_url(endpoint_id: str) -> str:
    return f"https://{endpoint_id}.api.runpod.ai/v1/completions"


def payload() -> dict:
    return {"model": MODEL, "prompt": list(PROMPT_TOKEN_IDS), "max_tokens": OUTPUT_TOKENS,
            "ignore_eos": True}


def sender(endpoint_id: str, api_key: str):
    return retry_lb_502(http_sender(lb_url(endpoint_id), payload=payload(),
                                    headers={"Authorization": f"Bearer {api_key}"},
                                    timeout=REQUEST_TIMEOUT_S,
                                    keep_headers=(WORKER, SERVER_LATENCY)))


def constant_rate(rate: float, seconds: float) -> tuple[float, ...]:
    return tuple(i / rate for i in range(round(rate * seconds)))


def server_latency_s(outcome) -> float | None:
    raw = outcome.headers.get(SERVER_LATENCY)
    return None if raw is None else float(raw) / 1000.0


def warm_up(send, *, workers: int, rps: float, min_clean: float, max_seconds: float,
            chunk_seconds: float = 5.0, replay_fn=replay, clock=time.monotonic,
            summary_out: dict | None = None) -> list[str]:
    """Light load until all `workers` pinned workers have answered, cleanly, for `min_clean` s.

    Returns their ids: the run's host_ids. Refuses more distinct workers than
    pinned, because the fleet is then not the one the run is about to measure.
    Waiting on the pin's own acknowledgement instead was rejected: workersMin
    is set the moment the API says so, but a worker serves only after it has
    started and loaded the engine, and a run begun before that measures a
    cold start rather than the fleet.

    The deadline is wall-clock (`clock`), checked before and after every
    chunk. Adding `chunk_seconds` per chunk was rejected: a chunk against a
    hung endpoint takes up to the request timeout, not `chunk_seconds`, so the
    nominal total could run for hours while two pinned GPUs bill. The clean
    streak, by contrast, counts chunks (`chunk_seconds` each): measured time
    would credit a chunk that dragged on for minutes as one clean stretch.

    Fails at once, not at the deadline, when responses have been 200 for
    `min_clean` s yet none carried the worker header: the fleet is up and the
    middleware is not loaded, or the load balancer strips headers (plan 2b
    P5), and waiting longer cannot produce a worker id.

    `summary_out`, if given, is refilled with the last chunk's summary after
    every chunk, so the caller can record what the fleet looked like even
    when this raises. An out-parameter keeps the return value a plain list of
    ids; returning a tuple was rejected as a needless break for the callers.
    """
    seen: set[str] = set()
    clean = 0.0
    start = clock()

    def expired() -> bool:
        return clock() - start >= max_seconds

    def give_up() -> TimeoutError:
        return TimeoutError(
            f"after {clock() - start:g} s, {len(seen)} of {workers} pinned workers answered "
            f"(clean streak {clean:g} s); not starting a run on a fleet that is not up")

    while True:
        if expired():
            raise give_up()
        outs = replay_fn(constant_rate(rps, chunk_seconds), send, max_in_flight=64,
                         start_delay=0.1)
        last = summarize(outs)
        if summary_out is not None:
            summary_out.clear()
            summary_out.update(last)
        seen |= {o.headers[WORKER] for o in outs if WORKER in o.headers}
        if len(seen) > workers:
            raise RuntimeError(
                f"{len(seen)} distinct workers answered ({sorted(seen)}) with {workers} pinned; "
                "the endpoint is not the fleet the run would measure. Check workersMax")
        clean = clean + chunk_seconds if all(o.status == 200 for o in outs) else 0.0
        if clean >= min_clean and not seen:
            raise RuntimeError(
                f"every response has been 200 for {clean:g} s but none carried {WORKER}: the "
                "worker middleware is not loaded or the load balancer strips response headers "
                "(plan 2b P5). Without worker ids a run cannot be attributed to a fleet, so "
                "waiting for them would only bill")
        if len(seen) == workers and clean >= min_clean:
            return sorted(seen)
        if expired():
            raise give_up()


def summarize(outcomes) -> dict:
    ok = [o for o in outcomes if o.status == 200]
    workers = [o.headers.get(WORKER) for o in ok if o.headers.get(WORKER)]
    share = {w: workers.count(w) / len(workers) for w in sorted(set(workers))} if workers else {}
    client = [o.latency for o in ok if o.latency is not None]
    server = [s for s in (server_latency_s(o) for o in ok) if s is not None]
    c50 = median(client) if client else None
    s50 = median(server) if server else None
    return {
        "requests": len(outcomes),
        "non_200": sum(1 for o in outcomes if o.status is not None and o.status != 200),
        "errors": sum(1 for o in outcomes if o.error),
        "headerless_200": sum(1 for o in ok if not o.headers.get(WORKER)),
        "lb_502_retried": sum(1 for o in outcomes if RETRY_MARK in o.headers),
        "worker_share": share,
        "client_p50_s": c50,
        "server_p50_s": s50,
        "client_minus_server_p50_s": None if c50 is None or s50 is None else c50 - s50,
        "max_jitter_s": max_jitter(outcomes),
    }
