from dataclasses import asdict, dataclass

import pytest

from harness.campaign import run_campaign
from harness.scheduler import build_schedule
from harness.store import JsonlStore
from harness.submit import SubmitOutcome


@dataclass
class Row:
    run_index: int
    condition: str
    run_id: str
    ok: bool

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Row":
        return cls(**d)


class Recorder:
    def __init__(self, fail_at: int | None = None):
        self.calls: list[tuple[int, str]] = []
        self.fail_at = fail_at

    def submit(self, scheduled, run_id):
        self.calls.append((scheduled.run_index, scheduled.condition))
        if scheduled.run_index == self.fail_at:
            raise KeyboardInterrupt  # an operator stopping the window mid-run
        return SubmitOutcome(clock_A={"t_submit": 0.0, "t_result": 1.0}, payload={}, error=None)


def _build(scheduled, run_id, outcome):
    return Row(scheduled.run_index, scheduled.condition, run_id, outcome.error is None)


def _run(store, schedule, submitter, **kw):
    return run_campaign(
        schedule,
        submitter.submit,
        _build,
        store,
        index_of=lambda r: r.run_index,
        condition_of=lambda r: r.condition,
        **kw,
    )


def test_one_record_per_scheduled_run_in_schedule_order(tmp_path):
    store = JsonlStore(tmp_path / "runs.jsonl", Row)
    schedule = build_schedule(["x", "y"], blocks=3, seed=4)
    _run(store, schedule, Recorder())
    rows = store.read_all()
    assert [r.run_index for r in rows] == list(range(6))
    assert [r.condition for r in rows] == [s.condition for s in schedule]


def test_run_ids_are_generated_by_the_caller_supplied_factory(tmp_path):
    store = JsonlStore(tmp_path / "runs.jsonl", Row)
    ids = iter(["id0", "id1"])
    _run(store, build_schedule(["x"], blocks=2, seed=1), Recorder(), make_run_id=lambda: next(ids))
    assert [r.run_id for r in store.read_all()] == ["id0", "id1"]


def test_resume_skips_what_is_stored_and_keeps_the_schedule(tmp_path):
    store = JsonlStore(tmp_path / "runs.jsonl", Row)
    schedule = build_schedule(["x", "y", "z"], blocks=3, seed=9)
    with pytest.raises(KeyboardInterrupt):
        _run(store, schedule, Recorder(fail_at=4))
    second = Recorder()
    _run(store, schedule, second, resume=True)
    assert [i for i, _ in second.calls] == list(range(4, 9))
    assert [r.run_index for r in store.read_all()] == list(range(9))


def test_resume_refuses_a_drifted_schedule(tmp_path):
    store = JsonlStore(tmp_path / "runs.jsonl", Row)
    _run(store, build_schedule(["x", "y", "z"], blocks=3, seed=9), Recorder())
    drifted = build_schedule(["x", "y", "z"], blocks=3, seed=10)
    first_stored = store.read_all()[0]
    assert drifted[0].condition != first_stored.condition, "pick seeds whose first slot differs"
    with pytest.raises(ValueError) as e:
        _run(store, drifted, Recorder(), resume=True)
    msg = str(e.value)
    assert "run_index 0" in msg
    assert repr(first_stored.condition) in msg
    assert repr(drifted[0].condition) in msg


def test_resume_refuses_a_shrunk_schedule(tmp_path):
    store = JsonlStore(tmp_path / "runs.jsonl", Row)
    _run(store, build_schedule(["x", "y"], blocks=3, seed=2), Recorder())
    with pytest.raises(ValueError, match="beyond"):
        _run(store, build_schedule(["x", "y"], blocks=1, seed=2), Recorder(), resume=True)


def test_resume_is_off_by_default(tmp_path):
    store = JsonlStore(tmp_path / "runs.jsonl", Row)
    schedule = build_schedule(["x"], blocks=2, seed=1)
    _run(store, schedule, Recorder())
    again = Recorder()
    _run(store, schedule, again)
    assert len(again.calls) == 2
    assert len(store.read_all()) == 4
