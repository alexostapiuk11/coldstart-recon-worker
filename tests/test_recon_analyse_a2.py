"""The analysis is proven against artifact 1's committed recon fixtures, whose
contents fixtures/README.md and docs/recon-a2.md already document -- so every
expected value below is checked against a written record, not against this
code's own output. `fixtures/README.md`'s Q1 section and "Known gaps" give the
engine-log values (compile time, KV tokens, the weights-download gap);
`docs/recon-a2.md`'s Q2 table (lines 56-60) gives the platform lifecycle
fields (`workerId`, `delayTime`, `executionTime`)."""

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


def test_platform_execution_time_is_reported(rows):
    """docs/recon-a2.md:58-60's Q2 table, `executionTime` column."""
    assert [r["execution_ms"] for r in rows] == [150577, 53415, 50324]


def test_healthy_column_is_read_from_the_engine_reported_field(rows):
    """Each fixture's `output.healthy` is `true` (checked directly in the
    committed JSON, not derived) -- the engine came up far enough to answer
    the recon completion prompt. A COMPLETED row whose engine never came up
    would show `healthy: false` here instead of looking identical to one that
    did, which is the point of carrying this column at all."""
    assert [r["healthy"] for r in rows] == [True, True, True]


def test_a_failed_job_is_a_row_of_absences_not_a_crash(tmp_path):
    """A FAILED job carries no output. The table must show that it happened --
    dropping it would make a flaky burst look like a smaller clean one."""
    (tmp_path / "burst1_0.json").write_text(json.dumps({"status": "FAILED", "id": "j"}))
    [row] = analyse_a2.load(tmp_path, "burst*.json")
    assert row["status"] == "FAILED"
    assert row["worker_id"] is None and row["compile_s"] is None
    assert row["weights_downloaded"] is None
    assert row["healthy"] is None

    table = analyse_a2.render_table([row])
    assert "—" in table
    assert "None" not in table


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
    there was nothing to say.

    The two live rows carry DIFFERENT worker ids, and a FAILED row with no
    worker id at all is mixed in: `distinct_workers` must land on 2, not 1 --
    a mutant that excludes timeout rows, hardcodes a constant, or drops the
    None-worker filter each produce a different wrong number here, which the
    previous version of this test (both rows sharing one worker id) could not
    have caught."""
    (tmp_path / "burst1_0.timeout.json").write_text(
        json.dumps({"status": "IN_QUEUE", "id": "j0", "workerId": "w-a"})
    )
    (tmp_path / "burst1_1.json").write_text(
        json.dumps({"status": "COMPLETED", "id": "j1", "workerId": "w-b"})
    )
    (tmp_path / "burst1_2.json").write_text(
        json.dumps({"status": "FAILED", "id": "j2"})
    )
    rows = analyse_a2.load(tmp_path, "burst*.json")

    assert [r["label"] for r in rows] == ["burst1_0.timeout", "burst1_1", "burst1_2"]
    timeout_row = rows[0]
    assert timeout_row["status"] == "IN_QUEUE"
    assert timeout_row["compile_s"] is None
    assert analyse_a2.distinct_workers(rows) == 2

    table = analyse_a2.render_table(rows)
    assert "timed out (capture aborted after this burst): 1" in table

    complete_only = [r for r in rows if not r["label"].endswith(".timeout")]
    assert "timed out" not in analyse_a2.render_table(complete_only)


def test_weights_downloaded_on_the_fixtures_matches_the_documented_gap(rows):
    """fixtures/README.md's "Known gaps" (lines 108-113): all three runs found
    weights already staged on the volume, so none carries the `Time spent
    downloading weights` line -- every value here is False. It is False and
    not None because each log's `Loading weights took` line (Q1, S4a) shows
    weight loading did complete; a log that never reached that line is a
    different case, tested below."""
    assert [r["weights_downloaded"] for r in rows] == [False, False, False]


def test_weights_downloaded_is_true_when_the_download_line_is_present(tmp_path):
    """Reuses tests/test_recon_capture_a2.py's WEIGHTS_LINE shape (line 32 of
    that file) for the download line, alongside the `Loading weights took`
    completion line fixtures/README.md documents for S4a."""
    lines = [
        ("(EngineCore pid=1) INFO 01-01 00:00:00 [weight_utils.py:530] Time "
         "spent downloading weights for Qwen/Qwen3-8B via hf_transfer: 41.2 seconds"),
        ("(EngineCore pid=1) INFO 01-01 00:00:05 [default_loader.py:430] "
         "Loading weights took 41.20 seconds"),
    ]
    (tmp_path / "burst1_0.json").write_text(json.dumps(
        {"status": "COMPLETED", "id": "j", "output": {"log_lines": lines}}
    ))
    [row] = analyse_a2.load(tmp_path, "burst*.json")
    assert row["weights_downloaded"] is True


def test_weights_downloaded_is_unknown_when_the_log_ends_before_loading_finishes(tmp_path):
    """An early death -- OOM, a truncated drain, a health-poll timeout mid-load
    -- still gets recorded as COMPLETED by worker/recon_handler.py, but the
    log never reaches `Loading weights took`. Reporting False there would
    claim "found already on disk" about a run that never got far enough to
    show that; None says the engine's log never said, which is the truth."""
    lines = ["INFO starting", "CUDA out of memory"]
    (tmp_path / "burst1_0.json").write_text(json.dumps(
        {"status": "COMPLETED", "id": "j", "output": {"log_lines": lines}}
    ))
    [row] = analyse_a2.load(tmp_path, "burst*.json")
    assert row["weights_downloaded"] is None


def test_a_non_dict_output_is_refused_with_the_offending_file_named(tmp_path):
    """Every field this row reads beyond status/id comes out of `output`
    (log_lines, healthy). A string or a list there is not a malformed log --
    it is a payload shape nothing here was written to read, and reading past
    it with `.get()` would either crash on an unrelated line or, worse,
    silently report a row of absences that looks like a job that ran and said
    nothing. `load()` must name the actual file, not just the label, because
    the operator reading this error has the directory, not the parsed rows."""
    bad = tmp_path / "burst1_0.json"
    bad.write_text(json.dumps({"status": "COMPLETED", "id": "j", "output": "not-an-object"}))
    with pytest.raises(ValueError, match=str(bad)):
        analyse_a2.load(tmp_path, "burst*.json")


def test_job_files_sort_by_burst_and_numeric_index_not_lexicographically(tmp_path):
    """`burst1_10.json` must sort after `burst1_2.json`, not between
    `burst1_1.json` and `burst1_2.json`: plain lexicographic sorting on the
    path string compares "10" against "2" character by character ('1' < '2'),
    which silently reorders a burst's own jobs as soon as it grows past ten."""
    for name, status in [
        ("burst1_2.json", {"status": "COMPLETED", "id": "j2"}),
        ("burst1_10.json", {"status": "COMPLETED", "id": "j10"}),
        ("burst1_1.json", {"status": "COMPLETED", "id": "j1"}),
    ]:
        (tmp_path / name).write_text(json.dumps(status))
    rows = analyse_a2.load(tmp_path, "burst*.json")
    assert [r["label"] for r in rows] == ["burst1_1", "burst1_2", "burst1_10"]


def test_main_default_directory_is_anchored_to_the_repo_not_the_cwd():
    """Same construction as `capture_a2.OUT`: anchored to the file's own
    location, not the working directory a reader happens to run from -- a
    relative default would print an empty table from the wrong place instead
    of the fixtures the capture actually wrote."""
    assert analyse_a2.DEFAULT_CAPTURE_DIR == REPO / "fixtures" / "a2_recon"
