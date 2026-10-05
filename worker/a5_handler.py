"""Artifact 5 measurement handler: one server instance per job.
Selected by overriding the template's dockerStartCmd."""

import runpod

from multilora.instance import run_instance
from multilora.worker_deps import real_deps
from multilora.worker_env import instance_kwargs, volume_env


def handler(job):
    return run_instance(job.get("input") or {}, deps=real_deps(), env=volume_env(), **instance_kwargs())


runpod.serverless.start({"handler": handler})
