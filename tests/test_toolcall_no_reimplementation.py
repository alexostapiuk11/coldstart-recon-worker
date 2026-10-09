"""`toolcall/` redefines no function the shared libraries define (amendment §7).

The same check as tests/test_placement_no_reimplementation.py: a module-level
function name in `harness.stats` or `harness.figure_guards` that `toolcall/`
also defines, at any depth. It catches the common case, a helper rewritten
under its familiar name. Parsed, not imported.
"""

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "toolcall"
REFERENCE = (REPO / "harness" / "stats.py", REPO / "harness" / "figure_guards.py")
ALLOWED: dict[str, str] = {}


def _defined(path: Path) -> set[str]:
    return {n.name for n in ast.walk(ast.parse(path.read_text()))
            if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)}


def _shared(path: Path) -> set[str]:
    return {n.name for n in ast.parse(path.read_text()).body
            if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)}


def test_the_reference_modules_exist_and_parse():
    assert all(p.is_file() for p in REFERENCE)
    assert "_percentile_interval" in _shared(REFERENCE[0])


def test_toolcall_defines_nothing_the_shared_libraries_define():
    reference = set().union(*(_shared(p) for p in REFERENCE))
    collisions = sorted(
        (name, str(p.relative_to(REPO)))
        for p in sorted(PACKAGE.rglob("*.py"))
        for name in _defined(p) & reference
        if name not in ALLOWED
    )
    assert collisions == []
