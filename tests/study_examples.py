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


def artifact_unit_with_flow() -> dict:
    """artifact_unit_with_links() with a phased flow: 8 steps in 3 phases, 3 milestones,
    evidence commits (invented shas, one in another repo) and two steps tied to decisions.
    The text is as long as real content is, so the fixture page shows real wrapping."""
    u = artifact_unit_with_links()
    u["flow"] = [
        {"phase": "Design", "label": "Capture real responses, then build offline",
         "detail": "Saved engine logs and provider responses from one cheap trial run become "
                   "test inputs; the harness is built against them and a free fake engine.",
         "output": "a test suite that replays captured logs with no GPU",
         "when": "2026-08-20 to 08-24",
         "evidence": [{"commit": "1a2b3c4", "note": "fixtures from the trial run"}]},
        {"phase": "Design", "label": "Pre-register the hypotheses and rules",
         "detail": "Hypotheses, contrasts, stopping rules and the gate are committed before "
                   "the first paid run.",
         "output": "a frozen pre-registration in docs/experiment.md",
         "milestone": True, "when": "2026-08-28", "decision": "d1",
         "evidence": [{"commit": "5d6e7f8a9b"}]},
        {"phase": "Measure", "label": "Prime arm C in a separate store",
         "detail": "Two priming runs never count; the second must show compile under one "
                   "second.",
         "output": "a warm compile cache, checked before every arm C run",
         "when": "2026-09-01", "decision": "d2"},
        {"phase": "Measure", "label": "Run interleaved triples",
         "detail": "Seeded triples, one job in flight; a change to any pinned setting ends "
                   "the experiment.",
         "output": "a complete store of one JSON line per run",
         "milestone": True, "when": "2026-09-02 to 09-04",
         "evidence": [{"commit": "abcdef0", "note": "store committed"},
                      {"commit": "0fedcba987", "repo": "~/projects/other-repo",
                       "note": "worker image pinned"}]},
        {"phase": "Measure", "label": "Store, never retry",
         "detail": "A failure is its own row: a retry would swap unlucky runs for faster ones.",
         "output": "failure rows kept next to the successes",
         "when": "2026-09-04"},
        {"phase": "Analyse and publish", "label": "Partition, then analyse",
         "detail": "A gate sorts rows into publishable, discarded and failed before any "
                   "statistic; then seeded bootstrap intervals.",
         "output": "intervals computed only from publishable rows",
         "when": "2026-09-06"},
        {"phase": "Analyse and publish", "label": "Draw the figures from the store",
         "detail": "Every figure is a function of the committed store.",
         "output": "figures that rebuild byte for byte",
         "when": "2026-09-08"},
        {"phase": "Analyse and publish", "label": "Publish what re-derives",
         "detail": "The post and its numbers come from the committed store; a re-run "
                   "reproduces the analysis with no GPU.",
         "output": "a published post whose every number re-derives on a laptop",
         "milestone": True, "when": "2026-09-12",
         "evidence": [{"commit": "9f8e7d6c5b4a"}]},
    ]
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


def xy_chart(**extra) -> dict:
    """An `xy` chart: a line through (0, 0), (50, 5), (100, 10) and a points series with
    a whisker on its first point."""
    return copy.deepcopy(dict({
        "type": "xy", "unit": "s", "x_label": "requests in flight", "y_label": "latency",
        "series": [
            {"name": "measured", "points": [{"x": 0, "y": 0}, {"x": 50, "y": 5},
                                            {"x": 100, "y": 10}]},
            {"name": "model", "style": "points",
             "points": [{"x": 0, "y": 1, "lo": 0.5, "hi": 1.5}, {"x": 100, "y": 8}]},
        ],
    }, **extra))


def scatter_chart(**extra) -> dict:
    """A `scatter` chart: queue depth has 19 policies on one spot, the others spread; a
    frontier runs through the best three."""
    return copy.deepcopy(dict({
        "type": "scatter", "unit": "s", "x_label": "replica-seconds", "y_label": "p99",
        "groups": [
            {"name": "queue depth", "points": [{"x": 880, "y": 14.44, "label": "cheapest"}]
             + [{"x": 880, "y": 14.44}] * 18 + [{"x": 880, "y": 15.1}]},
            {"name": "in-flight", "points": [{"x": 2535, "y": 14.48}, {"x": 3095, "y": 15.03}]},
            {"name": "utilisation", "marker": "square",
             "points": [{"x": 3095, "y": 14.53}, {"x": 3095, "y": 15.52}]},
        ],
        "frontier": {"name": "best p99 at each cost",
                     "points": [{"x": 880, "y": 14.44}, {"x": 2535, "y": 14.4}]},
    }, **extra))
