"""Example study-unit content for the study package's tests.

Not a test module. The facts are invented; only the shape matters.
"""

import copy


def _view(level: str) -> dict:
    return {
        "level": level,
        "title": f"The {level} view",
        "caption": f"What the {level} view shows.",
        "nodes": [
            {"id": "a", "label": "Author", "sub": "runs the study", "kind": "person",
             "col": 0, "row": 0},
            {"id": "b", "label": "Harness", "sub": "schedules and records", "kind": "focus",
             "col": 1, "row": 0},
            {"id": "c", "label": "GPU worker", "kind": "external", "col": 2, "row": 0},
        ],
        "edges": [
            {"from": "a", "to": "b", "label": "starts"},
            {"from": "b", "to": "c", "label": "submits 3 jobs"},
        ],
    }


def artifact_unit() -> dict:
    return copy.deepcopy({
        "id": "x1",
        "kind": "artifact",
        "title": "Example artifact",
        "short_title": "Example Artifact",
        "minutes": 45,
        "question": "Does the example hold?",
        "requirements": [
            {"text": f"Requirement {i}", "why": f"Because {i}."} for i in range(3)
        ],
        "concepts": [{"term": "Term", "plain": "A plain definition."}],
        "views": [_view(lv) for lv in ("context", "container", "component", "dynamic")],
        "decisions": [
            {
                "id": f"d{i}",
                "title": f"Decision {i}",
                "problem": "A problem.",
                "options": ["Option one", "Option two"],
                "chosen": "Option one",
                "why": "A reason.",
                "why_short": "A short reason.",
                "cost": "A cost.",
                "cost_short": "A short cost.",
            }
            for i in range(4)
        ],
        "flow": [{"label": f"Step {i}", "detail": f"Detail {i}."} for i in range(3)],
        "results": [
            {
                "title": "A result",
                "chart": {
                    "type": "stacked_bars",
                    "unit": "s",
                    "bars": [
                        {"label": "A", "segments": [
                            {"name": "load", "value": 40.5}, {"name": "compile", "value": 19.0}]},
                        {"label": "C", "segments": [
                            {"name": "load", "value": 21.3}, {"name": "compile", "value": 0.3}]},
                    ],
                },
                "axis": "Seconds to ready.",
                "read_as": "Shorter is faster.",
                "so": "d0",
            }
        ],
        "interview": {
            "pitch30": "Thirty seconds.",
            "pitch120": "Two minutes.",
            "followups": [{"q": f"Question {i}?", "a": f"Answer {i}."} for i in range(3)],
            "limits": "What it cannot claim.",
        },
        "recall": [{"q": "Why?", "a": "Because."}],
        "sources": [{"file": "docs/post.md", "section": "Where a vLLM cold start actually goes"}],
        "derived_numbers": [],
    })


def artifact_unit_with_links() -> dict:
    """artifact_unit() with requirement ids and every relationship field filled in.

    R3 is served by no decision (it has an unlinked_reason); the second result supports
    no decision (it has a so_none_reason); the first result supports two decisions.
    """
    u = artifact_unit()
    u["requirements"] = [
        {"id": "R1", "short": "Split the start into phases",
         "text": "Split one cold start into named phases.", "why": "So time has a place."},
        {"id": "R2", "short": "Change one thing only",
         "text": "Change exactly one thing between set-ups.", "why": "So a gap has a cause."},
        {"id": "R3", "short": "Re-derive every number",
         "text": "Let anyone re-derive every number on a laptop.", "why": "So it can be checked.",
         "unlinked_reason": "Served by the process: the flow's last step, not a decision."},
    ]
    u["concepts"] = [
        {"id": "arms", "short": "Arms A, B, C", "term": "Arm", "plain": "One set-up under test."},
        {"id": "contrast", "term": "Contrast", "plain": "The difference between two arms."},
    ]
    serves = {"d0": ["R1"], "d1": ["R1", "R2"], "d2": ["R2"], "d3": ["R1"]}
    uses = {"d0": ["arms"], "d2": ["contrast"], "d3": ["arms"]}
    for d in u["decisions"]:
        d["short"] = f"Short {d['id']}"
        d["serves"] = [{"req": r, "because": f"{d['id']} meets {r}."} for r in serves[d["id"]]]
        d["uses"] = [{"concept": k, "because": f"{d['id']} is built on {k}."}
                     for k in uses.get(d["id"], [])]
    r0 = u["results"][0]
    r0.update(so=["d0", "d1"], short="Where the time goes",
              takeaway="Loading weights is most of a cold start.")
    u["results"].append({
        "title": "A side result",
        "chart": {"type": "bars", "unit": "GiB",
                  "items": [{"label": "A", "value": 12.5}, {"label": "B", "value": 12.75}]},
        "axis": "GiB left for the KV cache.",
        "read_as": "About the same.",
        "so_none_reason": "Reported for completeness; no decision rests on it.",
    })
    u["flow"][1]["decision"] = "d2"
    return u


def prereq_unit() -> dict:
    return copy.deepcopy({
        "id": "px",
        "kind": "prereq",
        "title": "Example prerequisite",
        "short_title": "Example Prerequisite",
        "minutes": 20,
        "used_by": ["a1"],
        "concepts": [
            {"term": f"Term {i}", "plain": "Plain.", "analogy": "Like a thing.",
             "why": "It matters."}
            for i in range(3)
        ],
        "views": [dict(_view("concept"), level="concept")],
        "recall": [{"q": "Why?", "a": "Because."}],
        "sources": [{"file": "docs/post.md", "section": "Where a vLLM cold start actually goes"}],
        "derived_numbers": [],
    })
