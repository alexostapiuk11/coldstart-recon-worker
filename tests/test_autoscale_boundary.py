"""One file in `autoscale/` may import `coldstart`, and only one.

Artifact 2's simulator consumes exactly one thing from artifact 1: the measured
cold-start lag distribution. Confining that dependency to
`autoscale/coldstart_ecdf.py` buys two specific things, and both are easy to
lose by accident:

- The simulator stays testable without artifact 1's data on disk. Every other
  module takes plain numbers, so a future artifact can drive the same
  simulator from its own measurements.
- The pending harness extraction (docs/superpowers/plans/2026-09-03-harness-extraction.md)
  moves `coldstart.store`, `coldstart.analysis.stats` and
  `coldstart.analysis.pipeline` to a `harness/` package. With the dependency
  confined, that migration edits one file here instead of a dozen.

The invariant held through all thirteen tasks, but nothing was enforcing it --
it survived on the module docstring saying so, which is exactly the kind of
claim that rots. `sim.py` and `sweep.py` both import
`autoscale.coldstart_ecdf`, whose name contains "coldstart", so a grep-based
check would report a violation that is not one. This parses the imports.
"""

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "autoscale"
THE_ONE_FILE = "coldstart_ecdf.py"


def _imports_coldstart(path: Path) -> bool:
    """True when `path` imports the `coldstart` package itself.

    Distinguishes `from coldstart.store import ...` (a real dependency) from
    `from autoscale.coldstart_ecdf import ...` (a local sibling) by reading the
    top-level module name rather than substring-matching the text.
    """
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[0] == "coldstart" for alias in node.names):
                return True
        elif (
            isinstance(node, ast.ImportFrom)
            and node.level == 0
            and node.module
            and node.module.split(".")[0] == "coldstart"
        ):
            return True
    return False


def test_only_the_adapter_imports_artifact_one():
    offenders = sorted(
        path.name
        for path in PACKAGE.rglob("*.py")
        if path.name != THE_ONE_FILE and _imports_coldstart(path)
    )

    assert offenders == [], (
        f"{offenders} import `coldstart` directly. Artifact 2 depends on "
        f"artifact 1 through {THE_ONE_FILE} alone -- take the measured numbers "
        "as parameters instead, so the simulator stays runnable without "
        "artifact 1's data and the pending harness extraction stays a "
        "one-file change."
    )


def test_the_one_file_really_does_import_it():
    """Guards the guard. If the adapter stopped importing `coldstart` -- say it
    was refactored to read the JSONL directly -- the test above would pass
    while describing an arrangement that no longer exists."""
    assert _imports_coldstart(PACKAGE / THE_ONE_FILE), (
        f"autoscale/{THE_ONE_FILE} no longer imports `coldstart`, so the "
        "boundary this file describes is stale. Either restore the import or "
        "rewrite both tests to describe the new arrangement."
    )


def test_the_import_parser_is_not_fooled_by_the_sibling_module_name():
    """`autoscale.coldstart_ecdf` contains the string "coldstart", so a
    substring check would flag `sim.py` and `sweep.py` as violations. They are
    not. This pins that the parser reads the top-level package name."""
    sim = PACKAGE / "sim.py"
    assert "autoscale.coldstart_ecdf" in sim.read_text()
    assert not _imports_coldstart(sim)
