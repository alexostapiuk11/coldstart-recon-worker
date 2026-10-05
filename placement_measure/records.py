"""The stored record of one measurement job, and the `build_record` callback
`harness.campaign.run_campaign` calls.

One record type for both kinds of job: the worker's output is kept whole
(`output`), and the reductions in `placement.inputs` read the fields they need
from it. Splitting it into typed fields here would decide, before any paid run,
which readings matter; the swap's memory samples and the cell's neighbour-load
samples are the evidence a reader checks a reduction against.

`outcome` is "ok" only if the job returned AND produced its measurement: a
swap with a time, a cell with a run. A job whose engine never came up, or
whose measurement failed, is "failed", with the reason, and still stored, so
the failure-rate table counts it (spec 6.6).
"""

from dataclasses import asdict, dataclass

from harness.scheduler import ScheduledRun

__all__ = ["SCHEMA_VERSION", "A4Run", "build_record"]

SCHEMA_VERSION = 1


@dataclass
class A4Run:
    run_id: str
    run_index: int
    condition: str
    block_index: int
    kind: str
    outcome: str
    failure: str | None
    clock_A: dict
    output: dict | None
    source: str
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "A4Run":
        if d.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(
                f"record schema {d.get('schema_version')!r}; this build reads {SCHEMA_VERSION}"
            )
        return cls(**d)


def _failure_of(kind: str, output: dict) -> str | None:
    if kind == "swap":
        return None if output.get("swap_s") is not None else (output.get("failure") or "no swap time")
    if kind == "sleep":
        return None if output.get("switch_s") is not None else (
            output.get("failure") or "no switch time")
    if output.get("run") is None:
        return output.get("run_error") or "no measured run"
    return None


def build_record(scheduled: ScheduledRun, run_id: str, outcome, *, kind: str, source: str) -> A4Run:
    base = {"run_id": run_id, "run_index": scheduled.run_index, "condition": scheduled.condition,
            "block_index": scheduled.block_index, "kind": kind, "clock_A": dict(outcome.clock_A),
            "source": source}
    if outcome.error is not None:
        return A4Run(**base, outcome="failed", failure=outcome.error, output=outcome.diagnostics)
    failure = _failure_of(kind, outcome.payload)
    return A4Run(**base, outcome="failed" if failure else "ok", failure=failure,
                 output=outcome.payload)
