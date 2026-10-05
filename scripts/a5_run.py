"""Run artifact 5's gate or campaign against the live endpoint.

    set -a; . ./.env; set +a
    .venv/bin/python scripts/a5_run.py --which gate
    .venv/bin/python scripts/a5_run.py --which campaign            # refuses unless the gate passed
    .venv/bin/python scripts/a5_run.py --which campaign --resume
    .venv/bin/python scripts/a5_run.py --which topup --conditions sweep-N64 --blocks 3
    .venv/bin/python scripts/a5_run.py --which gate --stub         # GPU-free rehearsal

Stops with exit code 3 after --max-consecutive-failures (default 3) failed
instances in a row; every record is kept. Wait at least 30 s, then --resume.

Refuses to spend unless the endpoint matches multilora/pins.py. Stores go to
data/a5/<which>.jsonl, or build/a5-rehearsal/ with --stub.
"""

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.store import JsonlStore
from multilora.analysis import gate_verdict
from multilora.campaign import run
from multilora.cli import (
    guard_against_silent_restart,
    stop_after_consecutive_failures,
    submitter_for,
)
from multilora.conditions import campaign_schedule, gate_schedule, topup_schedule
from multilora.prereg_values import PREREG
from multilora.records import InstanceRecord

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", choices=("gate", "campaign", "topup"), required=True)
    ap.add_argument("--conditions", nargs="*", default=[], help="topup only")
    ap.add_argument("--blocks", type=int, default=0, help="topup only")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--force-restart", action="store_true")
    ap.add_argument("--stub", action="store_true")
    ap.add_argument("--store-dir")
    ap.add_argument(
        "--max-consecutive-failures", type=int, default=3,
        help="stop (exit code 3) after this many failed instances in a row; records are kept, "
        "and --resume continues after waiting at least 30 s (Amendment 3)",
    )
    args = ap.parse_args()
    stop_on_streak = stop_after_consecutive_failures(args.max_consecutive_failures)
    store_dir = Path(args.store_dir or (REPO / "build" / "a5-rehearsal" if args.stub else REPO / "data" / "a5"))
    store = JsonlStore(store_dir / f"{args.which}.jsonl", InstanceRecord)
    guard_against_silent_restart(
        len(store.read_all()), store.path, resume=args.resume, force=args.force_restart
    )
    if args.which in ("campaign", "topup"):
        verdict = gate_verdict(JsonlStore(store_dir / "gate.jsonl", InstanceRecord).read_all(), PREREG)
        if verdict["verdict"] != "pass":
            raise SystemExit(
                f"the equivalence gate reads {verdict['verdict']!r}; the campaign runs only after "
                "it passes (August §8). See the amendment's §4 for what fail and inconclusive mean."
            )
    if args.which == "gate":
        schedule = gate_schedule(PREREG)
    elif args.which == "campaign":
        schedule = campaign_schedule(PREREG)
    else:
        schedule = topup_schedule(PREREG, args.conditions, args.blocks)
    tally = Counter()
    started = time.monotonic()

    def progress(record):
        tally[record.outcome] += 1
        state = record.engine.get("compile_state", "-")
        print(f"[{sum(tally.values()):>4}/{len(schedule)}] run_index={record.run_index:<4} "
              f"{record.condition:<11} {record.outcome:<6} {state:<7} "
              f"{record.failure_class or ''} elapsed={(time.monotonic() - started) / 60:.1f}m",
              flush=True)
        stop_on_streak(record)

    run(schedule, submitter_for(stub=args.stub), store, PREREG, resume=args.resume, on_run=progress)
    print(f"[done] {dict(tally)} store={store.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
