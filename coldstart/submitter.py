"""Clock A. Stamps submit and result around a job, and captures failures as data."""

import time
from dataclasses import dataclass


@dataclass
class SubmitOutcome:
    clock_A: dict
    payload: dict | None
    error: str | None


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
