"""Turn BFCL entries into draft scenarios and tools for an author to finish.

    .venv/bin/python scripts/a3_import_bfcl.py --questions BFCL_v3_simple.json \
        --answers possible_answer/BFCL_v3_simple.json --ids simple_7 simple_12 \
        --commit <gorilla commit> --domain math --out toolcall/data/drafts

Reads BFCL's JSON-lines files from a local checkout of
github.com/ShishirPatil/gorilla at a pinned commit (plan 1 Task 18 records the
commit and its license). It reads local files only and downloads nothing.
Writes one draft scenario per id and one draft tool file per domain, all marked
`"draft": true`, which the loader refuses until an author finishes them.

With --answers, every id must have an answer and each entry is drafted as one
expected call. Omit --answers for the irrelevance category: every entry is then
a no-call draft.

Everything is converted in memory first. An entry outside the closed subset
(a tuple parameter, a parallel answer) is reported and skipped. Nothing is
written if a scenario file already exists or a tool of the same name already
holds a different definition in `tools/<domain>.json`; otherwise the new tools
are merged into that file and the scenarios are written.
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from toolcall.bfcl import draft_scenario, draft_tool

DOMAIN = re.compile(r"[a-z0-9_-]+")


def _jsonl(path: Path) -> dict[str, dict]:
    return {d["id"]: d for d in (json.loads(x) for x in path.read_text().splitlines() if x)}


def _merge_tools(existing: dict | None, new: dict[str, dict], domain: str, path: Path) -> dict:
    data = existing or {"domain": domain, "tools": []}
    if data.get("domain") != domain or not isinstance(data.get("tools"), list):
        raise ValueError(f"{path}: not a tool file for domain {domain!r}")
    by_name = {t["name"]: t for t in data["tools"]}
    for name, tool in new.items():
        if name in by_name and by_name[name] != tool:
            raise ValueError(f"{path}: tool {name!r} already has a different definition; "
                             "rename or finish that one first")
        by_name.setdefault(name, tool)
    return {**data, "tools": list(by_name.values())}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", type=Path, required=True)
    ap.add_argument("--answers", type=Path)
    ap.add_argument("--ids", nargs="+", required=True)
    ap.add_argument("--commit", required=True)
    ap.add_argument("--domain", required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    if not DOMAIN.fullmatch(args.domain):
        raise ValueError(f"domain {args.domain!r}: use lower-case letters, digits, '_' and '-'")
    questions = _jsonl(args.questions)
    answers = _jsonl(args.answers) if args.answers else {}
    for i in args.ids:
        if i not in questions:
            raise ValueError(f"id {i!r} is not in {args.questions}")
        if args.answers and i not in answers:
            raise ValueError(f"id {i!r} is not in the answers file {args.answers}")
    scenarios: dict[str, dict] = {}
    tools: dict[str, dict] = {}
    skipped = []
    for i in args.ids:
        entry = questions[i]
        try:
            sc = draft_scenario(entry, answers.get(i), commit=args.commit, domain=args.domain,
                                irrelevance=args.answers is None)
            drafted = {}
            for fn in entry["function"]:
                t = draft_tool(fn)
                if drafted.get(t["name"], t) != t:
                    raise ValueError(f"two different functions are both named {t['name']!r}")
                drafted[t["name"]] = t
        except ValueError as e:
            skipped.append(i)
            print(f"[skip] {i}: {e}")
            continue
        for name, t in drafted.items():
            if tools.get(name, t) != t:
                raise ValueError(f"tool {name!r} has a different definition in {i} than in an "
                                 "earlier entry")
            tools[name] = t
        scenarios[sc["id"]] = sc
        print(f"[draft] {sc['id']}")
    if not scenarios:
        print("nothing to write")
        return 1
    scenario_dir, tool_path = args.out / "scenarios", args.out / "tools" / f"{args.domain}.json"
    for sid in scenarios:
        if (scenario_dir / f"{sid}.json").exists():
            raise ValueError(f"{scenario_dir / f'{sid}.json'} already exists; "
                             "move it or choose another --out")
    existing = json.loads(tool_path.read_text()) if tool_path.exists() else None
    merged = _merge_tools(existing, tools, args.domain, tool_path)
    scenario_dir.mkdir(parents=True, exist_ok=True)
    tool_path.parent.mkdir(parents=True, exist_ok=True)
    for sid, sc in scenarios.items():
        (scenario_dir / f"{sid}.json").write_text(json.dumps(sc, indent=2, ensure_ascii=False)
                                                  + "\n")
    tool_path.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n")
    if skipped:
        print(f"skipped {len(skipped)}: {', '.join(skipped)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
