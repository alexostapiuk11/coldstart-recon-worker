"""The measured service curve, as the simulator, the sweep and figure 4 read it.

`data/a2/service-curve.json` is written by `scripts/a2_service_curve.py` from
the shared service sweep. This module reads it into a `ServiceCurve` and keeps
beside it what the curve alone cannot carry: per-level intervals for figure 4,
the levels the engine could not serve, and the engine facts the post states.

It lives in `autoscale/` rather than reusing `scripts/a2_service_curve.py`'s
loader because `scripts/` is not a package -- every caller would have to edit
`sys.path` -- and because that loader does not add the idle point below.

THE IDLE POINT. The sweep measured concurrency 1 upwards, and nvidia-smi reads
100% at every measured level, one request included. `ServiceCurve` clamps below
its first point, so without a point at 0 an IDLE replica would read 100% busy,
and no utilisation scale-down threshold could ever fire: H2 would be confirmed
by an interpolation artefact. The point added is (0, latency at level 1, 0, 0).
Its utilisation is measured, not assumed: every successful sweep run sampled
nvidia-smi while the engine sat idle, before and after its measured span, and
at least 80% of those samples read 0; the rest sit at the span's edges, next to
the warm-up and the prompt probe (tests/test_measured_curve.py checks the
committed store).
Its latency is never read by the simulator, which charges every dispatched
request the load ceil(in_flight / replicas) >= 1; it is set to level 1's so the
curve stays flat there rather than inventing a value. Throughput at 0 load is 0
by definition.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from autoscale.service import SERVICE_CURVE_PLACEHOLDER, ServiceCurve

__all__ = ["DEFAULT_PATH", "IDLE_CONCURRENCY", "MeasuredCurve", "load_measured_curve",
           "select_curve"]

DEFAULT_PATH = Path("data/a2/service-curve.json")
IDLE_CONCURRENCY = 0.0


@dataclass(frozen=True)
class MeasuredCurve:
    """The curve plus what figure 4 and the post need that it cannot hold."""

    curve: ServiceCurve
    intervals: tuple[dict, ...]
    excluded_levels: tuple[dict, ...]
    max_num_seqs: int
    gpu_util_method: str
    prompt_path: str
    source: str
    runs_per_level: tuple[int, ...] = ()

    @property
    def measured_points(self) -> tuple[tuple[float, float, float, float], ...]:
        """The curve's points without the idle point: what was swept."""
        return tuple(self.curve.points[1:])


def load_measured_curve(path=DEFAULT_PATH) -> MeasuredCurve:
    doc = json.loads(Path(path).read_text())
    if doc.get("measured") is not True:
        raise ValueError(
            f"{path} is not measured (measured={doc.get('measured')!r}); the simulator would "
            "run on invented numbers presented as the engine's. Use select_curve(..., "
            "placeholder=True) for a layout draft instead"
        )
    if doc.get("gpu_util_method") != "windowed":
        raise ValueError(
            f"{path} has gpu_util_method {doc.get('gpu_util_method')!r}, not 'windowed'; the "
            "idle point's 0% is a windowed reading's complement, and a whole-call median "
            "already mixes idle time into every level"
        )
    points = [tuple(float(x) for x in p) for p in doc["points"]]
    if not points or points[0][0] <= IDLE_CONCURRENCY:
        raise ValueError(
            f"{path}'s first level is {points[0][0] if points else None!r}; the idle point "
            "goes at concurrency 0, and a curve that already has a level there (or none) "
            "would get two values for one load"
        )
    intervals = tuple(doc.get("intervals") or ())
    if [i.get("concurrency") for i in intervals] != [p[0] for p in points]:
        raise ValueError(
            f"{path}'s intervals cover levels {[i.get('concurrency') for i in intervals]} but "
            f"its points cover {[p[0] for p in points]}; figure 4 would draw an interval "
            "against the wrong point"
        )
    excluded = tuple(doc.get("excluded_levels") or ())
    top = points[-1][0]
    inside = [e["concurrency"] for e in excluded if e["concurrency"] <= top]
    if inside:
        raise ValueError(
            f"{path} excludes levels {inside}, inside the measured range (top {top:g}); the "
            "simulator interpolates straight across a level the engine could not serve"
        )
    runs = tuple(int(level["n_runs"]) for level in doc.get("levels") or ())
    if runs and len(runs) != len(points):
        raise ValueError(
            f"{path} has {len(runs)} level rows for {len(points)} points; figure 4 states the "
            "runs behind each point and would attach the wrong count"
        )
    idle = (IDLE_CONCURRENCY, points[0][1], 0.0, 0.0)
    return MeasuredCurve(
        curve=ServiceCurve(points=[idle, *points], measured=True),
        intervals=intervals,
        excluded_levels=excluded,
        max_num_seqs=int(doc["max_num_seqs"]),
        gpu_util_method=doc["gpu_util_method"],
        prompt_path=doc.get("prompt_path", "unrecorded"),
        source=str(path),
        runs_per_level=runs,
    )


def select_curve(path, *, placeholder: bool) -> tuple[ServiceCurve, MeasuredCurve | None]:
    """The curve a script runs on: the measured one, or the placeholder on request.

    One switch for every script, so "which curve did this run on" has one
    answer per run. The placeholder is never a fallback for a missing file: a
    missing measured curve is an error, because silently drawing invented
    numbers is the failure the `measured` flag exists to prevent.
    """
    if placeholder:
        return SERVICE_CURVE_PLACEHOLDER, None
    measured = load_measured_curve(path if path is not None else DEFAULT_PATH)
    return measured.curve, measured
