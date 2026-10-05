"""docs/experiment-a2.md's 2026-10-04 amendment states what the code runs."""

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import a2_lb_probe as probe

from autoscale import validation_schedule as vs
from autoscale.measured_curve import DEFAULT_PATH, IDLE_CONCURRENCY, load_measured_curve
from autoscale.thresholds import SENSITIVITY_THRESHOLDS

DOC = (Path(__file__).resolve().parents[1] / "docs" / "experiment-a2.md").read_text()
SECTION = DOC.split("## Amendment, 2026-10-04: the measured curve and the validation operating point", 1)


def _section() -> str:
    assert len(SECTION) == 2, "the 2026-10-04 amendment is missing"
    return SECTION[1].split("\n## ", 1)[0]


def test_the_operating_point_matches_the_constants():
    s = _section()
    assert f"**{vs.VALIDATION_REPLICAS} replicas**" in s
    assert f"until **{vs.VALIDATION_UNTIL:g} s**" in s
    assert f"drain **{vs.VALIDATION_DRAIN_SECONDS:g} s**" in s
    assert f"seed **{vs.VALIDATION_SEED}**" in s
    assert "**server-side latency**" in s
    assert f"**{vs.WARMUP_RPS:g} req/s**" in s


def test_the_absolute_rates_are_stated():
    s = _section()
    for label in ("saturation", "baseline", "peak"):
        assert re.search(rf"{label}[^\n]*\*\*\d+\.\d req/s\*\*", s), label


def test_the_idle_point_and_the_sensitivity_signal_are_stated():
    s = _section()
    assert f"concurrency {IDLE_CONCURRENCY:g}" in s and "0%" in s
    assert "`utilization_throughput`" in s
    up, down = SENSITIVITY_THRESHOLDS["utilization_throughput"]
    assert ", ".join(f"{v:g}" for v in up) in s
    assert ", ".join(f"{v:g}" for v in down) in s


def test_the_void_run_and_probe_rules_are_stated():
    s = _section()
    assert "void" in s and "non-200" in s
    assert "P1" in s and "P8" in s


def _flat() -> str:
    """The section with line breaks and runs of spaces collapsed, for phrases that wrap."""
    return " ".join(_section().split())


def test_the_warm_up_window_matches_the_constants():
    s = _flat()
    assert f"every pinned worker has answered for {vs.WARMUP_MIN_SECONDS:g} s straight" in s
    assert f"giving up after {vs.WARMUP_MAX_SECONDS:g} s" in s


def test_the_probe_acceptance_matches_the_probe():
    s = _flat()
    assert f"{probe.RATES[-1]:g} req/s step" in s
    assert f"at least {probe.MIN_WORKER_SHARE:.0%} of requests" in s
    assert f"at or below {probe.MAX_JITTER_S:g} s" in s
    assert "every response was 200" in s


def test_the_request_count_and_the_scaled_rates_match_the_committed_curve():
    curve = load_measured_curve(DEFAULT_PATH).curve
    schedule = vs.build_schedule(
        curve, replicas=vs.VALIDATION_REPLICAS, kind=vs.VALIDATION_KIND,
        until=vs.VALIDATION_UNTIL, drain=vs.VALIDATION_DRAIN_SECONDS, seed=vs.VALIDATION_SEED)
    facts = vs.schedule_facts(schedule, curve, replicas=vs.VALIDATION_REPLICAS,
                              until=vs.VALIDATION_UNTIL, drain=vs.VALIDATION_DRAIN_SECONDS)
    shape = vs.validation_shape(curve, replicas=vs.VALIDATION_REPLICAS, kind=vs.VALIDATION_KIND)
    s = _flat()
    assert f"{facts['requests']:,} requests" in s
    assert f"baseline **{shape.baseline_rate:.1f} req/s**" in s
    assert f"peak **{shape.baseline_rate * shape.k:.1f} req/s**" in s


def test_the_three_void_rules_are_stated_and_no_others():
    s = _flat()
    assert "any non-200 response" in s
    assert "a response from a worker outside the pinned set" in s
    assert "a 200 without the server-latency header" in s
    assert "outcome list" not in s


SECOND = DOC.split("## Amendment, 2026-10-04 (second): the traffic model on the measured curve", 1)


def _second() -> str:
    assert len(SECOND) == 2, "the second 2026-10-04 amendment is missing"
    return " ".join(SECOND[1].split("\n## ", 1)[0].split())


def test_the_second_amendment_states_the_traffic_constants():
    from autoscale.traffic import ADDITIONAL_REPLICAS_AT_PEAK, BASELINE_FRACTION_OF_SATURATION
    s = _second()
    assert "Signed off by the owner on 2026-10-04" in s
    assert f"from **0.25 → {ADDITIONAL_REPLICAS_AT_PEAK:g}** additional replicas" in s
    assert f"**{BASELINE_FRACTION_OF_SATURATION:.0%}** of measured saturation" in s


def test_the_second_amendment_states_the_sweep_rates_the_code_computes():
    from autoscale.traffic import saturation_rps, spike_shape
    curve = load_measured_curve(DEFAULT_PATH).curve
    one = spike_shape(curve, "step")
    s = _second()
    assert f"saturation **{saturation_rps(curve):.1f} req/s**" in s
    assert f"baseline **{one.baseline_rate:.1f} req/s**" in s
    assert f"peak **{one.baseline_rate * one.k:.1f} req/s**" in s


def test_the_second_amendment_pins_the_validation_spike_and_the_engine_cap():
    sys.path.insert(0, str(REPO / "worker"))
    import lb_serve
    s = _second()
    assert f"baseline + **{vs.VALIDATION_ADDITIONAL_REPLICAS:g}** × saturation" in s
    assert f"**{vs.VALIDATION_REPLICAS} replicas**" in s
    assert f"**`--max-num-seqs {lb_serve.MAX_NUM_SEQS}`**" in s
