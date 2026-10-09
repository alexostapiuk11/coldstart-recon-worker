"""`toolcall/` loads `harness` and no other artifact's package, even
transitively (amendment §7).

Artifact 3 needs nothing from artifacts 1, 2, 4 or 5. A direct-import check is
not enough, for the reason tests/test_placement_boundary.py gives: a module can
load `coldstart` through an innocent-looking intermediate. So each module is
imported in a fresh interpreter and `sys.modules` is inspected. A fresh
subprocess per module, because pytest shares `sys.modules` across the session.
"""

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "toolcall"
BANNED = ("coldstart", "autoscale", "placement", "placement_measure", "multilora")

_PROBE = (
    "import importlib, sys; importlib.import_module({name!r}); "
    "print(sorted({{m.split('.')[0] for m in sys.modules}} & {banned!r}))"
)


def _banned_loaded(module: str) -> list[str]:
    result = subprocess.run(
        [sys.executable, "-c", _PROBE.format(name=module, banned=set(BANNED))],
        cwd=REPO,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(REPO), "PYTHONDONTWRITEBYTECODE": "1"},
        check=False,
    )
    assert result.returncode == 0, f"importing {module} failed:\n{result.stderr}"
    return eval(result.stdout.strip())  # a printed list of str, from our own probe


def _module_name(path: Path) -> str:
    parts = path.relative_to(REPO).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def test_the_package_exists():
    """Guards the guard: rglob over a missing directory yields nothing."""
    assert (PACKAGE / "__init__.py").is_file()


def test_no_module_loads_another_artifact_even_transitively():
    offenders = {
        _module_name(p): loaded
        for p in sorted(PACKAGE.rglob("*.py"))
        if (loaded := _banned_loaded(_module_name(p)))
    }
    assert offenders == {}


def test_the_probe_sees_a_transitive_import():
    """Guards the guard in the other direction: `autoscale.sim` never names
    `coldstart` but loads it. If the probe missed that, the check above would
    be blind to exactly the case it exists for."""
    assert "coldstart" in _banned_loaded("autoscale.sim")


def test_the_harness_never_loads_toolcall():
    offenders = [
        _module_name(p)
        for p in sorted((REPO / "harness").rglob("*.py"))
        if "toolcall" in (Path(p).read_text())
    ]
    assert offenders == []
