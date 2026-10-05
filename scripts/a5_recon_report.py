"""Compute the answers to R1-R9 from fixtures/a5/*.json.

    .venv/bin/python scripts/a5_recon_report.py

Writes fixtures/a5/recon_report.json, which docs/recon-a5.md cites.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from multilora.recon_report import report

DIR = Path(__file__).resolve().parents[1] / "fixtures" / "a5"
SKIP = {"recon_report.json", "real_adapter_candidates.json"}


def main() -> int:
    captures = [json.loads(p.read_text()) for p in sorted(DIR.glob("*.json")) if p.name not in SKIP]
    if not captures:
        raise SystemExit(f"no captures in {DIR}; run scripts/a5_recon_capture.py first")
    answers = report(captures)
    (DIR / "recon_report.json").write_text(json.dumps(answers, indent=1, sort_keys=True))
    print(json.dumps({k: v for k, v in answers.items() if k != "probes"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
