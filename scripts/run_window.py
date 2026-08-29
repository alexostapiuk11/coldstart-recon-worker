"""Run one measurement window against the live endpoint.

    .venv/bin/python scripts/run_window.py --triples 12
    .venv/bin/python scripts/run_window.py --triples 12 --resume

Reads RUNPOD_API_KEY and RUNPOD_ENDPOINT_ID from the environment (.env is
gitignored):

    set -a; . ./.env; set +a

Refuses to start unless the endpoint still matches its pins.
"""

import argparse
import os
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coldstart.driver import run_campaign
from coldstart.preflight import assert_endpoint_matches, fetch_endpoint
from coldstart.runpod_submitter import HttpTransport, RunPodSubmitter
from coldstart.store import JsonlStore

# Anchored to the repo root, like the sys.path line above -- a cwd-relative
# default (e.g. `Path("data/campaign.jsonl")`) would resolve against whatever
# directory the operator happens to be in. Invoked from a different terminal,
# tmux pane, or cron entry without an explicit --store, that would silently
# create a fresh, empty store elsewhere: run_campaign's resume-drift guard
# only validates records that are present, so an empty store passes trivially
# and the "resumed" window would restart at run_index=0, re-submitting and
# re-paying for every already-collected run.
STORE = Path(__file__).resolve().parents[1] / "data" / "campaign.jsonl"
ARMS = ["A", "B", "C"]
# Fixed for the whole campaign, not per invocation. Every window rebuilds the
# same schedule from this seed and --resume skips what is already recorded in
# the store; changing this value would re-randomise the interleaving between
# windows and invalidate the experiment (interleaving is the design's most
# important validity property -- see coldstart.driver.run_campaign).
SCHEDULE_SEED = 20260828


class RunTally:
    """Accumulates per-arm and per-outcome counts as runs land.

    Kept as a small, explicit accumulator rather than ad-hoc locals in the
    progress callback so a later between-window summary check can reuse this
    same accounting instead of re-deriving it in a second file.
    """

    def __init__(self):
        self.total = 0
        self.by_outcome = Counter()
        self.failed_by_arm = Counter()

    def add(self, record) -> None:
        self.total += 1
        outcome = record.status["outcome"]
        self.by_outcome[outcome] += 1
        if outcome != "ok":
            self.failed_by_arm[record.arm] += 1

    def summary(self) -> str:
        outcomes = " ".join(f"{k}={v}" for k, v in sorted(self.by_outcome.items()))
        parts = [f"{self.total} runs"]
        if outcomes:
            parts.append(outcomes)
        if self.failed_by_arm:
            per_arm = ", ".join(
                f"arm {arm}: {n} failed" for arm, n in sorted(self.failed_by_arm.items())
            )
            return f"{parts[0]}; {outcomes} ({per_arm})"
        return "; ".join(parts)


def _positive_int(raw: str) -> int:
    value = int(raw)
    if value <= 0:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {raw!r}")
    return value


def _require_credentials() -> tuple[str, str]:
    names = ("RUNPOD_API_KEY", "RUNPOD_ENDPOINT_ID")
    missing = [n for n in names if n not in os.environ]
    if missing:
        sys.exit(
            f"missing required environment variable(s): {', '.join(missing)} "
            "(see module docstring: `set -a; . ./.env; set +a`)"
        )
    return os.environ["RUNPOD_API_KEY"], os.environ["RUNPOD_ENDPOINT_ID"]


def _guard_against_silent_restart(store: JsonlStore, path: str, resume: bool, force: bool) -> None:
    """Refuse to proceed if this looks like an accidental restart from zero.

    Forgetting --resume on day three of a campaign would otherwise silently
    re-submit and re-pay for every prior run and append duplicate run_index
    rows -- nothing downstream de-duplicates by run_index, so this would bias
    the dataset as well as the bill. Make that impossible to do by accident:
    require either --resume or an explicit --force-restart acknowledging the
    re-submission.
    """
    if resume:
        return
    existing = store.read_all()
    if not existing:
        return
    if not force:
        sys.exit(
            f"refusing to start: {len(existing)} record(s) already exist in {path} "
            "and --resume was not passed. Continuing would re-submit and re-pay "
            "for every one of them, and nothing downstream de-duplicates by "
            "run_index. Pass --resume to continue the existing campaign, or "
            "--force-restart if you really mean to start over from run_index 0."
        )
    print(
        f"[warning] --force-restart set: ignoring {len(existing)} existing record(s) "
        f"in {path}; those runs will be re-submitted and re-paid for.",
        flush=True,
    )


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Run one measurement window against the live RunPod endpoint.",
        epilog=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--triples",
        type=_positive_int,
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
    ap.add_argument(
        "--force-restart",
        action="store_true",
        help=(
            "allow starting from run_index 0 even though --store already holds "
            "records and --resume was not passed; this re-submits and re-pays "
            "for every run already on disk -- normally you want --resume instead"
        ),
    )
    ap.add_argument("--store", default=str(STORE), help="path to the JSONL run store")
    args = ap.parse_args()

    key, endpoint_id = _require_credentials()

    assert_endpoint_matches(fetch_endpoint(endpoint_id, key))
    print(f"[preflight] endpoint {endpoint_id} matches the pinned configuration", flush=True)

    store = JsonlStore(args.store)
    _guard_against_silent_restart(store, args.store, resume=args.resume, force=args.force_restart)

    started = time.monotonic()
    tally = RunTally()

    def progress(record):
        tally.add(record)
        outcome = record.status["outcome"]
        detail = record.status.get("failure_class") or ""
        elapsed = time.monotonic() - started
        print(
            f"[{tally.total:>4}] run_index={record.run_index:<4} arm={record.arm} "
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
    print(f"[done] {tally.summary()}; store={args.store}", flush=True)


if __name__ == "__main__":
    main()
