"""`multilora/` imports `harness/` and never `coldstart/` or `autoscale/`
(amendment §5). Artifact 5 needs no code and no data from artifacts 1 or 2;
one convenience import would make it depend on a package whose published
results are frozen at a tag. Parses imports, as tests/test_autoscale_boundary.py
does, so a module whose name merely contains a banned word is not flagged."""

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BANNED = {"coldstart", "autoscale"}


def _top_level_imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_the_package_exists():
    """Guards the guard: rglob over a missing directory yields nothing."""
    assert (REPO / "multilora" / "__init__.py").is_file()


def test_multilora_never_imports_artifact_one_or_two():
    offenders = {
        str(p.relative_to(REPO)): sorted(_top_level_imports(p) & BANNED)
        for p in sorted((REPO / "multilora").rglob("*.py"))
        if _top_level_imports(p) & BANNED
    }
    assert offenders == {}
