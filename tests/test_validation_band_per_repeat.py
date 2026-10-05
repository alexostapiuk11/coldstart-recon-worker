"""`compare_per_repeat`: each repeat held to its own prediction (amendment 2026-10-05, third)."""

import math
import random

import pytest

from autoscale.validation_band import Bin, band, compare, compare_per_repeat

KW = {"min_compared_bins": 3, "max_miss_fraction": 0.5, "edge_tolerance_seconds": 0.001}


def _bin(i, status, p50=None):
    n = {"ok": 100, "thin": 3, "empty": 0, "censored": 100}[status]
    unfinished = 5 if status == "censored" else 0
    return Bin(i * 10.0, (i + 1) * 10.0, n, n - unfinished, unfinished,
               p50 if status == "ok" else None, status)


def _traj(spec):
    return [_bin(i, s, p) for i, (s, p) in enumerate(spec)]


def test_with_one_shared_prediction_it_is_exactly_the_signed_rule():
    """The reduction the amendment states: identical predictions give the
    signed min-max verdict, bin for bin, including every censoring case."""
    rng = random.Random(7)
    statuses = ["ok", "ok", "ok", "censored", "thin", "empty"]
    for _ in range(400):
        n_bins = 12
        pred = _traj([(rng.choice(statuses), round(rng.uniform(0.3, 0.7), 3))
                      for _ in range(n_bins)])
        reals = [_traj([(rng.choice(statuses), round(rng.uniform(0.3, 0.7), 3))
                        for _ in range(n_bins)]) for _ in range(3)]
        signed = compare(pred, band(reals, min_repeats=3), **KW)
        mine = compare_per_repeat([(r, pred) for r in reals], min_repeats=3, **KW)
        assert mine == signed


def test_a_bin_misses_only_when_every_repeat_is_on_the_same_side():
    real = [_traj([("ok", 0.50)] * 3), _traj([("ok", 0.52)] * 3), _traj([("ok", 0.55)] * 3)]
    above = [_traj([("ok", 0.40)] * 3), _traj([("ok", 0.45)] * 3), _traj([("ok", 0.50)] * 3)]
    v = compare_per_repeat(list(zip(real, above, strict=True)), min_repeats=3, **KW)
    assert {b.verdict for b in v.bins} == {"outside"}
    # residuals 0.10, 0.07, 0.05: the miss is the smallest, 0.05 s
    assert v.bins[0].miss_seconds == pytest.approx(0.05)
    mixed = [_traj([("ok", 0.45)] * 3), _traj([("ok", 0.60)] * 3), _traj([("ok", 0.50)] * 3)]
    v = compare_per_repeat(list(zip(real, mixed, strict=True)), min_repeats=3, **KW)
    assert {b.verdict for b in v.bins} == {"inside"} and v.outcome == "passed"


def test_censoring_cases():
    ok, cen = ("ok", 0.5), ("censored", None)

    def one(reals, preds):
        pairs = [(_traj([r]), _traj([p])) for r, p in zip(reals, preds, strict=True)]
        return compare_per_repeat(pairs, min_repeats=3, min_compared_bins=1,
                                  max_miss_fraction=0.5, edge_tolerance_seconds=0.001).bins[0]

    assert one([cen, cen, cen], [cen, cen, cen]).verdict == "agree_censored"
    assert one([cen, cen, cen], [cen, ok, cen]).verdict == "censoring_disagreement"
    assert one([ok, ok, ok], [ok, cen, ok]).verdict == "censoring_disagreement"
    assert math.isinf(one([ok, ok, ok], [ok, cen, ok]).miss_seconds)
    assert one([cen, ok, ok], [ok, ok, ok]).verdict == "excluded_unstable"
    assert one([ok, ("thin", None), ok], [ok, ok, ok]).verdict == "excluded_insufficient"
    assert one([ok, ok, ok], [ok, ("empty", None), ok]).verdict == "excluded_insufficient"


def test_too_few_repeats_or_mismatched_bins_are_refused():
    t = _traj([("ok", 0.5)] * 3)
    with pytest.raises(ValueError, match="repeats"):
        compare_per_repeat([(t, t), (t, t)], min_repeats=3, **KW)
    short = _traj([("ok", 0.5)] * 2)
    with pytest.raises(ValueError, match="edges"):
        compare_per_repeat([(t, t), (t, short), (t, t)], min_repeats=3, **KW)
    with pytest.raises(ValueError, match="edges"):
        compare_per_repeat([(t, t), (short, short), (t, t)], min_repeats=3, **KW)


def test_the_thresholds_are_checked_as_compare_checks_them():
    t = _traj([("ok", 0.5)] * 3)
    with pytest.raises(ValueError, match="max_miss_fraction"):
        compare_per_repeat([(t, t)] * 3, min_repeats=3, min_compared_bins=1,
                           max_miss_fraction=1.0, edge_tolerance_seconds=0.0)
