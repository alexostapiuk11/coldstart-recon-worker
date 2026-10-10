"""The confidentiality guard (amendment §6).

The author builds an agent platform at their employer. Nothing here may
resemble the employer's domain, and insurance or claims workflows are excluded
outright. This scans every string in every scenario and tool-library file for
that vocabulary: the string values, and the dict keys too, since a tool called
`file_claim` or a field called `policy_number` says as much as a sentence does.

The one exception is a field name of this repository's own formats
(`success_claim_pattern`, in SCHEMA_KEYS): the key is skipped, its value is not.

Matching is done on normalised text. camelCase is split, then every run of
punctuation, underscores, hyphens and whitespace becomes one space, and the text
is lower-cased, so `policyNumber`, `policy_number`, `policy-number` and
`policy\\n number` all read "policy number". The patterns are stems (`claim\\w*`,
`(re|un|under|co)?insur\\w*`) so inflections are caught: claimed, uninsured,
reinsurance. `\\b` still stops a stem at a word start, so exclaim and disclaimer
are not hits. Bare "adjust" and "adjusted" are not in the vocabulary; "adjuster"
and "adjustor" are.

A file with a hit must be listed in the sign-off file or
tests/test_toolcall_confidentiality.py fails. The scan cannot read intent; the
pre-publish gate's non-negotiable item still applies.

The sign-off file (toolcall/data/confidentiality_signoff.json, plan 1 Task 16):

    {"files": {"tools/travel.json": {
        "signed_off": "2026-10-08",
        "note": "premium is a cabin class here, not a price",
        "sha256": "<hash of the file's bytes>",
        "hits": ["premium"]}}}

A sign-off is pinned to the bytes the author read. It counts only while the
file's sha256 matches, and only for the hits listed: edit the file, or grow the
vocabulary so a new word hits, and the file is unsigned again until the author
re-reads it. `signed_off` is a real ISO date (YYYY-MM-DD) and `note` is not
empty. A sign-off entry that fails these checks, or a file that is not this
shape, raises ValueError rather than being read as "nothing signed".

To get an entry's hash and hits, run

    .venv/bin/python -m toolcall.confidentiality [--root DIR] path/to/file.json

and paste its output into the sign-off file (the key is the path relative to --root,
default toolcall/data, e.g. tools/travel.json), filling `signed_off` and `note`
after reading the file. The template's placeholder date is not a valid date,
so an unfilled entry is refused.
"""

import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

VOCABULARY = (
    r"\b(?:re|un|under|co)?insur\w*",
    r"\bpolicy ?holder\w*",
    r"\bunderwrit\w*",
    r"\bpremiums?\b",
    r"\bdeductibles?\b",
    r"\badjust(?:er|or)s?\b",
    r"\badjudicat\w*",
    r"\bclaim\w*",
    r"\bfnol\b",
    r"\bfirst notice of loss\b",
    r"\bcoverages?\b",
    r"\bbeneficiar(?:y|ies)\b",
    r"\bactuar\w*",
    r"\bindemn\w*",
    r"\bsubrogat\w*",
    r"\bloss ratio\b",
    r"\bpolicy ?numbers?\b",
)
DEFAULT_ROOT = Path(__file__).resolve().parent / "data"  # where the sign-off file lives
_PATTERNS = [re.compile(p) for p in VOCABULARY]
# Field names of this repository's own file formats. They are the schema, not
# the author's content, so the key is not scanned; its value still is.
SCHEMA_KEYS = frozenset({"success_claim_pattern"})
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


def normalise(text: str) -> str:
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    return re.sub(r"[\W_]+", " ", text).lower()


def _strings(x):
    """Every string value and every dict key, at any depth."""
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for k, v in x.items():
            if k not in SCHEMA_KEYS:
                yield str(k)
            yield from _strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from _strings(v)


def hits(path: Path) -> list[str]:
    found = set()
    for s in _strings(json.loads(Path(path).read_text())):
        text = normalise(s)
        for p in _PATTERNS:
            for m in p.finditer(text):
                found.add(m.group(0))
    return sorted(found)


def file_sha256(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def scan(root, skip=None) -> dict[str, list[str]]:
    """Hits per file under `root` (posix relative paths). `skip`: the sign-off
    file's path, compared as a path, not by its name at some depth."""
    root = Path(root)
    skip = Path(skip).resolve() if skip is not None else None
    return {
        p.relative_to(root).as_posix(): h
        for p in sorted(root.rglob("*.json"))
        if (skip is None or p.resolve() != skip) and (h := hits(p))
    }


def _bad(where: str, why: str) -> ValueError:
    return ValueError(f"confidentiality sign-off {where}: {why}")


def _load_signoff(signoff_path) -> dict[str, dict]:
    path = Path(signoff_path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except ValueError as e:
        raise _bad(str(path), f"not valid JSON ({e})") from e
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        raise _bad(str(path), 'expected an object with a "files" object')
    for name, entry in data["files"].items():
        where = f"{path.name}, {name!r}"
        if not isinstance(entry, dict):
            raise _bad(where, "the entry must be an object")
        signed = entry.get("signed_off")
        if not isinstance(signed, str) or not _DATE.fullmatch(signed):
            raise _bad(where, f"signed_off must be a YYYY-MM-DD date, got {signed!r}")
        try:
            date.fromisoformat(signed)
        except ValueError:
            raise _bad(where, f"signed_off {signed!r} is not a real date") from None
        note = entry.get("note")
        if not isinstance(note, str) or not note.strip():
            raise _bad(where, "note must say what the author checked, not be empty")
        sha = entry.get("sha256")
        if not isinstance(sha, str) or not _SHA256.fullmatch(sha):
            raise _bad(where, "sha256 must be the file's 64-character hex digest "
                              "(python -m toolcall.confidentiality FILE prints it)")
        reviewed = entry.get("hits")
        if not isinstance(reviewed, list) or not all(isinstance(h, str) for h in reviewed):
            raise _bad(where, "hits must be the list of hits the author reviewed")
    return data["files"]


def unsigned(root, signoff_path) -> dict[str, list[str]]:
    """Files with hits that no valid sign-off covers: no entry, a hash that no
    longer matches the file, or a hit the author did not review."""
    root = Path(root)
    signoff = _load_signoff(signoff_path)
    out = {}
    for name, found in scan(root, skip=signoff_path).items():
        entry = signoff.get(name)
        covered = (entry is not None and entry["sha256"] == file_sha256(root / name)
                   and set(found) <= set(entry["hits"]))
        if not covered:
            out[name] = found
    return out


def main(argv=None) -> int:
    """Print a sign-off entry template (hash and hits) for each file given. Keys
    are paths relative to --root (default: toolcall/data), in posix form, which
    is how the sign-off file and `scan` name files."""
    ap = argparse.ArgumentParser(prog="python -m toolcall.confidentiality")
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT,
                    help="the directory the sign-off keys are relative to")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    root = args.root.resolve()
    entries = {}
    for f in args.files:
        try:
            key = f.resolve().relative_to(root).as_posix()
        except ValueError:
            print(f"{f} is outside the root {root}; a sign-off key must be relative to it "
                  "(pass --root)", file=sys.stderr)
            return 2
        entries[key] = {"signed_off": "YYYY-MM-DD", "note": "", "sha256": file_sha256(f),
                        "hits": hits(f)}
    print(json.dumps(entries, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
