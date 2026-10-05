"""Per-condition instance counts, checked before analysis (amendment §4).

    .venv/bin/python scripts/a5_counts.py
    .venv/bin/python scripts/a5_counts.py --store-dir build/a5-rehearsal

Exits 1 and names the conditions below the bootstrap floor of 20 publishable
instances; those are topped up with `scripts/a5_run.py --which topup`.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.store import JsonlStore
from multilora.estimands import publishable_counts
from multilora.prereg_values import PREREG
from multilora.records import InstanceRecord

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store-dir", default=str(REPO / "data" / "a5"))
    args = ap.parse_args()
    d = Path(args.store_dir)
    records = []
    for name in ("gate", "campaign", "topup"):
        records += JsonlStore(d / f"{name}.jsonl", InstanceRecord).read_all()
    counts = publishable_counts(records, PREREG)
    for condition, c in sorted(counts.items()):
        mark = "ok " if c["meets_floor"] else "LOW"
        print(f"[{mark}] {condition:<11} publishable={c['publishable']:>3} "
              f"discarded={c['discarded']:>3} failed={c['failed']:>3}")
    low = [k for k, c in counts.items() if not c["meets_floor"]]
    if low:
        print(f"below the floor: {' '.join(sorted(low))}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
