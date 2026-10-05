"""Prime artifact 5's compile caches: two untimed starts per sweep point
(amendment §3d). Runs once, before the campaign, and is never data.

    set -a; . ./.env; set +a
    .venv/bin/python scripts/a5_prime.py            # the live endpoint
    .venv/bin/python scripts/a5_prime.py --stub     # a GPU-free rehearsal

Writes data/a5/priming.jsonl and exits non-zero unless every sweep point's
second start read warm.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.store import JsonlStore
from multilora.campaign import priming_payloads, priming_verdict
from multilora.cli import submitter_for
from multilora.prereg_values import PREREG
from multilora.records import InstanceRecord, build_record

DATA = Path(__file__).resolve().parents[1] / "data" / "a5"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stub", action="store_true")
    ap.add_argument("--store-dir")
    args = ap.parse_args()
    store_dir = Path(args.store_dir or (DATA.parent.parent / "build" / "a5-rehearsal" if args.stub else DATA))
    store = JsonlStore(store_dir / "priming.jsonl", InstanceRecord)
    if store.read_all():
        raise SystemExit(f"{store.path} already holds priming runs; priming runs once")
    submitter = submitter_for(stub=args.stub)
    for scheduled, payload in priming_payloads(PREREG):
        record = build_record(scheduled, payload["run_id"], submitter.submit_payload(payload))
        store.append(record)
        print(f"[{record.condition} start {record.block_index}] {record.outcome} "
              f"{record.engine.get('compile_state')}", flush=True)
    verdict = priming_verdict(store.read_all())
    print(json.dumps(verdict, indent=1))
    return 0 if all(v["ok"] for v in verdict.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
