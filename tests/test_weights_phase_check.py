"""The numbers docs/post.md quotes about the `T_weights` phase and the S6 mark.

Each assertion is a sentence in the post. They were wrong once -- the post called a
launch-to-model-loaded span "weight loading", said its rows summed to the median
total when medians do not add, and called request 1's whole latency a "first
token" -- so they are pinned to the committed campaign rather than left as prose.
"""

from pathlib import Path

import pytest

from scripts.weights_phase_check import compute

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def out():
    return compute(REPO / "data" / "campaign.jsonl")


def test_phase_medians_do_not_sum_to_the_median_total(out):
    """The post prints a 'sum of the rows above' line and says the gap is not an
    unmeasured residual."""
    assert out["sum_as_printed"] == {"A": 82.49, "B": 66.57, "C": 38.90}
    assert {a: round(v, 2) for a, v in out["median_total"].items()} == {
        "A": 81.12,
        "B": 65.43,
        "C": 39.37,
    }


def test_each_runs_phases_do_sum_to_its_total(out):
    """...because per run there is no residual: the gap above is the median not
    being additive, nothing else."""
    assert out["per_run_phase_sum_max_error"] < 1e-4


def test_t_weights_is_mostly_start_up_not_loading(out):
    load = {a: {k: round(v, 2) for k, v in d.items()} for a, d in out["load"].items()}
    assert load == {
        "A": {"t_weights": 45.83, "vllm_load": 17.40, "startup": 28.19},
        "B": {"t_weights": 30.35, "vllm_load": 4.57, "startup": 25.28},
        "C": {"t_weights": 21.34, "vllm_load": 4.54, "startup": 16.67},
    }


def _rounded(d):
    return (round(d["point"], 2), round(d["lo"], 2), round(d["hi"], 2))


def test_the_compile_cache_moves_start_up_and_not_vllms_own_loading(out):
    """B->C: 8.85 s on T_weights is 8.68 s of start-up and 0.03 s of loading, and
    that 0.03 s is indistinguishable from zero."""
    assert out["paired_triples"] == 100
    bc = out["paired"]["B->C"]
    assert _rounded(bc["t_weights"]) == (8.85, 8.37, 9.66)
    assert _rounded(bc["startup"]) == (8.68, 8.39, 8.99)
    point, lo, hi = _rounded(bc["vllm_load"])
    assert (point, lo, hi) == (0.03, -0.10, 0.18)
    assert lo < 0 < hi


def test_a_to_b_on_t_weights_is_the_interval_analysis_json_already_publishes(out):
    """One quantity, one interval: the post must not quote [.., 15.93] in one
    place and [.., 15.95] in another because two scripts seeded differently."""
    import json

    published = json.loads((REPO / "data" / "analysis.json").read_text())
    published = published["paired_A_to_B_t_weights"]
    assert _rounded(out["paired"]["A->B"]["t_weights"]) == _rounded(published)


def test_the_weight_cache_moves_mostly_loading(out):
    ab = out["paired"]["A->B"]
    assert _rounded(ab["t_weights"]) == (14.93, 13.86, 15.93)
    assert _rounded(ab["vllm_load"]) == (12.01, 11.24, 12.70)
    assert _rounded(ab["startup"]) == (2.75, 2.39, 3.04)


def test_the_s6_mark_is_request_ones_whole_latency_not_time_to_first_token(out):
    for arm in "ABC":
        assert round(out["request1"][arm]["end_to_end"], 2) == 0.30
        assert round(out["request1"][arm]["ttft"], 2) == 0.04


def test_kv_capacity_does_not_vary_within_an_arm(out):
    assert out["kv_capacity_values"] == {"A": [35792], "B": [35792], "C": [43040]}
