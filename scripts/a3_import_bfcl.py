"""Turn BFCL entries into draft scenarios and tools for an author to finish.

    .venv/bin/python scripts/a3_import_bfcl.py --questions BFCL_v3_simple.json \
        --answers possible_answer/BFCL_v3_simple.json --ids simple_7 simple_12 \
        --commit <gorilla commit> --domain math --out toolcall/data/drafts

Reads BFCL's JSON-lines files from a local checkout of
github.com/ShishirPatil/gorilla at a pinned commit (plan 1 Task 18 records the
commit and its license). Writes one draft scenario per id and one draft tool
file per domain, all marked `"draft": true`, which the loader refuses until an
author finishes them. Omit --answers for the irrelevance category.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from toolcall.bfcl import draft_scenario, draft_tool


def _jsonl(path: Path) -> dict[str, dict]:
    return {d["id"]: d for d in (json.loads(x) for x in path.read_text().splitlines() if x)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", type=Path, required=True)
    ap.add_argument("--answers", type=Path)
    ap.add_argument("--ids", nargs="+", required=True)
    ap.add_argument("--commit", required=True)
    ap.add_argument("--domain", required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    questions = _jsonl(args.questions)
    answers = _jsonl(args.answers) if args.answers else {}
    (args.out / "scenarios").mkdir(parents=True, exist_ok=True)
    (args.out / "tools").mkdir(parents=True, exist_ok=True)
    tools = {}
    for i in args.ids:
        entry = questions[i]
        sc = draft_scenario(entry, answers.get(i), commit=args.commit, domain=args.domain)
        (args.out / "scenarios" / f"{sc['id']}.json").write_text(
            json.dumps(sc, indent=2, ensure_ascii=False) + "\n")
        for fn in entry["function"]:
            t = draft_tool(fn)
            tools[t["name"]] = t
        print(f"[draft] {sc['id']}")
    (args.out / "tools" / f"{args.domain}.json").write_text(json.dumps(
        {"domain": args.domain, "tools": list(tools.values())}, indent=2,
        ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
