"""Measurement campaigns: the interleaved schedule, and each job's payload.

Each campaign is one schedule from `harness.scheduler.build_schedule`, so
conditions are interleaved within each block and a condition is never
confounded with time-varying platform state (artifact 1 spec 5):

- swaps: a condition is an ordered checkpoint pair and a cache state.
- cells: a condition is a grid cell -- `solo:o8`, or `pair:o8:n16`.
- sleep: one condition, the sleep-mode switch between two checkpoints
  (amendment §6), measured only if reconnaissance found sleep mode working.
- replay: one condition, `replay`, repeated: the same trace replayed on one
  GPU, whose repeats' spread is the validation band (August §9).

The designs are dataclasses whose values the second pre-registration step
fixes; nothing here chooses a grid, a pair or a request shape.
"""

from dataclasses import dataclass

from harness.scheduler import ScheduledRun, build_schedule
from harness.service_sweep import num_prompts_for
from placement_measure.prereg import (
    HF_HOME,
    JOB_BUDGET_S,
    RELEASE_TIMEOUT_S,
    RELEASE_TOLERANCE_MIB,
    SLEEP_GMU,
    SOLO_GMU,
    SPLIT_GMU,
    engine,
)

__all__ = ["REPLAY_CONDITION", "CellDesign", "ReplayDesign", "SleepDesign", "SwapDesign",
           "cell_condition", "parse_cell", "parse_sleep", "parse_swap", "sleep_condition",
           "swap_condition"]

REPLAY_CONDITION = "replay"

SLEEP_FLAGS = ("--enable-sleep-mode",)


def swap_condition(a: str, b: str, cold: bool) -> str:
    return f"swap:{a}>{b}:{'cold' if cold else 'warm'}"


def parse_swap(condition: str) -> tuple[str, str, bool]:
    kind, pair, state = condition.split(":")
    a, b = pair.split(">")
    if kind != "swap" or state not in ("cold", "warm"):
        raise ValueError(f"{condition!r} is not a swap condition")
    return a, b, state == "cold"


def sleep_condition(a: str, b: str) -> str:
    return f"sleep:{a}>{b}"


def parse_sleep(condition: str) -> tuple[str, str]:
    kind, _, pair = condition.partition(":")
    a, sep, b = pair.partition(">")
    if kind != "sleep" or not sep or not a or not b:
        raise ValueError(f"{condition!r} is not a sleep condition")
    return a, b


def cell_condition(own: int, neighbour: int | None) -> str:
    return f"solo:o{own}" if neighbour is None else f"pair:o{own}:n{neighbour}"


def parse_cell(condition: str) -> tuple[int, int | None]:
    parts = condition.split(":")
    if parts[0] == "solo" and len(parts) == 2:
        return int(parts[1][1:]), None
    if parts[0] == "pair" and len(parts) == 3:
        return int(parts[1][1:]), int(parts[2][1:])
    raise ValueError(f"{condition!r} is not a cell condition")


@dataclass(frozen=True)
class SwapDesign:
    pairs: tuple[tuple[str, str], ...]
    cold_states: tuple[bool, ...]
    repeats: int
    seed: int

    def schedule(self) -> list[ScheduledRun]:
        conditions = [swap_condition(a, b, c) for a, b in self.pairs for c in self.cold_states]
        return build_schedule(conditions, self.repeats, self.seed)

    def payload(self, scheduled: ScheduledRun, run_id: str) -> dict:
        a, b, cold = parse_swap(scheduled.condition)
        return {"kind": "swap", "run_id": run_id, "a": engine(a, SOLO_GMU).to_dict(),
                "b": engine(b, SOLO_GMU).to_dict(), "cold": cold, "hf_home": HF_HOME,
                "release_tolerance_mib": RELEASE_TOLERANCE_MIB,
                "release_timeout_s": RELEASE_TIMEOUT_S, "job_budget_s": JOB_BUDGET_S}


@dataclass(frozen=True)
class CellDesign:
    measured_model: str
    neighbour_model: str
    own_levels: tuple[int, ...]
    neighbour_levels: tuple[int, ...]  # 0 is the idle-neighbour column
    solo: bool
    input_len: int
    output_len: int
    repeats: int
    seed: int
    waves: int = 20
    min_prompts: int = 100
    warmup_waves: int = 1
    # The neighbour is sent this many times the measured run's request-waves,
    # and stopped when the measured run ends; a neighbour that still ran out
    # is flagged in the cell's own output.
    neighbour_overrun: int = 4
    # Cells outside the grid's product: the held-out cells the interference
    # check predicts, or a top-up of cells left short of valid repetitions.
    extra_cells: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "extra_cells", tuple(self.extra_cells))
        for c in self.extra_cells:
            parse_cell(c)

    def conditions(self) -> list[str]:
        cells = [cell_condition(o, n) for o in self.own_levels for n in self.neighbour_levels]
        if self.solo:
            cells += [cell_condition(o, None) for o in self.own_levels]
        cells += [c for c in self.extra_cells if c not in cells]
        if not cells:
            raise ValueError("a cell design with no cells would schedule nothing")
        return cells

    def schedule(self) -> list[ScheduledRun]:
        return build_schedule(self.conditions(), self.repeats, self.seed)

    def payload(self, scheduled: ScheduledRun, run_id: str) -> dict:
        own, neighbour = parse_cell(scheduled.condition)
        num_prompts = num_prompts_for(own, waves=self.waves, minimum=self.min_prompts)
        neighbour_prompts = 0 if not neighbour else self.neighbour_overrun * neighbour * (
            num_prompts // own + 1)
        gmu = SOLO_GMU if neighbour is None else SPLIT_GMU
        return {
            "kind": "cell", "run_id": run_id, "job_budget_s": JOB_BUDGET_S,
            "a": engine(self.measured_model, gmu).to_dict(),
            "b": None if neighbour is None else engine(self.neighbour_model, SPLIT_GMU).to_dict(),
            "cell": {"own": own, "neighbour": neighbour, "input_len": self.input_len,
                     "output_len": self.output_len, "num_prompts": num_prompts,
                     "warmup_prompts": self.warmup_waves * own,
                     "neighbour_prompts": neighbour_prompts,
                     "seed": self.seed * 1000 + scheduled.run_index},
        }


@dataclass(frozen=True)
class SleepDesign:
    """Repeats of one sleep-mode switch: A sleeps, B starts and serves, B
    sleeps, A wakes and serves. The switch's cost is B's sleep plus A's wake
    (`placement_measure.jobs`), the in-process counterpart of a swap."""

    a: str
    b: str
    repeats: int
    seed: int

    def schedule(self) -> list[ScheduledRun]:
        return build_schedule([sleep_condition(self.a, self.b)], self.repeats, self.seed)

    def payload(self, scheduled: ScheduledRun, run_id: str) -> dict:
        a, b = parse_sleep(scheduled.condition)
        return {"kind": "sleep", "run_id": run_id, "job_budget_s": JOB_BUDGET_S,
                "a": engine(a, SLEEP_GMU, SLEEP_FLAGS).to_dict(),
                "b": engine(b, SLEEP_GMU, SLEEP_FLAGS).to_dict()}


@dataclass(frozen=True)
class ReplayDesign:
    """Repeats of one trace replayed on one GPU (`placement_measure.replay`).

    Every repeat gets the identical payload apart from its run id: the same
    tenants, trace, request shape, cap and prompt seed. The band is the real
    system's spread on ONE trace, and anything that varied between repeats
    would widen it for free (artifact 2's `autoscale.validation`).
    """

    tenants: tuple[str, ...]
    trace: tuple[tuple[float, int], ...]
    until: float
    input_len: int
    output_len: int
    max_in_flight: int
    cold: bool
    repeats: int
    seed: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenants", tuple(self.tenants))
        object.__setattr__(self, "trace", tuple((float(t), int(m)) for t, m in self.trace))

    def schedule(self) -> list[ScheduledRun]:
        return build_schedule([REPLAY_CONDITION], self.repeats, self.seed)

    def payload(self, scheduled: ScheduledRun, run_id: str) -> dict:
        if scheduled.condition != REPLAY_CONDITION:
            raise ValueError(f"{scheduled.condition!r} is not a replay condition")
        return {"kind": "replay", "run_id": run_id, "job_budget_s": JOB_BUDGET_S,
                "tenants": [engine(m, SOLO_GMU).to_dict() for m in self.tenants],
                "schedule": [[t, m] for t, m in self.trace], "until": self.until,
                "input_len": self.input_len, "output_len": self.output_len,
                "max_in_flight": self.max_in_flight, "cold": self.cold, "seed": self.seed,
                "hf_home": HF_HOME, "release_tolerance_mib": RELEASE_TOLERANCE_MIB,
                "release_timeout_s": RELEASE_TIMEOUT_S}
