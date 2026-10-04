import pytest

from coldstart.pins import PINNED
from harness.runpod.preflight import PreflightError, assert_endpoint_matches

OK = {
    "id": "ka5mryakkxumew",
    "flashboot": False,
    "gpuTypeIds": ["NVIDIA GeForce RTX 4090"],
    "networkVolumeId": "9c7ut2slrd",
    "templateId": "mzadx4qugv",
    "workersMin": 0,
}


def test_matching_endpoint_passes():
    assert_endpoint_matches(OK, PINNED)


def test_flashboot_enabled_is_refused():
    """The failure this catches produces plausible numbers, not an error:
    FlashBoot caches exactly what the experiment measures."""
    with pytest.raises(PreflightError, match="flashboot"):
        assert_endpoint_matches(dict(OK, flashboot=True), PINNED)


def test_wrong_gpu_is_refused():
    with pytest.raises(PreflightError, match="gpuTypeIds"):
        assert_endpoint_matches(dict(OK, gpuTypeIds=["NVIDIA L4"]), PINNED)


def test_wrong_volume_is_refused():
    with pytest.raises(PreflightError, match="networkVolumeId"):
        assert_endpoint_matches(dict(OK, networkVolumeId="other"), PINNED)


def test_warm_workers_are_refused():
    """workersMin > 0 keeps a worker alive between runs, so a 'cold' start is
    not cold."""
    with pytest.raises(PreflightError, match="workersMin"):
        assert_endpoint_matches(dict(OK, workersMin=1), PINNED)


def test_every_pinned_key_is_checked():
    """A key added to PINNED must actually be asserted, or the guard silently
    stops covering it."""
    for key in PINNED:
        broken = dict(OK)
        broken[key] = "definitely-wrong"
        with pytest.raises(PreflightError, match=key):
            assert_endpoint_matches(broken, PINNED)


def test_missing_key_is_refused_not_defaulted():
    broken = dict(OK)
    del broken["flashboot"]
    with pytest.raises(PreflightError, match="flashboot"):
        assert_endpoint_matches(broken, PINNED)


def test_empty_pinned_override_is_refused():
    """An explicitly empty `pinned` would otherwise iterate zero times and pass
    any endpoint -- the exact false pass this guard exists to prevent."""
    with pytest.raises(ValueError, match="empty"):
        assert_endpoint_matches(OK, pinned={})


def test_the_check_refuses_to_guess_which_pins_to_check_against():
    """The harness cannot carry artifact 1's endpoint. Requiring `pinned` means
    a second artifact's runner cannot accidentally validate its endpoint against
    artifact 1's RTX 4090 pin set and pass for the wrong reason."""
    with pytest.raises(TypeError):
        assert_endpoint_matches({"flashboot": False})


def test_artifact_ones_pins_still_reject_a_drifted_endpoint():
    drifted = {**PINNED, "flashboot": True}
    with pytest.raises(PreflightError, match="flashboot"):
        assert_endpoint_matches(drifted, PINNED)
