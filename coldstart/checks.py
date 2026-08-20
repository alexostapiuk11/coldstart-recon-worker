from enum import Enum

# Clock A and clock B live on different machines. The residual absorbs the
# network round trip, so a residual smaller than this floor means the two
# clocks disagree — see spec 6.5 rule 3.
DEFAULT_RTT_FLOOR = 0.05


class FailureClass(str, Enum):
    SUBMIT_ERROR = "submit_error"
    PROVISIONING_TIMEOUT = "provisioning_timeout"
    IMAGE_PULL = "image_pull"
    WEIGHT_ACQUISITION = "weight_acquisition"
    OOM = "oom"
    ENGINE_INIT = "engine_init"
    HEALTH_TIMEOUT = "health_timeout"
    TTFT_TIMEOUT = "ttft_timeout"
    UNKNOWN = "unknown"


_SIGNATURES = [
    (FailureClass.OOM, ("out of memory", "oom")),
    (FailureClass.HEALTH_TIMEOUT, ("health check timed out", "health timeout")),
    (FailureClass.WEIGHT_ACQUISITION, ("download weights", "failed to fetch", "hf hub")),
    (FailureClass.IMAGE_PULL, ("image pull", "manifest unknown")),
    (FailureClass.PROVISIONING_TIMEOUT, ("no workers available", "provisioning timed out")),
    (FailureClass.ENGINE_INIT, ("engine init", "failed to initialize")),
    (FailureClass.TTFT_TIMEOUT, ("first token timed out",)),
    (FailureClass.SUBMIT_ERROR, ("submit failed",)),
]


def classify_failure(detail: str) -> FailureClass:
    low = (detail or "").lower()
    for cls, needles in _SIGNATURES:
        if any(n in low for n in needles):
            return cls
    return FailureClass.UNKNOWN


def compute_residual(t_total: float, t_process: float) -> float:
    """The one permitted cross-clock subtraction — see spec 6.5 rule 2."""
    residual = t_total - t_process
    if residual < 0:
        raise ValueError(
            f"negative residual: t_process={t_process} exceeds t_total={t_total}; "
            "this run must be discarded, not corrected"
        )
    return residual


def check_consistency(
    t_total: float, t_process: float, rtt_floor: float = DEFAULT_RTT_FLOOR
) -> tuple[bool, str | None]:
    """Discard rule, fixed in advance. Violations are recorded, never silently dropped."""
    if t_process > t_total:
        return False, f"t_process {t_process} exceeds t_total {t_total}"
    if (t_total - t_process) < rtt_floor:
        return False, f"residual below rtt_floor {rtt_floor}"
    return True, None
