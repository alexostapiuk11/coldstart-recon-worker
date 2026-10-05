"""What artifact 2's LB probe and validation driver share: where, what and how to send.

The request is the service curve's shape: 13 prompt tokens, 16 output tokens,
generation not stopped early. The prompt is a list of token IDs, which the
OpenAI completions API accepts, so its length is exact without a tokenizer
here (a tokenizer would add a dependency and could still disagree with the
curve's 13 by one). No sampling parameters are sent: the sweep's bench
requests sent none, so both use the server's defaults (the model's
generation_config).
"""

import sys
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.open_loop import http_sender, max_jitter, replay

WORKER = "x-a2-worker"
SERVER_LATENCY = "x-a2-server-latency-ms"
MODEL = "Qwen/Qwen3-8B"
PROMPT_TOKEN_IDS = tuple(range(1000, 1013))
OUTPUT_TOKENS = 16
REQUEST_TIMEOUT_S = 120.0


def lb_url(endpoint_id: str) -> str:
    return f"https://{endpoint_id}.api.runpod.ai/v1/completions"


def payload() -> dict:
    return {"model": MODEL, "prompt": list(PROMPT_TOKEN_IDS), "max_tokens": OUTPUT_TOKENS,
            "ignore_eos": True}


def sender(endpoint_id: str, api_key: str):
    return http_sender(lb_url(endpoint_id), payload=payload(),
                       headers={"Authorization": f"Bearer {api_key}"},
                       timeout=REQUEST_TIMEOUT_S, keep_headers=(WORKER, SERVER_LATENCY))


def constant_rate(rate: float, seconds: float) -> tuple[float, ...]:
    return tuple(i / rate for i in range(round(rate * seconds)))


def server_latency_s(outcome) -> float | None:
    raw = outcome.headers.get(SERVER_LATENCY)
    return None if raw is None else float(raw) / 1000.0


def warm_up(send, *, workers: int, rps: float, min_clean: float, max_seconds: float,
            chunk_seconds: float = 5.0, replay_fn=replay) -> list[str]:
    """Light load until all `workers` pinned workers have answered, cleanly, for `min_clean` s.

    Returns their ids: the run's host_ids. Refuses more distinct workers than
    pinned, because the fleet is then not the one the run is about to measure.
    Waiting on the pin's own acknowledgement instead was rejected: workersMin
    is set the moment the API says so, but a worker serves only after it has
    started and loaded the engine, and a run begun before that measures a
    cold start rather than the fleet.
    """
    seen: set[str] = set()
    clean = 0.0
    elapsed = 0.0
    while True:
        outs = replay_fn(constant_rate(rps, chunk_seconds), send, max_in_flight=64,
                         start_delay=0.1)
        elapsed += chunk_seconds
        seen |= {o.headers[WORKER] for o in outs if WORKER in o.headers}
        if len(seen) > workers:
            raise RuntimeError(
                f"{len(seen)} distinct workers answered ({sorted(seen)}) with {workers} pinned; "
                "the endpoint is not the fleet the run would measure. Check workersMax")
        clean = clean + chunk_seconds if all(o.status == 200 for o in outs) else 0.0
        if len(seen) == workers and clean >= min_clean:
            return sorted(seen)
        if elapsed >= max_seconds:
            raise TimeoutError(
                f"after {elapsed:g} s, {len(seen)} of {workers} pinned workers answered "
                f"(clean streak {clean:g} s); not starting a run on a fleet that is not up")


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
        "worker_share": share,
        "client_p50_s": c50,
        "server_p50_s": s50,
        "client_minus_server_p50_s": None if c50 is None or s50 is None else c50 - s50,
        "max_jitter_s": max_jitter(outcomes),
    }
