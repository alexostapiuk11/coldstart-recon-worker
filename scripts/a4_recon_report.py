"""Compute artifact 4's reconnaissance answers from the saved captures.

    .venv/bin/python scripts/a4_recon_report.py [--captures fixtures/a4/recon]

Writes fixtures/a4/recon-report.json and prints the answers as markdown, the
raw material for docs/recon-a4.md. Spends nothing.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from placement_measure.recon_report import render, report


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--captures", default="fixtures/a4/recon")
    ap.add_argument("--out", default="fixtures/a4/recon-report.json")
    args = ap.parse_args(argv)
    paths = sorted(Path(args.captures).glob("*.json"))
    if not paths:
        raise SystemExit(f"no captures in {args.captures}")
    rep = report([json.loads(p.read_text()) for p in paths])
    Path(args.out).write_text(json.dumps(rep, indent=1))
    print(render(rep))
    return rep


if __name__ == "__main__":
    main()
