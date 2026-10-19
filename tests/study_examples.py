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
