"""Synthetic measurement stores for plan 3's end-to-end tests: every campaign
a registered design runs, written as the real stores would be.

Not a test module. Latency is 1 + 0.1 x own + 0.05 x neighbour seconds, so the
surface is exactly bilinear and the held-out cells pass. Replays are the
simulator's own latencies on the validation trace, offset by -10, 0 and +10 ms
per repeat, so validation passes.
"""

import random

from a4_examples import example_report
from test_placement_inputs_step2 import _cell
from test_placement_stages import _swap as _staged_swap

from harness.stats import median
from harness.store import JsonlStore
from placement.fleet import Gpu, Placement
from placement.inputs import colocated_surface, eviction_seconds, solo_curve, swap_distribution
from placement.registration import values
from placement.resample import EmpiricalDistribution
from placement.sim import Engines, simulate
from placement.step2 import CELL_MIN_VALID, measurement_design
from placement.validation import validation_trace
from placement_measure.campaigns import parse_cell
from placement_measure.records import A4Run

SCREEN = {"chosen": {"offered_gpus": 2.0, "slo_swap_multiple": 4.0}}
SWAP_S = 32.0


def registered() -> dict:
    return values(measurement_design(example_report()), SCREEN, rate=0.69,
                  provenance="test rate, not a quote")


def latency(own, neighbour):
    return 1.0 + 0.1 * own + 0.05 * (neighbour or 0)


def _cells(reg) -> list[A4Run]:
    conditions = ([f"solo:o{c}" for c in reg["SOLO_LEVELS"]]
                  + [f"pair:o{o}:n{n}" for o in reg["OWN_LEVELS"] for n in reg["NEIGHBOUR_LEVELS"]]
                  + list(reg["HELD_OUT"]))
    out = []
    for condition in conditions:
        own, neighbour = parse_cell(condition)
        for i, offset in enumerate((-0.01, 0.0, 0.01)):
            out.append(_cell(condition, latency(own, neighbour) + offset, i=i))
    return out


def _swaps() -> list[A4Run]:
    out = []
    for i in range(8):
        for cold in (True, False):
            r = _staged_swap(cold, i=len(out))
            r.output["swap_s"] = SWAP_S + i * 0.5 + (4.0 if cold else 0.0)
            r.output["b"]["facts"] = {"s4b_s": 0.3}
            if cold:
                r.output["cache_s"] = 1.0
            out.append(r)
    return out


def _sleep() -> list[A4Run]:
    return [A4Run(run_id=f"z{i}", run_index=i, condition="sleep:a>b", block_index=i, kind="sleep",
                  outcome="ok", failure=None, clock_A={}, source="stub",
                  output={"switch_s": 5.0 + 0.1 * i}) for i in range(8)]


def replay_swap_seconds(swaps) -> float:
    """The replay's swap: the median cold compile-hit swap plus the median
    eviction, as `scripts/a4_step2.py replay` computes it."""
    simulated = swap_distribution(swaps, cold=True, compiled=False)
    return median(list(simulated.samples)) + eviction_seconds(swaps, cold=True)


def _replays(reg, cells, swaps) -> list[A4Run]:
    """Three replays of the registered validation trace whose latencies are
    the simulator's, given these cells' curves and these swaps."""
    measurement = measurement_design(example_report())
    warm = {"require_warm_compile": True}
    solo = solo_curve(cells, levels=reg["SOLO_LEVELS"], min_repeats=CELL_MIN_VALID, **warm)
    surface = colocated_surface(cells, own_levels=reg["OWN_LEVELS"],
                                neighbour_levels=reg["NEIGHBOUR_LEVELS"],
                                min_repeats=CELL_MIN_VALID, **warm)
    swap_s = replay_swap_seconds(swaps)
    design, _ = validation_trace(measurement, Engines(solo, surface), swap_s)
    placement = Placement("swap", (Gpu("pool", (0,)),), pool_models=(0, 1, 2))
    result = simulate(list(design.trace), placement, Engines(solo, surface),
                      EmpiricalDistribution(samples=(swap_s,), measured=True), 0.0,
                      random.Random(0))
    by_request = dict(zip(zip(result.arrivals, result.models, strict=True), result.latencies,
                          strict=True))
    lat = [by_request[(t, m)] for t, m in design.trace]
    out = []
    for i, off in enumerate((-0.01, 0.0, 0.01)):
        arrived = [t for t, _ in design.trace]
        output = {"schedule": [[t, m] for t, m in design.trace], "until": design.until,
                  "arrived": arrived,
                  "done": [a + x + off for a, x in zip(arrived, lat, strict=True)],
                  "swaps": [{}] * result.swaps, "host": {"host_id": f"h{i}"},
                  "ok": [True] * len(arrived)}
        out.append(A4Run(run_id=f"v{i}", run_index=i, condition="replay", block_index=i,
                         kind="replay", outcome="ok", failure=None, clock_A={}, source="stub",
                         output=output))
    return out


def write_stores(root) -> dict:
    """Write every store under `root/data/a4/` and return the registered values."""
    reg = registered()
    cells, swaps = _cells(reg), _swaps()
    for name, records in (("cells", cells), ("swaps", swaps), ("sleep", _sleep()),
                          ("replay", _replays(reg, cells, swaps))):
        store = JsonlStore(root / "data" / "a4" / f"{name}.jsonl", A4Run)
        for r in records:
            store.append(r)
    return reg
