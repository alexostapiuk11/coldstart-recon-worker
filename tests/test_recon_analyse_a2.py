"""The analysis is proven against artifact 1's committed recon fixtures, whose
contents fixtures/README.md already documents -- so every expected value below
is checked against a written record, not against this code's own output."""

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "recon"))

import analyse_a2

FIXTURES = REPO / "fixtures" / "runpod_api"


@pytest.fixture(scope="module")
def rows():
    return analyse_a2.load(FIXTURES, "status_*.json")


def test_one_row_per_captured_job(rows):
    assert [r["label"] for r in rows] == ["status_0", "status_1", "status_2"]


def test_the_worker_identity_is_read_off_the_payload(rows):
    """fixtures/README.md: all three landed on worker iiewfw59dqskoe."""
    assert {r["worker_id"] for r in rows} == {"iiewfw59dqskoe"}
    assert analyse_a2.distinct_workers(rows) == 1


def test_compile_time_separates_a_cold_container_from_a_warm_one(rows):
    """fixtures/README.md's table: 38.96 s cold, then 0.30 s and 0.29 s."""
    assert [r["compile_s"] for r in rows] == pytest.approx([38.96, 0.30, 0.29])


def test_kv_capacity_is_reported(rows):
    assert [r["kv_tokens"] for r in rows] == [35792, 43040, 43040]


def test_platform_delay_is_reported(rows):
    assert [r["delay_ms"] for r in rows] == [8577, 127, 127]


def test_a_failed_job_is_a_row_of_absences_not_a_crash(tmp_path):
    """A FAILED job carries no output. The table must show that it happened --
    dropping it would make a flaky burst look like a smaller clean one."""
    (tmp_path / "burst1_0.json").write_text(json.dumps({"status": "FAILED", "id": "j"}))
    [row] = analyse_a2.load(tmp_path, "burst*.json")
    assert row["status"] == "FAILED"
    assert row["worker_id"] is None and row["compile_s"] is None


def test_an_empty_capture_directory_is_refused(tmp_path):
    with pytest.raises(ValueError, match="no job payloads"):
        analyse_a2.load(tmp_path, "burst*.json")


def test_the_table_renders_every_row(rows):
    table = analyse_a2.render_table(rows)
    assert table.count("iiewfw59dqskoe") == 3
    assert "38.96" in table


def test_a_timeout_row_is_kept_counted_as_a_worker_and_flagged_in_the_table(tmp_path):
    """Amendment to Task 3, from code review: a job still unfinished at its
    polling deadline is saved as `<label>.timeout.json`, its last non-terminal
    status verbatim -- and `load()`'s glob matches it too, because `*` matches
    `.`. Dropping it would make an aborted capture look like a smaller clean
    one, the same reasoning as the FAILED-row test above; keeping its
    worker_id in `distinct_workers` is right too, because a worker that picked
    up the job is real evidence of a worker even though the job itself never
    finished. `render_table` must say a burst was aborted, so no reader
    mistakes the table for a completed run -- and must say nothing extra when
    there was nothing to say."""
    (tmp_path / "burst1_0.timeout.json").write_text(
        json.dumps({"status": "IN_QUEUE", "id": "j0", "workerId": "w-cold"})
    )
    (tmp_path / "burst1_1.json").write_text(
        json.dumps({"status": "COMPLETED", "id": "j1", "workerId": "w-cold"})
    )
    rows = analyse_a2.load(tmp_path, "burst*.json")

    assert [r["label"] for r in rows] == ["burst1_0.timeout", "burst1_1"]
    timeout_row = rows[0]
    assert timeout_row["status"] == "IN_QUEUE"
    assert timeout_row["compile_s"] is None
    assert analyse_a2.distinct_workers(rows) == 1

    table = analyse_a2.render_table(rows)
    assert "timed out (capture aborted after this burst): 1" in table

    complete_only = [r for r in rows if not r["label"].endswith(".timeout")]
    assert "timed out" not in analyse_a2.render_table(complete_only)
