"""Clock A. Stamps submit and result around a job, and captures failures as data."""

import json
import time
from dataclasses import dataclass


@dataclass
class SubmitOutcome:
    clock_A: dict
    payload: dict | None
    error: str | None
    # What the worker returned on a run that failed but still reported
    # something. `payload` stays None for a failure so nothing downstream can
    # mistake it for a usable run; this carries the engine output that explains
    # WHY it failed. A health-timeout run is the case that matters: the probe
    # returns its log lines with healthy=False, and without this they are
    # dropped -- discarding the evidence for exactly the runs that need it.
    diagnostics: dict | None = None


class StubSubmitter:
    """Clock A against the in-process stub. Same interface as the real submitter.

    `t_result` is stamped after the endpoint returns, which for a
    request/response worker is after all ten warmup requests (S7) complete --
    not at first token of request 1 (S6), the spec's `T_total` boundary
    (spec 7). `t_result - t_submit` is therefore NOT `T_total` and must not be
    treated as such downstream: `metrics.derive()` recovers `T_total` by
    subtracting the clock-B warmup tail (`S7_warmup_done - S6_first_token`)
    from this raw span. See B1.
    """

    def __init__(self, endpoint, clock=time.monotonic):
        self._endpoint = endpoint
        self._clock = clock

    def submit(self, arm: str, run_id: str) -> SubmitOutcome:
        """Run one job. `run_id` is supplied by the caller, never generated here.

        The arm's cache paths are namespaced by `run_id` (`CacheConfig.env`), so
        the id the endpoint runs under has to be the id the stored record
        carries. Generating one here -- or taking the platform's job id after
        the fact -- would leave the paths a run actually used unreconstructible
        from `RunRecord.run_id`.
        """
        t_submit = self._clock()
        try:
            payload = self._endpoint.run(arm=arm, run_id=run_id)
            error = None
        except Exception as e:  # noqa: BLE001 -- failures are data (spec 6.6)
            payload, error = None, str(e)
        # Stamped on both paths: a failed run still consumed wall-clock time and
        # still counts in the failure-rate table.
        t_result = self._clock()
        return SubmitOutcome(
            clock_A={"t_submit": t_submit, "t_result": t_result},
            payload=payload,
            error=error,
        )


# The text harness.runpod.submitter raises for a completed job whose engine
# never became healthy, phrased to match harness.failures' HEALTH_TIMEOUT
# needle. Repeated here rather than imported: the RunPod submitter imports this
# module, so importing back would be a cycle. tests/test_payload_stub_submitter.py
# pins that the two stay identical.
UNHEALTHY_ERROR = "health check timed out: probe reported unhealthy"


class PayloadStubSubmitter:
    """`submit_payload(payload)` against an in-process worker function.

    The GPU-free twin of `RunPodSubmitter.submit_payload`, for workers whose
    input is more than artifact 1's arm and run id. `StubSubmitter` cannot
    stand in for that: its interface is `submit(arm, run_id)`.

    It copies the real submitter's one decision about a worker's output: a job
    that completes with an output whose `healthy` is falsy is a FAILURE, with
    the output kept as diagnostics. A stub that accepted any output would let a
    GPU-free test pass a handler that forgets to return `healthy: True` -- and
    the real submitter would then record every paid run as failed.

    The payload and the output both round-trip through JSON, because the real
    transport serialises both. A payload that only works in-process (a tuple
    that comes back a list, a Path that does not serialise at all) fails here,
    as data, instead of on the first paid job.

    Not reproduced: clock C and the platform's worker id, which only the
    platform knows. Records built from this stub carry neither.
    """

    def __init__(self, worker, clock=time.monotonic):
        self._worker = worker
        self._clock = clock

    def submit_payload(self, payload: dict) -> SubmitOutcome:
        t_submit = self._clock()
        try:
            output = json.loads(json.dumps(self._worker(json.loads(json.dumps(payload)))))
            if output.get("healthy"):
                result, error, diagnostics = output, None, None
            else:
                result, error, diagnostics = None, UNHEALTHY_ERROR, output
        except Exception as e:  # noqa: BLE001 -- failures are data (spec 6.6)
            result, error, diagnostics = None, str(e), None
        t_result = self._clock()
        return SubmitOutcome(
            clock_A={"t_submit": t_submit, "t_result": t_result},
            payload=result,
            error=error,
            diagnostics=diagnostics,
        )
