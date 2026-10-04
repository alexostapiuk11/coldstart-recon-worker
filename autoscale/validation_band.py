"""Replay-validation arithmetic: latency trajectories, a tolerance band from
real repeats, and a three-state verdict. Artifact-agnostic, and free of
artifact 1.

It knows nothing about how a prediction was produced or how a real run was
driven -- callers hand it arrival times and latencies. And it imports nothing
that reaches `coldstart`: artifact 4's placement simulator imports it across a
transitive boundary against artifact 1's package, and gets the band and verdict
without artifact 2's even-balancing replay. `autoscale.validation` is artifact
2's gate built on top: its pre-registered constants, its run record, and the
replay into `run_fixed_capacity`. tests/test_validation_band.py checks the
boundary in a fresh interpreter.

No pre-registered value lives here. Bin width, required repeats, the minimum
number of judged bins, the tolerated miss fraction and the band-edge tolerance
are required keywords, because each artifact pre-registers its own and a
default would let one silently inherit another's.

Five decisions, each with its rejected alternative:

- **The per-bin statistic is the p50, not the p99.** A 10 s bin holds a few
  hundred requests at the rates these artifacts drive, and the p99's sample
  floor is 500 (`autoscale.stats.MIN_SAMPLES`). A p99 trajectory would be all
  "thin".
- **A bin with any unfinished request is censored**, never summarised. The
  median of the requests that finished is biased low by exactly the slow ones
  missing. A censored bin is compared by WHETHER both sides backlogged: reality
  backlogged and the model did not is a miss -- the flattering one -- not a bin
  excluded for lack of a number.
- **Both sides censored is agreement, but the bin is not judged.** It says
  only that both backlogged, nothing about the model's latency. Counting it
  toward the minimum, or as an agreement in the miss rate, would let a run that
  matched a few bins and then backlogged pass on its tail for free.
- **The pass rule is a miss rate, not "every bin agrees".** A model that
  predicts each bin's true median exactly still falls outside the min-max of
  three repeats with probability 1/4 per bin (all three repeats land on one
  side of the median: 2 x (1/2)^3). "Every bin" therefore passes a PERFECT
  model with probability 0.75^k -- 6% at 10 bins -- and its verdict says more
  about k than about the model. A miss fraction is a rate a perfect model
  meets and a biased one does not.
- **The verdict has three states.** Zero misses over too few judged bins is
  not agreement, so fewer than `min_compared_bins` judged bins is
  "not_evaluable", as `frontier.h3_verdict` treats a gap it cannot assess.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

from autoscale.stats import MIN_SAMPLES, percentiles

__all__ = ["BandBin", "Bin", "BinVerdict", "Validation", "band", "compare", "trajectory"]


@dataclass(frozen=True)
class Bin:
    """One bin of a latency trajectory, real or predicted.

    `p50` is None unless `status` is "ok": a censored, thin or empty bin has
    no median worth reporting, and a number there -- even a flagged one --
    would be plotted and quoted like any other.
    """

    start: float
    end: float
    requests: int
    completed: int
    unfinished: int
    p50: float | None
    status: str  # "ok" | "censored" | "thin" | "empty"


@dataclass(frozen=True)
class BandBin:
    """One bin of the tolerance band: the range of the real repeats' p50s.

    `lo`/`hi` are None unless `status` is "ok". The status says WHY there is
    no range -- all repeats backlogged, the repeats disagreed about it, or too
    few requests -- because each is excluded or judged differently.
    """

    start: float
    end: float
    lo: float | None
    hi: float | None
    status: str  # "ok" | "censored" | "unstable" | "insufficient"


@dataclass(frozen=True)
class BinVerdict:
    """The verdict on one bin. `miss_seconds` is 0.0 unless the bin is a miss;
    `math.inf` for a censoring disagreement, whose true distance is unknown
    and only bounded below -- reporting it as 0 would hide the worst miss."""

    start: float
    end: float
    verdict: str
    miss_seconds: float


@dataclass(frozen=True)
class Validation:
    """The outcome of one comparison.

    `compared` counts the JUDGED bins (inside, outside, censoring
    disagreement); `agreeing` counts the judged bins that agree, so
    `compared - agreeing` is the misses (see `misses`). Both-censored bins are
    in neither -- they agree but are not judged -- and are counted in
    `detail`. No separate miss field: it would be a third number that could
    disagree with the other two.
    """

    bins: tuple[BinVerdict, ...]
    compared: int
    agreeing: int
    outcome: str  # "passed" | "failed" | "not_evaluable"
    detail: str
    max_miss_seconds: float

    @property
    def misses(self) -> int:
        return self.compared - self.agreeing


def trajectory(arrivals, latencies, *, until: float, bin_seconds: float) -> list[Bin]:
    """Per-bin p50 of latency, keyed by the arrival times the caller passes,
    over [0, until]. `latencies[i]` is None for a request that had not
    completed when the window closed.

    Keyed by arrival rather than completion because the question is how the
    fleet treated the requests that came in during each stretch of load; a
    completion-keyed bin would credit a backlog's latencies to the quiet
    period in which it finally drained.

    Arrivals outside the window and latencies that are not durations are
    refused rather than clamped or skipped: either would put a request in a
    bin it never arrived in, or a number in a median that is not a latency.
    """
    arrivals, latencies = list(arrivals), list(latencies)
    if len(arrivals) != len(latencies):
        raise ValueError(
            f"{len(arrivals)} arrivals but {len(latencies)} latencies; pairing them "
            "anyway would attribute latencies to the wrong requests"
        )
    if not math.isfinite(bin_seconds) or bin_seconds <= 0:
        raise ValueError(
            f"bin_seconds must be finite and positive, got {bin_seconds!r}; a zero or "
            "negative width has no bins to put requests in, and NaN or inf makes "
            "every bin boundary meaningless"
        )
    if not math.isfinite(until) or until <= 0:
        raise ValueError(
            f"until must be finite and positive, got {until!r}; the window bounds "
            "both the bins and which requests count as finished, so a bad one makes "
            "every bin's censoring meaningless"
        )
    for t in arrivals:
        if not (0.0 <= t <= until):  # also False for NaN
            raise ValueError(
                f"arrival {t!r} is outside the window [0, {until!r}]; a negative one "
                "would index the bins from the end and one past `until` would be "
                "clamped into the last bin -- either reports a request in a bin it "
                "never arrived in"
            )
    for lat in latencies:
        if lat is not None and not (math.isfinite(lat) and lat >= 0):
            raise ValueError(
                f"latency {lat!r} is not a finite non-negative duration; use None "
                "for a request that had not completed, because a number here goes "
                "straight into the bin's median"
            )
    n_bins = math.ceil(until / bin_seconds)
    done: list[list[float]] = [[] for _ in range(n_bins)]
    open_: list[int] = [0] * n_bins
    for t, lat in zip(arrivals, latencies, strict=True):
        # An arrival exactly at `until` belongs to the last bin, not to a bin
        # past the window that nothing else would ever report.
        i = min(int(t // bin_seconds), n_bins - 1)
        if lat is None:
            open_[i] += 1
        else:
            done[i].append(lat)
    out = []
    for i in range(n_bins):
        completed, unfinished = len(done[i]), open_[i]
        start, end = i * bin_seconds, min((i + 1) * bin_seconds, until)
        if completed + unfinished == 0:
            status, p50 = "empty", None
        elif unfinished:
            status, p50 = "censored", None
        elif completed < MIN_SAMPLES["p50"]:
            status, p50 = "thin", None
        else:
            status, p50 = "ok", percentiles(done[i], want=("p50",))["p50"]
        out.append(Bin(start, end, completed + unfinished, completed, unfinished, p50, status))
    return out


def band(trajectories: Sequence[Sequence[Bin]], *, min_repeats: int) -> list[BandBin]:
    """Per bin, the min and max p50 across real repeats of ONE schedule.

    Whether the repeats really replayed one schedule is the caller's to check
    -- it is a property of how the runs were driven, which this module does
    not see. What it does check: enough repeats, and identical binning.

    Min and max, not mean +/- k standard deviations: a k-sigma band assumes a
    distribution, and three samples cannot check one -- nor say which k means
    anything. The range assumes nothing; its cost is that it only widens as
    runs are added, which is why each artifact fixes its repeat count.
    """
    if min_repeats < 2:
        raise ValueError(
            f"min_repeats={min_repeats}; a band needs at least two runs, because "
            "one run has zero spread and would hold a model to that run's noise"
        )
    runs = [list(t) for t in trajectories]
    if len(runs) < min_repeats:
        raise ValueError(
            f"{len(runs)} repeats; the band needs at least {min_repeats}. Fewer makes "
            "it the spread of too few numbers to say anything about reproducibility"
        )
    edges = [(b.start, b.end) for b in runs[0]]
    if any([(b.start, b.end) for b in run] != edges for run in runs[1:]):
        raise ValueError(
            "repeats were binned differently; their bin edges disagree, so a column "
            "of the band would take its min and max over different stretches of time"
        )
    out = []
    for column in zip(*runs, strict=True):
        statuses = {b.status for b in column}
        start, end = column[0].start, column[0].end
        if statuses == {"ok"}:
            values = [b.p50 for b in column]
            out.append(BandBin(start, end, min(values), max(values), "ok"))
        elif statuses == {"censored"}:
            out.append(BandBin(start, end, None, None, "censored"))
        elif "censored" in statuses:
            # The real system backlogged on some repeats and not others: it
            # disagrees with itself about whether it kept up, so there is no
            # band a model could be held to.
            out.append(BandBin(start, end, None, None, "unstable"))
        else:
            out.append(BandBin(start, end, None, None, "insufficient"))
    return out


def compare(predicted: Sequence[Bin], band_bins: Sequence[BandBin], *,
            min_compared_bins: int, max_miss_fraction: float,
            edge_tolerance_seconds: float) -> Validation:
    """Hold a predicted trajectory to the band, bin by bin, and give a verdict.

    Per bin:
    - band "unstable" or "insufficient", or a prediction with no median
      (thin, empty): excluded, not judged, and reported;
    - both censored: "agree_censored" -- agreement, but not judged (see the
      module docstring: it says nothing about latency, and counting it lets a
      backlogged tail pass for free);
    - exactly one censored: "censoring_disagreement", a judged miss of
      unbounded magnitude;
    - otherwise inside iff `lo - tol <= p50 <= hi + tol`. An outside miss's
      magnitude is its distance to the nearer UNWIDENED edge: the tolerance
      absorbs clock-resolution residue at an edge, and shrinking a real miss by
      it would under-report the distance. Distance rather than a ratio,
      because a band a few hundredths of a second wide around a sub-second p50
      makes any ratio explode.

    Outcome: fewer than `min_compared_bins` judged bins is "not_evaluable";
    more than `max_miss_fraction` of the judged bins missing is "failed";
    otherwise "passed". A miss rate rather than "every bin agrees" for the
    0.75^k reason in the module docstring.

    All three thresholds are required, not defaulted: they decide when the
    evidence counts, and that is a pre-registered choice per artifact.
    """
    if min_compared_bins < 1:
        raise ValueError(
            f"min_compared_bins={min_compared_bins}; a gate that requires no "
            "comparable bins passes on no evidence at all"
        )
    if not (math.isfinite(max_miss_fraction) and 0 <= max_miss_fraction < 1):
        raise ValueError(
            f"max_miss_fraction={max_miss_fraction!r} must be finite and in [0, 1); "
            "at 1 or above every bin may miss and the gate passes any model, and a "
            "NaN compares False against the miss count, which passes any model too"
        )
    if not (math.isfinite(edge_tolerance_seconds) and edge_tolerance_seconds >= 0):
        raise ValueError(
            f"edge_tolerance_seconds={edge_tolerance_seconds!r} must be finite and "
            "non-negative; a negative one narrows the band below what the repeats "
            "showed, an infinite one widens it to everything, and a NaN makes "
            "every comparison False so every bin misses"
        )
    predicted, band_bins = list(predicted), list(band_bins)
    if len(predicted) != len(band_bins) or any(
        (p.start, p.end) != (b.start, b.end) for p, b in zip(predicted, band_bins, strict=False)
    ):
        raise ValueError(
            "predicted and band bin edges differ; they were binned differently, so "
            "each prediction would be held to the band of a different stretch of time"
        )
    tol = edge_tolerance_seconds
    verdicts = []
    for p, b in zip(predicted, band_bins, strict=True):
        if b.status in ("unstable", "insufficient"):
            verdicts.append(BinVerdict(b.start, b.end, f"excluded_{b.status}", 0.0))
        elif b.status == "censored" or p.status == "censored":
            if b.status == p.status == "censored":
                verdicts.append(BinVerdict(b.start, b.end, "agree_censored", 0.0))
            else:
                # One side kept up and the other did not. A censored latency
                # is only bounded below, so the miss has no finite magnitude
                # and is reported as unbounded rather than as zero.
                verdicts.append(BinVerdict(b.start, b.end, "censoring_disagreement", math.inf))
        elif p.status != "ok":
            verdicts.append(BinVerdict(b.start, b.end, "excluded_insufficient", 0.0))
        elif b.lo - tol <= p.p50 <= b.hi + tol:
            verdicts.append(BinVerdict(b.start, b.end, "inside", 0.0))
        else:
            miss = b.lo - p.p50 if p.p50 < b.lo else p.p50 - b.hi
            verdicts.append(BinVerdict(b.start, b.end, "outside", miss))

    judged = [v for v in verdicts if v.verdict in ("inside", "outside", "censoring_disagreement")]
    agreeing = sum(1 for v in judged if v.verdict == "inside")
    misses = len(judged) - agreeing
    max_miss = max((v.miss_seconds for v in judged), default=0.0)
    if len(judged) < min_compared_bins:
        outcome = "not_evaluable"
        detail = (f"{len(judged)} judged bins, below the {min_compared_bins} required; "
                  "too few bins to judge is not agreement")
    elif misses > max_miss_fraction * len(judged):
        outcome = "failed"
        detail = (f"{misses} of {len(judged)} judged bins miss, more than the "
                  f"{max_miss_fraction:g} allowed; largest miss {max_miss:.3g} s")
    else:
        outcome = "passed"
        detail = (f"{misses} of {len(judged)} judged bins miss, within the "
                  f"{max_miss_fraction:g} allowed")
    # Excluded and both-censored bins are named in the summary line too, not
    # only per bin: a pass over 10 of 30 bins because 20 were unstable or
    # backlogged reads very differently from a pass over 30 of 30, and the
    # one-line detail is what gets quoted.
    excluded = sum(1 for v in verdicts if v.verdict.startswith("excluded"))
    unstable = sum(1 for v in verdicts if v.verdict == "excluded_unstable")
    both = sum(1 for v in verdicts if v.verdict == "agree_censored")
    detail += (f"; {excluded} excluded ({unstable} unstable); "
               f"{both} both censored (agreement, not judged)")
    return Validation(tuple(verdicts), len(judged), agreeing, outcome, detail, max_miss)
