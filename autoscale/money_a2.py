"""Artifact 2's money: what the measured throughput and the simulated replica-seconds cost.

Mirrors `coldstart.analysis.economics`: a frozen `Assumptions` published beside
the result so a reader can substitute their own rate, validated at construction
because every field feeds a dollar figure the post quotes. Two conversions, both
rounded to cents:

- `dollars_per_million_requests`: workers billed for an hour, over the requests
  they delivered in it. The rate is the delivered rate, not the offered one, so a
  worker pool that delivers a fraction of what was sent costs more per request.
- `dollars_per_spike`: replica-seconds (what the simulator's policies cost) at the
  hourly rate.

The rate is what RunPod billed artifact 2's endpoints, measured from its billing
API's rows (`billed_hourly_rate` over data/a2/billing-endpoints.json): total
dollars over total time billed. Rejected: the worker record's `costPerHr`
($0.74/h), which the analysis first used; it is RunPod's on-demand Pod price for
an RTX 4090, and serverless billed these endpoints about 1.5 times that.
`spikes_per_day` is illustrative and says so.
"""

import math
from dataclasses import dataclass

__all__ = [
    "SECONDS_PER_HOUR",
    "Assumptions",
    "billed_hourly_rate",
    "dollars_per_day",
    "dollars_per_million_requests",
    "dollars_per_spike",
]

SECONDS_PER_HOUR = 3600.0
_PER_MILLION = 1e6


def _finite_positive(value: float, name: str, consequence: str) -> None:
    if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive, got {value!r}; {consequence}")


def _to_cents(dollars: float) -> float:
    """Cents, except that a positive amount below a cent keeps four decimals.

    Rounding $0.0002 to cents would print a free spike for a policy that cost
    something; the post's formatter makes the same exception when it prints.
    """
    return round(dollars, 2) if dollars >= 0.01 else round(dollars, 4)


@dataclass(frozen=True)
class Assumptions:
    """Published in the post so a reader can substitute their own."""

    gpu_hourly_rate: float
    spikes_per_day: float

    def __post_init__(self) -> None:
        _finite_positive(self.gpu_hourly_rate, "gpu_hourly_rate",
                         "every dollar figure is this rate times a duration, so a zero, "
                         "negative or non-finite rate would print a free or negative price")
        _finite_positive(self.spikes_per_day, "spikes_per_day",
                         "the per-day figures multiply the per-spike cost by it, so a zero, "
                         "negative or non-finite count would print a free or negative day")

    @property
    def provenance(self) -> dict[str, str]:
        """Where each assumption comes from; the post's table prints these verbatim.

        The rate is "measured: billed": dollars over time billed, from RunPod's
        billing API for these endpoints (`billed_hourly_rate`). Rejected: "reported",
        the label of the worker record's `costPerHr`, which serverless did not bill.
        """
        return {"gpu_hourly_rate": "measured: billed", "spikes_per_day": "illustrative"}


def billed_hourly_rate(rows: list[dict]) -> float:
    """Dollars per hour billed: the rows' total `amount` over their total `timeBilledMs`.

    `rows` are RunPod billing API rows (`GET /v1/billing/endpoints`). Pooled, so a
    long row weighs by its hours. Rejected: the mean of each row's own rate, which
    would let a 144-second day count as much as a 20-hour one.
    """
    if not rows:
        raise ValueError("no billed rows: an hourly rate needs at least one billed amount, "
                         "and without one every dollar figure would rest on nothing")
    for r in rows:
        _finite_positive(r["amount"], "a billed row's amount",
                         "a free or negative billed row is a misread bill, and it would "
                         "lower the rate every dollar figure uses")
        _finite_positive(r["timeBilledMs"], "a billed row's timeBilledMs",
                         "a row with no time billed has no hourly rate")
    dollars = math.fsum(r["amount"] for r in rows)
    seconds = math.fsum(r["timeBilledMs"] for r in rows) / 1000
    return dollars / seconds * SECONDS_PER_HOUR


def dollars_per_million_requests(assumptions: Assumptions, *, workers: int, rate: float) -> float:
    """`workers` billed for an hour while delivering `rate` req/s, per million requests."""
    if type(workers) is not int or workers <= 0:
        raise ValueError(f"workers must be a positive whole number, got {workers!r}; the "
                         "billed hours are workers times the rate, so a fraction or zero would "
                         "misprice the endpoint")
    _finite_positive(rate, "rate", "dividing by it would give an infinite or negative cost per "
                                   "request")
    return _to_cents(workers * assumptions.gpu_hourly_rate / (rate * SECONDS_PER_HOUR)
                     * _PER_MILLION)


def dollars_per_spike(assumptions: Assumptions, *, replica_seconds: float) -> float:
    """One spike's replica-seconds at the hourly rate."""
    _finite_positive(replica_seconds, "replica_seconds",
                     "a policy that used no replica time, or a non-finite sum, is a broken "
                     "simulator reading, not a free spike")
    return _to_cents(replica_seconds / SECONDS_PER_HOUR * assumptions.gpu_hourly_rate)


def dollars_per_day(assumptions: Assumptions, *, replica_seconds_per_spike: float) -> float:
    """`spikes_per_day` spikes of `replica_seconds_per_spike` each, priced once.

    Rejected: 24 times the rounded per-spike figure, which would put the cents'
    rounding error into the day ($0.18 x 24 = $4.32 against the true $4.34).
    """
    _finite_positive(replica_seconds_per_spike, "replica_seconds_per_spike",
                     "a policy that used no replica time, or a non-finite sum, is a broken "
                     "simulator reading, not a free day")
    return _to_cents(replica_seconds_per_spike * assumptions.spikes_per_day / SECONDS_PER_HOUR
                     * assumptions.gpu_hourly_rate)
