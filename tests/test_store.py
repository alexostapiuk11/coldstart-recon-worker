import json

from coldstart.schema import SCHEMA_VERSION, RunRecord
from coldstart.store import JsonlStore


def make_record(run_id="r1", run_index=0, arm="A"):
    return RunRecord(
        run_id=run_id,
        run_index=run_index,
        arm=arm,
        clock_A={"t_submit": 1000.0, "t_result": 1090.0},
        clock_C={},
        clock_B={"t0_wall": 1000.4, "marks": [{"stage": "S1", "t_mono": 2.0}]},
        warmup=[],
        engine={},
        host={"host_id": "h1", "first_touch": True},
        config={"vllm_version": "0.0.0"},
        status={"outcome": "ok", "failure_class": None, "failure_detail": None},
    )


def test_every_field_survives_the_round_trip(tmp_path):
    path = tmp_path / "runs.jsonl"
    store = JsonlStore(path)
    store.append(make_record())

    on_disk = json.loads(path.read_text().strip())
    assert on_disk["run_id"] == "r1"
    assert on_disk["run_index"] == 0
    assert on_disk["arm"] == "A"
    assert on_disk["clock_A"] == {"t_submit": 1000.0, "t_result": 1090.0}
    assert on_disk["clock_B"] == {"t0_wall": 1000.4, "marks": [{"stage": "S1", "t_mono": 2.0}]}
    assert on_disk["clock_C"] == {}
    assert on_disk["warmup"] == []
    assert on_disk["engine"] == {}
    assert on_disk["host"] == {"host_id": "h1", "first_touch": True}
    assert on_disk["config"] == {"vllm_version": "0.0.0"}
    assert on_disk["status"] == {"outcome": "ok", "failure_class": None, "failure_detail": None}
    assert on_disk["schema_version"] == SCHEMA_VERSION
    assert set(on_disk) == set(RunRecord.__dataclass_fields__)

    assert store.read_all()[0].to_dict() == on_disk


def test_append_is_additive(tmp_path):
    store = JsonlStore(tmp_path / "runs.jsonl")
    store.append(make_record("r1", 0, "A"))
    store.append(make_record("r2", 1, "B"))
    assert [r.run_id for r in store.read_all()] == ["r1", "r2"]


def test_unknown_schema_version_is_rejected(tmp_path):
    path = tmp_path / "runs.jsonl"
    path.write_text('{"schema_version": 999, "run_id": "x"}\n')
    store = JsonlStore(path)
    try:
        store.read_all()
    except ValueError as e:
        assert "999" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_missing_file_reads_as_empty(tmp_path):
    assert JsonlStore(tmp_path / "nope.jsonl").read_all() == []


def test_fields_from_a_newer_build_are_ignored(tmp_path):
    path = tmp_path / "runs.jsonl"
    rec = make_record().to_dict()
    rec["field_from_the_future"] = 42
    path.write_text(json.dumps(rec) + "\n")
    got = JsonlStore(path).read_all()
    assert len(got) == 1
    assert got[0].run_id == "r1"


def test_parent_directories_are_created(tmp_path):
    store = JsonlStore(tmp_path / "deep" / "nested" / "runs.jsonl")
    store.append(make_record())
    assert len(store.read_all()) == 1
