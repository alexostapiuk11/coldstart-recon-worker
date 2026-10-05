"""Artifact 5 reconnaissance handler. Captures; publishes nothing.
Selected by overriding the template's dockerStartCmd, as recon_handler.py is."""

import runpod

from multilora.recon import run_probe
from multilora.worker_deps import post_json, post_status, real_deps
from multilora.worker_env import instance_kwargs, volume_env


def handler(job):
    payload = job.get("input") or {}
    if payload.get("probe") == "help":
        return run_probe(payload, deps=None, post_status=None)
    return run_probe(
        payload, deps=real_deps(), post_status=post_status, post_json=post_json,
        env=volume_env(), **instance_kwargs(),
    )


runpod.serverless.start({"handler": handler})
