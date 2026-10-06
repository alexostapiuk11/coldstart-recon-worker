"""Every number the post quotes, formatted once from data/a2/post-analysis.json."""

import copy
import json
from pathlib import Path

import pytest

from autoscale import post_numbers_a2
from autoscale.post_numbers_a2 import numbers

A = json.loads((Path(__file__).resolve().parents[1] / "data" / "a2" / "post-analysis.json")
               .read_text())


def test_the_validation_verdicts_are_stated_with_their_bins():
    n = numbers(A)
    assert n["attempt1_misses"] == "34 of 37 judged bins"
    assert n["attempt2_misses"] == "37 of 37 judged bins"
    assert n["attempt2_max_miss"] == "0.060 s"
    assert n["attempt1_max_miss"] == "2.59 s"


def test_the_load_balancer_ceiling_is_a_rate():
    n = numbers(A)
    assert n["lb_ceiling_rate"].endswith(" req/s") and n["lb_ceiling_rate"].startswith("1")
    assert n["lb_ceiling_rate"] == "17.1 req/s"
    assert n["lb_ceiling_offered"] == "25, 50 and 100 req/s"


def test_every_value_is_a_non_empty_string():
    assert all(isinstance(v, str) and v for v in numbers(A).values())


def test_seconds_use_three_decimals_below_one_and_two_from_one_up():
    assert post_numbers_a2._s(0.0596) == "0.060 s"
    assert post_numbers_a2._s(0.999) == "0.999 s"
    assert post_numbers_a2._s(1.0) == "1.00 s"
    # rounded first, then the decimals chosen: 0.9996 is "1.00", never "1.000"
    assert post_numbers_a2._s(0.9996) == "1.00 s"
    assert post_numbers_a2._s(0.9994) == "0.999 s"
    assert post_numbers_a2._s_span(0.9996, 1.5) == "1.00–1.50 s"
    assert post_numbers_a2._s(14.4406) == "14.44 s"


def test_counts_carry_a_thousands_comma():
    assert post_numbers_a2._count(3095) == "3,095"
    assert post_numbers_a2._count(37) == "37"
    assert post_numbers_a2._count(3094.9999999999936) == "3,095"


def test_percentages_are_whole_numbers():
    assert post_numbers_a2._pct(0.144) == "14%"
    assert post_numbers_a2._pct(0.146) == "15%"
    assert post_numbers_a2._pct(0.9867) == "99%"


def test_rates_have_one_decimal():
    assert post_numbers_a2._rate(277.7695) == "277.8 req/s"


def test_a_range_collapses_when_both_ends_format_alike():
    assert post_numbers_a2._span([0.8745, 0.8705, 0.8666], ".2f") == "0.87"
    assert post_numbers_a2._span([0.8414, 0.8223, 0.8342], ".2f") == "0.82–0.84"


def test_engine_and_calibrated_residuals_are_stated_in_their_own_direction():
    n = numbers(A)
    # a latency ratio below 1 is how much LOWER the latency was, not a speed-up
    assert n["attempt1_latency_below_prediction_pct"] == "14%"
    assert n["attempt2_latency_above_prediction_pct"] == "13%"
    assert not [k for k in n if "faster" in k or "slower" in k]


def test_a_latency_ratio_on_the_wrong_side_of_one_is_refused_not_printed_negative():
    a = copy.deepcopy(A)
    a["validation"]["engine"]["typical_residual"]["median_ratio_real_over_predicted"] = 1.05
    with pytest.raises(ValueError, match="negative percentage"):
        numbers(a)
    a = copy.deepcopy(A)
    a["validation"]["calibrated"]["typical_residual"]["median_ratio_real_over_predicted"] = 0.9
    with pytest.raises(ValueError, match="negative percentage"):
        numbers(a)
    a = copy.deepcopy(A)
    a["host_speed"]["exploratory"]["maxseqs128"]["daps3haubwrzbn"]["32"]["ratio"] = 1.02
    with pytest.raises(ValueError, match="negative percentage"):
        numbers(a)


def test_void_repeats_and_calibrated_host_ratios_are_stated():
    n = numbers(A)
    assert n["attempt1_void_repeats"] == "1"
    assert n["attempt2_host_ratio_64"] == "0.87"
    assert n["attempt2_host_ratio_128"] == "0.82–0.84"


def test_probe_1_peaks_publish_the_typical_value_and_the_maximum():
    n = numbers(A)
    # step 100 worker 2 reads 5, every other reading is 4
    assert n["probe1_peak_per_worker"] == "4"
    assert n["probe1_peak_per_worker_max"] == "5"
    assert n["probe1_errors_100"] == "449"
    assert n["probe1_client_p50_100"] == "52.00 s"
    assert n["probe1_server_p50_100"] == "0.311 s"


def test_a_tie_for_the_most_common_peak_is_refused_not_picked():
    a = copy.deepcopy(A)
    steps = a["load_balancer"]["probes"]["1"]["steps"]
    for step, peaks in {"25": (6, 6), "50": (6, 4), "100": (4, 4)}.items():
        for w, peak in zip(("worker 1", "worker 2"), peaks, strict=True):
            steps[step]["per_worker_concurrency"][w]["max"] = peak  # three 6s, three 4s
    with pytest.raises(ValueError, match="tie"):
        numbers(a)


def test_probes_2_and_3_are_stated_against_what_was_offered():
    n = numbers(A)
    assert n["probe2_non_200_total"] == "13"
    assert n["probe2_delivered_300"] == "277.7 req/s"
    assert n["probe3_delivered_450"] == "350.4 req/s"
    assert n["offered_300"] == "300 req/s" and n["offered_450"] == "450 req/s"
    assert [n[f"probe3_worker1_share_{s}"] for s in (25, 50, 100, 200, 300, 450)] == [
        "100%", "100%", "100%", "99%", "70%", "51%"]
    assert n["probe3_peak_worker1_450"] == "128" and n["probe3_peak_worker2_450"] == "128"


def test_probes_4_and_5_deliveries_and_the_502_first_attempts_are_stated():
    n = numbers(A)
    assert n["probe4_delivered_150"] == "108.7 req/s" and n["probe4_delivered_180"] == "114.3 req/s"
    assert n["probe5_delivered_180"] == "156.7 req/s" and n["probe5_delivered_210"] == "210.7 req/s"
    assert n["lb_502_first_attempt_count"] == "37"
    assert n["lb_502_first_attempt_median"] == "2.64 s"
    assert n["lb_502_first_attempt_max"] == "14.09 s"


def test_the_stall_share_is_a_range_over_the_three_repeats():
    n = numbers(A)
    assert n["stall_share_range"] == "21%–35%"
    assert [n[f"stall_share_repeat_{i}"] for i in (1, 2, 3)] == ["26%", "35%", "21%"]


def test_the_stall_share_range_says_it_includes_the_void_repeat():
    n = numbers(A)
    assert n["stall_share_includes_void_repeat"].startswith("yes, repeat 1 (void: 2 requests")
    a = copy.deepcopy(A)
    for r in a["load_balancer"]["stall_share"]["repeats"]:
        r["void"] = []
    assert numbers(a)["stall_share_includes_void_repeat"].startswith("no")


def test_the_host_speed_ratios_are_stated_as_ratios_and_as_percent_below_the_curve():
    n = numbers(A)
    assert n["curve_host_id"] == "ozhetwnhompob9"
    assert n["maxseqs128_host_id"] == "daps3haubwrzbn"
    assert [n[f"maxseqs128_ratio_{c}"] for c in (32, 64, 128)] == ["0.93", "0.94", "0.90"]
    assert [n[f"maxseqs128_latency_below_curve_pct_{c}"] for c in (32, 64, 128)] == [
        "7%", "6%", "10%"]
    assert not [k for k in n if "_faster_pct_" in k]
    assert [n[f"maxseqs256_ratio_{c}"] for c in (32, 64, 128)] == ["0.96", "0.93", "0.90"]
    assert n["attempt2_host_id"] == "sef5s24viyecyr"
    assert not [k for k in n if k.startswith("host_")]  # one key per ratio, no host-named copy


def test_the_gaps_are_stated_per_factor_and_tag_with_the_interval_at_factor_one():
    n = numbers(A)
    assert n["gap_x1_step_a"] == "0.082 s" and n["gap_x1_ramp_c"] == "10.87 s"
    assert n["gap_x1_step_a_interval"] == "0.050–1.06 s"
    assert n["gap_x088_ramp_c"] == "3.42 s" and n["gap_x112_ramp_c"] == "16.71 s"
    assert "gap_x088_step_a_interval" not in n


def test_the_simulator_hypotheses_all_read_fails():
    n = numbers(A)
    for key in ("h1", "h2", "h4", "h2_sensitivity",
                "h3_x1", "h3_x088", "h3_x112"):
        assert n[key] == "fails", key
    assert n["h2_step_a"] == "holds" and n["h2_step_c"] == "fails"
    assert n["h2_ramp_a"] == "fails" and n["h2_ramp_c"] == "fails"


def test_a_partial_h3_reads_partial():
    a = copy.deepcopy(A)
    a["simulator"]["h3"]["1"].update(holds=False, partial=True)
    assert numbers(a)["h3_x1"] == "partial"


def test_the_budget_and_the_reached_p99_and_cost_per_sweep_and_signal():
    n = numbers(A)
    assert n["budget"] == "3,095 replica-seconds"
    assert n["reached_step_a_queue_depth_p99"] == "14.44 s"
    assert n["reached_step_a_queue_depth_cost"] == "880 replica-seconds"
    assert n["reached_ramp_c_utilization_p99"] == "0.554 s"
    assert n["reached_ramp_c_utilization_cost"] == "3,095 replica-seconds"
    assert n["reached_ramp_a_in_flight_concurrency_cost"] == "2,875 replica-seconds"


def test_the_censoring_fact_is_stated():
    n = numbers(A)
    assert n["utilization_policies_at_cap"] == "19 of 19"
    assert n["utilization_scale_up_max_threshold"] == "0.95"
    assert n["curve_gpu_util"] == "1.0"


def test_a_utilization_run_below_the_cap_is_refused_not_miscounted():
    a = copy.deepcopy(A)
    a["simulator"]["h2_censoring"]["per_sweep"]["arm A"]["every_utilization_run_at_cap_cost"] = False
    with pytest.raises(ValueError, match="at the cap"):
        numbers(a)


def test_with_no_spend_no_spend_key_is_emitted():
    assert A["spend"] is None
    assert not [k for k in numbers(A) if k.startswith("spend")]


def test_a_recorded_spend_is_refused_until_task_13_defines_its_keys():
    a = copy.deepcopy(A)
    a["spend"] = {"total_usd": 1.0}
    with pytest.raises(NotImplementedError, match="Task 13"):
        numbers(a)


def test_the_h2_margin_is_signed_milliseconds_and_the_spread_is_a_range():
    n = numbers(A)
    assert n["h2_margin_step_a"] == "+43 ms"
    assert n["h2_margin_vs_best_other_step_a"] == "+82 ms"
    assert n["h2_margin_step_c"].startswith("-3,955")
    assert n["utilization_at_cap_p99_spread_step_a"] == "14.53–15.52 s"
    assert n["utilization_at_cap_p99_median_step_a"] == "14.73 s"
    assert n["utilization_at_cap_policies_step_a"] == "19"
    assert n["utilization_at_cap_p99_spread_ramp_c"] == "0.554–0.568 s"


def test_the_iso_cost_slice_is_stated_per_sweep_with_the_others_highest_cost():
    n = numbers(A)
    for sweep in ("step_a", "step_c", "ramp_a", "ramp_c"):
        assert n[f"iso_cost_slice_constrains_others_{sweep}"] == "no"
    assert n["iso_cost_slice_constrains_others"] == "no"
    assert n["others_highest_frontier_cost_ramp_a"] == "2,875 replica-seconds"
    a = copy.deepcopy(A)
    a["simulator"]["h2_noise"]["per_sweep"]["arm C"]["iso_cost_slice_constrains_others"] = True
    n = numbers(a)
    assert n["iso_cost_slice_constrains_others_step_c"] == "yes"
    assert n["iso_cost_slice_constrains_others"] == "yes, in step_c"


def test_a_missing_calibrated_host_names_what_it_would_mislabel():
    a = copy.deepcopy(A)
    a["host_speed"]["calibrated_ratios_by_host"]["second_host"] = {}
    with pytest.raises(ValueError, match="host"):
        numbers(a)


def test_an_unknown_sweep_name_is_refused_with_its_consequence():
    a = copy.deepcopy(A)
    a["simulator"]["h2"]["per_sweep"]["arm Z"] = True
    with pytest.raises(ValueError, match="arm Z"):
        numbers(a)


def test_the_arms_cold_start_medians_are_stated_in_seconds():
    n = numbers(A)
    cs = A["simulator"]["cold_start"]
    assert n["cold_start_median_a"] == f"{cs['A']['median']:.2f} s"
    assert n["cold_start_median_c"] == f"{cs['C']['median']:.2f} s"


def test_the_rate_and_the_default_cap_are_stated_in_dollars():
    n = numbers(A)
    assert n["money_rate"] == "$0.74/h"
    assert n["spikes_per_day"] == "24"
    cap = A["money"]["load_balancer_cap"]
    assert n["money_per_million_scaler4"] == f"${cap['scaler_4']['dollars_per_million']:.2f}"
    assert n["money_per_million_scaler128"] == f"${cap['scaler_128']['dollars_per_million']:.2f}"
    assert n["money_scaler_ratio"] == f"{round(cap['ratio'])}×"
    assert n["money_scaler_ratio"] == "18×"
    assert n["money_per_million_scaler4"] == "$24.04"


def test_the_signal_choice_is_stated_per_spike_and_per_day_with_its_label():
    n = numbers(A)
    assert n["money_spike_queue_depth_step_a"] == "$0.18"
    assert n["money_spike_in_flight_step_a"] == "$0.52"
    assert n["money_spike_utilization_step_a"] == "$0.64"
    assert n["money_day_queue_depth_step_a"] == "$4.34"
    assert n["money_day_utilization_step_a"] == "$15.27"
    assert n["money_signal_label"] == ("UNVALIDATED: simulator failed validation twice; "
                                       "p99s differ by 82 ms")


def test_dollars_take_cents_and_four_decimals_below_a_cent():
    assert post_numbers_a2._dollars(24.06) == "$24.06"
    assert post_numbers_a2._dollars(0.18) == "$0.18"
    assert post_numbers_a2._dollars(0.01) == "$0.01"
    assert post_numbers_a2._dollars(0.0002) == "$0.0002"
    assert post_numbers_a2._dollars(1234.5) == "$1,234.50"
    with pytest.raises(ValueError, match="positive"):
        post_numbers_a2._dollars(0.0)


def test_a_money_section_without_the_unvalidated_label_is_refused():
    a = copy.deepcopy(A)
    a["money"]["signal_choice"]["label"] = "p99s differ by 82 ms"
    with pytest.raises(ValueError, match="UNVALIDATED"):
        numbers(a)


def test_a_signal_the_money_keys_do_not_name_is_refused():
    a = copy.deepcopy(A)
    a["money"]["signal_choice"]["per_signal"]["mystery"] = copy.deepcopy(
        a["money"]["signal_choice"]["per_signal"]["queue_depth"])
    with pytest.raises(ValueError, match="mystery"):
        numbers(a)
