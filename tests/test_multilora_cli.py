import pytest

from multilora.cli import guard_against_silent_restart, pins_from_endpoint, require_credentials

ENDPOINT = {
    "flashboot": False, "gpuTypeIds": ["NVIDIA GeForce RTX 4090"], "networkVolumeId": "vol",
    "templateId": "tpl", "workersMin": 0, "name": "a5", "workersMax": 1,
}


def test_credentials_are_required():
    with pytest.raises(SystemExit, match="RUNPOD_ENDPOINT_ID"):
        require_credentials({"RUNPOD_API_KEY": "k"})
    assert require_credentials({"RUNPOD_API_KEY": "k", "RUNPOD_ENDPOINT_ID": "e"}) == ("k", "e")


def test_a_populated_store_needs_resume_or_force():
    guard_against_silent_restart(0, "s", resume=False, force=False)
    guard_against_silent_restart(5, "s", resume=True, force=False)
    guard_against_silent_restart(5, "s", resume=False, force=True)
    with pytest.raises(SystemExit, match="5 record"):
        guard_against_silent_restart(5, "s", resume=False, force=False)


def test_pins_are_the_five_fields_and_refuse_flashboot():
    assert pins_from_endpoint(ENDPOINT) == {k: ENDPOINT[k] for k in (
        "flashboot", "gpuTypeIds", "networkVolumeId", "templateId", "workersMin")}
    with pytest.raises(ValueError, match="flashboot"):
        pins_from_endpoint({**ENDPOINT, "flashboot": True})
    with pytest.raises(ValueError, match="workersMin"):
        pins_from_endpoint({**ENDPOINT, "workersMin": 1})
    with pytest.raises(ValueError, match="lacks"):
        pins_from_endpoint({"flashboot": False})
