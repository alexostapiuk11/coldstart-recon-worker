import json
import random
from pathlib import Path

import pytest

from autoscale.coldstart_ecdf import LagDistribution, load_measured_lags

CAMPAIGN = "data/campaign.jsonl"


def _campaign_lines():
    return [ln for ln in Path(CAMPAIGN).read_text().splitlines() if ln.strip()]


def _reversed_store(tmp_path):
    """A byte-for-byte copy of the campaign store with its records in reverse
    file order. `data/campaign.jsonl` is artifact 1's published input and is
    never touched."""
    lines = _campaign_lines()
    path = tmp_path / "reversed.jsonl"
    path.write_text("\n".join(reversed(lines)) + "\n")
    return path


def test_arm_pools_exclude_the_first_touch_run():
    """Artifact 1's single first-touch run (arm A, 2266.6 s) measures image
    distribution to a host that has never held the image, not a cold start.
    One such observation in 100 would dominate every p99 in the sweep.

    Arm B's count is pinned too, not just arm A's: the exclusion is a single
    run, so an ordering bug that drops the wrong run keeps the total at 299
    and merely moves the missing one between arms. Pinning A alone cannot see
    that; pinning A and B together can."""
    lags = load_measured_lags(CAMPAIGN)

    assert len(lags["A"].samples) == 99
    assert len(lags["B"].samples) == 100
    assert len(lags["C"].samples) == 100
    assert max(lags["A"].samples) < 200.0


def test_the_same_run_is_excluded_when_the_store_is_read_backwards(tmp_path):
    """REGRESSION (ordering defect). `annotate_first_touch` orders by
    `run_index`, but `derive()` does not emit that key, so every sort key was
    0, the stable sort degraded to file order, and reading the store backwards
    excluded an arm-B run instead of the arm-A 2266.6 s one -- with the pool
    sizes still summing to 299 and the medians still passing. First-touch is a
    property of when the scheduler ran a run, never of where its line sits in
    the file."""
    forward = load_measured_lags(CAMPAIGN)
    backward = load_measured_lags(_reversed_store(tmp_path))

    assert {arm: len(d.samples) for arm, d in backward.items()} == {
        arm: len(d.samples) for arm, d in forward.items()
    }
    assert sorted(backward["A"].samples) == sorted(forward["A"].samples)
    assert sorted(backward["B"].samples) == sorted(forward["B"].samples)
    assert max(backward["A"].samples) < 200.0


def test_a_failed_first_run_on_a_second_host_does_not_trip_the_guard(tmp_path):
    """DEFECT 1 regression. `first_touch` is assigned by `annotate_first_touch`
    over every derived row, but the guard in `load_measured_lags` used to count
    its "expected" side (distinct hosts) over `publishable` rows only while
    counting its "seen" side (`first_touch is True`) over that same
    `publishable` set. A host whose first-on-its-host run failed still shows up
    as a host in `publishable` -- it has other, later, repeat-host rows there
    -- but its own `first_touch=True` row never reaches `publishable`, since a
    failed run lands in `partition()`'s `failed` bucket, not `publishable`. So
    "seen" undercounts relative to "expected" on an entirely ordinary campaign
    that merely had a failed run. Failed and discarded runs are normal --
    `partition()` has buckets for exactly this.

    Splits the real campaign at run_index 150 (every real record shares one
    host_id, so this cleanly produces two hosts) and gives the second half a
    distinct host_id, then fails that host's first run (run_index 150, its
    first-on-its-host run by `annotate_first_touch`'s own ordering). Before the
    fix this raised `ValueError: found 1 first-touch run(s) across 2 distinct
    host(s)`."""
    lines = [json.loads(ln) for ln in _campaign_lines()]
    lines.sort(key=lambda r: r["run_index"])
    first_half, second_half = lines[:150], lines[150:]
    for rec in second_half:
        rec["host"]["host_id"] = "host-2"
    second_half[0]["status"] = {
        "outcome": "error",
        "failure_class": "synthetic_test_failure",
        "failure_detail": "injected by test_a_failed_first_run_on_a_second_host_does_not_trip_the_guard",
    }
    path = tmp_path / "two-host.jsonl"
    path.write_text(
        "\n".join(json.dumps(r, sort_keys=True) for r in first_half + second_half) + "\n"
    )

    load_measured_lags(path)  # must not raise


def test_measured_medians_match_artifact_ones_published_numbers():
    lags = load_measured_lags(CAMPAIGN)

    assert lags["A"].median() == pytest.approx(81.1, abs=0.5)
    assert lags["C"].median() == pytest.approx(39.4, abs=0.5)


def test_medians_are_artifact_ones_median_not_a_second_definition():
    """The delegation in `LagDistribution.median` is load-bearing, not
    incidental: two independent median implementations agree on almost every
    input, so a divergence would never surface in a test."""
    from coldstart.analysis.stats import median as stats_median

    d = LagDistribution(samples=[10.0, 20.0, 30.0, 41.0])

    assert d.median() == stats_median([10.0, 20.0, 30.0, 41.0])


def test_sampling_is_deterministic_given_a_seed():
    """One rng per sequence, five draws from it. Re-seeding inside the loop
    would compare a constant to itself and pass against a `sample()` that
    ignored `rng` entirely, so the drawn sequence is also asserted to vary."""
    d = LagDistribution(samples=[10.0, 20.0, 30.0])

    rng_a = random.Random(1)
    first = [d.sample(rng_a) for _ in range(5)]
    rng_b = random.Random(1)
    second = [d.sample(rng_b) for _ in range(5)]

    assert first == second
    assert len(set(first)) > 1


def test_sampling_only_ever_returns_measured_values():
    """Resampling, not fitting. A value the campaign never observed must never
    come out -- that is the whole reason this is an ECDF and not a parametric
    fit (spec section 3)."""
    d = LagDistribution(samples=[10.0, 20.0, 30.0])
    rng = random.Random(7)

    drawn = {d.sample(rng) for _ in range(200)}

    assert drawn <= {10.0, 20.0, 30.0}


def test_an_empty_distribution_refuses_to_be_built():
    with pytest.raises(ValueError, match="at least one sample"):
        LagDistribution(samples=[])


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_sample_refuses_to_be_built(bad):
    """A NaN lag medians to NaN and turns every downstream queue-time
    comparison into a silent False."""
    with pytest.raises(ValueError, match="non-finite"):
        LagDistribution(samples=[10.0, bad])


def test_a_none_sample_refuses_to_be_built():
    with pytest.raises(ValueError, match="None"):
        LagDistribution(samples=[10.0, None])


def test_a_negative_sample_refuses_to_be_built():
    """A negative scale-up lag means a replica was ready before it was asked
    for."""
    with pytest.raises(ValueError, match="negative"):
        LagDistribution(samples=[10.0, -3.0])


def test_a_non_numeric_sample_refuses_to_be_built_with_a_named_error():
    """MINOR fix. `math.isfinite` raises a bare `TypeError: must be real
    number, not str` on a non-numeric sample, with no index or value -- every
    other bad-sample case here names both. The validation must catch
    non-numeric types explicitly and raise the same `ValueError` shape as its
    neighbors."""
    with pytest.raises(ValueError, match=r"\[1\].*80\.5"):
        LagDistribution(samples=[10.0, "80.5"])


def test_a_missing_store_is_an_error_not_an_empty_dict(tmp_path):
    missing = tmp_path / "nope" / "campaign.jsonl"

    with pytest.raises(FileNotFoundError, match="campaign.jsonl"):
        load_measured_lags(missing)

    assert not missing.parent.exists(), (
        "the loader must not create directories on the way to failing"
    )


def test_an_empty_store_is_an_error_not_an_empty_dict(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("")

    with pytest.raises(ValueError, match="no publishable"):
        load_measured_lags(path)


def test_an_all_first_touch_store_is_its_own_diagnosis(tmp_path):
    """Every run on a distinct host is a real, readable campaign that yields
    no repeat-host runs. It must not report the same failure as an unreadable
    store."""
    lines = [json.loads(ln) for ln in _campaign_lines()]
    for i, rec in enumerate(lines):
        rec["host"]["host_id"] = f"host-{i}"
    path = tmp_path / "all-first-touch.jsonl"
    path.write_text("\n".join(json.dumps(r, sort_keys=True) for r in lines) + "\n")

    with pytest.raises(ValueError, match="no repeat-host"):
        load_measured_lags(path)


def test_an_arm_with_no_repeat_host_runs_is_an_error_not_an_absence(tmp_path):
    """An arm that vanished because every one of its runs was first-touch is
    a broken input, not a two-arm campaign."""
    lines = [json.loads(ln) for ln in _campaign_lines()]
    n = 0
    for rec in lines:
        if rec.get("arm") == "B":
            rec["host"]["host_id"] = f"lonely-host-{n}"
            n += 1
    assert n > 0, "fixture assumption: the campaign contains arm-B runs"
    path = tmp_path / "no-arm-b.jsonl"
    path.write_text("\n".join(json.dumps(r, sort_keys=True) for r in lines) + "\n")

    with pytest.raises(ValueError, match="no repeat-host runs for arm"):
        load_measured_lags(path)


def test_expected_arms_is_adjustable_for_a_deliberate_subset():
    """The arm check is a guard against silent absence, not a hardcoded claim
    that every store has three arms."""
    lags = load_measured_lags(CAMPAIGN, expected_arms=("A",))

    assert len(lags["A"].samples) == 99
