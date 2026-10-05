"""Paid feasibility probe for artifact 2's open-loop gate (plan 2b P1-P8).

SPENDS MONEY: two pinned RTX 4090 workers for ~10 minutes. The owner runs it
(docs/runbook-a2-validation.md). Reads RUNPOD_API_KEY and
RUNPOD_A2_LB_ENDPOINT_ID; never prints the key.

Pins 2 workers, warms up until both answer, then runs a constant-rate ladder
through the load balancer and releases (on any exit, including SIGTERM and
SIGHUP). Each step's outcomes go to <out>/step-<rate>.jsonl; the summary per
step goes to stdout and <out>/summary.json. The verdict at 450 req/s is the
amendment's acceptance rule; anything short of it stops the validation runs
until the owner decides.
"""

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from a2_lb_common import constant_rate, sender, summarize, warm_up

from autoscale.validation_schedule import (
    VALIDATION_REPLICAS,
    WARMUP_MAX_SECONDS,
    WARMUP_MIN_SECONDS,
    WARMUP_RPS,
)
from harness.open_loop import replay
from harness.runpod.pinning import WorkerPin, unwind_on_hangup_and_term

RATES = (25.0, 50.0, 100.0, 200.0, 300.0, 450.0)
STEP_SECONDS = 30.0
MIN_WORKER_SHARE = 0.35
MAX_JITTER_S = 0.25


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
    out.mkdir(parents=True, exist_ok=True)
    send = sender(endpoint, key)
    unwind_on_hangup_and_term()
    rows = {}
    with pin:
        ids = warm_up(send, workers=VALIDATION_REPLICAS, rps=WARMUP_RPS,
                      min_clean=WARMUP_MIN_SECONDS, max_seconds=WARMUP_MAX_SECONDS)
        print(f"[warm] workers {ids}")
        for rate in RATES:
            outs = replay(constant_rate(rate, STEP_SECONDS), send)
            with (out / f"step-{rate:g}.jsonl").open("w") as fh:
                for o in outs:
                    fh.write(json.dumps(asdict(o)) + "\n")
            rows[rate] = summarize(outs)
            print(f"[{rate:>5g} req/s] {json.dumps(rows[rate])}", flush=True)
    (out / "summary.json").write_text(json.dumps({"workers": ids, "steps": rows}, indent=1))
    passed, why = accept(rows[RATES[-1]], workers=VALIDATION_REPLICAS)
    print("[accept] PASS" if passed else "[accept] FAIL: " + "; ".join(why))


if __name__ == "__main__":
    main()
