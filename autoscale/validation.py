"""Artifact 2's open-loop validation gate (spec §10), GPU-free.

Pin capacity, drive a real transient load from a fixed arrival SCHEDULE,
replay that same schedule into `run_fixed_capacity`, and compare the predicted
latency trajectory against what happened. Three real repeats of the schedule
set the tolerance band -- "a model cannot be required to be more reproducible
than the system it models". The load driver is plan 2b's.

This module holds what is artifact 2's: the pre-registered constants, the
`RealRun` record, the checks that the repeats really replayed one schedule, and
the replay into the simulator. The band and verdict arithmetic is
`autoscale.validation_band`, kept separate because `autoscale.sim` -- imported
here -- pulls in `coldstart`, and artifact 4 needs that arithmetic without it.

Bins are keyed by SCHEDULED arrival time, not observed send time: every repeat
and the prediction then place exactly the same requests in the same bins, and
driver jitter cannot move a request across a boundary and manufacture a
difference no system produced. Jitter is bounded instead, and a run exceeding
the bound is refused -- it replayed a different trace, so it tests nothing.

The constants are fixed by docs/experiment-a2.md ("Validation gate — pass
rule"). Changing one after the first real validation run is an amendment.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

from autoscale.service import ServiceCurve
from autoscale.sim import run_fixed_capacity
from autoscale.validation_band import BandBin, Bin, Validation, band, compare, trajectory

__all__ = [
    "BIN_SECONDS",
    "MAX_SEND_JITTER_SECONDS",
    "MIN_COMPARED_BINS",
    "MIN_REPEATS",
    "RealRun",
    "predicted_trajectory",
    "tolerance_band",
    "validate",
]

MIN_REPEATS = 3  # spec §10: "Three real repeats; their spread sets the tolerance band"
BIN_SECONDS = 10.0
MAX_SEND_JITTER_SECONDS = 0.5
MIN_COMPARED_BINS = 5


@dataclass(frozen=True)
class RealRun:
    """One real open-loop run at pinned capacity, as the load driver records it.

    `latencies[i]` is None when request i had not completed when the window
    closed. `host_ids` is the platform identity of every replica that served
    (spec §10's new requirement): artifact 1 saw one first-touch cold start at
    2266.6 s against a 39-96 s norm, and a host-novelty event inside a
    validation run is indistinguishable from a simulator bug unless the host is
    on record.
    """

    schedule: tuple[float, ...]
    sent: tuple[float, ...]
    latencies: tuple[float | None, ...]
    replicas: int
    until: float
    host_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("schedule", "sent", "latencies", "host_ids"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        n = len(self.schedule)
        if n == 0 or len(self.sent) != n or len(self.latencies) != n:
            raise ValueError(
                f"schedule, sent and latencies must be one entry per request and "
                f"non-empty; got length {n}, {len(self.sent)}, {len(self.latencies)}. "
                "Misaligned lists attribute latencies to the wrong requests"
            )
        if type(self.replicas) is not int or self.replicas < 1:
            raise ValueError(
                f"replicas must be a positive int, got {self.replicas!r}; the replay "
                "would pin a different fleet from the one the real run had, or "
                "refuse it only later with no word about which run was malformed"
            )
        if not math.isfinite(self.until) or self.until <= 0:
            raise ValueError(
                f"until must be finite and positive, got {self.until!r}; the window "
                "is where a request stops counting as completed, so a bad one makes "
                "every bin's censoring meaningless"
            )
        if not self.host_ids or not all(isinstance(h, str) and h for h in self.host_ids):
            raise ValueError(
                "host_ids is empty or holds a blank id; spec §10 requires the host "
                "of every replica, because a host-novelty event is otherwise "
                "indistinguishable from a simulator bug"
            )
        previous = 0.0
        for t in self.schedule:
            if not math.isfinite(t) or t < previous or t > self.until:
                raise ValueError(
                    f"schedule entry {t!r} is not finite, not ascending, or past "
                    f"until={self.until!r}; the simulator would refuse to replay it"
                )
            previous = t
        if not all(math.isfinite(s) for s in self.sent):
            raise ValueError(
                "a send time is not finite; send jitter would be NaN or infinite, "
                "and a NaN compares False against the jitter bound and would pass it"
            )
        for lat in self.latencies:
            if lat is not None and (not math.isfinite(lat) or lat < 0):
                raise ValueError(
                    f"latency {lat!r} is not a finite non-negative duration; use "
                    "None for a request that had not completed"
                )

    def send_jitter(self) -> float:
        """The largest gap between when a request was scheduled and when it was
        sent. The largest, not the mean: one request sent seconds late can cross
        a bin boundary on its own."""
        return max(abs(s - t) for s, t in zip(self.sent, self.schedule, strict=True))


def predicted_trajectory(schedule, replicas: int, curve: ServiceCurve, until: float,
                         bin_seconds: float = BIN_SECONDS) -> list[Bin]:
    """Replay `schedule` into `run_fixed_capacity` and bin the outcome.

    The unfinished requests go in as None rather than being dropped: they are
    the backlog, and a trajectory without them would report the bins they
    arrived in as uncongested -- the flattering direction.
    """
    result = run_fixed_capacity(list(schedule), replicas, curve, until)
    pairs = result.completed_requests()
    arrivals = [a for a, _ in pairs] + list(result.unfinished_arrivals)
    latencies = [lat for _, lat in pairs] + [None] * len(result.unfinished_arrivals)
    return trajectory(arrivals, latencies, until=until, bin_seconds=bin_seconds)


def _check_repeats(runs: Sequence[RealRun]) -> None:
    """What only a RealRun can tell: that the repeats replayed ONE schedule, at
    one capacity, faithfully. How many repeats are enough is `band`'s check."""
    if not runs:
        raise ValueError("no real runs; there is nothing to build a band from")
    first = runs[0]
    for run in runs[1:]:
        if (run.schedule, run.replicas, run.until) != (first.schedule, first.replicas, first.until):
            raise ValueError(
                "repeats differ in schedule, replicas or window; the band must be "
                "the system's own spread on ONE trace, and mixing traces folds "
                "traffic variance into it and widens it for free"
            )
    for run in runs:
        if run.send_jitter() > MAX_SEND_JITTER_SECONDS:
            raise ValueError(
                f"send jitter {run.send_jitter():.3f} s exceeds "
                f"{MAX_SEND_JITTER_SECONDS} s; the driver did not replay the "
                "schedule, so the run tested a different trace from the one the "
                "simulator replays"
            )


def tolerance_band(runs: Sequence[RealRun], bin_seconds: float = BIN_SECONDS) -> list[BandBin]:
    """The band from real repeats, binned by SCHEDULED arrival (see the module
    docstring for why not send time), at artifact 2's pre-registered repeat
    count rather than one the caller picks."""
    _check_repeats(runs)
    return band(
        [trajectory(r.schedule, r.latencies, until=r.until, bin_seconds=bin_seconds)
         for r in runs],
        min_repeats=MIN_REPEATS,
    )


def validate(runs: Sequence[RealRun], curve: ServiceCurve,
             bin_seconds: float = BIN_SECONDS) -> Validation:
    """The gate end to end: band from the real repeats, prediction from
    replaying their shared schedule, verdict at the pre-registered
    `MIN_COMPARED_BINS`. The prediction replays the schedule, not any run's
    send times, so it sees exactly the trace every repeat was meant to."""
    tolerance = tolerance_band(runs, bin_seconds)
    first = runs[0]
    predicted = predicted_trajectory(first.schedule, first.replicas, curve, first.until,
                                     bin_seconds)
    return compare(predicted, tolerance, min_compared_bins=MIN_COMPARED_BINS)
