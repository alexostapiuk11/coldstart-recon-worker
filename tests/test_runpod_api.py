import json
from pathlib import Path

from coldstart.runpod_api import extract_lifecycle, extract_worker_id, residual_splittable

FIXTURE = Path("fixtures/runpod_api/status_0.json")

LIFECYCLE_KEYS = {"queued_at", "started_at", "completed_at", "delay_ms", "execution_ms"}


def test_extracts_whatever_lifecycle_fields_exist():
    payload = json.loads(FIXTURE.read_text())
    life = extract_lifecycle(payload)
    assert isinstance(life, dict)
    for k in life:
        assert k in LIFECYCLE_KEYS


def test_extracts_the_real_durations():
    """The pinned platform exposes durations, not absolute timestamps."""
    life = extract_lifecycle(json.loads(FIXTURE.read_text()))
    assert life["delay_ms"] == 8577
    assert life["execution_ms"] == 150577


def test_absolute_timestamps_are_absent_from_this_platform():
    """queued_at / started_at / completed_at are not exposed by RunPod --
    fixtures/README.md Q2. Their absence must not be faked."""
    life = extract_lifecycle(json.loads(FIXTURE.read_text()))
    assert "queued_at" not in life
    assert "started_at" not in life
    assert "completed_at" not in life


def test_missing_fields_are_absent_not_none():
    assert extract_lifecycle({"status": "COMPLETED"}) == {}


def test_explicit_nulls_are_treated_as_absent():
    assert extract_lifecycle({"delayTime": None, "executionTime": None}) == {}


def test_zero_duration_is_kept_not_dropped():
    """0 ms is a real measurement; truthiness checks would discard it."""
    life = extract_lifecycle({"delayTime": 0, "executionTime": 0})
    assert life == {"delay_ms": 0, "execution_ms": 0}


def test_residual_splittable_reports_honestly():
    assert residual_splittable({"delay_ms": 100, "execution_ms": 200}) is True
    assert residual_splittable({}) is False
    assert residual_splittable({"delay_ms": 100}) is False


def test_residual_is_splittable_for_every_real_capture():
    for i in range(3):
        payload = json.loads(Path(f"fixtures/runpod_api/status_{i}.json").read_text())
        assert residual_splittable(extract_lifecycle(payload)) is True


def test_extracts_worker_id_as_host_identity():
    """workerId is the platform's identity for the machine that ran the job --
    the input to within-host pairing."""
    assert extract_worker_id(json.loads(FIXTURE.read_text())) == "iiewfw59dqskoe"


def test_worker_id_is_none_when_absent():
    assert extract_worker_id({"status": "COMPLETED"}) is None


def test_all_three_captures_share_one_worker():
    """These three recon runs reused one worker, which is why the compile
    cache leaked between them -- fixtures/README.md."""
    ids = {
        extract_worker_id(json.loads(Path(f"fixtures/runpod_api/status_{i}.json").read_text()))
        for i in range(3)
    }
    assert len(ids) == 1
