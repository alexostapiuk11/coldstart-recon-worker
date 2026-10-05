"""`placement/` must never load `coldstart`, directly or transitively.

Artifact 4 depends on artifact 1 for measured numbers only, and only figure 4
needs them. Keeping every other module coldstart-free means the simulator runs
without artifact 1's store on disk, and the pending harness extraction never
has to touch this package.

A direct-import check is not enough here, which is why this test differs from
tests/test_autoscale_boundary.py. `autoscale.sim` imports
`autoscale.coldstart_ecdf`, which imports `coldstart` when it loads, so a
module that imports only `autoscale.sim` passes a direct check while loading
artifact 1 anyway. This test imports each module and inspects `sys.modules`.

Each import runs in a fresh subprocess. pytest shares `sys.modules` across the
whole session, and other test files import `coldstart`, so an in-process check
would pass or fail depending on which tests ran first.
"""

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "placement"

# Module file names allowed to load `coldstart`. Empty until the measurement
# plan adds figure 4's adapter, which reads artifact 1's published stage
# medians. When it lands, add its file name here and nothing else.
ADAPTERS: frozenset[str] = frozenset()

_PROBE = (
    "import importlib, sys; importlib.import_module({name!r}); "
    "print(any(m == 'coldstart' or m.startswith('coldstart.') for m in sys.modules))"
)


def _loads_coldstart(module: str) -> bool:
    result = subprocess.run(
        [sys.executable, "-c", _PROBE.format(name=module)],
        cwd=REPO,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(REPO), "PYTHONDONTWRITEBYTECODE": "1"},
        check=False,
    )
    assert result.returncode == 0, f"importing {module} failed:\n{result.stderr}"
    return result.stdout.strip() == "True"


def _module_name(path: Path) -> str:
    parts = path.relative_to(REPO).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def test_the_package_exists():
    """Guards the guard: `rglob` over a missing directory yields nothing, so
    the test below would pass vacuously if `placement/` were never created."""
    assert (PACKAGE / "__init__.py").is_file()


def test_no_module_loads_coldstart_even_transitively():
    offenders = [
        _module_name(path)
        for path in sorted(PACKAGE.rglob("*.py"))
        if path.name not in ADAPTERS and _loads_coldstart(_module_name(path))
    ]
    assert offenders == [], (
        f"{offenders} load `coldstart` when imported. Only figure 4's adapter "
        "may. Look for an import of autoscale.sim or autoscale.coldstart_ecdf, "
        "both of which load artifact 1 transitively, and take the measured "
        "numbers as parameters instead."
    )


def test_the_probe_sees_a_transitive_import():
    """Guards the guard in the other direction. `autoscale.sim` never names
    `coldstart` but loads it through `autoscale.coldstart_ecdf`. If the probe
    reported False here, the check above would be blind to exactly the case it
    exists for."""
    assert _loads_coldstart("autoscale.sim")
    assert not _loads_coldstart("autoscale.events")
