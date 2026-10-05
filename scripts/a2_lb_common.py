"""What artifact 2's LB probe and validation driver share: where, what and how to send.

The request is the service curve's shape: 13 prompt tokens, 16 output tokens,
generation not stopped early. The prompt is a list of token IDs, which the
OpenAI completions API accepts, so its length is exact without a tokenizer
here (a tokenizer would add a dependency and could still disagree with the
curve's 13 by one). No sampling parameters are sent: the sweep's bench
requests sent none, so both use the server's defaults (the model's
generation_config).
"""

import math
import resource
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.open_loop import http_sender, max_jitter, replay

WORKER = "x-a2-worker"
SERVER_LATENCY = "x-a2-server-latency-ms"
SERVER_RECEIVED = "x-a2-server-received"
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
# both cap their replay pool at POOL_THREADS; this is the shared value and check.
#
# 3500, not 4096: macOS allows 4096 threads per process (kern.num_taskthreads),
# the main thread and the libraries' own threads count against it, and a pool
# capped at 4096 crashed repeat 1 (2026-10-05) with "can't start new thread"
# once the load balancer held ~4000 requests. Under the cap a full pool does not
# fail: further requests wait to be sent, which the gate reads as send jitter.
POOL_THREADS = 3500
THREAD_HEADROOM = 256
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


def macos_thread_limit() -> int | None:
    """kern.num_taskthreads, or None off macOS or if it cannot be read."""
    if sys.platform != "darwin":
        return None
    try:
        out = subprocess.run(["sysctl", "-n", "kern.num_taskthreads"], capture_output=True,
                             text=True, check=True, timeout=5).stdout
        return int(out.strip())
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def ensure_thread_headroom(pool: int = POOL_THREADS, limit_fn=macos_thread_limit) -> None:
    """Refuse before the pin if the OS cannot give the pool its threads.

    Rejected: finding out mid-replay, which is how repeat 1 found out: the
    workers were pinned and billing, and no record was written. An unknown
    limit is not refused: Linux has no per-process cap this low by default.
    """
    limit = limit_fn()
    if limit is not None and pool + THREAD_HEADROOM > limit:
        raise SystemExit(
            f"this machine allows {limit} threads per process (kern.num_taskthreads) and the "
            f"replay pool may need {pool} plus about {THREAD_HEADROOM} of the process's own; "
            "the replay would die with \"can't start new thread\" after the workers were "
            "pinned. Lower POOL_THREADS or run the driver elsewhere")


# Amendment 2026-10-05 (fourth): each repeat's host is measured at
# autoscale.validation.CALIBRATION_LEVELS before its replay.
CALIBRATION_SETTLE_S = 10.0
CALIBRATION_MEASURE_S = 60.0
CALIBRATION_MIN_REQUESTS = 500


def closed_loop(send, concurrency: int, seconds: float, clock=time.monotonic) -> list[dict]:
    """`concurrency` senders, each sending back-to-back until `seconds` have passed.

    Closed loop, as the curve was measured: the engine holds about
    `concurrency` requests at all times. One row per request: its start and end
    on this call's clock, final status, server-side latency (None without a
    usable header) and error.
    """
    t0 = clock()
    rows: list[dict] = []
    lock = threading.Lock()

    def sender() -> None:
        while clock() - t0 < seconds:
            start = clock() - t0
            status, headers, error = None, {}, None
            try:
                status, headers = send(-1)
            except Exception as e:  # noqa: BLE001 -- a failed request is a row, not a crash
                error = f"{type(e).__name__}: {e}"[:300]
            raw = headers.get(SERVER_LATENCY)
            try:
                server = float(raw) / 1000.0 if raw is not None else None
            except ValueError:
                server = None
            with lock:
                rows.append({"start": start, "end": clock() - t0, "status": status,
                             "server_latency_s": server, "error": error})

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        for _ in range(concurrency):
            pool.submit(sender)
    return rows


def calibrate(send, curve, *, levels=None, settle=CALIBRATION_SETTLE_S,
              measure=CALIBRATION_MEASURE_S, min_requests=CALIBRATION_MIN_REQUESTS,
              closed_loop_fn=None) -> dict:
    """The repeat's host speed, as amendment 2026-10-05 (fourth) defines it.

    Per level: hold `level` requests outstanding for `settle + measure`
    seconds; the measured requests are those started after `settle`. The
    ratio is their median server-side latency over the committed curve's
    latency at that level. A level with fewer than `min_requests` measured
    requests, or any measured request that did not end in 200 with a
    server-latency header, voids the calibration, and with it the repeat.
    """
    from autoscale.validation import CALIBRATION_LEVELS
    levels = CALIBRATION_LEVELS if levels is None else levels
    loop = closed_loop if closed_loop_fn is None else closed_loop_fn
    out: dict = {"settle_s": settle, "measure_s": measure, "levels": {}, "void": []}
    ratios = []
    for level in levels:
        rows = loop(send, int(level), settle + measure)
        measured = [r for r in rows if r["start"] >= settle]
        good = [r["server_latency_s"] for r in measured
                if r["status"] == 200 and r["server_latency_s"] is not None]
        bad = len(measured) - len(good)
        med = median(good) if good else None
        ratio = None if med is None else med / curve.latency_at(level)
        name = f"{level:g}"
        if len(measured) < min_requests:
            out["void"].append(f"calibration level {name}: {len(measured)} measured requests, "
                               f"fewer than {min_requests}")
        if bad:
            out["void"].append(f"calibration level {name}: {bad} measured requests not 200 "
                               "with a server-latency header")
        out["levels"][name] = {"measured": len(measured), "settling": len(rows) - len(measured),
                               "not_200": bad, "median_server_latency_s": med,
                               "curve_latency_s": curve.latency_at(level), "ratio": ratio,
                               "rows": rows}
        ratios.append(ratio)
    out["ratios"] = None if out["void"] else ratios
    return out


def lb_url(endpoint_id: str) -> str:
    return f"https://{endpoint_id}.api.runpod.ai/v1/completions"


def payload() -> dict:
    return {"model": MODEL, "prompt": list(PROMPT_TOKEN_IDS), "max_tokens": OUTPUT_TOKENS,
            "ignore_eos": True}


def sender(endpoint_id: str, api_key: str):
    return retry_lb_502(http_sender(lb_url(endpoint_id), payload=payload(),
                                    headers={"Authorization": f"Bearer {api_key}"},
                                    timeout=REQUEST_TIMEOUT_S,
                                    keep_headers=(WORKER, SERVER_LATENCY, SERVER_RECEIVED)))


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
        # A worker answering without the engine-arrival stamp runs an image from
        # before the amendment of 2026-10-05 (third). RunPod restarted exactly such
        # a worker after the template moved to the new image, and the repeat was
        # paid for and voided. Waiting cannot change a worker's image, so stop now.
        stale = sorted({o.headers[WORKER] for o in outs if o.status == 200
                        and WORKER in o.headers and SERVER_RECEIVED not in o.headers})
        if stale:
            raise RuntimeError(
                f"workers {stale} answered without {SERVER_RECEIVED}: they run an image from "
                "before the engine-arrival amendment, and every request they serve would void "
                "the run. Make the endpoint start workers on the current image first")
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


def _p99(values) -> float | None:
    """Nearest-rank p99, or None for no values. Nearest-rank, not interpolated:
    the probe compares two tails, and a value that was actually observed is
    the plainer reading of each."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.99 * len(ordered)) - 1)]


def summarize(outcomes) -> dict:
    ok = [o for o in outcomes if o.status == 200]
    workers = [o.headers.get(WORKER) for o in ok if o.headers.get(WORKER)]
    share = {w: workers.count(w) / len(workers) for w in sorted(set(workers))} if workers else {}
    client = [o.latency for o in ok if o.latency is not None]
    server = [s for s in (server_latency_s(o) for o in ok) if s is not None]
    c50 = median(client) if client else None
    s50 = median(server) if server else None
    c99, s99 = _p99(client), _p99(server)
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
        "client_p99_s": c99,
        "server_p99_s": s99,
        "max_jitter_s": max_jitter(outcomes),
    }
