# Artifact 3 Plan 1 — Offline Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Executed 2026-10-09 to 2026-10-10, with approved deviations.** Review changed much of this plan's code. The code on `main` and `2026-10-10-artifact-3-plan-1-deviations.md` are authoritative; this plan's code blocks are kept as history.

**Goal:** Build all of artifact 3's code and its scenario suite with no API spend: the `toolcall/` package from the tool and scenario formats through the renderer, the deterministic grader, the mock tool layer and recovery loop, the provider clients, the campaign wiring and spend guard, to the statistics, analysis and four figures, all tested against a scripted stand-in for a model.

**Architecture:** `toolcall/` is artifact 3's package. It imports `harness/` and nothing from another artifact's package, transitively, and a test enforces it. A scenario and its tools are plain JSON; `formulation.render` turns one scenario into eight renderings that differ only in the manipulated factor. Each call is one scheduled run of the harness campaign loop, stored as a `CallRecord` with its exact request body, raw response and grade. Analysis is pure functions from records to one JSON-shaped dict, which the figures and the post's numbers block read. A stub model with planted effects stands where a provider would, so the tests check that the analysis recovers what was put in.

**Tech Stack:** Python 3.13, pytest, ruff, matplotlib, Pillow (already used by artifact 5's figure script), and the harness. No new dependency in this plan: the provider SDKs are imported only inside `Client.post`, and plan 2 installs them.

**Spec:** [the amendment](../specs/2026-10-08-tool-calling-reliability-amendment.md), which governs, over [the August design](../specs/2026-08-17-tool-calling-reliability-harness-design.md). "Amendment §4b" points at the amendment, "August §4" at the design. The amendment's §14 lists what writing this plan changed.

**Plan 1 of 3.** [Plan 2](2026-10-08-artifact-3-plan-2-pilot-and-preregistration.md) installs the SDKs, runs a one-call smoke check per model, commits pre-registration step 1, runs the pilot and commits step 2. [Plan 3](2026-10-08-artifact-3-plan-3-campaign-and-publication.md) runs the campaign and publishes. **Nothing in this plan spends money.** Task 18 downloads public BFCL files; that is a download the author approves, not a spend.

**How this plan was checked:** every code block below was first run on 2026-10-08 in a clone of `main` at `de0cbc8`, in the order the tasks give. All 205 tests the plan adds before Task 19 passed, alongside the existing 2,846, and `ruff check .` printed `All checks passed!` with the repository's own configuration (ruff 0.16.3). The full offline path ran end to end on the stub: a 66-scenario synthetic suite through all eight cells, recovery, the slice and the exploratory phase; the analysis recovered every planted effect; the analysis and the eight figure files were each generated twice and compared byte-identical. The four figures were rendered and looked at, at desktop width and at 375 px; that check found two clipped titles, which are fixed in the code below. Task 19's suite-size gate was run against the three worked examples and failed as it should; the authored suite itself is the author's work and is not in this document. Finally, every file was extracted from this document into a fresh clone of `de0cbc8`: all 65 came out byte-identical to the tested sources, and there the full suite passed, 3,051 tests (the 2,846 existing and the 205 this plan adds before Task 19), with `ruff check .` clean.

---

## Prerequisites — do not start before these are true

- [ ] **The harness modules this plan imports exist with these names.** Run:

```bash
.venv/bin/python -c "
import inspect
from harness.store import JsonlStore
from harness.scheduler import build_schedule
from harness.campaign import run_campaign
from harness.submit import SubmitOutcome
from harness.stats import MIN_BOOTSTRAP_SAMPLES, _percentile_interval, _check_iterations_and_alpha
from harness.figure_guards import phone_pt, validate_rows, PHONE_WIDTH_PX, MIN_PHONE_TEXT_PX
assert list(inspect.signature(build_schedule).parameters) == ['conditions', 'blocks', 'seed']
assert MIN_BOOTSTRAP_SAMPLES == 20
print('harness present')
"
```

Expected: `harness present`.

- [ ] **The suite and lint pass on `main`.** Run `.venv/bin/python -m pytest -q` and `.venv/bin/ruff check .`. Expected: every test passes (2,846 on `de0cbc8`) and `All checks passed!`.
- [ ] **The amendment is approved** (its status line says so) and §14 item 1 has the author's sign-off, or Task 19's recovery targets are adjusted to what was signed.
- [ ] **`git status --porcelain` is empty**, and work happens on a branch: `git checkout -b artifact-3-plan-1`.

---

## File structure

```
toolcall/
  __init__.py        SCHEMA_VERSION, NORMALIZER_VERSION; the package's one rule
  tools.py           ToolSpec, ParamSpec, the closed type subset, canonical schemas, the library
  normalize.py       normalizer v1: rules R1-R8, structural conformance, value matching
  scenarios.py       Scenario, Recovery; loading and validating against the library
  stub_suite.py      a small synthetic suite for dry runs and tests. NOT DATA
  formulation.py     the eight cells; rendering one scenario into one cell
  providers.py       ModelSettings; OpenAI and Anthropic request builders and parsers; clients
  responses.py       provider responses built in each documented shape, for dry runs
  grader.py          the ordered, deterministic grader
  prices.py          pinned per-token prices with source and read date
  guard.py           the spend guard: estimate check, per-call bound, metering
  mock_tools.py      the mock tool layer: four error kinds, two message formats
  recovery.py        one recovery conversation and its measures
  records.py         CallRecord, RecoveryRecord
  campaign.py        single-turn and recovery runs through harness.campaign
  stub.py            a stand-in model with planted effects. NOT DATA
  effects.py         Wilson, rates, 2^3 contrasts, the cluster bootstrap, Holm
  costs.py           cost per successful call; break-even
  budget.py          ICC, effective sample size, the N rule, budget tables
  prereg.py          the pre-registration record
  selection.py       the pilot's selection table, rho, and step 2's proposal
  hypotheses.py      H1-H5 and their verdicts
  analysis.py        everything the post reports, as one dict
  figures.py         the four figures
  runner.py          every phase of the paid path, stub or real
  numbers.py         the post's generated numbers block
  diagnose.py        the bring-your-own-tools entry point
  confidentiality.py the vocabulary scan and sign-off check
  bfcl.py            BFCL entries to draft scenarios
  README.md          for adopters
  data/
    tools/*.json, scenarios/*.json, confidentiality_signoff.json
scripts/
  a3_stub_demo.py, a3_render_figures.py, a3_diagnose.py, a3_import_bfcl.py
tests/
  a3_examples.py                 helpers: the synthetic suite, example_prereg()
  fixtures/a3/*.json             provider responses, hand-authored from documented shapes
  test_toolcall_*.py             one file per task
```

Plan 2 adds `toolcall/prereg_values.py`, `scripts/a3_run.py`, `a3_smoke.py`, `a3_select.py` and `docs/experiment-a3.md`. Plan 3 adds `toolcall/spend.py` and the publication scripts and tests.

---
## Task 1: The package and its boundaries

`toolcall/` must load `harness` and nothing from another artifact, even transitively (amendment §7), and must not redefine what the shared libraries define. Both guards come first, so every later module is checked from the moment it exists.

**Files:**
- Create: `toolcall/__init__.py`
- Test: `tests/test_toolcall_boundary.py`, `tests/test_toolcall_no_reimplementation.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_toolcall_boundary.py`:

```python
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
```

Create `tests/test_toolcall_no_reimplementation.py`:

```python
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_toolcall_boundary.py -v`
Expected: FAIL on `test_the_package_exists`: `toolcall/__init__.py` does not exist.

- [ ] **Step 3: Create the package**

Create `toolcall/__init__.py`:

```python
"""Artifact 3: how tool presentation changes tool-calling failure modes.

Imports `harness/` and nothing from another artifact's package;
tests/test_toolcall_boundary.py enforces it, transitively. Design:
docs/superpowers/specs/2026-10-08-tool-calling-reliability-amendment.md, which
governs docs/superpowers/specs/2026-08-17-tool-calling-reliability-harness-design.md.

Two version numbers travel with every graded record. Changing what either one
covers is a breaking change (August §4): numbers graded under different
versions are not comparable.
"""

SCHEMA_VERSION = 1  # the scenario and tool-library file formats
NORMALIZER_VERSION = 1  # toolcall/normalize.py's rules
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_toolcall_boundary.py tests/test_toolcall_no_reimplementation.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add toolcall/__init__.py tests/test_toolcall_boundary.py tests/test_toolcall_no_reimplementation.py
git commit -m "feat: the toolcall package, and guards that it loads no other artifact and copies no shared helper"
```

---

## Task 2: The data model: tools, normalization, scenarios

Three modules that only make sense together, and the synthetic suite the tests use.

- `tools.py`: a tool is plain data with a terse and a rich description and typed parameters from a closed subset (amendment §14 item 3). `canonical_schema` is the strict form every call is graded against (§4b).
- `normalize.py`: normalizer v1. The rules are numbered and published because they silently set every number (August §4). The split that matters: `conformance` decides MALFORMED, `call_matches` decides WRONG_PARAMS.
- `scenarios.py`: a scenario is validated against the library at load, so an ungradable one fails before any money is spent. Pattern value specifications carry an example (§14 item 6).
- `stub_suite.py`: a travel library, three template scenarios and `synthetic_suite`, which clones them into as many distinct scenarios as a bootstrap needs. NOT DATA.

**Files:**
- Create: `toolcall/tools.py`
- Create: `toolcall/normalize.py`
- Create: `toolcall/scenarios.py`
- Create: `toolcall/stub_suite.py`
- Test: `tests/a3_examples.py`
- Test: `tests/test_toolcall_tools.py`
- Test: `tests/test_toolcall_normalize.py`
- Test: `tests/test_toolcall_scenarios.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/a3_examples.py`:

```python
"""Artifact 3's test helpers: the synthetic suite, re-exported. NOT DATA."""

from toolcall.scenarios import scenario_from_dict
from toolcall.stub_suite import (  # noqa: F401
    FLIGHT,
    MISC,
    RECOVERY,
    SMALLTALK,
    TRAVEL,
    library,
    scenarios,
    synthetic_suite,
    write_suite,
)


def scenario(d=FLIGHT):
    return scenario_from_dict(d, library())


def example_prereg(**overrides):
    """Values for tests only. The real ones live in toolcall/prereg_values.py."""
    from toolcall.prereg import Preregistration
    from toolcall.providers import ModelSettings

    values = {
        "primary": ModelSettings("openai", "gpt-5.4-mini-2026-03-17", 0.0,
                                 reasoning_effort="none"),
        "slice_models": (
            ModelSettings("openai", "gpt-5.4-nano-2026-03-17", 0.0, reasoning_effort="none"),
            ModelSettings("anthropic", "claude-sonnet-5-5", None, thinking="between_tools"),
        ),
        "baseline_cell": "low-terse-loose",
        "band": (0.10, 0.90),
        "pilot_reps": 10,
        "pilot_cost_scenarios": 10,
        "pilot_cost_reps": 5,
        "delta2": 0.02,
        "identical_retry_floor": 0.05,
        "n_floor": 5,
        "n_cap": 20,
        "s_floor": 24,
        "alpha": 0.05,
        "iterations": 300,
        "bootstrap_seed": 7,
        "schedule_seed": 11,
        "retry_cap": 3,
        "turn_budget": 3,
        "normalizer_version": 1,
    }
    values.update(overrides)
    return Preregistration(**values)
```

Create `tests/test_toolcall_tools.py`:

```python
import json

import pytest

from tests.a3_examples import MISC, TRAVEL, library
from toolcall.tools import ParamSpec, ToolSpec, canonical_schema, load_library, tool_from_dict


def _p(**kw):
    base = {"name": "x", "type": "string", "required": True, "terse": "X.", "rich": "The x."}
    return ParamSpec(**{**base, **kw})


def test_the_canonical_schema_is_the_strict_form_without_descriptions():
    schema = canonical_schema(library().get("search_flights"))
    assert schema["required"] == ["origin", "destination", "date"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["cabin"] == {
        "type": "string", "enum": ["economy", "premium", "business"]}
    assert "description" not in schema["properties"]["origin"]


@pytest.mark.parametrize("kw, match", [
    ({"type": "object"}, "closed subset"),
    ({"type": "array"}, "items"),
    ({"type": "integer", "enum": ("a",)}, "strings only"),
    ({"enum": ("a",), "pattern": "^a$"}, "not both"),
    ({"rich": " "}, "both descriptions"),
    ({"name": "Bad-Name"}, "snake_case"),
])
def test_parameters_outside_the_closed_subset_are_refused(kw, match):
    with pytest.raises(ValueError, match=match):
        _p(**kw)


def test_a_tool_needs_a_required_parameter_and_unique_names():
    with pytest.raises(ValueError, match="required parameter"):
        ToolSpec("t", "d", "T.", "The t.", (_p(required=False),))
    with pytest.raises(ValueError, match="duplicate"):
        ToolSpec("t", "d", "T.", "The t.", (_p(), _p()))


def test_primary_param_is_the_first_required_one():
    assert library().get("search_flights").primary_param.name == "origin"


def test_load_library_reads_every_domain_and_refuses_duplicates(tmp_path):
    for data in (TRAVEL, MISC):
        (tmp_path / f"{data['domain']}.json").write_text(json.dumps(data))
    lib = load_library(tmp_path)
    assert len(lib.tools) == len(TRAVEL["tools"]) + len(MISC["tools"])
    assert next(t.name for t in lib.domain("travel")) == "airport_info"
    (tmp_path / "dupe.json").write_text(json.dumps({"domain": "x", "tools": [TRAVEL["tools"][0]]}))
    with pytest.raises(ValueError, match="defined twice"):
        load_library(tmp_path)


def test_a_draft_tool_is_refused():
    with pytest.raises(ValueError, match="draft"):
        tool_from_dict({**TRAVEL["tools"][0], "draft": True}, "travel")
```

Create `tests/test_toolcall_normalize.py`:

```python
"""Normalizer v1, rule by rule. Each test names the rule it pins."""

import pytest

from tests.a3_examples import library
from toolcall.normalize import (
    RULES,
    call_key,
    call_matches,
    conformance,
    value_matches,
    value_violations,
)

FLIGHTS = library().get("search_flights")
OK = {"origin": "JFK", "destination": "SFO", "date": "2026-11-03"}
ACCEPT = {"tool": "search_flights", "args": dict(OK),
          "may_include": {"passengers": 2, "cabin": "economy"}}


def test_the_rules_are_numbered_and_published():
    assert [r[0] for r in RULES] == [f"R{i}" for i in range(1, 9)]


def test_r1_enum_values_compare_case_insensitively():
    assert call_matches({**OK, "cabin": "Economy"}, ACCEPT, FLIGHTS)
    assert value_violations({**OK, "cabin": "ECONOMY"}, FLIGHTS) == []


def test_r2_whitespace_collapses_and_free_text_is_case_sensitive():
    assert call_matches({**OK, "origin": "  JFK "}, ACCEPT, FLIGHTS)
    assert not call_matches({**OK, "origin": "jfk"}, ACCEPT, FLIGHTS)


def test_r3_numbers_compare_numerically():
    assert call_matches({**OK, "passengers": 2.0}, ACCEPT, FLIGHTS)
    assert conformance({**OK, "passengers": 2.0}, FLIGHTS) is None
    assert conformance({**OK, "passengers": 2.5}, FLIGHTS) is not None


def test_r4_a_number_sent_as_a_string_is_structural():
    assert "type str" in conformance({**OK, "passengers": "2"}, FLIGHTS)


def test_r4_a_boolean_is_never_a_number():
    assert conformance({**OK, "passengers": True}, FLIGHTS) is not None


def test_r5_null_is_omission():
    assert call_matches({**OK, "cabin": None}, ACCEPT, FLIGHTS)
    assert "missing required ['date']" in conformance({**OK, "date": None}, FLIGHTS)


def test_r6_key_order_is_irrelevant():
    assert call_key("t", {"a": 1, "b": 2}, None) == call_key("t", {"b": 2, "a": 1}, None)


def test_r7_an_unknown_key_is_a_wrong_parameter_not_a_structural_failure():
    args = {**OK, "seat": "aisle"}
    assert conformance(args, FLIGHTS) is None
    assert not call_matches(args, ACCEPT, FLIGHTS)
    assert value_violations(args, FLIGHTS) == ["unknown key 'seat'"]


def test_r8_arrays_compare_in_order():
    from toolcall.tools import ParamSpec

    p = ParamSpec("tags", "array", True, "T.", "Tags.", items="string")
    assert value_matches(["a", "b"], ["a", "b"], p)
    assert not value_matches(["a", "b"], ["b", "a"], p)


def test_value_specifications():
    p = FLIGHTS.param("origin")
    assert value_matches({"one_of": ["JFK", "LGA"]}, "LGA", p)
    spec = {"pattern": "j.k", "example": "JFK"}
    assert value_matches(spec, "JFK", p)
    assert not value_matches(spec, "JFKX", p)


def test_conformance_refuses_a_non_object():
    assert "not an object" in conformance(["JFK"], FLIGHTS)


def test_call_key_treats_enum_case_and_whitespace_as_the_same_call():
    a = call_key("search_flights", {**OK, "cabin": "Economy "}, FLIGHTS)
    b = call_key("search_flights", {**OK, "cabin": "economy"}, FLIGHTS)
    assert a == b


@pytest.mark.parametrize("args", [{**OK, "cabin": "first"}, {**OK, "origin": "JFKX"}])
def test_value_violations_name_the_constraint(args):
    assert value_violations(args, FLIGHTS)
```

Create `tests/test_toolcall_scenarios.py`:

```python
import copy

import pytest

from tests.a3_examples import FLIGHT, RECOVERY, SMALLTALK, library, write_suite
from toolcall.scenarios import load_scenarios, scenario_from_dict


def _with(**changes):
    d = copy.deepcopy(FLIGHT)
    d.update(changes)
    return d


def test_the_three_examples_load():
    lib = library()
    for d in (FLIGHT, SMALLTALK, RECOVERY):
        s = scenario_from_dict(d, lib)
        assert s.id == d["id"]
    assert scenario_from_dict(RECOVERY, lib).recovery.error_kind == "invalid_parameter"


@pytest.mark.parametrize("changes, match", [
    ({"tools": ["search_flights"]}, "2-4"),
    ({"confusables": ["flight_status"]}, "4-6"),
    ({"confusables": ["search_flights", "flight_status", "flight_prices", "search_trains"]},
     "both in the low set"),
    ({"target_failure_mode": "CORRECT"}, "target_failure_mode"),
    ({"expectation": {}}, "exactly one"),
    ({"draft": True}, "draft"),
    ({"tools": ["search_flights", "no_such_tool"]}, "no tool named"),
])
def test_invalid_scenarios_are_refused(changes, match):
    with pytest.raises((ValueError, KeyError), match=match):
        scenario_from_dict(_with(**changes), library())


def test_an_acceptable_call_must_itself_be_well_formed():
    bad = _with(expectation={"acceptable_calls": [
        {"tool": "search_flights", "args": {"origin": "JFK", "destination": "SFO",
                                            "date": "2026-11-03", "passengers": "two"}}]})
    with pytest.raises(ValueError, match="canonical type"):
        scenario_from_dict(bad, library())


@pytest.mark.parametrize("spec, match", [
    ({"pattern": "jfk"}, "exactly an `example`"),
    ({"pattern": "jfk", "example": "LGA"}, "fails its pattern"),
    ({"any": ["JFK"]}, "unknown value specification"),
])
def test_value_specifications_are_checked_at_load(spec, match):
    bad = _with(expectation={"acceptable_calls": [{"tool": "search_flights", "args": {
        "origin": spec, "destination": "SFO", "date": "2026-11-03"}}]})
    with pytest.raises(ValueError, match=match):
        scenario_from_dict(bad, library())


def test_an_acceptable_call_must_give_every_required_argument():
    bad = _with(expectation={"acceptable_calls": [
        {"tool": "search_flights", "args": {"origin": "JFK"}}]})
    with pytest.raises(ValueError, match="omits required"):
        scenario_from_dict(bad, library())


def test_an_acceptable_call_must_use_the_low_set():
    bad = _with(expectation={"acceptable_calls": [
        {"tool": "flight_status", "args": {"flight_number": "UA1"}}]})
    with pytest.raises(ValueError, match="not in the low set"):
        scenario_from_dict(bad, library())


def test_a_no_call_scenario_targets_spurious():
    bad = copy.deepcopy(SMALLTALK)
    bad["target_failure_mode"] = "MISSING"
    with pytest.raises(ValueError, match="SPURIOUS"):
        scenario_from_dict(bad, library())


def test_bring_your_own_mode_relaxes_only_the_factorial_counts():
    d = _with(tools=["search_flights"], confusables=[])
    s = scenario_from_dict(d, library(), factorial=False)
    assert s.tools == ("search_flights",)


def test_load_scenarios_requires_the_id_to_match_the_file_name(tmp_path):
    tools_dir, sc_dir = write_suite(tmp_path)
    from toolcall.tools import load_library

    lib = load_library(tools_dir)
    assert len(load_scenarios(sc_dir, lib)) == 3
    (sc_dir / "renamed.json").write_text((sc_dir / f"{FLIGHT['id']}.json").read_text())
    with pytest.raises(ValueError, match="must equal the file name"):
        load_scenarios(sc_dir, lib)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/a3_examples.py tests/test_toolcall_tools.py tests/test_toolcall_normalize.py tests/test_toolcall_scenarios.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'toolcall.stub_suite'`.

- [ ] **Step 3: Write the implementation**

Create `toolcall/tools.py`:

```python
"""Abstract tools: what a tool is, independent of how it is presented.

A tool here is plain data: a name, a terse and a rich description, and typed
parameters. The formulation layer (toolcall/formulation.py) decides how it is
shown to a model; the grader (toolcall/grader.py) checks every call against the
tool's one canonical schema, its strict form, whatever the model was shown
(amendment §4b).

Parameter types are a closed subset -- string, integer, number, boolean, and an
array of one of those -- with an optional `enum` or `pattern` on strings. The
subset is closed on purpose: it is what every provider's strict mode accepts
(amendment §4a), so a canonical schema can never depend on a feature one
provider rejects, and the grader's conformance check is small enough to read.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

PRIMITIVES = ("string", "integer", "number", "boolean")
_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


@dataclass(frozen=True)
class ParamSpec:
    name: str
    type: str  # one of PRIMITIVES, or "array"
    required: bool
    terse: str
    rich: str
    items: str | None = None  # element type when type == "array"
    enum: tuple[str, ...] = ()
    pattern: str | None = None

    def __post_init__(self) -> None:
        if not _NAME.match(self.name):
            raise ValueError(f"parameter name {self.name!r} is not snake_case")
        if self.type not in PRIMITIVES + ("array",):
            raise ValueError(f"{self.name}: type {self.type!r} is outside the closed subset")
        if (self.type == "array") != (self.items is not None):
            raise ValueError(f"{self.name}: `items` is required for arrays and only for arrays")
        if self.items is not None and self.items not in PRIMITIVES:
            raise ValueError(f"{self.name}: array items must be a primitive, got {self.items!r}")
        if (self.enum or self.pattern) and self.type != "string":
            raise ValueError(f"{self.name}: enum and pattern apply to strings only")
        if self.enum and self.pattern:
            raise ValueError(f"{self.name}: give an enum or a pattern, not both")
        if self.pattern is not None:
            re.compile(self.pattern)
        if not self.terse.strip() or not self.rich.strip():
            raise ValueError(f"{self.name}: both descriptions are required")


@dataclass(frozen=True)
class ToolSpec:
    name: str
    domain: str
    terse: str
    rich: str
    params: tuple[ParamSpec, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not _NAME.match(self.name):
            raise ValueError(f"tool name {self.name!r} is not snake_case")
        if not self.terse.strip() or not self.rich.strip():
            raise ValueError(f"{self.name}: both descriptions are required")
        names = [p.name for p in self.params]
        if len(names) != len(set(names)):
            raise ValueError(f"{self.name}: duplicate parameter names")
        if self.params and not any(p.required for p in self.params):
            raise ValueError(f"{self.name}: a tool with parameters needs one required parameter")

    def param(self, name: str) -> ParamSpec | None:
        return next((p for p in self.params if p.name == name), None)

    @property
    def primary_param(self) -> ParamSpec | None:
        """The tool's single most obvious argument: its first required one.
        The loose rendering keeps only this one in `required` (amendment §4a)."""
        return next((p for p in self.params if p.required), None)


def canonical_schema(tool: ToolSpec) -> dict:
    """The strict form, without descriptions. Every call in every cell is
    graded against this (amendment §4b)."""
    props = {}
    for p in tool.params:
        prop: dict = {"type": p.type}
        if p.items:
            prop["items"] = {"type": p.items}
        if p.enum:
            prop["enum"] = list(p.enum)
        if p.pattern:
            prop["pattern"] = p.pattern
        props[p.name] = prop
    return {
        "type": "object",
        "properties": props,
        "required": [p.name for p in tool.params if p.required],
        "additionalProperties": False,
    }


def _param_from_dict(d: dict) -> ParamSpec:
    return ParamSpec(
        name=d["name"],
        type=d["type"],
        required=d["required"],
        terse=d["terse"],
        rich=d["rich"],
        items=d.get("items"),
        enum=tuple(d.get("enum", ())),
        pattern=d.get("pattern"),
    )


def tool_from_dict(d: dict, domain: str) -> ToolSpec:
    if d.get("draft"):
        raise ValueError(f"{d['name']}: still a draft (scripts/a3_import_bfcl.py output)")
    return ToolSpec(
        name=d["name"],
        domain=domain,
        terse=d["terse"],
        rich=d["rich"],
        params=tuple(_param_from_dict(p) for p in d.get("params", ())),
    )


@dataclass(frozen=True)
class Library:
    """Every tool, from every domain file, by name. Tool names are unique
    across domains, so a scenario can borrow an unrelated tool by name."""

    tools: dict[str, ToolSpec]

    def get(self, name: str) -> ToolSpec:
        if name not in self.tools:
            raise KeyError(f"no tool named {name!r} in the library")
        return self.tools[name]

    def domain(self, domain: str) -> list[ToolSpec]:
        return sorted((t for t in self.tools.values() if t.domain == domain), key=lambda t: t.name)


def load_library(directory) -> Library:
    tools: dict[str, ToolSpec] = {}
    for path in sorted(Path(directory).glob("*.json")):
        data = json.loads(path.read_text())
        for d in data["tools"]:
            tool = tool_from_dict(d, data["domain"])
            if tool.name in tools:
                raise ValueError(f"{path.name}: tool {tool.name!r} is defined twice")
            tools[tool.name] = tool
    if not tools:
        raise ValueError(f"no tools under {directory}")
    return Library(tools)
```

Create `toolcall/normalize.py`:

```python
"""The normalization rules, version 1.

These rules silently set every number the artifact publishes: a lenient
normalizer inflates the correct rate and a strict one deflates it, and neither
shows in the output (August §4). So they are written down here, in order,
published in the post, and versioned by `toolcall.NORMALIZER_VERSION`. Changing
one is a breaking change: bump the version, and never compare numbers graded
under two versions.

The split that matters most (amendment §4b): a call that is structurally
wrong is MALFORMED; a call that is well-formed but carries a wrong value is
WRONG_PARAMS. `conformance` decides the first, `call_matches` the second.
"""

import json
import math
import re

from toolcall.tools import ParamSpec, ToolSpec

RULES = (
    ("R1", (
        "Enum values compare case-insensitively. Anthropic's strict mode does not "
        "guarantee enum capitalisation (amendment §4b), so no arm may be penalised for "
        "it."
    )),
    ("R2", (
        "Strings are trimmed and internal whitespace runs collapse to one space before "
        "any comparison. Free-text values compare case-sensitively; enum values and "
        "pattern specifications compare case-insensitively."
    )),
    ("R3", (
        "Numbers compare numerically within an absolute tolerance of 1e-9, so 3 equals "
        "3.0. An integer parameter accepts a float with no fractional part."
    )),
    ("R4", (
        'A number sent as a string is a type error, not a coercion: "3" for an integer '
        "parameter is MALFORMED."
    )),
    ("R5", (
        "An explicit null for an optional parameter is the same as omitting it. A null "
        "for a required parameter is a missing required parameter."
    )),
    ("R6", "Key order is irrelevant."),
    ("R7", (
        "A key the canonical schema does not define is a wrong parameter (WRONG_PARAMS), "
        "not a structural failure and not ignored as harmless."
    )),
    ("R8", "Arrays compare element by element, in order."),
)

TOLERANCE = 1e-9


def collapse(s: str) -> str:
    return " ".join(s.split())


def strip_nulls(args: dict, tool: ToolSpec) -> dict:
    """R5: drop explicit nulls on optional parameters. A null on a required
    parameter is dropped too, so it then reads as missing."""
    return {k: v for k, v in args.items() if v is not None}


def _type_ok(value, type_: str) -> bool:
    if type_ == "string":
        return isinstance(value, str)
    if type_ == "boolean":
        return isinstance(value, bool)
    if isinstance(value, bool):
        return False  # bool is an int subclass in Python, never a number here
    if type_ == "integer":
        return isinstance(value, int) or (isinstance(value, float) and value.is_integer())
    if type_ == "number":
        return isinstance(value, int | float) and math.isfinite(value)
    raise ValueError(f"unknown type {type_!r}")


def _param_type_ok(value, p: ParamSpec) -> bool:
    if p.type == "array":
        return isinstance(value, list) and all(_type_ok(v, p.items) for v in value)
    return _type_ok(value, p.type)


def conformance(args, tool: ToolSpec) -> str | None:
    """Why `args` is structurally invalid for `tool`'s canonical schema, or
    None if it is valid. Structural means: not an object, a required key
    missing (after R5), or a known key with a value of the wrong JSON type
    (R3, R4). Value-level problems are not structural (R7, and amendment §4b)."""
    if not isinstance(args, dict):
        return f"arguments are a {type(args).__name__}, not an object"
    present = strip_nulls(args, tool)
    missing = [p.name for p in tool.params if p.required and p.name not in present]
    if missing:
        return f"missing required {missing}"
    for key, value in present.items():
        p = tool.param(key)
        if p is not None and not _param_type_ok(value, p):
            return f"{key!r} has type {type(value).__name__}, schema says {p.type}"
    return None


def _scalar_equal(a, b, p_type: str, enum: bool) -> bool:
    if p_type == "string":
        if not (isinstance(a, str) and isinstance(b, str)):
            return False
        a, b = collapse(a), collapse(b)
        return a.casefold() == b.casefold() if enum else a == b
    if p_type == "boolean":
        return a is b
    return abs(float(a) - float(b)) <= TOLERANCE


def _literal_equal(spec, value, p: ParamSpec) -> bool:
    if p.type == "array":
        return (
            isinstance(value, list)
            and isinstance(spec, list)
            and len(value) == len(spec)
            and all(_scalar_equal(s, v, p.items, False) for s, v in zip(spec, value))
        )
    return _scalar_equal(spec, value, p.type, bool(p.enum))


def value_matches(spec, value, p: ParamSpec) -> bool:
    """A value specification is a literal, `{"one_of": [literal, ...]}`, or
    `{"pattern": regex, "example": literal}` (a full, case-insensitive match on
    a string after R2; the example is one value that matches, for the stub)."""
    if isinstance(spec, dict) and set(spec) == {"one_of"}:
        return any(_literal_equal(s, value, p) for s in spec["one_of"])
    if isinstance(spec, dict) and set(spec) == {"pattern", "example"}:
        return isinstance(value, str) and re.fullmatch(
            spec["pattern"], collapse(value), re.IGNORECASE
        ) is not None
    return _literal_equal(spec, value, p)


def call_matches(args: dict, acceptable: dict, tool: ToolSpec) -> bool:
    """Whether well-formed `args` match one acceptable call: every key in
    `acceptable["args"]` present and matching, any other key present only if
    `acceptable["may_include"]` allows it with a matching value (R7)."""
    present = strip_nulls(args, tool)
    required = acceptable.get("args", {})
    optional = acceptable.get("may_include", {})
    if set(present) - set(required) - set(optional):
        return False
    for key, spec in required.items():
        if key not in present or not value_matches(spec, present[key], tool.param(key)):
            return False
    for key, spec in optional.items():
        if key in present and not value_matches(spec, present[key], tool.param(key)):
            return False
    return True


def value_violations(args: dict, tool: ToolSpec) -> list[str]:
    """The canonical schema's value-level constraints a well-formed call
    breaks: unknown keys (R7), enum values outside the set (R1), strings
    failing a pattern. Recorded as detail on a WRONG_PARAMS grade."""
    out = []
    for key, value in strip_nulls(args, tool).items():
        p = tool.param(key)
        if p is None:
            out.append(f"unknown key {key!r}")
        elif p.enum and collapse(value).casefold() not in {e.casefold() for e in p.enum}:
            out.append(f"{key!r}={value!r} is not one of {list(p.enum)}")
        elif p.pattern and re.fullmatch(p.pattern, collapse(value)) is None:
            out.append(f"{key!r}={value!r} does not match {p.pattern!r}")
    return out


def call_key(name: str, args: dict, tool: ToolSpec | None) -> str:
    """One string per distinct call after normalization, for comparing two
    calls: identical retries (August §4) are calls with equal keys."""
    if not isinstance(args, dict):
        return json.dumps([name, repr(args)])
    norm = {}
    for key, value in (strip_nulls(args, tool) if tool else args).items():
        p = tool.param(key) if tool else None
        if isinstance(value, str):
            value = collapse(value)
            if p is not None and p.enum:
                value = value.casefold()
        elif isinstance(value, float) and value.is_integer():
            value = int(value)
        norm[key] = value
    return json.dumps([name, norm], sort_keys=True)
```

Create `toolcall/scenarios.py`:

```python
"""Scenarios: plain data files, validated against the tool library.

A scenario names the tools it needs (its low set), the plausible confusables
written for it (amendment §4c), one user message, and exactly one expectation:
an enumerated list of acceptable calls, or "no call expected" (August §4).
Recovery scenarios add an injected error and the calls that count as recovering.

Validation runs at load time, so a scenario that could never be graded -- an
acceptable call that is itself malformed, a confusable that does not exist --
fails before any money is spent on it.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from toolcall.normalize import conformance, value_matches
from toolcall.tools import Library

TARGETS = ("MALFORMED", "SPURIOUS", "MISSING", "WRONG_TOOL", "WRONG_PARAMS")
ERROR_KINDS = ("invalid_parameter", "contradicting_result", "timeout", "malformed_payload")
# Kinds where repeating the failing call unchanged cannot succeed. H4 is
# computed on these only: after a timeout, an identical retry is correct.
PERSISTENT_KINDS = ("invalid_parameter", "contradicting_result")
LOW_SET = (2, 4)
CONFUSABLES = (4, 6)


@dataclass(frozen=True)
class Recovery:
    error_kind: str
    param: str  # the parameter the error is about
    expected: str  # the actionable message's hint, e.g. "YYYY-MM-DD, for example 2026-11-03"
    acceptable_recovery_calls: tuple[dict, ...]
    success_result: dict
    success_claim_pattern: str  # deterministic proxy for "hallucinated success"
    contradicting_result: dict | None = None


@dataclass(frozen=True)
class Scenario:
    id: str
    source: dict
    domain: str
    target_failure_mode: str
    tools: tuple[str, ...]
    confusables: tuple[str, ...]
    user_message: str
    acceptable_calls: tuple[dict, ...]
    no_call_expected: bool
    recovery: Recovery | None = None

    @property
    def acceptable_tools(self) -> set[str]:
        return {c["tool"] for c in self.acceptable_calls}


def _check_call(call: dict, library: Library, where: str) -> None:
    tool = library.get(call["tool"])
    unknown = set(call) - {"tool", "args", "may_include"}
    if unknown:
        raise ValueError(f"{where}: unknown fields {sorted(unknown)}")
    for group in ("args", "may_include"):
        for key, spec in call.get(group, {}).items():
            p = tool.param(key)
            if p is None:
                raise ValueError(f"{where}: {call['tool']} has no parameter {key!r}")
            if isinstance(spec, dict) and "pattern" in spec:
                if set(spec) != {"pattern", "example"}:
                    raise ValueError(f"{where}: a pattern needs exactly an `example` beside it")
                if not value_matches(spec, spec["example"], p):
                    raise ValueError(f"{where}: example {spec['example']!r} fails its pattern")
                literals = [spec["example"]]
            elif isinstance(spec, dict) and set(spec) == {"one_of"}:
                literals = spec["one_of"]
            elif isinstance(spec, dict):
                raise ValueError(f"{where}: unknown value specification {sorted(spec)}")
            else:
                literals = [spec]
            for lit in literals:
                if conformance({**_required_stub(tool), key: lit}, tool) is not None:
                    raise ValueError(f"{where}: {key}={lit!r} does not fit the canonical type")
                if not value_matches(lit, lit, p):
                    raise ValueError(f"{where}: {key}={lit!r} does not match itself")
    missing = [p.name for p in tool.params if p.required and p.name not in call.get("args", {})]
    if missing:
        raise ValueError(f"{where}: acceptable call omits required {missing}")


def _required_stub(tool) -> dict:
    """A placeholder value of the right type for every required parameter, so
    one literal can be type-checked on its own through `conformance`."""
    filler = {"string": "x", "integer": 1, "number": 1.0, "boolean": True}
    return {
        p.name: ([filler[p.items]] if p.type == "array" else filler[p.type])
        for p in tool.params
        if p.required
    }


def _recovery_from_dict(d: dict | None, library: Library, sid: str) -> Recovery | None:
    if d is None:
        return None
    if d["error_kind"] not in ERROR_KINDS:
        raise ValueError(f"{sid}: error_kind {d['error_kind']!r} not in {ERROR_KINDS}")
    calls = tuple(d["acceptable_recovery_calls"])
    if not calls:
        raise ValueError(f"{sid}: a recovery scenario needs acceptable recovery calls")
    for i, c in enumerate(calls):
        _check_call(c, library, f"{sid} recovery call {i}")
    if d["error_kind"] == "contradicting_result" and not d.get("contradicting_result"):
        raise ValueError(f"{sid}: contradicting_result kind needs a contradicting_result")
    return Recovery(
        error_kind=d["error_kind"],
        param=d["param"],
        expected=d["expected"],
        acceptable_recovery_calls=calls,
        success_result=d["success_result"],
        success_claim_pattern=d["success_claim_pattern"],
        contradicting_result=d.get("contradicting_result"),
    )


def scenario_from_dict(d: dict, library: Library, *, factorial: bool = True) -> Scenario:
    """`factorial=False` is the bring-your-own-tools path (August §7): your own
    tools and scenarios, the baseline formulation only, so the low-set and
    confusable counts the factorial needs are not required."""
    sid = d["id"]
    if d.get("draft"):
        raise ValueError(f"{sid}: still a draft (scripts/a3_import_bfcl.py output); author it")
    exp = d["expectation"]
    no_call = exp.get("no_call_expected", False)
    calls = tuple(exp.get("acceptable_calls", ()))
    if no_call == bool(calls):
        raise ValueError(f"{sid}: give acceptable_calls or no_call_expected, exactly one")
    if d["target_failure_mode"] not in TARGETS:
        raise ValueError(f"{sid}: target_failure_mode must be one of {TARGETS}")
    if no_call and d["target_failure_mode"] != "SPURIOUS":
        raise ValueError(f"{sid}: a no-call scenario targets SPURIOUS")
    tools = tuple(d["tools"])
    confusables = tuple(d["confusables"])
    if factorial and not LOW_SET[0] <= len(tools) <= LOW_SET[1]:
        raise ValueError(f"{sid}: the low set has {len(tools)} tools; amendment §4c says 2-4")
    if factorial and not CONFUSABLES[0] <= len(confusables) <= CONFUSABLES[1]:
        raise ValueError(f"{sid}: {len(confusables)} confusables; amendment §4c says 4-6")
    if not tools:
        raise ValueError(f"{sid}: no tools")
    if set(tools) & set(confusables):
        raise ValueError(f"{sid}: a tool cannot be both in the low set and a confusable")
    for name in tools + confusables:
        library.get(name)
    for i, c in enumerate(calls):
        if c["tool"] not in tools:
            raise ValueError(f"{sid}: acceptable call {i} uses {c['tool']}, not in the low set")
        _check_call(c, library, f"{sid} call {i}")
    recovery = _recovery_from_dict(d.get("recovery"), library, sid)
    if recovery is not None and no_call:
        raise ValueError(f"{sid}: a recovery scenario must expect a call")
    return Scenario(
        id=sid,
        source=d["source"],
        domain=d["domain"],
        target_failure_mode=d["target_failure_mode"],
        tools=tools,
        confusables=confusables,
        user_message=d["user_message"],
        acceptable_calls=calls,
        no_call_expected=no_call,
        recovery=recovery,
    )


def load_scenarios(directory, library: Library, *, factorial: bool = True) -> list[Scenario]:
    out = []
    for path in sorted(Path(directory).glob("*.json")):
        s = scenario_from_dict(json.loads(path.read_text()), library, factorial=factorial)
        if s.id != path.stem:
            raise ValueError(f"{path.name}: id {s.id!r} must equal the file name")
        out.append(s)
    if len({s.id for s in out}) != len(out):
        raise ValueError("duplicate scenario ids")
    return out
```

Create `toolcall/stub_suite.py`:

```python
"""A small synthetic suite for dry runs, the stub demo and tests. NOT DATA.

It exercises every branch of the loader, renderer, grader and recovery loop: a
confusable-heavy flight search, a no-call scenario and a recovery scenario, and
`synthetic_suite` clones them into as many distinct scenarios as a bootstrap
needs. The real suite lives in toolcall/data/ and is authored, not generated.
"""

import copy
import json
from pathlib import Path

from toolcall.scenarios import scenario_from_dict
from toolcall.tools import Library, tool_from_dict


def _p(name, type_, required, terse, rich, **kw):
    return {"name": name, "type": type_, "required": required, "terse": terse, "rich": rich, **kw}


IATA = "^[A-Z]{3}$"
DATE = "^\\d{4}-\\d{2}-\\d{2}$"

TRAVEL = {
    "domain": "travel",
    "tools": [
        {"name": "search_flights", "terse": "Search flights.",
         "rich": "Search scheduled passenger flights between two airports on one date. "
                 "Airports are three-letter IATA codes, for example JFK. Dates are YYYY-MM-DD. "
                 "Use flight_status, not this, for a flight that is already booked.",
         "params": [
             _p("origin", "string", True, "Origin.", "Departure airport, IATA code, e.g. JFK.",
                pattern=IATA),
             _p("destination", "string", True, "Destination.", "Arrival airport, IATA code.",
                pattern=IATA),
             _p("date", "string", True, "Date.", "Departure date, YYYY-MM-DD.", pattern=DATE),
             _p("cabin", "string", False, "Cabin.", "Cabin class. Defaults to economy.",
                enum=["economy", "premium", "business"]),
             _p("passengers", "integer", False, "Passengers.", "Number of travellers, 1-9."),
         ]},
        {"name": "flight_status", "terse": "Flight status.",
         "rich": "Live status of one flight by its flight number, such as UA123.",
         "params": [_p("flight_number", "string", True, "Flight.", "Carrier code and number.")]},
        {"name": "search_trains", "terse": "Search trains.",
         "rich": "Search rail journeys between two stations on one date.",
         "params": [_p("origin", "string", True, "From.", "Origin station name."),
                    _p("destination", "string", True, "To.", "Destination station name."),
                    _p("date", "string", True, "Date.", "YYYY-MM-DD.", pattern=DATE)]},
        {"name": "search_hotels", "terse": "Search hotels.",
         "rich": "Search hotels in a city for a check-in date and a number of nights.",
         "params": [_p("city", "string", True, "City.", "City name."),
                    _p("check_in", "string", True, "Check-in.", "YYYY-MM-DD.", pattern=DATE),
                    _p("nights", "integer", True, "Nights.", "Number of nights, at least 1.")]},
        {"name": "book_flight", "terse": "Book a flight.",
         "rich": "Book a flight already found with search_flights, by its offer id.",
         "params": [_p("offer_id", "string", True, "Offer.", "The id search_flights returned.")]},
        {"name": "flight_prices", "terse": "Flight prices.",
         "rich": "Cheapest fare per day for a route over a month, for flexible dates.",
         "params": [_p("origin", "string", True, "Origin.", "IATA code.", pattern=IATA),
                    _p("destination", "string", True, "Destination.", "IATA code.",
                       pattern=IATA),
                    _p("month", "string", True, "Month.", "YYYY-MM.")]},
        {"name": "airport_info", "terse": "Airport info.",
         "rich": "Terminals, lounges and transport for one airport by IATA code.",
         "params": [_p("code", "string", True, "Code.", "IATA code.", pattern=IATA)]},
        {"name": "get_currency_rate", "terse": "Currency rate.",
         "rich": "Exchange rate between two ISO 4217 currencies, for example USD to EUR.",
         "params": [_p("base", "string", True, "Base.", "ISO 4217 code."),
                    _p("quote", "string", True, "Quote.", "ISO 4217 code.")]},
    ],
}

MISC = {
    "domain": "misc",
    "tools": [
        {"name": f"misc_tool_{i:02d}", "terse": f"Misc {i}.",
         "rich": f"An unrelated utility, number {i}.",
         "params": [_p("value", "string", True, "Value.", "Any value.")]}
        for i in range(1, 17)
    ],
}

FLIGHT = {
    "id": "travel-flight-search",
    "source": {"kind": "authored"},
    "domain": "travel",
    "target_failure_mode": "WRONG_TOOL",
    "tools": ["search_flights", "search_hotels"],
    "confusables": ["flight_status", "flight_prices", "search_trains", "book_flight"],
    "user_message": "Find me a flight from JFK to SFO on 2026-11-03, two of us, economy.",
    "expectation": {"acceptable_calls": [{
        "tool": "search_flights",
        "args": {"origin": "JFK", "destination": "SFO", "date": "2026-11-03"},
        "may_include": {"passengers": 2, "cabin": "economy"},
    }]},
}

SMALLTALK = {
    "id": "travel-no-call",
    "source": {"kind": "authored"},
    "domain": "travel",
    "target_failure_mode": "SPURIOUS",
    "tools": ["search_flights", "airport_info"],
    "confusables": ["flight_status", "flight_prices", "search_trains", "book_flight"],
    "user_message": "Thanks, that's all I needed today.",
    "expectation": {"no_call_expected": True},
}

RECOVERY = {
    "id": "travel-recover-passengers",
    "source": {"kind": "authored"},
    "domain": "travel",
    "target_failure_mode": "WRONG_PARAMS",
    "tools": ["search_flights", "search_hotels"],
    "confusables": ["flight_status", "flight_prices", "search_trains", "book_flight"],
    "user_message": "Flights from BOS to ORD on 2026-12-01, just for me.",
    "expectation": {"acceptable_calls": [{
        "tool": "search_flights",
        "args": {"origin": "BOS", "destination": "ORD", "date": "2026-12-01"},
        "may_include": {"passengers": 1, "cabin": "economy"},
    }]},
    "recovery": {
        "error_kind": "invalid_parameter",
        "param": "passengers",
        "expected": "this service requires the number of travellers, 1-9",
        "acceptable_recovery_calls": [{
            "tool": "search_flights",
            "args": {"origin": "BOS", "destination": "ORD", "date": "2026-12-01",
                     "passengers": 1},
            "may_include": {"cabin": "economy"},
        }],
        "success_result": {"offers": [{"offer_id": "OF-1", "price_usd": 212}]},
        "success_claim_pattern": "\\bOF-\\d+\\b|\\$\\s?212",
    },
}



def library() -> Library:
    tools = {}
    for data in (TRAVEL, MISC):
        for d in data["tools"]:
            tools[d["name"]] = tool_from_dict(d, data["domain"])
    return Library(tools)


AIRPORTS = ("JFK", "SFO", "BOS", "ORD", "LAX", "SEA", "DEN", "ATL", "MIA", "DFW", "IAD", "PHX")


def synthetic_suite(n_call: int = 24, n_no_call: int = 4) -> list[dict]:
    """Distinct scenarios cloned from the three templates. Every third
    call scenario carries the recovery block, so recovery has as many
    scenarios as the bootstrap floor needs when n_call >= 60."""
    out = []
    for i in range(n_call):
        a, b = AIRPORTS[i % len(AIRPORTS)], AIRPORTS[(i * 5 + 1) % len(AIRPORTS)]
        if a == b:
            b = AIRPORTS[(i + 3) % len(AIRPORTS)]
        day = f"2026-11-{(i % 27) + 1:02d}"
        template = RECOVERY if i % 3 == 0 else FLIGHT
        d = copy.deepcopy(template)
        d["id"] = f"synthetic-call-{i:03d}"
        d["user_message"] = f"Flights from {a} to {b} on {day}, just for me. (#{i})"
        d["expectation"]["acceptable_calls"][0]["args"] = {
            "origin": a, "destination": b, "date": day}
        d["expectation"]["acceptable_calls"][0]["may_include"] = {
            "passengers": 1, "cabin": "economy"}
        if "recovery" in d:
            d["recovery"]["acceptable_recovery_calls"][0]["args"] = {
                "origin": a, "destination": b, "date": day, "passengers": 1}
        out.append(d)
    for i in range(n_no_call):
        d = copy.deepcopy(SMALLTALK)
        d["id"] = f"synthetic-nocall-{i:03d}"
        d["user_message"] = f"Thanks, that is everything for today. (#{i})"
        out.append(d)
    return out


def scenarios(dicts=None):
    lib = library()
    return [scenario_from_dict(d, lib) for d in (dicts or synthetic_suite())]


def write_suite(root: Path, dicts=None) -> tuple[Path, Path]:
    """Write the library and scenarios as files, the way toolcall/data/ holds them."""
    tools_dir, sc_dir = Path(root) / "tools", Path(root) / "scenarios"
    tools_dir.mkdir(parents=True, exist_ok=True)
    sc_dir.mkdir(parents=True, exist_ok=True)
    for data in (TRAVEL, MISC):
        (tools_dir / f"{data['domain']}.json").write_text(json.dumps(data))
    for d in dicts or (FLIGHT, SMALLTALK, RECOVERY):
        (sc_dir / f"{d['id']}.json").write_text(json.dumps(d))
    return tools_dir, sc_dir
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/a3_examples.py tests/test_toolcall_tools.py tests/test_toolcall_normalize.py tests/test_toolcall_scenarios.py -v`
Expected: 43 passed.

- [ ] **Step 5: Commit**

```bash
git add toolcall/tools.py toolcall/normalize.py toolcall/scenarios.py toolcall/stub_suite.py tests/a3_examples.py tests/test_toolcall_tools.py tests/test_toolcall_normalize.py tests/test_toolcall_scenarios.py
git commit -m "feat: tools, normalizer v1 and scenarios as validated plain data, with a synthetic suite for tests"
```

---

## Task 3: Eight renderings of one scenario

One scenario, eight renderings, and nothing else differs between them (August §4). Tool order is a function of the scenario and the count level only; richness changes only descriptions; strictness changes only schema keywords. The tests check each of those directly.

**Files:**
- Create: `toolcall/formulation.py`
- Test: `tests/test_toolcall_formulation.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_toolcall_formulation.py`:

```python
"""One scenario, eight renderings, and only the manipulated part differs."""

import json

import pytest

from tests.a3_examples import library, scenario
from toolcall.formulation import (
    BASELINE,
    CELLS,
    HIGH_COUNT,
    Formulation,
    parse_cell,
    render,
    tool_names,
)


def test_eight_cells_with_unique_names_and_a_baseline_among_them():
    assert len({c.name for c in CELLS}) == 8
    assert BASELINE in CELLS
    assert parse_cell("high-rich-strict") == Formulation("high", "rich", "strict")


def test_low_count_is_the_low_set_and_high_count_is_twenty():
    s, lib = scenario(), library()
    assert sorted(tool_names(s, lib, "low")) == sorted(s.tools)
    high = tool_names(s, lib, "high")
    assert len(high) == HIGH_COUNT == len(set(high))
    assert set(s.tools) | set(s.confusables) <= set(high)


def test_tool_order_depends_on_scenario_and_count_only():
    s, lib = scenario(), library()
    orders = {tuple(t["name"] for t in render(s, lib, c)) for c in CELLS if c.count == "high"}
    assert len(orders) == 1


def test_richness_changes_only_descriptions():
    s, lib = scenario(), library()
    terse = render(s, lib, Formulation("high", "terse", "strict"))
    rich = render(s, lib, Formulation("high", "rich", "strict"))

    def strip(tools):
        out = json.loads(json.dumps(tools))
        for t in out:
            t.pop("description")
            for p in t["parameters"]["properties"].values():
                p.pop("description")
        return out

    assert strip(terse) == strip(rich)
    assert terse != rich


def test_strictness_changes_only_schema_keywords():
    s, lib = scenario(), library()
    loose = {t["name"]: t for t in render(s, lib, Formulation("low", "rich", "loose"))}
    strict = {t["name"]: t for t in render(s, lib, Formulation("low", "rich", "strict"))}
    f_loose, f_strict = loose["search_flights"], strict["search_flights"]
    assert f_loose["description"] == f_strict["description"]
    assert f_strict["parameters"]["required"] == ["origin", "destination", "date"]
    assert f_loose["parameters"]["required"] == ["origin"]
    assert f_strict["parameters"]["additionalProperties"] is False
    assert "additionalProperties" not in f_loose["parameters"]
    assert f_strict["parameters"]["properties"]["cabin"]["enum"]
    assert "enum" not in f_loose["parameters"]["properties"]["cabin"]
    assert "pattern" not in f_loose["parameters"]["properties"]["origin"]


@pytest.mark.parametrize("bad", ["mid-terse-loose", "low-terse", "low-short-loose"])
def test_unknown_cells_are_refused(bad):
    with pytest.raises(ValueError):
        parse_cell(bad)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_toolcall_formulation.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'toolcall.formulation'`.

- [ ] **Step 3: Write the implementation**

Create `toolcall/formulation.py`:

```python
"""One scenario, eight renderings, and nothing else differs between them.

The three factors (August §5, amendment §4a and §4c):

- count: `low` is the scenario's own 2-4 tools; `high` is exactly 20 tools,
  the low set plus its confusables plus filler from the domain's library.
- richness: `terse` or `rich` descriptions, for the tool and every parameter.
- strictness: `strict` renders enums, patterns, every required parameter and
  `additionalProperties: false`; `loose` renders bare types and keeps only
  the tool's primary parameter in `required`.

Tool order is a function of the scenario and the count level only, so the
richness and strictness cells of one count level show the model the same
tools in the same order. The system prompt is one fixed text in every cell.
"""

import random
from dataclasses import dataclass

from toolcall.scenarios import Scenario
from toolcall.tools import Library, ToolSpec

HIGH_COUNT = 20
SYSTEM_PROMPT = (
    "You are an assistant that can call tools. Call a tool when the request needs one; "
    "otherwise answer directly. Make at most one tool call per turn."
)


@dataclass(frozen=True)
class Formulation:
    count: str  # "low" | "high"
    richness: str  # "terse" | "rich"
    strictness: str  # "loose" | "strict"

    def __post_init__(self) -> None:
        if self.count not in ("low", "high"):
            raise ValueError(f"count {self.count!r}")
        if self.richness not in ("terse", "rich"):
            raise ValueError(f"richness {self.richness!r}")
        if self.strictness not in ("loose", "strict"):
            raise ValueError(f"strictness {self.strictness!r}")

    @property
    def name(self) -> str:
        return f"{self.count}-{self.richness}-{self.strictness}"

    @property
    def signs(self) -> dict[str, int]:
        """The +1/-1 coding the 2^3 contrasts use (toolcall/effects.py)."""
        return {
            "count": 1 if self.count == "high" else -1,
            "richness": 1 if self.richness == "rich" else -1,
            "strictness": 1 if self.strictness == "strict" else -1,
        }


CELLS = tuple(
    Formulation(c, r, s)
    for c in ("low", "high")
    for r in ("terse", "rich")
    for s in ("loose", "strict")
)
BASELINE = Formulation("low", "terse", "loose")  # amendment §5, proposed for step 1


def parse_cell(name: str) -> Formulation:
    parts = name.split("-")
    if len(parts) != 3:
        raise ValueError(f"cell name {name!r} is not count-richness-strictness")
    return Formulation(*parts)


def tool_names(scenario: Scenario, library: Library, count: str) -> list[str]:
    """The tools in context, in the order the model sees them."""
    names = list(scenario.tools)
    if count == "high":
        names += list(scenario.confusables)
        same = [t.name for t in library.domain(scenario.domain)]
        other = sorted(
            (t.name for t in library.tools.values() if t.domain != scenario.domain),
        )
        for name in same + other:
            if len(names) == HIGH_COUNT:
                break
            if name not in names:
                names.append(name)
        if len(names) < HIGH_COUNT:
            raise ValueError(
                f"{scenario.id}: the library has only {len(names)} tools to offer; "
                f"the high level needs {HIGH_COUNT}"
            )
    random.Random(f"{scenario.id}:{count}").shuffle(names)
    return names


def render_tool(tool: ToolSpec, richness: str, strictness: str) -> dict:
    """Provider-neutral: name, description, JSON-schema parameters."""
    rich = richness == "rich"
    strict = strictness == "strict"
    props = {}
    for p in tool.params:
        prop: dict = {"type": p.type, "description": p.rich if rich else p.terse}
        if p.items:
            prop["items"] = {"type": p.items}
        if strict and p.enum:
            prop["enum"] = list(p.enum)
        if strict and p.pattern:
            prop["pattern"] = p.pattern
        props[p.name] = prop
    if strict:
        required = [p.name for p in tool.params if p.required]
    else:
        required = [tool.primary_param.name] if tool.primary_param else []
    schema: dict = {"type": "object", "properties": props, "required": required}
    if strict:
        schema["additionalProperties"] = False
    return {"name": tool.name, "description": tool.rich if rich else tool.terse,
            "parameters": schema}


def render(scenario: Scenario, library: Library, formulation: Formulation) -> list[dict]:
    return [
        render_tool(library.get(n), formulation.richness, formulation.strictness)
        for n in tool_names(scenario, library, formulation.count)
    ]
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_toolcall_formulation.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add toolcall/formulation.py tests/test_toolcall_formulation.py
git commit -m "feat: the eight cells, and a renderer that changes only the manipulated factor"
```

---

## Task 4: Provider requests and responses

Everything provider-specific in one module, as pure functions over each provider's documented JSON (amendment §3, §7). The settings the amendment fixes are pinned in the builders: `strict: false` sent explicitly, parallel calls off, `tool_choice` `auto`, reasoning `none` or thinking `between_tools`, no temperature where the provider refuses one. `responses.py` builds responses in the documented shapes for dry runs. The JSON fixtures are hand-authored from the providers' API references, not recorded; plan 2's smoke check compares them with real responses.

**Files:**
- Create: `tests/fixtures/a3/` (five response fixtures)
- Create: `toolcall/providers.py`, `toolcall/responses.py`
- Test: `tests/test_toolcall_providers.py`

- [ ] **Step 1: Write the five response fixtures**

Create `tests/fixtures/a3/openai_function_call.json`:

```json
{
  "id": "resp_0a1b2c",
  "object": "response",
  "created_at": 1759900000,
  "status": "completed",
  "model": "gpt-5.4-mini-2026-03-17",
  "output": [
    {
      "type": "function_call",
      "id": "fc_0a1b2c",
      "call_id": "call_9z8y7x",
      "name": "search_flights",
      "arguments": "{\"origin\":\"JFK\",\"destination\":\"SFO\",\"date\":\"2026-11-03\",\"passengers\":2}",
      "status": "completed"
    }
  ],
  "parallel_tool_calls": false,
  "tool_choice": "auto",
  "usage": {
    "input_tokens": 1312,
    "input_tokens_details": {"cached_tokens": 1024},
    "output_tokens": 41,
    "output_tokens_details": {"reasoning_tokens": 0},
    "total_tokens": 1353
  }
}
```

Create `tests/fixtures/a3/openai_message.json`:

```json
{
  "id": "resp_3d4e5f",
  "object": "response",
  "status": "completed",
  "model": "gpt-5.4-mini-2026-03-17",
  "output": [
    {
      "type": "message",
      "id": "msg_3d4e5f",
      "role": "assistant",
      "status": "completed",
      "content": [{"type": "output_text", "text": "You can call search_flights(origin=\"JFK\") to do that.", "annotations": []}]
    }
  ],
  "usage": {"input_tokens": 900, "input_tokens_details": {"cached_tokens": 0}, "output_tokens": 18, "output_tokens_details": {"reasoning_tokens": 0}, "total_tokens": 918}
}
```

Create `tests/fixtures/a3/openai_incomplete.json`:

```json
{
  "id": "resp_6g7h8i",
  "object": "response",
  "status": "incomplete",
  "incomplete_details": {"reason": "max_output_tokens"},
  "model": "gpt-5.4-mini-2026-03-17",
  "output": [
    {"type": "function_call", "id": "fc_6g7h8i", "call_id": "call_1", "name": "search_flights", "arguments": "{\"origin\":\"JF", "status": "incomplete"}
  ],
  "usage": {"input_tokens": 900, "input_tokens_details": {"cached_tokens": 0}, "output_tokens": 1024, "output_tokens_details": {"reasoning_tokens": 0}, "total_tokens": 1924}
}
```

Create `tests/fixtures/a3/anthropic_tool_use.json`:

```json
{
  "id": "msg_01AbCdEf",
  "type": "message",
  "role": "assistant",
  "model": "claude-sonnet-5-5",
  "content": [
    {"type": "thinking", "thinking": "", "signature": "EqQBCkgIARABGAIi"},
    {"type": "text", "text": "Searching now."},
    {"type": "tool_use", "id": "toolu_01XyZ", "name": "search_flights", "input": {"origin": "JFK", "destination": "SFO", "date": "2026-11-03"}}
  ],
  "stop_reason": "tool_use",
  "stop_sequence": null,
  "usage": {"input_tokens": 1500, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 200, "output_tokens": 95}
}
```

Create `tests/fixtures/a3/anthropic_refusal.json`:

```json
{
  "id": "msg_01GhIjKl",
  "type": "message",
  "role": "assistant",
  "model": "claude-sonnet-5-5",
  "content": [{"type": "text", "text": ""}],
  "stop_reason": "refusal",
  "stop_sequence": null,
  "stop_details": {"type": "refusal", "category": null, "explanation": null},
  "usage": {"input_tokens": 1500, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 3}
}
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_toolcall_providers.py`:

```python
"""Request builders and response parsers against hand-authored responses in
each provider's documented shape (tests/fixtures/a3/). No SDK, no network."""

import json
from pathlib import Path

import pytest

from tests.a3_examples import library, scenario
from toolcall.formulation import SYSTEM_PROMPT, Formulation, render
from toolcall.providers import (
    ModelSettings,
    ScriptedClient,
    anthropic_parse,
    anthropic_request,
    openai_parse,
    openai_request,
)
from toolcall.responses import openai_text

FIX = Path(__file__).parent / "fixtures" / "a3"
MINI = ModelSettings("openai", "gpt-5.4-mini-2026-03-17", 0.0, reasoning_effort="none")
SONNET = ModelSettings("anthropic", "claude-sonnet-5-5", None, thinking="between_tools")


def _fixture(name):
    return json.loads((FIX / name).read_text())


def _tools():
    return render(scenario(), library(), Formulation("low", "rich", "strict"))


def test_openai_request_pins_every_setting_the_amendment_fixes():
    body = openai_request(MINI, _tools(), [{"role": "user", "text": "hi"}])
    assert body["model"] == "gpt-5.4-mini-2026-03-17"
    assert body["instructions"] == SYSTEM_PROMPT
    assert body["tool_choice"] == "auto"
    assert body["parallel_tool_calls"] is False
    assert body["reasoning"] == {"effort": "none"}
    assert body["temperature"] == 0.0
    assert body["store"] is False
    assert all(t["strict"] is False and t["type"] == "function" for t in body["tools"])


def test_openai_temperature_is_omitted_when_the_default_is_registered():
    s = ModelSettings("openai", "gpt-5.4-mini-2026-03-17", None, reasoning_effort="none")
    assert "temperature" not in openai_request(s, _tools(), [{"role": "user", "text": "x"}])


def test_anthropic_request_disables_parallel_calls_and_sends_no_temperature():
    body = anthropic_request(SONNET, _tools(), [{"role": "user", "text": "hi"}])
    assert body["tool_choice"] == {"type": "auto", "disable_parallel_tool_use": True}
    assert body["thinking"] == {"type": "between_tools"}
    assert "temperature" not in body
    assert all("strict" not in t and "input_schema" in t for t in body["tools"])


def test_constrained_decoding_is_a_setting_not_a_rendering():
    on = ModelSettings("openai", "gpt-5.4-mini-2026-03-17", 0.0, reasoning_effort="none",
                       constrained=True)
    body = openai_request(on, _tools(), [{"role": "user", "text": "x"}])
    assert all(t["strict"] is True for t in body["tools"])
    flights = next(t for t in body["tools"] if t["name"] == "search_flights")["parameters"]
    assert flights["required"] == list(flights["properties"])
    assert flights["properties"]["cabin"]["type"] == ["string", "null"]
    assert flights["properties"]["origin"]["type"] == "string"
    off = openai_request(MINI, _tools(), [{"role": "user", "text": "x"}])
    assert next(t for t in off["tools"] if t["name"] == "search_flights")["parameters"] == next(
        t for t in _tools() if t["name"] == "search_flights")["parameters"]


def test_a_transcript_round_trips_tool_results_in_each_shape():
    transcript = [
        {"role": "user", "text": "go"},
        {"role": "assistant", "raw": [{"type": "function_call", "call_id": "c1",
                                       "name": "search_flights", "arguments": "{}"}]},
        {"role": "tool", "call_id": "c1", "content": "Error: timeout.", "is_error": True},
    ]
    oa = openai_request(MINI, _tools(), transcript)["input"]
    assert oa[-1] == {"type": "function_call_output", "call_id": "c1",
                      "output": "Error: timeout."}
    an = anthropic_request(SONNET, _tools(), transcript)["messages"]
    assert an[-1]["content"][0]["type"] == "tool_result"
    assert an[-1]["content"][0]["is_error"] is True


def test_openai_function_call_parses_with_cached_usage():
    p = openai_parse(_fixture("openai_function_call.json"))
    assert p.finish == "tool_call"
    assert p.calls[0].name == "search_flights"
    assert json.loads(p.calls[0].arguments)["passengers"] == 2
    assert p.usage == {"input": 1312, "cached": 1024, "cache_write": 0, "output": 41,
                       "reasoning": 0}
    assert p.model == "gpt-5.4-mini-2026-03-17"


def test_openai_text_and_truncation():
    assert openai_parse(_fixture("openai_message.json")).finish == "stop"
    assert openai_parse(_fixture("openai_incomplete.json")).finish == "truncated"


def test_anthropic_tool_use_parses_and_counts_cache_reads_as_input():
    p = anthropic_parse(_fixture("anthropic_tool_use.json"))
    assert p.finish == "tool_call"
    assert json.loads(p.calls[0].arguments) == {"origin": "JFK", "destination": "SFO",
                                                "date": "2026-11-03"}
    assert p.usage["input"] == 1700 and p.usage["cached"] == 200
    assert p.raw_output[0]["type"] == "thinking"


def test_anthropic_refusal():
    assert anthropic_parse(_fixture("anthropic_refusal.json")).finish == "refused"


def test_settings_refuse_the_other_providers_knobs():
    with pytest.raises(ValueError):
        ModelSettings("anthropic", "claude-sonnet-5-5", None, reasoning_effort="none")
    with pytest.raises(ValueError):
        ModelSettings("openai", "gpt-5.4-mini-2026-03-17", 0.0, thinking="between_tools")


def test_the_scripted_client_builds_the_real_body_and_records_it():
    client = ScriptedClient(MINI, lambda body: openai_text("ok"))
    body, response = client.send(_tools(), [{"role": "user", "text": "x"}])
    assert client.sent == [body]
    assert openai_parse(response).text == "ok"
```

- [ ] **Step 3: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_toolcall_providers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'toolcall.providers'`.

- [ ] **Step 4: Write the implementation**

Create `toolcall/providers.py`:

```python
"""The provider interface: build a request, send it, parse the response.

Two providers, OpenAI's Responses API and Anthropic's Messages API (amendment
§3, §7). Everything provider-specific is in this file. The request builders and
response parsers are pure functions over plain dicts in each provider's
documented JSON shape, so they are tested against hand-authored responses with
no SDK installed and no network. The SDKs are imported only inside `send`.

Every call keeps the exact request body it sent. That body is the evidence the
rendering was the only thing that differed between cells (August §4).

A conversation is a provider-neutral transcript, a list of:
    {"role": "user", "text": str}
    {"role": "assistant", "raw": <the provider's output, echoed back unchanged>}
    {"role": "tool", "call_id": str, "content": str, "is_error": bool}
Echoing the assistant's raw output keeps any reasoning or thinking items the
provider requires on the next turn.
"""

import json
from dataclasses import dataclass, field

from toolcall.formulation import SYSTEM_PROMPT

OPENAI = "openai"
ANTHROPIC = "anthropic"


@dataclass(frozen=True)
class ModelSettings:
    provider: str
    model: str
    temperature: float | None  # None: the provider default (amendment §3)
    max_output_tokens: int = 1024
    reasoning_effort: str | None = None  # OpenAI: "none"
    thinking: str | None = None  # Anthropic: "between_tools"
    constrained: bool = False  # provider strict mode; on only in the exploratory slice

    def __post_init__(self) -> None:
        if self.provider not in (OPENAI, ANTHROPIC):
            raise ValueError(f"provider {self.provider!r}")
        if self.provider == ANTHROPIC and self.reasoning_effort is not None:
            raise ValueError("reasoning_effort is an OpenAI setting")
        if self.provider == OPENAI and self.thinking is not None:
            raise ValueError("thinking is an Anthropic setting")

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: str  # the raw JSON text the model produced; parsed by the grader


@dataclass(frozen=True)
class Parsed:
    calls: tuple[ToolCall, ...]
    text: str
    finish: str  # "tool_call" | "stop" | "refused" | "truncated"
    usage: dict  # {"input", "cached", "cache_write", "output", "reasoning"}
    model: str
    raw_output: list = field(default_factory=list)


# --- OpenAI Responses API -------------------------------------------------


def openai_strict_parameters(schema: dict) -> dict:
    """OpenAI's strict mode requires every property in `required` and
    `additionalProperties: false`; an optional property is written as a
    union with null instead. Used only when constrained decoding is on (the
    exploratory slice, amendment §4a), so the factorial's schemas are never
    touched by it."""
    props = {}
    required = set(schema.get("required", []))
    for name, prop in schema["properties"].items():
        prop = dict(prop)
        if name not in required:
            prop["type"] = [prop["type"], "null"]
        props[name] = prop
    return {"type": "object", "properties": props, "required": list(props),
            "additionalProperties": False}



def openai_request(settings: ModelSettings, tools: list[dict], transcript: list[dict]) -> dict:
    items: list = []
    for turn in transcript:
        if turn["role"] == "user":
            items.append({"role": "user", "content": turn["text"]})
        elif turn["role"] == "assistant":
            items.extend(turn["raw"])
        elif turn["role"] == "tool":
            items.append(
                {"type": "function_call_output", "call_id": turn["call_id"],
                 "output": turn["content"]}
            )
        else:
            raise ValueError(f"unknown transcript role {turn['role']!r}")
    body = {
        "model": settings.model,
        "instructions": SYSTEM_PROMPT,
        "input": items,
        "tools": [
            {"type": "function", "name": t["name"], "description": t["description"],
             "parameters": (openai_strict_parameters(t["parameters"]) if settings.constrained
                            else t["parameters"]),
             "strict": settings.constrained}
            for t in tools
        ],
        "tool_choice": "auto",
        "parallel_tool_calls": False,
        "max_output_tokens": settings.max_output_tokens,
        "store": False,
    }
    if settings.reasoning_effort is not None:
        body["reasoning"] = {"effort": settings.reasoning_effort}
    if settings.temperature is not None:
        body["temperature"] = settings.temperature
    return body


def openai_parse(response: dict) -> Parsed:
    calls, texts, refused = [], [], False
    for item in response.get("output", []):
        if item.get("type") == "function_call":
            calls.append(ToolCall(item["call_id"], item["name"], item["arguments"]))
        elif item.get("type") == "message":
            for part in item.get("content", []):
                if part.get("type") == "output_text":
                    texts.append(part["text"])
                elif part.get("type") == "refusal":
                    refused = True
    reason = (response.get("incomplete_details") or {}).get("reason")
    if refused or reason == "content_filter":
        finish = "refused"
    elif response.get("status") == "incomplete" and reason == "max_output_tokens":
        finish = "truncated"
    elif calls:
        finish = "tool_call"
    else:
        finish = "stop"
    u = response.get("usage") or {}
    usage = {
        "input": u.get("input_tokens", 0),
        "cached": (u.get("input_tokens_details") or {}).get("cached_tokens", 0),
        "cache_write": 0,
        "output": u.get("output_tokens", 0),
        "reasoning": (u.get("output_tokens_details") or {}).get("reasoning_tokens", 0),
    }
    return Parsed(tuple(calls), "\n".join(texts), finish, usage, response.get("model", ""),
                  list(response.get("output", [])))


# --- Anthropic Messages API -----------------------------------------------


def anthropic_request(settings: ModelSettings, tools: list[dict], transcript: list[dict]) -> dict:
    messages: list = []
    for turn in transcript:
        if turn["role"] == "user":
            messages.append({"role": "user", "content": turn["text"]})
        elif turn["role"] == "assistant":
            messages.append({"role": "assistant", "content": turn["raw"]})
        elif turn["role"] == "tool":
            messages.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": turn["call_id"],
                 "content": turn["content"], "is_error": turn["is_error"]}
            ]})
        else:
            raise ValueError(f"unknown transcript role {turn['role']!r}")
    rendered = []
    for t in tools:
        tool = {"name": t["name"], "description": t["description"],
                "input_schema": t["parameters"]}
        if settings.constrained:
            tool["strict"] = True
        rendered.append(tool)
    body = {
        "model": settings.model,
        "max_tokens": settings.max_output_tokens,
        "system": SYSTEM_PROMPT,
        "messages": messages,
        "tools": rendered,
        "tool_choice": {"type": "auto", "disable_parallel_tool_use": True},
    }
    if settings.thinking is not None:
        body["thinking"] = {"type": settings.thinking}
    if settings.temperature is not None:
        body["temperature"] = settings.temperature
    return body


def anthropic_parse(response: dict) -> Parsed:
    calls, texts = [], []
    for block in response.get("content", []):
        if block.get("type") == "tool_use":
            calls.append(ToolCall(block["id"], block["name"], json.dumps(block["input"])))
        elif block.get("type") == "text":
            texts.append(block["text"])
    stop = response.get("stop_reason")
    if stop == "refusal":
        finish = "refused"
    elif stop == "max_tokens":
        finish = "truncated"
    elif calls:
        finish = "tool_call"
    else:
        finish = "stop"
    u = response.get("usage") or {}
    read = u.get("cache_read_input_tokens") or 0
    write = u.get("cache_creation_input_tokens") or 0
    usage = {
        "input": (u.get("input_tokens") or 0) + read + write,
        "cached": read,
        "cache_write": write,
        "output": u.get("output_tokens") or 0,
        "reasoning": 0,
    }
    return Parsed(tuple(calls), "\n".join(texts), finish, usage, response.get("model", ""),
                  list(response.get("content", [])))


BUILD = {OPENAI: openai_request, ANTHROPIC: anthropic_request}
PARSE = {OPENAI: openai_parse, ANTHROPIC: anthropic_parse}


# --- Clients --------------------------------------------------------------


class Client:
    """Builds and sends one request. `send` returns (request body, response
    dict); `request` and `post` are its two halves, so a caller can keep the
    body even when the post raises."""

    def __init__(self, settings: ModelSettings, sdk=None):
        self.settings = settings
        self._sdk = sdk

    def request(self, tools: list[dict], transcript: list[dict]) -> dict:
        return BUILD[self.settings.provider](self.settings, tools, transcript)

    def post(self, body: dict) -> dict:
        if self._sdk is None:
            if self.settings.provider == OPENAI:
                from openai import OpenAI

                self._sdk = OpenAI()
            else:
                from anthropic import Anthropic

                self._sdk = Anthropic()
        if self.settings.provider == OPENAI:
            return self._sdk.responses.create(**body).model_dump()
        return self._sdk.messages.create(**body).model_dump()

    def send(self, tools: list[dict], transcript: list[dict]) -> tuple[dict, dict]:
        body = self.request(tools, transcript)
        return body, self.post(body)


class ScriptedClient(Client):
    """No network. `policy(body)` returns a response dict in the provider's
    documented shape (toolcall/responses.py builds them). The request body is
    still built by the real builder, so dry runs exercise it."""

    def __init__(self, settings: ModelSettings, policy):
        super().__init__(settings, sdk=None)
        self.policy = policy
        self.sent: list[dict] = []

    def post(self, body: dict) -> dict:
        self.sent.append(body)
        return self.policy(body)
```

Create `toolcall/responses.py`:

```python
"""Provider responses, hand-built in each provider's documented JSON shape.

For dry runs and tests: the scripted client returns these, so the whole
harness -- parsing, grading, analysis, figures -- runs with no API call
(August §6, "dry-run mode is a build requirement"). Field names follow the
OpenAI Responses API and Anthropic Messages API references; the parser tests
in tests/test_toolcall_providers.py pin the shapes against
tests/fixtures/a3/*.json.
"""

import itertools
import json

_ids = itertools.count(1)


def _usage_openai(input_tokens: int, output_tokens: int, cached: int = 0) -> dict:
    return {
        "input_tokens": input_tokens,
        "input_tokens_details": {"cached_tokens": cached},
        "output_tokens": output_tokens,
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": input_tokens + output_tokens,
    }


def openai_call(name: str, args, *, model="gpt-5.4-mini-2026-03-17", input_tokens=1000,
                output_tokens=40, raw_arguments: str | None = None) -> dict:
    n = next(_ids)
    arguments = raw_arguments if raw_arguments is not None else json.dumps(args)
    return {
        "id": f"resp_{n}", "object": "response", "model": model, "status": "completed",
        "output": [{"type": "function_call", "id": f"fc_{n}", "call_id": f"call_{n}",
                    "name": name, "arguments": arguments, "status": "completed"}],
        "usage": _usage_openai(input_tokens, output_tokens),
    }


def openai_text(text: str, *, model="gpt-5.4-mini-2026-03-17", input_tokens=1000,
                output_tokens=40) -> dict:
    n = next(_ids)
    return {
        "id": f"resp_{n}", "object": "response", "model": model, "status": "completed",
        "output": [{"type": "message", "id": f"msg_{n}", "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": text, "annotations": []}]}],
        "usage": _usage_openai(input_tokens, output_tokens),
    }


def openai_refusal(*, model="gpt-5.4-mini-2026-03-17") -> dict:
    n = next(_ids)
    return {
        "id": f"resp_{n}", "object": "response", "model": model, "status": "completed",
        "output": [{"type": "message", "id": f"msg_{n}", "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "refusal", "refusal": "I can't help with that."}]}],
        "usage": _usage_openai(1000, 10),
    }


def openai_truncated(*, model="gpt-5.4-mini-2026-03-17") -> dict:
    n = next(_ids)
    return {
        "id": f"resp_{n}", "object": "response", "model": model, "status": "incomplete",
        "incomplete_details": {"reason": "max_output_tokens"},
        "output": [{"type": "function_call", "id": f"fc_{n}", "call_id": f"call_{n}",
                    "name": "search_flights", "arguments": '{"origin": "JF',
                    "status": "incomplete"}],
        "usage": _usage_openai(1000, 1024),
    }


def anthropic_call(name: str, args: dict, *, model="claude-sonnet-5-5", input_tokens=1000,
                   output_tokens=40) -> dict:
    n = next(_ids)
    return {
        "id": f"msg_{n}", "type": "message", "role": "assistant", "model": model,
        "content": [{"type": "tool_use", "id": f"toolu_{n}", "name": name, "input": args}],
        "stop_reason": "tool_use", "stop_sequence": None,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens,
                  "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
    }


def anthropic_text(text: str, *, model="claude-sonnet-5-5", stop_reason="end_turn") -> dict:
    n = next(_ids)
    return {
        "id": f"msg_{n}", "type": "message", "role": "assistant", "model": model,
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop_reason, "stop_sequence": None,
        "usage": {"input_tokens": 1000, "output_tokens": 40,
                  "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
    }
```

- [ ] **Step 5: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_toolcall_providers.py -v`
Expected: 11 passed.

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/a3 tests/test_toolcall_providers.py toolcall/providers.py toolcall/responses.py
git commit -m "feat: provider request builders and response parsers over documented shapes, and scripted responses"
```

---

## Task 5: The grader

The ordered, deterministic procedure (August §4) with amendment §4b's canonical schema and §4g's provider-side outcomes. The test is the hand-labelled set the August definition of done requires: every category, and every precedence boundary where two rules could both apply. One test pins that the grader never sees the rendered schema.

**Files:**
- Create: `toolcall/grader.py`
- Test: `tests/test_toolcall_grader.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_toolcall_grader.py`:

```python
"""Hand-labelled cases for all six categories and the three excluded outcomes,
including every precedence boundary (August §10's definition of done).

Each case is (label, scenario, response, expected category). The boundary
cases are the ones where two rules could both apply and the order decides.
"""

import json

import pytest

from tests.a3_examples import FLIGHT, SMALLTALK, library, scenario
from toolcall.formulation import tool_names
from toolcall.grader import CATEGORIES, EXCLUDED, grade
from toolcall.providers import anthropic_parse, openai_parse
from toolcall.responses import (
    anthropic_call,
    anthropic_text,
    openai_call,
    openai_refusal,
    openai_text,
    openai_truncated,
)

OK = {"origin": "JFK", "destination": "SFO", "date": "2026-11-03"}
LIB = library()
FLIGHT_S, NOCALL_S = scenario(FLIGHT), scenario(SMALLTALK)
HIGH = tool_names(FLIGHT_S, LIB, "high")
NOCALL_HIGH = tool_names(NOCALL_S, LIB, "high")

CASES = [
    # --- one clear case per category
    ("correct", FLIGHT_S, openai_call("search_flights", {**OK, "passengers": 2}), "CORRECT"),
    ("correct, optional enum in another case", FLIGHT_S,
     openai_call("search_flights", {**OK, "cabin": "Economy"}), "CORRECT"),
    ("correct direct answer", NOCALL_S, openai_text("You're welcome!"), "CORRECT"),
    ("missing", FLIGHT_S, openai_text("There are usually morning flights."), "MISSING"),
    ("spurious", NOCALL_S, openai_call("airport_info", {"code": "JFK"}), "SPURIOUS"),
    ("wrong tool, a confusable", FLIGHT_S, openai_call("flight_prices", {
        "origin": "JFK", "destination": "SFO", "month": "2026-11"}), "WRONG_TOOL"),
    ("wrong params, a value", FLIGHT_S, openai_call("search_flights", {**OK, "date": "2026-11-04"}),
     "WRONG_PARAMS"),
    ("malformed, unparseable", FLIGHT_S,
     openai_call("search_flights", None, raw_arguments='{"origin": "JFK",'), "MALFORMED"),
    # --- precedence boundaries
    ("malformed beats spurious: a broken call where none was expected", NOCALL_S,
     openai_call("airport_info", None, raw_arguments="not json"), "MALFORMED"),
    ("malformed beats wrong tool: a hallucinated tool name", FLIGHT_S,
     openai_call("search_flights_v2", OK), "MALFORMED"),
    ("malformed beats wrong params: a required key missing", FLIGHT_S,
     openai_call("search_flights", {"origin": "JFK", "destination": "SFO"}), "MALFORMED"),
    ("malformed beats wrong params: wrong JSON type", FLIGHT_S,
     openai_call("search_flights", {**OK, "passengers": "2"}), "MALFORMED"),
    ("an enum outside the set is a value error, not structural", FLIGHT_S,
     openai_call("search_flights", {**OK, "cabin": "first"}), "WRONG_PARAMS"),
    ("a pattern violation is a value error, not structural", FLIGHT_S,
     openai_call("search_flights", {**OK, "origin": "New York"}), "WRONG_PARAMS"),
    ("an unknown key is a wrong parameter (R7)", FLIGHT_S,
     openai_call("search_flights", {**OK, "seat": "aisle"}), "WRONG_PARAMS"),
    ("spurious beats wrong tool: any well-formed call where none was expected", NOCALL_S,
     openai_call("search_flights", OK), "SPURIOUS"),
    ("wrong tool beats wrong params: the wrong tool with the right-looking args", FLIGHT_S,
     openai_call("search_trains", {"origin": "JFK", "destination": "SFO",
                                   "date": "2026-11-03"}), "WRONG_TOOL"),
    ("arguments that are not an object are malformed", FLIGHT_S,
     openai_call("search_flights", None, raw_arguments='["JFK"]'), "MALFORMED"),
    ("a call written in text is not a call", FLIGHT_S,
     openai_text('search_flights(origin="JFK", destination="SFO")'), "MISSING"),
    # --- excluded outcomes come first
    ("refusal", FLIGHT_S, openai_refusal(), "REFUSED"),
    ("truncated call", FLIGHT_S, openai_truncated(), "TRUNCATED"),
]


@pytest.mark.parametrize("label, sc, response, expected", CASES, ids=[c[0] for c in CASES])
def test_hand_labelled(label, sc, response, expected):
    rendered = NOCALL_HIGH if sc is NOCALL_S else HIGH
    assert grade(openai_parse(response), sc, LIB, rendered).category == expected


def test_every_category_and_exclusion_is_covered():
    assert {c[3] for c in CASES} == set(CATEGORIES) | (set(EXCLUDED) - {"API_ERROR"})


def test_a_provider_error_is_api_error():
    assert grade(None, FLIGHT_S, LIB, HIGH, error="RateLimitError: 429").category == "API_ERROR"


def test_a_tool_not_rendered_in_this_cell_is_malformed():
    low = tool_names(FLIGHT_S, LIB, "low")
    r = openai_call("flight_prices", {"origin": "JFK", "destination": "SFO", "month": "2026-11"})
    assert grade(openai_parse(r), FLIGHT_S, LIB, low).category == "MALFORMED"


def test_wrong_tool_records_whether_it_was_a_confusable_or_filler():
    conf = grade(openai_parse(openai_call("flight_status", {"flight_number": "UA1"})),
                 FLIGHT_S, LIB, HIGH)
    filler = next(n for n in HIGH if n.startswith("misc_tool"))
    fill = grade(openai_parse(openai_call(filler, {"value": "x"})), FLIGHT_S, LIB, HIGH)
    low = grade(openai_parse(openai_call("search_hotels", {
        "city": "SF", "check_in": "2026-11-03", "nights": 1})), FLIGHT_S, LIB, HIGH)
    assert (conf.wrong_tool_kind, fill.wrong_tool_kind, low.wrong_tool_kind) == (
        "confusable", "filler", "low_set")


def test_the_flags_are_recorded_but_do_not_change_the_category():
    g = grade(openai_parse(openai_text('Use search_flights(origin="JFK")')), FLIGHT_S, LIB, HIGH)
    assert g.category == "MISSING" and g.text_looks_like_call


def test_two_calls_are_graded_on_the_first_and_flagged():
    r = openai_call("search_flights", OK)
    r["output"].append({**r["output"][0], "name": "flight_status",
                        "arguments": json.dumps({"flight_number": "UA1"})})
    g = grade(openai_parse(r), FLIGHT_S, LIB, HIGH)
    assert g.category == "CORRECT" and g.multiple_calls


def test_grading_is_the_same_across_providers():
    oa = grade(openai_parse(openai_call("search_flights", OK)), FLIGHT_S, LIB, HIGH)
    an = grade(anthropic_parse(anthropic_call("search_flights", OK)), FLIGHT_S, LIB, HIGH)
    assert oa.category == an.category == "CORRECT"
    assert grade(anthropic_parse(anthropic_text("", stop_reason="max_tokens")), FLIGHT_S, LIB,
                 HIGH).category == "TRUNCATED"


def test_grading_twice_gives_the_same_answer():
    r = openai_parse(openai_call("search_flights", {**OK, "cabin": "first"}))
    assert grade(r, FLIGHT_S, LIB, HIGH) == grade(r, FLIGHT_S, LIB, HIGH)


def test_the_grade_does_not_depend_on_the_rendered_schema():
    """Amendment §4b: the grader takes the rendered tool names, never the
    rendered schemas, so an enum the loose cell never declared is graded
    against the canonical schema exactly as in the strict cell."""
    import inspect

    assert list(inspect.signature(grade).parameters) == [
        "parsed", "scenario", "library", "rendered", "error"]
    r = openai_parse(openai_call("search_flights", {**OK, "cabin": "first"}))
    assert grade(r, FLIGHT_S, LIB, tool_names(FLIGHT_S, LIB, "low")).category == "WRONG_PARAMS"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_toolcall_grader.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'toolcall.grader'`.

- [ ] **Step 3: Write the implementation**

Create `toolcall/grader.py`:

```python
"""The deterministic grader: one response, one category.

The ordered procedure (August §4, with amendment §4b's canonical schema and
§4g's provider-side outcomes ahead of it):

    0. Provider-side: the request failed, the model refused, or the output
       hit the cap                                -> API_ERROR / REFUSED / TRUNCATED
       (excluded before any rate is computed, counted per cell)
    1. A call was made but is not a parseable call to a rendered tool that
       conforms structurally to the canonical schema    -> MALFORMED
    2. No call was expected, and a call was made         -> SPURIOUS
    3. A call was expected, and none was made            -> MISSING
    4. The tool is not one an acceptable call names      -> WRONG_TOOL
    5. The arguments match no acceptable call            -> WRONG_PARAMS
    6. otherwise                                         -> CORRECT

No call at all is never MALFORMED: a direct answer is MISSING or, where no call
was expected, CORRECT. A tool call written into the text instead of a call
block is flagged (`text_looks_like_call`) but graded by the same rules, so the
flag is descriptive only.

A response with more than one call is graded on its first and flagged.
"""

import json
from dataclasses import dataclass

from toolcall import NORMALIZER_VERSION
from toolcall.normalize import call_matches, conformance, value_violations
from toolcall.providers import Parsed
from toolcall.scenarios import Scenario
from toolcall.tools import Library

CATEGORIES = ("MALFORMED", "SPURIOUS", "MISSING", "WRONG_TOOL", "WRONG_PARAMS", "CORRECT")
FAILURES = CATEGORIES[:-1]
EXCLUDED = ("API_ERROR", "REFUSED", "TRUNCATED")


@dataclass(frozen=True)
class Grade:
    category: str
    detail: str
    multiple_calls: bool = False
    text_looks_like_call: bool = False
    wrong_tool_kind: str | None = None  # "confusable" | "filler" | "low_set"
    normalizer_version: int = NORMALIZER_VERSION

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d: dict) -> "Grade":
        return cls(**d)


def parse_arguments(raw: str):
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _looks_like_call(text: str, rendered: list[str]) -> bool:
    return any(f"{name}(" in text or f'"{name}"' in text for name in rendered)


def grade(parsed: Parsed | None, scenario: Scenario, library: Library, rendered: list[str],
          error: str | None = None) -> Grade:
    if error is not None or parsed is None:
        return Grade("API_ERROR", error or "no response")
    if parsed.finish == "refused":
        return Grade("REFUSED", "provider reported a refusal")
    if parsed.finish == "truncated":
        return Grade("TRUNCATED", "output cap reached")
    flags = {
        "multiple_calls": len(parsed.calls) > 1,
        "text_looks_like_call": not parsed.calls and _looks_like_call(parsed.text, rendered),
    }
    if parsed.calls:
        call = parsed.calls[0]
        args = parse_arguments(call.arguments)
        if call.name not in rendered:
            return Grade("MALFORMED", f"tool {call.name!r} is not in context", **flags)
        tool = library.get(call.name)
        why = conformance(args, tool)
        if why is not None:
            return Grade("MALFORMED", why, **flags)
        if scenario.no_call_expected:
            return Grade("SPURIOUS", f"called {call.name} when no call was expected", **flags)
        if call.name not in scenario.acceptable_tools:
            if call.name in scenario.confusables:
                kind = "confusable"
            elif call.name in scenario.tools:
                kind = "low_set"
            else:
                kind = "filler"
            return Grade("WRONG_TOOL", f"called {call.name}", wrong_tool_kind=kind, **flags)
        acceptable = [c for c in scenario.acceptable_calls if c["tool"] == call.name]
        if not any(call_matches(args, c, tool) for c in acceptable):
            detail = "; ".join(value_violations(args, tool)) or "values match no acceptable call"
            return Grade("WRONG_PARAMS", detail, **flags)
        return Grade("CORRECT", "", **flags)
    if scenario.no_call_expected:
        return Grade("CORRECT", "answered directly, as expected", **flags)
    return Grade("MISSING", "answered without a call", **flags)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_toolcall_grader.py -v`
Expected: 30 passed.

- [ ] **Step 5: Commit**

```bash
git add toolcall/grader.py tests/test_toolcall_grader.py
git commit -m "feat: the deterministic grader, with hand-labelled cases for every category and boundary"
```

---

## Task 6: Prices, the spend guard, mock tools and recovery

- `prices.py`: per-token prices pinned with their source and read date. Cost is always usage times these.
- `guard.py`: the portfolio rule in code. A paid script refuses to start unless the approved amount covers its estimate, refuses any call whose upper bound could cross it, and meters real usage (amendment §7, §14 item 5).
- `mock_tools.py`: the four error kinds in two message formats (August §4, §14 item 4).
- `recovery.py`: one conversation, its turn budget and the five measures. Identical retry compares normalized calls.

The spend guard's own tests are in Task 7, where there is a campaign for it to stop.

**Files:**
- Create: `toolcall/prices.py`
- Create: `toolcall/guard.py`
- Create: `toolcall/mock_tools.py`
- Create: `toolcall/recovery.py`
- Test: `tests/test_toolcall_recovery.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_toolcall_recovery.py`:

```python
import copy
import json

import pytest

from tests.a3_examples import RECOVERY, library, scenario
from toolcall.formulation import Formulation
from toolcall.mock_tools import error_text, reply
from toolcall.providers import ModelSettings, ScriptedClient
from toolcall.recovery import TURN_BUDGET, converse
from toolcall.responses import openai_call, openai_text

LIB = library()
SC = scenario(RECOVERY)
FIRST = {"origin": "BOS", "destination": "ORD", "date": "2026-12-01"}
FIXED = {**FIRST, "passengers": 1}
MINI = ModelSettings("openai", "gpt-5.4-mini-2026-03-17", 0.0, reasoning_effort="none")
CELL = Formulation("low", "terse", "loose")


def _script(*responses):
    it = iter(responses)
    return ScriptedClient(MINI, lambda body: next(it))


def test_actionable_names_the_parameter_and_opaque_does_not():
    assert "passengers" in error_text(SC.recovery, "actionable")
    assert error_text(SC.recovery, "opaque") == "Error: invalid request."


def test_invalid_parameter_rejects_until_the_requirement_is_met():
    assert reply(SC.recovery, "opaque", 0, "search_flights", FIRST, LIB).is_error
    assert reply(SC.recovery, "opaque", 1, "search_flights", FIRST, LIB).is_error
    assert reply(SC.recovery, "opaque", 1, "search_flights", FIXED, LIB).success


def test_timeout_fails_once_and_an_identical_retry_then_succeeds():
    rec = copy.deepcopy(RECOVERY)
    rec["recovery"]["error_kind"] = "timeout"
    rec["recovery"]["acceptable_recovery_calls"][0]["args"] = dict(FIRST)
    rec["recovery"]["acceptable_recovery_calls"][0]["may_include"] = {"passengers": 1}
    sc = scenario(rec)
    assert reply(sc.recovery, "opaque", 0, "search_flights", FIRST, LIB).is_error
    assert reply(sc.recovery, "opaque", 1, "search_flights", FIRST, LIB).success


def test_contradicting_result_is_not_an_error_but_is_not_success():
    rec = copy.deepcopy(RECOVERY)
    rec["recovery"]["error_kind"] = "contradicting_result"
    rec["recovery"]["contradicting_result"] = {"offers": [], "date": "2026-12-02"}
    sc = scenario(rec)
    r = reply(sc.recovery, "actionable", 0, "search_flights", FIRST, LIB)
    assert not r.is_error and not r.success and "do not match" in r.content
    assert json.loads(reply(sc.recovery, "opaque", 0, "search_flights", FIRST, LIB).content)


def test_an_identical_retry_then_a_fix_is_recovered_in_two():
    c = converse(_script(openai_call("search_flights", FIRST),
                         openai_call("search_flights", {**FIRST, "origin": " BOS"}),
                         openai_call("search_flights", FIXED)), SC, LIB, CELL, "opaque")
    assert c.injected and c.identical_retry and c.recovered and c.turns_to_recovery == 2


def test_giving_up_and_claiming_success_are_told_apart():
    gave = converse(_script(openai_call("search_flights", FIRST),
                            openai_text("Sorry, the search failed.")), SC, LIB, CELL, "opaque")
    lied = converse(_script(openai_call("search_flights", FIRST),
                            openai_text("Found one: offer OF-1 at $212.")), SC, LIB, CELL,
                    "opaque")
    assert gave.gave_up and not gave.hallucinated_success and gave.identical_retry is False
    assert lied.hallucinated_success and not lied.gave_up


def test_the_budget_is_three_attempts_after_the_error():
    calls = [openai_call("search_flights", FIRST) for _ in range(TURN_BUDGET + 1)]
    c = converse(_script(*calls), SC, LIB, CELL, "opaque")
    assert c.budget_exhausted and not c.recovered and len(c.turns) == TURN_BUDGET + 1


def test_a_first_call_that_already_meets_the_requirement_injects_nothing():
    c = converse(_script(openai_call("search_flights", FIXED)), SC, LIB, CELL, "opaque")
    assert not c.injected and c.identical_retry is None


def test_the_tool_reply_reaches_the_model_on_the_next_turn():
    client = _script(openai_call("search_flights", FIRST), openai_text("ok"))
    converse(client, SC, LIB, CELL, "actionable")
    last = client.sent[-1]["input"][-1]
    assert last["type"] == "function_call_output" and "passengers" in last["output"]


def test_a_provider_failure_mid_conversation_is_excluded():
    def boom(body):
        raise TimeoutError("read timeout")

    c = converse(ScriptedClient(MINI, boom), SC, LIB, CELL, "opaque")
    assert c.excluded == "API_ERROR"


def test_a_scenario_without_a_recovery_block_is_refused():
    from tests.a3_examples import FLIGHT

    with pytest.raises(ValueError, match="no recovery block"):
        converse(_script(), scenario(FLIGHT), LIB, CELL, "opaque")
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_toolcall_recovery.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'toolcall.mock_tools'`.

- [ ] **Step 3: Write the implementation**

Create `toolcall/prices.py`:

```python
"""Per-token prices, pinned with their source and the date they were read.

Cost in this artifact is computed from each response's own `usage`, times these
prices. The spend record (docs/spend-a3.md) compares that computation with
what the provider billed (amendment §8). A price change between the pilot and
the campaign is caught there; this table is re-read at pre-registration step 2.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Price:
    input: float  # USD per million uncached input tokens
    cached: float  # USD per million cache-read input tokens
    cache_write: float  # USD per million cache-write input tokens (Anthropic only)
    output: float  # USD per million output tokens, reasoning included
    source: str
    read: str  # the date the source was read
    check: str  # "docs" or "secondary", as amendment §0's labels


PRICES = {
    "gpt-5.4-mini-2026-03-17": Price(
        0.75, 0.075, 0.0, 4.50,
        "https://developers.openai.com/api/docs/models/gpt-5.4-mini", "2026-10-08", "docs"),
    "gpt-5.4-nano-2026-03-17": Price(
        0.20, 0.02, 0.0, 1.25,
        "https://developers.openai.com/api/docs/models/gpt-5.4-nano", "2026-10-08", "secondary"),
    "claude-sonnet-5-5": Price(
        2.00, 0.20, 2.50, 10.00,
        "https://platform.claude.com/docs/en/about-claude/pricing", "2026-10-08", "docs"),
}


def cost_usd(model: str, usage: dict) -> float:
    """`usage` is the normalized dict toolcall.providers parsers return:
    `input` counts every input token, cached and cache-written included."""
    if model not in PRICES:
        raise KeyError(f"no pinned price for {model!r}; add it with its source first")
    p = PRICES[model]
    uncached = usage["input"] - usage["cached"] - usage["cache_write"]
    if uncached < 0:
        raise ValueError(f"usage has more cached than total input tokens: {usage}")
    return (
        uncached * p.input
        + usage["cached"] * p.cached
        + usage["cache_write"] * p.cache_write
        + usage["output"] * p.output
    ) / 1e6
```

Create `toolcall/guard.py`:

```python
"""The spend guard (amendment §7).

The portfolio rule: no paid call without the author's explicit yes, stating the
number of calls and the estimated cost. A paid script therefore takes an
`--approved-usd` amount and does three things with it:

1. Before anything runs, it refuses if its own estimate exceeds the amount
   (`check_estimate`).
2. Before every call, it refuses if that call's upper bound could take total
   spend past the amount (`SpendGuard.before`).
3. After every call, it adds that call's metered cost from the response.

The per-call bound (`call_bound_usd`) is an upper bound, not an estimate: the
output can never exceed `max_output_tokens`, and the input is counted at two
characters of request JSON per token, where the providers' tokenizers average
three to four on this text. Plan 2 checks that assumption against the pilot's
recorded usage (`bound_held`). A bound rather than the largest call seen so far,
because a call larger than any before it would otherwise cross the cap.

`SpendCapReached` deliberately is not caught by the campaign's error handling:
it stops the run, and the records already stored stay stored.
"""

import json

from toolcall.prices import PRICES, cost_usd

CHARS_PER_TOKEN_BOUND = 2.0
TOKENIZER_FACTOR = {"openai": 1.0, "anthropic": 1.3}  # amendment §8


class SpendCapReached(RuntimeError):
    pass


def input_tokens_bound(settings, body: dict) -> float:
    return len(json.dumps(body)) / CHARS_PER_TOKEN_BOUND * TOKENIZER_FACTOR[settings.provider]


def call_bound_usd(settings, body: dict) -> float:
    p = PRICES[settings.model]
    return (input_tokens_bound(settings, body) * p.input
            + settings.max_output_tokens * p.output) / 1e6


def bound_held(settings, body: dict, usage: dict) -> bool:
    return usage["input"] <= input_tokens_bound(settings, body)


def check_estimate(estimate_usd: float, approved_usd: float) -> None:
    if approved_usd <= 0:
        raise SpendCapReached("no spend approved: pass --approved-usd with the amount agreed")
    if estimate_usd > approved_usd:
        raise SpendCapReached(
            f"estimated ${estimate_usd:.2f} exceeds the approved ${approved_usd:.2f}; "
            "ask the author for a new approval rather than raising the number"
        )


class SpendGuard:
    def __init__(self, approved_usd: float):
        if approved_usd <= 0:
            raise SpendCapReached("no spend approved")
        self.approved = approved_usd
        self.spent = 0.0
        self.calls = 0

    def before(self, bound_usd: float) -> None:
        if self.spent + bound_usd > self.approved:
            raise SpendCapReached(
                f"stopping: ${self.spent:.4f} spent over {self.calls} calls, and the next "
                f"(up to ${bound_usd:.4f}) could exceed the approved ${self.approved:.2f}"
            )

    def add(self, model: str, usage: dict) -> float:
        cost = cost_usd(model, usage)
        self.spent += cost
        self.calls += 1
        return cost


class GuardedClient:
    """Wraps a client so every post passes through the guard. Same interface."""

    def __init__(self, client, guard: SpendGuard, parse):
        self.client = client
        self.settings = client.settings
        self.guard = guard
        self._parse = parse

    def request(self, tools, transcript):
        return self.client.request(tools, transcript)

    def post(self, body):
        self.guard.before(call_bound_usd(self.settings, body))
        response = self.client.post(body)
        self.guard.add(self.settings.model, self._parse(response).usage)
        return response

    def send(self, tools, transcript):
        body = self.request(tools, transcript)
        return body, self.post(body)
```

Create `toolcall/mock_tools.py`:

```python
"""The mock tool layer: what a tool "returns" in a recovery scenario.

Mock tools exist because recovery needs something to fail (August §4). They
produce state, and the state is recorded, but grading never depends on it.

How each error kind behaves, decided by the scenario's acceptable recovery
calls (the calls the service would accept):

- invalid_parameter: the service rejects any call that matches no acceptable
  recovery call, naming the parameter. A first call that already matches is
  accepted, and that conversation records that no error was injected.
- contradicting_result: the first call returns a success-shaped result that
  contradicts the request. Later calls that match an acceptable recovery call
  get the real result; anything else gets the contradiction again.
- timeout, malformed_payload: the first call fails whatever it was. Later calls
  that match get the real result. These are transient: an identical retry is
  the right move, which is why H4 excludes them (scenarios.PERSISTENT_KINDS).

Two message formats per kind, the nested factor: `actionable` says what went
wrong and what to do; `opaque` says only that something did.
"""

import json
from dataclasses import dataclass

from toolcall.normalize import call_matches
from toolcall.scenarios import Recovery
from toolcall.tools import Library

FORMATS = ("actionable", "opaque")


@dataclass(frozen=True)
class ToolReply:
    content: str
    is_error: bool
    success: bool


def error_text(recovery: Recovery, fmt: str) -> str:
    if fmt not in FORMATS:
        raise ValueError(f"format {fmt!r}")
    p, hint = recovery.param, recovery.expected
    if recovery.error_kind == "invalid_parameter":
        if fmt == "actionable":
            return (f"Error: invalid request. Parameter '{p}': {hint}. The request was not "
                    f"processed; correct '{p}' and call again.")
        return "Error: invalid request."
    if recovery.error_kind == "timeout":
        if fmt == "actionable":
            return ("Error: the service timed out before processing the request. Nothing was "
                    "changed; the same request can be sent again.")
        return "Error: timeout."
    if recovery.error_kind == "malformed_payload":
        if fmt == "actionable":
            return ("Error: the service returned an unreadable response. Nothing was changed; "
                    "the same request can be sent again.")
        return "Error: bad response."
    raise ValueError(f"{recovery.error_kind} has no error text; it returns a result")


def _contradiction(recovery: Recovery, fmt: str) -> str:
    body = json.dumps(recovery.contradicting_result, sort_keys=True)
    if fmt == "actionable":
        return (f"{body}\nNote: these results do not match the requested '{recovery.param}'. "
                f"{recovery.expected}.")
    return body


def _accepted(name: str, args, recovery: Recovery, library: Library) -> bool:
    if not isinstance(args, dict):
        return False
    tool = library.tools.get(name)
    return tool is not None and any(
        c["tool"] == name and call_matches(args, c, tool)
        for c in recovery.acceptable_recovery_calls
    )


def reply(recovery: Recovery, fmt: str, attempt: int, name: str, args,
          library: Library) -> ToolReply:
    """The tool's answer to call number `attempt` (0 is the first call)."""
    ok = _accepted(name, args, recovery, library)
    success = ToolReply(json.dumps(recovery.success_result, sort_keys=True), False, True)
    kind = recovery.error_kind
    if kind == "invalid_parameter":
        return success if ok else ToolReply(error_text(recovery, fmt), True, False)
    if kind == "contradicting_result":
        if attempt > 0 and ok:
            return success
        return ToolReply(_contradiction(recovery, fmt), False, False)
    if attempt == 0 or not ok:
        return ToolReply(error_text(recovery, fmt), True, False)
    return success
```

Create `toolcall/recovery.py`:

```python
"""One recovery conversation: the first call meets an error, then up to
`TURN_BUDGET` attempts to recover (amendment §4e).

The measures, per conversation (August §4):

- injected: an error or contradiction reached the model. Every other measure
  is defined only when this is true; conversations without one are counted.
- recovered, turns_to_recovery: an attempt matched an acceptable recovery call.
- identical_retry: the first action after the error repeated the failing call
  unchanged, after normalization (`normalize.call_key`). The headline measure.
- gave_up: the model stopped calling without recovering, and its text does not
  claim success.
- hallucinated_success: it stopped calling without recovering, and its text
  matches the scenario's `success_claim_pattern`. That is a deterministic proxy
  for "claimed success", disclosed as such in the post: it cannot see a claim
  phrased in a way the pattern does not anticipate.
"""

import re
import time
from dataclasses import dataclass

from toolcall.formulation import Formulation, render
from toolcall.grader import grade, parse_arguments
from toolcall.guard import SpendCapReached
from toolcall.mock_tools import reply
from toolcall.normalize import call_key
from toolcall.providers import PARSE
from toolcall.scenarios import Scenario
from toolcall.tools import Library

TURN_BUDGET = 3


@dataclass
class Conversation:
    turns: list  # one dict per model turn: request, response, parsed summary, tool reply
    first_grade: dict | None
    injected: bool
    recovered: bool
    turns_to_recovery: int | None
    identical_retry: bool | None
    gave_up: bool
    hallucinated_success: bool
    budget_exhausted: bool
    excluded: str | None  # API_ERROR / REFUSED / TRUNCATED mid-conversation, or None


def _summary(parsed) -> dict:
    return {"finish": parsed.finish, "text": parsed.text, "usage": parsed.usage,
            "model": parsed.model,
            "calls": [{"call_id": c.call_id, "name": c.name, "arguments": c.arguments}
                      for c in parsed.calls]}


def converse(client, scenario: Scenario, library: Library, formulation: Formulation,
             fmt: str) -> Conversation:
    rec = scenario.recovery
    if rec is None:
        raise ValueError(f"{scenario.id} has no recovery block")
    tools = render(scenario, library, formulation)
    rendered = [t["name"] for t in tools]
    transcript = [{"role": "user", "text": scenario.user_message}]
    turns: list = []
    out = {"first_grade": None, "injected": False, "recovered": False,
           "turns_to_recovery": None, "identical_retry": None, "gave_up": False,
           "hallucinated_success": False, "budget_exhausted": False, "excluded": None}
    failing_key = None
    for attempt in range(TURN_BUDGET + 1):
        t0 = time.monotonic()
        try:
            body, response = client.send(tools, transcript)
        except SpendCapReached:
            raise
        except Exception as e:  # noqa: BLE001 -- every provider failure is data here
            turns.append({"error": f"{type(e).__name__}: {e}"})
            out["excluded"] = "API_ERROR"
            break
        parsed = PARSE[client.settings.provider](response)
        turn = {"request": body, "response": response, "parsed": _summary(parsed),
                "seconds": time.monotonic() - t0}
        turns.append(turn)
        if attempt == 0:
            out["first_grade"] = grade(parsed, scenario, library, rendered).to_dict()
        if parsed.finish in ("refused", "truncated"):
            out["excluded"] = "REFUSED" if parsed.finish == "refused" else "TRUNCATED"
            break
        if not parsed.calls:
            if attempt > 0:
                claims = re.search(rec.success_claim_pattern, parsed.text, re.IGNORECASE)
                out["hallucinated_success"] = bool(claims)
                out["gave_up"] = not claims
                if out["identical_retry"] is None:
                    out["identical_retry"] = False
            break
        call = parsed.calls[0]
        args = parse_arguments(call.arguments)
        key = call_key(call.name, args, library.tools.get(call.name))
        if attempt == 1:
            out["identical_retry"] = key == failing_key
        r = reply(rec, fmt, attempt, call.name, args, library)
        turn["tool_reply"] = {"content": r.content, "is_error": r.is_error,
                              "success": r.success}
        if r.success:
            if attempt == 0:
                break  # accepted first time: nothing was injected
            out["recovered"] = True
            out["turns_to_recovery"] = attempt
            break
        if attempt == 0:
            out["injected"] = True
            failing_key = key
        transcript += [
            {"role": "assistant", "raw": parsed.raw_output},
            {"role": "tool", "call_id": call.call_id, "content": r.content,
             "is_error": r.is_error},
        ]
    else:
        out["budget_exhausted"] = True
    return Conversation(turns=turns, **out)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_toolcall_recovery.py -v`
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add toolcall/prices.py toolcall/guard.py toolcall/mock_tools.py toolcall/recovery.py tests/test_toolcall_recovery.py
git commit -m "feat: pinned prices, the spend guard, the mock tool layer and the recovery loop"
```

---

## Task 7: Records, the campaign, and the stub model

Each call is one run of `harness.campaign.run_campaign`: interleaved by `build_schedule`, never retried in place, with the resume drift guard. A `CallRecord` keeps the exact request body and the raw response, so re-grading under a new normalizer needs no new call. A response naming a model other than the pinned one fails its record (amendment §3).

`stub.py` is a `ScriptedClient` policy with planted effects: it reads the request body the real builder produced and works out the scenario and cell from it alone. Its token counts come from the size of the request, as a real API's would.

**Files:**
- Create: `toolcall/records.py`
- Create: `toolcall/campaign.py`
- Create: `toolcall/stub.py`
- Test: `tests/test_toolcall_campaign.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_toolcall_campaign.py`:

```python
from collections import Counter

import pytest

from harness.store import JsonlStore
from tests.a3_examples import library, scenarios, synthetic_suite
from toolcall import campaign
from toolcall.formulation import CELLS, parse_cell
from toolcall.guard import (
    GuardedClient,
    SpendCapReached,
    SpendGuard,
    bound_held,
    call_bound_usd,
    check_estimate,
)
from toolcall.prices import cost_usd
from toolcall.providers import ModelSettings, ScriptedClient, openai_parse
from toolcall.records import CallRecord, RecoveryRecord
from toolcall.responses import openai_call, openai_text
from toolcall.stub import StubModel

MINI = ModelSettings("openai", "gpt-5.4-mini-2026-03-17", 0.0, reasoning_effort="none")
LIB = library()
SCS = scenarios(synthetic_suite(6, 2))


def _stub_client():
    return ScriptedClient(MINI, StubModel(LIB, SCS, seed=1))


def test_each_block_is_every_condition_once_in_a_shuffled_order():
    sched = campaign.schedule(CELLS, SCS, reps=3, seed=4)
    assert len(sched) == 3 * 8 * len(SCS)
    for b in range(3):
        block = [s.condition for s in sched if s.block_index == b]
        assert sorted(block) == sorted(campaign.condition(c, s.id) for c in CELLS for s in SCS)
    firsts = [[s.condition for s in sched if s.block_index == b][:5] for b in range(3)]
    assert firsts[0] != firsts[1]


def test_a_campaign_stores_one_graded_record_per_scheduled_call(tmp_path):
    store = JsonlStore(tmp_path / "c.jsonl", CallRecord)
    client = _stub_client()
    campaign.single_turn(campaign.schedule(CELLS, SCS, 2, 1), client, SCS, LIB, store,
                         phase="campaign")
    records = store.read_all()
    assert len(records) == 2 * 8 * len(SCS)
    r = records[0]
    assert r.request == client.sent[0]
    assert r.grade["category"] and r.cost_usd > 0 and r.returned_model == r.model
    assert r.rendered_tools == [t["name"] for t in r.request["tools"]]


def test_a_returned_model_that_differs_from_the_pin_fails_the_record(tmp_path):
    other = ScriptedClient(MINI, lambda body: openai_text("hi", model="gpt-5.4-mini"))
    store = JsonlStore(tmp_path / "c.jsonl", CallRecord)
    campaign.single_turn(campaign.schedule(CELLS[:1], SCS[:1], 1, 1), other, SCS, LIB, store,
                         phase="campaign")
    r = store.read_all()[0]
    assert r.grade["category"] == "API_ERROR" and "model mismatch" in r.error


def test_a_provider_exception_is_a_recorded_api_error_with_the_request_kept(tmp_path):
    def fail(body):
        raise ConnectionError("reset by peer")

    store = JsonlStore(tmp_path / "c.jsonl", CallRecord)
    campaign.single_turn(campaign.schedule(CELLS[:1], SCS[:1], 1, 1),
                         ScriptedClient(MINI, fail), SCS, LIB, store, phase="campaign")
    r = store.read_all()[0]
    assert r.grade["category"] == "API_ERROR" and r.request is not None and r.usage is None


def test_resume_skips_done_runs_and_refuses_a_drifted_schedule(tmp_path):
    store = JsonlStore(tmp_path / "c.jsonl", CallRecord)
    sched = campaign.schedule(CELLS, SCS, 2, 1)
    campaign.single_turn(sched[:10], _stub_client(), SCS, LIB, store, phase="campaign")
    campaign.single_turn(sched, _stub_client(), SCS, LIB, store, phase="campaign", resume=True)
    assert sorted(r.run_index for r in store.read_all()) == list(range(len(sched)))
    with pytest.raises(ValueError, match="resume"):
        campaign.single_turn(campaign.schedule(CELLS, SCS, 2, 99), _stub_client(), SCS, LIB,
                             store, phase="campaign", resume=True)


def test_the_spend_guard_stops_the_campaign_and_keeps_what_ran(tmp_path):
    first = cost_usd(MINI.model, openai_parse(openai_call("x", {})).usage)
    guard = SpendGuard(approved_usd=first * 30)
    client = GuardedClient(_stub_client(), guard, openai_parse)
    store = JsonlStore(tmp_path / "c.jsonl", CallRecord)
    sched = campaign.schedule(CELLS, SCS, 2, 1)
    with pytest.raises(SpendCapReached):
        campaign.single_turn(sched, client, SCS, LIB, store, phase="campaign")
    assert 0 < len(store.read_all()) == guard.calls < len(sched)
    assert guard.spent <= guard.approved


def test_check_estimate_needs_an_approval_that_covers_it():
    with pytest.raises(SpendCapReached, match="no spend approved"):
        check_estimate(1.0, 0.0)
    with pytest.raises(SpendCapReached, match="exceeds"):
        check_estimate(2.0, 1.0)
    check_estimate(1.0, 1.0)


def test_recovery_runs_store_every_turn(tmp_path):
    rec = [s for s in SCS if s.recovery]
    store = JsonlStore(tmp_path / "r.jsonl", RecoveryRecord)
    cells = [parse_cell("low-terse-loose")]
    campaign.recovery_runs(campaign.schedule(cells, rec, 2, 3, formats=["actionable", "opaque"]),
                           _stub_client(), rec, LIB, store)
    records = store.read_all()
    assert Counter(r.fmt for r in records) == {"actionable": 2 * len(rec),
                                               "opaque": 2 * len(rec)}
    assert all(r.turns and r.cost_usd > 0 for r in records)


def test_cost_comes_from_usage_and_the_pinned_price():
    usage = {"input": 2000, "cached": 1000, "cache_write": 0, "output": 100, "reasoning": 0}
    assert cost_usd("gpt-5.4-mini-2026-03-17", usage) == pytest.approx(
        (1000 * 0.75 + 1000 * 0.075 + 100 * 4.5) / 1e6)
    with pytest.raises(KeyError, match="no pinned price"):
        cost_usd("gpt-9", usage)


def test_the_per_call_bound_is_never_below_what_a_call_costs(tmp_path):
    client = _stub_client()
    store = JsonlStore(tmp_path / "c.jsonl", CallRecord)
    campaign.single_turn(campaign.schedule(CELLS, SCS, 1, 1), client, SCS, LIB, store,
                         phase="campaign")
    for r in store.read_all():
        assert bound_held(MINI, r.request, r.usage)
        assert call_bound_usd(MINI, r.request) >= r.cost_usd
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_toolcall_campaign.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'toolcall.campaign'`.

- [ ] **Step 3: Write the implementation**

Create `toolcall/records.py`:

```python
"""What one stored run is. Both shapes go through `harness.store.JsonlStore`.

A `CallRecord` is one single-turn call: the cell, the scenario, the repetition,
the exact request body, the raw response or the error, and the grade. A
`RecoveryRecord` is one recovery conversation with every turn kept.

Records keep the raw provider response, not only the grade, so re-grading
under a new normalizer version needs no new call.
"""

from dataclasses import asdict, dataclass

from toolcall import NORMALIZER_VERSION, SCHEMA_VERSION


@dataclass
class CallRecord:
    run_index: int
    block_index: int  # the repetition: block b is every (cell, scenario) once
    condition: str  # "<cell>|<scenario id>"
    run_id: str
    phase: str  # "pilot-baseline" | "pilot-cells" | "campaign" | "slice" | "exploratory"
    model: str  # the pinned id the request named
    returned_model: str | None
    cell: str
    scenario_id: str
    settings: dict
    request: dict | None
    response: dict | None
    error: str | None
    clock_A: dict
    grade: dict
    usage: dict | None
    cost_usd: float | None
    rendered_tools: list
    schema_version: int = SCHEMA_VERSION
    normalizer_version: int = NORMALIZER_VERSION

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CallRecord":
        return cls(**d)


@dataclass
class RecoveryRecord:
    run_index: int
    block_index: int
    condition: str  # "<cell>|<scenario id>|<format>"
    run_id: str
    phase: str  # "recovery"
    model: str
    cell: str
    scenario_id: str
    error_kind: str
    fmt: str
    settings: dict
    turns: list
    first_grade: dict | None
    injected: bool
    recovered: bool
    turns_to_recovery: int | None
    identical_retry: bool | None
    gave_up: bool
    hallucinated_success: bool
    budget_exhausted: bool
    excluded: str | None
    cost_usd: float
    schema_version: int = SCHEMA_VERSION
    normalizer_version: int = NORMALIZER_VERSION

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RecoveryRecord":
        return cls(**d)
```

Create `toolcall/campaign.py`:

```python
"""Single-turn and recovery runs, through the harness campaign loop.

A condition is one (cell, scenario) pair; a block is one repetition of every
condition, in an order `harness.scheduler.build_schedule` shuffles per block.
So repetitions of one condition are spread across the whole run rather than
fired back to back, and a provider-side change mid-run lands on every cell
alike rather than on whichever cell happened to be running.

`run_campaign` never retries a run in place and refuses a resume whose
schedule drifted (harness/campaign.py). Each phase and model gets its own store.
"""

import time

from harness.campaign import run_campaign
from harness.scheduler import build_schedule
from harness.submit import SubmitOutcome
from toolcall.formulation import Formulation, parse_cell, render
from toolcall.grader import grade
from toolcall.guard import SpendCapReached
from toolcall.prices import cost_usd
from toolcall.providers import PARSE
from toolcall.records import CallRecord, RecoveryRecord
from toolcall.recovery import converse


def condition(cell: Formulation, scenario_id: str, fmt: str | None = None) -> str:
    return "|".join([cell.name, scenario_id] + ([fmt] if fmt else []))


def schedule(cells, scenarios, reps: int, seed: int, formats=None):
    """`formats` set: a recovery schedule, one condition per format as well."""
    conds = [
        condition(c, s.id, f)
        for c in cells
        for s in scenarios
        for f in (formats or [None])
    ]
    return build_schedule(conds, reps, seed)


def _split(cond: str) -> tuple[Formulation, str, str | None]:
    parts = cond.split("|")
    return parse_cell(parts[0]), parts[1], (parts[2] if len(parts) == 3 else None)


def single_turn(schedule_, client, scenarios, library, store, *, phase: str,
                resume: bool = False, on_run=None):
    by_id = {s.id: s for s in scenarios}
    provider = client.settings.provider
    rendered_cache: dict = {}

    def tools_for(cond):
        if cond not in rendered_cache:
            cell, sid, _ = _split(cond)
            rendered_cache[cond] = render(by_id[sid], library, cell)
        return rendered_cache[cond]

    def submit(scheduled, run_id):
        _, sid, _ = _split(scheduled.condition)
        tools = tools_for(scheduled.condition)
        body = client.request(tools, [{"role": "user", "text": by_id[sid].user_message}])
        t_submit = time.time()
        try:
            response = client.post(body)
        except SpendCapReached:
            raise
        except Exception as e:  # noqa: BLE001 -- a provider failure is a recorded outcome
            return SubmitOutcome({"t_submit": t_submit, "t_result": time.time()}, None,
                                 f"{type(e).__name__}: {e}", {"request": body})
        return SubmitOutcome({"t_submit": t_submit, "t_result": time.time()},
                             {"request": body, "response": response}, None)

    def build(scheduled, run_id, outcome):
        cell, sid, _ = _split(scheduled.condition)
        tools = tools_for(scheduled.condition)
        names = [t["name"] for t in tools]
        model = client.settings.model
        error, parsed, response = outcome.error, None, None
        request = (outcome.payload or outcome.diagnostics or {}).get("request")
        if outcome.payload is not None:
            response = outcome.payload["response"]
            parsed = PARSE[provider](response)
            if parsed.model != model:
                error = f"model mismatch: asked for {model}, response names {parsed.model}"
        g = grade(parsed, by_id[sid], library, names, error=error)
        usage = parsed.usage if parsed else None
        return CallRecord(
            run_index=scheduled.run_index, block_index=scheduled.block_index,
            condition=scheduled.condition, run_id=run_id, phase=phase, model=model,
            returned_model=parsed.model if parsed else None, cell=cell.name,
            scenario_id=sid, settings=client.settings.to_dict(), request=request,
            response=response, error=error, clock_A=outcome.clock_A, grade=g.to_dict(),
            usage=usage, cost_usd=cost_usd(model, usage) if usage else None,
            rendered_tools=names,
        )

    return run_campaign(
        schedule_, submit, build, store,
        index_of=lambda r: r.run_index, condition_of=lambda r: r.condition,
        on_run=on_run, resume=resume,
    )


def recovery_runs(schedule_, client, scenarios, library, store, *, resume: bool = False,
                  on_run=None):
    by_id = {s.id: s for s in scenarios}

    def submit(scheduled, run_id):
        cell, sid, fmt = _split(scheduled.condition)
        t_submit = time.time()
        conv = converse(client, by_id[sid], library, cell, fmt)
        return SubmitOutcome({"t_submit": t_submit, "t_result": time.time()},
                             {"conversation": conv}, None)

    def build(scheduled, run_id, outcome):
        cell, sid, fmt = _split(scheduled.condition)
        conv = outcome.payload["conversation"]
        model = client.settings.model
        cost = sum(
            cost_usd(model, t["parsed"]["usage"]) for t in conv.turns if "parsed" in t
        )
        return RecoveryRecord(
            run_index=scheduled.run_index, block_index=scheduled.block_index,
            condition=scheduled.condition, run_id=run_id, phase="recovery", model=model,
            cell=cell.name, scenario_id=sid, error_kind=by_id[sid].recovery.error_kind,
            fmt=fmt, settings=client.settings.to_dict(), turns=conv.turns,
            first_grade=conv.first_grade, injected=conv.injected, recovered=conv.recovered,
            turns_to_recovery=conv.turns_to_recovery, identical_retry=conv.identical_retry,
            gave_up=conv.gave_up, hallucinated_success=conv.hallucinated_success,
            budget_exhausted=conv.budget_exhausted, excluded=conv.excluded, cost_usd=cost,
        )

    return run_campaign(
        schedule_, submit, build, store,
        index_of=lambda r: r.run_index, condition_of=lambda r: r.condition,
        on_run=on_run, resume=resume,
    )
```

Create `toolcall/stub.py`:

```python
"""A GPU-free, network-free stand-in for a model, with planted effects. NOT DATA.

`StubModel` is a `ScriptedClient` policy. It reads the request body the real
builder produced, works out which scenario and which cell it is looking at
from the rendered tools alone, and draws a category from probabilities with
known effects planted in them. The end-to-end tests check that the analysis
recovers those effects, the way artifact 5's stub let its tests check that its
analysis recovered the costs put in.

Planted (as rates of each category, before scenario difficulty):

- WRONG_TOOL rises with tool count, and rich descriptions cut it only at high
  count: the H1 interaction and H3.
- MALFORMED and WRONG_PARAMS fall under the strict schema: H2. Strictness does
  not touch WRONG_TOOL.
- Repetitions are sticky: with probability `stickiness` a call repeats its
  (scenario, cell) unit's first draw, so the intra-scenario correlation is high,
  as the Noise Floor Audit found for real endpoints.
- Recovery: opaque errors are followed by an identical retry more often than
  actionable ones: H4.
"""

import json
import random

from toolcall import responses
from toolcall.formulation import Formulation

PLANTED = {
    "WRONG_TOOL": {"base": 0.03, "high": 0.18, "high_rich": -0.12},
    "MALFORMED": {"base": 0.05, "strict": -0.04},
    "WRONG_PARAMS": {"base": 0.08, "strict": -0.05},
    "MISSING": {"base": 0.03},
    "SPURIOUS": {"base": 0.10, "high": 0.10},
}
IDENTICAL_RETRY = {"opaque": 0.45, "actionable": 0.10}


def _stable(*parts) -> random.Random:
    return random.Random(":".join(str(p) for p in parts))


class StubModel:
    def __init__(self, library, scenarios, *, seed: int = 0, stickiness: float = 0.8,
                 model: str = "gpt-5.4-mini-2026-03-17", difficulty: float = 0.10):
        self.library = library
        self.by_message = {s.user_message: s for s in scenarios}
        if len(self.by_message) != len(scenarios):
            raise ValueError("the stub identifies scenarios by user message; make them unique")
        self.seed = seed
        self.stickiness = stickiness
        self.model = model
        self.difficulty = {s.id: _stable(seed, "difficulty", s.id).random() * difficulty
                           for s in scenarios}
        self.calls_seen: dict = {}

    # -- reading the request -------------------------------------------------

    def _cell(self, tools: list[dict]) -> Formulation:
        count = "high" if len(tools) == 20 else "low"
        strict = any("additionalProperties" in t["parameters"] for t in tools)
        first = tools[0]
        rich = first["description"] == self.library.get(first["name"]).rich
        return Formulation(count, "rich" if rich else "terse", "strict" if strict else "loose")

    def _scenario_and_turns(self, body: dict):
        items = body["input"]
        user = next(i["content"] for i in items if i.get("role") == "user")
        tool_outputs = [i for i in items if i.get("type") == "function_call_output"]
        return self.by_message[user], tool_outputs

    # -- choosing an outcome -------------------------------------------------

    def _probabilities(self, scenario, cell: Formulation) -> dict[str, float]:
        high, rich, strict = cell.count == "high", cell.richness == "rich", \
            cell.strictness == "strict"
        d = self.difficulty[scenario.id]

        def rate(cat):
            p = PLANTED[cat]
            return max(0.0, p["base"] + p.get("high", 0) * high
                       + p.get("high_rich", 0) * (high and rich) + p.get("strict", 0) * strict)

        if scenario.no_call_expected:
            return {"SPURIOUS": min(0.9, rate("SPURIOUS") + d)}
        return {"WRONG_TOOL": rate("WRONG_TOOL") + d, "MALFORMED": rate("MALFORMED"),
                "WRONG_PARAMS": rate("WRONG_PARAMS") + d, "MISSING": rate("MISSING")}

    @staticmethod
    def _draw(rng, probs) -> str:
        x = rng.random()
        for cat, p in probs.items():
            if x < p:
                return cat
            x -= p
        return "CORRECT"

    # -- writing the response --------------------------------------------------

    def _stub_args(self, tool_name: str) -> dict:
        filler = {"string": "x", "integer": 1, "number": 1.0, "boolean": True}
        tool = self.library.get(tool_name)
        args = {}
        for p in tool.params:
            if not p.required:
                continue
            if p.enum:
                args[p.name] = p.enum[0]
            elif p.pattern == "^[A-Z]{3}$":
                args[p.name] = "AAA"
            elif p.pattern:
                args[p.name] = "2026-01-01"
            else:
                args[p.name] = [filler[p.items]] if p.type == "array" else filler[p.type]
        return args

    @staticmethod
    def _literal(spec):
        if isinstance(spec, dict) and "one_of" in spec:
            return spec["one_of"][0]
        if isinstance(spec, dict):
            return spec["example"]
        return spec

    def _respond(self, scenario, category: str, tools: list[dict], tokens: int) -> dict:
        names = [t["name"] for t in tools]
        kw = {"model": self.model, "input_tokens": tokens}
        if category == "CORRECT" and scenario.no_call_expected:
            return responses.openai_text("You're welcome.", **kw)
        if category == "MISSING":
            return responses.openai_text("I think there are flights in the morning.", **kw)
        if category == "SPURIOUS":
            return responses.openai_call(names[0], self._stub_args(names[0]), **kw)
        call = scenario.acceptable_calls[0]
        args = {k: self._literal(v) for k, v in call["args"].items()}
        if category == "CORRECT":
            return responses.openai_call(call["tool"], args, **kw)
        if category == "MALFORMED":
            return responses.openai_call(call["tool"], None, raw_arguments='{"origin": ', **kw)
        if category == "WRONG_TOOL":
            wrong = [n for n in names if n not in scenario.acceptable_tools]
            if wrong:
                return responses.openai_call(wrong[0], self._stub_args(wrong[0]), **kw)
            category = "WRONG_PARAMS"
        key = next(iter(args))
        args[key] = "ZZZ" if isinstance(args[key], str) else args[key] + 7
        return responses.openai_call(call["tool"], args, **kw)

    def _recovery_turn(self, scenario, tool_outputs, body) -> dict:
        last = tool_outputs[-1]["output"]
        fmt = "opaque" if len(last) < 40 else "actionable"
        rng = _stable(self.seed, "recovery", scenario.id, len(tool_outputs),
                      self.calls_seen.setdefault(("rec", scenario.id), 0))
        self.calls_seen[("rec", scenario.id)] += 1
        first = next(i for i in body["input"] if i.get("type") == "function_call")
        x = rng.random()
        if x < IDENTICAL_RETRY[fmt]:
            return responses.openai_call(first["name"], None,
                                         raw_arguments=first["arguments"], model=self.model)
        if x < IDENTICAL_RETRY[fmt] + 0.4:
            fix = scenario.recovery.acceptable_recovery_calls[0]
            return responses.openai_call(
                fix["tool"], {k: self._literal(v) for k, v in fix["args"].items()},
                model=self.model)
        return responses.openai_text("Sorry, I could not complete the search.",
                                     model=self.model)

    def __call__(self, body: dict) -> dict:
        """Usage reports input tokens from the size of the request, as a real
        API would, so per-cell costs differ the way they will when paid."""
        tokens = max(1, len(json.dumps(body)) // 4)
        scenario, tool_outputs = self._scenario_and_turns(body)
        if tool_outputs:
            return self._recovery_turn(scenario, tool_outputs, body)
        cell = self._cell(body["tools"])
        unit = (scenario.id, cell.name)
        n = self.calls_seen.get(unit, 0)
        self.calls_seen[unit] = n + 1
        probs = self._probabilities(scenario, cell)
        rng = _stable(self.seed, "call", *unit, n)
        if rng.random() < self.stickiness:
            category = self._draw(_stable(self.seed, "unit", *unit), probs)
        else:
            category = self._draw(rng, probs)
        if scenario.recovery is not None and category == "CORRECT":
            # recovery scenarios open with the natural call, which the
            # service then rejects for want of the parameter it requires
            call = scenario.acceptable_calls[0]
            return responses.openai_call(
                call["tool"], {k: self._literal(v) for k, v in call["args"].items()},
                model=self.model, input_tokens=tokens)
        return self._respond(scenario, category, body["tools"], tokens)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_toolcall_campaign.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add toolcall/records.py toolcall/campaign.py toolcall/stub.py tests/test_toolcall_campaign.py
git commit -m "feat: call and recovery records, campaign wiring through the harness loop, and a stub model with planted effects"
```

---

## Task 8: Rates, effects and intervals clustered on scenario

Amendment §4f. Wilson intervals only within one scenario; cell rates average per-scenario rates; effects are 2³ contrasts on the risk-difference scale; every interval resamples whole scenarios. The percentile endpoints, iteration checks and the floor of 20 are the harness's own, imported. One test shows why clustering matters: 24 scenarios that each always fail or always pass give an interval about twice as wide as a 240-call Wilson interval would claim.

**Files:**
- Create: `toolcall/effects.py`
- Test: `tests/test_toolcall_effects.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_toolcall_effects.py`:

```python
import math

import pytest

from toolcall.effects import (
    cluster_bootstrap,
    contrast,
    ever_flip_rows,
    half_rows,
    holm,
    rate_rows,
    weights,
    wilson,
)
from toolcall.formulation import CELLS


def test_wilson_matches_the_textbook_values():
    lo, hi = wilson(3, 100)
    assert lo == pytest.approx(0.01025, abs=1e-4) and hi == pytest.approx(0.08452, abs=1e-4)
    assert wilson(0, 20)[0] == 0.0 and wilson(20, 20)[1] == 1.0


def test_wilson_never_leaves_zero_to_one_where_the_normal_formula_would():
    p = 1 / 30
    normal_lo = p - 1.96 * math.sqrt(p * (1 - p) / 30)
    assert normal_lo < 0 < wilson(1, 30)[0]


def test_weights_are_the_standard_two_to_the_three_contrasts():
    w = weights("main:count")
    assert sum(w.values()) == 0 and w["high-rich-strict"] == 0.25
    i = weights("interaction:richness:count")
    assert i["high-rich-loose"] == 0.5 and i["low-rich-loose"] == -0.5
    at = weights("at:richness:count:high")
    assert at["low-rich-loose"] == 0 and at["high-rich-loose"] == 0.5


def _row(rate):
    return {c.name: rate(c) for c in CELLS}


def test_contrasts_recover_a_planted_main_effect_and_interaction():
    row = _row(lambda c: 0.1 + 0.2 * (c.count == "high")
               - 0.15 * (c.count == "high" and c.richness == "rich"))
    assert contrast(row, "at:richness:count:low") == pytest.approx(0.0)
    assert contrast(row, "at:richness:count:high") == pytest.approx(-0.15)
    assert contrast(row, "interaction:richness:count") == pytest.approx(-0.15)
    assert contrast(row, "main:count") == pytest.approx(0.2 - 0.075)
    assert contrast(row, "main:strictness") == pytest.approx(0.0)


def test_the_bootstrap_resamples_scenarios_and_refuses_too_few():
    units = [float(i % 2) for i in range(24)]
    r = cluster_bootstrap(units, lambda xs: sum(xs) / len(xs), iterations=500, seed=1)
    assert r["lo"] < 0.5 < r["hi"] and r["n_scenarios"] == 24
    with pytest.raises(ValueError, match="at least 20"):
        cluster_bootstrap(units[:19], sum)


def test_clustering_widens_the_interval_relative_to_pretending_calls_are_independent():
    """24 scenarios that each fail all 10 repetitions or none: 240 calls, but
    only 24 independent facts. The scenario bootstrap must be about as wide as
    a 24-sample interval, far wider than a 240-call Wilson interval."""
    rows = [1.0] * 6 + [0.0] * 18
    r = cluster_bootstrap(rows, lambda xs: sum(xs) / len(xs), iterations=2000, seed=2)
    w_lo, w_hi = wilson(60, 240)
    assert (r["hi"] - r["lo"]) > 1.8 * (w_hi - w_lo)


def test_one_sided_p_values():
    r = cluster_bootstrap([1.0] * 25, lambda xs: sum(xs) / len(xs), iterations=99, seed=0)
    assert r["p_le_0"] == pytest.approx(1 / 100) and r["p_ge_0"] == 1.0


def test_holm_steps_down_and_stops_at_the_first_failure():
    assert holm({"a": 0.01, "b": 0.02, "c": 0.04}, 0.05) == {"a": True, "b": True, "c": True}
    assert holm({"a": 0.01, "b": 0.03, "c": 0.04}, 0.05) == {"a": True, "b": False, "c": False}
    assert holm({"a": 0.2}, 0.05) == {"a": False}


def _outcomes(cats_by_block):
    return {"s1": {c.name: list(enumerate(cats_by_block)) for c in CELLS}}


def test_rates_flips_and_halves():
    o = _outcomes(["CORRECT", "WRONG_TOOL", "CORRECT", "CORRECT"])
    assert rate_rows(o, ("WRONG_TOOL",))[0]["low-terse-loose"] == 0.25
    assert ever_flip_rows(o) == [1.0]
    assert half_rows(o, ("WRONG_TOOL",))[0]["low-terse-loose"] == pytest.approx(-0.5)
    with pytest.raises(ValueError, match="no graded repetitions"):
        rate_rows({"s1": {}}, ("WRONG_TOOL",))
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_toolcall_effects.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'toolcall.effects'`.

- [ ] **Step 3: Write the implementation**

Create `toolcall/effects.py`:

```python
"""Rates, effects and their intervals, clustered on scenario (amendment §4f).

- A per-scenario rate is the share of one scenario's graded repetitions, in
  one cell, that land in a set of categories. Wilson intervals are used for
  these, and only these, because there the repetitions are the unit.
- A cell rate averages per-scenario rates, each scenario weighted equally.
- Effects are risk differences in percentage points, the 2^3 contrasts:
  a main effect is the high level minus the low, averaged over the other two
  factors; a two-way interaction is a factor's effect at the other factor's
  high level minus its effect at the low level.
- Every interval is a paired percentile bootstrap over scenarios: each draw
  resamples whole scenarios, so a scenario that fails for one reason in every
  repetition counts once, not N times. That is the August design's
  unit-of-variation correction.

`harness/stats.py` is medians-only by design. These estimators are new, so
they live here; the percentile endpoints, the iteration checks and the
bootstrap floor are the harness's own, imported, not copied.
"""

import math
import random
from collections import defaultdict

from harness.stats import (
    MIN_BOOTSTRAP_SAMPLES,
    _check_iterations_and_alpha,
    _percentile_interval,
)
from toolcall.formulation import CELLS
from toolcall.grader import CATEGORIES, EXCLUDED

FACTORS = ("count", "richness", "strictness")


def wilson(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n <= 0 or not 0 <= k <= n:
        raise ValueError(f"wilson needs 0 <= k <= n and n > 0, got k={k}, n={n}")
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def graded_outcomes(records) -> dict[str, dict[str, list[tuple[int, str]]]]:
    """{scenario: {cell: [(block_index, category), ...]}}, excluded outcomes removed."""
    out: dict = defaultdict(lambda: defaultdict(list))
    for r in records:
        cat = r.grade["category"]
        if cat in EXCLUDED:
            continue
        if cat not in CATEGORIES:
            raise ValueError(f"unknown category {cat!r} in run {r.run_index}")
        out[r.scenario_id][r.cell].append((r.block_index, cat))
    return {s: dict(c) for s, c in out.items()}


def rate_rows(outcomes, categories, cells=CELLS, scenarios=None) -> list[dict[str, float]]:
    """One row per scenario: {cell name: rate of `categories`}. Every scenario
    must have graded repetitions in every cell, or the contrast is undefined."""
    cats = set(categories)
    rows = []
    for sid in sorted(scenarios if scenarios is not None else outcomes):
        row = {}
        for cell in cells:
            reps = outcomes.get(sid, {}).get(cell.name, [])
            if not reps:
                raise ValueError(f"scenario {sid} has no graded repetitions in {cell.name}")
            row[cell.name] = sum(c in cats for _, c in reps) / len(reps)
        rows.append(row)
    return rows


def weights(estimand: str) -> dict[str, float]:
    """Cell weights for `main:<factor>`, `interaction:<f>:<g>`, or
    `at:<f>:<g>:<low|high>` (the effect of f with g held at one level)."""
    parts = estimand.split(":")
    w = {}
    for cell in CELLS:
        s = cell.signs
        if parts[0] == "main":
            w[cell.name] = s[parts[1]] / 4
        elif parts[0] == "interaction":
            w[cell.name] = s[parts[1]] * s[parts[2]] / 2
        elif parts[0] == "at":
            level = 1 if parts[3] in ("high", "rich", "strict") else -1
            w[cell.name] = s[parts[1]] / 2 if s[parts[2]] == level else 0.0
        else:
            raise ValueError(f"unknown estimand {estimand!r}")
    return w


def contrast(row: dict[str, float], estimand: str) -> float:
    return sum(wt * row[cell] for cell, wt in weights(estimand).items())


def cluster_bootstrap(units: list, statistic, iterations: int = 10000, seed: int = 0,
                      alpha: float = 0.05) -> dict:
    """Percentile interval on `statistic(units)`, resampling whole units
    (scenarios) with replacement. Also returns one-sided bootstrap p-values,
    the share of draws at or beyond zero on each side, add-one smoothed."""
    _check_iterations_and_alpha(iterations, alpha)
    if len(units) < MIN_BOOTSTRAP_SAMPLES:
        raise ValueError(
            f"{len(units)} scenarios; a bootstrap over scenarios needs at least "
            f"{MIN_BOOTSTRAP_SAMPLES} (harness.stats.MIN_BOOTSTRAP_SAMPLES)"
        )
    rng = random.Random(seed)
    n = len(units)
    draws = [statistic([units[rng.randrange(n)] for _ in range(n)]) for _ in range(iterations)]
    lo, hi = _percentile_interval(draws, alpha)
    return {
        "point": statistic(units),
        "lo": lo,
        "hi": hi,
        "p_le_0": (sum(d <= 0 for d in draws) + 1) / (iterations + 1),
        "p_ge_0": (sum(d >= 0 for d in draws) + 1) / (iterations + 1),
        "n_scenarios": n,
        "iterations": iterations,
        "alpha": alpha,
    }


def average(xs) -> float:
    xs = list(xs)
    return sum(xs) / len(xs)


def effect(rows, estimand: str, **kw) -> dict:
    return cluster_bootstrap(rows, lambda rs: average(contrast(r, estimand) for r in rs), **kw)


def cell_rates(rows, **kw) -> dict[str, dict]:
    return {
        cell.name: cluster_bootstrap(rows, lambda rs, c=cell.name: average(r[c] for r in rs),
                                     **kw)
        for cell in CELLS
    }


def holm(pvalues: dict[str, float], alpha: float = 0.05) -> dict[str, bool]:
    """Holm's step-down procedure: reject in order of p until the first
    p > alpha / (m - rank); nothing after it is rejected."""
    order = sorted(pvalues, key=lambda k: pvalues[k])
    m = len(order)
    out = {k: False for k in pvalues}
    for rank, key in enumerate(order):
        if pvalues[key] > alpha / (m - rank):
            break
        out[key] = True
    return out


def ever_flip_rows(outcomes, scenarios=None) -> list[float]:
    """Per scenario: the share of its cells whose graded repetitions do not all
    land in one category. The Noise Floor Audit's measure (amendment §4f)."""
    rows = []
    for sid in sorted(scenarios if scenarios is not None else outcomes):
        cells = outcomes[sid]
        flips = [len({c for _, c in reps}) > 1 for reps in cells.values()]
        rows.append(sum(flips) / len(flips))
    return rows


def half_rows(outcomes, categories, scenarios=None) -> list[dict[str, float]]:
    """Per scenario and cell: the rate among even-numbered repetitions minus
    the rate among odd-numbered ones. The A/A contrast H5 compares against."""
    cats = set(categories)
    rows = []
    for sid in sorted(scenarios if scenarios is not None else outcomes):
        row = {}
        for cell in CELLS:
            reps = outcomes[sid][cell.name]
            even = [c for b, c in reps if b % 2 == 0]
            odd = [c for b, c in reps if b % 2 == 1]
            if not even or not odd:
                raise ValueError(f"{sid} {cell.name}: the A/A contrast needs both halves")
            row[cell.name] = (sum(c in cats for c in even) / len(even)
                              - sum(c in cats for c in odd) / len(odd))
        rows.append(row)
    return rows


def per_scenario_wilson(outcomes, categories, cell: str) -> list[dict]:
    cats = set(categories)
    out = []
    for sid in sorted(outcomes):
        reps = outcomes[sid][cell]
        k = sum(c in cats for _, c in reps)
        lo, hi = wilson(k, len(reps))
        out.append({"scenario": sid, "k": k, "n": len(reps), "rate": k / len(reps),
                    "lo": lo, "hi": hi})
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_toolcall_effects.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add toolcall/effects.py tests/test_toolcall_effects.py
git commit -m "feat: Wilson intervals, 2^3 contrasts, a scenario-clustered bootstrap and Holm's procedure"
```

---

## Task 9: Cost per successful call, and sizing N

- `costs.py`: cost per successful call from recorded usage, for one attempt and for a retry policy that walks each scenario's repetitions in order (amendment §4f). Where reruns are sticky, the retry policy costs more than c / (1 − f) says; the test shows it.
- `budget.py`: the ICC, effective sample size, and §4d's rule for N.

**Files:**
- Create: `toolcall/costs.py`
- Create: `toolcall/budget.py`
- Test: `tests/test_toolcall_costs_budget.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_toolcall_costs_budget.py`:

```python
from types import SimpleNamespace

import pytest

from toolcall.budget import Line, effective_n, icc, reps_for, table, total
from toolcall.costs import _retry, _single, break_even, cost_per_success
from toolcall.formulation import CELLS


def test_single_attempt_cost_is_spend_over_successes():
    reps = [(0, 1.0, False), (1, 1.0, True), (2, 1.0, True)]
    assert _single(reps) == (3.0, 2)


def test_the_retry_policy_stops_at_the_first_success_in_each_group():
    reps = [(0, 1.0, False), (1, 1.0, True), (2, 1.0, False),   # group 1: 2 spent, 1 win
            (3, 1.0, False), (4, 1.0, False), (5, 1.0, False),  # group 2: 3 spent, 0 wins
            (6, 1.0, True)]                                      # a partial group is dropped
    assert _retry(reps, 3) == (5.0, 1)


def _records(fail_scenarios: int, n_scen: int = 24, reps: int = 6):
    out = []
    for s in range(n_scen):
        for cell in CELLS:
            for b in range(reps):
                ok = s >= fail_scenarios
                out.append(SimpleNamespace(scenario_id=f"s{s:02d}", cell=cell.name,
                                           block_index=b, cost_usd=0.001,
                                           grade={"category": "CORRECT" if ok else "MISSING"}))
    return out


def test_persistent_failures_make_retrying_dearer_than_the_geometric_formula():
    costs = cost_per_success(_records(fail_scenarios=6), retry_cap=3, iterations=200, seed=1)
    cell = costs["low-terse-loose"]
    assert cell["failure_rate_pooled"] == pytest.approx(0.25)
    assert cell["geometric_usd_per_success"] == pytest.approx(0.001 / 0.75)
    assert cell["retry"]["point"] > cell["geometric_usd_per_success"]


def test_a_cell_with_no_successes_reports_unbounded_not_infinity():
    costs = cost_per_success(_records(fail_scenarios=24), retry_cap=3, iterations=50, seed=1)
    assert costs["low-terse-loose"]["single"]["point"] is None


def test_break_even_pairs_terse_with_rich_at_each_count_and_strictness():
    costs = cost_per_success(_records(fail_scenarios=6), retry_cap=3, iterations=50, seed=1)
    pairs = break_even(costs)
    assert {(p["terse"], p["rich"]) for p in pairs} == {
        ("low-terse-loose", "low-rich-loose"), ("low-terse-strict", "low-rich-strict"),
        ("high-terse-loose", "high-rich-loose"), ("high-terse-strict", "high-rich-strict")}


def test_icc_is_one_when_scenarios_never_vary_and_zero_when_they_do_not_cluster():
    assert icc([[1] * 5, [0] * 5, [1] * 5]) == 1.0
    assert icc([[1, 0] * 5, [0, 1] * 5, [1, 0] * 5]) == 0.0


def test_effective_n_and_the_rule_for_n():
    assert effective_n(30, 5, 0.9) == pytest.approx(32.6, abs=0.1)
    assert effective_n(30, 40, 0.9) == pytest.approx(33.2, abs=0.1)
    assert reps_for(0.9, 5, 20) == 5     # extra repetitions buy almost nothing
    assert reps_for(0.5, 5, 20) == 19
    assert reps_for(0.1, 5, 20) == 20    # capped
    assert reps_for(0.0, 5, 20) == 20


def test_the_budget_table_adds_up():
    lines = [Line("a", 100, 0.01), Line("b", 10, 0.5)]
    assert total(lines) == pytest.approx(6.0)
    assert "**6.00**" in table(lines) and "7.50" in table(lines)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_toolcall_costs_budget.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'toolcall.costs'`.

- [ ] **Step 3: Write the implementation**

Create `toolcall/costs.py`:

```python
"""Cost per successful call, and when a richer formulation pays for itself
(August §5, "business framing"; amendment §4f).

Two policies, both computed from recorded calls and their own usage:

- single attempt: every graded call's cost, divided by the CORRECT ones.
- retry until success, up to `retry_cap` attempts: each scenario's repetitions,
  in their recorded order (block index), are cut into consecutive groups of
  `retry_cap`; a group spends until its first CORRECT call, or all of it.

The second is why this is computed from data and not from c / (1 - f): that
formula assumes a retry is an independent draw. With near-deterministic reruns
a scenario that fails tends to fail again, so the formula understates what a
retry policy costs. Both numbers are reported; the gap between them is the
unit-of-variation argument in dollars.

Calls excluded by grade (API_ERROR, REFUSED, TRUNCATED) are left out of both
and reported with the cell's counts.
"""

from collections import defaultdict

from toolcall.effects import cluster_bootstrap
from toolcall.formulation import CELLS
from toolcall.grader import EXCLUDED


def _units(records):
    """{scenario: {cell: [(block_index, cost_usd, correct)]}}, sorted by block."""
    out: dict = defaultdict(lambda: defaultdict(list))
    for r in records:
        if r.grade["category"] in EXCLUDED:
            continue
        out[r.scenario_id][r.cell].append(
            (r.block_index, r.cost_usd, r.grade["category"] == "CORRECT"))
    return {s: {c: sorted(v) for c, v in cells.items()} for s, cells in out.items()}


def _single(reps) -> tuple[float, int]:
    return sum(c for _, c, _ in reps), sum(ok for _, _, ok in reps)


def _retry(reps, cap: int) -> tuple[float, int]:
    spent, wins = 0.0, 0
    for start in range(0, len(reps) - cap + 1, cap):
        for _, cost, ok in reps[start:start + cap]:
            spent += cost
            if ok:
                wins += 1
                break
    return spent, wins


def _ratio(pairs) -> float:
    spent = sum(s for s, _ in pairs)
    wins = sum(w for _, w in pairs)
    return spent / wins if wins else float("inf")


def cost_per_success(records, retry_cap: int, iterations: int, seed: int,
                     alpha: float = 0.05) -> dict:
    units = _units(records)
    sids = sorted(units)
    out = {}
    for cell in CELLS:
        rows = [units[s][cell.name] for s in sids]
        reps = [r for row in rows for r in row]
        n_calls = len(reps)
        call_cost = sum(c for _, c, _ in reps) / n_calls
        failure = 1 - sum(ok for _, _, ok in reps) / n_calls
        entry = {"calls": n_calls, "usd_per_call": call_cost, "failure_rate_pooled": failure,
                 "geometric_usd_per_success": (call_cost / (1 - failure)
                                               if failure < 1 else None)}
        for name, policy in (("single", _single),
                             ("retry", lambda rs: _retry(rs, retry_cap))):
            r = cluster_bootstrap(rows, lambda rs, p=policy: _ratio([p(x) for x in rs]),
                                  iterations=iterations, seed=seed, alpha=alpha)
            entry[name] = {k: (None if isinstance(v, float) and v == float("inf") else v)
                           for k, v in r.items()}
        out[cell.name] = entry
    return out


def break_even(costs: dict) -> list[dict]:
    """For each pair differing only in richness: rich's per-call overhead and,
    under the geometric formula (labelled as such), the failure rate rich must
    reach to cost no more per success than terse."""
    out = []
    for cell in CELLS:
        if cell.richness != "terse":
            continue
        rich = f"{cell.count}-rich-{cell.strictness}"
        t, r = costs[cell.name], costs[rich]
        overhead = r["usd_per_call"] / t["usd_per_call"] - 1
        required = 1 - (r["usd_per_call"] / t["usd_per_call"]) * (1 - t["failure_rate_pooled"])
        out.append({
            "terse": cell.name, "rich": rich,
            "overhead_per_call": overhead,
            "terse_failure_rate": t["failure_rate_pooled"],
            "rich_failure_rate": r["failure_rate_pooled"],
            "required_rich_failure_rate_geometric": required,
            "pays_geometric": r["failure_rate_pooled"] <= required,
            "pays_measured_retry": (
                r["retry"]["point"] is not None and t["retry"]["point"] is not None
                and r["retry"]["point"] <= t["retry"]["point"]
            ),
        })
    return out
```

Create `toolcall/budget.py`:

```python
"""Sizing S and N from the pilot, and the cost of the campaign (amendment §4d, §8).

The effective sample size of S scenarios x N repetitions with intra-scenario
correlation rho is S*N / (1 + (N - 1)*rho). It approaches S/rho as N grows, so
past some N another repetition buys almost nothing. The rule: the smallest N
that reaches 95% of that limit, between the floor and the cap, then lowered to
fit the approved budget, never below the floor. S is every included scenario,
because under a high rho the information is in S.
"""

import math
from dataclasses import dataclass

TARGET_FRACTION = 0.95


def icc(groups: list[list[int]]) -> float:
    """One-way ANOVA estimator of the intra-class correlation for 0/1
    outcomes, one group per scenario. Unequal group sizes use the usual n0
    correction. Clamped to [0, 1]: a negative estimate means no clustering."""
    groups = [g for g in groups if g]
    k = len(groups)
    if k < 2:
        raise ValueError("an ICC needs at least two scenarios")
    sizes = [len(g) for g in groups]
    total = sum(sizes)
    grand = sum(sum(g) for g in groups) / total
    ssb = sum(n * (sum(g) / n - grand) ** 2 for g, n in zip(groups, sizes))
    ssw = sum(sum((x - sum(g) / len(g)) ** 2 for x in g) for g in groups)
    msb = ssb / (k - 1)
    msw = ssw / (total - k) if total > k else 0.0
    n0 = (total - sum(n * n for n in sizes) / total) / (k - 1)
    denom = msb + (n0 - 1) * msw
    if denom == 0:
        return 1.0  # every repetition of every scenario identical: fully clustered
    return min(1.0, max(0.0, (msb - msw) / denom))


def effective_n(s: int, n: int, rho: float) -> float:
    return s * n / (1 + (n - 1) * rho)


def reps_for(rho: float, n_floor: int, n_cap: int) -> int:
    """Smallest N with N*rho / (1 + (N-1)*rho) >= TARGET_FRACTION, clamped."""
    if rho <= 0:
        return n_cap
    need = TARGET_FRACTION * (1 - rho) / ((1 - TARGET_FRACTION) * rho)
    return max(n_floor, min(n_cap, math.ceil(need)))


@dataclass(frozen=True)
class Line:
    name: str
    calls: int
    usd_per_call: float

    @property
    def usd(self) -> float:
        return self.calls * self.usd_per_call


def total(lines: list[Line]) -> float:
    return sum(line.usd for line in lines)


def table(lines: list[Line], contingency: float = 0.25) -> str:
    rows = ["| component | calls | USD per call | USD |", "|---|---|---|---|"]
    rows += [f"| {x.name} | {x.calls:,} | {x.usd_per_call:.5f} | {x.usd:.2f} |" for x in lines]
    t = total(lines)
    rows.append(f"| **total** | | | **{t:.2f}** |")
    rows.append(f"| with {contingency:.0%} contingency | | | {t * (1 + contingency):.2f} |")
    return "\n".join(rows)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_toolcall_costs_budget.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add toolcall/costs.py toolcall/budget.py tests/test_toolcall_costs_budget.py
git commit -m "feat: cost per successful call from recorded order, break-even, the ICC and the rule for N"
```

---

## Task 10: The pre-registration record and the pilot's selection

`prereg.py` holds every pre-registered value as one validated object, in amendment §5's two steps; plan 2 fills it in `toolcall/prereg_values.py`. `selection.py` turns the pilot into the published selection table, rho, and step 2's whole proposal, including a check that the spend guard's input bound held on every pilot call (§14 item 5). `step2_proposal` is tested in Task 13, which can produce a pilot.

**Files:**
- Create: `toolcall/prereg.py`
- Create: `toolcall/selection.py`
- Test: `tests/test_toolcall_prereg.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_toolcall_prereg.py`:

```python
from dataclasses import fields
from types import SimpleNamespace

import pytest

from tests.a3_examples import example_prereg, scenarios, synthetic_suite
from toolcall.prereg import prereg_table
from toolcall.selection import baseline_table, rho, table_markdown


def test_the_example_is_valid_and_step_two_starts_unset():
    p = example_prereg()
    assert not p.step2_complete
    with pytest.raises(ValueError, match="step 2 is not committed"):
        p.require_step2()


@pytest.mark.parametrize("kw, match", [
    ({"band": (0.9, 0.1)}, "band"),
    ({"n_floor": 1}, "A/A"),
    ({"s_floor": 10}, "bootstrap floor"),
    ({"normalizer_version": 2}, "grading rules changed"),
    ({"baseline_cell": "mid-terse-loose"}, "count"),
    ({"included": ("a",) * 30}, "duplicates"),
    ({"included": tuple(f"s{i}" for i in range(10))}, "below s_floor"),
    ({"reps": 3}, "outside"),
])
def test_invalid_values_are_refused(kw, match):
    with pytest.raises(ValueError, match=match):
        example_prereg(**kw)


def test_the_table_names_every_field():
    table = prereg_table(example_prereg())
    for f in fields(example_prereg()):
        assert f"| `{f.name}` |" in table


def _pilot(rates: dict[str, float], reps=10):
    out = []
    for sid, rate in rates.items():
        k = round(rate * reps)
        for b in range(reps):
            out.append(SimpleNamespace(scenario_id=sid, cell="low-terse-loose", run_index=b,
                                       grade={"category": "CORRECT" if b < k else "WRONG_TOOL"}))
    return out


def test_selection_keeps_the_band_and_lists_every_candidate_with_its_reason():
    scs = scenarios(synthetic_suite(3, 0))
    rates = {scs[0].id: 1.0, scs[1].id: 0.5, scs[2].id: 0.0}
    rows = baseline_table(_pilot(rates), scs, example_prereg())
    assert {r["scenario"]: r["include"] for r in rows} == {
        scs[0].id: False, scs[1].id: True, scs[2].id: False}
    reasons = {r["scenario"]: r["reason"] for r in rows}
    assert reasons[scs[0].id] == "at or near ceiling" and reasons[scs[2].id] == "at or near floor"
    md = table_markdown(rows)
    assert md.count("\n") == len(rows) + 1


def test_selection_refuses_pilot_runs_outside_the_baseline_cell():
    scs = scenarios(synthetic_suite(1, 0))
    bad = [SimpleNamespace(scenario_id=scs[0].id, cell="high-rich-strict", run_index=0,
                           grade={"category": "CORRECT"})]
    with pytest.raises(ValueError, match="not the baseline cell"):
        baseline_table(bad, scs, example_prereg())


def test_rho_from_the_pilot():
    recs = _pilot({"a": 1.0, "b": 0.0, "c": 1.0, "d": 0.0})
    assert rho(recs, {"a", "b", "c", "d"}) == 1.0
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_toolcall_prereg.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'toolcall.prereg'`.

- [ ] **Step 3: Write the implementation**

Create `toolcall/prereg.py`:

```python
"""The pre-registered values, as one validated record (amendment §5).

Two dated steps, as artifact 4 did. Step 1's fields are fixed before the pilot.
Step 2's fields (the `None` defaults below) are fixed after the pilot and
before any campaign call. `toolcall/prereg_values.py` holds the values and
`docs/experiment-a3.md` embeds `prereg_table`'s output; a test fails if the two
disagree, so the document a reader sees and the object the code runs on are
one thing.
"""

from dataclasses import dataclass, fields

from harness.stats import MIN_BOOTSTRAP_SAMPLES
from toolcall import NORMALIZER_VERSION
from toolcall.formulation import parse_cell
from toolcall.providers import ModelSettings


@dataclass(frozen=True)
class Preregistration:
    # --- step 1: before the pilot --------------------------------------
    primary: ModelSettings
    slice_models: tuple[ModelSettings, ...]
    baseline_cell: str
    band: tuple[float, float]  # inclusive bounds on the baseline correct rate
    pilot_reps: int
    pilot_cost_scenarios: int
    pilot_cost_reps: int
    delta2: float  # H2's equivalence margin, a proportion
    identical_retry_floor: float  # H4's floor rule (amendment §4e)
    n_floor: int
    n_cap: int
    s_floor: int
    alpha: float
    iterations: int
    bootstrap_seed: int
    schedule_seed: int
    retry_cap: int  # attempts in the cost-per-successful-call policy (§4f)
    turn_budget: int
    normalizer_version: int
    # --- step 2: after the pilot, before the campaign ---------------------
    included: tuple[str, ...] | None = None
    reps: int | None = None
    recovery_reps: int | None = None
    slice_reps: int | None = None
    approved_usd: float | None = None

    def __post_init__(self) -> None:
        parse_cell(self.baseline_cell)
        lo, hi = self.band
        if not 0.0 <= lo < hi <= 1.0:
            raise ValueError(f"band must satisfy 0 <= lo < hi <= 1, got {self.band}")
        for name in ("pilot_reps", "pilot_cost_scenarios", "pilot_cost_reps", "n_floor",
                     "n_cap", "s_floor", "iterations", "retry_cap", "turn_budget"):
            v = getattr(self, name)
            if not isinstance(v, int) or v <= 0:
                raise ValueError(f"{name} must be a positive int, got {v!r}")
        if self.n_floor < 2:
            raise ValueError("n_floor must be at least 2: H5's A/A contrast splits repetitions")
        if self.n_cap < self.n_floor:
            raise ValueError("n_cap must be at least n_floor")
        if self.s_floor < MIN_BOOTSTRAP_SAMPLES:
            raise ValueError(f"s_floor is below the bootstrap floor {MIN_BOOTSTRAP_SAMPLES}")
        if not 0.0 < self.delta2 < 0.5 or not 0.0 < self.identical_retry_floor < 1.0:
            raise ValueError("delta2 and identical_retry_floor must be proportions")
        if not 0.0 < self.alpha < 1.0:
            raise ValueError("alpha must be in (0, 1)")
        if self.normalizer_version != NORMALIZER_VERSION:
            raise ValueError(
                f"pre-registered normalizer v{self.normalizer_version}, code is "
                f"v{NORMALIZER_VERSION}: grading rules changed after registration"
            )
        if self.included is not None:
            if len(self.included) < self.s_floor:
                raise ValueError(f"{len(self.included)} included scenarios, below s_floor")
            if len(set(self.included)) != len(self.included):
                raise ValueError("included has duplicates")
        if self.reps is not None and not self.n_floor <= self.reps <= self.n_cap:
            raise ValueError(f"reps {self.reps} outside [{self.n_floor}, {self.n_cap}]")
        for name in ("recovery_reps", "slice_reps"):
            v = getattr(self, name)
            if v is not None and v < self.n_floor:
                raise ValueError(f"{name} {v} is below n_floor")

    @property
    def step2_complete(self) -> bool:
        return all(getattr(self, f) is not None for f in STEP2)

    def require_step2(self) -> None:
        missing = [f for f in STEP2 if getattr(self, f) is None]
        if missing:
            raise ValueError(f"pre-registration step 2 is not committed: {missing} unset")


STEP2 = ("included", "reps", "recovery_reps", "slice_reps", "approved_usd")


def prereg_table(prereg: Preregistration) -> str:
    lines = ["| parameter | value |", "|---|---|"]
    for f in fields(prereg):
        value = getattr(prereg, f.name)
        if isinstance(value, ModelSettings):
            value = value.to_dict()
        elif f.name == "slice_models":
            value = tuple(m.to_dict() for m in value)
        lines.append(f"| `{f.name}` | `{value!r}` |")
    return "\n".join(lines)
```

Create `toolcall/selection.py`:

```python
"""The pilot's two outputs: which candidates are included, and rho (amendment §5).

Selection uses the baseline cell only, against a band fixed at pre-registration
step 1 (August §4's rule). Every candidate is listed with its rate and its
decision, and excluded candidates stay in the repository, flagged.
"""

from collections import defaultdict

from toolcall.budget import Line, icc, reps_for, table, total
from toolcall.effects import wilson
from toolcall.formulation import CELLS
from toolcall.grader import EXCLUDED
from toolcall.guard import bound_held
from toolcall.providers import ModelSettings


def baseline_table(pilot_records, scenarios, prereg) -> list[dict]:
    by: dict = defaultdict(list)
    for r in pilot_records:
        if r.cell != prereg.baseline_cell:
            raise ValueError(f"run {r.run_index} is in {r.cell}, not the baseline cell")
        if r.grade["category"] not in EXCLUDED:
            by[r.scenario_id].append(r.grade["category"] == "CORRECT")
    lo, hi = prereg.band
    out = []
    for s in sorted(scenarios, key=lambda s: s.id):
        reps = by.get(s.id, [])
        if not reps:
            out.append({"scenario": s.id, "n": 0, "correct": 0, "rate": None,
                        "include": False, "reason": "no graded pilot repetitions"})
            continue
        k = sum(reps)
        rate = k / len(reps)
        w_lo, w_hi = wilson(k, len(reps))
        include = lo <= rate <= hi
        reason = "inside the band" if include else (
            "at or near ceiling" if rate > hi else "at or near floor")
        out.append({"scenario": s.id, "n": len(reps), "correct": k, "rate": rate,
                    "wilson_lo": w_lo, "wilson_hi": w_hi, "include": include,
                    "reason": reason, "target": s.target_failure_mode})
    return out


def rho(pilot_records, included: set[str]) -> float:
    by: dict = defaultdict(list)
    for r in pilot_records:
        if r.scenario_id in included and r.grade["category"] not in EXCLUDED:
            by[r.scenario_id].append(int(r.grade["category"] == "CORRECT"))
    return icc(list(by.values()))


def table_markdown(rows: list[dict]) -> str:
    lines = ["| scenario | target | correct / n | rate | Wilson 95% | decision |",
             "|---|---|---|---|---|---|"]
    for r in rows:
        if r["rate"] is None:
            lines.append(f"| `{r['scenario']}` | | 0 / 0 | | | exclude: {r['reason']} |")
            continue
        lines.append(
            f"| `{r['scenario']}` | {r['target']} | {r['correct']} / {r['n']} | "
            f"{r['rate']:.2f} | {r['wilson_lo']:.2f}–{r['wilson_hi']:.2f} | "
            f"{'include' if r['include'] else 'exclude'}: {r['reason']} |")
    return "\n".join(lines)


def _usd_per_call(records) -> float:
    priced = [r.cost_usd for r in records if r.cost_usd is not None]
    if not priced:
        raise ValueError("no priced calls in this pilot store")
    return sum(priced) / len(priced)


def step2_proposal(pilot: dict, scenarios, prereg) -> dict:
    """Everything step 2 fixes, computed from the pilot's stores (amendment §5).

    The recovery and slice phases use the same N as the campaign: the same
    rho argument applies to their repetitions.

    `pilot` holds the four pilot stores' records: "baseline", "cells" (all
    eight cells), "slice" ({model: records}) and "recovery" (conversations).
    Cost per call is measured, not assumed: per cell from "cells", per slice
    model from "slice", per conversation from "recovery". The exploratory slice
    is priced at the dearest cell, since the best cell is not known yet."""
    rows = baseline_table(pilot["baseline"], scenarios, prereg)
    included = tuple(r["scenario"] for r in rows if r["include"])
    singles = pilot["baseline"] + pilot["cells"] + [r for v in pilot["slice"].values() for r in v]
    misses = [r.run_index for r in singles if r.usage and not bound_held(
        ModelSettings(**r.settings), r.request, r.usage)]
    if misses:
        raise ValueError(f"the spend guard's input bound failed on {len(misses)} pilot calls; "
                         "raise toolcall.guard.CHARS_PER_TOKEN_BOUND's margin before any "
                         "campaign spend")
    if len(included) < prereg.s_floor:
        return {"candidates": len(rows), "included": included,
                "selection_table": table_markdown(rows), "enough_scenarios": False}
    by_id = {s.id: s for s in scenarios}
    r = rho(pilot["baseline"], set(included))
    n = reps_for(r, prereg.n_floor, prereg.n_cap)
    cell_cost = {c.name: _usd_per_call([x for x in pilot["cells"] if x.cell == c.name])
                 for c in CELLS}
    per_cell = sum(cell_cost.values()) / len(cell_cost)
    rec_conv = sum(x.cost_usd for x in pilot["recovery"]) / len(pilot["recovery"])
    n_rec = sum(1 for i in included if by_id[i].recovery)
    s = len(included)
    lines = [
        Line(f"campaign: 8 cells x {s} scenarios x {n}", 8 * s * n, per_cell),
        Line(f"recovery: 2 cells x 2 formats x {n_rec} scenarios x {n}",
             2 * 2 * n_rec * n, rec_conv),
        Line(f"exploratory: 1 cell x {s} x {n}", s * n, max(cell_cost.values())),
    ]
    for model, recs in sorted(pilot["slice"].items()):
        lines.append(Line(f"slice {model}: 2 cells x {s} x {n}", 2 * s * n,
                          _usd_per_call(recs)))
    return {
        "candidates": len(rows), "included": included, "rho": r, "reps": n,
        "recovery_scenarios": n_rec, "recovery_reps": n, "slice_reps": n,
        "usd_per_call_by_cell": cell_cost,
        "usd_per_recovery_conversation": rec_conv, "estimate_usd": total(lines),
        "budget_table": table(lines), "selection_table": table_markdown(rows),
        "enough_scenarios": True,
        "enough_recovery_scenarios": n_rec >= 20,
    }
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_toolcall_prereg.py -v`
Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
git add toolcall/prereg.py toolcall/selection.py tests/test_toolcall_prereg.py
git commit -m "feat: the pre-registration record, and selection, rho and step 2 from the pilot"
```

---

## Task 11: The hypotheses and the analysis

`hypotheses.py` is amendment §2's H1–H5, each one estimand, one direction and one p-value, with Holm across the testable ones and H4's floor rule. `analysis.py` is everything the post reports, as plain JSON.

The test runs the whole offline path on the stub, 66 scenarios × 8 cells × 8 repetitions plus recovery, and checks the analysis recovers the planted effects. It also checks the analysis is byte-for-byte deterministic. It takes about 25 seconds.

**Files:**
- Create: `toolcall/hypotheses.py`
- Create: `toolcall/analysis.py`
- Test: `tests/test_toolcall_end_to_end.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_toolcall_end_to_end.py`:

```python
"""The whole offline path on the stub, which has known effects planted in it:
campaign, recovery, analysis. The analysis must recover what was put in.

Planted (toolcall/stub.py): tool count raises WRONG_TOOL, rich descriptions
cut it only at high count, strict schemas cut MALFORMED and WRONG_PARAMS and
leave WRONG_TOOL alone, and opaque errors bring more identical retries.
"""

import json

import pytest

from harness.store import JsonlStore
from tests.a3_examples import example_prereg, library, scenarios, synthetic_suite
from toolcall import campaign
from toolcall.analysis import analyse
from toolcall.formulation import CELLS, parse_cell
from toolcall.providers import ScriptedClient
from toolcall.records import CallRecord, RecoveryRecord
from toolcall.stub import StubModel


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("e2e")
    lib = library()
    scs = scenarios(synthetic_suite(60, 6))
    prereg = example_prereg(included=tuple(s.id for s in scs), reps=8, recovery_reps=5,
                            slice_reps=5, approved_usd=1.0, iterations=400)
    client = ScriptedClient(prereg.primary, StubModel(lib, scs, seed=5, stickiness=0.5))
    calls = JsonlStore(tmp / "campaign.jsonl", CallRecord)
    campaign.single_turn(campaign.schedule(CELLS, scs, prereg.reps, 1), client, scs, lib,
                         calls, phase="campaign")
    rec_scs = [s for s in scs if s.recovery]
    recs = JsonlStore(tmp / "recovery.jsonl", RecoveryRecord)
    cells = [parse_cell("low-terse-loose"), parse_cell("high-rich-strict")]
    campaign.recovery_runs(campaign.schedule(cells, rec_scs, prereg.recovery_reps, 2,
                                             formats=["actionable", "opaque"]),
                           client, rec_scs, lib, recs)
    return calls.read_all(), recs.read_all(), scs, prereg


@pytest.fixture(scope="module")
def analysis(run):
    calls, recs, scs, prereg = run
    return analyse(calls, recs, scs, prereg)


def test_count_raises_wrong_tool(analysis):
    e = analysis["effects"]["WRONG_TOOL"]["main:count"]
    assert e["lo"] > 0


def test_richness_matters_at_high_count_and_little_at_low(analysis):
    eff = analysis["effects"]["WRONG_TOOL"]
    assert eff["at:richness:count:high"]["hi"] < 0
    assert eff["at:richness:count:low"]["lo"] < 0 < eff["at:richness:count:low"]["hi"]


def test_strictness_cuts_malformed_and_wrong_params_and_not_wrong_tool(analysis):
    assert analysis["effects"]["MALFORMED+WRONG_PARAMS"]["main:strictness"]["hi"] < 0
    s = analysis["effects"]["WRONG_TOOL"]["main:strictness"]
    assert s["lo"] < 0 < s["hi"]


def test_h4_finds_more_identical_retries_after_opaque_errors(analysis):
    h4 = analysis["hypotheses"]["H4"]
    assert h4["testable"] and h4["lo"] > 0 and h4["verdict"] == "supported"


def test_every_hypothesis_has_a_verdict_and_holm_was_applied(analysis):
    for h in analysis["hypotheses"].values():
        assert h["verdict"] in ("supported", "not supported", "not testable")
    assert all("holm_rejects" in h for h in analysis["hypotheses"].values()
               if h["verdict"] != "not testable")


def test_the_analysis_is_plain_json_and_deterministic(run, analysis):
    calls, recs, scs, prereg = run
    again = analyse(calls, recs, scs, prereg)
    assert json.dumps(analysis, sort_keys=True) == json.dumps(again, sort_keys=True)


def test_counts_add_up(run, analysis):
    calls = run[0]
    assert sum(c["calls"] for c in analysis["counts"].values()) == len(calls)


def test_the_retry_policy_costs_more_than_the_independence_formula_says(analysis):
    """Sticky repetitions: a failing scenario fails again, so retrying is
    worse than c / (1 - f) assumes (amendment §4f). Checked on the worst cell."""
    worst = analysis["cost"][analysis["ranked_cells"]["worst"]]
    assert worst["retry"]["point"] > worst["geometric_usd_per_success"]


def test_excluded_scenarios_are_left_out(run):
    calls, recs, scs, _ = run
    keep = tuple(s.id for s in scs[:40])
    a = analyse(calls, recs, scs, example_prereg(included=keep, reps=8, recovery_reps=5,
                                                  slice_reps=5, approved_usd=1.0,
                                                  iterations=100))
    assert a["S"] == 40
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_toolcall_end_to_end.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'toolcall.analysis'`.

- [ ] **Step 3: Write the implementation**

Create `toolcall/hypotheses.py`:

```python
"""H1-H5 as amended (amendment §2), each one estimand, one direction and one
p-value, with Holm's correction across the testable ones (§4f).

Failure rate is the share of graded repetitions not CORRECT. Every effect is a
risk difference on that scale, and every p-value is a one-sided cluster-
bootstrap p-value: the share of draws on the wrong side of zero.

- H1: interaction(richness, count) on failure rate < 0.
- H2: main(strictness) on MALFORMED + WRONG_PARAMS < 0, and main(strictness)
  on WRONG_TOOL with its 90% interval inside +/- delta2. Holm uses the first
  part's p-value; H2 is supported only if Holm rejects it and the equivalence
  part also passes.
- H3: main(count) on WRONG_TOOL > 0, and larger than |main(richness)| and
  |main(strictness)| on WRONG_TOOL. An intersection-union test: its p-value is
  the largest of the three one-sided p-values.
- H4: identical-retry rate, opaque minus actionable, > 0, over persistent error
  kinds and injected conversations, per scenario averaged over the recovery
  cells. Not testable if the opaque rate's point estimate is under the floor,
  or if fewer scenarios than the bootstrap floor have both formats.
- H5: |main(count) on failure rate| minus |the same contrast on the A/A rows|
  > 0.
"""

from collections import defaultdict

from harness.stats import MIN_BOOTSTRAP_SAMPLES
from toolcall.effects import (
    average,
    cluster_bootstrap,
    contrast,
    half_rows,
    holm,
    rate_rows,
)
from toolcall.grader import FAILURES
from toolcall.scenarios import PERSISTENT_KINDS


def _kw(prereg) -> dict:
    return {"iterations": prereg.iterations, "seed": prereg.bootstrap_seed,
            "alpha": prereg.alpha}


def _h1(outcomes, prereg) -> dict:
    rows = rate_rows(outcomes, FAILURES)
    r = cluster_bootstrap(rows, lambda rs: average(
        contrast(x, "interaction:richness:count") for x in rs), **_kw(prereg))
    return {"estimand": "interaction(richness, count) on failure rate", "direction": "< 0",
            **r, "p": r["p_ge_0"]}


def _h2(outcomes, prereg) -> dict:
    rows = rate_rows(outcomes, ("MALFORMED", "WRONG_PARAMS"))
    a = cluster_bootstrap(rows, lambda rs: average(
        contrast(x, "main:strictness") for x in rs), **_kw(prereg))
    wt = rate_rows(outcomes, ("WRONG_TOOL",))
    kw = {**_kw(prereg), "alpha": 2 * prereg.alpha}  # a 90% interval: two one-sided tests
    b = cluster_bootstrap(wt, lambda rs: average(contrast(x, "main:strictness") for x in rs),
                          **kw)
    equivalent = -prereg.delta2 < b["lo"] and b["hi"] < prereg.delta2
    return {"estimand": "main(strictness) on MALFORMED + WRONG_PARAMS", "direction": "< 0",
            **a, "p": a["p_le_0"],
            "equivalence": {"estimand": "main(strictness) on WRONG_TOOL",
                            "margin": prereg.delta2, **b, "passes": equivalent}}


def _h3(outcomes, prereg) -> dict:
    rows = rate_rows(outcomes, ("WRONG_TOOL",))
    kw = _kw(prereg)

    def stat(name):
        def f(rs):
            t = average(contrast(x, "main:count") for x in rs)
            if name == "count":
                return t
            other = average(contrast(x, f"main:{name}") for x in rs)
            return t - abs(other)
        return f

    parts = {name: cluster_bootstrap(rows, stat(name), **kw)
             for name in ("count", "richness", "strictness")}
    p = max(part["p_le_0"] for part in parts.values())
    return {"estimand": "main(count) on WRONG_TOOL, and its margin over the other two",
            "direction": "> 0", **parts["count"], "p": p,
            "margins": {"over_richness": parts["richness"],
                        "over_strictness": parts["strictness"]}}


def _h4(recovery_records, prereg) -> dict:
    by: dict = defaultdict(lambda: defaultdict(list))
    for r in recovery_records:
        if r.excluded or not r.injected or r.error_kind not in PERSISTENT_KINDS:
            continue
        if r.identical_retry is None:
            continue
        by[r.scenario_id][r.fmt].append(bool(r.identical_retry))
    units = [
        (sum(v["opaque"]) / len(v["opaque"]), sum(v["actionable"]) / len(v["actionable"]))
        for _, v in sorted(by.items())
        if v.get("opaque") and v.get("actionable")
    ]
    base = {"estimand": "identical-retry rate, opaque minus actionable", "direction": "> 0",
            "n_scenarios": len(units), "floor": prereg.identical_retry_floor}
    if len(units) < MIN_BOOTSTRAP_SAMPLES:
        return {**base, "testable": False,
                "reason": f"{len(units)} scenarios with both formats; the bootstrap floor is "
                          f"{MIN_BOOTSTRAP_SAMPLES}"}
    opaque = average(o for o, _ in units)
    if opaque < prereg.identical_retry_floor:
        return {**base, "testable": False, "opaque_rate": opaque,
                "reason": f"opaque identical-retry rate {opaque:.3f} is below the floor"}
    r = cluster_bootstrap(units, lambda us: average(o - a for o, a in us), **_kw(prereg))
    return {**base, **r, "testable": True, "opaque_rate": opaque, "p": r["p_le_0"]}


def _h5(outcomes, prereg) -> dict:
    rows = rate_rows(outcomes, FAILURES)
    aa = half_rows(outcomes, FAILURES)
    pairs = list(zip(rows, aa))

    def stat(ps):
        t = average(contrast(r, "main:count") for r, _ in ps)
        a = average(contrast(h, "main:count") for _, h in ps)
        return abs(t) - abs(a)

    r = cluster_bootstrap(pairs, stat, **_kw(prereg))
    return {"estimand": "|main(count) on failure| minus |the A/A contrast|",
            "direction": "> 0", **r, "p": r["p_le_0"]}


def evaluate(outcomes, recovery_records, prereg) -> dict:
    out = {"H1": _h1(outcomes, prereg), "H2": _h2(outcomes, prereg),
           "H3": _h3(outcomes, prereg), "H4": _h4(recovery_records, prereg),
           "H5": _h5(outcomes, prereg)}
    testable = {k: v["p"] for k, v in out.items() if v.get("testable", True)}
    rejected = holm(testable, prereg.alpha)
    for key, h in out.items():
        if key not in testable:
            h["verdict"] = "not testable"
            continue
        h["holm_rejects"] = rejected[key]
        supported = rejected[key] and (key != "H2" or h["equivalence"]["passes"])
        h["verdict"] = "supported" if supported else "not supported"
    return out
```

Create `toolcall/analysis.py`:

```python
"""Everything the post reports, as one JSON-shaped dict.

The figures and the post's numbers block read this and nothing else, so a
number in the post is a number in `data/a3/analysis.json`, and tests fail if
either drifts from a fresh run of this function.
"""

from collections import Counter, defaultdict

from harness.stats import MIN_BOOTSTRAP_SAMPLES
from toolcall import NORMALIZER_VERSION, SCHEMA_VERSION
from toolcall.costs import break_even, cost_per_success
from toolcall.effects import (
    average,
    cell_rates,
    cluster_bootstrap,
    effect,
    ever_flip_rows,
    graded_outcomes,
    rate_rows,
)
from toolcall.formulation import CELLS, parse_cell
from toolcall.grader import CATEGORIES, EXCLUDED, FAILURES
from toolcall.hypotheses import evaluate
from toolcall.normalize import RULES
from toolcall.scenarios import PERSISTENT_KINDS

ESTIMANDS = (
    "main:count", "main:richness", "main:strictness",
    "interaction:richness:count", "interaction:strictness:count",
    "interaction:strictness:richness",
    "at:richness:count:low", "at:richness:count:high",
)


def _kw(prereg) -> dict:
    return {"iterations": prereg.iterations, "seed": prereg.bootstrap_seed,
            "alpha": prereg.alpha}


def counts_by_cell(records) -> dict:
    out: dict = {}
    for cell in CELLS:
        rs = [r for r in records if r.cell == cell.name]
        c = Counter(r.grade["category"] for r in rs)
        out[cell.name] = {
            **{k: c.get(k, 0) for k in CATEGORIES + EXCLUDED},
            "calls": len(rs),
            "multiple_calls": sum(r.grade["multiple_calls"] for r in rs),
            "text_looks_like_call": sum(r.grade["text_looks_like_call"] for r in rs),
            "excluded_share": (sum(c.get(k, 0) for k in EXCLUDED) / len(rs)) if rs else None,
        }
    return out


def ranked_cells(records, prereg) -> dict:
    """Best and worst cells by failure-rate point estimate: the pre-registered
    rule that picks the recovery, slice and exploratory cells (amendment §4e)."""
    rows = rate_rows(graded_outcomes(records), FAILURES)
    points = {c.name: average(r[c.name] for r in rows) for c in CELLS}
    order = sorted(points, key=lambda k: (points[k], k))
    return {"best": order[0], "worst": order[-1], "failure_rate": points}


def _two_cell(records, cells: tuple[str, str], prereg) -> dict:
    outcomes = graded_outcomes(records)
    formulations = [parse_cell(c) for c in cells]
    rows = rate_rows(outcomes, FAILURES, cells=formulations)
    kw = _kw(prereg)
    out = {c: cluster_bootstrap(rows, lambda rs, c=c: average(r[c] for r in rs), **kw)
           for c in cells}
    out["difference"] = cluster_bootstrap(
        rows, lambda rs: average(r[cells[1]] - r[cells[0]] for r in rs), **kw)
    out["cells"] = list(cells)
    return out


def _marginal(failure_rows, prereg) -> dict:
    """Failure rate at each (count, richness) pair, averaged over strictness:
    the four points of the interaction figure, each with its interval."""
    out = {}
    for count in ("low", "high"):
        for richness in ("terse", "rich"):
            cells = [f"{count}-{richness}-{s}" for s in ("loose", "strict")]
            out[f"{count}-{richness}"] = cluster_bootstrap(
                failure_rows,
                lambda rs, cs=cells: average(average(r[c] for c in cs) for r in rs),
                **_kw(prereg))
    return out


def _identical_retry_ci(records, fmt, prereg):
    """Per-scenario identical-retry rates over persistent kinds, bootstrapped
    over scenarios; None when too few scenarios for the bootstrap floor."""
    by: dict = defaultdict(list)
    for r in records:
        if (r.fmt == fmt and r.injected and not r.excluded
                and r.error_kind in PERSISTENT_KINDS and r.identical_retry is not None):
            by[r.scenario_id].append(bool(r.identical_retry))
    units = [sum(v) / len(v) for _, v in sorted(by.items())]
    if len(units) < MIN_BOOTSTRAP_SAMPLES:
        return None
    return cluster_bootstrap(units, average, **_kw(prereg))


def _recovery(records, prereg) -> dict:
    by_fmt: dict = defaultdict(list)
    for r in records:
        by_fmt[r.fmt].append(r)
    out = {}
    for fmt, rs in sorted(by_fmt.items()):
        injected = [r for r in rs if r.injected and not r.excluded]
        n = len(injected)
        out[fmt] = {
            "conversations": len(rs),
            "injected": n,
            "not_injected": sum(not r.injected and not r.excluded for r in rs),
            "excluded": Counter(r.excluded for r in rs if r.excluded),
            "identical_retry": (sum(bool(r.identical_retry) for r in injected) / n) if n else None,
            "recovered": (sum(r.recovered for r in injected) / n) if n else None,
            "gave_up": (sum(r.gave_up for r in injected) / n) if n else None,
            "hallucinated_success": (sum(r.hallucinated_success for r in injected) / n)
            if n else None,
            "turns_to_recovery": Counter(r.turns_to_recovery for r in injected if r.recovered),
            "identical_retry_persistent": _identical_retry_ci(rs, fmt, prereg),
        }
    return out


def analyse(records, recovery_records, scenarios, prereg, *, slices=None,
            exploratory=None, spend=None) -> dict:
    """`records`: the primary model's campaign calls. `slices`: {model: calls}
    in the two slice cells. `exploratory`: constrained-decoding calls in the
    best cell, or None if the slice was cut."""
    included = set(prereg.included) if prereg.included else {s.id for s in scenarios}
    records = [r for r in records if r.scenario_id in included]
    outcomes = graded_outcomes(records)
    kw = _kw(prereg)
    failure_rows = rate_rows(outcomes, FAILURES)
    rates = {"failure": cell_rates(failure_rows, **kw)}
    for cat in FAILURES:
        rates[cat] = cell_rates(rate_rows(outcomes, (cat,)), **kw)
    effects = {
        target: {e: effect(rate_rows(outcomes, cats), e, **kw) for e in ESTIMANDS}
        for target, cats in (("failure", FAILURES), ("WRONG_TOOL", ("WRONG_TOOL",)),
                             ("MALFORMED+WRONG_PARAMS", ("MALFORMED", "WRONG_PARAMS")))
    }
    flips = ever_flip_rows(outcomes)
    distinct = Counter(len({c for _, c in reps}) for cells in outcomes.values()
                       for reps in cells.values())
    wrong_kind = Counter(r.grade.get("wrong_tool_kind") for r in records
                         if r.grade["category"] == "WRONG_TOOL")
    costs = cost_per_success(records, prereg.retry_cap, prereg.iterations,
                             prereg.bootstrap_seed, prereg.alpha)
    ranks = ranked_cells(records, prereg)
    out = {
        "schema_version": SCHEMA_VERSION,
        "normalizer_version": NORMALIZER_VERSION,
        "normalizer_rules": [list(r) for r in RULES],
        "model": prereg.primary.model,
        "settings": prereg.primary.to_dict(),
        "S": len(outcomes),
        "N": prereg.reps,
        "counts": counts_by_cell(records),
        "cell_rates": rates,
        "marginal_count_richness": _marginal(failure_rows, prereg),
        "effects": effects,
        "hypotheses": evaluate(outcomes, recovery_records, prereg),
        "flakiness": {
            "ever_flip": cluster_bootstrap(flips, average, **kw),
            "distinct_categories_per_unit": {str(k): v for k, v in sorted(distinct.items())},
            "units": sum(distinct.values()),
        },
        "wrong_tool_kind": {str(k): v for k, v in sorted(wrong_kind.items())},
        "ranked_cells": ranks,
        "recovery": _recovery(recovery_records, prereg),
        "cost": costs,
        "break_even": break_even(costs),
        "slice": {model: _two_cell(rs, (ranks["best"], ranks["worst"]), prereg)
                  for model, rs in sorted((slices or {}).items())},
        "exploratory_constrained": (
            {"cell": ranks["best"],
             "counts": Counter(r.grade["category"] for r in exploratory)}
            if exploratory else None),
        "spend": spend,
    }
    return _plain(out)


def _plain(x):
    """Counters and tuples to JSON types, so the dict round-trips byte-for-byte."""
    if isinstance(x, dict):
        return {str(k): _plain(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [_plain(v) for v in x]
    return x
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_toolcall_end_to_end.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add toolcall/hypotheses.py toolcall/analysis.py tests/test_toolcall_end_to_end.py
git commit -m "feat: H1-H5 with Holm and the floor rule, and the analysis as one JSON dict"
```

---

## Task 12: The four figures

August §8's four figures, drawn from the analysis only. Text sizes go through `harness.figure_guards.phone_pt`; the tests check every text artist clears the phone floor, N is in every title, value axes start at zero, and an empty input is refused. Looking at them is Task 15.

**Files:**
- Create: `toolcall/figures.py`
- Test: `tests/test_toolcall_figures.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_toolcall_figures.py`:

```python
"""The four figures, drawn from a stub analysis: they render, every text is
legible at phone width, N is on every figure, value axes start at zero, and an
empty input is refused. Looking at them is a separate, manual step (plan 1
Task 15); these tests guard what can be checked without eyes."""

import matplotlib.text
import pytest

from harness.figure_guards import MIN_PHONE_TEXT_PX, PHONE_WIDTH_PX
from harness.store import JsonlStore
from tests.a3_examples import example_prereg, library, scenarios, synthetic_suite
from toolcall import campaign
from toolcall.analysis import analyse
from toolcall.figures import FIGURES, WIDTH_IN
from toolcall.formulation import CELLS, parse_cell
from toolcall.providers import ScriptedClient
from toolcall.records import CallRecord, RecoveryRecord
from toolcall.stub import StubModel


@pytest.fixture(scope="module")
def analysis(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("fig")
    lib, scs = library(), scenarios(synthetic_suite(60, 6))
    prereg = example_prereg(included=tuple(s.id for s in scs), reps=6, recovery_reps=5,
                            slice_reps=5, approved_usd=1.0, iterations=200)
    client = ScriptedClient(prereg.primary, StubModel(lib, scs, seed=2))
    calls = JsonlStore(tmp / "c.jsonl", CallRecord)
    campaign.single_turn(campaign.schedule(CELLS, scs, 6, 1), client, scs, lib, calls,
                         phase="campaign")
    rec = [s for s in scs if s.recovery]
    recs = JsonlStore(tmp / "r.jsonl", RecoveryRecord)
    campaign.recovery_runs(campaign.schedule([parse_cell("low-terse-loose")], rec, 5, 2,
                                             formats=["actionable", "opaque"]),
                           client, rec, lib, recs)
    return analyse(calls.read_all(), recs.read_all(), scs, prereg)


@pytest.mark.parametrize("name", list(FIGURES))
def test_every_figure_writes_a_file(analysis, tmp_path, name):
    FIGURES[name](analysis, tmp_path / f"{name}.png")
    assert (tmp_path / f"{name}.png").stat().st_size > 10_000


@pytest.mark.parametrize("name", list(FIGURES))
def test_every_text_element_is_legible_at_phone_width(analysis, tmp_path, name):
    fig = FIGURES[name](analysis, tmp_path / f"{name}.png")
    for t in fig.findobj(matplotlib.text.Text):
        if t.get_text().strip():
            px = t.get_fontsize() * PHONE_WIDTH_PX / (72 * WIDTH_IN)
            assert px >= MIN_PHONE_TEXT_PX, (name, t.get_text(), px)


@pytest.mark.parametrize("name", list(FIGURES))
def test_the_sample_size_is_on_the_figure(analysis, tmp_path, name):
    fig = FIGURES[name](analysis, tmp_path / f"{name}.png")
    assert "scenarios" in fig._suptitle.get_text() or "units" in fig._suptitle.get_text()


@pytest.mark.parametrize("name", ["interaction", "flakiness", "identical_retry"])
def test_value_axes_start_at_zero(analysis, tmp_path, name):
    fig = FIGURES[name](analysis, tmp_path / f"{name}.png")
    assert fig.axes[0].get_ylim()[0] == 0


def test_empty_input_is_refused(analysis, tmp_path):
    empty = {**analysis, "recovery": {}}
    with pytest.raises(ValueError, match="empty"):
        FIGURES["identical_retry"](empty, tmp_path / "x.png")
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_toolcall_figures.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'toolcall.figures'`.

- [ ] **Step 3: Write the implementation**

Create `toolcall/figures.py`:

```python
"""The four figures (August §8), drawn from the analysis dict only.

Same constraints as every artifact: N stated, no truncated value axes,
intervals shown, legible on a phone. Text sizes go through
`harness.figure_guards.phone_pt`, and tests/test_toolcall_figures.py checks
every text artist clears the phone floor.
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from harness.figure_guards import phone_pt, validate_rows
from toolcall.formulation import CELLS
from toolcall.grader import CATEGORIES

PX_TITLE = 10.0
PX_TEXT = 8.4
WIDTH_IN = 8.0

CATEGORY_COLOR = {
    "CORRECT": "#d9d9d9",
    "MALFORMED": "#7a3e9d",
    "SPURIOUS": "#c88a2e",
    "MISSING": "#4a8a4a",
    "WRONG_TOOL": "#c04a4a",
    "WRONG_PARAMS": "#2f6fd0",
}
RICHNESS_COLOR = {"terse": "#c04a4a", "rich": "#2f6fd0"}
FORMAT_COLOR = {"actionable": "#2f6fd0", "opaque": "#c04a4a"}


def _pt(px: float) -> float:
    return phone_pt(px, WIDTH_IN)


def _style(ax) -> None:
    ax.tick_params(labelsize=_pt(PX_TEXT))
    ax.xaxis.label.set_size(_pt(PX_TEXT))
    ax.yaxis.label.set_size(_pt(PX_TEXT))
    ax.grid(alpha=0.3, axis="x" if ax.get_ylabel() == "" else "y")


def _n_line(analysis: dict) -> str:
    return f"{analysis['S']} scenarios × {analysis['N']} repetitions per cell"


def taxonomy(analysis: dict, out_path):
    """Figure 1: which failure mode moves, cell by cell. Bars are cell rates
    of each category; the whisker is the failure rate's 95% interval."""
    rates = analysis["cell_rates"]
    cells = [c.name for c in CELLS]
    validate_rows(cells)
    fig, ax = plt.subplots(figsize=(WIDTH_IN, 7.0))
    left = [0.0] * len(cells)
    for cat in ("CORRECT",) + tuple(c for c in CATEGORIES if c != "CORRECT"):
        if cat == "CORRECT":
            widths = [1 - rates["failure"][c]["point"] for c in cells]
        else:
            widths = [rates[cat][c]["point"] for c in cells]
        ax.barh(cells, widths, left=left, color=CATEGORY_COLOR[cat], label=cat.lower())
        left = [lo + w for lo, w in zip(left, widths)]
    fail = [rates["failure"][c] for c in cells]
    correct_edge = [1 - f["point"] for f in fail]
    ax.errorbar(correct_edge, cells,
                xerr=[[f["hi"] - f["point"] for f in fail], [f["point"] - f["lo"] for f in fail]],
                fmt="none", ecolor="black", capsize=3, lw=1.2)
    ax.set_xlim(0, 1)
    ax.set_xlabel("Share of graded calls")
    ax.set_ylabel("tool count – description – schema")
    ax.invert_yaxis()
    _style(ax)
    ax.legend(fontsize=_pt(PX_TEXT), ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.12))
    fig.suptitle(
        f"Failure modes by formulation\n{_n_line(analysis)}\n"
        "whisker: 95% interval on the failure rate",
        fontsize=_pt(PX_TITLE),
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    return fig


def interaction(analysis: dict, out_path):
    """Figure 2: H1. Failure rate at low and high tool count, terse vs rich,
    averaged over schema strictness, with 95% intervals."""
    m = analysis["marginal_count_richness"]
    fig, ax = plt.subplots(figsize=(WIDTH_IN, 6.0))
    xs = [0, 1]
    for richness in ("terse", "rich"):
        pts = [m[f"{count}-{richness}"] for count in ("low", "high")]
        ax.errorbar(xs, [p["point"] for p in pts],
                    yerr=[[p["point"] - p["lo"] for p in pts], [p["hi"] - p["point"] for p in pts]],
                    color=RICHNESS_COLOR[richness], marker="o", capsize=4, lw=2,
                    label=f"{richness} descriptions")
    h1 = analysis["hypotheses"]["H1"]
    ax.set_xticks(xs, ["low (2–4 tools)", "high (20 tools)"])
    ax.set_xlim(-0.3, 1.3)
    ax.set_ylim(bottom=0)
    ax.set_ylabel("Failure rate")
    ax.set_xlabel("Tool count")
    _style(ax)
    ax.legend(fontsize=_pt(PX_TEXT), loc="upper left")
    fig.suptitle(
        f"Description richness by tool count\n{_n_line(analysis)}\n"
        f"interaction {h1['point']:+.3f} (95% interval {h1['lo']:+.3f} to {h1['hi']:+.3f}), "
        f"H1 {h1['verdict']}",
        fontsize=_pt(PX_TITLE),
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    return fig


def flakiness(analysis: dict, out_path):
    """Figure 3: how often repetitions of one scenario in one cell disagree."""
    f = analysis["flakiness"]
    dist = f["distinct_categories_per_unit"]
    keys = sorted(dist, key=int)
    validate_rows(keys)
    shares = [dist[k] / f["units"] for k in keys]
    fig, ax = plt.subplots(figsize=(WIDTH_IN, 5.0))
    ax.bar([f"{k} outcome{'s' if k != '1' else ''}" for k in keys], shares, color="#2f6fd0")
    ax.set_ylim(0, 1)
    ax.set_ylabel("Share of (scenario, cell) units")
    ax.set_xlabel("Distinct categories among one unit's repetitions")
    _style(ax)
    e = f["ever_flip"]
    fig.suptitle(
        f"Rerun disagreement at the most deterministic setting\n"
        f"{f['units']} (scenario, cell) units, {analysis['N']} repetitions each\n"
        f"ever-flip fraction {e['point']:.3f} (95% interval {e['lo']:.3f} to {e['hi']:.3f})",
        fontsize=_pt(PX_TITLE),
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    return fig


def identical_retry(analysis: dict, out_path):
    """Figure 4: H4. Identical-retry rate after an error, by message format,
    over persistent error kinds, with the pre-registered floor drawn."""
    rec = analysis["recovery"]
    fmts = [f for f in ("actionable", "opaque") if f in rec]
    validate_rows(fmts)
    cis = [rec[f]["identical_retry_persistent"] for f in fmts]
    fig, ax = plt.subplots(figsize=(WIDTH_IN, 5.0))
    for x, (fmt, ci) in enumerate(zip(fmts, cis)):
        point = ci["point"] if ci else rec[fmt]["identical_retry"]
        ax.bar(x, point, color=FORMAT_COLOR[fmt], width=0.6)
        if ci:
            ax.errorbar(x, point, yerr=[[point - ci["lo"]], [ci["hi"] - point]],
                        fmt="none", ecolor="black", capsize=5, lw=1.2)
    h4 = analysis["hypotheses"]["H4"]
    ax.axhline(h4["floor"], color="#888888", ls="--", lw=1.2, label="pre-registered floor")
    ax.set_xticks(range(len(fmts)), [f"{f} error" for f in fmts])
    ax.set_ylim(0, 1)
    ax.set_ylabel("Identical-retry rate")
    _style(ax)
    ax.legend(fontsize=_pt(PX_TEXT), loc="upper left")
    n = h4["n_scenarios"]
    fig.suptitle(
        f"Repeating the failing call unchanged\n"
        f"{n} scenarios, persistent error kinds · H4 {h4['verdict']}",
        fontsize=_pt(PX_TITLE),
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    return fig


FIGURES = {
    "taxonomy": taxonomy,
    "interaction": interaction,
    "flakiness": flakiness,
    "identical_retry": identical_retry,
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_toolcall_figures.py -v`
Expected: 16 passed.

- [ ] **Step 5: Commit**

```bash
git add toolcall/figures.py tests/test_toolcall_figures.py
git commit -m "feat: the four figures, phone-legible, with N and intervals on each"
```

---

## Task 13: Every phase of the paid path, rehearsable

`runner.py` builds each phase's schedule from the pre-registration, estimates its cost from the bodies it will send, refuses to start without an approval that covers the estimate, and wraps the client in the spend guard. `stub=True` runs the identical path on the stub. The test drives every phase in order on the stub, then drives a paid phase through a fake SDK object to prove the real client path, the metering and both refusals. The last test exercises `selection.step2_proposal` on a stub pilot.

**Files:**
- Create: `toolcall/runner.py`
- Test: `tests/test_toolcall_runner.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_toolcall_runner.py`:

```python
"""Every phase of the paid path, on the stub and through a fake SDK.

The fake SDK stands where `openai.OpenAI()` would: an object whose
`responses.create(**body)` returns something with `.model_dump()`. It proves the
non-stub path builds the real client, meters spend, and refuses to start
without an approval that covers its own estimate."""

from types import SimpleNamespace

import pytest

from harness.store import JsonlStore
from tests.a3_examples import example_prereg, library, scenarios, synthetic_suite
from toolcall.formulation import CELLS
from toolcall.guard import SpendCapReached
from toolcall.records import CallRecord, RecoveryRecord
from toolcall.responses import openai_call
from toolcall.runner import PHASES, estimate_call_usd, run_phase

LIB = library()
SCS = scenarios(synthetic_suite(60, 6))
STEP2 = {"included": tuple(s.id for s in SCS), "reps": 5, "recovery_reps": 5, "slice_reps": 5,
         "approved_usd": 50.0}


def _quiet(_msg):
    pass


def test_every_phase_runs_on_the_stub_in_order(tmp_path):
    prereg = example_prereg(**STEP2, iterations=100)
    for phase in PHASES:
        out = run_phase(phase, prereg, LIB, SCS, tmp_path, stub=True, say=_quiet)
        assert out["stores"], phase
    campaign = JsonlStore(tmp_path / "campaign.jsonl", CallRecord).read_all()
    assert len(campaign) == 8 * len(SCS) * 5
    rec = JsonlStore(tmp_path / "recovery.jsonl", RecoveryRecord).read_all()
    assert {r.fmt for r in rec} == {"actionable", "opaque"}
    explo = JsonlStore(tmp_path / "exploratory.jsonl", CallRecord).read_all()
    assert all(t["strict"] for t in explo[0].request["tools"])
    assert (tmp_path / "slice-claude-sonnet-5-5.jsonl").exists()


def test_campaign_phases_refuse_to_start_before_step_two(tmp_path):
    with pytest.raises(ValueError, match="step 2"):
        run_phase("campaign", example_prereg(), LIB, SCS, tmp_path, stub=True, say=_quiet)


def test_phases_after_the_campaign_need_its_records(tmp_path):
    with pytest.raises(ValueError, match="needs the campaign"):
        run_phase("slice", example_prereg(**STEP2), LIB, SCS, tmp_path, stub=True, say=_quiet)


class FakeSDK:
    def __init__(self):
        self.bodies = []
        self.responses = SimpleNamespace(create=self._create)

    def _create(self, **body):
        self.bodies.append(body)
        name = body["tools"][0]["name"]
        resp = openai_call(name, {}, model=body["model"])
        return SimpleNamespace(model_dump=lambda: resp)


def test_a_paid_phase_needs_an_approval_covering_its_estimate(tmp_path):
    prereg = example_prereg()
    with pytest.raises(SpendCapReached, match="no spend approved"):
        run_phase("pilot-baseline", prereg, LIB, SCS, tmp_path, sdk=FakeSDK(), say=_quiet)
    with pytest.raises(SpendCapReached, match="exceeds"):
        run_phase("pilot-baseline", prereg, LIB, SCS, tmp_path, approved_usd=0.0001,
                  sdk=FakeSDK(), say=_quiet)


def test_a_paid_phase_runs_through_the_sdk_and_meters_what_it_spends(tmp_path):
    sdk = FakeSDK()
    said = []
    out = run_phase("pilot-baseline", example_prereg(), LIB, SCS, tmp_path, approved_usd=5.0,
                    sdk=sdk, say=said.append)
    assert len(sdk.bodies) == len(SCS) * 10
    assert out["spent_usd"] > 0 and out["spent_usd"] <= 5.0
    assert said[0].startswith(f"pilot-baseline on gpt-5.4-mini-2026-03-17: {len(SCS) * 10:,} calls")


def test_the_estimate_grows_with_what_is_sent_and_with_thinking():
    prereg = example_prereg()
    small = estimate_call_usd(prereg.primary, [], "hi")
    big = estimate_call_usd(prereg.primary, [{"description": "x" * 4000}], "hi")
    sonnet = estimate_call_usd(prereg.slice_models[1], [{"description": "x" * 4000}], "hi")
    assert small < big < sonnet


def test_step_two_is_computed_from_the_pilot(tmp_path):
    from toolcall.selection import step2_proposal

    prereg = example_prereg()
    for phase in ("pilot-baseline", "pilot-cells", "pilot-slice", "pilot-recovery"):
        run_phase(phase, prereg, LIB, SCS, tmp_path, stub=True, say=_quiet)
    pilot = {
        "baseline": JsonlStore(tmp_path / "pilot-baseline.jsonl", CallRecord).read_all(),
        "cells": JsonlStore(tmp_path / "pilot-cells.jsonl", CallRecord).read_all(),
        "recovery": JsonlStore(tmp_path / "pilot-recovery.jsonl", RecoveryRecord).read_all(),
        "slice": {m.model: JsonlStore(tmp_path / f"pilot-slice-{m.model}.jsonl",
                                      CallRecord).read_all() for m in prereg.slice_models},
    }
    p = step2_proposal(pilot, SCS, prereg)
    assert p["candidates"] == len(SCS)
    assert 0 < len(p["included"]) < len(SCS)
    assert prereg.n_floor <= p["reps"] <= prereg.n_cap
    assert set(p["usd_per_call_by_cell"]) == {c.name for c in CELLS}
    assert p["usd_per_call_by_cell"]["high-rich-strict"] > p["usd_per_call_by_cell"][
        "low-terse-loose"]
    assert p["estimate_usd"] > 0 and "**total**" in p["budget_table"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_toolcall_runner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'toolcall.runner'`.

- [ ] **Step 3: Write the implementation**

Create `toolcall/runner.py`:

```python
"""Every paid phase, as one function each, so scripts/a3_run.py stays thin and
the same code path runs on the stub (`stub=True`) as on the real providers.

Each phase builds its schedule from the pre-registration, estimates its cost
from the request bodies it will send, refuses to start unless the author's
approved amount covers the estimate, and wraps the client in the spend guard.

| phase           | cells                       | scenarios                | repetitions  |
|-----------------|-----------------------------|--------------------------|--------------|
| pilot-baseline  | baseline                    | every candidate          | pilot_reps   |
| pilot-cells     | all eight                   | first pilot_cost_scenarios | pilot_cost_reps |
| pilot-slice     | high-rich-strict, baseline  | first 5, per slice model | 1            |
| pilot-recovery  | baseline                    | first 5 with recovery    | 1 per format |
| campaign        | all eight                   | included                 | reps         |
| recovery        | baseline, best              | included with recovery   | recovery_reps per format |
| slice           | best, worst                 | included, per slice model | slice_reps  |
| exploratory     | best, constrained decoding  | included                 | reps         |

"best" and "worst" come from the campaign's own records by the pre-registered
rule (`analysis.ranked_cells`), so those phases cannot start before it ends.
"""

import json
from dataclasses import replace
from pathlib import Path

from harness.store import JsonlStore
from toolcall import campaign
from toolcall.analysis import ranked_cells
from toolcall.formulation import BASELINE, CELLS, Formulation, parse_cell, render
from toolcall.guard import GuardedClient, SpendGuard, check_estimate
from toolcall.prices import PRICES
from toolcall.providers import PARSE, Client, ScriptedClient
from toolcall.records import CallRecord, RecoveryRecord
from toolcall.stub import StubModel

FORMATS = ("actionable", "opaque")
OUTPUT_TOKENS_ESTIMATE = 200
THINKING_TOKENS_ESTIMATE = 300  # Sonnet 5.5 with between_tools; amendment §8's assumption
TOKENIZER_FACTOR = {"anthropic": 1.3, "openai": 1.0}  # amendment §8
CHARS_PER_TOKEN = 4.0
RECOVERY_TURNS_ESTIMATE = 3
PHASES = ("pilot-baseline", "pilot-cells", "pilot-slice", "pilot-recovery", "campaign",
          "recovery", "slice", "exploratory")


def estimate_call_usd(settings, tools: list[dict], user_message: str) -> float:
    """An upper-leaning estimate from the size of what will be sent. The guard
    then meters the real usage; this only decides whether to start."""
    chars = len(json.dumps(tools)) + len(user_message) + 400
    tokens_in = chars / CHARS_PER_TOKEN * TOKENIZER_FACTOR[settings.provider]
    out = OUTPUT_TOKENS_ESTIMATE + (THINKING_TOKENS_ESTIMATE if settings.thinking else 0)
    p = PRICES[settings.model]
    return (tokens_in * p.input + out * p.output) / 1e6


def _store(root: Path, name: str, cls):
    return JsonlStore(root / f"{name}.jsonl", cls)


def _client(settings, library, scenarios, stub: bool, sdk=None):
    if stub:
        if settings.provider != "openai":
            settings = replace(settings, provider="openai", thinking=None,
                               reasoning_effort="none")
        return ScriptedClient(settings, StubModel(library, scenarios, seed=0,
                                                  model=settings.model))
    return Client(settings, sdk=sdk)


def _plan(cells, scenarios, library, settings, reps, formats=None) -> tuple[int, float]:
    """(calls, estimated USD)."""
    total, calls = 0.0, 0
    for cell in cells:
        for s in scenarios:
            est = estimate_call_usd(settings, render(s, library, cell), s.user_message)
            n = reps * (len(formats) * RECOVERY_TURNS_ESTIMATE if formats else 1)
            total += n * est
            calls += n
    return calls, total


def _guarded(client, approved: float, stub: bool):
    if stub:
        return client
    return GuardedClient(client, SpendGuard(approved), PARSE[client.settings.provider])


def _announce(phase, model, calls, est, approved, say):
    say(f"{phase} on {model}: {calls:,} calls, estimated ${est:.2f}; approved ${approved:.2f}")


def run_phase(phase: str, prereg, library, scenarios, root, *, approved_usd: float = 0.0,
              stub: bool = False, resume: bool = False, say=print, sdk=None) -> dict:
    if phase not in PHASES:
        raise ValueError(f"unknown phase {phase!r}; one of {PHASES}")
    root = Path(root)
    by_id = {s.id: s for s in scenarios}
    candidates = sorted(scenarios, key=lambda s: s.id)
    if not phase.startswith("pilot"):
        prereg.require_step2()
        included = [by_id[i] for i in prereg.included]
    jobs = []  # (store name, settings, cells, scenarios, reps, formats, seed offset)
    p = prereg
    if phase == "pilot-baseline":
        jobs.append(("pilot-baseline", p.primary, [parse_cell(p.baseline_cell)], candidates,
                     p.pilot_reps, None, 1))
    elif phase == "pilot-cells":
        jobs.append(("pilot-cells", p.primary, list(CELLS), candidates[:p.pilot_cost_scenarios],
                     p.pilot_cost_reps, None, 2))
    elif phase == "pilot-slice":
        for m in p.slice_models:
            jobs.append((f"pilot-slice-{m.model}", m,
                         [Formulation("high", "rich", "strict"), BASELINE],
                         [s for s in candidates if not s.no_call_expected][:5], 1, None, 3))
    elif phase == "pilot-recovery":
        jobs.append(("pilot-recovery", p.primary, [BASELINE],
                     [s for s in candidates if s.recovery][:5], 1, FORMATS, 4))
    elif phase == "campaign":
        jobs.append(("campaign", p.primary, list(CELLS), included, p.reps, None, 0))
    else:
        done = JsonlStore(root / "campaign.jsonl", CallRecord).read_all()
        if not done:
            raise ValueError(f"{phase} needs the campaign's records to pick the cells")
        ranks = ranked_cells(done, p)
        best, worst = parse_cell(ranks["best"]), parse_cell(ranks["worst"])
        if phase == "recovery":
            cells = [BASELINE] if best == BASELINE else [BASELINE, best]
            jobs.append(("recovery", p.primary, cells, [s for s in included if s.recovery],
                         p.recovery_reps, FORMATS, 5))
        elif phase == "slice":
            for m in p.slice_models:
                jobs.append((f"slice-{m.model}", m, [best, worst], included, p.slice_reps,
                             None, 6))
        else:
            jobs.append(("exploratory", replace(p.primary, constrained=True), [best], included,
                         p.reps, None, 7))
    plans = [(job, *_plan(job[2], job[3], library, job[1], job[4], job[5])) for job in jobs]
    calls = sum(x[1] for x in plans)
    est = sum(x[2] for x in plans)
    _announce(phase, ", ".join(sorted({j[1].model for j in jobs})), calls, est, approved_usd, say)
    if not stub:
        check_estimate(est, approved_usd)
    out = {"phase": phase, "calls_planned": calls, "estimate_usd": est, "stores": []}
    remaining = approved_usd
    for (name, settings, cells, scs, reps, formats, offset), _, job_est in plans:
        client = _guarded(_client(settings, library, scenarios, stub, sdk), remaining or job_est,
                          stub)
        sched = campaign.schedule(cells, scs, reps, p.schedule_seed + offset, formats=formats)
        if formats:
            store = _store(root, name, RecoveryRecord)
            campaign.recovery_runs(sched, client, scs, library, store, resume=resume)
        else:
            store = _store(root, name, CallRecord)
            campaign.single_turn(sched, client, scs, library, store, phase=name, resume=resume)
        if not stub:
            remaining -= client.guard.spent
            out.setdefault("spent_usd", 0.0)
            out["spent_usd"] += client.guard.spent
        out["stores"].append(str(store.path))
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_toolcall_runner.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add toolcall/runner.py tests/test_toolcall_runner.py
git commit -m "feat: every phase of the paid path behind one runner, rehearsable on the stub"
```

---

## Task 14: Publication helpers: numbers, diagnose, confidentiality, BFCL

- `numbers.py`: the post's numbers block, generated between markers (artifact 5's pattern).
- `diagnose.py`: the adoption path (August §7): your tools, the baseline formulation, your taxonomy.
- `confidentiality.py`: the vocabulary scan and sign-off check (amendment §6).
- `bfcl.py`: one BFCL entry to a draft scenario the loader refuses until an author finishes it.

The two scripts are thin wrappers, run in Step 6.

**Files:**
- Create: `toolcall/numbers.py`
- Create: `toolcall/diagnose.py`
- Create: `toolcall/confidentiality.py`
- Create: `toolcall/bfcl.py`
- Create: `scripts/a3_diagnose.py`
- Create: `scripts/a3_import_bfcl.py`
- Test: `tests/test_toolcall_publication.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_toolcall_publication.py`:

```python
"""The numbers block, the bring-your-own-tools path, the confidentiality scan
and the BFCL import. All offline."""

import json
import tempfile
from pathlib import Path

import pytest

from harness.store import JsonlStore
from tests.a3_examples import (
    FLIGHT,
    MISC,
    TRAVEL,
    example_prereg,
    library,
    scenarios,
    synthetic_suite,
    write_suite,
)
from toolcall import bfcl, campaign, confidentiality
from toolcall.analysis import analyse
from toolcall.diagnose import diagnose, report
from toolcall.formulation import CELLS
from toolcall.numbers import END, START, block_in, numbers_block, pct, pp, replace_block
from toolcall.providers import ScriptedClient
from toolcall.records import CallRecord
from toolcall.scenarios import scenario_from_dict
from toolcall.stub import StubModel
from toolcall.tools import tool_from_dict


def test_formatting():
    assert pct(0.1234) == "12.3%" and pp(-0.145) == "-14.5 pp" and pp(0.005) == "+0.5 pp"


def test_the_block_is_replaced_between_its_markers_only():
    post = f"intro\n{START}\nold\n{END}\noutro"
    new = replace_block(post, f"{START}\nnew\n{END}")
    assert new == f"intro\n{START}\nnew\n{END}\noutro"
    with pytest.raises(ValueError, match="no a3-numbers block"):
        block_in("no markers")


def test_the_numbers_block_renders_from_a_stub_analysis():
    a = json.loads(json.dumps(_stub_analysis()))
    block = numbers_block(a)
    assert block.startswith(START) and block.endswith(END)
    assert "H1, richness × count interaction" in block and "95% interval" in block


def _stub_analysis():
    lib, scs = library(), scenarios(synthetic_suite(24, 2))
    prereg = example_prereg(included=tuple(s.id for s in scs), reps=5, recovery_reps=5,
                            slice_reps=5, approved_usd=1.0, iterations=100)
    store = JsonlStore(Path(tempfile.mkdtemp()) / "c.jsonl", CallRecord)
    campaign.single_turn(campaign.schedule(CELLS, scs, 5, 1),
                         ScriptedClient(prereg.primary, StubModel(lib, scs, seed=1)),
                         scs, lib, store, phase="campaign")
    return analyse(store.read_all(), [], scs, prereg)


def test_bring_your_own_tools_runs_the_baseline_only_and_reports_a_taxonomy(tmp_path):
    tools_dir, sc_dir = write_suite(tmp_path / "suite")
    from toolcall.scenarios import load_scenarios
    from toolcall.tools import load_library

    lib = load_library(tools_dir)
    scs = load_scenarios(sc_dir, lib, factorial=False)
    client = ScriptedClient(example_prereg().primary, StubModel(lib, scs, seed=0))
    summary = diagnose(client, tools_dir, sc_dir, tmp_path / "d.jsonl", reps=5)
    assert summary["graded"] == 15
    assert sum(r["calls"] for r in summary["categories"]) == 15
    assert all(len(b["tools"]) <= 4 for b in client.sent)
    assert "| WRONG_TOOL |" in report(summary)


def test_the_confidentiality_scan_reads_values_and_flags_the_vocabulary(tmp_path):
    (tmp_path / "ok.json").write_text(json.dumps({"success_claim_pattern": "x", "a": "flights"}))
    (tmp_path / "bad.json").write_text(json.dumps({"m": "File a claim under my policyholder ID"}))
    assert confidentiality.scan(tmp_path) == {"bad.json": ["claim", "policyholder"]}
    signoff = tmp_path / "confidentiality_signoff.json"
    signoff.write_text(json.dumps({"files": {"bad.json": {"signed_off": "2026-10-08",
                                                          "note": "test"}}}))
    assert confidentiality.unsigned(tmp_path, signoff) == {}


def test_the_example_travel_library_would_need_a_signoff_for_its_cabin_class(tmp_path):
    """`premium` is a cabin class here, and an insurance word too: the scan
    flags it, and only a signed-off entry clears it. That is the mechanism."""
    (tmp_path / "travel.json").write_text(json.dumps(TRAVEL))
    (tmp_path / "misc.json").write_text(json.dumps(MISC))
    assert set(confidentiality.scan(tmp_path)) == {"travel.json"}


BFCL_ENTRY = {
    "id": "simple_7",
    "question": [[{"role": "user", "content": "Find the area of a triangle, base 10, height 5."}]],
    "function": [{
        "name": "geometry.area_triangle",
        "description": "Calculate the area of a triangle. Uses base times height over two.",
        "parameters": {"type": "dict", "properties": {
            "base": {"type": "integer", "description": "The base."},
            "height": {"type": "integer", "description": "The height."},
            "unit": {"type": "string", "description": "Unit of measure."}},
            "required": ["base", "height"]}}],
}
BFCL_ANSWER = {"id": "simple_7", "ground_truth": [
    {"geometry.area_triangle": {"base": [10], "height": [5], "unit": ["units", ""]}}]}


def test_a_bfcl_entry_becomes_a_draft_that_the_loader_refuses():
    tool = bfcl.draft_tool(BFCL_ENTRY["function"][0])
    sc = bfcl.draft_scenario(BFCL_ENTRY, BFCL_ANSWER, commit="abc123", domain="math")
    assert tool["name"] == "geometry_area_triangle" and tool["draft"]
    assert sc["expectation"]["acceptable_calls"] == [{
        "tool": "geometry_area_triangle", "args": {"base": 10, "height": 5},
        "may_include": {"unit": "units"}}]
    assert sc["source"] == {"kind": "bfcl", "id": "simple_7", "commit": "abc123"}
    with pytest.raises(ValueError, match="draft"):
        tool_from_dict(tool, "math")
    with pytest.raises(ValueError, match="draft"):
        scenario_from_dict(sc, library())


def test_an_irrelevance_entry_becomes_a_no_call_draft():
    sc = bfcl.draft_scenario(BFCL_ENTRY, None, commit="abc", domain="math")
    assert sc["expectation"] == {"no_call_expected": True}
    assert sc["target_failure_mode"] == "SPURIOUS"


def test_bfcl_types_outside_the_subset_are_refused():
    fn = json.loads(json.dumps(BFCL_ENTRY["function"][0]))
    fn["parameters"]["properties"]["base"]["type"] = "tuple"
    with pytest.raises(ValueError, match="closed subset"):
        bfcl.draft_tool(fn)


def test_the_example_scenario_survives_a_json_round_trip():
    assert scenario_from_dict(json.loads(json.dumps(FLIGHT)), library()).id == FLIGHT["id"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_toolcall_publication.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'toolcall.numbers'`.

- [ ] **Step 3: Write the implementation**

Create `toolcall/numbers.py`:

```python
"""The post's numbers, generated from `data/a3/analysis.json`.

The post carries a table between two markers. `scripts/a3_numbers.py` rewrites
it from the analysis, and tests/test_a3_post.py fails if the table in the post
differs from a fresh generation, so no number can be typed by hand or left
stale after a re-analysis (artifact 5's pattern).

Rates are shown as percentages and effects as percentage points, the scale the
hypotheses are registered on (amendment §4f).
"""

START = "<!-- a3-numbers:start -->"
END = "<!-- a3-numbers:end -->"


def pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def pp(x: float) -> str:
    return f"{100 * x:+.1f} pp"


def ci_pct(ci: dict) -> str:
    return f"{pct(ci['point'])} (95% interval {pct(ci['lo'])} to {pct(ci['hi'])})"


def ci_pp(ci: dict) -> str:
    return f"{pp(ci['point'])} (95% interval {pp(ci['lo'])} to {pp(ci['hi'])})"


def usd(x) -> str:
    return "unbounded" if x is None else f"${x:.5f}"


def numbers_block(a: dict) -> str:
    h = a["hypotheses"]
    rates = a["cell_rates"]["failure"]
    ranks = a["ranked_cells"]
    eff = a["effects"]["failure"]
    cost = a["cost"]
    rows = [
        ("Model and setting", (f"`{a['model']}`, temperature {a['settings']['temperature']}, "
                               f"reasoning {a['settings']['reasoning_effort']}")),
        ("Design", f"{a['S']} scenarios × 8 cells × {a['N']} repetitions"),
        ("Failure rate, baseline cell (low-terse-loose)", ci_pct(rates["low-terse-loose"])),
        (f"Failure rate, best cell ({ranks['best']})", ci_pct(rates[ranks["best"]])),
        (f"Failure rate, worst cell ({ranks['worst']})", ci_pct(rates[ranks["worst"]])),
        ("Rich descriptions at low tool count", ci_pp(eff["at:richness:count:low"])),
        ("Rich descriptions at high tool count", ci_pp(eff["at:richness:count:high"])),
        ("H1, richness × count interaction", f"{ci_pp(h['H1'])}, {h['H1']['verdict']}"),
        ("H2, strictness on malformed + wrong-parameter rate",
         f"{ci_pp(h['H2'])}, {h['H2']['verdict']}"),
        (("H2, strictness on wrong-tool rate (90% interval, margin "
          f"±{100 * h['H2']['equivalence']['margin']:.0f} pp)"),
         (f"{pp(h['H2']['equivalence']['point'])} ({pp(h['H2']['equivalence']['lo'])} to "
          f"{pp(h['H2']['equivalence']['hi'])})")),
        ("H3, tool count on wrong-tool rate", f"{ci_pp(h['H3'])}, {h['H3']['verdict']}"),
        ("H4, identical retries, opaque minus actionable",
         f"{ci_pp(h['H4'])}, {h['H4']['verdict']}" if h["H4"].get("testable")
         else f"not testable: {h['H4']['reason']}"),
        ("H5, tool count against the rerun A/A contrast",
         f"{ci_pp(h['H5'])}, {h['H5']['verdict']}"),
        ("Ever-flip fraction", ci_pct(a["flakiness"]["ever_flip"])),
        ("Cost per successful call, baseline cell, retrying up to 3 times",
         usd(cost["low-terse-loose"]["retry"]["point"])),
        (f"Cost per successful call, best cell ({ranks['best']}), retrying up to 3 times",
         usd(cost[ranks["best"]]["retry"]["point"])),
    ]
    if a.get("spend"):
        rows.append(("Spend, billed", f"${a['spend']['billed_usd']:.2f}"))
    lines = ["| quantity | value |", "|---|---|"] + [f"| {k} | {v} |" for k, v in rows]
    return "\n".join([START] + lines + [END])


def block_in(text: str) -> str:
    start, end = text.find(START), text.find(END)
    if start == -1 or end == -1 or end < start:
        raise ValueError("the post has no a3-numbers block")
    return text[start:end + len(END)]


def replace_block(text: str, block: str) -> str:
    return text.replace(block_in(text), block)
```

Create `toolcall/diagnose.py`:

```python
"""Run it on your own agent: your tools, your scenarios, your failure taxonomy.

The adoption path (August §7). Point it at a directory of tool-library files
and a directory of scenario files in this repository's format, and it runs the
baseline formulation only -- your tools as you list them, terse or rich and
loose or strict as you choose -- and reports how the calls break down across
the six categories. The factorial is optional; this is the easy default.
"""

from collections import Counter, defaultdict

from harness.store import JsonlStore
from toolcall import campaign
from toolcall.effects import wilson
from toolcall.formulation import Formulation
from toolcall.grader import CATEGORIES, EXCLUDED
from toolcall.records import CallRecord
from toolcall.scenarios import load_scenarios
from toolcall.tools import load_library

INTERVENTION = {
    "MALFORMED": "schema strictness, output format constraints",
    "SPURIOUS": "description scoping, explicit guidance on when not to call",
    "MISSING": "tool discoverability, description richness",
    "WRONG_TOOL": "disambiguation between similar tools, fewer tools in context",
    "WRONG_PARAMS": "typing strictness, parameter naming and descriptions",
}


def diagnose(client, tools_dir, scenarios_dir, store_path, *, reps: int,
             richness: str = "rich", strictness: str = "strict", seed: int = 0) -> dict:
    library = load_library(tools_dir)
    scenarios = load_scenarios(scenarios_dir, library, factorial=False)
    cell = Formulation("low", richness, strictness)
    store = JsonlStore(store_path, CallRecord)
    campaign.single_turn(campaign.schedule([cell], scenarios, reps, seed), client, scenarios,
                         library, store, phase="diagnose")
    return summarise(store.read_all())


def summarise(records) -> dict:
    graded = [r for r in records if r.grade["category"] not in EXCLUDED]
    counts = Counter(r.grade["category"] for r in graded)
    n = len(graded)
    by_scenario: dict = defaultdict(Counter)
    for r in graded:
        by_scenario[r.scenario_id][r.grade["category"]] += 1
    rows = []
    for cat in CATEGORIES:
        k = counts.get(cat, 0)
        lo, hi = wilson(k, n) if n else (None, None)
        rows.append({"category": cat, "calls": k, "share": k / n if n else None,
                     "pooled_wilson_lo": lo, "pooled_wilson_hi": hi,
                     "points_at": INTERVENTION.get(cat, "")})
    return {"graded": n,
            "excluded": Counter(r.grade["category"] for r in records
                                if r.grade["category"] in EXCLUDED),
            "categories": rows,
            "by_scenario": {s: dict(c) for s, c in sorted(by_scenario.items())},
            "note": "Pooled Wilson intervals treat repetitions of one scenario as independent, "
                    "which they are not; read the per-scenario breakdown before trusting them."}


def report(summary: dict) -> str:
    lines = [f"{summary['graded']} graded calls; excluded: {dict(summary['excluded']) or 0}",
             "", "| category | calls | share | what it points at |", "|---|---|---|---|"]
    for r in summary["categories"]:
        share = "" if r["share"] is None else f"{100 * r['share']:.1f}%"
        lines.append(f"| {r['category']} | {r['calls']} | {share} | {r['points_at']} |")
    lines += ["", summary["note"]]
    return "\n".join(lines)
```

Create `toolcall/confidentiality.py`:

```python
"""The confidentiality guard (amendment §6).

The author builds an agent platform at their employer. Nothing here may
resemble the employer's domain, and insurance or claims workflows are excluded
outright. This scans the string values of every scenario and tool-library
file for that vocabulary. A file with a hit must be listed in the sign-off file
with the author's date and a note, or tests/test_toolcall_confidentiality.py
fails. The scan cannot read intent; the pre-publish gate's non-negotiable item
still applies.
"""

import json
import re
from pathlib import Path

VOCABULARY = (
    r"\binsur(e|ed|er|ers|ance|ances)\b",
    r"\bpolicy ?holders?\b",
    r"\bunderwrit\w*",
    r"\bpremiums?\b",
    r"\bdeductibles?\b",
    r"\badjust(er|ers|or|ors)\b",
    r"\badjudicat\w*",
    r"\bclaim(s|ant|ants)?\b",
    r"\bfnol\b",
    r"\bfirst notice of loss\b",
    r"\bcoverages?\b",
    r"\bbeneficiar(y|ies)\b",
    r"\bactuar\w*",
    r"\bindemnit\w*",
    r"\bsubrogat\w*",
    r"\bloss ratio\b",
    r"\bpolicy numbers?\b",
)
_PATTERNS = [re.compile(p, re.IGNORECASE) for p in VOCABULARY]


def _strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for v in x.values():
            yield from _strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from _strings(v)


def hits(path: Path) -> list[str]:
    found = set()
    for s in _strings(json.loads(Path(path).read_text())):
        for p in _PATTERNS:
            for m in p.finditer(s):
                found.add(m.group(0).lower())
    return sorted(found)


def scan(root) -> dict[str, list[str]]:
    root = Path(root)
    return {
        str(p.relative_to(root)): h
        for p in sorted(root.rglob("*.json"))
        if p.name != "confidentiality_signoff.json" and (h := hits(p))
    }


def unsigned(root, signoff_path) -> dict[str, list[str]]:
    signoff = json.loads(Path(signoff_path).read_text()) if Path(signoff_path).exists() else {}
    signed = {
        k for k, v in signoff.get("files", {}).items()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v.get("signed_off", "")) and v.get("note")
    }
    return {k: v for k, v in scan(root).items() if k not in signed}
```

Create `toolcall/bfcl.py`:

```python
"""Drafts from the Berkeley Function Calling Leaderboard's public data (amendment §6).

BFCL's single-turn entries already carry what a scenario needs: a user
message, function documents and, for the categories with answers, the
acceptable values of every argument. This converts one entry and its answer
into a *draft*: a scenario and tool definitions in this repository's format,
marked `"draft": true`. The loader refuses drafts. An author finishes each
one: writes the terse and rich descriptions, chooses the low set, writes 4-6
confusables, and removes the draft flag. That is why the seed is "public
seed plus authored extension", and why the post can attribute every seed
scenario to its BFCL id and commit.

BFCL types: `dict` (the parameters object), `integer`, `float`, `string`,
`boolean`, `array`. `tuple` and `any` have no equivalent in the closed subset
and raise, so such an entry is skipped rather than approximated. In an answer,
the empty string `""` among an argument's values means the argument may be
omitted.
"""

import re

TYPES = {"integer": "integer", "float": "number", "number": "number", "string": "string",
         "boolean": "boolean", "array": "array"}


def tool_name(bfcl_name: str) -> str:
    name = re.sub(r"[^a-z0-9_]", "_", bfcl_name.lower())
    return re.sub(r"_+", "_", name).strip("_")


def _first_sentence(text: str) -> str:
    m = re.match(r"(.+?[.!?])(\s|$)", text.strip())
    return (m.group(1) if m else text.strip())[:120]


def draft_tool(fn: dict) -> dict:
    params = []
    props = fn["parameters"].get("properties", {})
    required = set(fn["parameters"].get("required", []))
    for name, spec in props.items():
        t = spec.get("type")
        if t not in TYPES:
            raise ValueError(f"{fn['name']}.{name}: BFCL type {t!r} is outside the closed subset")
        p = {"name": tool_name(name), "type": TYPES[t], "required": name in required,
             "terse": _first_sentence(spec.get("description", name)),
             "rich": spec.get("description", name)}
        if t == "array":
            item = spec.get("items", {}).get("type")
            if item not in TYPES or TYPES[item] == "array":
                raise ValueError(f"{fn['name']}.{name}: array items {item!r} unsupported")
            p["items"] = TYPES[item]
        if spec.get("enum"):
            p["enum"] = list(spec["enum"])
        params.append(p)
    return {"name": tool_name(fn["name"]), "terse": _first_sentence(fn["description"]),
            "rich": fn["description"], "params": params, "draft": True}


def _acceptable(answer_entry: dict) -> dict:
    (fn_name, args), = answer_entry.items()
    call = {"tool": tool_name(fn_name), "args": {}, "may_include": {}}
    for name, values in args.items():
        omit = "" in values
        values = [v for v in values if v != ""]
        if not values:
            continue
        spec = values[0] if len(values) == 1 else {"one_of": values}
        call["may_include" if omit else "args"][tool_name(name)] = spec
    return call


def draft_scenario(entry: dict, answer: dict | None, *, commit: str, domain: str) -> dict:
    user = [m["content"] for turn in entry["question"] for m in turn if m["role"] == "user"][-1]
    tools = [tool_name(f["name"]) for f in entry["function"]]
    d = {
        "id": f"bfcl-{tool_name(entry['id'])}",
        "draft": True,
        "source": {"kind": "bfcl", "id": entry["id"], "commit": commit},
        "domain": domain,
        "target_failure_mode": "SPURIOUS" if answer is None else "WRONG_PARAMS",
        "tools": tools,
        "confusables": [],
        "user_message": user,
    }
    if answer is None:
        d["expectation"] = {"no_call_expected": True}
    else:
        d["expectation"] = {"acceptable_calls": [_acceptable(a) for a in answer["ground_truth"]]}
    return d
```

Create `scripts/a3_diagnose.py`:

```python
"""Your tools, your scenarios, your failure taxonomy (August §7).

    .venv/bin/python scripts/a3_diagnose.py --tools my/tools --scenarios my/scenarios \
        --model gpt-5.4-mini-2026-03-17 --reps 5 --approved-usd 1.00
    .venv/bin/python scripts/a3_diagnose.py --tools ... --scenarios ... --dry-run

Runs the baseline formulation only (rich descriptions and strict schemas by
default; change with --richness / --strictness). --dry-run uses the stub model
and makes no API call: use it to check your files before spending anything.
A real run spends money: it needs --approved-usd and the provider's API key in
the environment (OPENAI_API_KEY or ANTHROPIC_API_KEY).
"""

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from toolcall.diagnose import diagnose, report
from toolcall.formulation import Formulation, render
from toolcall.guard import GuardedClient, SpendGuard, check_estimate
from toolcall.providers import PARSE, Client, ModelSettings, ScriptedClient
from toolcall.runner import estimate_call_usd
from toolcall.scenarios import load_scenarios
from toolcall.stub import StubModel
from toolcall.tools import load_library


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tools", type=Path, required=True)
    ap.add_argument("--scenarios", type=Path, required=True)
    ap.add_argument("--model", default="gpt-5.4-mini-2026-03-17")
    ap.add_argument("--provider", choices=["openai", "anthropic"], default="openai")
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--richness", choices=["terse", "rich"], default="rich")
    ap.add_argument("--strictness", choices=["loose", "strict"], default="strict")
    ap.add_argument("--approved-usd", type=float, default=0.0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--store", type=Path)
    args = ap.parse_args()
    if args.provider == "openai":
        settings = ModelSettings("openai", args.model, 0.0, reasoning_effort="none")
    else:
        settings = ModelSettings("anthropic", args.model, None, thinking="between_tools")
    library = load_library(args.tools)
    scenarios = load_scenarios(args.scenarios, library, factorial=False)
    cell = Formulation("low", args.richness, args.strictness)
    if args.dry_run:
        dry = ModelSettings("openai", "gpt-5.4-mini-2026-03-17", 0.0, reasoning_effort="none")
        client = ScriptedClient(dry, StubModel(library, scenarios))
    else:
        ests = [estimate_call_usd(settings, render(s, library, cell), s.user_message)
                for s in scenarios]
        estimate = sum(ests) * args.reps
        print(f"{len(scenarios) * args.reps} calls, estimated ${estimate:.2f}; "
              f"approved ${args.approved_usd:.2f}")
        check_estimate(estimate, args.approved_usd)
        client = GuardedClient(Client(settings), SpendGuard(args.approved_usd),
                               PARSE[settings.provider])
    store = args.store or Path(tempfile.mkdtemp()) / "diagnose.jsonl"
    summary = diagnose(client, args.tools, args.scenarios, store, reps=args.reps,
                       richness=args.richness, strictness=args.strictness)
    print(report(summary))
    print(f"\nrecords: {store}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Create `scripts/a3_import_bfcl.py`:

```python
"""Turn BFCL entries into draft scenarios and tools for an author to finish.

    .venv/bin/python scripts/a3_import_bfcl.py --questions BFCL_v3_simple.json \
        --answers possible_answer/BFCL_v3_simple.json --ids simple_7 simple_12 \
        --commit <gorilla commit> --domain math --out toolcall/data/drafts

Reads BFCL's JSON-lines files from a local checkout of
github.com/ShishirPatil/gorilla at a pinned commit (plan 1 Task 18 records the
commit and its license). Writes one draft scenario per id and one draft tool
file per domain, all marked `"draft": true`, which the loader refuses until an
author finishes them. Omit --answers for the irrelevance category.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from toolcall.bfcl import draft_scenario, draft_tool


def _jsonl(path: Path) -> dict[str, dict]:
    return {d["id"]: d for d in (json.loads(x) for x in path.read_text().splitlines() if x)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", type=Path, required=True)
    ap.add_argument("--answers", type=Path)
    ap.add_argument("--ids", nargs="+", required=True)
    ap.add_argument("--commit", required=True)
    ap.add_argument("--domain", required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    questions = _jsonl(args.questions)
    answers = _jsonl(args.answers) if args.answers else {}
    (args.out / "scenarios").mkdir(parents=True, exist_ok=True)
    (args.out / "tools").mkdir(parents=True, exist_ok=True)
    tools = {}
    for i in args.ids:
        entry = questions[i]
        sc = draft_scenario(entry, answers.get(i), commit=args.commit, domain=args.domain)
        (args.out / "scenarios" / f"{sc['id']}.json").write_text(
            json.dumps(sc, indent=2, ensure_ascii=False) + "\n")
        for fn in entry["function"]:
            t = draft_tool(fn)
            tools[t["name"]] = t
        print(f"[draft] {sc['id']}")
    (args.out / "tools" / f"{args.domain}.json").write_text(json.dumps(
        {"domain": args.domain, "tools": list(tools.values())}, indent=2,
        ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_toolcall_publication.py -v`
Expected: 10 passed.

- [ ] **Step 5: Check the diagnose script end to end, on the synthetic suite, with no API call**

```bash
.venv/bin/python -c "from toolcall.stub_suite import write_suite; write_suite('build/a3-byo')"
.venv/bin/python scripts/a3_diagnose.py --tools build/a3-byo/tools --scenarios build/a3-byo/scenarios --dry-run --reps 3
```
Expected: `9 graded calls; excluded: 0`, then a six-row table.

- [ ] **Step 6: Commit**

```bash
git add toolcall/numbers.py toolcall/diagnose.py toolcall/confidentiality.py toolcall/bfcl.py scripts/a3_diagnose.py scripts/a3_import_bfcl.py tests/test_toolcall_publication.py
git commit -m "feat: the numbers block, the bring-your-own-tools path, the confidentiality scan and BFCL drafts"
```

---

## Task 15: Render the figures from a stub analysis, and look at them

The figure tests check what can be checked without eyes. This task is the eyes (the portfolio's figure rule, and the author's global rule that a screenshot nobody looked at is not evidence). The stub analysis is labelled NOT DATA everywhere it appears.

**Files:**
- Create: `scripts/a3_stub_demo.py`, `scripts/a3_render_figures.py`

- [ ] **Step 1: Create the stub demo**

Create `scripts/a3_stub_demo.py`:

```python
"""A stub analysis, for laying out figures before any data exists. NOT DATA.

    .venv/bin/python scripts/a3_stub_demo.py --out build/a3-stub

Runs the synthetic suite through the campaign and recovery phases on the stub
model, analyses it, and writes analysis.json. Its numbers are planted by
toolcall/stub.py and mean nothing about any real model.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.store import JsonlStore
from toolcall.analysis import analyse
from toolcall.prereg import Preregistration
from toolcall.providers import ModelSettings
from toolcall.records import CallRecord, RecoveryRecord
from toolcall.runner import run_phase
from toolcall.stub_suite import library, scenarios, synthetic_suite


def demo_prereg(included) -> Preregistration:
    return Preregistration(
        primary=ModelSettings("openai", "gpt-5.4-mini-2026-03-17", 0.0,
                              reasoning_effort="none"),
        slice_models=(ModelSettings("openai", "gpt-5.4-nano-2026-03-17", 0.0,
                                    reasoning_effort="none"),),
        baseline_cell="low-terse-loose", band=(0.10, 0.90), pilot_reps=10,
        pilot_cost_scenarios=10, pilot_cost_reps=5, delta2=0.02, identical_retry_floor=0.05,
        n_floor=5, n_cap=20, s_floor=24, alpha=0.05, iterations=1000, bootstrap_seed=1,
        schedule_seed=1, retry_cap=3, turn_budget=3, normalizer_version=1,
        included=tuple(included), reps=8, recovery_reps=5, slice_reps=5, approved_usd=1.0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="build/a3-stub")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    lib, scs = library(), scenarios(synthetic_suite(60, 6))
    prereg = demo_prereg(s.id for s in scs)
    for phase in ("campaign", "recovery", "slice"):
        run_phase(phase, prereg, lib, scs, out, stub=True)
    calls = JsonlStore(out / "campaign.jsonl", CallRecord).read_all()
    recs = JsonlStore(out / "recovery.jsonl", RecoveryRecord).read_all()
    slices = {m.model: JsonlStore(out / f"slice-{m.model}.jsonl", CallRecord).read_all()
              for m in prereg.slice_models}
    a = analyse(calls, recs, scs, prereg, slices=slices)
    (out / "analysis.json").write_text(json.dumps(a, indent=1, sort_keys=True) + "\n")
    print(f"[ok] {out / 'analysis.json'} (stub, NOT DATA)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Create the render script**

Create `scripts/a3_render_figures.py`:

```python
"""Render artifact 3's four figures from an analysis file.

    .venv/bin/python scripts/a3_render_figures.py --analysis data/a3/analysis.json --out docs/figures/a3

Also writes a 375 px wide `-phone.png` copy of each figure, which is what gets
looked at for legibility before a figure is called done.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib.pyplot as plt
from PIL import Image

from harness.figure_guards import PHONE_WIDTH_PX
from toolcall.figures import FIGURES


def phone_copy(src: Path) -> Path:
    dst = src.with_name(src.stem + "-phone.png")
    with Image.open(src) as im:
        height = round(im.height * PHONE_WIDTH_PX / im.width)
        im.resize((PHONE_WIDTH_PX, height), Image.LANCZOS).save(dst)
    return dst


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--analysis", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    analysis = json.loads(Path(args.analysis).read_text())
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, draw in FIGURES.items():
        path = out / f"{name}.png"
        plt.close(draw(analysis, path))
        print(f"[ok] {path} and {phone_copy(path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Run both**

```bash
.venv/bin/python scripts/a3_stub_demo.py --out build/a3-stub
.venv/bin/python scripts/a3_render_figures.py --analysis build/a3-stub/analysis.json --out build/a3-stub/figures
```
Expected: `[ok] build/a3-stub/analysis.json (stub, NOT DATA)`, then four `[ok]` lines, each naming a figure and its `-phone.png` copy.

- [ ] **Step 4: Look at all eight files**

Open each PNG and each `-phone.png` (the phone copies are 375 px wide, the width `harness.figure_guards` calibrates against). Check, and write down what you saw:

- no title, label or legend is clipped at either width;
- every title states the scenario or unit count and the repetitions;
- the taxonomy whiskers sit at the edge of the grey `correct` segment;
- the interaction plot's y axis starts at 0;
- the identical-retry figure draws the dashed floor line.

If anything fails, fix `toolcall/figures.py`, re-run Step 3, and look again. Two clipped titles were found and fixed this way while this plan was written.

- [ ] **Step 5: Confirm two renders are identical**

```bash
.venv/bin/python scripts/a3_render_figures.py --analysis build/a3-stub/analysis.json --out build/a3-stub/figures-2 > /dev/null
for f in build/a3-stub/figures/*.png; do cmp -s "$f" "build/a3-stub/figures-2/$(basename $f)" || echo "DIFF $f"; done; echo compared
```
Expected: `compared`, with no `DIFF` line. Plan 3's published-figures test relies on byte-identical renders.

- [ ] **Step 6: Commit**

```bash
git add scripts/a3_stub_demo.py scripts/a3_render_figures.py
git commit -m "feat: the stub demo and the figure renderer, looked at on desktop and phone"
```

---

## Task 16: Two worked domain libraries, three worked scenarios, and the data tests

The real suite lives in `toolcall/data/`. This task writes two complete domain libraries (weather, 12 tools; calendar, 10) and three complete scenarios: a confusable-heavy forecast request with a recovery block, a wrong-parameter calendar request, and a no-call message. They are the templates Task 19 follows. `test_toolcall_data.py` then checks every data file, whatever the suite holds: it loads, renders in all eight cells, fits Anthropic's strict-mode caps, names no tool in its user message, has unique messages, records BFCL provenance, passes the confidentiality scan, and is formatted JSON.

**Files:**
- Create: `toolcall/data/tools/weather.json`, `toolcall/data/tools/calendar.json`
- Create: `toolcall/data/scenarios/weather-forecast-lisbon.json`, `calendar-standup-once.json`, `weather-thanks-no-call.json`
- Create: `toolcall/data/confidentiality_signoff.json`
- Test: `tests/test_toolcall_data.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_toolcall_data.py`:

```python
"""Every file under toolcall/data/ is valid, renders in all eight cells, fits
the provider strict-mode caps, and passes the confidentiality guard.

These run on whatever the suite holds at the time. The suite's size and
coverage are checked separately, by tests/test_toolcall_suite.py, which is
added when authoring is complete (plan 1 Task 19)."""

import json
from pathlib import Path

import pytest

from toolcall import confidentiality
from toolcall.formulation import CELLS, Formulation, render
from toolcall.scenarios import load_scenarios
from toolcall.tools import load_library

DATA = Path(__file__).resolve().parents[1] / "toolcall" / "data"
LIB = load_library(DATA / "tools")
SCENARIOS = load_scenarios(DATA / "scenarios", LIB)
# Anthropic's strict-mode limits, read 2026-10-08 (amendment §3): the
# exploratory slice must stay within them if it is ever repeated on Claude.
MAX_STRICT_TOOLS, MAX_OPTIONAL = 20, 24


def test_the_suite_loads():
    assert SCENARIOS, "no scenarios under toolcall/data/scenarios"


@pytest.mark.parametrize("s", SCENARIOS, ids=[s.id for s in SCENARIOS])
def test_every_scenario_renders_in_all_eight_cells(s):
    for cell in CELLS:
        tools = render(s, LIB, cell)
        assert len(tools) == (20 if cell.count == "high" else len(s.tools))


@pytest.mark.parametrize("s", SCENARIOS, ids=[s.id for s in SCENARIOS])
def test_the_strict_high_rendering_fits_the_strict_mode_caps(s):
    tools = render(s, LIB, Formulation("high", "rich", "strict"))
    optional = sum(len(t["parameters"]["properties"]) - len(t["parameters"]["required"])
                   for t in tools)
    assert len(tools) <= MAX_STRICT_TOOLS and optional <= MAX_OPTIONAL, (len(tools), optional)


@pytest.mark.parametrize("s", SCENARIOS, ids=[s.id for s in SCENARIOS])
def test_the_user_message_names_no_tool(s):
    """The message must not hand the model a tool name; that would test
    reading, not choosing."""
    assert not [t for t in LIB.tools if t in s.user_message]


def test_user_messages_are_unique():
    assert len({s.user_message for s in SCENARIOS}) == len(SCENARIOS)


def test_every_bfcl_seed_names_its_source_id_and_commit():
    for s in SCENARIOS:
        if s.source.get("kind") == "bfcl":
            assert s.source.get("id") and len(s.source.get("commit", "")) >= 7, s.id


def test_no_unsigned_confidentiality_hits():
    """Amendment §6. A hit is not proof of a problem; an unsigned one is."""
    assert confidentiality.unsigned(DATA, DATA / "confidentiality_signoff.json") == {}


def test_every_data_file_is_formatted_json():
    for path in DATA.rglob("*.json"):
        text = path.read_text()
        assert text == json.dumps(json.loads(text), indent=2, ensure_ascii=False) + "\n", path
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_toolcall_data.py -v`
Expected: an error at collection: `ValueError: no tools under .../toolcall/data/tools`.

- [ ] **Step 3: Write the two libraries**

Create `toolcall/data/tools/weather.json`:

```json
{
  "domain": "weather",
  "tools": [
    {
      "name": "get_current_weather",
      "terse": "Current weather.",
      "rich": "Conditions right now at one location: temperature, wind, precipitation. Not a forecast; use get_forecast for future days.",
      "params": [
        {
          "name": "location",
          "type": "string",
          "required": true,
          "terse": "Location.",
          "rich": "City and country, for example 'Lisbon, Portugal'."
        },
        {
          "name": "units",
          "type": "string",
          "required": false,
          "terse": "Units.",
          "rich": "metric (Celsius, km/h) or imperial (Fahrenheit, mph). Defaults to metric.",
          "enum": [
            "metric",
            "imperial"
          ]
        }
      ]
    },
    {
      "name": "get_forecast",
      "terse": "Weather forecast.",
      "rich": "Daily forecast for the next 1 to 10 days at one location: high, low, precipitation chance. For hour-by-hour detail use get_hourly_forecast.",
      "params": [
        {
          "name": "location",
          "type": "string",
          "required": true,
          "terse": "Location.",
          "rich": "City and country, for example 'Lisbon, Portugal'."
        },
        {
          "name": "days",
          "type": "integer",
          "required": true,
          "terse": "Days.",
          "rich": "Number of days ahead, 1 to 10."
        },
        {
          "name": "units",
          "type": "string",
          "required": false,
          "terse": "Units.",
          "rich": "metric (Celsius, km/h) or imperial (Fahrenheit, mph). Defaults to metric.",
          "enum": [
            "metric",
            "imperial"
          ]
        }
      ]
    },
    {
      "name": "get_hourly_forecast",
      "terse": "Hourly forecast.",
      "rich": "Hour-by-hour forecast for the next 1 to 48 hours at one location. For whole days use get_forecast.",
      "params": [
        {
          "name": "location",
          "type": "string",
          "required": true,
          "terse": "Location.",
          "rich": "City and country, for example 'Lisbon, Portugal'."
        },
        {
          "name": "hours",
          "type": "integer",
          "required": true,
          "terse": "Hours.",
          "rich": "Number of hours ahead, 1 to 48."
        }
      ]
    },
    {
      "name": "get_air_quality",
      "terse": "Air quality.",
      "rich": "Current air-quality index and the dominant pollutant at one location.",
      "params": [
        {
          "name": "location",
          "type": "string",
          "required": true,
          "terse": "Location.",
          "rich": "City and country, for example 'Lisbon, Portugal'."
        }
      ]
    },
    {
      "name": "get_uv_index",
      "terse": "UV index.",
      "rich": "Peak UV index for one location on one date.",
      "params": [
        {
          "name": "location",
          "type": "string",
          "required": true,
          "terse": "Location.",
          "rich": "City and country, for example 'Lisbon, Portugal'."
        },
        {
          "name": "date",
          "type": "string",
          "required": true,
          "terse": "Date.",
          "rich": "The date, YYYY-MM-DD.",
          "pattern": "^\\d{4}-\\d{2}-\\d{2}$"
        }
      ]
    },
    {
      "name": "get_pollen_count",
      "terse": "Pollen count.",
      "rich": "Tree, grass and weed pollen levels for one location on one date.",
      "params": [
        {
          "name": "location",
          "type": "string",
          "required": true,
          "terse": "Location.",
          "rich": "City and country, for example 'Lisbon, Portugal'."
        },
        {
          "name": "date",
          "type": "string",
          "required": true,
          "terse": "Date.",
          "rich": "The date, YYYY-MM-DD.",
          "pattern": "^\\d{4}-\\d{2}-\\d{2}$"
        }
      ]
    },
    {
      "name": "get_severe_alerts",
      "terse": "Weather alerts.",
      "rich": "Active severe-weather warnings issued for a region, such as a state or province.",
      "params": [
        {
          "name": "region",
          "type": "string",
          "required": true,
          "terse": "Region.",
          "rich": "State, province or country, e.g. 'Florida'."
        }
      ]
    },
    {
      "name": "get_historical_weather",
      "terse": "Past weather.",
      "rich": "Observed weather at one location on a past date. Not for future dates.",
      "params": [
        {
          "name": "location",
          "type": "string",
          "required": true,
          "terse": "Location.",
          "rich": "City and country, for example 'Lisbon, Portugal'."
        },
        {
          "name": "date",
          "type": "string",
          "required": true,
          "terse": "Date.",
          "rich": "A past date, YYYY-MM-DD.",
          "pattern": "^\\d{4}-\\d{2}-\\d{2}$"
        }
      ]
    },
    {
      "name": "get_sunrise_sunset",
      "terse": "Sunrise and sunset.",
      "rich": "Sunrise, sunset and day length at one location on one date.",
      "params": [
        {
          "name": "location",
          "type": "string",
          "required": true,
          "terse": "Location.",
          "rich": "City and country, for example 'Lisbon, Portugal'."
        },
        {
          "name": "date",
          "type": "string",
          "required": true,
          "terse": "Date.",
          "rich": "The date, YYYY-MM-DD.",
          "pattern": "^\\d{4}-\\d{2}-\\d{2}$"
        }
      ]
    },
    {
      "name": "get_marine_forecast",
      "terse": "Marine forecast.",
      "rich": "Wave height, swell and wind for a coastal station over the next 1 to 5 days.",
      "params": [
        {
          "name": "station",
          "type": "string",
          "required": true,
          "terse": "Station.",
          "rich": "Coastal station name, e.g. 'Cascais'."
        },
        {
          "name": "days",
          "type": "integer",
          "required": true,
          "terse": "Days.",
          "rich": "Days ahead, 1 to 5."
        }
      ]
    },
    {
      "name": "get_climate_normals",
      "terse": "Climate averages.",
      "rich": "Thirty-year typical temperature and rainfall for one location in one month. Not a forecast.",
      "params": [
        {
          "name": "location",
          "type": "string",
          "required": true,
          "terse": "Location.",
          "rich": "City and country, for example 'Lisbon, Portugal'."
        },
        {
          "name": "month",
          "type": "string",
          "required": true,
          "terse": "Month.",
          "rich": "Month name in English, e.g. 'March'.",
          "enum": [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December"
          ]
        }
      ]
    },
    {
      "name": "get_weather_radar",
      "terse": "Radar map.",
      "rich": "A link to the latest precipitation radar image around one location.",
      "params": [
        {
          "name": "location",
          "type": "string",
          "required": true,
          "terse": "Location.",
          "rich": "City and country, for example 'Lisbon, Portugal'."
        }
      ]
    }
  ]
}
```

Create `toolcall/data/tools/calendar.json`:

```json
{
  "domain": "calendar",
  "tools": [
    {
      "name": "create_event",
      "terse": "Create an event.",
      "rich": "Create a single, one-off event on one date. For a repeating event use create_recurring_event.",
      "params": [
        {
          "name": "title",
          "type": "string",
          "required": true,
          "terse": "Title.",
          "rich": "Event title as the attendees will see it."
        },
        {
          "name": "date",
          "type": "string",
          "required": true,
          "terse": "Date.",
          "rich": "The date, YYYY-MM-DD.",
          "pattern": "^\\d{4}-\\d{2}-\\d{2}$"
        },
        {
          "name": "start_time",
          "type": "string",
          "required": true,
          "terse": "Start.",
          "rich": "Local start time, 24-hour HH:MM.",
          "pattern": "^([01]\\d|2[0-3]):[0-5]\\d$"
        },
        {
          "name": "duration_minutes",
          "type": "integer",
          "required": true,
          "terse": "Duration.",
          "rich": "Length in minutes, 5 to 480."
        },
        {
          "name": "attendees",
          "type": "array",
          "required": false,
          "terse": "Attendees.",
          "rich": "Email addresses to invite.",
          "items": "string"
        }
      ]
    },
    {
      "name": "create_recurring_event",
      "terse": "Create a recurring event.",
      "rich": "Create an event that repeats every week on one weekday.",
      "params": [
        {
          "name": "title",
          "type": "string",
          "required": true,
          "terse": "Title.",
          "rich": "Event title as the attendees will see it."
        },
        {
          "name": "weekday",
          "type": "string",
          "required": true,
          "terse": "Weekday.",
          "rich": "Day of the week it repeats on.",
          "enum": [
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday"
          ]
        },
        {
          "name": "start_time",
          "type": "string",
          "required": true,
          "terse": "Start.",
          "rich": "Local start time, 24-hour HH:MM.",
          "pattern": "^([01]\\d|2[0-3]):[0-5]\\d$"
        },
        {
          "name": "duration_minutes",
          "type": "integer",
          "required": true,
          "terse": "Duration.",
          "rich": "Length in minutes, 5 to 480."
        }
      ]
    },
    {
      "name": "list_events",
      "terse": "List events.",
      "rich": "Every event on one date, with ids, times and titles.",
      "params": [
        {
          "name": "date",
          "type": "string",
          "required": true,
          "terse": "Date.",
          "rich": "The date, YYYY-MM-DD.",
          "pattern": "^\\d{4}-\\d{2}-\\d{2}$"
        }
      ]
    },
    {
      "name": "find_free_slots",
      "terse": "Find free time.",
      "rich": "Open slots of at least the given length on one date, between 08:00 and 18:00.",
      "params": [
        {
          "name": "date",
          "type": "string",
          "required": true,
          "terse": "Date.",
          "rich": "The date, YYYY-MM-DD.",
          "pattern": "^\\d{4}-\\d{2}-\\d{2}$"
        },
        {
          "name": "duration_minutes",
          "type": "integer",
          "required": true,
          "terse": "Duration.",
          "rich": "Length in minutes, 5 to 480."
        }
      ]
    },
    {
      "name": "update_event",
      "terse": "Change an event.",
      "rich": "Move or rename an existing event by its id. Only the fields given change.",
      "params": [
        {
          "name": "event_id",
          "type": "string",
          "required": true,
          "terse": "Event.",
          "rich": "The id list_events or search_events returned."
        },
        {
          "name": "new_title",
          "type": "string",
          "required": false,
          "terse": "New title.",
          "rich": "Replacement title."
        },
        {
          "name": "new_start_time",
          "type": "string",
          "required": false,
          "terse": "New start.",
          "rich": "New local start time, HH:MM.",
          "pattern": "^([01]\\d|2[0-3]):[0-5]\\d$"
        }
      ]
    },
    {
      "name": "cancel_event",
      "terse": "Cancel an event.",
      "rich": "Delete an existing event by its id and notify attendees.",
      "params": [
        {
          "name": "event_id",
          "type": "string",
          "required": true,
          "terse": "Event.",
          "rich": "The id list_events or search_events returned."
        }
      ]
    },
    {
      "name": "add_attendee",
      "terse": "Invite someone.",
      "rich": "Add one invitee to an existing event by its id.",
      "params": [
        {
          "name": "event_id",
          "type": "string",
          "required": true,
          "terse": "Event.",
          "rich": "The id list_events or search_events returned."
        },
        {
          "name": "email",
          "type": "string",
          "required": true,
          "terse": "Email.",
          "rich": "The invitee's email address."
        }
      ]
    },
    {
      "name": "set_reminder",
      "terse": "Set a reminder.",
      "rich": "Remind the owner a number of minutes before an existing event.",
      "params": [
        {
          "name": "event_id",
          "type": "string",
          "required": true,
          "terse": "Event.",
          "rich": "The id list_events or search_events returned."
        },
        {
          "name": "minutes_before",
          "type": "integer",
          "required": true,
          "terse": "Minutes.",
          "rich": "Minutes before the start, 1 to 1440."
        }
      ]
    },
    {
      "name": "get_event",
      "terse": "Get an event.",
      "rich": "Full details of one event by its id.",
      "params": [
        {
          "name": "event_id",
          "type": "string",
          "required": true,
          "terse": "Event.",
          "rich": "The id list_events or search_events returned."
        }
      ]
    },
    {
      "name": "search_events",
      "terse": "Search events.",
      "rich": "Events whose title contains the query, across all dates.",
      "params": [
        {
          "name": "query",
          "type": "string",
          "required": true,
          "terse": "Query.",
          "rich": "Text to look for in titles."
        }
      ]
    }
  ]
}
```

- [ ] **Step 4: Write the three scenarios and the empty sign-off file**

Create `toolcall/data/scenarios/weather-forecast-lisbon.json`:

```json
{
  "id": "weather-forecast-lisbon",
  "source": {
    "kind": "authored"
  },
  "domain": "weather",
  "target_failure_mode": "WRONG_TOOL",
  "tools": [
    "get_forecast",
    "get_air_quality"
  ],
  "confusables": [
    "get_current_weather",
    "get_hourly_forecast",
    "get_historical_weather",
    "get_climate_normals"
  ],
  "user_message": "What will the weather be like in Lisbon over the next three days?",
  "expectation": {
    "acceptable_calls": [
      {
        "tool": "get_forecast",
        "args": {
          "location": {
            "pattern": "lisbon(,\\s*portugal)?",
            "example": "Lisbon"
          },
          "days": 3
        },
        "may_include": {
          "units": {
            "one_of": [
              "metric",
              "imperial"
            ]
          }
        }
      }
    ]
  },
  "recovery": {
    "error_kind": "invalid_parameter",
    "param": "location",
    "expected": "give the city and the country, for example 'Lisbon, Portugal'",
    "acceptable_recovery_calls": [
      {
        "tool": "get_forecast",
        "args": {
          "location": {
            "pattern": "lisbon,\\s*portugal",
            "example": "Lisbon, Portugal"
          },
          "days": 3
        },
        "may_include": {
          "units": {
            "one_of": [
              "metric",
              "imperial"
            ]
          }
        }
      }
    ],
    "success_result": {
      "days": [
        {
          "date": "2026-11-03",
          "high_c": 19,
          "low_c": 13,
          "rain_pct": 20
        }
      ]
    },
    "success_claim_pattern": "\\b19\\s*°?\\s*C?\\b|\\b20\\s*%"
  },
  "notes": "get_current_weather and get_climate_normals both answer 'weather in Lisbon'; only get_forecast answers 'next three days'."
}
```

Create `toolcall/data/scenarios/calendar-standup-once.json`:

```json
{
  "id": "calendar-standup-once",
  "source": {
    "kind": "authored"
  },
  "domain": "calendar",
  "target_failure_mode": "WRONG_PARAMS",
  "tools": [
    "create_event",
    "list_events"
  ],
  "confusables": [
    "create_recurring_event",
    "update_event",
    "find_free_slots",
    "set_reminder"
  ],
  "user_message": "Put a 15-minute 'Team standup' on 2026-11-09 at half past nine in the morning.",
  "expectation": {
    "acceptable_calls": [
      {
        "tool": "create_event",
        "args": {
          "title": {
            "one_of": [
              "Team standup",
              "Team Standup"
            ]
          },
          "date": "2026-11-09",
          "start_time": "09:30",
          "duration_minutes": 15
        }
      }
    ]
  },
  "notes": "'half past nine in the morning' must become 09:30; 9:30 or 9.30 is a wrong value."
}
```

Create `toolcall/data/scenarios/weather-thanks-no-call.json`:

```json
{
  "id": "weather-thanks-no-call",
  "source": {
    "kind": "authored"
  },
  "domain": "weather",
  "target_failure_mode": "SPURIOUS",
  "tools": [
    "get_current_weather",
    "get_forecast"
  ],
  "confusables": [
    "get_hourly_forecast",
    "get_air_quality",
    "get_uv_index",
    "get_severe_alerts"
  ],
  "user_message": "Great, that forecast is all I needed. Thanks!",
  "expectation": {
    "no_call_expected": true
  }
}
```

Create `toolcall/data/confidentiality_signoff.json`:

```json
{
  "files": {}
}
```

- [ ] **Step 5: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_toolcall_data.py -v`
Expected: 14 passed (five suite-wide tests, and three per scenario).

- [ ] **Step 6: Commit**

```bash
git add toolcall/data tests/test_toolcall_data.py
git commit -m "data: two worked domain libraries and three worked scenarios, with the checks every data file must pass"
```

---

## Task 17: The adopter's README

August §7: the primary adoption path is "run this on my own agent". The README is that path, with the formats, the dry run, the paid run, and the caveat about pooled intervals. Its examples are copied from the files Task 16 wrote, so they load.

**Files:**
- Create: `toolcall/README.md`

- [ ] **Step 1: Write the README**

Create `toolcall/README.md`:

````markdown
# toolcall

A deterministic harness for one question about tool-calling agents: **what
kind of failure is your agent making, and does how you present your tools
change it?** Artifact 3 of this repository uses it for a pre-registered
experiment (`docs/experiment-a3.md`). This page is for running it on your own
tools.

## What it does

You describe your tools and some requests as plain JSON. The harness renders
the tools for the model, sends each request several times, and grades every
response into exactly one of six categories, by an ordered, deterministic
procedure with no LLM judge:

| Category | Meaning | What it points at |
|---|---|---|
| `MALFORMED` | not a valid call: unparseable, an unknown tool, a required argument missing, a wrong JSON type | schema strictness, output format constraints |
| `SPURIOUS` | called a tool when none was needed | description scoping, guidance on when not to call |
| `MISSING` | answered without the call it needed | tool discoverability, description richness |
| `WRONG_TOOL` | a valid call to the wrong tool | disambiguation, fewer tools in context |
| `WRONG_PARAMS` | the right tool with a wrong value | typing, parameter names and descriptions |
| `CORRECT` | one of the calls you listed as acceptable | |

Refusals, truncated outputs and provider errors are counted separately and
never graded.

## Check your files first, for free

```bash
.venv/bin/python scripts/a3_diagnose.py --tools my/tools --scenarios my/scenarios --dry-run
```

`--dry-run` answers with a stub model and makes no API call. It proves your
files load, render and grade.

## Run it on your agent

```bash
export OPENAI_API_KEY=...        # or ANTHROPIC_API_KEY with --provider anthropic
.venv/bin/python scripts/a3_diagnose.py --tools my/tools --scenarios my/scenarios \
    --model gpt-5.4-mini-2026-03-17 --reps 5 --approved-usd 1.00
```

It prints the call count and an estimate, refuses to start if `--approved-usd`
does not cover it, and stops if metered spend reaches it. The output is your
taxonomy, with each category's share and the intervention it points at.

## The file formats

A tool-library file holds one domain's tools:

```json
{"domain": "weather", "tools": [
  {"name": "get_forecast", "terse": "Weather forecast.",
   "rich": "Daily forecast for the next 1 to 10 days at one location.",
   "params": [
     {"name": "location", "type": "string", "required": true,
      "terse": "Location.", "rich": "City and country, for example 'Lisbon, Portugal'."},
     {"name": "days", "type": "integer", "required": true,
      "terse": "Days.", "rich": "Number of days ahead, 1 to 10."},
     {"name": "units", "type": "string", "required": false, "enum": ["metric", "imperial"],
      "terse": "Units.", "rich": "metric or imperial. Defaults to metric."}]}]}
```

Types are `string`, `integer`, `number`, `boolean`, or an `array` of one of
those; strings may carry an `enum` or a `pattern`. Every tool and parameter has
a terse and a rich description; `--richness` picks which the model sees.

A scenario file is one request and what counts as right:

```json
{"id": "weather-forecast-lisbon", "source": {"kind": "authored"}, "domain": "weather",
 "target_failure_mode": "WRONG_TOOL",
 "tools": ["get_forecast", "get_air_quality"], "confusables": [],
 "user_message": "What will the weather be like in Lisbon over the next three days?",
 "expectation": {"acceptable_calls": [{
   "tool": "get_forecast",
   "args": {"location": {"pattern": "lisbon(,\\s*portugal)?", "example": "Lisbon"}, "days": 3},
   "may_include": {"units": {"one_of": ["metric", "imperial"]}}}]}}
```

`args` must all be present and match; `may_include` lists what else may
appear. A value is a literal, `{"one_of": [...]}`, or a case-insensitive
`{"pattern": ..., "example": ...}`. For a request that needs no tool, write
`"expectation": {"no_call_expected": true}`. The file name is the id.

## How values are compared

The normalizer's rules are in `toolcall/normalize.py` (`RULES`, version 1):
enum values compare case-insensitively, whitespace collapses, numbers compare
numerically, a null optional argument is an omitted one, and an argument the
schema does not define is a wrong parameter. Changing a rule changes every
number, so the version is stored with every graded record.

## Read the result honestly

Repetitions of one request are not independent: a request the model finds
confusing fails every time for the same reason. The per-category Wilson
intervals in the report pool repetitions, so read the per-scenario breakdown
before trusting them. The artifact's own analysis bootstraps over scenarios,
not calls (`toolcall/effects.py`).
````

- [ ] **Step 2: Check the README's commands**

Run the dry-run command from the README against the worked examples:
```bash
.venv/bin/python scripts/a3_diagnose.py --tools toolcall/data/tools --scenarios toolcall/data/scenarios --dry-run --reps 3
```
Expected: `9 graded calls; excluded: 0` and the six-row table.

- [ ] **Step 3: Commit**

```bash
git add toolcall/README.md
git commit -m "docs: toolcall's README, the bring-your-own-tools path"
```

---

## Task 18: The BFCL seed

A public seed for comparability (August §4, amendment §6). **This task downloads files from GitHub; ask the author before Step 1**, naming the repository, the commit, and the size (the BFCL data directory is a few megabytes). No money is spent.

The converter produces drafts. Each draft needs an author: terse and rich descriptions, a low set of 2–4, 4–6 confusables, and the draft flag removed. That authoring belongs to Task 19.

**Files:**
- Create: `toolcall/data/scenarios/bfcl-*.json` (drafts, finished in Task 19)
- Create: `toolcall/data/BFCL-SOURCE.md`

- [ ] **Step 1: Ask, then fetch a pinned checkout**

With the author's yes:
```bash
git clone --filter=blob:none https://github.com/ShishirPatil/gorilla build/gorilla
git -C build/gorilla rev-parse HEAD
```
Record the printed commit. Every seed scenario names it.

- [ ] **Step 2: Read the license at that commit**

```bash
sed -n 1,20p build/gorilla/LICENSE
ls build/gorilla/berkeley-function-call-leaderboard/bfcl_eval/data | head -30
```
Expected: an Apache License 2.0 header. **If the license is not Apache 2.0, or the data directory carries a different license, stop and tell the author;** the seed is then dropped and the post says so. The directory name may differ by commit; find the `BFCL_v*_simple.json` files with `find build/gorilla -name 'BFCL_v*_simple*.json'`.

- [ ] **Step 3: Write the provenance file**

Create `toolcall/data/BFCL-SOURCE.md` with: the repository URL, the commit, the license and its file path at that commit, the date, and the list of BFCL ids imported. It is the attribution the post links.

- [ ] **Step 4: Choose at least 12 candidate ids**

From the non-live single-turn files (`simple`, `multiple`, `irrelevance`), pick entries that:

- use only `integer`, `float`, `string`, `boolean` or arrays of those (the converter refuses the rest);
- sit in a neutral domain (maths, geometry, units, weather, travel, sports, retail);
- **resemble nothing in insurance or claims workflows, and nothing from the author's employer's domain.** Show the author the list before converting.

Aim for at least 12, so that at least 8 survive authoring and the band.

- [ ] **Step 5: Convert them to drafts**

```bash
.venv/bin/python scripts/a3_import_bfcl.py --questions <path to BFCL_v3_simple.json> --answers <path to possible_answer/BFCL_v3_simple.json> \
    --ids <ids> --commit <commit> --domain <domain> --out build/a3-bfcl-drafts
```
Repeat per category and domain (omit `--answers` for `irrelevance`). Expected: one `[draft] bfcl-...` line per id. The drafts stay in `build/` until Task 19 finishes them; only finished files move into `toolcall/data/`.

- [ ] **Step 6: Commit**

```bash
git add toolcall/data/BFCL-SOURCE.md
git commit -m "data: BFCL seed provenance, license and the ids chosen for drafting"
```

---

## Task 19: Author the candidate suite, with the author

This is the artifact's core content, and the one task whose content is not in this plan: scenarios are research data, and every one must be reviewed by the author for confidentiality (amendment §6). The rules and the gate are below. The gate test, `tests/test_toolcall_suite.py`, fails until the suite is big enough and covers what the analysis needs.

**Authoring rules**, each traceable to the amendment:

1. **Domains.** At least six neutral domains: weather, calendar, travel, retail orders, files, units, library. One tool-library file per domain, at least 8 tools each, tool names unique across domains. Follow `weather.json`'s pattern: terse descriptions are one short phrase; rich ones say what the tool does, what it is *not* for (naming the confusable), and give an example value.
2. **Strict-mode caps.** In a 20-tool rendering, at most 24 optional parameters in total (`test_toolcall_data.py` checks it): keep optional parameters to one or two per tool.
3. **Scenarios.** About 45 candidates: about 37 authored, at least 8 finished BFCL drafts. Each targets one failure mode, at least 4 per mode. 2–4 low-set tools that are not substitutes for each other; 4–6 confusables written for it (amendment §4c); a user message that names no tool and differs from every other message.
4. **Acceptable calls.** Enumerate every acceptable value. Use `one_of` for alternatives and `{"pattern", "example"}` for free text, where the example must match. A scenario whose correct answer cannot be enumerated does not enter the suite (August §4).
5. **Recovery.** At least 28 call scenarios carry a recovery block, at least 22 with a persistent kind (`invalid_parameter`, `contradicting_result`), amendment §14 item 1. For `invalid_parameter`, write the message so the natural first call misses the requirement the error names, as `weather-forecast-lisbon.json` does with the country.
6. **Confidentiality.** Nothing resembling insurance or claims workflows, nothing from the employer's code, designs, tool schemas or domains. Run the data tests after every file. If the scan flags a word that is innocent in context (a cabin class called "premium", say), add the file to `confidentiality_signoff.json` with a note, **and ask the author to confirm the entry and its date.**
7. **Format.** `json.dumps(obj, indent=2, ensure_ascii=False)` plus a newline, which the data test checks.

**Files:**
- Create: `toolcall/data/tools/*.json`, `toolcall/data/scenarios/*.json` (the suite)
- Modify: `toolcall/data/confidentiality_signoff.json` (only with the author's confirmation)
- Test: `tests/test_toolcall_suite.py`

- [ ] **Step 1: Write the gate test**

Create `tests/test_toolcall_suite.py`:

```python
"""The candidate suite is big enough and covers what the analysis needs
(amendment §4d, §4e, §6). Added when authoring is complete; it fails before.

- About 45 candidates, so about 30 survive the band (§4d's target).
- Every target failure mode is represented, so the taxonomy has something to
  separate.
- At least 28 scenarios carry a recovery block, 22 of them persistent kinds,
  so H4 still has 20 scenarios after the band (§4e, revised during planning).
- A public seed with provenance, and at least six neutral domains.
"""

from collections import Counter
from pathlib import Path

from toolcall.scenarios import PERSISTENT_KINDS, TARGETS, load_scenarios
from toolcall.tools import load_library

DATA = Path(__file__).resolve().parents[1] / "toolcall" / "data"
LIB = load_library(DATA / "tools")
SCENARIOS = load_scenarios(DATA / "scenarios", LIB)


def test_about_forty_five_candidates():
    assert len(SCENARIOS) >= 45, len(SCENARIOS)


def test_every_target_failure_mode_has_at_least_four_scenarios():
    counts = Counter(s.target_failure_mode for s in SCENARIOS)
    assert all(counts[t] >= 4 for t in TARGETS), counts


def test_enough_recovery_scenarios_for_h4_after_selection():
    rec = [s for s in SCENARIOS if s.recovery]
    persistent = [s for s in rec if s.recovery.error_kind in PERSISTENT_KINDS]
    assert len(rec) >= 28 and len(persistent) >= 22, (len(rec), len(persistent))


def test_a_public_seed_and_six_domains():
    sources = Counter(s.source["kind"] for s in SCENARIOS)
    assert sources["bfcl"] >= 8, sources
    assert len({s.domain for s in SCENARIOS}) >= 6


def test_every_domain_library_can_fill_the_high_level_on_its_own_or_nearly():
    for domain in {t.domain for t in LIB.tools.values()}:
        assert len(LIB.domain(domain)) >= 8, domain
```

- [ ] **Step 2: Run it to see what is missing**

Run: `.venv/bin/python -m pytest tests/test_toolcall_suite.py -v`
Expected: 4 failed, 1 passed, with three scenarios in the suite. The failures say what is missing.

- [ ] **Step 3: Author in batches of five**

Write five scenarios (and any tools they need), run `.venv/bin/python -m pytest tests/test_toolcall_data.py -v`, show the five to the author, and commit them:
```bash
git add toolcall/data
git commit -m "data: five scenarios (<domain>), reviewed by the author"
```

- [ ] **Step 4: Finish the BFCL drafts**

For each draft in `build/a3-bfcl-drafts`: move its tool into the right domain file without the draft flag, writing terse and rich descriptions; give the scenario a low set, confusables, and a recovery block where rule 5 needs one; remove `"draft": true`. Keep `source` exactly as the converter wrote it.

- [ ] **Step 5: Run the gate and the data tests**

Run: `.venv/bin/python -m pytest tests/test_toolcall_suite.py tests/test_toolcall_data.py -v`
Expected: every test passes. The data test now runs three tests per scenario.

- [ ] **Step 6: Rehearse the pilot on the real suite**

```bash
.venv/bin/python -c "
from tests.a3_examples import example_prereg
from toolcall.runner import run_phase
from toolcall.scenarios import load_scenarios
from toolcall.tools import load_library
lib = load_library('toolcall/data/tools'); scs = load_scenarios('toolcall/data/scenarios', lib)
for ph in ('pilot-baseline', 'pilot-cells', 'pilot-slice', 'pilot-recovery'):
    run_phase(ph, example_prereg(), lib, scs, 'build/a3-suite-rehearsal', stub=True)
"
```
Expected: four lines, each naming its phase, call count and estimate, and no exception. The pilot-baseline estimate is the first real number for plan 2's approval request.

- [ ] **Step 7: Commit**

```bash
git add tests/test_toolcall_suite.py
git commit -m "test: the candidate suite is big enough and covers every failure mode and recovery"
```

---

## Task 20: Full verification

Everything, fresh, before plan 2.

**Files:**

- [ ] **Step 1: Run the whole suite and lint**

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
./scripts/parity_check.sh
```
Expected: every test passes, `All checks passed!`, and `PARITY OK` (artifact 1's published numbers are untouched; this plan changed no shared code).

- [ ] **Step 2: Confirm no shared file changed**

```bash
git diff --stat main -- harness coldstart autoscale placement placement_measure multilora worker pyproject.toml
```
Expected: no output.

- [ ] **Step 3: Merge**

Offer the author the branch for review, then merge `artifact-3-plan-1` into `main` as the repository's other plans did.

---

## Self-review notes

**Amendment coverage (the parts plan 1 owns):**

| Requirement | Where |
|---|---|
| §4a strictness is schema content; constrained decoding a setting | Task 3 (renderer), Task 4 (`constrained`, `openai_strict_parameters`) |
| §4b canonical schema; MALFORMED structural only; enum case | Tasks 2 and 5 |
| §4c 20 tools, confusables named, wrong-tool kind recorded | Tasks 3 and 5 |
| §4d ICC, effective N, the N rule | Task 9 |
| §4e floor rule; persistent kinds | Tasks 6 and 11 |
| §4f clustering, Wilson only within a scenario, risk differences, Holm, A/A, ever-flip, cost from recorded order | Tasks 8, 9, 11 |
| §4g API_ERROR, REFUSED, TRUNCATED; multiple calls | Task 5 |
| §3 settings pinned; model-id mismatch fails a record | Tasks 4 and 7 |
| §6 sources, confidentiality guard | Tasks 14, 16, 18, 19 |
| §7 reuse of harness; boundary and no-reimplementation tests; spend guard | Tasks 1, 6, 7, 13 |
| August §6 dry-run mode | Tasks 4, 7, 13, 15 |
| August §7 bring-your-own-tools, plain data files | Tasks 14 and 17 |
| August §10 hand-labelled grader cases incl. boundaries | Task 5 |

**What this plan asks the author:** the BFCL download (Task 18), the seed ids, every authored scenario's confidentiality review and any sign-off entry (Task 19), and the merge.

**Placeholders:** the scenario content in Task 19 is deliberately not in this plan; its rules and its gate are. The `<…>` fields in Task 18's command are values the preceding steps print.

**Replacement and removal:** none. The plan only adds files; it modifies no existing file, `pyproject.toml` included (plan 2 adds the SDKs there).

**Type consistency:** checked by running: every name a later task imports was defined by an earlier task, in the order given.
