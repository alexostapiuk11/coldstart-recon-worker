"""The real effects behind `multilora.instance.Deps`, used only in the worker
image. Imports are local so the package imports without huggingface_hub,
which the vLLM image carries and a laptop need not."""

import json
import os
import socket
import subprocess

import requests

from multilora.instance import Deps


def model_config(model: str, revision: str) -> dict:
    from huggingface_hub import hf_hub_download

    with open(hf_hub_download(model, "config.json", revision=revision)) as f:
        return json.load(f)


def download_adapter(repo: str, revision: str, dest: str) -> None:
    from huggingface_hub import snapshot_download

    snapshot_download(
        repo, revision=revision, local_dir=dest,
        allow_patterns=["adapter_config.json", "adapter_model.safetensors"],
    )


def http_get(url: str) -> str:
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    return r.text


def post_status(url: str, body: dict) -> int:
    return requests.post(url, json=body, timeout=120).status_code


def post_json(url: str, body: dict) -> dict:
    r = requests.post(url, json=body, timeout=60)
    r.raise_for_status()
    return r.json()


def host_info() -> dict:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=15, check=False,
        ).stdout.strip()
        gpu, driver = (p.strip() for p in out.split(",")[:2])
    except Exception:  # noqa: BLE001 -- host metadata never fails a measured run
        gpu, driver = "unknown", "unknown"
    return {
        "gpu_model": gpu,
        "driver_version": driver,
        "host_id": socket.gethostname(),
        "vcpus": os.cpu_count(),
        "runpod_pod_id": os.environ.get("RUNPOD_POD_ID"),
    }


def real_deps() -> Deps:
    return Deps(
        model_config=model_config,
        download_adapter=download_adapter,
        http_get=http_get,
        host_info=host_info,
    )
