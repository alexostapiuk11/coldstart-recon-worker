"""The pre-registered values, as one validated record (amendment §5).

Two dated steps, as artifact 4 did. Step 1's fields are fixed before the pilot.
Step 2's fields (the `None` defaults below) are fixed after the pilot and
before any campaign call. `toolcall/prereg_values.py` holds the values and
`docs/experiment-a3.md` embeds `prereg_table`'s output; a test fails if the two
disagree, so the document a reader sees and the object the code runs on are
one thing.
"""

from dataclasses import dataclass, fields

from harness.stats import MIN_BOOTSTRAP_SAMPLES
from toolcall import NORMALIZER_VERSION
from toolcall.formulation import parse_cell
from toolcall.providers import ModelSettings


@dataclass(frozen=True)
class Preregistration:
    # --- step 1: before the pilot --------------------------------------
    primary: ModelSettings
    slice_models: tuple[ModelSettings, ...]
    baseline_cell: str
    band: tuple[float, float]  # inclusive bounds on the baseline correct rate
    pilot_reps: int
    pilot_cost_scenarios: int
    pilot_cost_reps: int
    delta2: float  # H2's equivalence margin, a proportion
    identical_retry_floor: float  # H4's floor rule (amendment §4e)
    n_floor: int
    n_cap: int
    s_floor: int
    alpha: float
    iterations: int
    bootstrap_seed: int
    schedule_seed: int
    retry_cap: int  # attempts in the cost-per-successful-call policy (§4f)
    turn_budget: int
    normalizer_version: int
    # --- step 2: after the pilot, before the campaign ---------------------
    included: tuple[str, ...] | None = None
    reps: int | None = None
    recovery_reps: int | None = None
    slice_reps: int | None = None
    approved_usd: float | None = None

    def __post_init__(self) -> None:
        parse_cell(self.baseline_cell)
        lo, hi = self.band
        if not 0.0 <= lo < hi <= 1.0:
            raise ValueError(f"band must satisfy 0 <= lo < hi <= 1, got {self.band}")
        for name in ("pilot_reps", "pilot_cost_scenarios", "pilot_cost_reps", "n_floor",
                     "n_cap", "s_floor", "iterations", "retry_cap", "turn_budget"):
            v = getattr(self, name)
            if not isinstance(v, int) or v <= 0:
                raise ValueError(f"{name} must be a positive int, got {v!r}")
        if self.n_floor < 2:
            raise ValueError("n_floor must be at least 2: H5's A/A contrast splits repetitions")
        if self.n_cap < self.n_floor:
            raise ValueError("n_cap must be at least n_floor")
        if self.s_floor < MIN_BOOTSTRAP_SAMPLES:
            raise ValueError(f"s_floor is below the bootstrap floor {MIN_BOOTSTRAP_SAMPLES}")
        if not 0.0 < self.delta2 < 0.5 or not 0.0 < self.identical_retry_floor < 1.0:
            raise ValueError("delta2 and identical_retry_floor must be proportions")
        if not 0.0 < self.alpha < 1.0:
            raise ValueError("alpha must be in (0, 1)")
        if self.normalizer_version != NORMALIZER_VERSION:
            raise ValueError(
                f"pre-registered normalizer v{self.normalizer_version}, code is "
                f"v{NORMALIZER_VERSION}: grading rules changed after registration"
            )
        if self.included is not None:
            if len(self.included) < self.s_floor:
                raise ValueError(f"{len(self.included)} included scenarios, below s_floor")
            if len(set(self.included)) != len(self.included):
                raise ValueError("included has duplicates")
        if self.reps is not None and not self.n_floor <= self.reps <= self.n_cap:
            raise ValueError(f"reps {self.reps} outside [{self.n_floor}, {self.n_cap}]")
        for name in ("recovery_reps", "slice_reps"):
            v = getattr(self, name)
            if v is not None and v < self.n_floor:
                raise ValueError(f"{name} {v} is below n_floor")

    @property
    def step2_complete(self) -> bool:
        return all(getattr(self, f) is not None for f in STEP2)

    def require_step2(self) -> None:
        missing = [f for f in STEP2 if getattr(self, f) is None]
        if missing:
            raise ValueError(f"pre-registration step 2 is not committed: {missing} unset")


STEP2 = ("included", "reps", "recovery_reps", "slice_reps", "approved_usd")


def prereg_table(prereg: Preregistration) -> str:
    lines = ["| parameter | value |", "|---|---|"]
    for f in fields(prereg):
        value = getattr(prereg, f.name)
        if isinstance(value, ModelSettings):
            value = value.to_dict()
        elif f.name == "slice_models":
            value = tuple(m.to_dict() for m in value)
        lines.append(f"| `{f.name}` | `{value!r}` |")
    return "\n".join(lines)
