"""Artifact 4's endpoint pin set, checked before any job is submitted.

Same GPU class and network volume as artifacts 1 and 2, so the weights staged
on the volume are the ones every engine reads. The template is artifact 4's
own (its dockerStartCmd selects one of the two handlers) and is passed in,
because it is provisioned when the paid run is prepared. A pin set is one
experiment's boundary, so it lives with the experiment, not in `harness/`.
"""

from placement_measure.prereg import GPU_TYPE, JOB_BUDGET_S, NETWORK_VOLUME

__all__ = ["PINNED_BASE", "pins"]

PINNED_BASE = {
    "gpuTypeIds": [GPU_TYPE],
    "networkVolumeId": NETWORK_VOLUME,
    "executionTimeoutMs": JOB_BUDGET_S * 1000,
}


def pins(template_id: str) -> dict:
    if not template_id:
        raise ValueError(
            "a template id is required; without it the preflight would accept an "
            "endpoint running any image and any start command"
        )
    return {**PINNED_BASE, "templateId": template_id}
