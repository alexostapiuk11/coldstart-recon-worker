"""Refuses to start a paid window unless the endpoint still matches its pins.

The pins are the caller's: every value in a pin set is part of an experiment's
boundary (spec 5, threats to validity), and a change ends the experiment rather
than continuing across it. Artifact 1's live in `coldstart/pins.py`.

The guard exists because the failure it catches is invisible afterwards -- an
endpoint with FlashBoot back on produces a complete, plausible dataset that
measures the platform's cache instead of the arms.
"""

import requests

REST = "https://rest.runpod.io/v1"


class PreflightError(RuntimeError):
    """The endpoint no longer matches the pinned configuration."""


def assert_endpoint_matches(endpoint: dict, pinned: dict) -> None:
    """Raise unless every pinned key is present on `endpoint` with the pinned value.

    A key missing from the endpoint is treated as a mismatch, not defaulted to the
    pinned value: silently assuming an absent field already matches would let a
    RunPod API response that drops a field (or a caller that passes a partial dict)
    sail through the one check that exists to catch exactly that kind of drift.
    Fail closed on absence the same way it fails closed on a wrong value.

    `pinned` is required and has no default: the harness does not know which
    experiment it is guarding, and defaulting to one artifact's pin set would
    let another artifact's runner validate its endpoint against the wrong
    configuration and pass for the wrong reason. An explicitly empty override
    would check nothing and pass any endpoint -- the exact false pass this
    module exists to prevent -- so it is rejected outright below rather than
    allowed to iterate zero times.
    """
    # explainer:preflight-refuses
    # A guard handed nothing to check could simply check nothing and pass --
    # iterating zero times over an empty pin set reports success on any
    # endpoint at all, which is the exact false pass this module exists to
    # prevent. It refuses instead. Same instinct one line down: a key absent
    # from the endpoint counts as a mismatch rather than being assumed fine.
    if not pinned:
        raise ValueError("pinned configuration is empty; refusing to check nothing")
    # explainer:end
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

    harness.runpod.submitter.HttpTransport retries 409/5xx because those show up
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
