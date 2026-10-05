from pathlib import Path

from harness.scheduler import ScheduledRun
from harness.store import JsonlStore
from harness.submit import SubmitOutcome
from multilora import SCHEMA_VERSION
from multilora.campaign import job_payload
from multilora.records import InstanceRecord, build_record

LOG = (Path(__file__).resolve().parents[1] / "fixtures/vllm_logs/startup_1.log").read_text()


def test_an_ok_outcome_becomes_a_record_with_engine_facts():
    payload = {
        "healthy": True,
        "log_lines": LOG.splitlines(),
        "served_cmd": ["vllm", "serve"],
        "host": {"host_id": "w1", "vcpus": 16},
        "adapters": {"a00": "abc"},
        "phases": [{"phase_index": 0}],
        "gauge_samples": [],
    }
    rec = build_record(
        ScheduledRun(3, 1, "sweep-N1"), "run-x",
        SubmitOutcome(clock_A={"t_submit": 1.0, "t_result": 2.0}, payload=payload, error=None),
    )
    assert rec.outcome == "ok" and rec.schema_version == SCHEMA_VERSION
    assert (rec.run_index, rec.block_index, rec.condition) == (3, 1, "sweep-N1")
    assert rec.engine["compile_state"] == "warm"
    assert rec.engine["kv_capacity_tokens"] == 43_040
    assert rec.host["vcpus"] == 16


def test_a_failed_outcome_is_a_classified_record_with_its_evidence():
    rec = build_record(
        ScheduledRun(0, 0, "gate"), "run-y",
        SubmitOutcome(
            clock_A={"t_submit": 0.0, "t_result": 9.0},
            payload=None,
            error="health check timed out: probe reported unhealthy",
            diagnostics={"log_lines": ["CUDA out of memory"]},
        ),
    )
    assert rec.outcome == "failed"
    assert rec.failure_class == "health_timeout"
    assert rec.diagnostics == {"log_lines": ["CUDA out of memory"]}
    assert rec.phases == []


def test_records_round_trip_through_the_harness_store(tmp_path):
    store = JsonlStore(tmp_path / "a5.jsonl", InstanceRecord)
    rec = InstanceRecord(1, 0, 0, "sweep-N2", "r", "ok", None, None, {"t_submit": 0.0},
                         engine={"compile_state": "warm"})
    store.append(rec)
    assert store.read_all() == [rec]


def test_the_job_payload_carries_everything_the_worker_needs(prereg):
    payload = job_payload(ScheduledRun(5, 0, "diag-N16"), "run-z", prereg)
    assert payload["n_slots"] == 16
    assert payload["registered"] == [f"a{i:02d}" for i in range(16)]
    assert payload["specialize_active_lora"] is True
    assert payload["disable_log_stats"] is False
    assert payload["concurrency"] == prereg.concurrency
    assert payload["requests_per_phase"] == prereg.requests_per_phase
    assert len(payload["phases"]) == 4
    assert {p["regime"] for p in payload["phases"]} == {"concentrated", "spread"}
    assert payload["dataset_args"] == list(prereg.bench_dataset_args)
    assert payload["real_adapters"] == []


def test_a_gate_payload_names_each_real_adapter_and_its_revision(prereg):
    payload = job_payload(ScheduledRun(0, 0, "gate"), "run-g", prereg)
    assert payload["n_slots"] == 8
    assert payload["real_adapters"][0] == {
        "name": "r00", "repo": "example/adapter-0", "revision": "rev0",
    }
