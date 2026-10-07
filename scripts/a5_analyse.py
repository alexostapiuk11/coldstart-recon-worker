"""Assemble artifact 5's analysis from the stores.

    .venv/bin/python scripts/a5_analyse.py --require-a4     # for publication
    .venv/bin/python scripts/a5_analyse.py --store-dir build/a5-rehearsal --out build/a5-rehearsal/analysis.json

Writes data/a5/analysis.json by default. Deterministic: fixed bootstrap
iterations and seed, sorted keys, so a re-run on the same stores is byte-identical.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.store import JsonlStore
from multilora.analysis import analyse
from multilora.prereg_values import PREREG
from multilora.records import InstanceRecord

REPO = Path(__file__).resolve().parents[1]
ITERATIONS = 10000
SEED = 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store-dir", default=str(REPO / "data" / "a5"))
    ap.add_argument("--a4", default=str(REPO / "data" / "a4" / "cost_per_tenant.json"))
    ap.add_argument("--require-a4", action="store_true")
    ap.add_argument("--out")
    args = ap.parse_args()
    store_dir = Path(args.store_dir)
    a4_path = Path(args.a4)
    if args.require_a4 and not a4_path.exists():
        raise SystemExit(f"{a4_path} does not exist; artifact 4's results are required to publish")
    a4 = json.loads(a4_path.read_text()) if a4_path.exists() else None
    campaign = JsonlStore(store_dir / "campaign.jsonl", InstanceRecord).read_all()
    topup = JsonlStore(store_dir / "topup.jsonl", InstanceRecord).read_all()
    if topup:
        print(f"[note] including {len(topup)} top-up instances; the post must disclose them")
    result = analyse(
        campaign + topup,
        JsonlStore(store_dir / "gate.jsonl", InstanceRecord).read_all(),
        PREREG, a4=a4, iterations=ITERATIONS, seed=SEED,
    )
    out = Path(args.out or store_dir / "analysis.json")
    result["topup_instances"] = len(topup)
    out.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    print(f"[ok] {out}: gate {result['gate']['verdict']}, "
          f"tenants {result['tenants'].get('tenants')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
