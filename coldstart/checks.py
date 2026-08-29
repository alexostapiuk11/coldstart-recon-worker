import math
import re
from enum import StrEnum
from typing import NamedTuple

# Clock A and clock B live on different machines. The residual absorbs the
# network round trip, so a residual smaller than this floor means the two
# clocks disagree — see spec 6.5 rule 3.
DEFAULT_RTT_FLOOR = 0.05


class FailureClass(StrEnum):
    SUBMIT_ERROR = "submit_error"
    PROVISIONING_TIMEOUT = "provisioning_timeout"
    IMAGE_PULL = "image_pull"
    WEIGHT_ACQUISITION = "weight_acquisition"
    OOM = "oom"
    ENGINE_INIT = "engine_init"
    HEALTH_TIMEOUT = "health_timeout"
    TTFT_TIMEOUT = "ttft_timeout"
    UNKNOWN = "unknown"


class DiscardReason(StrEnum):
    """Mirrors FailureClass: a closed taxonomy so a downstream reader can
    tabulate discards by class instead of substring-matching the free-form
    `reason` string that check_consistency also returns.

    The first two values are produced by check_consistency below.
    MISSING_WARMUP_END is produced directly by metrics.derive(): a run
    missing S7_warmup_done can't even have a T_total correction computed
    (spec 6.5 / B1), so it never reaches check_consistency at all — it needs
    its own tabulatable reason rather than silently falling into one of the
    other two.

    ARM_STATE_MISMATCH is produced by metrics.derive() when the compile-cache
    state observed from engine output disagrees with the state the arm's
    configuration asked for. Pre-registered as an exclusion rule: an arm whose
    cache state was not what it claimed is not a slightly noisy data point, it
    is a different arm.

    ARM_STATE_UNVERIFIABLE is also produced by metrics.derive(), for the
    sibling case ARM_STATE_MISMATCH cannot cover: a live run whose worker
    payload was missing compile_cache_observed and/or
    cache_config.compile_cache_warm (coldstart/driver.py detects this and
    flags the record; derive() cannot tell it apart from a historical row
    that simply predates those fields by looking at the data alone, so the
    driver carries the distinction explicitly). Not the same as a mismatch --
    there is no disagreement to report, only an unanswerable question -- and
    not a FailureClass either: the run completed and produced a full,
    otherwise-usable measurement, so it is a discard, not a failure.
    """

    PROCESS_EXCEEDS_TOTAL = "process_exceeds_total"
    RESIDUAL_BELOW_RTT_FLOOR = "residual_below_rtt_floor"
    MISSING_WARMUP_END = "missing_warmup_end"
    ARM_STATE_MISMATCH = "arm_state_mismatch"
    ARM_STATE_UNVERIFIABLE = "arm_state_unverifiable"


class _Needle:
    """Plain substring match, unless `regex` is given for a needle short
    enough to misfire inside an unrelated word (e.g. "oom" inside "room")."""

    __slots__ = ("_regex", "text")

    def __init__(self, text: str, *, regex: re.Pattern[str] | None = None):
        self.text = text
        self._regex = regex

    def matches(self, low: str) -> bool:
        if self._regex is not None:
            return self._regex.search(low) is not None
        return self.text in low


# Row order is a priority policy, not incidental: classify_failure is
# first-match-wins, so when a failure string carries multiple signals the
# earliest matching row wins. Root cause outranks the symptom it commonly
# produces, e.g. OOM (root cause) is checked before ENGINE_INIT and
# HEALTH_TIMEOUT (symptoms an OOM often also trips).
_SIGNATURES = [
    (
        FailureClass.OOM,
        (_Needle("out of memory"), _Needle("oom", regex=re.compile(r"\boom\b"))),
    ),
    (
        FailureClass.HEALTH_TIMEOUT,
        (_Needle("health check timed out"), _Needle("health timeout")),
    ),
    (
        FailureClass.WEIGHT_ACQUISITION,
        (_Needle("download weights"), _Needle("failed to fetch"), _Needle("hf hub")),
    ),
    (FailureClass.IMAGE_PULL, (_Needle("image pull"), _Needle("manifest unknown"))),
    (
        FailureClass.PROVISIONING_TIMEOUT,
        (_Needle("no workers available"), _Needle("provisioning timed out")),
    ),
    (FailureClass.ENGINE_INIT, (_Needle("engine init"), _Needle("failed to initialize"))),
    (FailureClass.TTFT_TIMEOUT, (_Needle("first token timed out"),)),
    (FailureClass.SUBMIT_ERROR, (_Needle("submit failed"),)),
]


def classify_failure(detail: str | None) -> FailureClass:
    low = (detail or "").lower()
    for cls, needles in _SIGNATURES:
        if any(needle.matches(low) for needle in needles):
            return cls
    return FailureClass.UNKNOWN


def _validate_clock_inputs(t_total: float, t_process: float) -> None:
    """Guard both clock readings before any arithmetic — mirrors the
    precondition guards in StageRecorder.mark (coldstart/recorder.py).

    NaN compares False against every operator, so without this guard a NaN
    input falls through every check downstream and is silently accepted.
    """
    for name, value in (("t_total", t_total), ("t_process", t_process)):
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite, got {value}")
        if value < 0:
            raise ValueError(f"{name} must be non-negative, got {value}")


def compute_residual(t_total: float, t_process: float) -> float:
    """The one permitted cross-clock subtraction — see spec 6.5 rule 2."""
    _validate_clock_inputs(t_total, t_process)
    residual = t_total - t_process
    if residual < 0:
        raise ValueError(
            f"negative residual: t_process={t_process} exceeds t_total={t_total}; "
            "this run must be discarded, not corrected"
        )
    return residual


class ConsistencyResult(NamedTuple):
    """`bool(result)` reflects `ok`, so `if check_consistency(...):` is
    correct for the one function whose job is to reject."""

    ok: bool
    reason: str | None
    discard_reason: DiscardReason | None

    def __bool__(self) -> bool:
        return self.ok


def check_consistency(
    t_total: float, t_process: float, rtt_floor: float = DEFAULT_RTT_FLOOR
) -> ConsistencyResult:
    """Apply the discard rule fixed in advance (spec 6.5 rule 3).

    Detects a violation and describes it; this function does not persist
    anything, so the caller is responsible for recording the result.
    """
    _validate_clock_inputs(t_total, t_process)
    if t_process > t_total:
        return ConsistencyResult(
            False,
            f"t_process {t_process} exceeds t_total {t_total}",
            DiscardReason.PROCESS_EXCEEDS_TOTAL,
        )
    # Single source of truth for the exceeds/negative-residual invariant —
    # see compute_residual above.
    residual = compute_residual(t_total, t_process)
    if residual < rtt_floor:
        return ConsistencyResult(
            False,
            f"residual {residual} below rtt_floor {rtt_floor}",
            DiscardReason.RESIDUAL_BELOW_RTT_FLOOR,
        )
    return ConsistencyResult(True, None, None)
