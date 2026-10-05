"""No function in `placement/` re-implements one the shared libraries define.

The amendment's rule is "never a third copy" of the statistics or the figure
guards. A rule like that rots unless something checks it, and "does not
re-implement" cannot be checked directly, so this checks the observable
symptom: a function name, public or private, that `placement/` defines and a
reference module also defines.

A name collision is not proof of duplication, and a renamed copy would slip
past. It catches the common case, where a helper is re-written under its
familiar name. A deliberate local helper that shares a name goes in `ALLOWED`
with the reason beside it, so the exception is visible in review.

Modules are parsed, not imported, so this needs no `sys.modules` isolation.
"""

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "placement"

# name -> why placement/ deliberately defines it too.
ALLOWED: dict[str, str] = {}


def _reference_files() -> list[Path]:
    files = [REPO / "harness" / "stats.py", REPO / "autoscale" / "stats.py"]
    guards = REPO / "harness" / "figure_guards.py"
    # Until the extraction's task 11 moves them, the figure guards live in
    # artifact 1's figures module.
    files.append(guards if guards.is_file() else REPO / "coldstart" / "analysis" / "figures.py")
    return files


def _defined(path: Path) -> set[str]:
    """Every function and method name in `path`, at any depth."""
    tree = ast.parse(path.read_text())
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def _shared(path: Path) -> set[str]:
    """Module-level function names only. A shared helper is something another
    module can import, which a function nested inside a chart function is not;
    counting those would flag names like `draw` that collide by accident."""
    tree = ast.parse(path.read_text())
    return {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def test_the_reference_modules_exist():
    """Guards the guard: a missing reference file would make every name look
    unique. `harness/stats.py` appears when the extraction's task 4 lands,
    which is this plan's prerequisite."""
    missing = [str(p.relative_to(REPO)) for p in _reference_files() if not p.is_file()]
    assert missing == [], f"reference modules missing: {missing}"


def test_the_parser_sees_known_definitions():
    assert "median" in _shared(REPO / "harness" / "stats.py")


def test_placement_defines_nothing_the_shared_libraries_define():
    reference: set[str] = set()
    for path in _reference_files():
        reference |= _shared(path)
    collisions = sorted(
        (name, str(path.relative_to(REPO)))
        for path in sorted(PACKAGE.rglob("*.py"))
        for name in _defined(path) & reference
        if name not in ALLOWED
    )
    assert collisions == [], (
        f"{collisions}: these names are already defined by a shared library. "
        "Import the shared function instead of writing a new one, or add the "
        "name to ALLOWED with the reason it has to be local."
    )
