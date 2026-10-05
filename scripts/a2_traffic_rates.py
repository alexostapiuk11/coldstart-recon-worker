"""Print the absolute traffic rates and the validation schedule's facts.

The amendment of 2026-10-04 quotes these numbers. Spec §8's ordering rule
requires the absolute rates to be computed from the service curve and
committed BEFORE any policy sweep runs on it; this script is how they are
computed, so the amendment can be checked by re-running it.
"""

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from autoscale.measured_curve import DEFAULT_PATH, load_measured_curve
from autoscale.traffic import saturation_rps, spike_shape
from autoscale.validation_schedule import (
    VALIDATION_DRAIN_SECONDS,
    VALIDATION_KIND,
    VALIDATION_REPLICAS,
    VALIDATION_SEED,
    VALIDATION_UNTIL,
    build_schedule,
    schedule_facts,
    validation_shape,
)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--curve", default=str(REPO / DEFAULT_PATH))
    args = ap.parse_args(argv)
    curve = load_measured_curve(args.curve).curve
    one = spike_shape(curve, VALIDATION_KIND)
    val = validation_shape(curve, replicas=VALIDATION_REPLICAS, kind=VALIDATION_KIND)
    schedule = build_schedule(curve, replicas=VALIDATION_REPLICAS, kind=VALIDATION_KIND,
                              until=VALIDATION_UNTIL, drain=VALIDATION_DRAIN_SECONDS,
                              seed=VALIDATION_SEED)
    facts = schedule_facts(schedule, curve, replicas=VALIDATION_REPLICAS, until=VALIDATION_UNTIL,
                           drain=VALIDATION_DRAIN_SECONDS)
    rows = {
        "saturation_rps": saturation_rps(curve),
        "baseline_rps_one_replica": one.baseline_rate,
        "peak_rps_one_replica": one.baseline_rate * one.k,
        "k": one.k,
        "validation_replicas": VALIDATION_REPLICAS,
        "validation_baseline_rps": val.baseline_rate,
        "validation_peak_rps": val.baseline_rate * val.k,
        "validation_requests": facts["requests"],
        "validation_last_arrival_s": facts["last_arrival_s"],
        "validation_peak_bin_rps": facts["peak_bin_rps"],
        "validation_bins_with_20_requests": facts["bins_with_20_requests"],
        "validation_predicted_p50_s": facts["predicted_p50_s"],
        "validation_predicted_p99_s": facts["predicted_p99_s"],
        "validation_predicted_unfinished": facts["predicted_unfinished"],
    }
    for key, value in rows.items():
        print(f"{key} {value:.4f}" if isinstance(value, float) else f"{key} {value}")


if __name__ == "__main__":
    main()
