"""The confidentiality guard (amendment §6).

The author builds an agent platform at their employer. Nothing here may
resemble the employer's domain, and insurance or claims workflows are excluded
outright. This scans the string values of every scenario and tool-library
file for that vocabulary. A file with a hit must be listed in the sign-off file
with the author's date and a note, or tests/test_toolcall_confidentiality.py
fails. The scan cannot read intent; the pre-publish gate's non-negotiable item
still applies.
"""

import json
import re
from pathlib import Path

VOCABULARY = (
    r"\binsur(e|ed|er|ers|ance|ances)\b",
    r"\bpolicy ?holders?\b",
    r"\bunderwrit\w*",
    r"\bpremiums?\b",
    r"\bdeductibles?\b",
    r"\badjust(er|ers|or|ors)\b",
    r"\badjudicat\w*",
    r"\bclaim(s|ant|ants)?\b",
    r"\bfnol\b",
    r"\bfirst notice of loss\b",
    r"\bcoverages?\b",
    r"\bbeneficiar(y|ies)\b",
    r"\bactuar\w*",
    r"\bindemnit\w*",
    r"\bsubrogat\w*",
    r"\bloss ratio\b",
    r"\bpolicy numbers?\b",
)
_PATTERNS = [re.compile(p, re.IGNORECASE) for p in VOCABULARY]


def _strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for v in x.values():
            yield from _strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from _strings(v)


def hits(path: Path) -> list[str]:
    found = set()
    for s in _strings(json.loads(Path(path).read_text())):
        for p in _PATTERNS:
            for m in p.finditer(s):
                found.add(m.group(0).lower())
    return sorted(found)


def scan(root) -> dict[str, list[str]]:
    root = Path(root)
    return {
        str(p.relative_to(root)): h
        for p in sorted(root.rglob("*.json"))
        if p.name != "confidentiality_signoff.json" and (h := hits(p))
    }


def unsigned(root, signoff_path) -> dict[str, list[str]]:
    signoff = json.loads(Path(signoff_path).read_text()) if Path(signoff_path).exists() else {}
    signed = {
        k for k, v in signoff.get("files", {}).items()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v.get("signed_off", "")) and v.get("note")
    }
    return {k: v for k, v in scan(root).items() if k not in signed}
