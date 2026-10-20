"""Traceability: every number in a unit's text must appear in a source it cites.

A number counts if it has a decimal point or three or more digits (small integers such
as "three arms" are prose), and is not a year. It is traced if the same digits appear in
one of the unit's source files, or if the unit declares it in `derived_numbers` with a
reason. A flow step's `when` and `evidence` (dates, commit shas, notes on commits) are not
numeric claims and are not scanned. Section citations must be exact substrings of their
file.

Evidence commits are checked separately (missing_commits): each must exist in its repo.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from study.schema import ContentError

NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
# Keys whose strings are never numeric claims.
NOT_CLAIMS = ("sources", "derived_numbers", "links", "when", "evidence")


def _normalise(token: str) -> str:
    """Drop thousands commas and trailing zeros, so "0.30" and 0.3 are the same number."""
    t = token.replace(",", "")
    return t.rstrip("0").rstrip(".") if "." in t else t


def _significant(token: str) -> bool:
    t = token.replace(",", "")
    if re.fullmatch(r"(19|20)\d\d", t):
        return False
    return "." in t or len(t) >= 3


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for k, v in node.items():
            if k not in NOT_CLAIMS:
                yield from _strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _strings(v)


def _stacked_bars(ch):
    return [s["value"] for b in ch["bars"] for s in b["segments"]]


def _bars(ch):
    return [i["value"] for i in ch["items"]]


def _interval(ch):
    return [row[k] for row in ch["rows"] for k in ("estimate", "low", "high")]


def _percentiles(ch):
    return ([v["value"] for row in ch["rows"] for v in row["values"]]
            + [row["max_label"]["value"] for row in ch["rows"] if "max_label" in row])


def _refs(ch):
    return [r[k] for r in ch.get("refs", []) for k in ("x", "y") if k in r]


def _xy(ch):
    return ([p[k] for s in ch["series"] for p in s["points"] for k in ("x", "y", "lo", "hi")
             if k in p]
            + [b[k] for b in ch.get("bands", []) for k in ("y_lo", "y_hi")] + _refs(ch))


def _scatter(ch):
    fr = ch.get("frontier", {}).get("points", [])
    return ([p[k] for g in ch["groups"] for p in g["points"] for k in ("x", "y")]
            + [p[k] for p in fr for k in ("x", "y")] + _refs(ch))


# Every chart type's numeric values (they are numbers, not strings, so _strings misses
# them). A new chart type needs an entry here; a test checks this matches CHART_TYPES.
CHART_NUMBERS = {
    "stacked_bars": _stacked_bars,
    "bars": _bars,
    "interval": _interval,
    "percentiles": _percentiles,
    "xy": _xy,
    "scatter": _scatter,
    "matrix": lambda ch: [],  # all text: its labels, subs and cells are scanned as strings
}


def _token(v: float) -> str:
    """A chart value as a number token, never in exponent form: 1234567 -> '1234567'."""
    text = repr(float(v))
    if "e" in text:
        text = f"{float(v):f}"
    return _normalise(text.lstrip("-"))


def _numbers_in(node):
    out = []
    for s in _strings(node):
        out += [_normalise(t) for t in NUMBER.findall(s) if _significant(t)]
    for i, r in enumerate(node.get("results", []) if isinstance(node, dict) else []):
        ch = r["chart"]
        numbers = CHART_NUMBERS.get(ch.get("type"))
        if numbers is None:
            raise ContentError(f"results[{i}].chart: unknown chart type '{ch.get('type')}'; "
                               f"known types are {', '.join(CHART_NUMBERS)}")
        out += [t for t in map(_token, numbers(ch)) if _significant(t)]
    return out


def _read(path: str) -> str:
    return Path(path).expanduser().read_text()


def untraced_numbers(content: dict) -> list[str]:
    known = set()
    for s in content["sources"]:
        known |= {_normalise(t) for t in NUMBER.findall(_read(s["file"]))}
    known |= {_normalise(str(d["value"])) for d in content.get("derived_numbers", [])}
    seen, flagged = set(), []
    for n in _numbers_in(content):
        if n not in known and n not in seen:
            flagged.append(n)
        seen.add(n)
    return flagged


def missing_sections(content: dict) -> list[str]:
    return [f"{s['file']}: {s['section']}" for s in content["sources"]
            if s["section"] not in _read(s["file"])]


def evidence_commits(content: dict) -> list[tuple[str | None, str]]:
    """(repo or None for this repo, sha) for every evidence commit in the flow."""
    return [(e.get("repo"), e["commit"]) for s in content.get("flow", [])
            for e in s.get("evidence", [])]


def missing_commits(content: dict, root: Path) -> tuple[list[str], list[str]]:
    """(missing, unavailable): evidence commits that are not commits in their repo, as
    "<sha> in <repo>", and why some could not be checked (git not on PATH, a repo path
    that does not exist or is not a git repository). A repo defaults to `root`; '~'
    expands to the home directory."""
    if shutil.which("git") is None:
        return [], ["git is not on PATH"]
    missing, unavailable, usable = [], [], {}
    for repo, sha in evidence_commits(content):
        path = Path(repo).expanduser() if repo else Path(root)
        if path not in usable:
            usable[path] = _git_repo(path)
            if usable[path]:
                unavailable.append(f"{path}: {usable[path]}")
        if usable[path]:
            continue
        found = subprocess.run(["git", "-C", str(path), "cat-file", "-e", f"{sha}^{{commit}}"],
                               capture_output=True, check=False).returncode == 0
        if not found:
            missing.append(f"{sha} in {path}")
    return missing, unavailable


def _git_repo(path: Path) -> str:
    """Why `path` cannot be checked, or "" when it is a git repository."""
    if not path.is_dir():
        return "no such directory"
    ok = subprocess.run(["git", "-C", str(path), "rev-parse", "--git-dir"],
                        capture_output=True, check=False).returncode == 0
    return "" if ok else "not a git repository"


def load(unit_dir: Path) -> dict:
    return json.loads((unit_dir / "content.json").read_text())


# Keys of practice.json whose strings are never numeric claims: the declarations
# themselves, a calculator input's id and expression (constants there are unit
# conversions; a price or a rate belongs in an input), the unit id and review targets.
PRACTICE_NOT_CLAIMS = NOT_CLAIMS + ("assumed_numbers", "unit", "expr", "id", "review")


def _practice_strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for k, v in node.items():
            if k not in PRACTICE_NOT_CLAIMS:
                yield from _practice_strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _practice_strings(v)


def untraced_practice_numbers(practice: dict, unit: dict) -> list[str]:
    """Numbers in practice.json's text that no source of the unit holds. A number counts as
    traced (same rules as `untraced_numbers`) if it appears in one of the UNIT's source
    files or derived_numbers, or in the practice file's own `assumed_numbers` (a labelled
    assumption) or `derived_numbers`. A calculator's numeric fields (default, range, step)
    are parameters, not claims, and are not scanned."""
    known = set()
    for s in unit["sources"]:
        known |= {_normalise(t) for t in NUMBER.findall(_read(s["file"]))}
    known |= {_normalise(str(d["value"])) for d in unit.get("derived_numbers", [])}
    known |= {_normalise(str(d["value"])) for d in practice.get("derived_numbers", [])}
    for a in practice.get("assumed_numbers", []):
        known |= {_normalise(t) for t in NUMBER.findall(a["value"])}
    seen, flagged = set(), []
    for s in _practice_strings(practice):
        for token in NUMBER.findall(s):
            n = _normalise(token)
            if _significant(token) and n not in known and n not in seen:
                flagged.append(n)
            seen.add(n)
    return flagged
