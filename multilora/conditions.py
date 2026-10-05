"""What one scheduled instance is, and in what order its phases run.

A condition names one kind of server instance: a sweep point, a diagnostic
point with `specialize_active_lora` on, the gauge control with stats logging
off, or the equivalence gate. The harness scheduler interleaves conditions
within blocks; this module decides what each one means and what its phases
are. Adapter names are fixed strings so a stored record says exactly which
adapters each phase listed.
"""

import re
from dataclasses import dataclass

from harness.scheduler import ScheduledRun, build_schedule
from multilora.prereg import Preregistration

SWEEP = "sweep"
DIAGNOSTIC = "diag"
CONTROL = "ctrl"
GATE = "gate"

CONCENTRATED = "concentrated"
SPREAD = "spread"
REAL = "real"
SYNTHETIC = "synthetic"

_NAMED = re.compile(r"^(sweep|diag|ctrl)-N(\d+)$")


@dataclass(frozen=True)
class Condition:
    name: str
    kind: str
    n_slots: int
    specialize_active_lora: bool
    disable_log_stats: bool


@dataclass(frozen=True)
class PhaseSpec:
    phase_index: int
    regime: str
    adapters: tuple[str, ...]


def synthetic_name(i: int) -> str:
    return f"a{i:02d}"


def real_name(i: int) -> str:
    return f"r{i:02d}"


def gate_synthetic_name(i: int) -> str:
    return f"s{i:02d}"


def condition_name(kind: str, n_slots: int) -> str:
    return f"{kind}-N{n_slots}"


def parse_condition(name: str, prereg: Preregistration) -> Condition:
    if name == GATE:
        return Condition(GATE, GATE, prereg.gate_slots, False, False)
    m = _NAMED.match(name)
    if not m:
        raise ValueError(f"unknown condition {name!r}")
    kind, n = m.group(1), int(m.group(2))
    if n not in prereg.sweep:
        raise ValueError(f"condition {name!r} is not at a sweep point {prereg.sweep}")
    if kind == DIAGNOSTIC and n not in prereg.diagnostic_points:
        raise ValueError(f"{name!r} is not a pre-registered diagnostic point")
    if kind == CONTROL and n != prereg.control_point:
        raise ValueError(f"{name!r} is not the pre-registered control point")
    return Condition(name, kind, n, kind == DIAGNOSTIC, kind == CONTROL)


def campaign_conditions(prereg: Preregistration) -> list[str]:
    """Every non-gate condition, in a fixed order the scheduler then shuffles
    within each block. The diagnostic and control conditions are present only
    if the pre-registration kept them after the budget check."""
    names = [condition_name(SWEEP, n) for n in prereg.sweep]
    if prereg.include_diagnostic:
        names += [condition_name(DIAGNOSTIC, n) for n in prereg.diagnostic_points]
    if prereg.include_control:
        names.append(condition_name(CONTROL, prereg.control_point))
    return names


def campaign_schedule(prereg: Preregistration) -> list[ScheduledRun]:
    return build_schedule(
        campaign_conditions(prereg), prereg.instances_per_condition, prereg.schedule_seed
    )


def gate_schedule(prereg: Preregistration) -> list[ScheduledRun]:
    """The gate runs first and alone (August §8), so it has its own schedule
    and its own store. Its seed is offset so it never shares a stream with the
    campaign's."""
    return build_schedule([GATE], prereg.instances_per_condition, prereg.schedule_seed + 1)


def registered_adapters(condition: Condition, prereg: Preregistration) -> tuple[str, ...]:
    if condition.kind == GATE:
        g = prereg.gate_adapters
        return tuple(real_name(i) for i in range(g)) + tuple(
            gate_synthetic_name(i) for i in range(g)
        )
    return tuple(synthetic_name(i) for i in range(condition.n_slots))


def phase_plan(
    condition: Condition, prereg: Preregistration, run_index: int
) -> list[PhaseSpec]:
    """The instance's timed phases, alternating regimes in an order drawn per
    instance. The draw reuses the harness scheduler: two regimes, `phases_per_
    regime` blocks, seeded from the campaign seed and the run index, so the
    order is reproducible from the stored record alone."""
    if condition.kind == GATE:
        g = prereg.gate_adapters
        lists = {
            REAL: tuple(real_name(i) for i in range(g)),
            SYNTHETIC: tuple(gate_synthetic_name(i) for i in range(g)),
        }
    else:
        registered = registered_adapters(condition, prereg)
        lists = {
            CONCENTRATED: registered[: prereg.concentrated_k],
            SPREAD: registered,
        }
    seed = prereg.schedule_seed * 1_000_003 + run_index
    order = build_schedule(list(lists), prereg.phases_per_regime, seed)
    return [PhaseSpec(s.run_index, s.condition, lists[s.condition]) for s in order]


def topup_schedule(prereg: Preregistration, conditions: list[str], blocks: int) -> list[ScheduledRun]:
    """Extra instances for conditions that fell below the bootstrap floor after
    exclusions (amendment §4). Own store, own seed stream; the post discloses
    them. Only named, registered, non-gate conditions may be topped up."""
    known = set(campaign_conditions(prereg))
    unknown = [c for c in conditions if c not in known]
    if unknown or not conditions:
        raise ValueError(f"top-up conditions must be registered campaign conditions: {unknown}")
    if blocks <= 0:
        raise ValueError("blocks must be positive")
    return build_schedule(list(conditions), blocks, prereg.schedule_seed + 2)
