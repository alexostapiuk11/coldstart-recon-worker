"""Refuses to start a paid window unless the endpoint still matches its pins.

Every value here is part of the experiment's boundary (spec 5, threats to
validity): a change ends the experiment rather than continuing across it. The
guard exists because the failure it catches is invisible afterwards -- an
endpoint with FlashBoot back on produces a complete, plausible dataset that
measures the platform's cache instead of the arms.
"""

import requests

REST = "https://rest.runpod.io/v1"

# `9c7ut2slrd` and `mzadx4qugv` are opaque RunPod ids; see the "Provisioned
# infrastructure" table in recon/README.md for what they actually are (the
# network volume and the container template) rather than hunting them down
# in the RunPod console.
#
# `gpuTypeIds` is compared as a list, which makes the check order-sensitive.
# That's inert today with a single element; if the pin ever grows to more
# than one GPU type, an API response that reports them in a different order
# would trip a false refusal. That's the tolerable direction of error for a
# guard whose job is to refuse to spend, so it's left as-is rather than
# sorted away -- but it's a known trade, not an oversight.
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
    """Raise unless every pinned key is present on `endpoint` with the pinned value.

    A key missing from the endpoint is treated as a mismatch, not defaulted to the
    pinned value: silently assuming an absent field already matches would let a
    RunPod API response that drops a field (or a caller that passes a partial dict)
    sail through the one check that exists to catch exactly that kind of drift.
    Fail closed on absence the same way it fails closed on a wrong value.

    `pinned` defaults to the module-level `PINNED` but can be overridden so this
    function stays testable without patching global state, and so a future
    variant of the guard (e.g. a differently-configured second endpoint) can
    reuse the same check against a different pin set. It must not be used to
    weaken the default guard: an explicitly empty override would check nothing
    and pass any endpoint, which is the exact false pass this module exists to
    prevent, so it is rejected outright below rather than allowed to iterate
    zero times.
    """
    pinned = PINNED if pinned is None else pinned
    if not pinned:
        raise ValueError("pinned configuration is empty; refusing to check nothing")
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
    """Fetch the endpoint's current config. Deliberately a single unretried GET.

    coldstart.runpod_submitter.HttpTransport retries 409/5xx because those show up
    mid-campaign on calls that submit or poll a job, where there is an in-flight
    paid run to protect and aborting over one transient blip would waste it.

    Here there is nothing in flight yet. This check runs once, before any money
    is committed, so a transient platform error costs the operator a cheap
    manual re-run rather than a wasted paid job -- which makes the retry
    machinery not worth its complexity at this checkpoint.

    Note what this reasoning does NOT claim: retrying would not weaken the
    check. A retried GET still returns whatever the endpoint reports and
    assert_endpoint_matches still validates it identically. The justification is
    the cost asymmetry, not a correctness risk.
    """
    r = requests.get(
        f"{REST}/endpoints/{endpoint_id}",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()
