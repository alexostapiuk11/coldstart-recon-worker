# Harness Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the artifact-agnostic half of `coldstart/` into a `harness/` package so artifacts 2–5 inherit the measurement plumbing, statistics, publishability gate, and figure guard rails without inheriting artifact 1's cold-start vocabulary.

**Architecture:** Modules move by `git mv` into `harness/`, one module (or one split) per task, with imports rewritten across `coldstart/`, `worker/`, `scripts/`, and `tests/` in the same commit. Four modules are *split* rather than moved, because they mix generic machinery with artifact-1 constants: `pipeline.py` (machinery vs. `REQUIRED_FOR_*` presets), `checks.py` (failure taxonomy vs. clock reconciliation), `preflight.py` (the check vs. the pinned endpoint), and `figures.py` (guard rails vs. the four charts). Three modules are *generalized* where an artifact-1 name is hardcoded in a way that would block reuse: `JsonlStore` takes a record class, `build_schedule` speaks conditions/blocks instead of arms/triples, and the grouping functions take an explicit key. Everything else moves verbatim — the YAGNI line is that a name is generalized only when it would otherwise make artifact 2 or 5 store the wrong thing or group by the wrong column.

**The invariant that makes this safe:** `harness/` must never import `coldstart`. A test enforces the direction (Task 3), and every task ends with a parity gate that re-derives artifact 1's published numbers and re-renders its four figures.

**Tech Stack:** Python 3.13 (stdlib only in the moved modules, plus `requests` for the RunPod client and `matplotlib` for figures), pytest, ruff.

**Scope:** Refactor only. No behavior change is intended anywhere. Three signature changes are deliberate and logged in Task 1's decision log; everything else keeps its exact semantics, and the parity gate is what proves it.

---

## Prerequisite — do not start before this is true

The portfolio contract (artifact 1 spec §3) states that artifact 2 runs against the harness **"tagged at the commit that produced artifact 1's numbers."**

- [ ] Artifact 1's post is published at its permanent slug.
- [ ] A tag exists at the commit that produced the published numbers:

```bash
git tag -a artifact-1-published -m "Harness and data as published for artifact 1" && git push origin artifact-1-published
```

- [ ] `git status --porcelain` is clean.

The tag is the reader's reproduction path. This plan changes import paths throughout the repo, so anyone re-running artifact 1 exactly as published uses the tag; `main` carries the refactored harness. Do not re-pin `docs/experiment.md`'s image digest — it names the image the campaign actually ran on and is historical.

---

## File structure after this plan

```
harness/                    artifact-agnostic — the thing artifacts 2-5 import
  __init__.py               empty
  stats.py                  medians, percentiles, ECDF, bootstrap CIs, paired units
  publish.py                partition/publishability gate, failure + discard tables
  figure_guards.py          empty-input, missing-field, phone-legibility guards
  store.py                  append-only JSONL, record class injected
  scheduler.py              interleaved randomized blocks
  recorder.py               clock B: monotonic stage marks
  failures.py               failure taxonomy + string classifier
  vllm_logs.py              engine-log parser (stages, KV blocks, engine info)
  submit.py                 SubmitOutcome protocol + StubSubmitter
  runpod/
    __init__.py             empty
    api.py                  job lifecycle extraction
    submitter.py            HttpTransport + RunPodSubmitter
    preflight.py            assert_endpoint_matches, fetch_endpoint

coldstart/                  artifact 1 only
  __init__.py               SCHEMA_VERSION
  schema.py                 RunRecord
  driver.py                 A1 campaign orchestration + record assembly
  cache_config.py           A1 arms' cold/warm cache directories
  checks.py                 DiscardReason, compute_residual, check_consistency
  pins.py                   NEW — the pinned RunPod endpoint configuration
  stubs/                    A1 stub endpoint and engine
  analysis/
    metrics.py              A1 derive()
    economics.py            A1 business framing
    figures.py              the four body figures
    presets.py              NEW — REQUIRED_FOR_* publishability presets
```

Deleted by the end of this plan (moved, not dropped): `coldstart/analysis/stats.py`, `coldstart/analysis/pipeline.py`, `coldstart/store.py`, `coldstart/scheduler.py`, `coldstart/recorder.py`, `coldstart/vllm_logs.py`, `coldstart/submitter.py`, `coldstart/runpod_api.py`, `coldstart/runpod_submitter.py`, `coldstart/preflight.py`.

---

## Task 1: Capability inventory and keep/drop decision log

**Files:**
- Create: `docs/superpowers/plans/2026-09-03-harness-extraction-inventory.md`

The inventory below was built by reading the modules, not by trusting a description. **Verify each row against the code before committing it** — a capability that exists but is missing from this table is the failure mode this task exists to prevent.

- [ ] **Step 1: Verify the inventory against the code**

Run the symbol dump and check every public name appears in the table below:

```bash
grep -n "^def \|^class \|^[A-Z_]* *[:=]" coldstart/*.py coldstart/analysis/*.py | grep -v "^.*:.*_[a-z]" | sed 's/(.*//'
```

- [ ] **Step 2: Write the inventory document**

Create `docs/superpowers/plans/2026-09-03-harness-extraction-inventory.md` with this content:

````markdown
# Harness Extraction — Capability Inventory and Decision Log

Built by reading `coldstart/` at commit `artifact-1-published`. Every capability
below carries an explicit decision. A capability in neither column is a planning bug.

## Moved to harness verbatim — behavior unchanged

| Capability | From | To |
|---|---|---|
| `median` (bootstrap-floor-exempt), `percentiles`, `ecdf` | `analysis/stats.py` | `harness/stats.py` |
| `bootstrap_median_diff`, `bootstrap_contrast_difference` | `analysis/stats.py` | `harness/stats.py` |
| `bootstrap_paired_median_diff`, `bootstrap_paired_contrast_difference` | `analysis/stats.py` | `harness/stats.py` |
| `within_host_triples` (paired units within a host) | `analysis/stats.py` | `harness/stats.py` |
| `MIN_SAMPLES`, `MIN_BOOTSTRAP_SAMPLES` sample floors | `analysis/stats.py` | `harness/stats.py` |
| `_quantile`/`_median` percentile convention | `analysis/stats.py` | `harness/stats.py` |
| `parse_engine_log`, `ParsedLog`, phase patterns, merged-phase reporting | `vllm_logs.py` | `harness/vllm_logs.py` |
| `StageRecorder`: `start`/`mark`/`now`/`at`/`duration`/`bundle`, duplicate-mark refusal, wall-clock-never-used-for-arithmetic rule | `recorder.py` | `harness/recorder.py` |
| `FailureClass` (9 members), `_Needle` regex-vs-substring matching, `_SIGNATURES` priority order, `classify_failure` first-match-wins | `checks.py` | `harness/failures.py` |
| `SubmitOutcome` (incl. `diagnostics` for failed-but-reporting runs), `StubSubmitter` | `submitter.py` | `harness/submit.py` |
| `extract_lifecycle`, `residual_splittable`, `extract_worker_id`, `TERMINAL_STATES` | `runpod_api.py` | `harness/runpod/api.py` |
| `HttpTransport` (409/5xx retry), `RunPodSubmitter`, `_UnhealthyRun` | `runpod_submitter.py` | `harness/runpod/submitter.py` |
| `fetch_endpoint` (deliberately unretried), `PreflightError`, `REST` | `preflight.py` | `harness/runpod/preflight.py` |
| `partition`, `PartitionResult`, `NotPublishableError`, `_missing_required` (`consistent is True` check), `_exclusion_labels` (closed-category reasons) | `analysis/pipeline.py` | `harness/publish.py` |
| `annotate_first_touch` (first-run-on-host marking, ordered by `run_index`) | `analysis/pipeline.py` | `harness/publish.py` |
| `PHONE_WIDTH_PX`, `MIN_PHONE_TEXT_PX`, `phone_pt` | `analysis/figures.py` | `harness/figure_guards.py` |
| `_validate_rows` (empty-input refusal), `_required_field` (missing/None → `NotPublishableError`), `_row_identity` | `analysis/figures.py` | `harness/figure_guards.py` |
| append-only `JsonlStore.append`, truncated-line diagnostic in `read_all` | `store.py` | `harness/store.py` |
| interleaved-randomized-within-block schedule, seeded RNG order | `scheduler.py` | `harness/scheduler.py` |

## Moved with a deliberate signature change — sign-off required

| Capability | Change | Why |
|---|---|---|
| `JsonlStore(path)` | → `JsonlStore(path, record_cls)` | The store hardcoded `RunRecord`. A second artifact stores a different record shape through the same file discipline. `record_cls` needs only `to_dict()` / `from_dict()`. |
| `build_schedule(arms, triples, seed)` → `ScheduledRun(run_index, triple_index, arm)` | → `build_schedule(conditions, blocks, seed)` → `ScheduledRun(run_index, block_index, condition)` | "Arm" and "triple" are artifact 1's vocabulary. Artifact 5's two regimes and artifact 4's three placement strategies are the same structure under different names. **RNG consumption order is unchanged, so an identical seed yields an identical schedule.** `coldstart/driver.py` maps back to `arm`/`triple_index`, so the stored JSONL is byte-identical. |
| `failure_rate_by_arm(rows)` / `discard_table(rows)` | → `failure_rate_by_group(rows, key)` / `discard_table(rows, key)`, **no default** | Grouping was hardcoded to `row["arm"]`. A default of `"arm"` would let artifact 2 group by a column it does not have and silently emit a one-bucket table; requiring the key fails closed, matching `assert_endpoint_matches`'s existing refusal to check nothing. |
| `assert_endpoint_matches(endpoint, pinned=None)` defaulting to module-level `PINNED` | → `assert_endpoint_matches(endpoint, pinned)`, required | `PINNED` is artifact 1's endpoint, not a harness fact. It moves to `coldstart/pins.py`; the two call sites pass it explicitly. The `if not pinned: raise` guard against checking nothing is preserved. |

**Sign-off:** these four are caller-observable. Confirm before Task 8 begins.

## Stays in coldstart — artifact 1 specific, deliberately not generalized

| Capability | Why it does not move |
|---|---|
| `RunRecord` (clock A/B/C, warmup, arm, engine, host, config, status) | The shape of one cold start. Other artifacts get their own record. |
| `SCHEMA_VERSION` | Versions artifact 1's record, not the harness. |
| `compute_residual`, `check_consistency`, `DEFAULT_RTT_FLOOR`, `ConsistencyResult` | Reconciles clock A against clock B for artifact 1's stage taxonomy. |
| `DiscardReason` (5 members, incl. `ARM_STATE_*`) | Outputs of artifact 1's own checks. `harness/publish.py` reads `.value` off whatever enum a row carries, so no import is needed. |
| `metrics.derive` and every `S4`/`T_fast`/`T_weights` derivation | The cold-start decomposition itself. |
| `economics.py` (foregone tokens, cost per scale-up, break-even) | Artifact 1's business framing. Artifacts 4/5 need cost per tenant per month — a different formula. |
| `figures.py` waterfall / warmup / ECDF / per-host, `S4_SUBPHASE_KEYS`, `ARMS`, colors | Artifact 1's four charts. |
| `REQUIRED_FOR_*` presets | Name artifact 1's fields (`t_weights`, `t_compile`, `t_fast_seconds`). Move to `coldstart/analysis/presets.py`. |
| `cache_config.py` (`CACHE_CONFIGS`, `resolve`) | Encodes arms A/B/C's cold/warm directories. Artifact 4 may want something like it; it does not want this. |
| `driver.py` (`run_campaign`, `_record_from`, resume drift guard) | Assembles a `RunRecord`. The orchestration shape may generalize later; nothing needs it yet. |
| `stubs/` (`StubEndpoint`, `VirtualClock`, `stub_engine`) | Replays artifact 1's captured engine logs. |
| `worker/` (`handler.py`, `probe.py`, `recon_handler.py`) | The artifact 1 measurement worker. |

## Intentionally dropped

Nothing. This is a move, not a rewrite: every capability above is either relocated or retained in place.
````

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/plans/2026-09-03-harness-extraction-inventory.md
git commit -m "docs: inventory what coldstart does before splitting it"
```

---

## Task 2: Fidelity baseline and a reusable parity gate

**Files:**
- Create: `scripts/parity_check.sh`
- Create: `docs/superpowers/plans/2026-09-03-harness-extraction-baseline.md`

Artifact 1's analysis is fully seeded (`bootstrap_*` take explicit `seed=`), and its figures render deterministically. Both were confirmed byte-reproducible before this plan was written, which is what makes an exact-match gate possible rather than an eyeball comparison.

- [ ] **Step 1: Write the parity gate script**

Create `scripts/parity_check.sh`:

```bash
#!/usr/bin/env bash
# Every published artifact-1 number and pixel, re-derived from the stored
# records. Run after every refactor step: this is the gate that a move
# changed nothing, and "the tests pass" is not that gate -- the tests exercise
# the code, this exercises the published result.
set -euo pipefail

PY=.venv/bin/python
OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT

echo "== tests =="
$PY -m pytest -q

echo "== lint =="
$PY -m ruff check .

echo "== analysis: every published number =="
$PY scripts/analyse.py --store data/campaign.jsonl > "$OUT/analysis.json"
if ! diff -q "$OUT/analysis.json" data/analysis.json > /dev/null; then
  echo "PARITY FAILURE: analysis output differs from data/analysis.json"
  diff "$OUT/analysis.json" data/analysis.json | head -40
  exit 1
fi
echo "analysis.json: identical"

echo "== figures: every published pixel =="
$PY scripts/render_figures.py --store data/campaign.jsonl --out "$OUT/figures" > /dev/null
for f in waterfall warmup ecdf per_host; do
  if ! cmp -s "$OUT/figures/$f.png" "build/figures-final/$f.png"; then
    echo "PARITY FAILURE: $f.png differs from build/figures-final/$f.png"
    exit 1
  fi
  echo "$f.png: identical"
done

echo
echo "PARITY OK"
```

Make it executable:

```bash
chmod +x scripts/parity_check.sh
```

- [ ] **Step 2: Run it and confirm it passes on unmodified code**

Run: `./scripts/parity_check.sh`
Expected, on the last four lines:

```
waterfall.png: identical
warmup.png: identical
ecdf.png: identical
per_host.png: identical

PARITY OK
```

If this fails *before* any refactoring, stop — the baseline is not what this plan assumes and the rest of it is unsafe.

The expected test count quoted in later tasks is this baseline plus exactly the tests this plan adds (2 + 1 + 2 + 2 + 7 + 2). If your count differs, reconcile it against the tests you actually wrote before continuing — a silently *lower* count means a test file stopped being collected.

- [ ] **Step 3: Record the baseline**

Create `docs/superpowers/plans/2026-09-03-harness-extraction-baseline.md`:

```markdown
# Harness Extraction — Fidelity Baseline

Captured before any module moved. `scripts/parity_check.sh` re-checks all of it.

## Suite

- `pytest -q`: **527 passed**
- `ruff check .`: **All checks passed**

## Published artifact-1 output — sha256

| File | sha256 |
|---|---|
| `data/analysis.json` | `1c30e2310a70e56ac0bdd68d6e4dcdf0dba9e3a5a374bf8792dd48e372a70e95` |
| `build/figures-final/waterfall.png` | `e45925a04901b169ac605a0b823783795d53dd97719dbcd7b3d0c625a1bf72f2` |
| `build/figures-final/warmup.png` | `c6b127f8bd7b503687576f6745aff4dec611357ef10a057dd88acc157ae75731` |
| `build/figures-final/ecdf.png` | `93a130f40467a9583e94659e5d47110865c4825760a583874e0e902aef38e501` |
| `build/figures-final/per_host.png` | `51d104044e76529302413c73c81de8ff7e63d913d59738636a04ac871f486949` |

The `*-phone.png` variants in `build/figures-final/` are downscales of the four
above (artifact-1 campaign plan, Task 11 Step 4), not separate renders. Pixel-identical
sources mean identical downscales, so the gate covers them transitively.

## Reproduce

    .venv/bin/python scripts/analyse.py --store data/campaign.jsonl | diff - data/analysis.json
    .venv/bin/python scripts/render_figures.py --store data/campaign.jsonl --out /tmp/f
    cmp /tmp/f/waterfall.png build/figures-final/waterfall.png
```

Verify the digests you record match the tree you are on:

```bash
shasum -a 256 data/analysis.json build/figures-final/waterfall.png build/figures-final/warmup.png build/figures-final/ecdf.png build/figures-final/per_host.png
```

- [ ] **Step 4: Commit**

```bash
git add scripts/parity_check.sh docs/superpowers/plans/2026-09-03-harness-extraction-baseline.md
git commit -m "test: a parity gate that re-derives every published number and pixel"
```

---

## Task 3: The harness package, its import-direction guard, and image coverage

**Files:**
- Create: `harness/__init__.py`, `harness/runpod/__init__.py`
- Create: `tests/test_harness_boundary.py`
- Modify: `worker/Dockerfile`, `.github/workflows/build-worker.yml`

The Dockerfile copies `coldstart/` into the image because `worker/handler.py` imports it. `recorder.py` moves to `harness/` in Task 6, so the image must carry `harness/` too. Getting this wrong is invisible locally and fails on a **paid GPU run**, so the copy and its guard land before anything moves.

- [ ] **Step 1: Write the failing boundary tests**

Create `tests/test_harness_boundary.py`:

```python
"""The two structural invariants the split exists to create.

1. harness/ never imports coldstart/. The whole point is that artifact 2 can
   depend on the harness without dragging in artifact 1's cold-start vocabulary;
   one convenience import in the wrong direction silently ends that.

2. Every first-party package the worker modules need is COPYed into the image.
   worker/handler.py imports harness.recorder at runtime on a paid GPU run --
   a missing COPY is an ImportError in the most expensive possible place, and
   nothing in the local loop would reveal it.
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
    copied = set(re.findall(r"^COPY\s+(\w+)\s+/opt/", dockerfile, re.M))

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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_harness_boundary.py -v`
Expected: `test_harness_never_imports_coldstart` FAILS — `harness/` does not exist yet, so `rglob` raises nothing but the directory is absent; if it errors on the missing path that is the same signal. `test_dockerfile_copies_...` PASSES today (only `coldstart` is needed and only `coldstart` is copied).

- [ ] **Step 3: Create the package and update the image**

```bash
mkdir -p harness/runpod
touch harness/__init__.py harness/runpod/__init__.py
```

In `worker/Dockerfile`, replace the `COPY coldstart /opt/coldstart` line and the comment above it with:

```dockerfile
# The probe imports the pre-registered warmup trio from coldstart.analysis.metrics
# and the stage recorder from harness.recorder rather than re-defining either, so
# both packages ship in the image. /opt is on the path for them and for the worker
# modules beside them. tests/test_harness_boundary.py asserts these COPY lines
# cover everything the image actually imports.
COPY coldstart /opt/coldstart
COPY harness /opt/harness
```

In `.github/workflows/build-worker.yml`, add `harness/**` to the `paths` filter directly below `coldstart/**`:

```yaml
      - "coldstart/**"
      # Same reasoning as coldstart/** above: the image vendors this package
      # too (worker/handler.py imports harness.recorder), so a change here
      # changes the image.
      - "harness/**"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_harness_boundary.py -v`
Expected: 2 passed.

- [ ] **Step 5: Run the parity gate**

Run: `./scripts/parity_check.sh`
Expected: `PARITY OK`, and the test count is now 529.

- [ ] **Step 6: Commit**

```bash
git add harness tests/test_harness_boundary.py worker/Dockerfile .github/workflows/build-worker.yml
git commit -m "feat: add the harness package, its import-direction guard, and image coverage"
```

---

## Task 4: Move stats.py

**Files:**
- Move: `coldstart/analysis/stats.py` → `harness/stats.py`
- Modify: `coldstart/analysis/metrics.py`, `coldstart/analysis/figures.py`, `scripts/analyse.py`, `tests/test_stats.py`, `tests/test_pipeline.py`, `tests/test_end_to_end.py`, `tests/test_reproducibility.py`

Moves verbatim. Nothing in it names a cold-start concept: `within_host_triples` takes condition labels as arguments rather than hardcoding arms.

- [ ] **Step 1: Point the tests at the new path first**

In `tests/test_stats.py`, rewrite the two import statements:

```python
import harness.stats as stats_module
from harness.stats import (
```

(keep the imported name list exactly as it is)

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_stats.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'harness.stats'`

- [ ] **Step 3: Move the module and rewrite every import**

```bash
git mv coldstart/analysis/stats.py harness/stats.py
grep -rln "coldstart\.analysis\.stats" --include="*.py" . | grep -v ".venv" | xargs sed -i '' 's/coldstart\.analysis\.stats/harness.stats/g'
```

In `harness/stats.py`, if the module docstring names `coldstart`, reword it to name the harness instead. Then check the reverse-reference in `coldstart/analysis/figures.py`'s docstring, which points readers at `coldstart.analysis.stats.median`:

```bash
sed -i '' 's/``coldstart\.analysis\.stats\.median``/``harness.stats.median``/' coldstart/analysis/figures.py
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest -q`
Expected: 529 passed.

- [ ] **Step 5: Run the parity gate**

Run: `./scripts/parity_check.sh`
Expected: `PARITY OK`

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: move stats into the harness"
```

---

## Task 5: Move vllm_logs.py

**Files:**
- Move: `coldstart/vllm_logs.py` → `harness/vllm_logs.py`
- Modify: `coldstart/driver.py`, `coldstart/stubs/stub_endpoint.py`, `tests/test_vllm_logs.py`, `tests/test_stubs.py`, `tests/test_driver.py`

The engine-log parser is the single highest-value file for artifacts 4 and 5: artifact 4's fourth figure decomposes swap cost onto artifact 1's stage taxonomy, and artifact 5 reads KV blocks off the same lines.

- [ ] **Step 1: Point the test at the new path first**

In `tests/test_vllm_logs.py`:

```python
from harness.vllm_logs import parse_engine_log
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_vllm_logs.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'harness.vllm_logs'`

- [ ] **Step 3: Move the module and rewrite every import**

```bash
git mv coldstart/vllm_logs.py harness/vllm_logs.py
grep -rln "coldstart\.vllm_logs\|coldstart/vllm_logs" --include="*.py" . | grep -v ".venv" | xargs sed -i '' -e 's/coldstart\.vllm_logs/harness.vllm_logs/g' -e 's|coldstart/vllm_logs|harness/vllm_logs|g'
```

The second pattern catches prose references — `coldstart/analysis/pipeline.py`'s `REQUIRED_FOR_T_COMPILE` docstring points at `coldstart/vllm_logs.py`'s `PATTERNS`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest -q`
Expected: 529 passed.

- [ ] **Step 5: Run the parity gate**

Run: `./scripts/parity_check.sh`
Expected: `PARITY OK`

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: move the engine-log parser into the harness"
```

---

## Task 6: Move recorder.py

**Files:**
- Move: `coldstart/recorder.py` → `harness/recorder.py`
- Modify: `worker/handler.py`, `tests/test_recorder.py`, `tests/test_probe_units.py`

This is the module that makes Task 3's Dockerfile change load-bearing.

- [ ] **Step 1: Point the test at the new path first**

In `tests/test_recorder.py`:

```python
from harness.recorder import StageRecorder
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_recorder.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'harness.recorder'`

- [ ] **Step 3: Move the module and rewrite every import**

```bash
git mv coldstart/recorder.py harness/recorder.py
grep -rln "coldstart\.recorder" --include="*.py" . | grep -v ".venv" | xargs sed -i '' 's/coldstart\.recorder/harness.recorder/g'
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest -q`
Expected: 529 passed, including `test_harness_boundary.py::test_dockerfile_copies_every_first_party_package_the_image_imports` — which now has something real to check, because `worker/handler.py` imports `harness.recorder`.

- [ ] **Step 5: Prove the guard actually catches the failure it exists for**

Temporarily remove the `COPY harness /opt/harness` line from `worker/Dockerfile`, then:

Run: `.venv/bin/python -m pytest tests/test_harness_boundary.py -v`
Expected: FAIL with `worker/Dockerfile does not COPY ['harness']`

Restore the line and re-run:
Expected: 2 passed.

- [ ] **Step 6: Run the parity gate**

Run: `./scripts/parity_check.sh`
Expected: `PARITY OK`

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: move the stage recorder into the harness"
```

---

## Task 7: Split the failure taxonomy out of checks.py

**Files:**
- Create: `harness/failures.py`
- Modify: `coldstart/checks.py`, `coldstart/driver.py`, `tests/test_checks.py`

`checks.py` holds two unrelated things: a string-to-`FailureClass` classifier (generic — these are platform and engine failure strings) and artifact 1's clock reconciliation (`compute_residual`, `check_consistency`). Only the first moves. `DiscardReason` stays: all five of its members are outputs of artifact 1's own checks, and `harness/publish.py` reads `.value` off whatever enum a row carries rather than importing one.

- [ ] **Step 1: Point the test at the new paths first**

In `tests/test_checks.py`, split the single import block into two — `FailureClass` and `classify_failure` come from the harness, everything else stays:

```python
from coldstart.checks import (
    DEFAULT_RTT_FLOOR,
    ConsistencyResult,
    DiscardReason,
    check_consistency,
    compute_residual,
)
from harness.failures import FailureClass, classify_failure
```

Adjust the names to whatever the file actually imports today — keep the same set, just routed to the two modules.

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_checks.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'harness.failures'`

- [ ] **Step 3: Create harness/failures.py**

Create `harness/failures.py` and move into it, unchanged, from `coldstart/checks.py`: the `import re` dependency, `FailureClass`, `_Needle`, `_SIGNATURES`, and `classify_failure`. Give it this module docstring:

```python
"""Platform and engine failure strings, classified into a closed taxonomy.

Lives in the harness rather than beside artifact 1's clock checks because none
of these signatures are about cold starts: an OOM, an image pull failure, or a
health-check timeout looks the same whichever experiment was running when it
happened, and every artifact has to report a failure rate by class alongside
its latency numbers.
"""
```

Delete those four items and the now-unused `import re` from `coldstart/checks.py`, and give `coldstart/checks.py` a docstring naming what it still is:

```python
"""Artifact 1's clock reconciliation and its discard taxonomy.

The failure classifier that used to live here is artifact-agnostic and moved to
harness/failures.py. What remains reconciles clock A against clock B for the
cold-start stage decomposition specifically -- see spec 6.5 rule 3.
"""
```

- [ ] **Step 4: Rewrite the remaining import**

`coldstart/driver.py` imports `classify_failure` from `coldstart.checks`:

```python
from harness.failures import classify_failure
```

Confirm nothing else still expects the old location:

```bash
grep -rn "checks import.*classify_failure\|checks import.*FailureClass" --include="*.py" . | grep -v ".venv"
```

Expected: no output.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest -q`
Expected: 529 passed.

- [ ] **Step 6: Run the parity gate**

Run: `./scripts/parity_check.sh`
Expected: `PARITY OK`

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: move the failure taxonomy into the harness, leave the clock checks behind"
```

---

## Task 8: Move the store and inject the record class

**Files:**
- Move: `coldstart/store.py` → `harness/store.py`
- Modify: `scripts/analyse.py`, `scripts/render_figures.py`, `scripts/run_window.py`, `scripts/prime_compile_cache.py`, `tests/test_store.py`, `tests/test_driver.py`, `tests/test_end_to_end.py`, `tests/test_reproducibility.py`

**Signature change** (inventory sign-off required): `JsonlStore(path)` → `JsonlStore(path, record_cls)`.

- [ ] **Step 1: Write the failing test for the new signature**

Add to `tests/test_store.py`:

```python
def test_store_round_trips_a_record_type_that_is_not_runrecord(tmp_path):
    """The store is the harness's, not artifact 1's: any record with to_dict()
    and from_dict() goes through the same append-only file discipline. Artifact
    2's service-curve rows and artifact 5's sweep points are not RunRecords."""

    @dataclass
    class SweepPoint:
        concurrency: int
        ttft: float

        def to_dict(self) -> dict:
            return asdict(self)

        @classmethod
        def from_dict(cls, d: dict) -> "SweepPoint":
            return cls(**d)

    store = JsonlStore(tmp_path / "sweep.jsonl", SweepPoint)
    store.append(SweepPoint(concurrency=8, ttft=0.42))
    store.append(SweepPoint(concurrency=16, ttft=0.61))

    assert store.read_all() == [
        SweepPoint(concurrency=8, ttft=0.42),
        SweepPoint(concurrency=16, ttft=0.61),
    ]
```

Add the imports this test needs at the top of the file:

```python
from dataclasses import asdict, dataclass

from harness.store import JsonlStore
```

and change the existing `RunRecord` import line to keep coming from `coldstart.schema`:

```python
from coldstart.schema import SCHEMA_VERSION, RunRecord
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'harness.store'`

- [ ] **Step 3: Move and generalize the store**

```bash
git mv coldstart/store.py harness/store.py
```

Rewrite `harness/store.py` in full:

```python
import json
from pathlib import Path


class JsonlStore:
    """Append-only. Never rewrites or deletes a record — see artifact 1 spec 6.6.

    `record_cls` is the artifact's own record type: anything with a `to_dict()`
    method and a `from_dict()` classmethod. It is a constructor argument rather
    than a hard import of `RunRecord` so a second artifact can store its own
    record shape through the same file discipline -- the append-only rule and
    the truncated-line diagnostic below are what is worth sharing, and neither
    depends on what a record contains.
    """

    def __init__(self, path, record_cls):
        self.path = Path(path)
        self.record_cls = record_cls
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record) -> None:
        with self.path.open("a") as f:
            f.write(json.dumps(record.to_dict(), sort_keys=True) + "\n")

    def read_all(self) -> list:
        if not self.path.exists():
            return []
        out = []
        with self.path.open() as f:
            for lineno, raw_line in enumerate(f, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as e:
                    raise ValueError(
                        f"{self.path}: line {lineno} is not valid JSON ({e}). "
                        "A line truncated mid-write is the signature of a "
                        "process killed mid-append (e.g. an interrupted "
                        "campaign); if this is the last line in the file, "
                        "truncating it is the fix -- read_all() will not "
                        "silently drop it for you."
                    ) from e
                out.append(self.record_cls.from_dict(data))
        return out
```

- [ ] **Step 4: Update every construction site**

Rewrite the import path everywhere, then pass `RunRecord` at each construction:

```bash
grep -rln "coldstart\.store" --include="*.py" . | grep -v ".venv" | xargs sed -i '' 's/coldstart\.store/harness.store/g'
grep -rn "JsonlStore(" --include="*.py" . | grep -v ".venv"
```

For each hit, add `RunRecord` as the second argument. The four script sites are:

- `scripts/analyse.py`: `JsonlStore(args.store, RunRecord)`
- `scripts/render_figures.py`: `JsonlStore(args.store, RunRecord)`
- `scripts/run_window.py`: `JsonlStore(args.store, RunRecord)`
- `scripts/prime_compile_cache.py`: `JsonlStore(args.store, RunRecord)`

Each of those four scripts needs the import added beside its existing `coldstart` imports:

```python
from coldstart.schema import RunRecord
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest -q`
Expected: 530 passed.

- [ ] **Step 6: Run the parity gate**

Run: `./scripts/parity_check.sh`
Expected: `PARITY OK` — this proves `analyse.py` and `render_figures.py` still read the campaign correctly through the new signature.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: move the store into the harness and inject the record type"
```

---

## Task 9: Move the scheduler and neutralize its vocabulary

**Files:**
- Move: `coldstart/scheduler.py` → `harness/scheduler.py`
- Modify: `coldstart/driver.py`, `tests/test_scheduler.py`, `tests/test_driver.py`

**Signature change** (inventory sign-off required): `build_schedule(arms, triples, seed)` → `build_schedule(conditions, blocks, seed)`, and `ScheduledRun.arm`/`.triple_index` → `.condition`/`.block_index`.

The RNG consumption order is untouched, so the same seed produces the same order. `coldstart/driver.py` maps the neutral names back to `arm`/`triple_index` when it builds a `RunRecord`, so **the stored JSONL is unchanged** — which the parity gate proves.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_scheduler.py`:

```python
def test_schedule_is_identical_under_the_neutral_vocabulary():
    """The rename must not disturb the RNG. A schedule built for artifact 1's
    three arms at seed 7 has to come out in exactly the order the campaign ran,
    or a resumed window would splice two different interleavings together."""
    sched = build_schedule(conditions=["A", "B", "C"], blocks=4, seed=7)

    assert [s.condition for s in sched] == [
        s.condition for s in build_schedule(conditions=["A", "B", "C"], blocks=4, seed=7)
    ]
    assert [s.run_index for s in sched] == list(range(12))
    assert [s.block_index for s in sched] == [0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 3]
    for b in range(4):
        assert sorted(s.condition for s in sched if s.block_index == b) == ["A", "B", "C"]


def test_schedule_works_for_a_two_condition_experiment():
    """Artifact 5 interleaves two regimes at each registered count, not three
    arms in a triple. Same structure, different arity -- which is the reason
    this module speaks conditions and blocks rather than arms and triples."""
    sched = build_schedule(conditions=["concentrated", "spread"], blocks=3, seed=1)

    assert len(sched) == 6
    assert [s.run_index for s in sched] == list(range(6))
    for b in range(3):
        assert sorted(s.condition for s in sched if s.block_index == b) == [
            "concentrated",
            "spread",
        ]
```

Update the file's import:

```python
from harness.scheduler import build_schedule
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_scheduler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'harness.scheduler'`

- [ ] **Step 3: Move and rewrite the scheduler**

```bash
git mv coldstart/scheduler.py harness/scheduler.py
```

Rewrite `harness/scheduler.py` in full:

```python
import random
from dataclasses import dataclass


@dataclass(frozen=True)
class ScheduledRun:
    run_index: int
    block_index: int
    condition: str


def build_schedule(conditions: list[str], blocks: int, seed: int) -> list[ScheduledRun]:
    """Interleaved, randomized within each block.

    Blocking all of one condition together would confound the intervention with
    time-varying platform conditions — see artifact 1 spec 5, sample plan.

    The vocabulary is deliberately artifact-neutral. Artifact 1's three arms
    within a triple, artifact 5's two regimes at one registered count, and
    artifact 4's three placement strategies are the same structure; naming it
    "arm" and "triple" here would have made two of those read as a hack.
    `coldstart/driver.py` maps `condition`/`block_index` back onto `RunRecord`'s
    `arm`/`triple_index` fields, so artifact 1's stored records are unchanged.
    """
    rng = random.Random(seed)
    out: list[ScheduledRun] = []
    idx = 0
    for b in range(blocks):
        order = list(conditions)
        rng.shuffle(order)
        for condition in order:
            out.append(ScheduledRun(run_index=idx, block_index=b, condition=condition))
            idx += 1
    return out
```

- [ ] **Step 4: Map the names back in the driver**

In `coldstart/driver.py`, rewrite the import:

```python
from harness.scheduler import build_schedule
```

Then make exactly these five edits:

1. In `_record_from`, the failed-run branch: `arm=scheduled.arm,` → `arm=scheduled.condition,`
2. In `_record_from`, the ok-run branch: `arm=scheduled.arm,` → `arm=scheduled.condition,`
3. In `run_campaign`: `schedule = build_schedule(arms=arms, triples=triples, seed=seed)` → `schedule = build_schedule(conditions=arms, blocks=triples, seed=seed)`
4. In `run_campaign`'s resume guard: `arm_by_index = {s.run_index: s.arm for s in schedule}` → `{s.run_index: s.condition for s in schedule}`
5. In `run_campaign`'s loop:

```python
        outcome = submitter.submit(arm=scheduled.condition, run_id=run_id)
        record = _record_from(scheduled, run_id, outcome)
        record.host["triple_index"] = scheduled.block_index
```

`run_campaign`'s own signature keeps `arms`/`triples`: it builds artifact 1 records, and the runner scripts and resume-drift error messages all speak that vocabulary.

- [ ] **Step 5: Update the driver test's direct use**

`tests/test_driver.py` constructs `ScheduledRun` directly. Rewrite that import:

```python
    from harness.scheduler import ScheduledRun
```

and every construction to the new field names, e.g.:

```python
    scheduled = ScheduledRun(run_index=0, block_index=0, condition="A")
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest -q`
Expected: 532 passed.

- [ ] **Step 7: Run the parity gate**

Run: `./scripts/parity_check.sh`
Expected: `PARITY OK`

- [ ] **Step 8: Verify the stored record shape did not move**

The gate re-derives numbers from the *existing* store, which cannot catch a change in what a *new* record would contain. Check that directly:

```bash
.venv/bin/python -c "
from coldstart.driver import _record_from
from harness.scheduler import ScheduledRun
from harness.submit import SubmitOutcome
s = ScheduledRun(run_index=3, block_index=1, condition='B')
r = _record_from(s, 'abc', SubmitOutcome(clock_A={'t_submit': 0.0, 't_result': 1.0}, payload=None, error='submit failed'))
print(r.arm, r.run_index, r.status['failure_class'])
"
```

Expected: `B 3 submit_error`

(If Task 12 has not run yet, import `SubmitOutcome` from `coldstart.submitter` instead.)

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "refactor: move the scheduler into the harness and neutralize its vocabulary"
```

---

## Task 10: Split pipeline.py into the harness gate and artifact 1's presets

**Files:**
- Move: `coldstart/analysis/pipeline.py` → `harness/publish.py`
- Create: `coldstart/analysis/presets.py`
- Modify: `coldstart/analysis/figures.py`, `scripts/analyse.py`, `scripts/render_figures.py`, `tests/test_pipeline.py`, `tests/test_figures.py`, `tests/test_end_to_end.py`, `tests/test_reproducibility.py`

The machinery is generic; the five `REQUIRED_FOR_*` presets name artifact 1's fields (`t_weights`, `t_compile`, `t_fast_seconds`) and carry rulings specific to its clock checks. They move to `coldstart/analysis/presets.py` **with their docstrings intact** — those docstrings are the record of decisions that were litigated once and must not be re-litigated.

**Signature change** (inventory sign-off required): `failure_rate_by_arm(rows)` → `failure_rate_by_group(rows, key)` and `discard_table(rows)` → `discard_table(rows, key)`, both with the key **required**.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pipeline.py`:

```python
def test_failure_rate_groups_by_the_key_the_caller_names():
    """Grouping was hardcoded to `arm`. Artifact 2's rows are keyed by signal,
    artifact 5's by regime -- and a default of "arm" would have let either one
    group by a column it does not have and emit a plausible one-bucket table."""
    rows = [
        {"signal": "queue_depth", "ok": True},
        {"signal": "queue_depth", "ok": False, "failure_class": "oom"},
        {"signal": "utilization", "ok": True},
    ]

    out = failure_rate_by_group(rows, key="signal")

    assert out["queue_depth"] == {
        "total": 2,
        "failed": 1,
        "by_class": {"oom": 1},
        "rate": 0.5,
    }
    assert out["utilization"]["rate"] == 0.0


def test_grouping_functions_refuse_to_guess_the_key():
    with pytest.raises(TypeError):
        failure_rate_by_group([{"arm": "A", "ok": True}])
    with pytest.raises(TypeError):
        discard_table([{"arm": "A", "exclusion_reason": "x"}])
```

Update that file's imports — the machinery from the harness, the presets from coldstart:

```python
import pytest

from coldstart.analysis.presets import (
    REQUIRED_FOR_T_TOTAL,
    REQUIRED_FOR_T_WEIGHTS,
)
from harness.publish import (
    NotPublishableError,
    PartitionResult,
    annotate_first_touch,
    discard_table,
    failure_rate_by_group,
    partition,
)
```

Keep whatever additional names the file already imports; route each to whichever of the two modules now owns it.

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'harness.publish'`

- [ ] **Step 3: Move the module**

```bash
git mv coldstart/analysis/pipeline.py harness/publish.py
```

- [ ] **Step 4: Move the presets out of it**

Create `coldstart/analysis/presets.py` containing the module-level block comment ("CONSISTENCY IS THE SHARED FLOOR...") and all five preset constants — `REQUIRED_FOR_WARMUP`, `REQUIRED_FOR_T_TOTAL`, `REQUIRED_FOR_T_WEIGHTS`, `REQUIRED_FOR_T_COMPILE`, `REQUIRED_FOR_T_FAST` — **copied verbatim with every docstring**, under this module docstring:

```python
"""Artifact 1's publishability presets: what each of its analyses requires.

Each is a `required` tuple `harness.publish.partition()` already knows how to
interpret. They live here rather than in the harness because they name artifact
1's fields -- `t_weights`, `t_compile`, `t_fast_seconds` -- and because the
rulings recorded in their docstrings are about artifact 1's clock checks
specifically. A second artifact writes its own presets against the same
`partition()`.

Read the block comment below before adding a preset: consistency is the floor
every one of them stands on, and that was settled twice already.
"""
```

Delete those constants and that block comment from `harness/publish.py`, and replace its module docstring's reference to them with:

```python
"""The gate between stored rows and every consumer.

`metrics.derive()`-style pipelines return two different row shapes (a short row
for a failed run, a full row for an ok one) and `None` for fields they could not
compute on an otherwise-ok run. Nothing used to decide which rows were safe to
hand to a figure or a stats call, so every consumer invented its own error
policy and each failed differently on the same bad input — recorded as B4 in
the artifact 1 plan.

`partition()` is the one function meant to sit between `[derive(r) for r in
store.read_all()]` and everything downstream. It does not hardcode one notion of
"publishable": the caller states which fields the analysis at hand actually
needs via `required`. See `coldstart/analysis/presets.py` for artifact 1's
presets and for the ruling that every preset includes `"consistent"`.

Imports nothing from any artifact — that is what makes it reusable, and
tests/test_harness_boundary.py enforces it.
"""
```

- [ ] **Step 5: Require the grouping key**

In `harness/publish.py`, change the two grouping functions' signatures and bodies:

```python
def failure_rate_by_group(rows, key: str) -> dict[str, dict]:
```

with `arm = row["arm"]` becoming `group = row[key]` and `out.setdefault(arm, ...)` becoming `out.setdefault(group, ...)`. Add to its docstring, after the existing text:

```
    `key` names the column to group by and has no default. Artifact 1 passes
    "arm"; artifact 2's signals and artifact 5's regimes are different columns.
    A default would let a caller group by a column its rows do not carry and
    get one plausible-looking bucket back instead of an error -- the same
    fail-closed reasoning as `assert_endpoint_matches` refusing an empty pin set.
```

Do the same to `discard_table(discarded_rows, key: str)`.

- [ ] **Step 6: Rewrite every import and call site**

```bash
grep -rln "coldstart\.analysis\.pipeline\|coldstart/analysis/pipeline" --include="*.py" . | grep -v ".venv" | xargs sed -i '' -e 's/coldstart\.analysis\.pipeline/harness.publish/g' -e 's|coldstart/analysis/pipeline|harness/publish|g'
```

Then, in each consumer, split the import so presets come from `coldstart.analysis.presets`:

- `scripts/analyse.py` — imports `REQUIRED_FOR_T_COMPILE`, `REQUIRED_FOR_T_TOTAL`, `REQUIRED_FOR_T_WEIGHTS` plus `PartitionResult`, `discard_table`, `failure_rate_by_arm`, `partition`
- `scripts/render_figures.py` — imports `REQUIRED_FOR_T_TOTAL`, `REQUIRED_FOR_WARMUP` plus `NotPublishableError`, `annotate_first_touch`, `partition`
- `tests/test_reproducibility.py` — imports `REQUIRED_FOR_T_COMPILE`, `REQUIRED_FOR_T_TOTAL` plus `partition`
- `tests/test_end_to_end.py`, `tests/test_figures.py` — route each imported name to its new owner

Update the two renamed call sites in `scripts/analyse.py`:

```python
    failure_rate_by_group(rows, key="arm")
```

```python
    discard_table(total_part.discarded, key="arm")
```

Match the surrounding call's actual argument expressions; only the function name and the added `key` change. Find every one:

```bash
grep -rn "failure_rate_by_arm\|discard_table(" --include="*.py" . | grep -v ".venv"
```

Expected after the edit: no remaining `failure_rate_by_arm`, and every `discard_table(` call passing `key=`.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest -q`
Expected: 534 passed.

- [ ] **Step 8: Run the parity gate**

Run: `./scripts/parity_check.sh`
Expected: `PARITY OK` — this is the task most able to change a published number, because it touches what counts as publishable. An `analysis.json` diff here means a preset or the gate changed meaning.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "refactor: split the publishability gate from artifact 1's presets"
```

---

## Task 11: Extract the figure guard rails

**Files:**
- Create: `harness/figure_guards.py`
- Modify: `coldstart/analysis/figures.py`, `tests/test_figures.py`

Every spec in the portfolio carries the same figure constraints — N stated, no truncated axes, legible on a phone, empty input refused, a missing arm never silently dropped. Those guards live inside `figures.py` today, and `_row_identity` is duplicated between `figures.py` and `pipeline.py`. This task extracts them once and DRYs the duplicate.

- [ ] **Step 1: Write the failing test**

Create `tests/test_figure_guards.py`:

```python
"""The guards are the portfolio's shared figure contract, so they get their own
tests rather than being exercised only through artifact 1's four charts."""

import pytest

from harness.figure_guards import (
    MIN_PHONE_TEXT_PX,
    PHONE_WIDTH_PX,
    group_required,
    phone_pt,
    required_field,
    validate_rows,
)
from harness.publish import NotPublishableError


def test_validate_rows_refuses_empty_input():
    with pytest.raises(ValueError, match="rows must not be empty"):
        validate_rows([])


def test_validate_rows_materializes_a_generator():
    rows = validate_rows(r for r in [{"arm": "A"}])
    assert rows == [{"arm": "A"}]


def test_required_field_names_the_row_and_the_field_when_absent():
    with pytest.raises(NotPublishableError, match="t_total"):
        required_field({"arm": "A", "host_id": "h1"}, "t_total")


def test_required_field_rejects_none_as_firmly_as_absent():
    with pytest.raises(NotPublishableError, match="= None"):
        required_field({"arm": "A", "host_id": "h1", "t_total": None}, "t_total")


def test_group_required_refuses_to_silently_drop_a_group():
    rows = [{"regime": "spread"}, {"regime": "spread"}]
    with pytest.raises(ValueError, match="concentrated"):
        group_required(rows, "regime", ("spread", "concentrated"))


def test_group_required_splits_when_every_group_is_present():
    rows = [{"regime": "spread"}, {"regime": "concentrated"}]
    by = group_required(rows, "regime", ("spread", "concentrated"))
    assert list(by) == ["spread", "concentrated"]
    assert by["spread"] == [{"regime": "spread"}]


def test_phone_pt_inverts_the_downscale_relation():
    # A 12pt callout on an 8-inch canvas renders at 7.8px at phone width.
    assert phone_pt(7.8, 8.0) == pytest.approx(12.0, abs=0.1)
    assert MIN_PHONE_TEXT_PX < 7.8
    assert PHONE_WIDTH_PX == 375
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_figure_guards.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'harness.figure_guards'`

- [ ] **Step 3: Create harness/figure_guards.py**

```python
"""Input guards and legibility constants every artifact's figures share.

The four figure constraints repeat verbatim across all five artifact specs:
N stated, no truncated axes, intervals shown, legible on a phone. Two of those
are enforceable in code and are enforced here -- an empty input raises rather
than drawing an empty axes, and a group missing from the data raises rather
than quietly producing a chart that compares two conditions where the reader
believes three were compared.

`PHONE_WIDTH_PX` / `phone_pt` exist because this repo has already shipped that
defect once: a figure that is illegible on a phone still renders, still passes
every assertion about its data, and looks fine on the laptop it was written on.
"""

from harness.publish import NotPublishableError

# Text smaller than this, once a figure is downscaled to phone width, is not
# readable. Measured on the 300-run campaign's figures: 8pt legends on an
# 8-inch canvas (5.2px) and 11pt labels on a 10.9-inch canvas (5.3px) were both
# unreadable at phone width, while a 12pt callout on an 8-inch canvas (7.8px)
# was comfortable. The floor sits just below the latter.
PHONE_WIDTH_PX = 375
MIN_PHONE_TEXT_PX = 7.5

# Fields tried, in order, when naming a row in an error message. A row carries
# whichever of these its artifact defines; the identity is for a human reading
# a traceback, so an absent field is skipped rather than raising inside the
# error path itself.
IDENTITY_FIELDS = ("arm", "condition", "regime", "signal", "host_id", "triple_index")


def phone_pt(px: float, fig_width_in: float) -> float:
    """Point size that renders at `px` pixels when a `fig_width_in`-wide figure
    is displayed `PHONE_WIDTH_PX` wide. Inverse of the relation above."""
    return px * 72 * fig_width_in / PHONE_WIDTH_PX


def row_identity(row: dict, fields: tuple[str, ...] = IDENTITY_FIELDS) -> str:
    """Name a row for an error message, using whichever identity fields it has."""
    present = [f"{f}={row[f]!r}" for f in fields if f in row]
    return " ".join(present) if present else "row with no identity fields"


def required_field(row: dict, key: str):
    """Raise `NotPublishableError`, naming the row and `key`, in place of the
    bare `KeyError` (key absent -- a failed run's short row) or `TypeError`
    (key present but `None` -- an inconsistent or merged run) that
    dereferencing `row[key]` directly would produce deep inside a median or
    ECDF call. B4 in the artifact 1 plan."""
    if key not in row:
        raise NotPublishableError(
            f"row ({row_identity(row)}) has no {key!r} field -- route rows "
            "through harness.publish.partition() with that field in "
            "`required` before calling this figure"
        )
    val = row[key]
    if val is None:
        raise NotPublishableError(
            f"row ({row_identity(row)}) has {key!r} = None -- not publishable "
            "for this figure; route rows through harness.publish.partition() "
            "with that field in `required` first"
        )
    return val


def validate_rows(rows) -> list[dict]:
    """Fail loudly on the one input domain every figure shares: nothing to plot.

    A copy is returned so callers get a stable list even if `rows` was a
    generator (no figure consumes `rows` more than once, but this keeps that
    assumption from becoming load-bearing by accident)."""
    rows = list(rows)
    if not rows:
        raise ValueError("rows must not be empty")
    return rows


def group_required(rows, key: str, expected) -> dict[str, list[dict]]:
    """Split rows by `row[key]`, requiring every value in `expected` to appear.

    Silently skipping a missing group (`if not rs: continue`) would drop that
    group's whole series from the chart with no indication anything was wrong --
    a figure that quietly compares two conditions instead of three is a
    misleading chart, not a smaller one. Insertion order follows `expected`, so
    a caller controls series order by ordering that tuple."""
    rows = validate_rows(rows)
    by = {v: [r for r in rows if r[key] == v] for v in expected}
    missing = [v for v in expected if not by[v]]
    if missing:
        raise ValueError(
            f"no rows for {key} {missing}; refusing to silently drop "
            f"{'a series' if len(missing) == 1 else 'series'} from the chart"
        )
    return by
```

- [ ] **Step 4: Rewire figures.py onto the guards**

In `coldstart/analysis/figures.py`:

Delete the local `PHONE_WIDTH_PX`, `MIN_PHONE_TEXT_PX`, `phone_pt`, `_row_identity`, `_required_field`, `_validate_rows`, and `_by_arm` definitions, and import them instead — keeping the module-level names the tests already reference:

```python
from harness.figure_guards import (
    MIN_PHONE_TEXT_PX,
    PHONE_WIDTH_PX,
    group_required,
    phone_pt,
    required_field,
    row_identity,
    validate_rows,
)
from harness.publish import NotPublishableError
```

Then rewrite the call sites throughout the module:

```bash
sed -i '' -e 's/\b_validate_rows(/validate_rows(/g' -e 's/\b_required_field(/required_field(/g' -e 's/\b_row_identity(/row_identity(/g' coldstart/analysis/figures.py
```

and replace each `_by_arm(rows)` call with:

```python
    by = group_required(rows, "arm", ARMS)
```

`ARMS`, `S4_SUBPHASE_KEYS`, `RESIDUAL_COLOR`, and the sub-phase labels and colors stay in `figures.py` — they are artifact 1's.

- [ ] **Step 5: Leave publish.py's identity helper where it is, and say why**

`harness/publish.py` has its own `_row_identity`, so the shared `row_identity` in `figure_guards` looks like a duplicate worth collapsing. It is not: `figure_guards` imports `NotPublishableError` from `publish`, so importing `row_identity` from `figure_guards` back into `publish` is an import cycle.

The decision is that `publish` keeps its own one-liner. Replace its body's comment so the next reader does not try the collapse again:

```python
def _row_identity(row: dict) -> str:
    # Deliberately not harness.figure_guards.row_identity, which formats the
    # same thing: figure_guards imports NotPublishableError from this module,
    # so importing it back here is a cycle. Two four-line formatters is the
    # cheaper of the two problems.
    return (
        f"arm={row.get('arm')!r} host_id={row.get('host_id')!r} "
        f"triple_index={row.get('triple_index')!r}"
    )
```

Note that this one keeps artifact 1's fixed field list while `figure_guards.row_identity` scans `IDENTITY_FIELDS` — the second is what a new artifact needs; this one only ever formats rows that came from `partition()`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest -q`
Expected: 541 passed.

Run: `.venv/bin/python -m ruff check .`
Expected: `All checks passed!`

- [ ] **Step 7: Run the parity gate**

Run: `./scripts/parity_check.sh`
Expected: `PARITY OK` — the figure bytes are the assertion that no guard changed what gets drawn.

- [ ] **Step 8: Look at the figures**

Byte-identical PNGs are the same pixels that were inspected and published, so this is a confirmation rather than a fresh review — but per the repo's own rule, a figure task does not end without eyes on the figure:

```bash
open build/figures-final/waterfall.png build/figures-final/warmup.png build/figures-final/ecdf.png build/figures-final/per_host.png
```

Confirm each renders, then note in the task report that the rendered output was `cmp`-identical to the published figures.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "refactor: extract the shared figure guards, including phone legibility"
```

---

## Task 12: Move the RunPod plumbing and separate artifact 1's pins

**Files:**
- Move: `coldstart/submitter.py` → `harness/submit.py`
- Move: `coldstart/runpod_api.py` → `harness/runpod/api.py`
- Move: `coldstart/runpod_submitter.py` → `harness/runpod/submitter.py`
- Move: `coldstart/preflight.py` → `harness/runpod/preflight.py`
- Create: `coldstart/pins.py`
- Modify: `coldstart/driver.py`, `coldstart/stubs/stub_endpoint.py`, `scripts/run_window.py`, `scripts/prime_compile_cache.py`, `tests/test_submitter.py`, `tests/test_runpod_api.py`, `tests/test_runpod_submitter.py`, `tests/test_preflight.py`, `tests/test_driver.py`, `tests/test_end_to_end.py`

**Signature change** (inventory sign-off required): `assert_endpoint_matches(endpoint, pinned=None)` → `assert_endpoint_matches(endpoint, pinned)`, required.

- [ ] **Step 1: Write the failing test**

In `tests/test_preflight.py`, rewrite the import and add the new case:

```python
from coldstart.pins import PINNED
from harness.runpod.preflight import PreflightError, assert_endpoint_matches
```

```python
def test_the_check_refuses_to_guess_which_pins_to_check_against():
    """The harness cannot carry artifact 1's endpoint. Requiring `pinned` means
    a second artifact's runner cannot accidentally validate its endpoint against
    artifact 1's RTX 4090 pin set and pass for the wrong reason."""
    with pytest.raises(TypeError):
        assert_endpoint_matches({"flashboot": False})


def test_artifact_ones_pins_still_reject_a_drifted_endpoint():
    drifted = {**PINNED, "flashboot": True}
    with pytest.raises(PreflightError, match="flashboot"):
        assert_endpoint_matches(drifted, PINNED)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_preflight.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'coldstart.pins'`

- [ ] **Step 3: Move the four modules**

```bash
git mv coldstart/submitter.py harness/submit.py
git mv coldstart/runpod_api.py harness/runpod/api.py
git mv coldstart/runpod_submitter.py harness/runpod/submitter.py
git mv coldstart/preflight.py harness/runpod/preflight.py
```

Rewrite the import paths across the tree:

```bash
grep -rln "coldstart\.runpod_submitter\|coldstart\.runpod_api\|coldstart\.submitter\|coldstart\.preflight" --include="*.py" . | grep -v ".venv" | xargs sed -i '' \
  -e 's/coldstart\.runpod_submitter/harness.runpod.submitter/g' \
  -e 's/coldstart\.runpod_api/harness.runpod.api/g' \
  -e 's/coldstart\.submitter/harness.submit/g' \
  -e 's/coldstart\.preflight/harness.runpod.preflight/g'
```

`harness/runpod/submitter.py` imports `SubmitOutcome` — its import line becomes:

```python
from harness.submit import SubmitOutcome
```

`harness/runpod/preflight.py`'s `fetch_endpoint` docstring names `coldstart.runpod_submitter.HttpTransport`; the sed above rewrites it correctly.

- [ ] **Step 4: Split the pins out of preflight**

Create `coldstart/pins.py`:

```python
"""Artifact 1's pinned endpoint configuration — the experiment's boundary.

Every value here is part of what the published result is a measurement OF
(spec 5, threats to validity): a change ends the experiment rather than
continuing across it. `harness.runpod.preflight.assert_endpoint_matches` does
the checking; this module is only what artifact 1 checks against, which is why
it does not live in the harness.

`9c7ut2slrd` and `mzadx4qugv` are opaque RunPod ids; see the "Provisioned
infrastructure" table in recon/README.md for what they actually are (the
network volume and the container template) rather than hunting them down in
the RunPod console.

`gpuTypeIds` is compared as a list, which makes the check order-sensitive.
That's inert today with a single element; if the pin ever grows to more than
one GPU type, an API response that reports them in a different order would
trip a false refusal. That's the tolerable direction of error for a guard whose
job is to refuse to spend, so it's left as-is -- but it's a known trade, not an
oversight.
"""

PINNED = {
    "flashboot": False,
    "gpuTypeIds": ["NVIDIA GeForce RTX 4090"],
    "networkVolumeId": "9c7ut2slrd",
    "templateId": "mzadx4qugv",
    "workersMin": 0,
}
```

In `harness/runpod/preflight.py`, delete the `PINNED` dict and its comment block, and change the signature and its first line:

```python
def assert_endpoint_matches(endpoint: dict, pinned: dict) -> None:
```

```python
    if not pinned:
        raise ValueError("pinned configuration is empty; refusing to check nothing")
```

(the `pinned = PINNED if pinned is None else pinned` line goes away entirely)

In that function's docstring, replace the paragraph explaining the `pinned` default with:

```
    `pinned` is required and has no default: the harness does not know which
    experiment it is guarding, and defaulting to one artifact's pin set would
    let another artifact's runner validate its endpoint against the wrong
    configuration and pass for the wrong reason. An explicitly empty override
    would check nothing and pass any endpoint -- the exact false pass this
    module exists to prevent -- so it is rejected outright below rather than
    allowed to iterate zero times.
```

- [ ] **Step 5: Update the two callers**

In both `scripts/run_window.py` and `scripts/prime_compile_cache.py`, add the pins import beside the existing ones:

```python
from coldstart.pins import PINNED
```

and pass them at the call site:

```python
    assert_endpoint_matches(fetch_endpoint(args.endpoint, api_key), PINNED)
```

Match each script's actual expression for fetching the endpoint; only the added second argument changes.

Confirm no caller still relies on the default:

```bash
grep -rn "assert_endpoint_matches(" --include="*.py" . | grep -v ".venv"
```

Expected: every call passes two arguments.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest -q`
Expected: 543 passed.

- [ ] **Step 7: Run the parity gate**

Run: `./scripts/parity_check.sh`
Expected: `PARITY OK`

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor: move the RunPod client into the harness, leave artifact 1's pins behind"
```

---

## Task 13: Parity gate, deletion verification, and documentation

**Files:**
- Modify: `docs/runbook.md`, `fixtures/README.md`, `recon/README.md` (only where they name a moved path)
- Create: `harness/README.md`

Nothing is deleted in this task — the moves already removed the old locations, and each was gated by a passing parity check as it happened. This task verifies that in one place, and makes the split legible to whoever picks up artifact 2.

- [ ] **Step 1: Verify every moved module landed and nothing dangles**

```bash
test ! -e coldstart/analysis/stats.py && test ! -e coldstart/analysis/pipeline.py && \
test ! -e coldstart/store.py && test ! -e coldstart/scheduler.py && \
test ! -e coldstart/recorder.py && test ! -e coldstart/vllm_logs.py && \
test ! -e coldstart/submitter.py && test ! -e coldstart/runpod_api.py && \
test ! -e coldstart/runpod_submitter.py && test ! -e coldstart/preflight.py && \
echo "all ten old locations removed"
```

```bash
grep -rn "coldstart\.\(store\|scheduler\|recorder\|vllm_logs\|submitter\|runpod_api\|runpod_submitter\|preflight\)\|coldstart\.analysis\.\(stats\|pipeline\)" --include="*.py" --include="*.md" . | grep -v ".venv\|docs/superpowers/plans"
```

Expected: no output. (The plans directory is excluded deliberately — the artifact 1 plans are a historical record of how the code looked when it was built and must not be rewritten.)

- [ ] **Step 2: Verify each preserved capability is exercised, not merely importable**

Parity is about behavior. Run the capabilities the inventory marked Preserved through their real paths:

```bash
.venv/bin/python -m pytest -q tests/test_stats.py tests/test_vllm_logs.py tests/test_recorder.py \
  tests/test_checks.py tests/test_store.py tests/test_scheduler.py tests/test_pipeline.py \
  tests/test_figures.py tests/test_figure_guards.py tests/test_submitter.py \
  tests/test_runpod_api.py tests/test_runpod_submitter.py tests/test_preflight.py \
  tests/test_driver.py tests/test_end_to_end.py tests/test_reproducibility.py -v 2>&1 | tail -5
```

Expected: all pass. `test_end_to_end.py` and `test_reproducibility.py` are the two that exercise the whole chain — schedule, submit, store, derive, partition, bootstrap — through the moved modules at once.

- [ ] **Step 3: Run the full parity gate one final time**

Run: `./scripts/parity_check.sh`
Expected: `PARITY OK`

- [ ] **Step 4: Write the harness README**

Create `harness/README.md`:

```markdown
# harness

The artifact-agnostic half of the measurement stack. Artifact 1
(`coldstart/`) is its first consumer; artifacts 2–5 are the reason it exists.

## The one rule

**`harness/` never imports `coldstart/`.** `tests/test_harness_boundary.py`
enforces it. When a module here needs something artifact-specific — a record
type, a pin set, a grouping key, a publishability preset — it takes it as a
parameter. That is why `JsonlStore` takes a record class, `build_schedule`
speaks conditions and blocks, `failure_rate_by_group` requires a key, and
`assert_endpoint_matches` requires a pin set.

## What is here

| Module | What it gives an artifact |
|---|---|
| `stats.py` | Medians, percentiles, ECDF, bootstrap CIs, bootstrap on a difference of contrasts, paired within-host units. Every "intervals shown" constraint in the portfolio runs through this. |
| `publish.py` | `partition()` — the gate between stored rows and any figure or stats call — plus failure-rate and discard tables from disjoint row populations. |
| `figure_guards.py` | Empty-input refusal, missing-field errors that name the row, refusal to silently drop a series, and the phone-legibility floor every spec requires. |
| `store.py` | Append-only JSONL with a truncated-line diagnostic. Pass your own record type. |
| `scheduler.py` | Interleaved, randomized-within-block schedules, so a condition is never confounded with time-varying platform state. |
| `recorder.py` | Clock B: monotonic stage marks relative to `t0`, wall clock never used for arithmetic. |
| `failures.py` | Platform and engine failure strings → a closed `FailureClass` taxonomy. |
| `vllm_logs.py` | Engine log → startup sub-phases, KV blocks, engine info, and which phases the version merges. |
| `submit.py` | The submitter interface (`SubmitOutcome`) and an in-process stub for the GPU-free loop. |
| `runpod/` | Endpoint preflight, job lifecycle extraction, and a retrying HTTP client. |

## What is deliberately NOT here

Cold-start stage taxonomy, `RunRecord`, the clock-A/clock-B residual, the
`REQUIRED_FOR_*` presets, artifact 1's economics, and its four figures. Those are
in `coldstart/`. See
`docs/superpowers/plans/2026-09-03-harness-extraction-inventory.md` for the full
decision log.

## Not yet here

Artifacts 2 and 4 need a concurrent load generator and a discrete-event
simulator; neither exists yet. `worker/probe.py` issues sequential requests
only. Build the load generator in the harness when artifact 2 starts — it is
shared by artifacts 2, 4, and 5.
```

- [ ] **Step 5: Update the docs that name a moved path**

```bash
grep -rn "coldstart/\(store\|scheduler\|recorder\|vllm_logs\|submitter\|runpod_api\|runpod_submitter\|preflight\)\.py\|coldstart/analysis/\(stats\|pipeline\)\.py" docs/runbook.md docs/experiment.md fixtures/README.md recon/README.md
```

For each hit **in `docs/runbook.md`, `fixtures/README.md`, and `recon/README.md`**, rewrite the path to its new location. **Do not touch `docs/experiment.md`** — it is the pre-registration, its git timestamp is the evidence that the hypotheses were fixed in advance, and it describes the code as it was when the campaign ran.

- [ ] **Step 6: Re-run everything**

Run: `./scripts/parity_check.sh`
Expected: `PARITY OK`

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "docs: describe the harness split and update the paths it moved"
```

- [ ] **Step 8: Confirm the published artifact is still reachable**

```bash
git diff --stat artifact-1-published -- data/ build/figures-final/
```

Expected: no output. The data and the published figures are untouched by this plan; only the code that reads them moved.

---

## Self-review notes

**Spec coverage.** Every module named in the reuse analysis has a task: stats (4), vllm_logs (5), recorder (6), failures (7), store (8), scheduler (9), publish + presets (10), figure guards (11), RunPod + pins (12). The three things the analysis said do *not* exist — a concurrent load generator, a discrete-event simulator, a closed-loop platform driver — are deliberately out of scope and recorded as "Not yet here" in the harness README so the next reader does not assume they were missed.

**Parity.** Task 1 inventories by reading the code; Task 2 captures the baseline and builds the gate; every task from 3 onward runs that gate; Task 13 verifies removal and exercises each preserved capability through its real path. The four signature changes are the only caller-observable differences and each is logged with its reason and flagged for sign-off.

**Risk concentrated in two places.** Task 9 (scheduler) can change what a *new* record contains without changing any stored record, which the parity gate cannot see — Step 8 checks that directly. Task 10 (publishability) can change which rows count as publishable, which the gate *can* see, and an `analysis.json` diff there is the loudest signal in this plan.
