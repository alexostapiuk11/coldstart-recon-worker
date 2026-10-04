"""Platform and engine failure strings, classified into a closed taxonomy.

Lives in the harness rather than beside artifact 1's clock checks because none
of these signatures are about cold starts: an OOM, an image pull failure, or a
health-check timeout looks the same whichever experiment was running when it
happened, and every artifact has to report a failure rate by class alongside
its latency numbers.
"""

import re
from enum import StrEnum


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
