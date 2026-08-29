"""End-to-end synthetic validation.

Proves the whole pipeline recovers a known answer before any paid run: the
stub's ground truth orders the arms, and the analysis has to rediscover that
ordering through the real driver, store, parser, metrics, gate and statistics.
"""

from coldstart.analysis.metrics import derive
from coldstart.analysis.pipeline import (
    REQUIRED_FOR_T_TOTAL,
    REQUIRED_FOR_T_WEIGHTS,
    discard_table,
    failure_rate_by_arm,
    partition,
)
from coldstart.analysis.stats import (
    bootstrap_median_diff,
    bootstrap_paired_median_diff,
    within_host_triples,
)
from coldstart.driver import run_campaign
from coldstart.store import JsonlStore
from coldstart.stubs.stub_endpoint import StubEndpoint, VirtualClock
from coldstart.submitter import StubSubmitter


def _campaign(tmp_path, *, seed, triples, hosts=6, endpoint=None):
    """A stub campaign through the real driver and store.

    The submitter and endpoint share a VirtualClock so the clock-A span
    actually contains the clock-B timeline; with a wall clock the stub returns
    instantly and every T_total is negative.
    """
    clock = VirtualClock()
    ep = endpoint if endpoint is not None else StubEndpoint(seed=seed, hosts=hosts, clock=clock)
    store = JsonlStore(tmp_path / "runs.jsonl")
    run_campaign(
        submitter=StubSubmitter(ep, clock=clock),
        store=store,
        arms=["A", "B", "C"],
        triples=triples,
        seed=seed,
    )
    return [derive(r) for r in store.read_all()]


def test_pipeline_recovers_the_stubs_known_ordering(tmp_path):
    rows = _campaign(tmp_path, seed=42, triples=40)
    result = partition(rows, required=REQUIRED_FOR_T_WEIGHTS)
    assert len(result.publishable) > 100

    by = {a: [r["t_weights"] for r in result.publishable if r["arm"] == a] for a in "ABC"}
    ab = bootstrap_median_diff(by["A"], by["B"], iterations=400, seed=1)
    assert ab["lo"] > 0, "weight caching effect must be recovered with a positive interval"


def test_pipeline_recovers_the_compile_effect(tmp_path):
    """H3, the reason arm C exists: B (cold compile) minus C (warm compile)."""
    rows = _campaign(tmp_path, seed=43, triples=40)
    pub = partition(rows, required=REQUIRED_FOR_T_TOTAL).publishable
    by = {a: [r["t_compile"] for r in pub if r["arm"] == a] for a in "ABC"}
    bc = bootstrap_median_diff(by["B"], by["C"], iterations=400, seed=2)
    assert bc["lo"] > 0, "compile-cache effect must be recovered with a positive interval"


def test_arm_ordering_is_total_on_t_total(tmp_path):
    """The stub's ground truth is A slowest, then B, then C. The analysis has
    to recover that ordering, not merely find some difference."""
    rows = _campaign(tmp_path, seed=44, triples=40)
    pub = partition(rows, required=REQUIRED_FOR_T_TOTAL).publishable
    ab = bootstrap_median_diff(
        [r["t_total"] for r in pub if r["arm"] == "A"],
        [r["t_total"] for r in pub if r["arm"] == "B"],
        iterations=400,
        seed=3,
    )
    bc = bootstrap_median_diff(
        [r["t_total"] for r in pub if r["arm"] == "B"],
        [r["t_total"] for r in pub if r["arm"] == "C"],
        iterations=400,
        seed=4,
    )
    assert ab["lo"] > 0 and bc["lo"] > 0


def test_within_host_triples_are_found(tmp_path):
    rows = _campaign(tmp_path, seed=7, triples=40, hosts=2)
    kept = within_host_triples(rows)
    assert kept, "with only 2 hosts some triples must land on one host"


def test_paired_analysis_recovers_the_effect_with_the_host_confound_removed(tmp_path):
    """The stub gives each host its own speed multiplier, so the paired
    estimate is the one that removes it."""
    # With 2 hosts a triple lands entirely on one host about a quarter of the
    # time, so the campaign has to be large enough to clear the bootstrap's
    # 20-unit floor. That floor is a real guard against reading an interval off
    # a thin sample, not an obstacle to route around.
    rows = _campaign(tmp_path, seed=8, triples=120, hosts=2)
    triples = within_host_triples(rows)
    assert len(triples) >= 20
    paired = bootstrap_paired_median_diff(triples, "A", "B", "t_weights", iterations=400, seed=5)
    assert paired["lo"] > 0


# --- the gate holds when runs fail or are unusable ---------------------------


def test_failures_and_discards_are_counted_separately(tmp_path):
    class SometimesBroken:
        def __init__(self, clock):
            self.calls = 0
            self._inner = StubEndpoint(seed=11, clock=clock)

        def run(self, arm, run_id):
            self.calls += 1
            if self.calls % 7 == 0:
                raise RuntimeError("health check timed out")
            return self._inner.run(arm=arm, run_id=run_id)

    clock = VirtualClock()
    store = JsonlStore(tmp_path / "runs.jsonl")
    run_campaign(
        submitter=StubSubmitter(SometimesBroken(clock), clock=clock),
        store=store,
        arms=["A", "B", "C"],
        triples=20,
        seed=12,
    )
    rows = [derive(r) for r in store.read_all()]
    result = partition(rows, required=REQUIRED_FOR_T_TOTAL)

    assert len(result.failed) > 0
    assert len(result.publishable) + len(result.discarded) + len(result.failed) == len(rows)

    rates = failure_rate_by_arm(rows)
    assert sum(v["failed"] for v in rates.values()) == len(result.failed)

    # A failed run can never appear in the discard table, and vice versa.
    discards = discard_table(result.discarded)
    assert sum(v["total"] for v in discards.values()) == len(result.discarded)


def test_no_failed_run_reaches_the_paired_analysis(tmp_path):
    """A failed run still carries arm/host_id/triple_index, so before the gate
    it could stand in for a missing arm and inflate the triple count."""

    class AlwaysBrokenArmB:
        def __init__(self, clock):
            self._inner = StubEndpoint(seed=13, hosts=1, clock=clock)

        def run(self, arm, run_id):
            if arm == "B":
                raise RuntimeError("health check timed out")
            return self._inner.run(arm=arm, run_id=run_id)

    clock = VirtualClock()
    store = JsonlStore(tmp_path / "runs.jsonl")
    run_campaign(
        submitter=StubSubmitter(AlwaysBrokenArmB(clock), clock=clock),
        store=store,
        arms=["A", "B", "C"],
        triples=10,
        seed=14,
    )
    rows = [derive(r) for r in store.read_all()]
    # Every triple is missing arm B, so no complete triple exists even though
    # a B row is present in every one of them.
    assert within_host_triples(rows) == []


# --- the plan's definition of done: a 120-run campaign, no GPU, no cost ------


def test_a_120_run_campaign_completes_and_is_publishable(tmp_path):
    rows = _campaign(tmp_path, seed=99, triples=40)
    assert len(rows) == 120
    result = partition(rows, required=REQUIRED_FOR_T_TOTAL)
    assert len(result.publishable) == 120, "no synthetic run should be unpublishable"
    for row in result.publishable:
        assert row["t_total"] > 0
        assert row["t_s4_bracket"] is not None
        assert row["t_fast_seconds"] >= row["t_total"], "spec 7 invariant"
