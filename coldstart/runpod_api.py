"""Clock C. What the platform itself says about a job's lifecycle.

Clock C is the least trusted of the three and the only one this project does not
control. It exists to split the residual `T_platform = T_total - T_process` into
queue delay versus execution, and the design has to survive the platform exposing
nothing useful at all -- so every field here is optional by construction.
"""

# Keys as they appear in the real status payload -- see fixtures/README.md Q2.
#
# RunPod reports *durations*, not absolute timestamps. `queued_at`, `started_at`
# and `completed_at` are part of the lifecycle vocabulary the analysis accepts,
# but this platform does not emit them and nothing here fabricates them from the
# durations: a derived timestamp would look like an observation while carrying
# the submitting host's clock offset, which is exactly the error clock C exists
# to avoid.
FIELD_MAP = {
    "delayTime": "delay_ms",
    "executionTime": "execution_ms",
}

# The platform's identity for the machine that ran the job. Not a lifecycle
# field, so it is deliberately not in FIELD_MAP -- but it is the input to
# within-host pairing (`stats.within_host_triples`), which removes the host
# confound, so the client exposes it rather than making callers reach into the
# raw payload.
WORKER_ID_FIELD = "workerId"


def extract_lifecycle(payload: dict) -> dict:
    """Clock C. Returns only fields the platform actually exposes.

    Absent fields are omitted rather than set to None, so downstream code can
    check presence without ambiguity -- the residual split is opportunistic
    (spec 6.5) and the design must work if nothing useful is exposed.

    An explicit null is treated as absent. A zero is not: 0 ms of queue delay is
    a real measurement, and a truthiness check here would silently discard the
    fastest runs, biasing the very quantity being measured.
    """
    out = {}
    for src, dst in FIELD_MAP.items():
        if src in payload and payload[src] is not None:
            out[dst] = payload[src]
    return out


def residual_splittable(lifecycle: dict) -> bool:
    """True when clock C can split T_platform into queue delay vs bring-up.

    Both halves are required. One alone cannot partition the residual, and
    reporting a partial split as a split would overstate what is known.
    """
    return "delay_ms" in lifecycle and "execution_ms" in lifecycle


def extract_worker_id(payload: dict) -> str | None:
    """The platform's host identity for this run, or None if not reported.

    Returned as None rather than omitted because, unlike the lifecycle fields,
    there is exactly one of these and callers want to store it unconditionally.
    """
    value = payload.get(WORKER_ID_FIELD)
    return value if value else None
