"""`placement_measure/` runs inside the worker image, so it may import only
`harness/` and the standard library: never `coldstart/` (which the image
carries, so a stray import would work there and hide the dependency), never
`autoscale/` or `placement/` (which it does not carry, so the import would be
an ImportError on a paid run). Each module is imported in a fresh interpreter,
because pytest shares `sys.modules` across the session and other tests import
`coldstart`."""

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {"coldstart", "autoscale", "placement"}
MODULES = sorted(f"placement_measure.{p.stem}" for p in (ROOT / "placement_measure").glob("*.py")
                 if p.stem != "__init__")


def test_the_package_exists():
    """Guards the guard: with no package the parametrised test below has no
    cases and passes by checking nothing."""
    assert (ROOT / "placement_measure" / "__init__.py").is_file()


def _loads(module: str) -> set[str]:
    code = (f"import importlib, sys; importlib.import_module({module!r}); "
            "print(sorted({m.split('.')[0] for m in sys.modules}))")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                         env={**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"},
                         check=False)
    assert out.returncode == 0, out.stderr
    return set(ast.literal_eval(out.stdout))


@pytest.mark.parametrize("module", MODULES)
def test_the_worker_package_loads_neither_coldstart_nor_autoscale(module):
    """The image carries it beside coldstart/, so a stray import would work in
    the image and hide the dependency; and autoscale/ is not in the image at
    all, so importing it would be an ImportError on a paid run."""
    loaded = _loads(module)
    assert not loaded & FORBIDDEN, sorted(loaded & FORBIDDEN)
