"""Refuses to start a paid window unless the endpoint still matches its pins.

Every value here is part of the experiment's boundary (spec 5, threats to
validity): a change ends the experiment rather than continuing across it. The
guard exists because the failure it catches is invisible afterwards -- an
endpoint with FlashBoot back on produces a complete, plausible dataset that
measures the platform's cache instead of the arms.
"""

import requests

REST = "https://rest.runpod.io/v1"

PINNED = {
    "flashboot": False,
    "gpuTypeIds": ["NVIDIA GeForce RTX 4090"],
    "networkVolumeId": "9c7ut2slrd",
    "templateId": "mzadx4qugv",
    "workersMin": 0,
}


class PreflightError(RuntimeError):
    """The endpoint no longer matches the pinned configuration."""


def assert_endpoint_matches(endpoint: dict, pinned: dict | None = None) -> None:
    pinned = PINNED if pinned is None else pinned
    problems = []
    for key, expected in pinned.items():
        if key not in endpoint:
            problems.append(f"{key}: absent from the endpoint, expected {expected!r}")
        elif endpoint[key] != expected:
            problems.append(f"{key}: {endpoint[key]!r}, expected {expected!r}")
    if problems:
        raise PreflightError(
            "endpoint does not match the pinned configuration; refusing to spend:\n  "
            + "\n  ".join(problems)
        )


def fetch_endpoint(endpoint_id: str, api_key: str) -> dict:
    r = requests.get(
        f"{REST}/endpoints/{endpoint_id}",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()
