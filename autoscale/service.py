"""The measured service curve: what one replica does as concurrency rises.

Measured, not modeled. Continuous batching makes latency-versus-concurrency
strongly non-linear in a way no queueing formula reproduces, which is why the
spec buys this curve on hardware rather than deriving it. Linear interpolation
between measured points is deliberate: a spline would invent curvature between
samples, and the sweep is dense enough that straight segments are honest.
"""

import bisect
import math
from dataclasses import dataclass

__all__ = ["SERVICE_CURVE_PLACEHOLDER", "ServiceCurve"]


@dataclass
class ServiceCurve:
    """`points` are (concurrency, latency_seconds, throughput_tps, gpu_utilization),
    ascending by concurrency.

    `measured` is False for the placeholder used until plan 2's sweep runs. Any
    figure or number derived from an unmeasured curve must say so -- the whole
    methodological claim is that every parameter is measured and only the
    control loop is modeled.
    """

    points: list[tuple[int, float, float, float]]
    measured: bool

    def __post_init__(self) -> None:
        if len(self.points) < 2:
            raise ValueError("a service curve needs at least two points to interpolate")
        # NaN compares False against every `<`/`>`/`==` below, including
        # against itself, so a NaN concurrency, latency, throughput, or
        # utilization would slip past both the ascending-order check (a NaN
        # concurrency sorts nowhere, so `sorted()` can't be trusted to catch
        # it) and every downstream interpolation comparison in `_interpolate`
        # and `utilization_at`, producing a plausible-looking number computed
        # from garbage. +-inf compare as ordinary (extreme) values and would
        # pass those same checks legitimately, but then poison the linear
        # interpolation arithmetic (e.g. `(y1 - y0)` or the fraction) with an
        # inf or NaN that propagates into every later `latency_at` /
        # `throughput_at` / `utilization_at` call on this curve. Reject all
        # four fields, on every point, before any ordering or interpolation
        # logic runs.
        for point in self.points:
            concurrency, latency, throughput, utilization = point
            for field_name, value in (
                ("concurrency", concurrency),
                ("latency", latency),
                ("throughput", throughput),
                ("utilization", utilization),
            ):
                if not math.isfinite(value):
                    raise ValueError(
                        f"service curve point {point!r} has {field_name}="
                        f"{value!r}, which is not finite; a non-finite value "
                        "compares False against every ordering check below "
                        "(NaN) or poisons the interpolation arithmetic with "
                        "inf (+-inf), so it would silently produce a "
                        "plausible-looking but meaningless latency, "
                        "throughput, or utilization instead of raising here"
                    )
        concurrencies = [p[0] for p in self.points]
        if concurrencies != sorted(concurrencies):
            raise ValueError("service curve points must be in ascending concurrency order")
        if len(set(concurrencies)) != len(concurrencies):
            raise ValueError(
                "service curve points must have distinct concurrency values; "
                "two points at the same concurrency make `_interpolate`'s "
                "`(x1 - x0)` a division by zero for any query landing exactly "
                "on that concurrency"
            )

    @property
    def max_measured_concurrency(self) -> int:
        return self.points[-1][0]

    def is_extrapolating(self, concurrency: int) -> bool:
        if math.isnan(concurrency):
            # `concurrency > self.max_measured_concurrency` is False for
            # NaN, so without this guard a caller checking "is this safe to
            # trust?" before calling latency_at would get False -- a clean
            # bill of health -- for the exact input that then makes
            # latency_at raise. The flag and the method it is meant to
            # describe would disagree.
            raise ValueError(
                "concurrency is NaN; NaN compares False against "
                "`concurrency > max_measured_concurrency`, so this would "
                "silently report a NaN query as within the validated range "
                "instead of raising -- disagreeing with latency_at, which "
                "does raise on the same input"
            )
        return concurrency > self.max_measured_concurrency

    def _interpolate(self, concurrency: int, index: int) -> float:
        xs = [p[0] for p in self.points]
        if concurrency <= xs[0]:
            return self.points[0][index]
        if concurrency >= xs[-1]:
            return self.points[-1][index]
        i = bisect.bisect_left(xs, concurrency)
        x0, x1 = xs[i - 1], xs[i]
        y0, y1 = self.points[i - 1][index], self.points[i][index]
        return y0 + (concurrency - x0) / (x1 - x0) * (y1 - y0)

    def latency_at(self, concurrency: int) -> float:
        if math.isnan(concurrency):
            # `concurrency <= xs[0]` and `concurrency >= xs[-1]` in
            # `_interpolate` are both False for NaN, so without this guard a
            # NaN would fall through to `bisect_left`, which treats NaN as
            # neither less than nor greater than any point and inserts it at
            # a position that depends only on comparison order -- silently
            # returning a real-looking latency instead of raising.
            raise ValueError(
                "concurrency is NaN; NaN compares False against every "
                "boundary check in _interpolate, so it would silently fall "
                "through to bisect_left and return a plausible but "
                "meaningless latency instead of raising"
            )
        return self._interpolate(concurrency, 1)

    def throughput_at(self, concurrency: int) -> float:
        if math.isnan(concurrency):
            raise ValueError(
                "concurrency is NaN; NaN compares False against every "
                "boundary check in _interpolate, so it would silently fall "
                "through to bisect_left and return a plausible but "
                "meaningless throughput instead of raising"
            )
        return self._interpolate(concurrency, 2)

    def utilization_at(self, concurrency: int) -> float:
        if math.isnan(concurrency):
            raise ValueError(
                "concurrency is NaN; NaN compares False against every "
                "boundary check in _interpolate, so it would silently fall "
                "through to bisect_left and return a plausible but "
                "meaningless utilization instead of raising"
            )
        return min(1.0, self._interpolate(concurrency, 3))


# Shapes chosen to be qualitatively right for continuous batching -- latency
# flat then rising, throughput rising then flattening, utilization saturating
# well before the latency knee, which is the censoring H2 predicts. The NUMBERS
# ARE INVENTED and exist only so the simulator and sweep can be built and tested
# before hardware time is bought. Plan 2 replaces this wholesale.
SERVICE_CURVE_PLACEHOLDER = ServiceCurve(
    points=[
        (1, 0.30, 53.0, 0.18),
        (2, 0.31, 103.0, 0.34),
        (4, 0.33, 194.0, 0.61),
        (8, 0.38, 337.0, 0.85),
        (16, 0.52, 492.0, 0.96),
        (32, 0.95, 539.0, 0.99),
        (64, 2.10, 549.0, 1.00),
    ],
    measured=False,
)
