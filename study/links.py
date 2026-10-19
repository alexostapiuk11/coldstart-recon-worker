"""The links between requirements, decisions, results and concepts, and their codes.

The cards and the map show the same links under the same codes: a requirement keeps its
own id, decisions are D1, D2, ... and results F1, F2, ... in content order, and concepts
that have an id are C1, C2, ... in content order.
"""

from __future__ import annotations

from study.schema import so_ids


def traced(c: dict) -> bool:
    """A unit opts in to links once any requirement carries an id."""
    return any("id" in r for r in c.get("requirements", []))


def link_index(c: dict) -> dict:
    decisions = c.get("decisions", [])
    results = c.get("results", [])
    concepts = [t for t in c.get("concepts", []) if "id" in t]
    idx = {
        "dec_code": {d["id"]: f"D{i + 1}" for i, d in enumerate(decisions)},
        "res_code": [f"F{i + 1}" for i in range(len(results))],
        "con_code": {t["id"]: f"C{i + 1}" for i, t in enumerate(concepts)},
        "req": {r["id"]: r for r in c.get("requirements", []) if "id" in r},
        "answered_by": {r["id"]: [] for r in c.get("requirements", []) if "id" in r},
        "used_by": {t["id"]: [] for t in concepts},
        "seen_in": {d["id"]: [] for d in decisions},
    }
    for d in decisions:
        for s in d.get("serves", []):
            idx["answered_by"][s["req"]].append(d)
        for u in d.get("uses", []):
            idx["used_by"][u["concept"]].append(d)
    for i, r in enumerate(results):
        for d in so_ids(r):
            idx["seen_in"][d].append(i)
    return idx


def req_label(r: dict) -> str:
    """A requirement's name on its card heading and in the map: its `short`, else its text."""
    return r.get("short") or r["text"]
