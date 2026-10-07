import pytest

from tests.conftest import example_prereg


def test_the_example_is_valid_and_derives_the_margin_and_phase_size(prereg):
    assert prereg.equivalence_margin == pytest.approx(0.05)
    assert prereg.requests_per_phase == 640
    assert prereg.gate_slots == 8


def test_small_concurrency_still_meets_the_p95_floor():
    small = {"sweep": (1, 2, 4), "diagnostic_points": (1, 4), "control_point": 4}
    assert example_prereg(concurrency=4, **small).requests_per_phase == 80
    assert example_prereg(concurrency=9, **small).requests_per_phase == 90


def test_a_sweep_above_concurrency_is_refused():
    with pytest.raises(ValueError, match="exceeds concurrency"):
        example_prereg(concurrency=32)


def test_a_sweep_that_does_not_double_is_refused():
    with pytest.raises(ValueError, match="double"):
        example_prereg(sweep=(1, 2, 3, 4), diagnostic_points=(1,), control_point=4)


def test_too_few_instances_for_a_bootstrap_are_refused():
    with pytest.raises(ValueError, match="bootstrap floor"):
        example_prereg(instances_per_condition=19)


def test_the_gate_size_defaults_to_the_campaign_size(prereg):
    assert prereg.gate_instances == 24


def test_too_few_gate_instances_for_a_bootstrap_are_refused():
    from harness.stats import MIN_BOOTSTRAP_SAMPLES

    with pytest.raises(ValueError, match="gate_instances must be an int at or above the bootstrap floor"):
        example_prereg(gate_instances=MIN_BOOTSTRAP_SAMPLES - 1)
    assert example_prereg(gate_instances=MIN_BOOTSTRAP_SAMPLES).gate_instances == MIN_BOOTSTRAP_SAMPLES


@pytest.mark.parametrize("bad", [True, 144.0, "144", None])
def test_the_gate_size_must_be_a_real_int(bad):
    with pytest.raises(ValueError, match="gate_instances must be an int at or above the bootstrap floor"):
        example_prereg(gate_instances=bad)


@pytest.mark.parametrize("tau", [0.0, 1.0, -0.1])
def test_the_knee_threshold_must_be_a_fraction(tau):
    with pytest.raises(ValueError, match="knee_threshold"):
        example_prereg(knee_threshold=tau)


def test_non_positive_rates_are_refused():
    with pytest.raises(ValueError, match="gpu_hourly_rate"):
        example_prereg(gpu_hourly_rate=0.0)


def test_every_real_gate_adapter_is_pinned_to_a_revision():
    with pytest.raises(ValueError, match="real_adapters has 3"):
        example_prereg(real_adapters=(("a", "1"), ("b", "2"), ("c", "3")))
    with pytest.raises(ValueError, match="repo id, revision"):
        example_prereg(real_adapters=(("a", "1"), ("b", "2"), ("c", "3"), ("d", "")))


def test_the_request_shape_must_be_stated():
    with pytest.raises(ValueError, match="bench_dataset_args"):
        example_prereg(bench_dataset_args=())


def test_diagnostic_and_control_points_must_be_on_the_sweep():
    with pytest.raises(ValueError, match="diagnostic_points"):
        example_prereg(diagnostic_points=(1, 3))
    with pytest.raises(ValueError, match="control_point"):
        example_prereg(control_point=48)


def test_the_table_names_every_field_and_the_derived_values(prereg):
    from dataclasses import fields

    from multilora.prereg import prereg_table

    table = prereg_table(prereg)
    for f in fields(prereg):
        assert f"| `{f.name}` |" in table
    assert "| `equivalence_margin` (derived) | `0.05` |" in table
