# Artifact 2 Publication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish artifact 2 as a post that leads with the failed validation and the RunPod load-balancer findings, then reports the simulator's unvalidated answer to the original question beside the exploratory sensitivity check. Every number in the post is computed from committed data, and every figure is guarded against drift.

**Architecture:**
- **Evidence and analysis.** Evidence that exists only in the git-ignored `build/` folder is copied into `data/a2/` first. One analysis script (`scripts/a2_post_analysis.py`) reduces all committed evidence to `data/a2/post-analysis.json`. Every quoted number is formatted once from that file (`autoscale/post_numbers_a2.py`), and a test fails if the post lacks any of them.
- **Figures.** Four new matplotlib figures go in a new module, `autoscale/figures_a2_post.py`. The existing `autoscale/figures.py` stays untouched: its figures are kept, and only the post's figure set changes. They are rendered by `scripts/a2_render_post_figures.py` to `docs/figures/a2/` (desktop plus a 375 px phone variant). A byte-equality test guards them against drift, as artifact 1's are.
- **Isolation and removals.** There is no style-isolation boundary: the figures are static PNG images embedded in Markdown. Nothing visible is removed, since artifact 2 has no published figures yet. The originally planned figures 1–3 (convergence, frontiers, overlay) are *not* published as results. The new "simulator's answer" figure replaces them and is labelled unvalidated on its face.

**Tech Stack:** Python 3.13, matplotlib (Agg), pytest, ruff. Data are gzipped JSON or JSONL under `data/a2/`. The post is Markdown at `docs/post-a2.md`.

---

## Context the engineer needs

Read these before Task 1. They are the source of every claim.

| Read | Why |
|---|---|
| `docs/experiment-a2.md` | The pre-registration and its amendments, especially the five dated 2026-10-04 and 2026-10-05 |
| `docs/findings-a2-validation-host-speed.md` | Exploratory: the first failure was host speed, not `--max-num-seqs` |
| `docs/findings-a2-sensitivity-service-speed.md` | Exploratory: H3 under ±12% service speed |
| `docs/regime-search-a2-measured.md` | How the traffic regime was chosen |
| `docs/runbook-a2-validation.md` | The amended notes at the top: endpoint settings and the load-balancer facts |
| `docs/post.md` | Artifact 1's post: its header comment, byline, repo link, plain Markdown figures, and "Reproducing this" |
| `tests/test_published_figures.py` | Artifact 1's drift guard. Task 11 mirrors it |
| `placement/post_numbers.py`, `tests/test_placement_post_numbers.py` | Artifact 4's "numbers formatted once" pattern. Task 6 mirrors it |
| `harness/figure_guards.py` | `MIN_PHONE_TEXT_PX = 7.5`, `PHONE_WIDTH_PX = 375`, `phone_pt()` |
| `autoscale/figures.py` lines 84–365 | Shared colours, pixel sizes (`PX_*`), `_pt`, `_tidy`, `_note`, `_finish`, `FIG_WIDTH_IN` |

House rules, all of them binding:
- **Running Python:** `PYTHONDONTWRITEBYTECODE=1` on every Python run, `.venv/bin/python`, and `-o addopts=""` for pytest.
- **Lint:** `ruff` only on touched files.
- **Commits:**
  - stage named files only, never `git add -A`;
  - end every commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`;
  - push only when the owner says so, with `git -c pack.threads=1 push origin main` (multithreaded packs corrupted twice on this Mac).
- **Off limits:** never edit `docs/experiment.md`, `worker/probe.py`, or other sessions' files.
- **Secrets:** never print secrets. Read `.env` only by sourcing it, and never print RunPod worker records whole: they carry endpoint secrets.
- **Visual work:** invoke `superpowers:verifying-visual-output` before calling any figure done. Look at the PNG at full size **and** at 375 px.
- **Error messages** name what went wrong **and** the consequence. **Docstrings** say why, including the rejected alternative.

## Owner decisions this plan needs (Task 0 records them)

1. **Permanent slug.** It names the mechanism, not the headline, per the portfolio contract. Proposed: `/experiments/autoscaling-signal-and-cold-start`.
2. **Operational definitions of H1, H2 and H4**, written here *after* the simulator's frontiers were seen. That is disclosed, so they need the owner's sign-off before Task 3 computes them. Proposed:
   - **H1** (in-flight concurrency dominates on the step): on each arm, every frontier point of queue depth and of GPU utilisation is weakly dominated by some in-flight frontier point (cost ≤ and p99 ≤, at least one strictly), on medians. It **holds** only if it holds on both arms.
   - **H2** (utilisation is the worst): at the iso-cost budget, utilisation's reached p99 is the highest of the three signals, on both arms and both shapes. Its mechanism (censoring) is reported descriptively: utilisation's frontier sits at the replica cap.
   - **H4** (ranking stable across shapes, margins shrink on the ramp): on each arm, the order of the three signals by reached p99 at the iso-cost budget is the same for step and ramp (ties within 1 ms count as ties), **and** the ramp's gap is smaller than the step's. It holds only if both conditions hold on both arms.
3. **The figure set:** the four post figures of Tasks 7–10, plus the measured service curve (existing figure 4).
4. **The publication date** in the byline.


### Owner decisions, recorded 2026-10-05 (signed by the owner)

1. **Slug:** `/experiments/autoscaling-signal-and-cold-start`, as proposed.
2. **H1, H2 and H4:** signed off exactly as written above, with the disclosure that
   they were written after the x1.00 frontiers were seen. Task 3 implements them unchanged.
3. **Figures:** the five as proposed: validation attempts, load balancer, host speed, the
   simulator's answer (labelled unvalidated), and the measured service curve.
4. **Date:** the date the post is published. The post carries the placeholder
   `PUBLICATION-DATE` in its byline until the pre-publish gate (Task 15), where the owner sets
   it. Task 14's test accepts the placeholder; Task 15's gate refuses it.

---

## File structure

| File | Responsibility |
|---|---|
| `data/a2/lb-probes/probe-{1..5}/summary.json`, `step-*.jsonl.gz` | Load-balancer probe evidence, copied from `build/` (Task 1) |
| `data/a2/frontier-sweep.json` | The headline policy sweep at x1.00 (Task 1), copied from `build/a2-figures-k05/sweep-cache.json` |
| `data/a2/README-evidence.md` | What each evidence file is, which commit produced it, and the command that recreates it |
| `autoscale/a2_evidence.py` | Pure functions: load-balancer throughput and routing, stall statistics, host-speed table (Task 2) |
| `autoscale/hypotheses.py` | H1, H2 and H4 as signed in Task 0, with reached p99 at budget (Task 3) |
| `scripts/a2_post_analysis.py` | Writes `data/a2/post-analysis.json` from committed evidence only (Task 5) |
| `autoscale/post_numbers_a2.py` | Every quoted number, formatted once (Task 6) |
| `autoscale/figures_a2_post.py` | The four post figures (Tasks 7–10) |
| `scripts/a2_render_post_figures.py` | Renders the figures and their phone variants into `docs/figures/a2/` (Task 11) |
| `autoscale/money_a2.py` | Cost in dollars, with published assumptions (Task 12) |
| `docs/spend-a2.md` | Artifact 2's actual spend (Task 13) |
| `docs/post-a2.md` | The post (Task 14) |
| `scripts/preview_post_a2.py` | Writes a local HTML preview of the post (Task 17) |
| `tests/test_a2_evidence.py`, `test_hypotheses.py`, `test_a2_post_analysis.py`, `test_a2_post_numbers.py`, `test_a2_post_figures.py`, `test_a2_published_figures.py`, `test_money_a2.py`, `test_a2_post.py` | The tests for each of the above |

There is no replacement or removal of code in this plan. `autoscale/figures.py`, the render script and their tests are not modified. Replacement and removal rules 1–4 therefore have nothing to inventory: the parity audit is empty by construction. Task 0 records the one visible change, which figures the post publishes, as an owner decision.

---

### Task 0: Record the owner's decisions

**Files:**
- Modify: `docs/superpowers/plans/2026-10-05-artifact-2-publication.md` (this file, "Owner decisions" section)

- [ ] **Step 1: Ask the owner the four questions above.** For the H1, H2 and H4 definitions, show them verbatim, and say they were written after the x1.00 frontiers were seen (the sensitivity check's output printed them).
- [ ] **Step 2: Write the answers under "Owner decisions"**, each with the date and "signed by the owner".
- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/plans/2026-10-05-artifact-2-publication.md
git commit -m "plan: artifact 2 publication, owner decisions recorded (slug, H1/H2/H4 definitions, figures, date)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 1: Preserve the evidence that lives only in `build/`

**Files:**
- Create: `data/a2/lb-probes/probe-{1,2,3,4,5}/summary.json` and `step-<rate>.jsonl.gz`
- Create: `data/a2/frontier-sweep.json`
- Create: `data/a2/README-evidence.md`
- Test: `tests/test_a2_evidence_files.py`

The probe directories are `build/a2-lb-probe` (probe 1: scaler value 4, 2 workers) and `build/a2-lb-probe-2` through `build/a2-lb-probe-5`:

| Probe | Endpoint and settings | Driver |
|---|---|---|
| 2 | scaler 128, 2 workers | no retry |
| 3 | scaler 128, 2 workers | 502 retry |
| 4 | scaler 512, 1 worker, old endpoint | |
| 5 | scaler 512, 1 worker, new endpoint, new image | |

- [ ] **Step 1: Write the failing test**

```python
"""The load-balancer and frontier evidence the post cites is committed, not only in build/."""

import gzip
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROBES = REPO / "data" / "a2" / "lb-probes"


def test_every_probe_has_a_summary_and_its_steps():
    for n in range(1, 6):
        d = PROBES / f"probe-{n}"
        summary = json.loads((d / "summary.json").read_text())
        assert summary["steps"], n
        for rate in summary["steps"]:
            rows = gzip.open(d / f"step-{rate}.jsonl.gz", "rt").read().splitlines()
            assert len(rows) == summary["steps"][rate]["requests"], (n, rate)


def test_probe_1_shows_the_17_per_second_ceiling():
    s = json.loads((PROBES / "probe-1" / "summary.json").read_text())
    assert set(s["steps"]) >= {"25", "50", "100"} and s["status"].startswith("stopped")


def test_the_frontier_sweep_is_the_headline_x1_sweep():
    raw = json.loads((REPO / "data" / "a2" / "frontier-sweep.json").read_text())
    assert raw["identity"]["additional_replicas"] == 0.5
    assert set(raw["gaps"]) == {"arm A", "arm C", "ramp arm A", "ramp arm C"}
    assert round(raw["gaps"]["arm C"]["point"], 4) == 3.955
```

- [ ] **Step 2: Run it and see it fail** (`FileNotFoundError`)

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" -q tests/test_a2_evidence_files.py`

- [ ] **Step 3: Copy the evidence**

```bash
for pair in "a2-lb-probe:1" "a2-lb-probe-2:2" "a2-lb-probe-3:3" "a2-lb-probe-4:4" "a2-lb-probe-5:5"; do
  src="build/${pair%%:*}"; dst="data/a2/lb-probes/probe-${pair##*:}"
  mkdir -p "$dst" && cp "$src/summary.json" "$dst/" && \
  for f in "$src"/step-*.jsonl; do gzip -9 -c "$f" > "$dst/$(basename "$f").gz"; done
done
cp build/a2-figures-k05/sweep-cache.json data/a2/frontier-sweep.json
du -sh data/a2/lb-probes data/a2/frontier-sweep.json
```

Expected: about 6 MB for the probes and 1 MB for the sweep.

- [ ] **Step 4: Write `data/a2/README-evidence.md`.** For each file, give what it is, the date, the commit of the code that produced it, the endpoint settings, and the command that recreates it:
  - probes: `scripts/a2_lb_probe.py --out …`;
  - sweep: `scripts/a2_render_figures.py --out build/a2-figures-k05`.

  It must state that the probes are evidence for the post's load-balancer findings, not pre-registered measurements.

- [ ] **Step 5: Run the test and see it pass.** Then commit:

```bash
git add data/a2/lb-probes data/a2/frontier-sweep.json data/a2/README-evidence.md tests/test_a2_evidence_files.py
git commit -m "data: the five load-balancer probes and the headline frontier sweep, copied out of build/ so the post's evidence is committed

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Derive the load-balancer, stall and host-speed numbers

**Files:**
- Create: `autoscale/a2_evidence.py`
- Test: `tests/test_a2_evidence.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Derived evidence: load-balancer throughput and routing, stalls, host speed."""

import pytest

from autoscale import a2_evidence as ev


def _row(i, sent, latency, worker="w1", server_ms="300", status=200):
    return {"index": i, "scheduled": sent, "sent": sent, "latency": latency, "status": status,
            "headers": {"x-a2-worker": worker, "x-a2-server-latency-ms": server_ms}}


def test_delivered_rate_counts_completions_over_their_span():
    rows = [_row(i, i * 0.1, 0.5) for i in range(11)]  # completions 0.5 .. 1.5 s
    assert ev.delivered_rate(rows) == pytest.approx(11 / 1.0)


def test_per_worker_concurrency_reconstructs_server_side_occupancy():
    # two overlapping requests on w1, one on w2; server interval ends return_leg_s before
    # the client saw the response and lasts the server latency
    rows = [_row(0, 0.0, 1.1, "w1", "1000"), _row(1, 0.2, 1.1, "w1", "1000"),
            _row(2, 0.0, 1.1, "w2", "1000")]
    got = ev.per_worker_concurrency(rows, return_leg_s=0.1)
    assert got["w1"]["max"] == 2 and got["w2"]["max"] == 1
    assert got["w1"]["requests"] == 2


def test_stall_share_is_the_fraction_of_requests_slower_than_two_seconds():
    record = {"client_latency_s": [0.5, 2.5, 3.0, None, 0.4], "status": [200] * 5}
    assert ev.stall_share(record, threshold_s=2.0) == pytest.approx(2 / 4)


def test_host_speed_table_divides_each_hosts_medians_by_the_curve():
    curve = {32: 0.4, 64: 0.5, 128: 0.6}
    runs = [{"level": 64, "latency_s": 0.45, "outcome": "ok", "host": {"host_id": "h"}},
            {"level": 64, "latency_s": 0.47, "outcome": "ok", "host": {"host_id": "h"}},
            {"level": 64, "latency_s": 0.49, "outcome": "ok", "host": {"host_id": "h"}}]
    table = ev.host_speed_table(runs, curve)
    assert table["h"][64]["ratio"] == pytest.approx(0.47 / 0.5)
    assert table["h"][64]["n"] == 3
```

- [ ] **Step 2: Run them and see them fail** (`ImportError`)

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" -q tests/test_a2_evidence.py`

- [ ] **Step 3: Implement `autoscale/a2_evidence.py`**

```python
"""Numbers the post derives from committed load-balancer, validation and host evidence.

Pure functions over the records' plain dicts, so the post analysis
(scripts/a2_post_analysis.py) and its tests share one implementation. Nothing
here is pre-registered: these are the evidence behind the post's findings
about RunPod's load balancer and host speed, and the post says so.
"""

import statistics
from collections import defaultdict

__all__ = ["delivered_rate", "host_speed_table", "per_worker_concurrency", "stall_share"]

WORKER = "x-a2-worker"
SERVER_LATENCY = "x-a2-server-latency-ms"


def delivered_rate(rows) -> float:
    """Completions per second over the span of completion times, 200s only.

    Completions, not sends: the first probe offered 25-100 req/s and the path
    delivered ~17/s, which a send count would hide.
    """
    done = sorted(r["sent"] + r["latency"] for r in rows
                  if r.get("status") == 200 and r.get("latency") is not None)
    if len(done) < 2:
        raise ValueError("fewer than two completions; a rate needs a span")
    return len(done) / (done[-1] - done[0])


def per_worker_concurrency(rows, *, return_leg_s: float) -> dict:
    """Mean and peak requests in flight on each worker, server-side.

    The probes ran before the engine stamped its arrival time, so each server
    interval is reconstructed: it ends `return_leg_s` before the client saw
    the response (about half the ~0.2 s unloaded load-balancer overhead) and
    lasts the stamped server latency. The approximation shifts intervals by a
    fraction of a second and is disclosed with every number it produces.
    Rejected: client-side intervals, which include the load balancer's own
    time and so overstate what a worker held.
    """
    per: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for r in rows:
        h = r.get("headers") or {}
        if r.get("status") != 200 or WORKER not in h or SERVER_LATENCY not in h:
            continue
        server = float(h[SERVER_LATENCY]) / 1000.0
        end = r["sent"] + r["latency"] - return_leg_s
        per[h[WORKER]].append((end - server, end))
    out = {}
    for worker, intervals in per.items():
        events = sorted([(a, 1) for a, _ in intervals] + [(b, -1) for _, b in intervals])
        level = peak = 0
        area, last = 0.0, events[0][0]
        for t, d in events:
            area += level * (t - last)
            last = t
            level += d
            peak = max(peak, level)
        span = events[-1][0] - events[0][0]
        out[worker] = {"requests": len(intervals), "max": peak,
                       "mean": area / span if span > 0 else 0.0}
    return out


def stall_share(record, *, threshold_s: float) -> float:
    """Fraction of completed requests whose client latency exceeded `threshold_s`."""
    lat = [x for x, st in zip(record["client_latency_s"], record["status"], strict=True)
           if x is not None and st == 200]
    if not lat:
        raise ValueError("no completed requests; a share of nothing is not zero")
    return sum(1 for x in lat if x > threshold_s) / len(lat)


def host_speed_table(runs, curve_latency: dict) -> dict:
    """Per host and level: median latency of the ok runs, run count, ratio to the curve."""
    by: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in runs:
        if r.get("outcome") == "ok":
            by[r["host"]["host_id"]][int(r["level"])].append(r["latency_s"])
    return {host: {level: {"median_s": statistics.median(v), "n": len(v),
                           "ratio": statistics.median(v) / curve_latency[level]}
                   for level, v in sorted(levels.items())}
            for host, levels in by.items()}
```

- [ ] **Step 4: Run the tests and see them pass.** Run ruff on the two files.
- [ ] **Step 5: Commit**

```bash
git add autoscale/a2_evidence.py tests/test_a2_evidence.py
git commit -m "evidence: load-balancer throughput and routing, stall share and host speed, derived once for the post

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: H1, H2 and H4 as the owner signed them

**Files:**
- Create: `autoscale/hypotheses.py`
- Test: `tests/test_hypotheses.py`

Precondition: Task 0 has recorded the owner's sign-off on the definitions. If the owner changed them, implement the signed text instead and record the change in the docstring.

- [ ] **Step 1: Write the failing tests**

```python
"""H1, H2 and H4 on frontiers, as defined in the publication plan's Task 0."""

from autoscale.frontier import PolicyPoint, gap_at_iso_cost, iso_cost_budget, pareto_frontier
from autoscale.hypotheses import h1_holds_on, h2_worst_on, h4_holds_on, reached_p99


def _pp(signal, cost, p99, up=1.0):
    return PolicyPoint(cost_samples=(cost,) * 3, p99_samples=(p99,) * 3, signal=signal,
                       scale_up_at=up, scale_down_at=0.0, rep_indices=(0, 1, 2))


def _fr(points):
    by = {}
    for p in points:
        by.setdefault(p.signal, []).append(p)
    return {s: pareto_frontier(v) for s, v in by.items()}


def test_reached_p99_is_the_gaps_own_slice():
    fr = _fr([_pp("queue_depth", 10, 5.0), _pp("in_flight_concurrency", 20, 3.0),
              _pp("utilization", 30, 4.0)])
    budget = iso_cost_budget(fr)
    r = reached_p99(fr, budget)
    assert max(r.values()) - min(r.values()) == gap_at_iso_cost(fr, cost=budget)


def test_h1_needs_every_other_frontier_point_dominated():
    dominant = _fr([_pp("in_flight_concurrency", 10, 2.0), _pp("queue_depth", 12, 3.0),
                    _pp("utilization", 30, 2.0)])
    assert h1_holds_on(dominant) is True
    cheaper_queue = _fr([_pp("in_flight_concurrency", 10, 2.0), _pp("queue_depth", 5, 3.0),
                         _pp("utilization", 30, 2.0)])
    assert h1_holds_on(cheaper_queue) is False


def test_h2_is_utilisation_strictly_worst_at_the_budget():
    fr = _fr([_pp("queue_depth", 10, 3.0), _pp("in_flight_concurrency", 10, 2.0),
              _pp("utilization", 10, 4.0)])
    assert h2_worst_on(fr) is True
    fr = _fr([_pp("queue_depth", 10, 5.0), _pp("in_flight_concurrency", 10, 2.0),
              _pp("utilization", 10, 4.0)])
    assert h2_worst_on(fr) is False


def test_h4_needs_the_same_ranking_and_a_smaller_ramp_gap():
    step = _fr([_pp("queue_depth", 10, 5.0), _pp("in_flight_concurrency", 10, 2.0),
                _pp("utilization", 10, 3.0)])
    ramp_same = _fr([_pp("queue_depth", 10, 4.0), _pp("in_flight_concurrency", 10, 2.0),
                     _pp("utilization", 10, 3.0)])
    assert h4_holds_on(step, ramp_same) is True
    ramp_wider = _fr([_pp("queue_depth", 10, 9.0), _pp("in_flight_concurrency", 10, 2.0),
                      _pp("utilization", 10, 3.0)])
    assert h4_holds_on(step, ramp_wider) is False
    ramp_reordered = _fr([_pp("queue_depth", 10, 2.5), _pp("in_flight_concurrency", 10, 2.0),
                          _pp("utilization", 10, 3.0)])
    assert h4_holds_on(step, ramp_reordered) is False
```

- [ ] **Step 2: Run them and see them fail** (`ImportError`)

- [ ] **Step 3: Implement `autoscale/hypotheses.py`**

```python
"""H1, H2 and H4, operationalised after the simulator's frontiers were seen.

The pre-registration states H1, H2 and H4 in words only. These definitions
were written on 2026-10-05, after the x1.00 frontiers had been printed by
the exploratory sensitivity run, and were signed by the owner before this
module computed anything (publication plan, Task 0). The post says so beside
every verdict, and every verdict is on an UNVALIDATED simulator.

Each function takes frontiers per signal (`{signal: [PolicyPoint, ...]}`) for
one sweep. "Reached p99" is the iso-cost slice the gap uses: the best median
p99 a signal's frontier reaches at or under the budget.
"""

from autoscale.frontier import iso_cost_budget

__all__ = ["TIE_SECONDS", "h1_holds_on", "h2_worst_on", "h4_holds_on", "ranking",
           "reached_p99"]

TIE_SECONDS = 0.001
SIGNALS = ("queue_depth", "in_flight_concurrency", "utilization")


def reached_p99(frontiers, budget: float) -> dict[str, float]:
    return {s: min(p.p99 for p in f if p.cost <= budget) for s, f in frontiers.items()}


def _dominates(a, b) -> bool:
    return a.cost <= b.cost and a.p99 <= b.p99 and (a.cost < b.cost or a.p99 < b.p99)


def h1_holds_on(frontiers) -> bool:
    """Every queue-depth and utilisation frontier point is weakly dominated by an
    in-flight one. Rejected: comparing only at the iso-cost slice, which is H3's
    measure; H1 says "dominates on the frontier", which is the whole curve."""
    inflight = frontiers["in_flight_concurrency"]
    others = [p for s in ("queue_depth", "utilization") for p in frontiers[s]]
    return all(any(_dominates(a, b) for a in inflight) for b in others)


def h2_worst_on(frontiers) -> bool:
    """Utilisation's reached p99 at the budget is strictly the highest, by more than a tie."""
    r = reached_p99(frontiers, iso_cost_budget(frontiers))
    return all(r["utilization"] > r[s] + TIE_SECONDS for s in r if s != "utilization")


def ranking(frontiers) -> list[list[str]]:
    """Signals from best to worst reached p99 at the budget; ties grouped."""
    r = reached_p99(frontiers, iso_cost_budget(frontiers))
    groups: list[list[str]] = []
    for s in sorted(r, key=r.get):
        if groups and abs(r[s] - r[groups[-1][-1]]) <= TIE_SECONDS:
            groups[-1].append(s)
        else:
            groups.append([s])
    return [sorted(g) for g in groups]


def h4_holds_on(step, ramp) -> bool:
    """Same ranking on both shapes, and a smaller gap on the ramp."""
    def gap(fr):
        r = reached_p99(fr, iso_cost_budget(fr))
        return max(r.values()) - min(r.values())
    return ranking(step) == ranking(ramp) and gap(ramp) < gap(step)
```

- [ ] **Step 4: Run the tests and see them pass.** Run ruff.
- [ ] **Step 5: Commit**

```bash
git add autoscale/hypotheses.py tests/test_hypotheses.py
git commit -m "hypotheses: H1, H2 and H4 as the owner signed them for publication, on the iso-cost slice the gap uses

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Record the H1/H2/H4 definitions in the pre-registration

**Files:**
- Modify: `docs/experiment-a2.md` (append before `## Stopping rule`)
- Test: `tests/test_prereg_a2_plan2b.py` (append)

- [ ] **Step 1: Append the section** `## Analysis note, <date>: H1, H2 and H4 operationalised after the frontiers were seen`. It contains:
  - the three definitions verbatim from Task 0;
  - the statement that they were written after the x1.00 frontiers were seen, and signed by the owner;
  - the statement that every verdict is on a simulator that failed validation twice.
- [ ] **Step 2: Append a test** that `TIE_SECONDS` and the phrase "after the frontiers were seen" appear in that section:

```python
def test_the_h1_h2_h4_definitions_are_recorded():
    from autoscale.hypotheses import TIE_SECONDS
    part = DOC.split("## Analysis note, ", 1)
    assert len(part) == 2, "the H1/H2/H4 analysis note is missing"
    s = " ".join(part[1].split("\n## ", 1)[0].split())
    assert "after the frontiers were seen" in s
    assert f"within {TIE_SECONDS * 1000:g} ms" in s
```

- [ ] **Step 3: Run that test and see it pass. Commit.**

---

### Task 5: One analysis file for everything the post quotes

**Files:**
- Create: `scripts/a2_post_analysis.py`
- Create: `data/a2/post-analysis.json` (generated)
- Test: `tests/test_a2_post_analysis.py`

- [ ] **Step 1: Write the failing test** (reproducibility, plus the shape of the output)

```python
"""data/a2/post-analysis.json is what the script computes from committed data, byte for byte."""

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_a_fresh_run_reproduces_the_committed_analysis(tmp_path):
    out = tmp_path / "a.json"
    subprocess.run([sys.executable, str(REPO / "scripts" / "a2_post_analysis.py"), "--out",
                    str(out)], check=True, cwd=REPO, env={"PYTHONDONTWRITEBYTECODE": "1",
                                                          "PATH": "/usr/bin:/bin"})
    assert out.read_bytes() == (REPO / "data" / "a2" / "post-analysis.json").read_bytes()


def test_the_analysis_has_every_section_the_post_cites():
    a = json.loads((REPO / "data" / "a2" / "post-analysis.json").read_text())
    assert set(a) >= {"validation", "load_balancer", "host_speed", "simulator", "spend"}
    assert a["validation"]["engine"]["outcome"] == "failed"
    assert a["validation"]["calibrated"]["outcome"] == "failed"
    assert set(a["simulator"]["h3"]) == {"0.88", "1", "1.12"}
```

- [ ] **Step 2: Implement `scripts/a2_post_analysis.py`.** It reads only committed files:
  - `data/a2/validation*/verdict.json` and records;
  - `data/a2/lb-probes/*`;
  - `data/a2/exploratory/*`;
  - `data/a2/frontier-sweep.json`;
  - `data/a2/service-curve.json`.

  It writes sorted, `indent=1` JSON with these sections:
  - `validation`. For each attempt, `engine` and `calibrated`: outcome, compared, misses, max miss, and per-repeat host, ratios, server p50, never-reached count and retries.
  - `load_balancer`:
    - per probe and step, the summary fields plus `delivered_rate`;
    - for probes 2 and 3, `per_worker_concurrency` at `return_leg_s=0.1`;
    - the stall share at 2 s per one-replica repeat in `data/a2/validation/`;
    - the 502-retry first-attempt durations.
  - `host_speed`: `host_speed_table` of both `maxseqs*.jsonl` stores against the committed curve, and the calibrated repeats' ratios by host.
  - `simulator`:
    - the four headline gaps at x1.00 (from `frontier-sweep.json`) and at x0.88 and x1.12 (from `exploratory/sensitivity-service-speed.json`);
    - H3 per factor;
    - H1 and H2 per arm and shape, and H4 per arm, on the x1.00 frontiers, using `autoscale.hypotheses`;
    - the per-signal reached p99 and cost at the budget.
  - `spend`: `null` until Task 13 fills it from `docs/spend-a2.md`'s table.

  Rebuild `PolicyPoint`s from `frontier-sweep.json` with `a2_render_figures._points`.

- [ ] **Step 3: Generate the file:** `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a2_post_analysis.py --out data/a2/post-analysis.json`
- [ ] **Step 4: Run the tests and see them pass.** Read the JSON's `simulator` section and confirm the x1.00 gaps are 0.0821, 3.9550, 8.2488 and 10.8734.
- [ ] **Step 5: Commit** the script, the JSON and the test.

---

### Task 6: Numbers formatted once

**Files:**
- Create: `autoscale/post_numbers_a2.py`
- Test: `tests/test_a2_post_numbers.py`

- [ ] **Step 1: Write the failing test**

```python
"""Every number the post quotes, formatted once from data/a2/post-analysis.json."""

import json
from pathlib import Path

from autoscale.post_numbers_a2 import numbers

A = json.loads((Path(__file__).resolve().parents[1] / "data" / "a2" / "post-analysis.json")
               .read_text())


def test_the_validation_verdicts_are_stated_with_their_bins():
    n = numbers(A)
    assert n["attempt1_misses"] == "34 of 37 judged bins"
    assert n["attempt2_misses"] == "37 of 37 judged bins"
    assert n["attempt2_max_miss"] == "0.060 s"


def test_the_load_balancer_ceiling_is_a_rate():
    n = numbers(A)
    assert n["lb_ceiling_rate"].endswith(" req/s") and n["lb_ceiling_rate"].startswith("1")


def test_every_value_is_a_non_empty_string():
    assert all(isinstance(v, str) and v for v in numbers(A).values())
```

- [ ] **Step 2: Implement `numbers(analysis) -> dict[str, str]`.** Formats:
  - seconds to three decimals below 1 s, otherwise two;
  - percentages as whole numbers;
  - rates to one decimal with " req/s";
  - dollars with cents.

  Keys, one per number the post quotes:
  - attempt 1 and 2: misses, max miss, typical residual, host ratios;
  - load balancer: the ceiling rate, the client and server p50 per probe-1 step, the probe-2 non-200s, the per-worker concurrency rows of probe 3, the stall shares, and the retry durations;
  - host speed: the ratios per host and level;
  - simulator: the gaps at three factors, H1, H2, H3 and H4 outcomes, and the reached p99 per signal;
  - spend lines.

- [ ] **Step 3: Run the tests and see them pass. Commit.**

---

### Tasks 7–10: The four post figures

Every figure task follows the same shape. Each one's test file is `tests/test_a2_post_figures.py`, its code is in `autoscale/figures_a2_post.py`, and its inputs come from `data/a2/post-analysis.json` and nothing else. Every figure:
- uses `FIG_WIDTH_IN` and `FIG_HEIGHT_IN` and the `PX_*` sizes from `autoscale/figures.py`;
- carries a banner saying **MEASURED**, or **SIMULATED · FAILED VALIDATION** (Task 10 only);
- states N on its face, uses no truncated axes, and passes `MIN_PHONE_TEXT_PX` at 375 px;
- keeps all text on canvas.

The common test helpers are at the top of `tests/test_a2_post_figures.py`:

```python
"""The post's four figures: content, legibility at phone width, nothing off canvas."""

import json
from pathlib import Path

import matplotlib
import pytest

matplotlib.use("Agg")
from autoscale import figures_a2_post as fp
from harness.figure_guards import MIN_PHONE_TEXT_PX

A = json.loads((Path(__file__).resolve().parents[1] / "data" / "a2" / "post-analysis.json")
               .read_text())


def _texts(fig):
    return [t.get_text() for t in fig.findobj(matplotlib.text.Text) if t.get_text().strip()]


def _legible_and_on_canvas(fig):
    width_in = fig.get_size_inches()[0]
    for t in fig.findobj(matplotlib.text.Text):
        if t.get_text().strip():
            assert t.get_fontsize() * 375 / (72 * width_in) >= MIN_PHONE_TEXT_PX, t.get_text()
    fig.canvas.draw()
    w, h = fig.canvas.get_width_height()
    renderer = fig.canvas.get_renderer()
    for t in fig.findobj(matplotlib.text.Text):
        if t.get_text().strip() and t.get_visible():
            box = t.get_window_extent(renderer)
            assert box.x0 >= -1 and box.y0 >= -1 and box.x1 <= w + 1 and box.y1 <= h + 1, \
                t.get_text()


def _gids(fig):
    return [a.get_gid() for a in fig.findobj() if getattr(a, "get_gid", lambda: None)()]
```

### Task 7: Figure "two attempts"

**Files:** modify `autoscale/figures_a2_post.py` (create it in this task), `tests/test_a2_post_figures.py` (create).

What it shows: two panels side by side. Each plots the three repeats' residuals (real p50 minus predicted p50) per 10 s bin against engine arrival time:
- **left:** attempt 1, uncalibrated, 34/37 misses;
- **right:** attempt 2, host-calibrated, 37/37 misses.

Each panel has a zero line, and its miss count is on its face. The y-axes are shared and symmetric about zero, so the change of sign is visible at a glance.

Inputs: Task 5 must also write `validation.<attempt>.residuals` (a per-repeat list of `[bin_start, residual or null]`), computed with `autoscale.validation.engine_trajectories` on each attempt's records.

- [ ] **Step 1: Write the failing test**

```python
def test_attempts_draws_both_panels_with_their_verdicts(tmp_path):
    fig = fp.validation_attempts(A, tmp_path / "a.png", return_figure=True)
    assert len(fig.axes) == 2
    assert _gids(fig).count("residual_series") == 6 and _gids(fig).count("zero") == 2
    text = " ".join(_texts(fig))
    assert "34 of 37" in text and "37 of 37" in text and "MEASURED" in text
    lo0, hi0 = fig.axes[0].get_ylim()
    assert lo0 == pytest.approx(-hi0) and fig.axes[1].get_ylim() == (lo0, hi0)
    _legible_and_on_canvas(fig)
```

- [ ] **Step 2: Run it and see it fail.**
- [ ] **Step 3: Implement `validation_attempts(analysis, path, *, return_figure=False)`.**
  - Use `plt.subplots(1, 2, sharey=True, figsize=(FIG_WIDTH_IN, FIG_HEIGHT_IN))`.
  - Each series is a `plot` with `gid="residual_series"`, and the zero line uses `gid="zero"`.
  - Set the y-limits to ±1.15 × the largest |residual| across both attempts.
  - Each panel's title is `f"attempt {k}: {label} — {misses} misses"`.
  - The banner reads "MEASURED · 1 replica, 3 repeats per attempt".
  - The note gives n per repeat and states "residual = real − predicted p50 per 10 s bin, binned by engine arrival".
  - Reuse `_tidy`, `_note`, `_finish` and `_pt` by importing them from `autoscale.figures`.
- [ ] **Step 4: Run the test and see it pass.** Then render to `build/post-figs/attempts.png`, make the 375 px variant with the snippet in Task 11, and **look at both**. Check: no overlap, readable at 375 px, the change of sign obvious. Fix and re-render until all three hold.
- [ ] **Step 5: Commit.**

### Task 8: Figure "the load balancer"

What it shows: two panels.
- **Left:** delivered completions per second against the offered rate, for probe 1 (scaler 4) and probe 2 (scaler 128). The ~17 req/s plateau is visible, with a dashed y = x reference.
- **Right:** probe 3's mean and peak requests in flight per worker, at each offered rate, as grouped bars. A horizontal line marks the cap of 128, and the note says "fills worker 1 to the cap before worker 2".

The note discloses the server-interval reconstruction (`return_leg_s = 0.1`).

- [ ] **Step 1: Write the failing test**

```python
def test_load_balancer_shows_the_ceiling_and_the_fill_first_routing(tmp_path):
    fig = fp.load_balancer(A, tmp_path / "lb.png", return_figure=True)
    assert len(fig.axes) == 2
    assert {"delivered_scaler_4", "delivered_scaler_128", "offered_equals_delivered",
            "cap_128"} <= set(_gids(fig))
    assert sum(1 for g in _gids(fig) if g.startswith("worker_bar")) >= 8
    assert "MEASURED" in " ".join(_texts(fig))
    _legible_and_on_canvas(fig)
```

- [ ] **Steps 2–5:** see it fail; implement `load_balancer(analysis, path, *, return_figure=False)` with those gids; render and **look at it at full size and at 375 px**; commit.

### Task 9: Figure "host speed"

What it shows: one panel. The x axis is concurrency (32, 64, 128); the y axis is the latency ratio to the committed curve (1.0 is the curve's host, `ozhetwnhompob9`).
- `daps3haubwrzbn` (exploratory sweeps) is plotted with min–max bars over its 3 runs, one series per `--max-num-seqs` value.
- `sef5s24viyecyr` (the calibrations at 64 and 128 from the three calibrated repeats) is plotted as points.

The y axis runs 0.75–1.05, as a ratio axis starting at 0.75; the note says so explicitly, because a ratio near 1 is unreadable on an axis from 0. The note also states "4 hosts seen, 3 measured; not a distribution".

- [ ] **Step 1: Write the failing test**

```python
def test_host_speed_plots_each_host_against_the_curves_host(tmp_path):
    fig = fp.host_speed(A, tmp_path / "h.png", return_figure=True)
    assert "curve_host" in _gids(fig)
    assert {"daps3haubwrzbn_128", "daps3haubwrzbn_256", "sef5s24viyecyr"} <= set(_gids(fig))
    text = " ".join(_texts(fig))
    assert "not a distribution" in text and "MEASURED" in text
    _legible_and_on_canvas(fig)
```

- [ ] **Steps 2–5:** as in Task 8, including the visual check at both widths.

### Task 10: Figure "what the unvalidated simulator says"

What it shows: two panels, step and ramp.
- **x axis:** the cold start, arm A (81 s) and arm C (39 s).
- **y axis:** the inter-signal gap at iso-cost, in seconds.
- **Series:** one line per engine speed (x0.88, x1.00, x1.12) with its bootstrap intervals.

The banner is **"SIMULATED · FAILED VALIDATION"** in `CENSOR_COLOR`, on a hatched background. The note says "exploratory sensitivity (x0.88, x1.12) not pre-registered; the simulator failed its validation twice".

- [ ] **Step 1: Write the failing test**

```python
def test_simulator_answer_is_labelled_unvalidated_on_its_face(tmp_path):
    fig = fp.simulator_answer(A, tmp_path / "s.png", return_figure=True)
    text = " ".join(_texts(fig))
    assert "FAILED VALIDATION" in text and "not pre-registered" in text
    assert _gids(fig).count("gap_series") == 6  # 3 speeds x 2 shapes
    assert all(ax.get_ylim()[0] == 0 for ax in fig.axes)
    _legible_and_on_canvas(fig)
```

- [ ] **Steps 2–5:** as above, with the visual check at both widths. Confirm "FAILED VALIDATION" is readable at 375 px.

---

### Task 11: Publish the figures beside the post, guarded against drift

**Files:**
- Create: `scripts/a2_render_post_figures.py`
- Create: `docs/figures/a2/{attempts,load_balancer,host_speed,simulator_answer,service_curve}.png` and `*-phone.png`
- Test: `tests/test_a2_published_figures.py`

- [ ] **Step 1: Write the failing test** (it mirrors `tests/test_published_figures.py`)

```python
"""Artifact 2's published figures are a fresh render's bytes, linked from the post, tracked."""

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PUB = REPO / "docs" / "figures" / "a2"
NAMES = ("attempts", "load_balancer", "host_speed", "simulator_answer", "service_curve")


@pytest.fixture(scope="module")
def fresh(tmp_path_factory):
    out = tmp_path_factory.mktemp("render")
    subprocess.run([sys.executable, str(REPO / "scripts" / "a2_render_post_figures.py"),
                    "--out", str(out)], check=True, cwd=REPO,
                   env={"PYTHONDONTWRITEBYTECODE": "1", "PATH": "/usr/bin:/bin",
                        "MPLBACKEND": "Agg"})
    return out


@pytest.mark.parametrize("name", NAMES)
def test_published_figure_matches_a_fresh_render(fresh, name):
    assert (PUB / f"{name}.png").read_bytes() == (fresh / f"{name}.png").read_bytes()


@pytest.mark.parametrize("name", NAMES)
def test_the_post_links_the_published_figure(name):
    assert f"(figures/a2/{name}.png)" in (REPO / "docs" / "post-a2.md").read_text()


@pytest.mark.parametrize("name", NAMES)
def test_phone_variant_is_published_and_tracked(name):
    for f in (f"{name}.png", f"{name}-phone.png"):
        assert (PUB / f).exists()
        tracked = subprocess.run(["git", "ls-files", "--error-unmatch", str(PUB / f)],
                                 cwd=REPO, capture_output=True)
        assert tracked.returncode == 0, f
```

- [ ] **Step 2: Implement the render script.** It writes the five desktop PNGs to `--out`. `service_curve` comes from `autoscale.figures.service_curve` with the measured curve. Phone variants are written only with `--phone`: each is a 375 px-wide LANCZOS downscale with PIL (`Image.resize((375, round(h * 375 / w)))`). The phone files aren't re-derived in the test, as in artifact 1.
- [ ] **Step 3: Publish**
  1. Run `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a2_render_post_figures.py --out docs/figures/a2 --phone`.
  2. **Look at all ten images.** Invoke `superpowers:verifying-visual-output` and note in the commit message what you checked.
- [ ] **Step 4: Commit** the script, `docs/figures/a2/*` and the test. The link test passes only after Task 14.

---

### Task 12: Cost in dollars, with the assumptions published

**Files:**
- Create: `autoscale/money_a2.py`
- Test: `tests/test_money_a2.py`

Two money statements, both computed from `post-analysis.json`:
1. **The cost of the load balancer's default cap.** At scaler value 4, the two-worker endpoint delivered about 17 req/s while being billed for two workers. Express this as dollars per million requests at the measured $/h, against the same two workers at scaler value 128 at 300 req/s.
2. **The cost of the signal choice, from the unvalidated simulator.** On arm A's step, at iso-p99, queue depth reached p99 for about 880 replica-seconds against about 2,535 for in-flight concurrency. Express it as dollars per spike at the measured rate, labelled unvalidated.

The assumption table follows artifact 1's style. `gpu_hourly_rate` is **0.74 $/h, measured** (the RunPod worker records' `costPerHr` for an RTX 4090 on 2026-10-05). `spikes_per_day` is **24, illustrative**.

- [ ] **Step 1: Write the failing test**

```python
from autoscale.money_a2 import Assumptions, dollars_per_million_requests, dollars_per_spike


def test_dollars_per_million_requests_at_a_rate():
    a = Assumptions(gpu_hourly_rate=0.74, spikes_per_day=24.0)
    # two workers for one hour at 17 req/s
    assert dollars_per_million_requests(a, workers=2, rate=17.0) == round(
        2 * 0.74 / (17.0 * 3600) * 1e6, 2)


def test_dollars_per_spike_from_replica_seconds():
    a = Assumptions(gpu_hourly_rate=0.74, spikes_per_day=24.0)
    assert dollars_per_spike(a, replica_seconds=3600.0) == 0.74


def test_assumptions_refuse_non_positive_rates():
    import pytest
    with pytest.raises(ValueError, match="gpu_hourly_rate"):
        Assumptions(gpu_hourly_rate=0.0, spikes_per_day=24.0)
```

- [ ] **Step 2: Implement** a frozen dataclass with `__post_init__` validation and the two functions, rounding to cents. Each assumption carries a provenance string: "measured" or "illustrative".
- [ ] **Step 3: Add the money lines to `post-analysis.json`** (Task 5's script) and to `numbers()` (Task 6). Regenerate, run all tests, and commit.

---

### Task 13: Record artifact 2's spend

**Files:**
- Create: `docs/spend-a2.md`
- Modify: `scripts/a2_post_analysis.py` (read its table into `spend`)

- [ ] **Step 1: The owner reads the RunPod console's billing for 2026-10-03 to 2026-10-05**, per endpoint (`a8261k5opy1ldl`, `7h0aglrmsjovyc`, `lybvnpnt2m327y`, `un0lhqt51q1bvp`), and gives the figures. The session's own estimates are below, to be replaced, never published as the record:

| Item | Estimate |
|---|---|
| Pilot | $0.08 |
| 1–64 sweep | $0.79 |
| 1–256 sweep | $0.97 |
| Recon | $0.57 |
| Five load-balancer probes | about $1.1 |
| Failed two-replica repeat | about $0.5 |
| One-replica repeats, first set | about $0.5 |
| Engine-arrival attempt, including its void | about $0.6 |
| Exploratory host sweeps | about $0.7 |
| Calibrated attempt | about $0.6 |

- [ ] **Step 2: Write `docs/spend-a2.md`.** It holds a table of item, endpoint, dates and dollars from the console, a total, and the one-line source ("RunPod console, billing, read by the owner on <date>").
- [ ] **Step 3: Ask the owner whether artifact 1's actual spend has been read.** Spec §13 flagged it as unrecorded. If yes, add a line. If no, say so in the file.
- [ ] **Step 4: Regenerate `post-analysis.json`, run the tests, and commit.**

---

### Task 14: Write the post

**Files:**
- Create: `docs/post-a2.md`
- Test: `tests/test_a2_post.py`

- [ ] **Step 1: Write the failing test**

```python
"""docs/post-a2.md quotes every computed number, links every figure, and labels the
unvalidated simulator wherever its numbers appear."""

import json
import re
from pathlib import Path

from autoscale.post_numbers_a2 import numbers

REPO = Path(__file__).resolve().parents[1]
POST = (REPO / "docs" / "post-a2.md").read_text()
A = json.loads((REPO / "data" / "a2" / "post-analysis.json").read_text())


def test_every_computed_number_is_quoted_verbatim():
    missing = [k for k, v in numbers(A).items() if v not in POST]
    assert not missing, missing


def test_the_header_has_the_permanent_slug_byline_and_repo_link():
    assert re.search(r"Permanent slug: /experiments/\S+", POST)
    assert re.search(r"^\*\*Oleksii Ostapiuk\*\* · \d{4}-\d{2}-\d{2} · ", POST, re.M)
    assert "github.com/alexostapiuk11/coldstart-recon-worker" in POST


def test_the_simulator_section_is_labelled_unvalidated():
    section = POST.split("## What the unvalidated simulator says", 1)[1].split("\n## ", 1)[0]
    assert "failed" in section and "not a measurement" in section
    assert "exploratory" in section


def test_every_amendment_is_listed_in_reproducing_this():
    doc = (REPO / "docs" / "experiment-a2.md").read_text()
    dates = re.findall(r"^## Amendment, (\d{4}-\d{2}-\d{2}(?: \(\w+\))?)", doc, re.M)
    repro = POST.split("## Reproducing this", 1)[1]
    assert all(d in repro for d in dates), dates
```

- [ ] **Step 2: Write `docs/post-a2.md`,** following the header form of artifact 1's `docs/post.md` lines 1–20:
  - an HTML comment with "Permanent slug: <Task 0 slug>";
  - `# <title>`;
  - the byline `**Oleksii Ostapiuk** · <Task 0 date> · `<slug>``;
  - a lede, then the repo link.

  Sections, in this order (headings exact):
  1. `## The question` — the original question in one paragraph, and the answer: not answered by measurement.
  2. `## What was measured and what was simulated`
  3. `## The test the simulator had to pass` — the pre-registered gate, and why it was written first.
  4. `## Attempt one: the engine was faster than the curve` — figure `attempts`, and the host-speed cause with figure `host_speed`.
  5. `## Attempt two: calibrated, and wrong the other way` — the ~12% closed-loop versus open-loop gap, stated with its evidence base (one host).
  6. `## What RunPod's load balancer does` — figure `load_balancer`, the five findings, dated 2026-10-05.
  7. `## What the unvalidated simulator says` — figure `simulator_answer`, H3 with the sensitivity, H1/H2/H4 with the analysis-note caveat. It must contain the words "failed", "not a measurement" and "exploratory".
  8. `## The service curve` — figure `service_curve`.
  9. `## What it costs` — the Task 12 table and statements, plus the spend from Task 13.
  10. `## Limits` — the standing limits plus: one provider, one GPU class, four hosts seen, load-balancer behaviour as of a date, and the closed-loop gate never built.
  11. `## Reproducing this` — commands, the data files, and every amendment by date.
  12. `## Next`

  Every number comes from `numbers()`; copy the strings, don't retype them. Embed the figures as `![alt](figures/a2/<name>.png)`.
- [ ] **Step 3: Run `tests/test_a2_post.py` and `tests/test_a2_published_figures.py`.** Fix the post until both pass.
- [ ] **Step 4: Commit** the post and its test.

---

### Task 15: Repo README link back, and the pre-publish gate

**Files:**
- Modify: `README.md` (add the post's slug and title under artifacts)

- [ ] **Step 1: Add the link back** (the portfolio contract: "the repo README links back as canonical").
- [ ] **Step 2: Run the gate.** Each item is checked and its evidence noted:
  - [ ] Nothing traceable to employer internal material. **Owner only:** ask, and do not answer for them.
  - [ ] `docs/experiment-a2.md` committed before the first paid policy-sweep record. Check with `git log --diff-filter=A --format=%H -- docs/experiment-a2.md` and `git log --diff-filter=A --format=%H -- data/a2/service-sweep.jsonl`, comparing their dates.
  - [ ] Every amendment dated and signed, and listed in "Reproducing this" (Task 14's test).
  - [ ] Both validation attempts published with every miss (`verdict.json` linked from the post).
  - [ ] Every number in the post comes from `post-analysis.json` (Task 14's test).
  - [ ] Five figures inspected at full size and phone width (Tasks 7–11).
  - [ ] The repo publishes the raw records, the analysis code, the figure code and the runbook.
  - [ ] The exposed endpoint credentials rotated (Task 16).
- [ ] **Step 3: Record the gate** as `git commit --allow-empty -m "artifact 2 pre-publish gate: <each item: pass/evidence>; Employer boundary: confirmed by the owner on <date>"`, plus the co-author line.

---

### Task 16: Housekeeping on RunPod (owner-approved, each step separately)

- [ ] **Step 1: Rotate the credentials printed in the session on 2026-10-05.**
  1. Create a replacement load-balancing endpoint with the same settings as `un0lhqt51q1bvp`: GraphQL `saveEndpoint`, `type: "LB"`, `scalerValue: 512`, `workersMax: 1`.
  2. Update `RUNPOD_A2_LB_ENDPOINT_ID` in `.env`.
  3. Delete `un0lhqt51q1bvp`.

  Print only the id, type and settings, **never the worker records**.
- [ ] **Step 2: Delete the retired endpoint `lybvnpnt2m327y`,** with the owner's confirmation.
- [ ] **Step 3: Push,** with the owner's go: `git -c pack.threads=1 push origin main`.

---

### Task 17: Final manual visual checkpoint

**Files:**
- Create: `scripts/preview_post_a2.py`

No Markdown package is installed, so this writes `build/post-a2-preview.html`. The page embeds the post's text and renders it in the browser with marked from `https://cdn.jsdelivr.net/npm/marked/marked.min.js`, with image paths rewritten to `../docs/figures/a2/`.

- [ ] **Step 1: Write and run the script.**
- [ ] **Step 2: Open the preview in the browser pane** at `file://<repo>/build/post-a2-preview.html`. Use `mcp__Claude_Browser__resize_window` at a width ≥ 1280 and take a screenshot. Scroll through and screenshot each figure in place.
- [ ] **Step 3: Resize to 375 × 667 (preset `mobile`)** and repeat. Then reset to `desktop`.
- [ ] **Step 4: Look at every screenshot.** Check:
  - figures render in place, legibly;
  - no broken images;
  - the "FAILED VALIDATION" banner is readable on a phone;
  - the simulator section can't be mistaken for a measurement.
- [ ] **Step 5: Report** the screenshot paths and what was checked. The owner reads the post in full and decides to publish.

---

## Self-review

1. **Spec coverage, against spec §16 (definition of done):**
   - "failure characterized and published instead of the frontiers": Tasks 7, 9 and 14.
   - Confirmatory gate "dropped with … published": Task 14's Limits states it was never built and why.
   - `host_id` recorded: in every record already, cited in Task 5.
   - Frontiers produced and H3 evaluated: Tasks 5, 10 and 14.
   - Four body figures inspected at both widths, published and guarded: Tasks 7–11 (five figures).
   - Cost in both units: Task 12.
   - Post with slug, byline, date and repo link: Task 14.
   - Spend: Task 13.
   - Pre-publish gate, including the employer check: Task 15.
   - Learning-guide modules: **not covered.** They're the owner's and outside this plan; Task 15's gate should ask the owner whether `docs/learning/progress.md` covers artifact 2.
2. **Placeholders:** Tasks 5, 6, 8, 9 and 14 describe structure rather than give full code, where the code is mechanical over the JSON. Their tests and gids are fully specified. An implementer must not add keys the tests don't name without adding them to `numbers()` too.
3. **Type consistency:**
   - `post-analysis.json` is produced in Task 5 and read in Tasks 6–14.
   - `autoscale.hypotheses` names are used consistently in Tasks 3, 5 and 14.
   - The figure functions are `validation_attempts`, `load_balancer`, `host_speed` and `simulator_answer`, each taking `(analysis, path, *, return_figure=False)`.
4. **Visual verification:** every figure task has legibility and on-canvas assertions, plus a by-eye check at full size and 375 px, and the plan ends with the browser checkpoint at desktop and mobile.
5. **Parity:** no code is replaced or removed. The existing figure module and tests are untouched.
