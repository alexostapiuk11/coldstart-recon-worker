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


def sequence_view(level: str = "dynamic") -> dict:
    """A `sequence` view: one consumer applies a payment, is killed before it records its
    Kafka progress, and applies the redelivered payment again 4.4 s later. Every step
    kind (message, reply, note, crash, fault, gap) and mark (duplicate, never_sent)."""
    return copy.deepcopy({
        "level": level, "style": "sequence",
        "title": "A crash between the two commits",
        "caption": "The ledger commit lands, the Kafka commit never does, so the batch "
                   "comes back.",
        "participants": [
            {"id": "kafka", "label": "Kafka partition 1", "kind": "system"},
            {"id": "grp", "label": "Group coordinator", "kind": "system"},
            {"id": "cons", "label": "consumer-A", "sub": "stack N", "kind": "focus"},
            {"id": "ldb", "label": "ledger-db", "kind": "store"},
            {"id": "orch", "label": "Orchestrator", "sub": "injects faults",
             "kind": "external"},
        ],
        "steps": [
            {"from": "kafka", "to": "cons", "label": "poll returns (1, 646)",
             "text": "payment p00004001"},
            {"from": "cons", "to": "ldb", "label": "BEGIN, apply, COMMIT",
             "text": "db_txid 1898860"},
            {"from": "ldb", "to": "cons", "kind": "reply", "label": "committed"},
            {"from": "cons", "kind": "note", "label": "ledger committed, Kafka progress not"},
            {"from": "orch", "to": "cons", "kind": "fault", "label": "SIGKILL"},
            {"from": "cons", "kind": "crash", "label": "killed before commitSync"},
            {"from": "cons", "to": "grp", "label": "commitSync({1: 647})",
             "mark": "never_sent"},
            {"kind": "gap", "label": "4.4 s later"},
            {"from": "orch", "to": "cons", "label": "docker start"},
            {"from": "cons", "to": "cons", "label": "rejoin as generation 2"},
            {"from": "kafka", "to": "cons", "label": "poll redelivers (1, 646)",
             "mark": "duplicate"},
            {"from": "cons", "to": "ldb", "label": "COMMIT again", "text": "db_txid 1899467",
             "mark": "duplicate", "badge": "applied twice"},
            {"from": "kafka", "to": "ldb", "kind": "note",
             "label": "same (partition, offset) twice: consumer side"},
        ],
    })


def matrix_chart(**extra) -> dict:
    """A `matrix` chart: four stacks by three fault cells, mixing every status and tone;
    one cell has a note, one is empty (status none) and one not applicable."""
    def cell(text, status, tone=None, **more):
        return dict({"text": text, "status": status}, **({"tone": tone} if tone else {}), **more)
    return copy.deepcopy(dict({
        "type": "matrix", "unit": "trials",
        "rows": [{"label": "N", "sub": "no defense"}, {"label": "K", "sub": "Kafka txns"},
                 {"label": "I", "sub": "key at the sink"}, {"label": "O+I"}],
        "cols": [{"label": "F1", "sub": "broker kill"}, {"label": "F4-con-t", "sub": "hook"},
                 {"label": "F5", "sub": "zombie"}],
        "cells": [
            [cell("10 of 10 duplicated", "observed", "bad"), cell("dup in 8 of 10", "predicted", "bad"),
             cell("", "none")],
            [cell("more dup than N", "predicted", "warn"),
             cell(">= 8/10 dup (H1)", "predicted", "bad", note="output once, ledger twice"),
             cell("dup >= 8/10", "pending", "bad")],
            [cell("0 dup", "predicted", "ok"), cell("0 dup", "observed", "ok"),
             cell("0 dup", "pending", "ok")],
            [cell("no loss", "predicted", "ok"), cell("0 dup", "pending", "neutral"),
             cell("", "n/a")],
        ],
        "legend": [{"status": "predicted", "label": "pre-registered prediction"},
                   {"tone": "bad", "label": "anomaly expected"}],
        "note": "Pre-registered 2026-10-12; results pending.",
    }, **extra))


def walkthrough_block() -> dict:
    """A `walkthrough` for artifact_unit(): a tiny order book, five steps over four
    registers. Step 1 sets every register; step 3 fills against the best bid; step 5
    restates a value that has not changed (so it must not be highlighted). Step 4 names
    decision d1 (a decision id artifact_unit() and artifact_unit_with_links() both have)."""
    return copy.deepcopy({
        "title": "A limit order meets the book",
        "lead": "Watch the best bid, the best ask and the last fill change as three orders arrive.",
        "registers": [
            {"id": "bid", "label": "Best bid"},
            {"id": "ask", "label": "Best ask"},
            {"id": "orders", "label": "Resting orders"},
            {"id": "fill", "label": "Last fill"},
        ],
        "steps": [
            {"say": "The book holds a buy at 99 and a sell at 101. Nothing has traded yet.",
             "values": {"bid": "99 x 5", "ask": "101 x 4", "orders": "2", "fill": "none"}},
            {"say": "A buy of 3 at 100 arrives. It is below the best ask, so it rests and "
                    "becomes the best bid.",
             "values": {"bid": "100 x 3", "orders": "3"}},
            {"say": "A sell of 2 at 99 crosses the best bid and fills against it.",
             "values": {"bid": "100 x 1", "fill": "2 at 100"}},
            {"say": "A sell of 1 at 100 takes the last of that bid; the older buy is best again.",
             "values": {"bid": "99 x 5", "orders": "2", "fill": "1 at 100"},
             "decision": "d1"},
            {"say": "Nothing else crosses: the book is quiet.",
             "values": {"orders": "2"}},
        ],
        "takeaway": "A resting order only changes the book; a crossing order changes the book "
                    "and the fill.",
    })


def artifact_unit_with_walkthrough() -> dict:
    u = artifact_unit()
    u["walkthrough"] = walkthrough_block()
    return u
