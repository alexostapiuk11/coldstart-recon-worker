"""Paid feasibility probe for artifact 2's open-loop gate (plan 2b P1-P8).

SPENDS MONEY: two pinned RTX 4090 workers for ~10 minutes. The owner runs it
(docs/runbook-a2-validation.md). Reads RUNPOD_API_KEY and
RUNPOD_A2_LB_ENDPOINT_ID; never prints the key or writes it anywhere.

Pins 2 workers, warms up until both answer, then runs a constant-rate ladder
through the load balancer and releases (on any exit, including SIGTERM and
SIGHUP). Each step's outcomes go to <out>/step-<rate>.jsonl. The evidence is
<out>/summary.json, rewritten (atomically) after warm-up and after every step
with `status` ("warming", "running", "complete" or "stopped: <reason>"), the
warm-up's last chunk summary, the workers, the steps, and how the release
ended. It is written once more on the way out of any failure, so a partial
run, or a release that failed after a complete ladder, still leaves its
evidence. Writing it only after the ladder was rejected: the steps that did
run are exactly what the owner needs after a failure, and they cost money.

The verdict at 450 req/s is the amendment's acceptance rule, evaluated only
if that step completed; otherwise the probe prints that acceptance was not
evaluable. Anything short of a pass stops the validation runs until the owner
decides.

Spend guard: the ladder stops after any step in which more than half the
requests failed (non-200 or error). That does not change the pre-registered
acceptance, which needs zero non-200s at the top step: a later step cannot
turn a failing ladder into a passing one, so continuing would only bill.
"""

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from a2_lb_common import constant_rate, ensure_fd_limit, sender, summarize, warm_up

from autoscale.validation_schedule import (
    VALIDATION_REPLICAS,
    WARMUP_MAX_SECONDS,
    WARMUP_MIN_SECONDS,
    WARMUP_RPS,
)
from harness.open_loop import replay
from harness.runpod.pinning import ReleaseFailed, WorkerPin, unwind_on_hangup_and_term

RATES = (25.0, 50.0, 100.0, 200.0, 300.0, 450.0)
STEP_SECONDS = 30.0
MIN_WORKER_SHARE = 0.35
MAX_JITTER_S = 0.25
EARLY_STOP_FAILURE_FRACTION = 0.5
# 450 req/s over 2 workers is above one replica's 211 req/s saturation, so
# latency climbs through the step. 4096 threads hold about 9 s of latency
# (4096 / 450) before the driver's pool, not the load balancer, causes send
# jitter. The replay default of 1024 holds only ~2.3 s and would blame the LB
# for the driver's own queueing.
LADDER_MAX_IN_FLIGHT = 4096


def accept(summary: dict, *, workers: int) -> tuple[bool, list[str]]:
    why = []
    if summary["non_200"] or summary["errors"]:
        why.append(f"{summary['non_200']} non-200 and {summary['errors']} errors at the top step")
    shares = summary["worker_share"]
    if len(shares) != workers or min(shares.values(), default=0.0) < MIN_WORKER_SHARE:
        why.append(f"worker shares {shares}: each of {workers} must serve >= {MIN_WORKER_SHARE:.0%}")
    if summary["max_jitter_s"] > MAX_JITTER_S:
        why.append(f"max send jitter {summary['max_jitter_s']:.3f} s > {MAX_JITTER_S} s")
    return (not why, why)


def _write_summary(out: Path, state: dict) -> None:
    tmp = out / "summary.json.tmp"
    tmp.write_text(json.dumps(state, indent=1))
    os.replace(tmp, out / "summary.json")


def _failure_fraction(row: dict) -> float:
    return (row["non_200"] + row["errors"]) / row["requests"] if row["requests"] else 1.0


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="build/a2-lb-probe")
    ap.add_argument("--preflight-only", action="store_true")
    args = ap.parse_args(argv)
    key = os.environ["RUNPOD_API_KEY"]
    endpoint = os.environ["RUNPOD_A2_LB_ENDPOINT_ID"]
    pin = WorkerPin(endpoint, key, workers=VALIDATION_REPLICAS)
    if args.preflight_only:
        ep = pin.preflight()
        print(f"[preflight] {endpoint}: workersMin {ep['workersMin']}, workersMax "
              f"{ep['workersMax']}; nothing written")
        return
    out = Path(args.out)
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} is not empty; move the earlier probe aside first")
    ensure_fd_limit(8192)  # before the pin and before anything is written
    out.mkdir(parents=True, exist_ok=True)
    send = sender(endpoint, key)
    unwind_on_hangup_and_term()
    state = {"status": "warming", "workers": None, "warmup": {}, "steps": {},
             "release": None, "error": None}
    rows = {}
    _write_summary(out, state)
    try:
        with pin:
            ids = warm_up(send, workers=VALIDATION_REPLICAS, rps=WARMUP_RPS,
                          min_clean=WARMUP_MIN_SECONDS, max_seconds=WARMUP_MAX_SECONDS,
                          summary_out=state["warmup"])
            state["workers"] = ids
            state["status"] = "running"
            _write_summary(out, state)
            print(f"[warm] workers {ids}; last chunk {json.dumps(state['warmup'])}", flush=True)
            for i, rate in enumerate(RATES):
                outs = replay(constant_rate(rate, STEP_SECONDS), send,
                              max_in_flight=LADDER_MAX_IN_FLIGHT)
                with (out / f"step-{rate:g}.jsonl").open("w") as fh:
                    for o in outs:
                        fh.write(json.dumps(asdict(o)) + "\n")
                rows[rate] = summarize(outs)
                state["steps"][f"{rate:g}"] = rows[rate]
                _write_summary(out, state)
                print(f"[{rate:>5g} req/s] {json.dumps(rows[rate])}", flush=True)
                frac = _failure_fraction(rows[rate])
                if frac > EARLY_STOP_FAILURE_FRACTION and i + 1 < len(RATES):
                    state["status"] = (
                        f"stopped: {frac:.0%} of the {rate:g} req/s step's requests failed "
                        f"(over {EARLY_STOP_FAILURE_FRACTION:.0%}); later steps cannot change "
                        "the acceptance verdict, so the ladder stopped to stop billing")
                    print(f"[stop] {state['status']}", flush=True)
                    break
            else:
                state["status"] = "complete"
            _write_summary(out, state)
        state["release"] = "ok"
    except BaseException as e:
        state["error"] = f"{type(e).__name__}: {e}"[:300]
        state["release"] = "FAILED" if isinstance(e, ReleaseFailed) else "ok"
        if state["status"] in ("warming", "running"):
            state["status"] = f"stopped: {state['error']}"
        raise
    finally:
        _write_summary(out, state)
    if RATES[-1] in rows:
        passed, why = accept(rows[RATES[-1]], workers=VALIDATION_REPLICAS)
        print("[accept] PASS" if passed else "[accept] FAIL: " + "; ".join(why))
    else:
        print(f"[accept] not evaluable: the {RATES[-1]:g} req/s step did not run "
              f"({state['status']})")


if __name__ == "__main__":
    main()
