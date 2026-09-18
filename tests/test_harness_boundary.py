"""The two structural invariants the split exists to create.

1. harness/ never imports coldstart/. The whole point is that artifact 2 can
   depend on the harness without dragging in artifact 1's cold-start vocabulary;
   one convenience import in the wrong direction silently ends that.

2. Every first-party package the worker modules need is COPYed into the image.
   worker/handler.py imports harness.recorder at runtime on a paid GPU run --
   a missing COPY is an ImportError in the most expensive possible place, and
   nothing in the local loop would reveal it.

Both parse imports rather than grepping, for the reason
tests/test_autoscale_boundary.py gives: a substring check cannot tell
`import coldstart` from a module whose NAME merely contains the word, and a
guard that reports violations which are not one gets disabled.
"""

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FIRST_PARTY = {"coldstart", "harness", "worker", "recon"}


def _imported_top_level(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_the_harness_package_exists():
    """Guards the guard. `rglob` over a missing directory yields nothing, so
    the import-direction test below would pass vacuously on a repo where
    `harness/` was never created or was deleted -- reporting a clean boundary
    for an arrangement that does not exist."""
    assert (REPO / "harness" / "__init__.py").is_file(), (
        "harness/__init__.py is missing, so the import-direction test below "
        "has nothing to scan and passes without checking anything"
    )


def test_harness_never_imports_coldstart():
    offenders = []
    for path in sorted((REPO / "harness").rglob("*.py")):
        if "coldstart" in _imported_top_level(path):
            offenders.append(str(path.relative_to(REPO)))
    assert offenders == [], (
        f"harness modules import coldstart: {offenders}. The harness must not "
        "depend on artifact 1 -- move the artifact-1-specific part into "
        "coldstart/ and pass it in as a parameter instead."
    )


def test_dockerfile_copies_every_first_party_package_the_image_imports():
    dockerfile = (REPO / "worker" / "Dockerfile").read_text()
    copied = set(re.findall(r"^COPY\s+(\w+)\s+/opt/", dockerfile, re.MULTILINE))

    needed: set[str] = set()
    for pkg in ("worker", *sorted(copied)):
        for path in sorted((REPO / pkg).rglob("*.py")):
            needed |= _imported_top_level(path) & FIRST_PARTY
    needed.discard("worker")  # copied file-by-file, not as a package

    missing = needed - copied
    assert missing == set(), (
        f"worker/Dockerfile does not COPY {sorted(missing)}, but code in the "
        "image imports it. This fails at runtime on a paid GPU run."
    )


def test_the_ci_image_build_triggers_on_every_copied_package():
    """A package vendored into the image but absent from the workflow's `paths`
    filter means a change to it does not rebuild the image, so the GPU run uses
    a stale one. Silent, and expensive in the same place as a missing COPY."""
    workflow = (REPO / ".github" / "workflows" / "build-worker.yml").read_text()
    dockerfile = (REPO / "worker" / "Dockerfile").read_text()
    copied = set(re.findall(r"^COPY\s+(\w+)\s+/opt/", dockerfile, re.MULTILINE))

    missing = [pkg for pkg in sorted(copied) if f'"{pkg}/**"' not in workflow]
    assert missing == [], (
        f"{missing} are COPYed into the worker image but absent from "
        "build-worker.yml's paths filter, so changing them does not rebuild "
        "the image and a GPU run would use a stale one"
    )
