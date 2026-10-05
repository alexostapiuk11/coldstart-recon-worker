"""Amendment 3 (docs/experiment-a5.md) extends the larger gate from 144 to 196
scheduled instances, run with --resume into the same store, to replace the 52
that a host fault cost it. These pin the mechanism the paid run depends on:
the extended schedule agrees with the stored one, resume appends exactly the
52 new run indices, and the 144 stored records are not touched."""

from dataclasses import replace

from harness.store import JsonlStore
from harness.submit import PayloadStubSubmitter
from multilora.campaign import run
from multilora.conditions import gate_schedule, parse_condition, phase_plan
from multilora.prereg_values import PREREG
from multilora.records import InstanceRecord
from multilora.stub import StubInstanceEndpoint

STORED, EXTENDED = 144, 196
FAILED = range(92, 144)


def _worker(failing):
    endpoint = StubInstanceEndpoint(seed=0)

    def worker(payload):
        if payload["run_index"] in failing:
            return {"healthy": False, "host": {"host_id": "bad-host"}, "log_lines": ["Error 804"]}
        return endpoint.run(payload)

    return worker


def test_the_amended_gate_is_the_stored_gate_plus_52():
    assert PREREG.gate_instances == EXTENDED == STORED + len(FAILED)
    stored = gate_schedule(replace(PREREG, gate_instances=STORED))
    extended = gate_schedule(PREREG)
    assert extended[:STORED] == stored
    gate = parse_condition(extended[0].condition, PREREG)
    assert [phase_plan(gate, PREREG, i) for i in range(STORED)] == [
        phase_plan(gate, replace(PREREG, gate_instances=STORED), i) for i in range(STORED)
    ]


def test_resume_appends_exactly_the_52_replacements_and_leaves_the_store_alone(tmp_path):
    store = JsonlStore(tmp_path / "gate.jsonl", InstanceRecord)
    first = replace(PREREG, gate_instances=STORED)
    run(gate_schedule(first), PayloadStubSubmitter(_worker(set(FAILED))), store, first)
    before = store.path.read_text()
    stored = store.read_all()
    assert len(stored) == STORED
    assert [r.run_index for r in stored if r.outcome != "ok"] == list(FAILED)

    extended = replace(PREREG, gate_instances=EXTENDED)
    run(gate_schedule(extended), PayloadStubSubmitter(_worker(set())), store, extended,
        resume=True)
    after = store.path.read_text()
    assert after.startswith(before)
    records = store.read_all()
    assert records[:STORED] == stored
    new = records[STORED:]
    assert len(new) == EXTENDED - STORED == 52
    assert [r.run_index for r in new] == list(range(STORED, EXTENDED))
    assert all(r.outcome == "ok" and r.condition == "gate" for r in new)
    # The failed records stay; nothing re-runs them in place.
    assert sorted(r.run_index for r in records if r.outcome != "ok") == list(FAILED)
