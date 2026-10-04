"""Artifact 1's pinned endpoint configuration — the experiment's boundary.

Every value here is part of what the published result is a measurement OF
(spec 5, threats to validity): a change ends the experiment rather than
continuing across it. `harness.runpod.preflight.assert_endpoint_matches` does
the checking; this module is only what artifact 1 checks against, which is why
it does not live in the harness.

`9c7ut2slrd` and `mzadx4qugv` are opaque RunPod ids; see the "Provisioned
infrastructure" table in recon/README.md for what they actually are (the
network volume and the container template) rather than hunting them down in
the RunPod console.

`gpuTypeIds` is compared as a list, which makes the check order-sensitive.
That's inert today with a single element; if the pin ever grows to more than
one GPU type, an API response that reports them in a different order would
trip a false refusal. That's the tolerable direction of error for a guard whose
job is to refuse to spend, so it's left as-is -- but it's a known trade, not an
oversight.
"""

PINNED = {
    "flashboot": False,
    "gpuTypeIds": ["NVIDIA GeForce RTX 4090"],
    "networkVolumeId": "9c7ut2slrd",
    "templateId": "mzadx4qugv",
    "workersMin": 0,
}
