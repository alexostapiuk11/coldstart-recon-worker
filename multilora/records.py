"""One server instance's stored result, and how it is built from a job outcome.

The worker returns, for a healthy instance (plan 3 implements it; the stub in
this package mimics it):

    healthy        True
    log_lines      the engine's startup output
    served_cmd     the exact `vllm serve` argument list
    host           host_id, gpu_model, vcpus (the submitter adds platform ids)
    adapters       {adapter name: sha256 checksum}
    phases         one dict per timed phase: phase_index, regime, adapters,
                   concurrency, num_requests, duration_s, completed, failed,
                   and the tool's raw per-request ttfts, output_lens, errors
    gauge_samples  {phase_index, t, running} per scrape

Raw arrays are stored unaltered. Amendment §3f's rules are applied at analysis
time, in `multilora.phase`, so a rule can be audited against the data it ran on.
"""

from dataclasses import asdict, dataclass, field

from harness.failures import classify_failure
from multilora import SCHEMA_VERSION
from multilora.engine import engine_facts


@dataclass
class InstanceRecord:
    schema_version: int
    run_index: int
    block_index: int
    condition: str
    run_id: str
    outcome: str  # "ok" | "failed"
    failure: str | None
    failure_class: str | None
    clock_A: dict
    host: dict = field(default_factory=dict)
    engine: dict = field(default_factory=dict)
    served_cmd: list = field(default_factory=list)
    adapters: dict = field(default_factory=dict)
    phases: list = field(default_factory=list)
    gauge_samples: list = field(default_factory=list)
    diagnostics: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "InstanceRecord":
        return cls(**d)


def build_record(scheduled, run_id: str, outcome) -> InstanceRecord:
    """A failed job is a record too: failures are data, and the failure-rate
    table counts them. Its evidence travels in `diagnostics`."""
    common = {
        "schema_version": SCHEMA_VERSION,
        "run_index": scheduled.run_index,
        "block_index": scheduled.block_index,
        "condition": scheduled.condition,
        "run_id": run_id,
        "clock_A": outcome.clock_A,
    }
    if outcome.payload is None:
        return InstanceRecord(
            **common,
            outcome="failed",
            failure=outcome.error,
            failure_class=classify_failure(outcome.error).value,
            diagnostics=outcome.diagnostics,
        )
    p = outcome.payload
    return InstanceRecord(
        **common,
        outcome="ok",
        failure=None,
        failure_class=None,
        host=dict(p.get("host") or {}),
        engine=engine_facts(p.get("log_lines") or []),
        served_cmd=list(p.get("served_cmd") or []),
        adapters=dict(p.get("adapters") or {}),
        phases=list(p.get("phases") or []),
        gauge_samples=list(p.get("gauge_samples") or []),
    )
