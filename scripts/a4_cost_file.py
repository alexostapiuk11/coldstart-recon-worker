"""Write data/a4/cost_per_tenant.json for artifact 5 from data/a4/analysis.json.

    .venv/bin/python scripts/a4_cost_file.py [--analysis data/a4/analysis.json] \\
        [--out data/a4/cost_per_tenant.json]
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from placement.cost_file import build


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--analysis", default="data/a4/analysis.json")
    ap.add_argument("--out", default="data/a4/cost_per_tenant.json")
    args = ap.parse_args(argv)
    result = build(json.loads(Path(args.analysis).read_text()))
    Path(args.out).write_text(json.dumps(result, indent=1) + "\n")
    ref = next(r for r in result["rows"] if r["regime"] == result["reference"]["regime"]
               and r["s"] == result["reference"]["s"])
    print(f"wrote {args.out}: reference {result['reference']}: dedicated "
          f"${ref['dedicated_cost_per_tenant_month']:.2f}, swapped "
          f"${ref['swapped_cost_per_tenant_month']:.2f} per tenant per month")
    return result


if __name__ == "__main__":
    main()
