"""The pre-registered values, as one validated record (amendment §5).

Two dated steps, as artifact 4 did. Step 1's fields are fixed before the pilot.
Step 2's fields (the `None` defaults below) are fixed after the pilot and
before any campaign call. `toolcall/prereg_values.py` holds the values and
`docs/experiment-a3.md` embeds `prereg_table`'s output; a test fails if the two
disagree, so the document a reader sees and the object the code runs on are
one thing.
"""

import math
from dataclasses import dataclass, fields

from harness.stats import MIN_BOOTSTRAP_SAMPLES
from toolcall import NORMALIZER_VERSION
from toolcall.formulation import parse_cell
from toolcall.prices import PRICES
from toolcall.providers import ModelSettings

# With Holm's procedure at alpha/5 and add-one bootstrap p-values, fewer draws
# than this can never reach the smallest threshold, so the test cannot reject.
MIN_ITERATIONS = 100


def _require_int(name: str, value, *, positive: bool = False) -> None:
    """An int that is not a bool (True is an int in Python and would pass a
    bare isinstance check), optionally positive."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(  # noqa: TRY004 - every refusal in this record is a ValueError
            f"{name} must be a positive int, got {value!r}" if positive
            else f"{name} must be an int, got {value!r}")
    if positive and value <= 0:
        raise ValueError(f"{name} must be a positive int, got {value!r}")


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
    # The familywise level for Holm's procedure over the five hypotheses; each
    # interval is (1 - alpha). H2's equivalence part uses a (1 - 2*alpha) interval.
    alpha: float
    iterations: int
    bootstrap_seed: int
    schedule_seed: int
    retry_cap: int  # attempts in the cost-per-successful-call policy (§4f)
    turn_budget: int
    normalizer_version: int
    # below this, a scenario is dropped from the analysis and disclosed (pre-registration rule)
    min_graded_per_cell: int = 2
    # --- step 2: after the pilot, before the campaign ---------------------
    included: tuple[str, ...] | None = None
    reps: int | None = None
    recovery_reps: int | None = None
    slice_reps: int | None = None
    approved_usd: float | None = None

    def __post_init__(self) -> None:
        parse_cell(self.baseline_cell)
        self._validate_models()
        if not isinstance(self.band, tuple) or len(self.band) != 2:
            raise ValueError(f"band must be a (lo, hi) tuple, got {self.band!r}")
        lo, hi = self.band
        if not 0.0 <= lo < hi <= 1.0:
            raise ValueError(f"band must satisfy 0 <= lo < hi <= 1, got {self.band}")
        for name in ("pilot_reps", "pilot_cost_scenarios", "pilot_cost_reps", "n_floor",
                     "n_cap", "s_floor", "iterations", "retry_cap", "turn_budget"):
            _require_int(name, getattr(self, name), positive=True)
        for name in ("bootstrap_seed", "schedule_seed"):
            _require_int(name, getattr(self, name))
        if self.n_floor < 2:
            raise ValueError("n_floor must be at least 2: H5's A/A contrast splits repetitions")
        if self.n_cap < self.n_floor:
            raise ValueError("n_cap must be at least n_floor")
        _require_int("min_graded_per_cell", self.min_graded_per_cell)
        if not 1 <= self.min_graded_per_cell <= self.n_floor:
            raise ValueError(
                f"min_graded_per_cell must be an int in [1, n_floor={self.n_floor}], "
                f"got {self.min_graded_per_cell!r}")
        if self.s_floor < MIN_BOOTSTRAP_SAMPLES:
            raise ValueError(f"s_floor is below the bootstrap floor {MIN_BOOTSTRAP_SAMPLES}")
        if self.iterations < MIN_ITERATIONS:
            raise ValueError(
                f"iterations {self.iterations} is below {MIN_ITERATIONS}: with Holm at "
                "alpha/5 and add-one p-values, fewer draws can never reject")
        if not 0.0 < self.delta2 < 0.5 or not 0.0 < self.identical_retry_floor < 1.0:
            raise ValueError("delta2 and identical_retry_floor must be proportions")
        if not 0.0 < self.alpha <= 0.5:
            raise ValueError("alpha must be in (0, 0.5]")
        if self.normalizer_version != NORMALIZER_VERSION:
            raise ValueError(
                f"pre-registered normalizer v{self.normalizer_version}, code is "
                f"v{NORMALIZER_VERSION}: grading rules changed after registration"
            )
        if self.included is not None:
            if not isinstance(self.included, tuple):
                raise ValueError("included must be a tuple, so the rendered table is stable")
            if len(self.included) < self.s_floor:
                raise ValueError(f"{len(self.included)} included scenarios, below s_floor")
            if len(set(self.included)) != len(self.included):
                raise ValueError("included has duplicates")
        for name in ("reps", "recovery_reps", "slice_reps"):
            if getattr(self, name) is not None:
                _require_int(name, getattr(self, name), positive=True)
        if self.reps is not None and not self.n_floor <= self.reps <= self.n_cap:
            raise ValueError(f"reps {self.reps} outside [{self.n_floor}, {self.n_cap}]")
        for name in ("recovery_reps", "slice_reps"):
            v = getattr(self, name)
            if v is not None and not self.n_floor <= v <= self.n_cap:
                raise ValueError(f"{name} {v} outside [{self.n_floor}, {self.n_cap}]")
        if self.approved_usd is not None:
            v = self.approved_usd
            if (isinstance(v, bool) or not isinstance(v, (int, float))
                    or not math.isfinite(v) or v <= 0):
                raise ValueError(f"approved_usd must be a finite positive number, got {v!r}")
        # Step 2 is one dated commitment: all of it or none of it.
        set_fields = [f for f in STEP2 if getattr(self, f) is not None]
        if set_fields and len(set_fields) != len(STEP2):
            raise ValueError(
                f"pre-registration step 2 is partly committed: {set_fields} set, "
                f"{[f for f in STEP2 if f not in set_fields]} unset")

    def _validate_models(self) -> None:
        if not isinstance(self.slice_models, tuple) or not self.slice_models:
            raise ValueError("slice_models must be a non-empty tuple of ModelSettings")
        everyone = (self.primary, *self.slice_models)
        for m in everyone:
            if not isinstance(m, ModelSettings):
                raise ValueError(  # noqa: TRY004 - every refusal in this record is a ValueError
                    f"model settings must be ModelSettings, got {m!r}")
            if m.constrained:
                raise ValueError(
                    f"{m.model}: constrained decoding is applied by the exploratory slice "
                    "itself, so a pre-registered setting must have constrained=False")
            if m.model not in PRICES:
                raise ValueError(f"no pinned price for {m.model!r}: add it to toolcall.prices")
        ids = [m.model for m in everyone]
        if len(set(ids)) != len(ids):
            raise ValueError(f"model ids must be distinct across primary and slice: {ids}")

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
