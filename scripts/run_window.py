"""Run one measurement window against the live endpoint.

    .venv/bin/python scripts/run_window.py --triples 12
    .venv/bin/python scripts/run_window.py --triples 12 --resume

Reads RUNPOD_API_KEY and RUNPOD_ENDPOINT_ID from the environment (.env is
gitignored). Refuses to start unless the endpoint still matches its pins.
"""

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coldstart.driver import run_campaign
from coldstart.preflight import assert_endpoint_matches, fetch_endpoint
from coldstart.runpod_submitter import HttpTransport, RunPodSubmitter
from coldstart.store import JsonlStore

STORE = Path("data/campaign.jsonl")
ARMS = ["A", "B", "C"]
# Fixed for the whole campaign, not per invocation. Every window rebuilds the
# same schedule from this seed and --resume skips what is already recorded in
# the store; changing this value would re-randomise the interleaving between
# windows and invalidate the experiment (interleaving is the design's most
# important validity property -- see coldstart.driver.run_campaign).
SCHEDULE_SEED = 20260828


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Run one measurement window against the live RunPod endpoint."
    )
    ap.add_argument(
        "--triples",
        type=int,
        required=True,
        help=(
            "number of triples in the WHOLE campaign schedule (not just this "
            "window) -- every invocation must pass the same value, together "
            "with the same --store, or --resume will detect the drift and "
            "refuse to continue"
        ),
    )
    ap.add_argument(
        "--resume",
        action="store_true",
        help="skip runs already recorded in --store instead of re-running them",
    )
    ap.add_argument("--store", default=str(STORE), help="path to the JSONL run store")
    args = ap.parse_args()

    key = os.environ["RUNPOD_API_KEY"]
    endpoint_id = os.environ["RUNPOD_ENDPOINT_ID"]

    assert_endpoint_matches(fetch_endpoint(endpoint_id, key))
    print(f"[preflight] endpoint {endpoint_id} matches the pinned configuration", flush=True)

    store = JsonlStore(args.store)
    started = time.monotonic()
    seen = {"n": 0}

    def progress(record):
        seen["n"] += 1
        outcome = record.status["outcome"]
        detail = record.status.get("failure_class") or ""
        elapsed = time.monotonic() - started
        print(
            f"[{seen['n']:>4}] run_index={record.run_index:<4} arm={record.arm} "
            f"{outcome:<7} {detail:<20} elapsed={elapsed / 60:.1f}m",
            flush=True,
        )

    run_campaign(
        submitter=RunPodSubmitter(HttpTransport(endpoint_id, key)),
        store=store,
        arms=ARMS,
        triples=args.triples,
        seed=SCHEDULE_SEED,
        on_run=progress,
        resume=args.resume,
    )
    print(f"[done] {seen['n']} runs this invocation; store={args.store}", flush=True)


if __name__ == "__main__":
    main()
