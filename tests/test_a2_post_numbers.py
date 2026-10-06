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
    # the magnitude picks the decimals, so a negative takes the positive's format
    assert post_numbers_a2._s(-6.1977) == "-6.20 s"
    assert post_numbers_a2._s(-0.0596) == "-0.060 s"


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
    assert n["attempt1_void_repeats"] == "one repeat was void"
    assert n["attempt2_void_repeats"] == "no repeat was void"
    assert n["attempt2_host_ratio_64"] == "0.87 at 64"
    assert n["attempt2_host_ratio_128"] == "0.82–0.84 at 128"


def test_void_repeats_read_as_a_phrase_for_any_count():
    # A bare "1" or "0" occurs hundreds of times in the post, so the verbatim check could
    # never fail for it; the phrase occurs once, and reads without a forced digit.
    for count, want in ((0, "no repeat was void"), (1, "one repeat was void"),
                        (3, "3 repeats were void")):
        a = copy.deepcopy(A)
        a["validation"]["calibrated"]["void_repeats"] = count
        assert numbers(a)["attempt2_void_repeats"] == want


def test_probe_1_peaks_publish_the_typical_value_and_the_maximum():
    n = numbers(A)
    # step 100 worker 2 reads 5, every other reading is 4
    assert n["probe1_peak_per_worker"] == "per-worker peak in flight was 4"
    assert n["probe1_peak_per_worker_max"] == "except one reading of 5"
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


def test_probe_1_with_no_reading_above_the_typical_peak_says_so():
    a = copy.deepcopy(A)
    for s in a["load_balancer"]["probes"]["1"]["steps"].values():
        for w in s["per_worker_concurrency"].values():
            w["max"] = 4
    assert numbers(a)["probe1_peak_per_worker_max"] == "with no reading above it"


def test_probes_2_and_3_are_stated_against_what_was_offered():
    n = numbers(A)
    assert n["probe2_non_200_total"] == "13 such 502s"
    assert n["probe2_delivered_300"] == "277.7 req/s"
    assert n["probe3_delivered_450"] == "350.4 req/s"
    assert n["offered_300"] == "300 req/s" and n["offered_450"] == "450 req/s"
    assert n["probe3_worker1_share_by_step"] == (
        "from 25 to 450 req/s: 100%, 100%, 100%, 99%, 70%, 51%")
    assert not [k for k in n if k.startswith("probe3_worker1_share_") and k[-1].isdigit()]
    assert n["probe3_peaks_450"] == "both workers reach 128 in flight"
    a = copy.deepcopy(A)
    a["load_balancer"]["probes"]["3"]["steps"]["450"]["per_worker_concurrency"]["worker 2"][
        "max"] = 120
    assert numbers(a)["probe3_peaks_450"] == "worker 1 reach 128 and worker 2 reach 120 in flight"


def test_probes_4_and_5_deliveries_and_the_502_first_attempts_are_stated():
    n = numbers(A)
    assert n["probe4_delivered_150"] == "108.7 req/s" and n["probe4_delivered_180"] == "114.3 req/s"
    assert n["probe5_delivered_180"] == "156.7 req/s" and n["probe5_delivered_210"] == "210.7 req/s"
    assert n["lb_502_first_attempt_count"] == "37 first attempts"
    assert n["lb_502_first_attempt_median"] == "2.64 s"
    assert n["lb_502_first_attempt_max"] == "14.09 s"


def test_the_stall_share_is_a_range_over_the_three_repeats():
    n = numbers(A)
    assert n["stall_share_range"] == "21%–35%"


def test_the_stall_share_range_says_it_includes_the_void_repeat():
    # Said from the data, in one plain clause: which repeat was void and what voided it.
    n = numbers(A)
    assert n["stall_share_includes_void_repeat"] == "repeat 1 was void: 2 requests got 400s"
    a = copy.deepcopy(A)
    for r in a["load_balancer"]["stall_share"]["repeats"]:
        r["void"] = []
    assert numbers(a)["stall_share_includes_void_repeat"] == "no repeat was void"


def test_the_repeats_refused_for_send_jitter_are_named_with_their_jitter():
    n = numbers(A)
    assert n["stall_jitter_refused"] == "repeats 2 and 3 were refused for send jitter (0.591 s and 0.806 s)"


def test_the_stall_share_is_split_into_outside_and_inside_the_engine():
    n = numbers(A)
    # One table row per repeat: client-side share, outside the engine, of those also
    # backlogged in the engine. A bare "35%" cell would also match the range "21%–35%".
    assert [n[f"stall_row_repeat_{i}"] for i in (1, 2, 3)] == [
        "| 1 | 26% | 16% | 75% |", "| 2 | 35% | 19% | 90% |", "| 3 | 21% | 10% | 77% |"]
    assert not [k for k in n if k.startswith(("stall_share_repeat_", "stall_outside_engine",
                                              "stall_engine_backlog"))]
    assert n["stall_server_backlog_s"] == "1.50 s"


def test_the_host_speed_ratios_are_stated_as_ratios_and_as_percent_below_the_curve():
    n = numbers(A)
    assert n["curve_host_id"] == "ozhetwnhompob9"
    assert n["maxseqs128_host_id"] == "daps3haubwrzbn"
    # One table row per level: --max-num-seqs 128's ratio (percent lower), then 256's.
    assert [n[f"remeasure_row_{c}"] for c in (32, 64, 128)] == [
        "| 32 | 0.93 (7% lower) | 0.96 (4% lower) |",
        "| 64 | 0.94 (6% lower) | 0.93 (7% lower) |",
        "| 128 | 0.90 (10% lower) | 0.90 (10% lower) |"]
    assert not [k for k in n if "_faster_pct_" in k or "_ratio_" in k and "maxseqs" in k]
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
    # Each verdict is anchored to what it is about, so it occurs once in the post: a bare
    # "fails" occurs a dozen times and the verbatim check could not fail for it.
    assert (n["h1"], n["h2"], n["h3"], n["h4"]) == ("H1 fails", "H2 fails", "H3 fails", "H4 fails")
    assert n["h2_sensitivity"] == "on the sensitivity arm it fails"
    assert (n["h3_x088"], n["h3_x1"], n["h3_x112"]) == (
        "x0.88 | fails", "x1.00 | fails", "x1.12 | fails")
    assert n["h2_step_a"] == "step, arm A | holds" and n["h2_step_c"] == "step, arm C | fails"
    assert n["h2_ramp_a"] == "ramp, arm A | fails" and n["h2_ramp_c"] == "ramp, arm C | fails"


def test_a_partial_h3_reads_partial():
    a = copy.deepcopy(A)
    a["simulator"]["h3"]["1"].update(holds=False, partial=True)
    assert numbers(a)["h3_x1"] == "x1.00 | partial"
    assert numbers(a)["h3"] == "H3 holds only in part"


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
    assert n["utilization_scale_up_max_threshold"] == "the highest of which is 0.95"
    assert n["curve_gpu_util"] == "GPU utilisation reads 1.0"


def test_a_utilization_run_below_the_cap_is_refused_not_miscounted():
    a = copy.deepcopy(A)
    a["simulator"]["h2_censoring"]["per_sweep"]["arm A"]["every_utilization_run_at_cap_cost"] = False
    with pytest.raises(ValueError, match="at the cap"):
        numbers(a)


def test_with_no_spend_no_spend_key_is_emitted():
    a = copy.deepcopy(A)
    a["spend"] = None
    assert not [k for k in numbers(a) if k.startswith("spend")]


def test_the_spend_is_stated_in_dollars_hours_and_endpoints():
    n = numbers(A)
    assert n["spend_total_a2"] == "$6.07"
    assert n["spend_hours_a2"] == "5.5 hours of worker time"
    assert n["spend_endpoints_a2"] == "4 endpoints"


def test_a_money_rate_other_than_the_billed_one_is_refused():
    a = copy.deepcopy(A)
    a["money"]["gpu_hourly_rate"] = 0.74
    with pytest.raises(ValueError, match="billed"):
        numbers(a)


def test_the_h2_margin_is_signed_milliseconds_and_the_spread_is_a_range():
    n = numbers(A)
    assert n["h2_margin_step_a"] == "+43 ms"
    assert n["h2_margin_vs_best_other_step_a"] == "+82 ms"
    assert n["h2_margin_step_c"].startswith("-3,955")
    assert n["utilization_at_cap_p99_spread_step_a"] == "14.53–15.52 s"
    assert n["utilization_at_cap_p99_median_step_a"] == "14.73 s"
    assert n["utilization_at_cap_policies"] == "utilisation's 19 at-cap policies"
    assert not [k for k in n if k.startswith("utilization_at_cap_policies_")]
    assert n["utilization_at_cap_p99_spread_ramp_c"] == "0.554–0.568 s"


def test_the_iso_cost_slice_is_stated_per_sweep_with_the_others_highest_cost():
    n = numbers(A)
    # One sentence over all four sweeps; the per-sweep "no"s it summarises were bare
    # words the verbatim check could not fail for.
    assert n["iso_cost_slice_constrains_others"] == (
        "In no sweep does the slice constrain either of them")
    assert not [k for k in n if k.startswith("iso_cost_slice_constrains_others_")]
    assert n["others_highest_frontier_cost_ramp_a"] == "2,875 replica-seconds"
    a = copy.deepcopy(A)
    a["simulator"]["h2_noise"]["per_sweep"]["arm C"]["iso_cost_slice_constrains_others"] = True
    a["simulator"]["h2_noise"]["per_sweep"]["ramp arm A"]["iso_cost_slice_constrains_others"] = True
    assert numbers(a)["iso_cost_slice_constrains_others"] == (
        "The slice constrains them in 2 sweeps: step, arm C; ramp, arm A")


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
    assert n["money_rate"] == "$1.11/h"
    assert n["spikes_per_day"] == "24 per day"
    cap = A["money"]["load_balancer_cap"]
    assert n["money_per_million_scaler4"] == f"${cap['scaler_4']['dollars_per_million']:.2f}"
    assert n["money_per_million_scaler128"] == f"${cap['scaler_128']['dollars_per_million']:.2f}"
    assert n["money_scaler_ratio"] == f"{round(cap['ratio'])}×"
    assert n["money_scaler_ratio"] == "18×"
    assert n["money_per_million_scaler4"] == "$36.02"
    assert n["money_per_million_scaler128"] == "$2.05"


def test_the_signal_choice_is_stated_per_spike_and_per_day_with_its_label():
    n = numbers(A)
    assert n["money_spike_queue_depth_step_a"] == "$0.27"
    assert n["money_spike_in_flight_step_a"] == "$0.78"
    assert n["money_spike_utilization_step_a"] == "$0.95"
    assert n["money_day_queue_depth_step_a"] == "$6.50"
    assert n["money_day_utilization_step_a"] == "$22.87"
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


def test_the_engine_in_flight_past_its_cap_is_stated_per_attempt():
    n = numbers(A)
    assert n["attempt1_engine_over_cap_range"] == "33%–59%"
    assert n["attempt1_engine_max_in_flight"] == "512 in attempt one"
    assert n["attempt2_engine_over_cap_range"] == "6%–17%"
    assert n["attempt2_engine_max_in_flight"] == "452–503 in attempt two"


def test_attempt_1s_most_negative_raw_residual_and_void_stamp_count():
    n = numbers(A)
    assert n["attempt1_min_residual"] == "-6.20 s"
    assert n["attempt1_void_200_without_stamp"] == "64,784"


def test_the_502s_are_stated_as_fast_and_slow_with_their_ranges():
    n = numbers(A)
    assert n["lb_502_fast"] == "17 failed after 0.109–0.399 s"
    assert n["lb_502_slow"] == "20 failed after 2.50–14.09 s"
    assert not [k for k in n if k.startswith(("lb_502_fast_", "lb_502_slow_"))]
    assert n["probe2_502_span"] == "0.124–0.284 s"


def test_the_probe_workers_hosts_and_engine_version_are_counts():
    n = numbers(A)
    assert n["probes_1_to_3_distinct_workers"] == "6 workers in all"
    assert n["hosts_in_records"] == (
        "6 hosts appear in the curve, host re-measurement and validation records")
    assert n["hosts_measured_for_speed"] == "3 of them were measured for speed"
    assert n["engine_version"] == "vLLM 0.27.1"


def test_attempt_1s_host_at_about_100_in_flight_is_stated_beside_its_references():
    n = numbers(A)
    assert n["attempt1_in_flight_band"] == "90 to 110"
    assert n["attempt1_latency_at_100"] == "0.494 s"
    assert n["maxseqs128_latency_at_100"] == "0.487 s"
    assert n["curve_latency_at_100"] == "0.533 s"


def test_the_cold_start_counts_and_the_cost_spans_across_sweeps():
    n = numbers(A)
    assert (n["cold_start_n_a"], n["cold_start_n_c"], n["campaign_runs"]) == (
        "99 for arm A", "100 for arm C", "of its 300 cold starts")
    assert n["queue_depth_cost_span"] == "640–895 replica-seconds"
    assert n["others_cost_span"] == "2,320–3,095 replica-seconds"


def test_the_simulator_identity_reads_as_phrases():
    n = numbers(A)
    assert n["repetitions"] == "30 repetitions per policy"
    assert n["max_replicas"] == "up to 12 replicas"
    assert n["money_p99_spread_step_a"] == "reached p99s are within 82 ms of each other"


def test_the_list_price_and_the_reported_cost_per_hour_are_context():
    n = numbers(A)
    assert n["money_list_rate"] == "$1.10/h"
    assert n["money_reported_rate"] == "$0.74/h"
    assert n["money_billed_above_list"] == "1% above"
    # The 1.5x framing priced everything at the reported rate; it is gone with that rate.
    assert "money_list_ratio" not in n


def test_a_billed_rate_at_or_below_the_list_price_is_not_called_above_it():
    a = copy.deepcopy(A)
    a["money"]["billed_over_list"] = 0.99
    with pytest.raises(ValueError, match="above"):
        numbers(a)
