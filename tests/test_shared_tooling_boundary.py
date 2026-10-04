"""The shared in-container tooling loads no artifact's package.

`tests/test_harness_boundary.py` parses direct imports. That misses a module
that imports something which imports coldstart, so this file imports each new
module in a fresh interpreter and inspects `sys.modules` afterwards, the
pattern plan 2a uses for `autoscale/validation_band.py`. `autoscale` is banned
as well as `coldstart`: artifact 5's package refuses to load `autoscale`, and
it imports these modules.
"""

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
BANNED = ("coldstart", "autoscale")
SHARED = [
    "harness.serve",
    "harness.bench",
    "harness.gpu_util",
    "harness.campaign",
    "harness.submit",
    "harness.runpod.submitter",
    "harness.service_sweep",
    "harness.sweep_worker",
]


def _loaded_after_import(module: str, extra_path: str | None = None) -> list[str]:
    prelude = f"sys.path.insert(0, {extra_path!r}); " if extra_path else ""
    code = (
        f"import importlib, json, sys; {prelude}importlib.import_module({module!r}); "
        "print(json.dumps(sorted(sys.modules)))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    return json.loads(out.stdout)


@pytest.mark.parametrize("module", SHARED)
def test_importing_a_shared_module_loads_no_artifact_package(module):
    banned = [m for m in _loaded_after_import(module) if m.split(".")[0] in BANNED]
    assert banned == [], (
        f"importing {module} loads {banned}; artifacts 4 and 5 import this module, "
        "and artifact 5 refuses to load autoscale, so the shared tooling would stop "
        "being shareable"
    )


def test_the_sweep_handler_runs_without_artifact_one():
    banned = [
        m
        for m in _loaded_after_import("sweep_handler", str(REPO / "worker"))
        if m.split(".")[0] in BANNED
    ]
    assert banned == [], (
        f"worker/sweep_handler.py loads {banned}; the sweep would then depend on "
        "artifact 1's package being importable in the image"
    )


def test_no_harness_module_imports_autoscale():
    offenders = []
    for path in sorted((REPO / "harness").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            if any(n.split(".")[0] == "autoscale" for n in names):
                offenders.append(str(path.relative_to(REPO)))
    assert offenders == [], (
        f"{offenders} import autoscale; the harness serves artifacts that ban it. "
        "Emit plain values and let artifact 2 adapt them"
    )
