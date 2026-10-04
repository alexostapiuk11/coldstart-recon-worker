"""The pre-registered threshold grids, one per signal, and nothing else.

A module of its own, importing nothing, because two very different readers
need the same numbers: the sweep, which runs every combination through the
simulator, and figure 4, which shades the load above the top of utilization's
grid. While the grids lived in `autoscale.sweep`, the figure could only read
them by importing the sweep -- and with it `autoscale.sim`,
`autoscale.coldstart_ecdf` and artifact 1's `coldstart` package, none of which a
chart needs. Copying the utilization grid into the figure module was the
rejected alternative: two copies of a pre-registered value drift the first time
one is edited, and the figure would then shade against a grid the sweep no
longer uses. `autoscale.sweep` re-exports the name, so its readers are
unchanged.
"""

__all__ = ["THRESHOLDS"]

# PER-SIGNAL THRESHOLD GRIDS. The three signals do not share units, so one
# numeric grid cannot span all three:
#
#   queue_depth            requests waiting per replica     0 .. unbounded
#   in_flight_concurrency  active requests per replica      0 .. max_measured_concurrency
#   utilization            a FRACTION                       0 .. 1
#
# Sweeping the single grid (2, 4, 8, 16) across all three -- the original
# design -- puts every threshold above utilization's maximum possible value, so
# that policy never fires and its whole frontier collapses to one "never scale"
# point. H2 ("utilization is worst") would then be confirmed trivially by a
# units mismatch rather than by the censoring mechanism the artifact publishes,
# which would make the headline indefensible.
#
# This is NOT the per-signal tuning the design rejects. That rejection is about
# refusing to hand-pick each signal's best operating point; giving each signal a
# grid that spans its own range is what makes the frontiers comparable at all.
# The grids are pre-registered in docs/experiment-a2.md before any sweep runs,
# so they cannot be chosen to produce a result.
THRESHOLDS: dict[str, tuple[tuple[float, ...], tuple[float, ...]]] = {
    # signal: (scale_up_grid, scale_down_grid)
    "queue_depth": ((1.0, 2.0, 4.0, 8.0, 16.0), (0.0, 0.25, 0.5, 1.0)),
    "in_flight_concurrency": ((2.0, 4.0, 8.0, 12.0, 16.0), (0.5, 1.0, 2.0, 4.0)),
    "utilization": ((0.50, 0.65, 0.80, 0.90, 0.95), (0.05, 0.15, 0.30, 0.50)),
}
