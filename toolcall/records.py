"""What one stored run is. Both shapes go through `harness.store.JsonlStore`.

A `CallRecord` is one single-turn call: the cell, the scenario, the repetition,
the exact request body, the raw response or the error, and the grade. A
`RecoveryRecord` is one recovery conversation with every turn kept.

Records keep the raw provider response, not only the grade, so re-grading
under a new normalizer version needs no new call.
"""

from dataclasses import asdict, dataclass

from toolcall import NORMALIZER_VERSION, SCHEMA_VERSION


@dataclass
class CallRecord:
    run_index: int
    block_index: int  # the repetition: block b is every (cell, scenario) once
    condition: str  # "<cell>|<scenario id>"
    run_id: str
    phase: str  # "pilot-baseline" | "pilot-cells" | "campaign" | "slice" | "exploratory"
    model: str  # the pinned id the request named
    returned_model: str | None
    cell: str
    scenario_id: str
    settings: dict
    request: dict | None
    response: dict | None
    error: str | None
    clock_A: dict
    grade: dict
    usage: dict | None
    cost_usd: float | None
    rendered_tools: list
    schema_version: int = SCHEMA_VERSION
    normalizer_version: int = NORMALIZER_VERSION

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CallRecord":
        return cls(**d)


@dataclass
class RecoveryRecord:
    run_index: int
    block_index: int
    condition: str  # "<cell>|<scenario id>|<format>"
    run_id: str
    phase: str  # "recovery"
    model: str
    cell: str
    scenario_id: str
    error_kind: str
    fmt: str
    settings: dict
    turns: list
    first_grade: dict | None
    injected: bool
    recovered: bool
    turns_to_recovery: int | None
    identical_retry: bool | None
    gave_up: bool
    hallucinated_success: bool
    budget_exhausted: bool
    excluded: str | None
    cost_usd: float
    schema_version: int = SCHEMA_VERSION
    normalizer_version: int = NORMALIZER_VERSION

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RecoveryRecord":
        return cls(**d)
