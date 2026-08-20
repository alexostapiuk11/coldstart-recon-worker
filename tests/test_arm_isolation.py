"""Codebase-wide invariant: cache configuration is the only thing that differs between
arms — spec 6.3: "Cache configuration is a single interface with three implementations,
and it is the only thing that differs between arms... If arm behavior diverges anywhere
else in the code the experiment is compromised."

This is a testable, structural version of that claim: no source file outside the places
that legitimately need to know which arm is running — the interface itself, the
scheduler that assigns arms to runs, and the analysis layer that groups results by arm —
may branch on an arm value. That is precisely the shape of the regression this guards
against: someone later adding `if arm == "C":` inside the probe or the handler, which is
how this kind of single-variable experiment quietly stops being one.
"""

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Directories that contain runtime code and are worth scanning. Anything else (docs,
# fixtures, build output, the tests themselves) is out of scope for this check.
SCAN_ROOTS = ["coldstart", "worker", "recon"]

# Files/prefixes allowed to branch on an arm value, because the job requires it:
# - cache_config.py *is* the interface; the branch lives there by design.
# - scheduler.py assigns arms to runs (spec 5, sample plan).
# - analysis/ groups and compares results by arm — that is what analysis is for.
ALLOWED_PREFIXES = (
    "coldstart/cache_config.py",
    "coldstart/scheduler.py",
    "coldstart/analysis/",
)


def _is_arm_identifier(node: ast.AST) -> bool:
    """True for `arm`, `self.arm`, `record.arm`, `job["arm"]` — the ways an arm value
    is plausibly named or reached in this codebase (see RunRecord.arm in schema.py)."""
    if isinstance(node, ast.Name):
        return node.id == "arm"
    if isinstance(node, ast.Attribute):
        return node.attr == "arm"
    if isinstance(node, ast.Subscript):
        sl = node.slice
        return isinstance(sl, ast.Constant) and sl.value == "arm"
    return False


def _is_literal_operand(node: ast.AST) -> bool:
    """A constant or a literal container of constants — the other side of `arm == "C"`
    or `arm in ("B", "C")`."""
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return all(isinstance(elt, ast.Constant) for elt in node.elts)
    return False


def _find_arm_branches(tree: ast.AST) -> list[int]:
    """Line numbers of any construct that branches on an arm value: a comparison
    (`==`, `!=`, `in`, `not in`, ...) between an arm identifier and a literal, or a
    `match` statement switching on one."""
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            operands = [node.left, *node.comparators]
            if any(_is_arm_identifier(o) for o in operands) and any(
                _is_literal_operand(o) for o in operands
            ):
                lines.append(node.lineno)
        elif isinstance(node, ast.Match) and _is_arm_identifier(node.subject):
            lines.append(node.lineno)
    return lines


def _scan_targets():
    for root in SCAN_ROOTS:
        base = REPO_ROOT / root
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if "__pycache__" in rel:
                continue
            if any(rel.startswith(prefix) for prefix in ALLOWED_PREFIXES):
                continue
            yield path, rel


def test_no_arm_conditional_logic_outside_the_allowed_files():
    violations = []
    for path, rel in _scan_targets():
        tree = ast.parse(path.read_text(), filename=rel)
        for lineno in _find_arm_branches(tree):
            violations.append(f"{rel}:{lineno}")
    assert violations == [], (
        "arm-conditional logic found outside cache_config.py/scheduler.py/analysis — "
        f"this breaks the single-variable claim (spec 6.3): {violations}"
    )


def test_the_scanner_actually_detects_the_regression_it_guards_against():
    """A scanner that never fires is not a test. Prove `_find_arm_branches` catches the
    exact shape of mutation this file exists to catch: `if arm == "C":` appearing inside
    a file the real scan does not exempt (e.g. the probe or the handler)."""
    tree = ast.parse(
        'def handler(job):\n'
        '    arm = job["arm"]\n'
        '    if arm == "C":\n'
        '        warm_up_compile_cache()\n'
    )
    assert _find_arm_branches(tree) == [3]


def test_the_scanner_also_catches_a_membership_check_and_a_match_statement():
    tree = ast.parse(
        'def f(arm):\n'
        '    if arm in ("B", "C"):\n'
        '        pass\n'
        '    match arm:\n'
        '        case "A":\n'
        '            pass\n'
    )
    assert sorted(_find_arm_branches(tree)) == [2, 4]


def test_the_scanner_does_not_flag_arm_used_only_as_data():
    """Passing an arm value along — e.g. `resolve(record.arm)` or `d["arm"] = self.arm`
    — is not conditional logic and must not be flagged; only branching on it is the
    violation this test exists to catch."""
    tree = ast.parse(
        'def f(record):\n'
        '    cfg = resolve(record.arm)\n'
        '    d = {"arm": record.arm}\n'
        '    return cfg, d\n'
    )
    assert _find_arm_branches(tree) == []
