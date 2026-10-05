"""The regime search runs exactly what docs/regime-search-a2-measured.md states."""

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import a2_regime_search as rs

from autoscale.frontier import PolicyPoint
from autoscale.measured_curve import DEFAULT_PATH

DOC = (REPO / "docs" / "regime-search-a2-measured.md").read_text()
FIXED = DOC.split("\n---\n", 1)[0]  # everything above the results line


def _pp(signal, n=30, cost=100.0, p99=0.5, up=1.0, down=0.0):
    return PolicyPoint(cost_samples=(cost,) * n, p99_samples=(p99,) * n, signal=signal,
                       scale_up_at=up, scale_down_at=down, rep_indices=tuple(range(n)))


def test_the_candidates_and_their_order_match_the_document():
    rows = re.findall(r"^\| (0\.\d+) \| ([^|]+) \|$", FIXED, flags=re.MULTILINE)
    doc = [(float(b), float(a.split(" ")[0]))
           for b, cell in rows for a in [x.strip() for x in cell.split(",")]]
    assert doc == list(rs.CANDIDATES)
    assert rs.CANDIDATES[0] == (0.70, 0.25)  # the current regime, the control


def test_the_criteria_constants_match_the_document():
    flat = " ".join(FIXED.split())
    assert "at least 20 of 30 repetitions" in flat and rs.MIN_BOOTSTRAP_SAMPLES == 20
    assert f"at least {rs.P2_MIN_DISTINCT} distinct median p99 values at 1 ms" in flat
    assert rs.P2_RESOLUTION_S == 0.001
    assert "2000 iterations, seed 17" in flat
    assert rs.render.GAP_BOOTSTRAP_ITERATIONS == 2000 and rs.render.SEED == 17
    assert [t for t, *_ in rs.SWEEPS] == ["arm A step", "arm C step", "arm A ramp", "arm C ramp"]


def test_the_screen_fails_a_thin_or_missing_queue_depth_frontier():
    assert rs.screen_failure([]) is not None
    assert "below 20" in rs.screen_failure([_pp("queue_depth", n=4)])
    assert rs.screen_failure([_pp("queue_depth", n=20)]) is None


def test_p1_refuses_a_thin_frontier_and_passes_a_full_one():
    full = [_pp("queue_depth"), _pp("in_flight_concurrency", p99=0.6),
            _pp("utilization", p99=0.7)]
    assert rs.p1_failure(full) is None
    thin = [_pp("queue_depth", n=3), *full[1:]]
    assert "fewer than 20" in rs.p1_failure(thin)
    assert "no frontier" in rs.p1_failure(full[1:])


def test_p2_counts_distinct_medians_at_one_millisecond():
    assert rs.p2_distinct([_pp("queue_depth", p99=0.5001), _pp("utilization", p99=0.5003)]) == 1
    assert rs.p2_distinct([_pp("queue_depth", p99=0.500), _pp("utilization", p99=0.502)]) == 2


class FakeRunner:
    """Per candidate, a canned sweep: `good` candidates give full frontiers."""

    def __init__(self, good):
        self.good = set(good)
        self.calls = []

    def __call__(self, task):
        b, a, arm, kind, _label, signals, _, _ = task
        self.calls.append(((b, a), arm, kind, signals))
        n = 30 if (b, a) in self.good else 3
        names = signals or ("in_flight_concurrency", "queue_depth", "utilization")
        pts = [_pp(s, n=n if s == "queue_depth" else 30, p99=0.5 + 0.01 * i)
               for i, s in enumerate(names)]
        return pts, []


def test_the_search_stops_at_the_first_passing_candidate_in_order(tmp_path):
    cands = ((0.70, 0.25), (0.70, 0.5), (0.70, 1.0), (0.40, 0.25))
    fake = FakeRunner(good={(0.70, 1.0), (0.40, 0.25)})
    records = rs.search(DEFAULT_PATH, "data/campaign.jsonl", tmp_path, workers=1,
                        runner=fake, candidates=cands)
    assert [(r["baseline_fraction"], r["additional_replicas"], r["stage"], r["passed"])
            for r in records] == [(0.70, 0.25, "screen", False), (0.70, 0.5, "screen", False),
                                  (0.70, 1.0, "verify", True)]
    # Every candidate was screened; only the passing one was verified, and
    # (0.40, 0.25) -- also good -- never reached stage 2.
    verified = {c for c, _, _, sig in fake.calls if sig != ("queue_depth",)}
    assert verified == {(0.70, 1.0)}
    assert len([c for c in fake.calls if c[3] == ("queue_depth",)]) == 4
    assert (tmp_path / "results.json").exists()


def test_a_rerun_resumes_from_the_checkpoints(tmp_path):
    cands = ((0.70, 0.25), (0.70, 0.5))
    rs.search(DEFAULT_PATH, "data/campaign.jsonl", tmp_path, workers=1,
              runner=FakeRunner(good={(0.70, 0.5)}), candidates=cands)
    again = FakeRunner(good={(0.70, 0.5)})
    records = rs.search(DEFAULT_PATH, "data/campaign.jsonl", tmp_path, workers=1,
                        runner=again, candidates=cands)
    assert again.calls == []
    assert records[-1]["passed"] is True
