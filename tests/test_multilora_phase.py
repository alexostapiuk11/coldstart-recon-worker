import pytest

from multilora.phase import (
    PhaseCountMismatch,
    check_counts,
    is_failure,
    phase_summaries,
    successful,
    summarize,
)
from multilora.records import InstanceRecord


def phase(ttfts, lens, errors, *, duration=10.0, index=0, regime="spread", completed=None, failed=None):
    ok = sum(1 for t, n, e in zip(ttfts, lens, errors) if not is_failure(t, n, e))
    return {
        "phase_index": index,
        "regime": regime,
        "ttfts": ttfts,
        "output_lens": lens,
        "errors": errors,
        "duration_s": duration,
        "completed": ok if completed is None else completed,
        "failed": len(ttfts) - ok if failed is None else failed,
    }


def test_three_kinds_of_failure_are_removed():
    p = phase([0.1, 0.0, 0.2, 0.3], [16, 16, 0, 16], ["", "", "", "boom"])
    assert successful(p) == ([0.1], [16])


def test_an_empty_error_string_with_zero_ttft_is_still_a_failure():
    """vLLM 0.27.1 records some failures as error=\"\" with ttft 0.0."""
    assert is_failure(0.0, 16, "")


def test_counts_that_agree_pass():
    check_counts(phase([0.1, 0.0], [16, 16], ["", ""]))


def test_counts_that_disagree_fail_the_phase():
    p = phase([0.1, 0.0], [16, 16], ["", ""], completed=2, failed=0)
    with pytest.raises(PhaseCountMismatch, match="tool reports 2 completed"):
        check_counts(p)


def test_mismatched_array_lengths_are_refused():
    with pytest.raises(ValueError, match="differ in length"):
        successful(phase([0.1], [16, 16], [""]))


def test_throughput_is_total_tokens_over_total_duration():
    a = phase([0.1] * 50, [16] * 50, [""] * 50, duration=10.0)
    b = phase([0.2] * 50, [16] * 50, [""] * 50, duration=6.0)
    s = summarize([a, b])
    assert s["throughput_tps"] == pytest.approx(100 * 16 / 16.0)
    assert s["request_rate"] == pytest.approx(100 / 16.0)
    assert s["ttft_p50"] == pytest.approx(0.15)
    assert s["n_ok"] == 100 and s["n_failed"] == 0


def test_failed_requests_do_not_enter_ttft_or_throughput():
    p = phase([0.1] * 90 + [0.0] * 10, [16] * 90 + [16] * 10, [""] * 100, duration=9.0)
    s = summarize([p])
    assert s["n_failed"] == 10
    assert s["throughput_tps"] == pytest.approx(90 * 16 / 9.0)


def test_p95_needs_the_sample_floor():
    with pytest.raises(ValueError, match="p95 requires at least 80"):
        summarize([phase([0.1] * 40, [16] * 40, [""] * 40)])


def test_phase_summaries_are_in_phase_order():
    rec = InstanceRecord(
        1, 0, 0, "gate", "r", "ok", None, None, {},
        phases=[
            phase([0.3] * 80, [16] * 80, [""] * 80, index=2, regime="real"),
            phase([0.1] * 80, [16] * 80, [""] * 80, index=0, regime="real"),
            phase([0.9] * 80, [16] * 80, [""] * 80, index=1, regime="synthetic"),
        ],
    )
    assert [s["ttft_p50"] for s in phase_summaries(rec, "real")] == [0.1, 0.3]
