import pytest

from harness.runpod.preflight import PreflightError, assert_endpoint_matches
from placement_measure.pins import PINNED_BASE, pins

ENDPOINT = {
    "gpuTypeIds": ["NVIDIA GeForce RTX 4090"],
    "networkVolumeId": "9c7ut2slrd",
    "executionTimeoutMs": 1800000,
    "templateId": "tpl",
    "flashboot": False,
    "allowedCudaVersions": ["13.0"],
}


def test_the_pin_set_matches_the_endpoint_as_provisioned():
    assert_endpoint_matches(ENDPOINT, pins("tpl"))


def test_flashboot_is_pinned_off():
    # FlashBoot back on measures the platform's cache, not the arms, and the
    # endpoint's own response gives no sign of it (recon/README.md).
    assert PINNED_BASE["flashboot"] is False
    with pytest.raises(PreflightError, match="flashboot"):
        assert_endpoint_matches({**ENDPOINT, "flashboot": True}, pins("tpl"))


def test_the_cuda_restriction_is_pinned():
    # The image needs a CUDA 13.0 host driver; one host without it failed every
    # engine start with Error 804 and the capture still printed ok.
    assert PINNED_BASE["allowedCudaVersions"] == ["13.0"]
    with pytest.raises(PreflightError, match="allowedCudaVersions"):
        assert_endpoint_matches({**ENDPOINT, "allowedCudaVersions": []}, pins("tpl"))
    with pytest.raises(PreflightError, match="allowedCudaVersions"):
        assert_endpoint_matches({k: v for k, v in ENDPOINT.items() if k != "allowedCudaVersions"},
                                pins("tpl"))
