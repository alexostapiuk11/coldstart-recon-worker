# Artifact 3 Plan 2 — Pilot and Pre-registration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Revise before executing.** Plan 1's execution changed interfaces this plan calls: `run_phase(sdks=...)`, the spend ledger and its lock, the STUB marker, pilot-recovery planning, `recovered_given_correct_first`, the openai/anthropic dependencies, and new pre-registration rules. Revise this plan against the real code at kickoff, using every "For plan 2" line in `2026-10-10-artifact-3-plan-1-deviations.md`.

**Goal:** Install the provider SDKs, confirm each pinned model accepts the registered settings with one call each, commit pre-registration step 1, run the paid pilot, compute S, N and the budget from it, and commit pre-registration step 2 before any campaign call.

**Architecture:** No new library code: plan 1 built and tested every module this plan calls. Three thin scripts drive it: `scripts/a3_smoke.py` (one call per model), `scripts/a3_run.py` (any phase, paid or `--stub`), and `scripts/a3_select.py` (step 2's values from the pilot). The pre-registered values live in `toolcall/prereg_values.py`; `docs/experiment-a3.md` embeds them, and a test fails if the two disagree. Pilot records are committed under `data/a3/` and are never campaign data.

**Tech Stack:** Python 3.13, pytest, the `openai` and `anthropic` SDKs (installed in Task 1), and plan 1's `toolcall/`.

**Spec:** [the amendment](../specs/2026-10-08-tool-calling-reliability-amendment.md), §3 (models and settings), §4d (S and N), §5 (two-step pre-registration) and §8 (budget), with §14's planning revisions.

**Plan 2 of 3.** [Plan 1](2026-10-08-artifact-3-plan-1-offline-core.md) built the code and the suite. [Plan 3](2026-10-08-artifact-3-plan-3-campaign-and-publication.md) runs the campaign and publishes.

**This plan spends money, a little.** The smoke check is 3 calls, under $0.01. The pilot is roughly 500 to 1,000 calls, **about $0.50 to $2**, depending on the suite's size; `scripts/a3_run.py` prints the exact estimate before each phase and refuses to start without an approval that covers it. **No paid call runs without the author's explicit yes in chat, stating the number of calls and the estimated cost.** API keys are set by the author in their own shell; they never appear in chat, in a file, or in a command this plan writes.

**How this plan was checked:** every script and test below was run on 2026-10-08 in a clone of `main` with plan 1's code in place. All four pilot phases and the step-2 computation ran end to end on the stub, against both the synthetic suite and the three worked examples; the step-2 script's refusal when too few candidates pass the band was exercised; the paid scripts' refusal without an approval was exercised; and a paid phase was driven through a fake SDK object to check the metering. The six files this plan creates were extracted from this document into a fresh clone with plan 1 extracted beside them, byte-identical to the tested sources; their tests passed and ruff was clean. The paid steps themselves, which need the live APIs, have not been run.

---

## Prerequisites — do not start before these are true

- [ ] **Plan 1 is complete and merged**, including Task 19's suite: `.venv/bin/python -m pytest tests/test_toolcall_suite.py -q` passes.
- [ ] **The §9b self-check has been offered** to the author before this plan starts (August §10's definition of done: learning modules before the corresponding build stage), and the outcome is recorded in `docs/learning/progress.md` under a new artifact 3 heading, whatever it was.
- [ ] **The amendment's §14 item 1 has the author's sign-off** (recovery scenarios at least 20).
- [ ] **`git status --porcelain` is empty**; work on a branch: `git checkout -b artifact-3-plan-2`.

---

## File structure

```
pyproject.toml                MODIFY: add openai and anthropic to dependencies
toolcall/prereg_values.py     CREATE: the pre-registered values, step 1 then step 2
tests/test_toolcall_prereg_values.py  CREATE: the document and the values agree
docs/experiment-a3.md         CREATE: the pre-registration, in two dated steps
scripts/a3_smoke.py           CREATE: one call per pinned model
scripts/a3_run.py             CREATE: run one phase, paid or --stub
scripts/a3_select.py          CREATE: step 2's values from the pilot
fixtures/a3/smoke/*.json      CREATED BY Task 2: the smoke check's requests and responses
data/a3/pilot-*.jsonl         CREATED BY Task 4: the pilot's records
data/a3/selection.json        CREATED BY Task 5: step 2's computed values
```

---
## Task 1: The provider SDKs

Plan 1 never imported an SDK at module level; `Client.post` imports them when a real call is made. **Installing them is a download from PyPI: ask the author first**, naming the two packages.

**Files:**
- Modify: `pyproject.toml` (the `dependencies` line)

- [ ] **Step 1: Ask, then install**

With the author's yes:
```bash
.venv/bin/pip install openai anthropic
.venv/bin/python -c "import openai, anthropic; print(openai.__version__, anthropic.__version__)"
```
Expected: two version numbers. Record them in Task 3's document.

- [ ] **Step 2: Add them to the dependencies**

In `pyproject.toml`, change the dependencies line to:
```toml
dependencies = ["anthropic", "matplotlib", "numpy", "openai", "requests", "safetensors"]
```

- [ ] **Step 3: Check nothing else moved**

Run: `.venv/bin/python -m pytest -q`
Expected: every test passes, the same count as before.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "build: the openai and anthropic SDKs, for artifact 3's paid runs"
```

---

## Task 2: Step 1's values, and one call per model

Step 1 registers each model's settings, and two of them cannot be known from the documentation alone (amendment §3, §13): whether `gpt-5.4-mini-2026-03-17` accepts `temperature: 0` with reasoning `none`, and whether each response names the pinned id. One call each answers both. The values file is written first because the smoke script reads it; both are committed together with the pre-registration in Task 3.

**Files:**
- Create: `toolcall/prereg_values.py`, `scripts/a3_smoke.py`
- Create (by running): `fixtures/a3/smoke/*.json`

- [ ] **Step 1: Write the step-1 values**

Create `toolcall/prereg_values.py`:

```python
"""The pre-registered values. Step 1 is committed before the pilot; step 2,
the fields after the marker, after the pilot and before the campaign.
docs/experiment-a3.md embeds `prereg_table(PREREG)`, and
tests/test_toolcall_prereg_values.py fails if the two disagree."""

from toolcall.prereg import Preregistration
from toolcall.providers import ModelSettings

PREREG = Preregistration(
    # --- step 1 ---
    primary=ModelSettings("openai", "gpt-5.4-mini-2026-03-17", 0.0, reasoning_effort="none"),
    slice_models=(
        ModelSettings("openai", "gpt-5.4-nano-2026-03-17", 0.0, reasoning_effort="none"),
        ModelSettings("anthropic", "claude-sonnet-5-5", None, thinking="between_tools"),
    ),
    baseline_cell="low-terse-loose",
    band=(0.10, 0.90),
    pilot_reps=10,
    pilot_cost_scenarios=10,
    pilot_cost_reps=5,
    delta2=0.02,
    identical_retry_floor=0.05,
    n_floor=5,
    n_cap=20,
    s_floor=24,
    alpha=0.05,
    iterations=10000,
    bootstrap_seed=20261008,
    schedule_seed=20261008,
    retry_cap=3,
    turn_budget=3,
    normalizer_version=1,
    # --- step 2 ---
)
```

- [ ] **Step 2: Write the smoke script**

Create `scripts/a3_smoke.py`:

```python
"""One call per pinned model, to fix the settings step 1 registers (plan 2 Task 2).

    .venv/bin/python scripts/a3_smoke.py --approved-usd 0.10

For each model in toolcall/prereg_values.py's step-1 settings, sends the first
scenario at the baseline formulation once and saves the request and the
response, or the error, under fixtures/a3/smoke/. It answers three questions
the pre-registration needs: is the request accepted with these settings (for
the primary, temperature 0 with reasoning none); does the response name the
pinned model id; and what does one call cost. About 3 calls, under $0.01.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from toolcall.formulation import BASELINE, render
from toolcall.guard import GuardedClient, SpendGuard, check_estimate
from toolcall.prereg_values import PREREG
from toolcall.prices import cost_usd
from toolcall.providers import PARSE, Client
from toolcall.runner import estimate_call_usd
from toolcall.scenarios import load_scenarios
from toolcall.tools import load_library

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--approved-usd", type=float, default=0.0)
    ap.add_argument("--out", type=Path, default=REPO / "fixtures" / "a3" / "smoke")
    args = ap.parse_args()
    lib = load_library(REPO / "toolcall" / "data" / "tools")
    sc = sorted(load_scenarios(REPO / "toolcall" / "data" / "scenarios", lib),
                key=lambda s: s.id)
    sc = next(s for s in sc if not s.no_call_expected)
    tools = render(sc, lib, BASELINE)
    models = (PREREG.primary, *PREREG.slice_models)
    ests = [estimate_call_usd(m, tools, sc.user_message) for m in models]
    print(f"{len(models)} calls, estimated ${sum(ests):.4f}; approved ${args.approved_usd:.2f}")
    check_estimate(sum(ests), args.approved_usd)
    args.out.mkdir(parents=True, exist_ok=True)
    guard = SpendGuard(args.approved_usd)
    for m in models:
        client = GuardedClient(Client(m), guard, PARSE[m.provider])
        body = client.request(tools, [{"role": "user", "text": sc.user_message}])
        record = {"settings": m.to_dict(), "scenario": sc.id, "request": body}
        try:
            response = client.post(body)
            parsed = PARSE[m.provider](response)
            record.update(response=response, accepted=True, returned_model=parsed.model,
                          model_matches=parsed.model == m.model, finish=parsed.finish,
                          cost_usd=cost_usd(m.model, parsed.usage))
        except Exception as e:  # noqa: BLE001 -- the error is the answer
            record.update(accepted=False, error=f"{type(e).__name__}: {e}")
        path = args.out / f"{m.model}.json"
        path.write_text(json.dumps(record, indent=2, sort_keys=True, default=str) + "\n")
        print(f"[{'ok' if record['accepted'] else 'REFUSED'}] {m.model}: "
              f"{record.get('returned_model', record.get('error'))}")
    print(f"metered spend: ${guard.spent:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Re-read the prices**

Open the three pages in `toolcall/prices.py` and confirm each price. `gpt-5.4-nano-2026-03-17`'s is marked `secondary`: if its page confirms it, change that entry's `check` to `"docs"`; if any price differs, correct it and its read date, and re-run `.venv/bin/python -m pytest tests/test_toolcall_campaign.py -v`.

- [ ] **Step 4: Ask the author for the keys and the approval**

Ask the author to set `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` in the shell this plan runs in (not in chat, not in a file). Then ask, in these words or close: **"The smoke check sends 3 calls, one per pinned model, estimated under $0.01. May I run it with --approved-usd 0.05?"** Wait for a yes.

- [ ] **Step 5: Run it (paid, under $0.01)**

```bash
.venv/bin/python scripts/a3_smoke.py --approved-usd 0.05
```
Expected: `3 calls, estimated $0.00…`, then one `[ok]` line per model naming the returned model id, then the metered spend.

- [ ] **Step 6: Read the answers and fix the settings**

Open each file in `fixtures/a3/smoke/`.

- `accepted: false` on the primary or nano with an error about `temperature`: set that model's temperature to `None` in `toolcall/prereg_values.py`. That is the provider default, which amendment §3 already allows and the post discloses. Re-run Step 5 for that model only, after asking again.
- `accepted: false` for any other reason: stop and show the author the error.
- `model_matches: false`: stop. The pin does not hold, and the amendment's §3 rule fails every such record.
- Compare each `response` with the matching hand-authored file in `tests/fixtures/a3/`: the fields `toolcall/providers.py` reads must be present under the same names. If one is not, the parser is wrong; fix it and its fixture before going on.

- [ ] **Step 7: Commit**

```bash
git add fixtures/a3/smoke
git commit -m "fixtures: artifact 3's smoke check, one call per pinned model"
```

---

## Task 3: Pre-registration step 1, committed before the pilot

Amendment §5. The git timestamp on this commit is the evidence the hypotheses, the selection band, the grading rules and the floors were fixed before the pilot existed. The table in the document is generated from `toolcall/prereg_values.py`, never typed.

**Files:**
- Create: `docs/experiment-a3.md`, `tests/test_toolcall_prereg_values.py`

- [ ] **Step 1: Write the test**

Create `tests/test_toolcall_prereg_values.py`:

```python
"""The pre-registration document and the values the code runs on are one thing.

- docs/experiment-a3.md embeds exactly `prereg_table(PREREG)`.
- The pinned models all have a pinned price.
- Once step 2 is committed: its values are the ones scripts/a3_select.py
  computed from the committed pilot, and every included scenario exists.
"""

import json
from pathlib import Path

import pytest

from toolcall.prereg import prereg_table
from toolcall.prereg_values import PREREG
from toolcall.prices import PRICES

REPO = Path(__file__).resolve().parents[1]
DOC = REPO / "docs" / "experiment-a3.md"
SELECTION = REPO / "data" / "a3" / "selection.json"


def test_the_document_embeds_the_values_exactly():
    assert prereg_table(PREREG) in DOC.read_text()


def test_every_pinned_model_has_a_pinned_price():
    for m in (PREREG.primary, *PREREG.slice_models):
        assert m.model in PRICES


@pytest.mark.skipif(not PREREG.step2_complete, reason="step 2 is not committed yet")
def test_step_two_is_what_the_pilot_computed():
    sel = json.loads(SELECTION.read_text())
    assert list(PREREG.included) == sel["included"]
    assert (PREREG.reps, PREREG.recovery_reps, PREREG.slice_reps) == (
        sel["reps"], sel["recovery_reps"], sel["slice_reps"])
    for sid in PREREG.included:
        assert (REPO / "toolcall" / "data" / "scenarios" / f"{sid}.json").is_file(), sid
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_toolcall_prereg_values.py -v`
Expected: FAIL with `FileNotFoundError` for `docs/experiment-a3.md`.

- [ ] **Step 3: Write the document**

The text below is step 1. Its parameter table is the output of this command, pasted in place; if Task 2 changed a temperature, the command prints the changed table, and that is what goes in:
```bash
.venv/bin/python -c "
from toolcall.prereg import prereg_table
from toolcall.prereg_values import PREREG
print(prereg_table(PREREG))
"
```

Add one line under "Models and settings" naming the SDK versions Task 1 printed.

Create `docs/experiment-a3.md`:

```markdown
# Artifact 3 — Pre-registration

Committed in two dated steps, as artifact 4's was. Step 1 is committed before
the pilot runs; step 2 after the pilot and before any campaign call. The git
timestamp on each step's commit, on this file and on
`toolcall/prereg_values.py`, is the evidence its values were fixed before the
data they govern existed. Design:
docs/superpowers/specs/2026-10-08-tool-calling-reliability-amendment.md, which
governs the 2026-08-17 design.

Nothing above an amendment heading is edited after its commit. Post-hoc changes
are numbered, dated amendments appended at the end, each committed before the
data it governs.

## Step 1 — fixed before the pilot

### Models and settings

- Primary: `gpt-5.4-mini-2026-03-17`, OpenAI Responses API, reasoning effort
  `none`, temperature as in the table below, 1,024 output tokens, provider
  strict mode off (`strict: false` sent on every tool), parallel tool calls
  off, `tool_choice` `auto`, `store` false.
- Slice, smaller: `gpt-5.4-nano-2026-03-17`, the same settings.
- Slice, frontier from a different provider: `claude-sonnet-5-5`, Messages API,
  thinking `between_tools`, no temperature (the API refuses one), strict off,
  parallel tool use disabled, `tool_choice` `auto`.
- The smoke check's request and response for each model are committed under
  `fixtures/a3/smoke/`, and are what the settings above were checked against.
- Prices: `toolcall/prices.py`, each with its source page and read date.

### Parameters

| parameter | value |
|---|---|
| `primary` | `{'provider': 'openai', 'model': 'gpt-5.4-mini-2026-03-17', 'temperature': 0.0, 'max_output_tokens': 1024, 'reasoning_effort': 'none', 'thinking': None, 'constrained': False}` |
| `slice_models` | `({'provider': 'openai', 'model': 'gpt-5.4-nano-2026-03-17', 'temperature': 0.0, 'max_output_tokens': 1024, 'reasoning_effort': 'none', 'thinking': None, 'constrained': False}, {'provider': 'anthropic', 'model': 'claude-sonnet-5-5', 'temperature': None, 'max_output_tokens': 1024, 'reasoning_effort': None, 'thinking': 'between_tools', 'constrained': False})` |
| `baseline_cell` | `'low-terse-loose'` |
| `band` | `(0.1, 0.9)` |
| `pilot_reps` | `10` |
| `pilot_cost_scenarios` | `10` |
| `pilot_cost_reps` | `5` |
| `delta2` | `0.02` |
| `identical_retry_floor` | `0.05` |
| `n_floor` | `5` |
| `n_cap` | `20` |
| `s_floor` | `24` |
| `alpha` | `0.05` |
| `iterations` | `10000` |
| `bootstrap_seed` | `20261008` |
| `schedule_seed` | `20261008` |
| `retry_cap` | `3` |
| `turn_budget` | `3` |
| `normalizer_version` | `1` |
| `included` | `None` |
| `reps` | `None` |
| `recovery_reps` | `None` |
| `slice_reps` | `None` |
| `approved_usd` | `None` |

### Hypotheses

Failure rate is the share of graded repetitions not `CORRECT`. Effects are risk
differences on that scale, in the 2³ contrasts of `toolcall/effects.py`. Every
p-value is a one-sided bootstrap p-value over scenarios.

- **H1.** The richness-by-count interaction on failure rate is negative: rich
  descriptions cut failures more at 20 tools than at 2–4.
- **H2.** Schema strictness's main effect on the `MALFORMED` + `WRONG_PARAMS`
  rate is negative, and its main effect on the `WRONG_TOOL` rate has a 90%
  interval inside ±`delta2`.
- **H3.** Tool count's main effect on the `WRONG_TOOL` rate is positive and
  exceeds the absolute main effects of richness and of strictness on it.
- **H4.** Over persistent error kinds and injected conversations, the
  identical-retry rate after an opaque error exceeds that after an actionable
  one. Not testable if the opaque rate is under `identical_retry_floor`, or if
  fewer than 20 included scenarios have conversations in both formats.
- **H5.** The absolute main effect of tool count on failure rate exceeds the
  absolute value of the same contrast computed between even- and odd-numbered
  repetitions of identical cells.

Holm's procedure at `alpha` runs across the testable hypotheses. H2 is
supported only if Holm rejects its first part and its equivalence part passes.
Anything else the post reports is labelled exploratory in those words.

### Rules fixed now

- **Selection.** Every candidate runs `pilot_reps` times in `baseline_cell`. A
  candidate is included if its correct rate lies in `band`, inclusive. Every
  candidate, its rate and its decision are published; excluded candidates stay
  in the repository. If fewer than `s_floor` are included, more are authored
  and piloted; the band is not widened.
- **Grading.** `toolcall/grader.py`'s ordered procedure, against each tool's
  canonical schema, with normalizer v1 (`toolcall/normalize.py`, rules R1–R8).
- **Exclusions.** `API_ERROR`, `REFUSED` and `TRUNCATED` are removed before any
  rate and counted per cell. A response naming a model other than the pinned
  one is an `API_ERROR`. No run is retried in place.
- **S and N.** S is every included scenario. N is the smallest number of
  repetitions reaching 95% of the effective-sample-size limit at the pilot's
  rho, between `n_floor` and `n_cap`, lowered to fit the approved budget but
  never below `n_floor` (`toolcall/budget.py`). Recovery and slice repetitions
  use the same N.
- **Best and worst cells.** The lowest and highest failure-rate point
  estimates in the campaign. Recovery runs in the baseline and best cells, the
  slice in the best and worst, the exploratory constrained-decoding run in the
  best.
- **Statistics.** Cluster bootstrap over scenarios, `iterations` draws,
  `bootstrap_seed`; Wilson intervals only within one scenario.
- **Cost per successful call.** From each call's usage at the pinned prices;
  the retry policy walks each scenario's repetitions in recorded order, up to
  `retry_cap` attempts.
- **Spend.** Every paid phase needs an explicit approved amount from the
  author, stated with its call count, and stops when metered spend reaches it.
- **Confidentiality.** No scenario resembles insurance or claims workflows or
  the author's employer's domain; `tests/test_toolcall_data.py` scans every
  data file.
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_toolcall_prereg_values.py -v`
Expected: 2 passed, 1 skipped (step 2 is not committed yet).

- [ ] **Step 5: Read it once for the employer boundary**

Read the whole document for anything traceable to the author's employer. There should be nothing; it describes public models and synthetic scenarios.

- [ ] **Step 6: Commit**

```bash
git add docs/experiment-a3.md toolcall/prereg_values.py scripts/a3_smoke.py tests/test_toolcall_prereg_values.py
git commit -m "prereg: artifact 3 step 1, committed before the pilot"
```

---

## Task 4: The pilot (paid, about $0.50 to $2)

Four phases (`toolcall/runner.py`'s table): every candidate at the baseline formulation, ten candidates in all eight cells to price each cell, ten calls per slice model to price them, and a few recovery conversations to price one. Each goes to its own store and none is ever campaign data.

**Files:**
- Create: `scripts/a3_run.py`
- Create (by running): `data/a3/pilot-*.jsonl`

- [ ] **Step 1: Write the runner script**

Create `scripts/a3_run.py`:

```python
"""Run one phase of artifact 3, paid or rehearsed.

    .venv/bin/python scripts/a3_run.py pilot-baseline --approved-usd 1.00
    .venv/bin/python scripts/a3_run.py campaign --stub          # rehearsal, no API call

Phases, in order: pilot-baseline, pilot-cells, pilot-slice, pilot-recovery
(plan 2); campaign, recovery, slice, exploratory (plan 3). A paid phase prints
its call count and estimate, then refuses to start unless --approved-usd covers
the estimate, and stops if real spend reaches it. --stub runs the same path on
the stub model and writes to build/a3-rehearsal instead of data/a3.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from toolcall.guard import SpendCapReached
from toolcall.prereg_values import PREREG
from toolcall.runner import PHASES, run_phase
from toolcall.scenarios import load_scenarios
from toolcall.tools import load_library

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "toolcall" / "data"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=PHASES)
    ap.add_argument("--approved-usd", type=float, default=0.0)
    ap.add_argument("--stub", action="store_true")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--suite", type=Path, default=DATA, help="tools/ and scenarios/ beneath")
    args = ap.parse_args()
    library = load_library(args.suite / "tools")
    scenarios = load_scenarios(args.suite / "scenarios", library)
    out = args.out or (REPO / "build" / "a3-rehearsal" if args.stub else REPO / "data" / "a3")
    try:
        result = run_phase(args.phase, PREREG, library, scenarios, out,
                           approved_usd=args.approved_usd, stub=args.stub, resume=args.resume)
    except SpendCapReached as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    for path in result["stores"]:
        print(f"[ok] {path}")
    if "spent_usd" in result:
        print(f"metered spend this phase: ${result['spent_usd']:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Rehearse all four phases on the stub**

```bash
for p in pilot-baseline pilot-cells pilot-slice pilot-recovery; do
  .venv/bin/python scripts/a3_run.py $p --stub
done
```
Expected: per phase, a line naming the phase, its model, its call count and its estimate, then `[ok]` lines under `build/a3-rehearsal/`. Write down the four call counts and estimates.

- [ ] **Step 3: Ask for the approval**

Ask, with the numbers from Step 2: **"The pilot sends <total> calls in four phases (<counts>), estimated $<total>. May I run it with --approved-usd <estimate rounded up, plus 25%>?"** Wait for a yes. Use one approval per phase if the author prefers.

- [ ] **Step 4: Run the four phases (paid)**

```bash
APPROVED=<the approved amount, split per phase as agreed>
.venv/bin/python scripts/a3_run.py pilot-baseline --approved-usd $APPROVED
.venv/bin/python scripts/a3_run.py pilot-cells --approved-usd $APPROVED
.venv/bin/python scripts/a3_run.py pilot-slice --approved-usd $APPROVED
.venv/bin/python scripts/a3_run.py pilot-recovery --approved-usd $APPROVED
```
Expected per phase: the announcement, `[ok]` per store, and `metered spend this phase: $…`. A `refused:` line means the estimate exceeded the approval: stop and ask again; never raise the number unasked. If a phase stops part-way (`SpendCapReached`, or a crash), re-run it with `--resume`; the campaign loop skips what is stored and refuses a drifted schedule.

- [ ] **Step 5: Look at what came back**

```bash
.venv/bin/python -c "
from collections import Counter
from harness.store import JsonlStore
from toolcall.records import CallRecord
for name in ('pilot-baseline', 'pilot-cells'):
    rs = JsonlStore(f'data/a3/{name}.jsonl', CallRecord).read_all()
    print(name, len(rs), Counter(r.grade['category'] for r in rs))
"
```
Expected: every category appears somewhere in `pilot-cells`, and `API_ERROR`, `REFUSED` and `TRUNCATED` are rare. If `TRUNCATED` is common, the 1,024-token cap is too low for these responses: stop and tell the author, because changing it is a step-1 change and needs an amendment.

- [ ] **Step 6: Commit**

```bash
git add scripts/a3_run.py data/a3/pilot-baseline.jsonl data/a3/pilot-cells.jsonl data/a3/pilot-slice-*.jsonl data/a3/pilot-recovery.jsonl
git commit -m "data: artifact 3's pilot, four phases, never campaign data"
```

---

## Task 5: Step 2's values, from the pilot

`scripts/a3_select.py` applies the band fixed at step 1, estimates rho on the included candidates, picks N by amendment §4d's rule, prices every line of the campaign from measured cost per call, and checks that the spend guard's input bound held on every pilot call (§14 item 5). It spends nothing.

**Files:**
- Create: `scripts/a3_select.py`
- Create (by running): `data/a3/selection.json`

- [ ] **Step 1: Write the script**

Create `scripts/a3_select.py`:

```python
"""Pre-registration step 2's values, computed from the pilot (plan 2 Task 5).

    .venv/bin/python scripts/a3_select.py

Reads data/a3/pilot-*.jsonl, applies the band fixed at step 1, estimates rho,
picks N by amendment §4d's rule, prices the campaign from measured cost per
call, and writes data/a3/selection.json. Prints the selection table and the
budget table that docs/experiment-a3.md's step 2 embeds. Spends nothing.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.store import JsonlStore
from toolcall.prereg_values import PREREG
from toolcall.records import CallRecord, RecoveryRecord
from toolcall.scenarios import load_scenarios
from toolcall.selection import step2_proposal
from toolcall.tools import load_library

REPO = Path(__file__).resolve().parents[1]


def main(data: Path = REPO / "data" / "a3") -> int:
    lib = load_library(REPO / "toolcall" / "data" / "tools")
    scenarios = load_scenarios(REPO / "toolcall" / "data" / "scenarios", lib)
    pilot = {
        "baseline": JsonlStore(data / "pilot-baseline.jsonl", CallRecord).read_all(),
        "cells": JsonlStore(data / "pilot-cells.jsonl", CallRecord).read_all(),
        "recovery": JsonlStore(data / "pilot-recovery.jsonl", RecoveryRecord).read_all(),
        "slice": {m.model: JsonlStore(data / f"pilot-slice-{m.model}.jsonl",
                                      CallRecord).read_all() for m in PREREG.slice_models},
    }
    p = step2_proposal(pilot, scenarios, PREREG)
    (data / "selection.json").write_text(json.dumps(p, indent=1, sort_keys=True) + "\n")
    print(p["selection_table"], "\n")
    if not p["enough_scenarios"]:
        print(f"STOP: {len(p['included'])} of {p['candidates']} candidates are inside the band, "
              f"below s_floor {PREREG.s_floor}. Author more candidates and pilot them; do not "
              "widen the band (amendment §13).")
        return 1
    print(f"candidates {p['candidates']}, included {len(p['included'])}, rho {p['rho']:.3f}, "
          f"N {p['reps']}, recovery scenarios {p['recovery_scenarios']}\n")
    print(p["budget_table"])
    if not p["enough_recovery_scenarios"]:
        print("\nNOTE: fewer than 20 included recovery scenarios; H4 will be not testable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "data" / "a3"))
```

- [ ] **Step 2: Run it**

```bash
.venv/bin/python scripts/a3_select.py
```
Expected: the selection table (every candidate, its rate, its Wilson interval and its decision), a summary line with the included count, rho, N and the recovery-scenario count, then the budget table with a total and a 25% contingency line.

- [ ] **Step 3: If it stops**

- `STOP: … below s_floor`: author more candidates (plan 1 Task 19's rules), then pilot **all** candidates again into a fresh directory, `data/a3/pilot-round-2/`, with `scripts/a3_run.py pilot-baseline --out data/a3/pilot-round-2` (paid; ask first), and run `scripts/a3_select.py data/a3/pilot-round-2`. Record the second round as Amendment 1 in `docs/experiment-a3.md`, saying why. **Never widen the band** (amendment §13).
- `ValueError: the spend guard's input bound failed`: stop. Show the author which calls broke the bound; raising `CHARS_PER_TOKEN_BOUND`'s margin is a change to `toolcall/guard.py` with its own test, before any campaign spend.
- `NOTE: fewer than 20 included recovery scenarios`: H4 will be reported as not testable. Tell the author; authoring more recovery blocks and re-piloting is their call.

- [ ] **Step 4: Check the total against the target**

If the budget table's total with contingency exceeds $60, apply amendment §8's cut order, in order, until it fits: the exploratory slice; the slice's N down to the floor; recovery's second formulation; the main N down to the floor. Each cut is a step-2 value (for the first and third, note them in the document's step 2; the code runs the phases the document names). Never cut S, and never a factor's second level.

- [ ] **Step 5: Commit**

```bash
git add scripts/a3_select.py data/a3/selection.json
git commit -m "data: artifact 3's selection, rho, N and budget, computed from the pilot"
```

---

## Task 6: Pre-registration step 2, committed before the campaign

The step-2 commit fixes the included scenarios, N, and the approved spend before any campaign call. The step-1 text above it is not edited.

**Files:**
- Modify: `toolcall/prereg_values.py` (the step-2 fields)
- Modify: `docs/experiment-a3.md` (append step 2)

- [ ] **Step 1: Ask for the campaign approval**

Show the author the budget table from Task 5 and ask: **"The campaign, recovery, slice and exploratory phases are <calls> calls, estimated $<total>, $<with contingency> with 25% contingency. Do you approve $<amount> for plan 3's paid phases?"** The amount they approve is `approved_usd`. Plan 3 still asks again before each phase.

- [ ] **Step 2: Fill in step 2**

Add the step-2 fields to `toolcall/prereg_values.py`, after the `# --- step 2 ---` marker, from `data/a3/selection.json` and the approval:
```python
    # --- step 2 ---
    included=(  # every id selection.json lists under "included", in its order
        "...",
    ),
    reps=...,           # selection.json "reps"
    recovery_reps=...,  # selection.json "recovery_reps"
    slice_reps=...,     # selection.json "slice_reps"
    approved_usd=...,   # the amount the author approved in Step 1
)
```

- [ ] **Step 3: Append step 2 to the document**

Append, below the last step-1 line and nothing above it:
```markdown
## Step 2 — fixed after the pilot, before the campaign

The pilot ran on <dates>, in four phases (`data/a3/pilot-*.jsonl`), and cost
$<metered> metered. `scripts/a3_select.py` computed everything below from it;
its output is `data/a3/selection.json`.

### Selection

<the selection table a3_select printed: every candidate, its rate, its Wilson
interval and its decision>

<included> of <candidates> candidates are included. rho on the included
candidates is <rho>, so N = <N> by the rule in "Rules fixed now".
<recovery> included scenarios carry a recovery block.

### Budget

<the budget table a3_select printed>

The author approved $<amount> for plan 3's paid phases on <date>, in chat.
<any cut from amendment §8's order, and why; or "Nothing is cut.">

### Parameters as of step 2

<the output of the table command below>
```
The table command:
```bash
.venv/bin/python -c "
from toolcall.prereg import prereg_table
from toolcall.prereg_values import PREREG
print(prereg_table(PREREG))
"
```

- [ ] **Step 4: Run the agreement test**

Run: `.venv/bin/python -m pytest tests/test_toolcall_prereg_values.py -v`
Expected: 3 passed. The step-2 test now runs and checks the values against `selection.json`.

- [ ] **Step 5: Confirm no campaign data exists**

```bash
ls data/a3/
```
Expected: only `pilot-*` files and `selection.json`. If a `campaign.jsonl` exists, stop: step 2 must precede it.

- [ ] **Step 6: Commit**

```bash
git add toolcall/prereg_values.py docs/experiment-a3.md
git commit -m "prereg: artifact 3 step 2, committed before the campaign"
```

- [ ] **Step 7: Full check, then merge**

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
```
Expected: every test passes and `All checks passed!`. Offer the branch for review and merge it.

---

## Self-review notes

**Amendment coverage (the parts plan 2 owns):**

| Requirement | Where |
|---|---|
| §3 settings confirmed on the live APIs; pinned ids returned | Task 2 |
| §5 step 1 before the pilot; step 2 before the campaign | Tasks 3 and 6, each a separate commit; Task 6 Step 5 checks the order |
| §4d S and N from the pilot's rho | Task 5 (`step2_proposal`, tested in plan 1 Task 13) |
| §8 budget from measured cost per call; cut order | Task 5 |
| §14 item 5 the guard's bound checked against real usage | Task 5 |
| Selection band fixed before the pilot; every candidate published | Tasks 3 and 6 |
| No paid call without the author's yes stating calls and cost | Tasks 2, 4 and 6, each an explicit ask before running |

**What this plan asks the author:** the SDK download, the API keys (set in their own shell), the smoke approval, the pilot approval, the campaign budget, and the merge.

**Placeholders:** the `<…>` fields are numbers the preceding step prints, or the author's approved amount. No design decision is left open.

**Replacement and removal:** none. `pyproject.toml` gains two dependencies; nothing else that exists is modified.
