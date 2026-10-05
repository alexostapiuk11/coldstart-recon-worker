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
    # The replica count was amended 2026-10-05 (second); see the test on that section.
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


def test_the_first_probe_acceptance_is_kept_as_signed():
    """Superseded by the 2026-10-05 (second) amendment; the text stays as history."""
    s = _flat()
    assert "450 req/s step" in s and "at least 35% of requests" in s
    assert "every response was 200" in s


def test_the_request_count_and_the_scaled_rates_match_the_committed_curve():
    curve = load_measured_curve(DEFAULT_PATH).curve
    schedule = vs.build_schedule(
        curve, replicas=vs.VALIDATION_REPLICAS, kind=vs.VALIDATION_KIND,
        until=vs.VALIDATION_UNTIL, drain=vs.VALIDATION_DRAIN_SECONDS, seed=vs.VALIDATION_SEED)
    facts = vs.schedule_facts(schedule, curve, replicas=vs.VALIDATION_REPLICAS,
                              until=vs.VALIDATION_UNTIL, drain=vs.VALIDATION_DRAIN_SECONDS)
    shape = vs.validation_shape(curve, replicas=vs.VALIDATION_REPLICAS, kind=vs.VALIDATION_KIND)
    s = _one_replica()
    assert f"**{facts['requests']:,} requests**" in s
    assert f"Baseline **{shape.baseline_rate:.1f} req/s**" in s
    assert f"peak **{shape.baseline_rate * shape.k:.1f} req/s**" in s
    assert f"p50 {facts['predicted_p50_s']:.3f} s, p99 {facts['predicted_p99_s']:.3f} s" in s


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
    assert "**2 replicas**" in s  # as signed then; amended 2026-10-05 (second)
    assert f"**`--max-num-seqs {lb_serve.MAX_NUM_SEQS}`**" in s


THIRD = DOC.split("## Amendment, 2026-10-05: the load balancer's own 502s", 1)


def test_the_retry_amendment_states_what_the_driver_retries():
    import a2_lb_common as common
    assert len(THIRD) == 2, "the 2026-10-05 amendment is missing"
    s = " ".join(THIRD[1].split("\n## ", 1)[0].split())
    assert "Signed off by the owner on 2026-10-05" in s
    assert f"answers **{common.LB_RETRY_STATUS} without the `{common.WORKER}` header**" in s
    assert "retried **once**" in s
    assert "`lb_502_retried`" in s
    assert "scaler value is **128**" in s


FOURTH = DOC.split("## Amendment, 2026-10-05 (second): one validation replica", 1)


def _one_replica() -> str:
    assert len(FOURTH) == 2, "the 2026-10-05 (second) amendment is missing"
    return " ".join(FOURTH[1].split("\n## ", 1)[0].split())


def test_the_one_replica_amendment_matches_the_constants():
    s = _one_replica()
    assert "Signed off by the owner on 2026-10-05" in s
    assert f"**{vs.VALIDATION_REPLICAS} replica** pinned" in s
    assert "scaler value is **512**" in s


def test_the_one_replica_probe_matches_the_probe():
    s = _one_replica()
    ladder = ", ".join(f"{r:g}" for r in probe.RATES)
    assert f"Ladder: **{ladder} req/s**" in s
    assert f"jitter is at or below {probe.MAX_JITTER_S:g} s" in s
    assert f"client p99 minus server p99 is at or below {probe.MAX_CLIENT_TAIL_S:.1f} s" in s
    assert "every request's final status is 200" in s


FIFTH = DOC.split("## Amendment, 2026-10-05 (third): the gate judges the arrivals the engine received", 1)


def test_the_engine_arrival_amendment_matches_the_code():
    import a2_lb_common as common
    import a2_validate as v

    from autoscale import validation as gate
    assert len(FIFTH) == 2, "the 2026-10-05 (third) amendment is missing"
    s = " ".join(FIFTH[1].split("\n## ", 1)[0].split())
    assert "Signed off by the owner on 2026-10-05" in s
    assert f"`{common.SERVER_RECEIVED}`" in s
    assert f"more than **{v.MAX_NEVER_REACHED_FRACTION:.0%}** of its requests never reached" in s
    assert f"{gate.BIN_SECONDS:g} s bins" in s
    assert f"at least {gate.MIN_COMPARED_BINS} judged bins" in s
    assert "at most half of them missing" in s and gate.MAX_MISS_FRACTION == 0.5
    assert "all above +1 ms or all below −1 ms" in s and gate.BAND_EDGE_TOLERANCE_SECONDS == 0.001


SIXTH = DOC.split("## Amendment, 2026-10-05 (fourth): calibrate each repeat's host speed", 1)


def test_the_host_calibration_amendment_matches_the_code():
    import a2_lb_common as common
    import a2_validate as v

    from autoscale import validation as gate
    assert len(SIXTH) == 2, "the 2026-10-05 (fourth) amendment is missing"
    s = " ".join(SIXTH[1].split("\n## ", 1)[0].split())
    assert "Signed off by the owner on 2026-10-05" in s
    lo, hi = gate.CALIBRATION_LEVELS
    assert f"**{lo:g}** and **{hi:g}**" in s
    assert f"{common.CALIBRATION_SETTLE_S:g} s to settle, then {common.CALIBRATION_MEASURE_S:g} s" in s
    assert f"at least **{common.CALIBRATION_MIN_REQUESTS}**" in s
    assert f"`{v.OUT.as_posix()}/`" in s
    assert "**second and last** attempt" in s
