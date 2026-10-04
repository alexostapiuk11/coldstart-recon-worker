# Harness Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Extract the artifact-agnostic half of `coldstart/` into a `harness/` package so artifacts 2–5 inherit the measurement plumbing, statistics, publishability gate, and figure guard rails without inheriting artifact 1's cold-start vocabulary.

**Architecture:** Modules move by `git mv` into `harness/`, one module (or one split) per task, with imports rewritten across `coldstart/`, `worker/`, `scripts/`, and `tests/` in the same commit. Four modules are *split* rather than moved, because they mix generic machinery with artifact-1 constants: `pipeline.py` (machinery vs. `REQUIRED_FOR_*` presets), `checks.py` (failure taxonomy vs. clock reconciliation), `preflight.py` (the check vs. the pinned endpoint), and `figures.py` (guard rails vs. the four charts). Three modules are *generalized* where an artifact-1 name is hardcoded in a way that would block reuse: `JsonlStore` takes a record class, `build_schedule` speaks conditions/blocks instead of arms/triples, and the grouping functions take an explicit key. Everything else moves verbatim — the YAGNI line is that a name is generalized only when it would otherwise make artifact 2 or 5 store the wrong thing or group by the wrong column.

**Added 2026-09-26 by plan 2a:** `recon/analyse_a2.py` imports `coldstart.vllm_logs` and `coldstart.runpod_api`. Both move in this plan (Tasks 5 and 12), and the rewrite list above does not name `recon/`. Include it in those two tasks' import rewrites. `recon/capture.py` and `recon/capture_a2.py` import neither, by design.

**Revised 2026-10-03, after Tasks 1–3 landed, so agents can run the rest unattended.** The repository moved on after this plan was written, and several steps would have failed or done damage as written. The changes:

- **It runs in a dedicated worktree, and never stages with `git add -A`.** Other workstreams commit to the shared checkout and keep uncommitted work there, and this plan rewrites every importer of ten modules. See "How to run this plan".
- **Test counts are relative to a baseline recorded at the start.** The suite grew from 529 tests to 1,213, so every absolute count below was wrong.
- **The find-and-replace skips three files.** Their prose explains why artifact 2 does not import artifact 1, and rewriting it would make it false. Import forms the replace cannot match are edited by hand.
- **The parity gate already compares against the committed `docs/figures/`.** The script Task 2 committed improved on the text shown in Task 2 below, for exactly the worktree reason, and the text was never updated. It is left as the historical record; the committed `scripts/parity_check.sh` is authoritative.
- **Each task's list of files to edit is brought up to date.** The lists in Tasks 4, 5, 8, 10 and 12 now name every current importer and call site, including `autoscale/`, `recon/` and the explainer.
- **Task 11's rename command is fixed, and two constants are re-exported.** macOS `sed` has no `\b`, so the command silently matched nothing. Without the re-exports, ruff flags the constants as unused.
- **Task 12 re-places the explainer's code quote.** The inventory required it; the plan had no step for it.
- **Task 13's checks account for historical documents**, and its final diff uses tracked paths.
- **Both owner sign-offs are explicit STOP gates.**

The text before this revision is in git history at commit `d3b90d4`.

**The invariant that makes this safe:** `harness/` must never import `coldstart`. A test enforces the direction (Task 3), and every task ends with a parity gate that re-derives artifact 1's published numbers and re-renders its four figures.

**Tech Stack:** Python 3.13 (stdlib only in the moved modules, plus `requests` for the RunPod client and `matplotlib` for figures), pytest, ruff.

**Scope:** Refactor only. No behavior change is intended anywhere. Three signature changes are deliberate and logged in Task 1's decision log; everything else keeps its exact semantics, and the parity gate is what proves it.

---

## Prerequisite — do not start before this is true

The portfolio contract (artifact 1 spec §3) states that artifact 2 runs against the harness **"tagged at the commit that produced artifact 1's numbers."**

- [x] Artifact 1's post is published at its permanent slug. *(Artifact 2's final design records artifact 1 as complete.)*
- [x] A tag exists at the commit that produced the published numbers. *(Verified 2026-10-03: `artifact-1-published` is commit `5666765`, and `data/` and `docs/figures/` are unchanged since it.)*

- [x] You are in the dedicated worktree described in "How to run this plan" below, and `git status --porcelain --untracked-files=no` prints nothing.

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

## How to run this plan

**Tasks 1–3 are done** (commits `8ffa013`, `0bbc6ba`, `01f6c12`). Start at Task 4, after the worktree is set up and `N0` is recorded as described below.

### Work in a dedicated worktree, never in the shared checkout

Artifacts 2, 4 and 5 commit to `main` from the shared checkout and keep uncommitted work in it. This plan rewrites every importer of ten modules by find-and-replace. In the shared checkout it would edit, and then commit, other sessions' unfinished files.

```bash
MAIN=$(git rev-parse --show-toplevel)
git -C "$MAIN" worktree add "$MAIN/../artifacts-harness-extraction" -b harness-extraction main
cd "$MAIN/../artifacts-harness-extraction"
ln -s "$MAIN/.venv" .venv
```

`.gitignore` ignores the directory form `.venv/`, not a symlink, so `git status` lists `?? .venv` here. That is expected. Never stage it.

### Staging: never `git add -A` or `git add .`

Every commit step stages tracked changes with `-u`, names any new file explicitly, then checks that nothing was left out and nothing stray went in:

```bash
git add -u
git add <each new file the task names>
git diff --name-only               # must print nothing
git diff --cached --name-status    # review: only this task's files
```

`-u` stages modifications, deletions and renames of tracked files only, and in this worktree every tracked change is the task's own.

### Test counts are relative

Before Task 4, record `N0`, the collected test count before any move:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" --collect-only -q | tail -1
```

The `-o addopts=""` matters: `pyproject.toml` already adds `-q`, and a second one suppresses the total line. Expected: a single line of the form `N tests collected`. On 2026-10-03, at commit `ffad644`, it read `1213 tests collected`. Then run `./scripts/parity_check.sh` once, and expect `PARITY OK` before anything moves. Each task states its expected count as `N0` plus the tests this plan has added by then. Every test run below passes `-o addopts=""` for the same reason as the count command: without it the summary line with the count is suppressed. "Passes" means pytest exits 0 with exactly that count. A lower count means a test file stopped being collected: stop and investigate.

### The find-and-replace skips three files

Every replace command in Tasks 4–12 filters its file list through this pattern. Define it in the same shell as the command:

```bash
EXCLUDE='^(\./)?(\.venv/|autoscale/stats\.py$|autoscale/sim\.py$|tests/test_autoscale_boundary\.py$)'
```

`autoscale/stats.py`, `autoscale/sim.py` and `tests/test_autoscale_boundary.py` mention moved modules only in prose. That prose explains why artifact 2 does not import artifact 1's package. Rewriting the module names would make each sentence false. They are artifact 2's files, so leave them. Task 13 accounts for them.

### Imports are re-sorted after every rewrite

Renaming `coldstart.x` to `harness.x` moves an import to a different position in its block, and ruff's import-order rule then fails the parity gate. Each move task re-sorts imports, only in the files it changed, just before its gate. That is shown in each task, and it was checked on 2026-10-03 by dry-running Task 4 in a scratch worktree: 13 files changed, all tests passed, `PARITY OK`.

### Files that belong to artifact 2's workstream

The moves must edit imports in `autoscale/coldstart_ecdf.py`, `tests/test_coldstart_ecdf.py` and `tests/test_autoscale_stats.py`, or those files break. Change only the import lines, plus Task 8's one constructor call. If merging the branch conflicts in one of these files, keep `main`'s content and re-apply only this plan's import change.

### Never repair parity by regenerating outputs

`data/analysis.json` and `docs/figures/*.png` are the published artifact. If the parity gate fails, the step changed behavior. Undo the step and find out why. Never write `scripts/analyse.py` or `scripts/render_figures.py` output to those paths, and never edit them.

### Owner sign-off gates

Two gates stop the plan until the owner answers. Record the answer and its date beside the gate. **An unchecked gate means STOP and ask.**

- [x] **Before Task 4: the explainer.** The published explainer quotes `coldstart/preflight.py` through the `preflight-refuses` sentinel, and its card 1 names that path (`explainer/page.html`). Task 12 moves the file to `harness/runpod/preflight.py`. It also deletes one quoted line, `pinned = PINNED if pinned is None else pinned`, because the pin set becomes a required argument. The card's prose stays true either way.
  - **Option A (recommended).** The explainer follows the code. Task 12 updates the sentinel map and the card's path, and the next rebuild quotes one line fewer.
  - **Option B.** The explainer keeps quoting the code as published. That means teaching `coldstart/explainer/excerpts.py` to read from the `artifact-1-published` tag, which this plan does not include.

  Owner's answer and date: **Option A** — the explainer follows the code. 2026-10-04.
- [x] **Before Task 8: the four signature changes** in the inventory's "Moved with a deliberate signature change" table. Artifact 5's plan 1 asserts the new signatures in its prerequisites, and artifact 4's plans assume them, so declining one changes those plans too. Owner's answer and date: **all four approved**, 2026-10-04.

---

## Task 1: Capability inventory and keep/drop decision log

**Files:**
- Create: `docs/superpowers/plans/2026-09-03-harness-extraction-inventory.md`

The inventory below was built by reading the modules, not by trusting a description. **Verify each row against the code before committing it** — a capability that exists but is missing from this table is the failure mode this task exists to prevent.

- [x] **Step 1: Verify the inventory against the code**

Run the symbol dump and check every public name appears in the table below:

```bash
grep -n "^def \|^class \|^[A-Z_]* *[:=]" coldstart/*.py coldstart/analysis/*.py | grep -v "^.*:.*_[a-z]" | sed 's/(.*//'
```

- [x] **Step 2: Write the inventory document**

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

- [x] **Step 3: Commit**

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

- [x] **Step 1: Write the parity gate script**

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

- [x] **Step 2: Run it and confirm it passes on unmodified code**

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

- [x] **Step 3: Record the baseline**

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

- [x] **Step 4: Commit**

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

- [x] **Step 1: Write the failing boundary tests**

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

- [x] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_harness_boundary.py -v`
Expected: `test_harness_never_imports_coldstart` FAILS — `harness/` does not exist yet, so `rglob` raises nothing but the directory is absent; if it errors on the missing path that is the same signal. `test_dockerfile_copies_...` PASSES today (only `coldstart` is needed and only `coldstart` is copied).

- [x] **Step 3: Create the package and update the image**

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

- [x] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_harness_boundary.py -v`
Expected: 2 passed.

- [x] **Step 5: Run the parity gate**

Run: `./scripts/parity_check.sh`
Expected: `PARITY OK`, and the test count is now 529.

- [x] **Step 6: Commit**

```bash
git add harness tests/test_harness_boundary.py worker/Dockerfile .github/workflows/build-worker.yml
git commit -m "feat: add the harness package, its import-direction guard, and image coverage"
```

---

## Task 4: Move stats.py

**Files:**
- Move: `coldstart/analysis/stats.py` → `harness/stats.py`
- Modify, as of 2026-10-03: `coldstart/analysis/metrics.py`, `coldstart/analysis/figures.py`, `coldstart/explainer/numbers.py`, `scripts/analyse.py`, `autoscale/coldstart_ecdf.py`, `tests/test_stats.py`, `tests/test_pipeline.py`, `tests/test_end_to_end.py`, `tests/test_reproducibility.py`, `tests/test_metrics.py`, `tests/test_coldstart_ecdf.py`, `tests/test_autoscale_stats.py`

Moves verbatim. Nothing in it names a cold-start concept: `within_host_triples` takes condition labels as arguments rather than hardcoding arms.

- [x] **Step 1: Point the tests at the new path first**

In `tests/test_stats.py`, rewrite the two import statements:

```python
import harness.stats as stats_module
from harness.stats import (
```

(keep the imported name list exactly as it is)

- [x] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_stats.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'harness.stats'`

- [x] **Step 3: Move the module and rewrite every import**

```bash
git mv coldstart/analysis/stats.py harness/stats.py
EXCLUDE='^(\./)?(\.venv/|autoscale/stats\.py$|autoscale/sim\.py$|tests/test_autoscale_boundary\.py$)'
grep -rln "coldstart\.analysis\.stats" --include="*.py" . | grep -Ev "$EXCLUDE" | xargs sed -i '' 's/coldstart\.analysis\.stats/harness.stats/g'
```

`tests/test_autoscale_stats.py` imports the module in a form the replace cannot match. Edit that line by hand:

```python
    from harness import stats as a1
```

(it was `from coldstart.analysis import stats as a1`). Then confirm nothing still points at the old location:

```bash
grep -rlE "coldstart\.analysis\.stats|from coldstart\.analysis import stats" --include="*.py" . | grep -Ev "$EXCLUDE"
```

Expected: no output.

In `harness/stats.py`, if the module docstring names `coldstart`, reword it to name the harness instead. Then check the reverse-reference in `coldstart/analysis/figures.py`'s docstring, which points readers at `coldstart.analysis.stats.median`:

```bash
sed -i '' 's/``coldstart\.analysis\.stats\.median``/``harness.stats.median``/' coldstart/analysis/figures.py
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" -q`
Expected: exit 0, and the last line starts with `<N0> passed`.

- [x] **Step 5: Run the parity gate**

First re-sort the imports in the files this task changed. A renamed module sorts differently, and the gate's `ruff check .` fails on it otherwise:

```bash
git diff --name-only --diff-filter=d HEAD -- '*.py' | xargs .venv/bin/ruff check --fix --select I --quiet
```

Then run: `./scripts/parity_check.sh`
Expected: `PARITY OK`

- [x] **Step 6: Commit**

```bash
git add -u
git diff --name-only
git diff --cached --name-status
git commit -m "refactor: move stats into the harness"
```

Expected: `git diff --name-only` prints nothing, and the staged list holds only this task's files.

---

## Task 5: Move vllm_logs.py

**Files:**
- Move: `coldstart/vllm_logs.py` → `harness/vllm_logs.py`
- Modify, as of 2026-10-03: `coldstart/driver.py`, `coldstart/stubs/stub_endpoint.py`, `recon/analyse_a2.py`, `tests/test_vllm_logs.py`, `tests/test_stubs.py`, `tests/test_driver.py`

The engine-log parser is the single highest-value file for artifacts 4 and 5: artifact 4's fourth figure decomposes swap cost onto artifact 1's stage taxonomy, and artifact 5 reads KV blocks off the same lines.

- [x] **Step 1: Point the test at the new path first**

In `tests/test_vllm_logs.py`:

```python
from harness.vllm_logs import parse_engine_log
```

- [x] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_vllm_logs.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'harness.vllm_logs'`

- [x] **Step 3: Move the module and rewrite every import**

```bash
git mv coldstart/vllm_logs.py harness/vllm_logs.py
EXCLUDE='^(\./)?(\.venv/|autoscale/stats\.py$|autoscale/sim\.py$|tests/test_autoscale_boundary\.py$)'
grep -rln "coldstart\.vllm_logs\|coldstart/vllm_logs" --include="*.py" . | grep -Ev "$EXCLUDE" | xargs sed -i '' -e 's/coldstart\.vllm_logs/harness.vllm_logs/g' -e 's|coldstart/vllm_logs|harness/vllm_logs|g'
```

The second pattern catches prose references — `coldstart/analysis/pipeline.py`'s `REQUIRED_FOR_T_COMPILE` docstring points at `coldstart/vllm_logs.py`'s `PATTERNS`.

- [x] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" -q`
Expected: exit 0, and the last line starts with `<N0> passed`.

- [x] **Step 5: Run the parity gate**

First re-sort the imports in the files this task changed. A renamed module sorts differently, and the gate's `ruff check .` fails on it otherwise:

```bash
git diff --name-only --diff-filter=d HEAD -- '*.py' | xargs .venv/bin/ruff check --fix --select I --quiet
```

Then run: `./scripts/parity_check.sh`
Expected: `PARITY OK`

- [x] **Step 6: Commit**

```bash
git add -u
git diff --name-only
git diff --cached --name-status
git commit -m "refactor: move the engine-log parser into the harness"
```

Expected: `git diff --name-only` prints nothing, and the staged list holds only this task's files.

---

## Task 6: Move recorder.py

**Files:**
- Move: `coldstart/recorder.py` → `harness/recorder.py`
- Modify: `worker/handler.py`, `tests/test_recorder.py`, `tests/test_probe_units.py`

This is the module that makes Task 3's Dockerfile change load-bearing.

- [x] **Step 1: Point the test at the new path first**

In `tests/test_recorder.py`:

```python
from harness.recorder import StageRecorder
```

- [x] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_recorder.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'harness.recorder'`

- [x] **Step 3: Move the module and rewrite every import**

```bash
git mv coldstart/recorder.py harness/recorder.py
EXCLUDE='^(\./)?(\.venv/|autoscale/stats\.py$|autoscale/sim\.py$|tests/test_autoscale_boundary\.py$)'
grep -rln "coldstart\.recorder" --include="*.py" . | grep -Ev "$EXCLUDE" | xargs sed -i '' 's/coldstart\.recorder/harness.recorder/g'
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" -q`
Expected: exit 0, and the last line starts with `<N0> passed`, including `test_harness_boundary.py::test_dockerfile_copies_every_first_party_package_the_image_imports` — which now has something real to check, because `worker/handler.py` imports `harness.recorder`.

- [x] **Step 5: Prove the guard actually catches the failure it exists for**

Temporarily remove the `COPY harness /opt/harness` line from `worker/Dockerfile`, then:

Run: `.venv/bin/python -m pytest tests/test_harness_boundary.py -v`
Expected: FAIL with `worker/Dockerfile does not COPY ['harness']`

Restore the line and re-run:
Expected: 4 passed. Confirm with `git diff worker/Dockerfile` that the restored file is identical to before.

- [x] **Step 6: Run the parity gate**

First re-sort the imports in the files this task changed. A renamed module sorts differently, and the gate's `ruff check .` fails on it otherwise:

```bash
git diff --name-only --diff-filter=d HEAD -- '*.py' | xargs .venv/bin/ruff check --fix --select I --quiet
```

Then run: `./scripts/parity_check.sh`
Expected: `PARITY OK`

- [x] **Step 7: Commit**

```bash
git add -u
git diff --name-only
git diff --cached --name-status
git commit -m "refactor: move the stage recorder into the harness"
```

Expected: `git diff --name-only` prints nothing, and the staged list holds only this task's files.

---

## Task 7: Split the failure taxonomy out of checks.py

**Files:**
- Create: `harness/failures.py`
- Modify: `coldstart/checks.py`, `coldstart/driver.py`, `tests/test_checks.py`

`checks.py` holds two unrelated things: a string-to-`FailureClass` classifier (generic — these are platform and engine failure strings) and artifact 1's clock reconciliation (`compute_residual`, `check_consistency`). Only the first moves. `DiscardReason` stays: all five of its members are outputs of artifact 1's own checks, and `harness/publish.py` reads `.value` off whatever enum a row carries rather than importing one.

- [x] **Step 1: Point the test at the new paths first**

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

- [x] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_checks.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'harness.failures'`

- [x] **Step 3: Create harness/failures.py**

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

- [x] **Step 4: Rewrite the remaining import**

`coldstart/driver.py` imports `classify_failure` from `coldstart.checks`:

```python
from harness.failures import classify_failure
```

Confirm nothing else still expects the old location:

```bash
grep -rn "checks import.*classify_failure\|checks import.*FailureClass" --include="*.py" . | grep -v ".venv"
```

Expected: no output.

- [x] **Step 5: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" -q`
Expected: exit 0, and the last line starts with `<N0> passed`.

- [x] **Step 6: Run the parity gate**

First re-sort the imports in the files this task changed. A renamed module sorts differently, and the gate's `ruff check .` fails on it otherwise:

```bash
git diff --name-only --diff-filter=d HEAD -- '*.py' | xargs .venv/bin/ruff check --fix --select I --quiet
```

Then run: `./scripts/parity_check.sh`
Expected: `PARITY OK`

- [x] **Step 7: Commit**

```bash
git add -u
git add harness/failures.py
git diff --name-only
git diff --cached --name-status
git commit -m "refactor: move the failure taxonomy into the harness, leave the clock checks behind"
```

Expected: `git diff --name-only` prints nothing, and the staged list holds only this task's files.

---

## Task 8: Move the store and inject the record class

**Files:**
- Move: `coldstart/store.py` → `harness/store.py`
- Modify, as of 2026-10-03: `scripts/analyse.py`, `scripts/render_figures.py`, `scripts/run_window.py`, `scripts/prime_compile_cache.py`, `scripts/build_explainer.py`, `coldstart/explainer/numbers.py`, `autoscale/coldstart_ecdf.py`, `tests/test_store.py`, `tests/test_driver.py`, `tests/test_end_to_end.py`, `tests/test_reproducibility.py`

**Signature change** (inventory sign-off required): `JsonlStore(path)` → `JsonlStore(path, record_cls)`.

- [x] **Step 1: Write the failing test for the new signature**

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

- [x] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'harness.store'`

- [x] **Step 3: Move and generalize the store**

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

- [x] **Step 4: Update every construction site**

Rewrite the import path everywhere, then pass `RunRecord` at each construction:

```bash
EXCLUDE='^(\./)?(\.venv/|autoscale/stats\.py$|autoscale/sim\.py$|tests/test_autoscale_boundary\.py$)'
grep -rln "coldstart\.store" --include="*.py" . | grep -Ev "$EXCLUDE" | xargs sed -i '' 's/coldstart\.store/harness.store/g'
grep -rn "JsonlStore(" --include="*.py" . | grep -v ".venv"
```

Every hit gets `RunRecord` as its second argument. As of 2026-10-03 the sites are:

- `scripts/analyse.py`, `scripts/render_figures.py`, `scripts/run_window.py`: `JsonlStore(args.store, RunRecord)`
- `scripts/prime_compile_cache.py`: `JsonlStore(STORE, RunRecord)`
- `scripts/build_explainer.py`: `JsonlStore(str(self.repo / "data" / "campaign.jsonl"), RunRecord)`
- `coldstart/explainer/numbers.py`: `JsonlStore(str(Path(repo) / "data" / "campaign.jsonl"), RunRecord)`
- `autoscale/coldstart_ecdf.py`: `JsonlStore(path, RunRecord)`. This is the one module in `autoscale/` allowed to import `coldstart`.
- `tests/test_driver.py` (19 calls), `tests/test_end_to_end.py` (3), `tests/test_reproducibility.py` (2), and the existing calls in `tests/test_store.py`: add `, RunRecord` before each call's closing parenthesis.

Each file that does not already import `RunRecord` gets, beside its existing `coldstart` imports:

```python
from coldstart.schema import RunRecord
```

Confirm no single-argument construction is left:

```bash
grep -rn "JsonlStore(" --include="*.py" . | grep -v "\.venv/" | grep -v "RunRecord)\|SweepPoint)\|def __init__"
```

Expected: no output.

- [x] **Step 5: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" -q`
Expected: exit 0, and the last line starts with `<N0 + 1> passed`.

- [x] **Step 6: Run the parity gate**

First re-sort the imports in the files this task changed. A renamed module sorts differently, and the gate's `ruff check .` fails on it otherwise:

```bash
git diff --name-only --diff-filter=d HEAD -- '*.py' | xargs .venv/bin/ruff check --fix --select I --quiet
```

Then run: `./scripts/parity_check.sh`
Expected: `PARITY OK` — this proves `analyse.py` and `render_figures.py` still read the campaign correctly through the new signature.

- [x] **Step 7: Commit**

```bash
git add -u
git diff --name-only
git diff --cached --name-status
git commit -m "refactor: move the store into the harness and inject the record type"
```

Expected: `git diff --name-only` prints nothing, and the staged list holds only this task's files.

---

## Task 9: Move the scheduler and neutralize its vocabulary

**Files:**
- Move: `coldstart/scheduler.py` → `harness/scheduler.py`
- Modify: `coldstart/driver.py`, `tests/test_scheduler.py`, `tests/test_driver.py`

**Signature change** (inventory sign-off required): `build_schedule(arms, triples, seed)` → `build_schedule(conditions, blocks, seed)`, and `ScheduledRun.arm`/`.triple_index` → `.condition`/`.block_index`.

The RNG consumption order is untouched, so the same seed produces the same order. `coldstart/driver.py` maps the neutral names back to `arm`/`triple_index` when it builds a `RunRecord`, so **the stored JSONL is unchanged** — which the parity gate proves.

- [x] **Step 1: Write the failing test**

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

- [x] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_scheduler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'harness.scheduler'`

- [x] **Step 3: Move and rewrite the scheduler**

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

- [x] **Step 4: Map the names back in the driver**

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

- [x] **Step 5: Update the driver test's direct use**

`tests/test_driver.py` constructs `ScheduledRun` directly. Rewrite that import:

```python
    from harness.scheduler import ScheduledRun
```

and every construction to the new field names, e.g.:

```python
    scheduled = ScheduledRun(run_index=0, block_index=0, condition="A")
```

- [x] **Step 6: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" -q`
Expected: exit 0, and the last line starts with `<N0 + 3> passed`.

- [x] **Step 7: Run the parity gate**

First re-sort the imports in the files this task changed. A renamed module sorts differently, and the gate's `ruff check .` fails on it otherwise:

```bash
git diff --name-only --diff-filter=d HEAD -- '*.py' | xargs .venv/bin/ruff check --fix --select I --quiet
```

Then run: `./scripts/parity_check.sh`
Expected: `PARITY OK`

- [x] **Step 8: Verify the stored record shape did not move**

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

- [x] **Step 9: Commit**

```bash
git add -u
git diff --name-only
git diff --cached --name-status
git commit -m "refactor: move the scheduler into the harness and neutralize its vocabulary"
```

Expected: `git diff --name-only` prints nothing, and the staged list holds only this task's files.

---

## Task 10: Split pipeline.py into the harness gate and artifact 1's presets

**Files:**
- Move: `coldstart/analysis/pipeline.py` → `harness/publish.py`
- Create: `coldstart/analysis/presets.py`
- Modify, as of 2026-10-03: `coldstart/analysis/figures.py`, `harness/stats.py` (one docstring), `scripts/analyse.py`, `scripts/render_figures.py`, `autoscale/coldstart_ecdf.py`, `tests/test_pipeline.py`, `tests/test_figures.py`, `tests/test_end_to_end.py`, `tests/test_reproducibility.py`

The machinery is generic; the five `REQUIRED_FOR_*` presets name artifact 1's fields (`t_weights`, `t_compile`, `t_fast_seconds`) and carry rulings specific to its clock checks. They move to `coldstart/analysis/presets.py` **with their docstrings intact** — those docstrings are the record of decisions that were litigated once and must not be re-litigated.

**Signature change** (inventory sign-off required): `failure_rate_by_arm(rows)` → `failure_rate_by_group(rows, key)` and `discard_table(rows)` → `discard_table(rows, key)`, both with the key **required**.

- [x] **Step 1: Write the failing tests**

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

- [x] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'harness.publish'`

- [x] **Step 3: Move the module**

```bash
git mv coldstart/analysis/pipeline.py harness/publish.py
```

- [x] **Step 4: Move the presets out of it**

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

- [x] **Step 5: Require the grouping key**

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

- [x] **Step 6: Rewrite every import and call site**

```bash
EXCLUDE='^(\./)?(\.venv/|autoscale/stats\.py$|autoscale/sim\.py$|tests/test_autoscale_boundary\.py$)'
grep -rln "coldstart\.analysis\.pipeline\|coldstart/analysis/pipeline" --include="*.py" . | grep -Ev "$EXCLUDE" | xargs sed -i '' -e 's/coldstart\.analysis\.pipeline/harness.publish/g' -e 's|coldstart/analysis/pipeline|harness/publish|g'
```

Then, in each consumer, split the import so presets come from `coldstart.analysis.presets`:

- `scripts/analyse.py` — imports `REQUIRED_FOR_T_COMPILE`, `REQUIRED_FOR_T_TOTAL`, `REQUIRED_FOR_T_WEIGHTS` plus `PartitionResult`, `discard_table`, `failure_rate_by_arm`, `partition`
- `scripts/render_figures.py` — imports `REQUIRED_FOR_T_TOTAL`, `REQUIRED_FOR_WARMUP` plus `NotPublishableError`, `annotate_first_touch`, `partition`
- `tests/test_reproducibility.py` — imports `REQUIRED_FOR_T_COMPILE`, `REQUIRED_FOR_T_TOTAL` plus `partition`
- `autoscale/coldstart_ecdf.py` — imports `REQUIRED_FOR_T_TOTAL` (from `coldstart.analysis.presets`) plus `annotate_first_touch`, `partition` (from `harness.publish`)
- `tests/test_end_to_end.py`, `tests/test_figures.py` — route each imported name to its new owner

Rename every call. As of 2026-10-03 they are in `scripts/analyse.py` (one of each), `tests/test_end_to_end.py` (one of each, plus its import) and `tests/test_pipeline.py` (two of each, plus its import). In `scripts/analyse.py` the calls become:

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

**Do not rename the output key.** `scripts/analyse.py` stores the result as `out["failure_rate_by_arm"] = ...`, and that key is part of the published `data/analysis.json`. Only the function call on the right-hand side changes:

```python
    out["failure_rate_by_arm"] = failure_rate_by_group(rows, key="arm")
```

Prose that names the old function is renamed too: two docstrings in `harness/publish.py` and one in `scripts/analyse.py`.

Expected after the edit: the only remaining `failure_rate_by_arm` is that output key, and every `discard_table(` call passes `key=`.

- [x] **Step 7: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" -q`
Expected: exit 0, and the last line starts with `<N0 + 5> passed`.

- [x] **Step 8: Run the parity gate**

First re-sort the imports in the files this task changed. A renamed module sorts differently, and the gate's `ruff check .` fails on it otherwise:

```bash
git diff --name-only --diff-filter=d HEAD -- '*.py' | xargs .venv/bin/ruff check --fix --select I --quiet
```

Then run: `./scripts/parity_check.sh`
Expected: `PARITY OK` — this is the task most able to change a published number, because it touches what counts as publishable. An `analysis.json` diff here means a preset or the gate changed meaning.

- [x] **Step 9: Commit**

```bash
git add -u
git add coldstart/analysis/presets.py
git diff --name-only
git diff --cached --name-status
git commit -m "refactor: split the publishability gate from artifact 1's presets"
```

Expected: `git diff --name-only` prints nothing, and the staged list holds only this task's files.

---

## Task 11: Extract the figure guard rails

**Files:**
- Create: `harness/figure_guards.py`
- Modify: `coldstart/analysis/figures.py`, `tests/test_figures.py`

Every spec in the portfolio carries the same figure constraints — N stated, no truncated axes, legible on a phone, empty input refused, a missing arm never silently dropped. Those guards live inside `figures.py` today, and `_row_identity` is duplicated between `figures.py` and `pipeline.py`. This task extracts them once and DRYs the duplicate.

- [x] **Step 1: Write the failing test**

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

- [x] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_figure_guards.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'harness.figure_guards'`

- [x] **Step 3: Create harness/figure_guards.py**

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

- [x] **Step 4: Rewire figures.py onto the guards**

In `coldstart/analysis/figures.py`:

Delete the local `PHONE_WIDTH_PX`, `MIN_PHONE_TEXT_PX`, `phone_pt`, `_row_identity`, `_required_field`, `_validate_rows`, and `_by_arm` definitions, and import them instead. Two of the names are no longer used inside this module once the local definitions go, but tests import them from here: `tests/test_figures.py` takes both constants, and `tests/test_a2_figures.py` takes `MIN_PHONE_TEXT_PX`. They are imported with the explicit re-export form, so ruff does not flag them as unused:

```python
from harness.figure_guards import (
    MIN_PHONE_TEXT_PX as MIN_PHONE_TEXT_PX,  # re-exported: tests import it from here
    PHONE_WIDTH_PX as PHONE_WIDTH_PX,  # re-exported: tests import it from here
    group_required,
    phone_pt,
    required_field,
    row_identity,
    validate_rows,
)
```

`NotPublishableError` is already imported from `harness.publish` since Task 10; do not import it twice. If ruff later reports one of the other names as unused, remove that name from the import.

The module docstring near the top says "`_required_field` below replaces …". Reword it to name `required_field`, imported from `harness.figure_guards`, since nothing below defines it any more. The check after the next command expects no remaining mention.

Only after the definitions are deleted, rewrite the call sites. Running it before would turn `def _validate_rows(` into a local `def validate_rows(` that shadows the import. There is no `\b` in the patterns because macOS `sed` does not support it, and with it the command silently matches nothing:

```bash
sed -i '' -e 's/_validate_rows(/validate_rows(/g' -e 's/_required_field(/required_field(/g' -e 's/_row_identity(/row_identity(/g' coldstart/analysis/figures.py
grep -n "_validate_rows\|_required_field\|_row_identity\|def validate_rows\|def required_field" coldstart/analysis/figures.py
```

Expected from the `grep`: no output.

and replace each `_by_arm(rows)` call with:

```python
    by = group_required(rows, "arm", ARMS)
```

`ARMS`, `S4_SUBPHASE_KEYS`, `RESIDUAL_COLOR`, and the sub-phase labels and colors stay in `figures.py` — they are artifact 1's.

- [x] **Step 5: Leave publish.py's identity helper where it is, and say why**

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

- [x] **Step 6: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" -q`
Expected: exit 0, and the last line starts with `<N0 + 12> passed`.

Run: `.venv/bin/python -m ruff check .`
Expected: `All checks passed!`

- [x] **Step 7: Run the parity gate**

First re-sort the imports in the files this task changed. A renamed module sorts differently, and the gate's `ruff check .` fails on it otherwise:

```bash
git diff --name-only --diff-filter=d HEAD -- '*.py' | xargs .venv/bin/ruff check --fix --select I --quiet
```

Then run: `./scripts/parity_check.sh`
Expected: `PARITY OK` — the figure bytes are the assertion that no guard changed what gets drawn.

- [x] **Step 8: Look at the figures**

Byte-identical PNGs are the same pixels that were inspected and published, so this is a confirmation rather than a fresh review. But per the repo's own rule, a figure task does not end without eyes on the figure. View each of `docs/figures/waterfall.png`, `docs/figures/warmup.png`, `docs/figures/ecdf.png` and `docs/figures/per_host.png` with the Read tool, which displays images.

Confirm each renders, then note in the task report that the gate found the fresh renders `cmp`-identical to them.

- [x] **Step 9: Commit**

```bash
git add -u
git add harness/figure_guards.py
git add tests/test_figure_guards.py
git diff --name-only
git diff --cached --name-status
git commit -m "refactor: extract the shared figure guards, including phone legibility"
```

Expected: `git diff --name-only` prints nothing, and the staged list holds only this task's files.

---

## Task 12: Move the RunPod plumbing and separate artifact 1's pins

**Files:**
- Move: `coldstart/submitter.py` → `harness/submit.py`
- Move: `coldstart/runpod_api.py` → `harness/runpod/api.py`
- Move: `coldstart/runpod_submitter.py` → `harness/runpod/submitter.py`
- Move: `coldstart/preflight.py` → `harness/runpod/preflight.py`
- Create: `coldstart/pins.py`
- Modify, as of 2026-10-03: `coldstart/driver.py`, `coldstart/stubs/stub_endpoint.py`, `coldstart/explainer/excerpts.py`, `explainer/page.html`, `recon/analyse_a2.py`, `scripts/run_window.py`, `scripts/prime_compile_cache.py`, `tests/test_submitter.py`, `tests/test_runpod_api.py`, `tests/test_runpod_submitter.py`, `tests/test_preflight.py`, `tests/test_driver.py`, `tests/test_end_to_end.py`

**Signature change** (inventory sign-off required): `assert_endpoint_matches(endpoint, pinned=None)` → `assert_endpoint_matches(endpoint, pinned)`, required.

- [x] **Step 1: Write the failing test**

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

- [x] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_preflight.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'coldstart.pins'`

- [x] **Step 3: Move the four modules**

```bash
git mv coldstart/submitter.py harness/submit.py
git mv coldstart/runpod_api.py harness/runpod/api.py
git mv coldstart/runpod_submitter.py harness/runpod/submitter.py
git mv coldstart/preflight.py harness/runpod/preflight.py
```

Rewrite the import paths across the tree:

```bash
EXCLUDE='^(\./)?(\.venv/|autoscale/stats\.py$|autoscale/sim\.py$|tests/test_autoscale_boundary\.py$)'
grep -rln "coldstart\.runpod_submitter\|coldstart\.runpod_api\|coldstart\.submitter\|coldstart\.preflight" --include="*.py" . | grep -Ev "$EXCLUDE" | xargs sed -i '' \
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

- [x] **Step 4: Split the pins out of preflight**

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

- [x] **Step 4b: Re-place the explainer's code quote**

This step assumes the owner chose option A at the explainer gate. If they chose option B, STOP: this plan does not cover it.

The line Step 4 deleted, `pinned = PINNED if pinned is None else pinned`, sat inside the `# explainer:preflight-refuses` … `# explainer:end` block. Keep both markers and the comment between them. The block now holds that comment and the two-line `if not pinned: raise`.

In `coldstart/explainer/excerpts.py`, point the slug at the file's new home:

```python
    "preflight-refuses": "harness/runpod/preflight.py",
```

In `explainer/page.html`, card 1's path label:

```html
    <p class="where">harness/runpod/preflight.py</p>
```

Check the quote and the build:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -c "
from pathlib import Path
from coldstart.explainer.excerpts import extract
print(extract('preflight-refuses', Path('.')))"
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_explainer_excerpts.py tests/test_explainer_build.py -q
```

Expected: the excerpt prints the comment and the `if not pinned:` raise, with no `PINNED`, and both test files pass.

- [x] **Step 5: Update the two callers**

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

- [x] **Step 6: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" -q`
Expected: exit 0, and the last line starts with `<N0 + 14> passed`.

- [x] **Step 7: Run the parity gate**

First re-sort the imports in the files this task changed. A renamed module sorts differently, and the gate's `ruff check .` fails on it otherwise:

```bash
git diff --name-only --diff-filter=d HEAD -- '*.py' | xargs .venv/bin/ruff check --fix --select I --quiet
```

Then run: `./scripts/parity_check.sh`
Expected: `PARITY OK`

- [x] **Step 8: Commit**

```bash
git add -u
git add coldstart/pins.py
git diff --name-only
git diff --cached --name-status
git commit -m "refactor: move the RunPod client into the harness, leave artifact 1's pins behind"
```

Expected: `git diff --name-only` prints nothing, and the staged list holds only this task's files.

---

## Task 13: Parity gate, deletion verification, and documentation

**Files:**
- Modify: `docs/runbook.md`, `recon/README.md` (only where they name a moved path; as of 2026-10-03, `fixtures/README.md` names none)
- Create: `harness/README.md`

Nothing is deleted in this task — the moves already removed the old locations, and each was gated by a passing parity check as it happened. This task verifies that in one place, and makes the split legible to whoever picks up artifact 2.

- [x] **Step 1: Verify every moved module landed and nothing dangles**

```bash
test ! -e coldstart/analysis/stats.py && test ! -e coldstart/analysis/pipeline.py && \
test ! -e coldstart/store.py && test ! -e coldstart/scheduler.py && \
test ! -e coldstart/recorder.py && test ! -e coldstart/vllm_logs.py && \
test ! -e coldstart/submitter.py && test ! -e coldstart/runpod_api.py && \
test ! -e coldstart/runpod_submitter.py && test ! -e coldstart/preflight.py && \
echo "all ten old locations removed"
```

```bash
grep -rn "coldstart\.\(store\|scheduler\|recorder\|vllm_logs\|submitter\|runpod_api\|runpod_submitter\|preflight\)\|coldstart\.analysis\.\(stats\|pipeline\)" --include="*.py" . | grep -Ev '^(\./)?(\.venv/|autoscale/stats\.py:|autoscale/sim\.py:|tests/test_autoscale_boundary\.py:)'
```

Expected: no output. Python only: the markdown docs are updated in Step 5 and checked there. The three excluded files are the prose files the find-and-replace skipped, as "How to run this plan" explains.

- [x] **Step 2: Verify each preserved capability is exercised, not merely importable**

Parity is about behavior. Run the capabilities the inventory marked Preserved through their real paths:

```bash
.venv/bin/python -m pytest -q tests/test_stats.py tests/test_vllm_logs.py tests/test_recorder.py \
  tests/test_checks.py tests/test_store.py tests/test_scheduler.py tests/test_pipeline.py \
  tests/test_figures.py tests/test_figure_guards.py tests/test_submitter.py \
  tests/test_runpod_api.py tests/test_runpod_submitter.py tests/test_preflight.py \
  tests/test_driver.py tests/test_end_to_end.py tests/test_reproducibility.py -v 2>&1 | tail -5
```

Expected: all pass. `test_end_to_end.py` and `test_reproducibility.py` are the two that exercise the whole chain — schedule, submit, store, derive, partition, bootstrap — through the moved modules at once.

- [x] **Step 3: Run the full parity gate one final time**

Run: `./scripts/parity_check.sh`
Expected: `PARITY OK`

- [x] **Step 4: Write the harness README**

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

The in-container tooling artifacts 2, 4 and 5 share comes from its own plan,
per artifact 4's scope amendment (decision 4): the `vllm serve` lifecycle
(`serve.py`), the load path (`bench.py`), and the single-engine service-curve
sweep. The discrete-event simulators live with their artifacts: `autoscale/`
for artifact 2, and `placement/` for artifact 4.
```

- [x] **Step 5: Update the docs that name a moved path**

```bash
grep -rn "coldstart/\(store\|scheduler\|recorder\|vllm_logs\|submitter\|runpod_api\|runpod_submitter\|preflight\)\.py\|coldstart/analysis/\(stats\|pipeline\)\.py" docs/runbook.md docs/experiment.md fixtures/README.md recon/README.md
```

For each hit **in `docs/runbook.md` and `recon/README.md`**, rewrite the path to its new location. Then confirm no live doc still names an old path:

```bash
grep -rln "coldstart\.\(store\|scheduler\|recorder\|vllm_logs\|submitter\|runpod_api\|runpod_submitter\|preflight\)\|coldstart\.analysis\.\(stats\|pipeline\)\|coldstart/\(store\|scheduler\|recorder\|vllm_logs\|submitter\|runpod_api\|runpod_submitter\|preflight\)\.py\|coldstart/analysis/\(stats\|pipeline\)\.py" --include="*.md" . | grep -Ev '^(\./)?(\.venv/|docs/superpowers/|docs/experiment\.md$)'
```

Expected: no output. `docs/superpowers/` holds plans and specs, which record the code as it was when they were written. **Do not touch `docs/experiment.md`** — it is the pre-registration, its git timestamp is the evidence that the hypotheses were fixed in advance, and it describes the code as it was when the campaign ran.

- [x] **Step 6: Re-run everything**

Run: `./scripts/parity_check.sh`
Expected: `PARITY OK`

- [x] **Step 7: Commit**

```bash
git add -u
git add harness/README.md
git diff --name-only
git diff --cached --name-status
git commit -m "docs: describe the harness split and update the paths it moved"
```

Expected: `git diff --name-only` prints nothing, and the staged list holds only this task's files.

- [x] **Step 8: Confirm the published artifact is still reachable**

```bash
git diff --stat artifact-1-published -- data/ docs/figures/
```

Expected: no output. The data and the published figures are untouched by this plan; only the code that reads them moved. (`build/` is gitignored, so it cannot be checked this way.)

- [x] **Step 9: Rebase, re-check, and hand back**

```bash
git rebase main
./scripts/parity_check.sh
```

Expected: `PARITY OK` on the rebased branch. Resolve any conflict in an artifact 2 file as "How to run this plan" describes. Then stop and report. Merging `harness-extraction` into `main` is the owner's decision, because other workstreams depend on the old import paths until they rebase. Use superpowers:finishing-a-development-branch for that handoff.

---

## Self-review notes

**Spec coverage.** Every module named in the reuse analysis has a task: stats (4), vllm_logs (5), recorder (6), failures (7), store (8), scheduler (9), publish + presets (10), figure guards (11), RunPod + pins (12). The three things the analysis said do *not* exist — a concurrent load generator, a discrete-event simulator, a closed-loop platform driver — are deliberately out of scope and recorded as "Not yet here" in the harness README so the next reader does not assume they were missed.

**Parity.** Task 1 inventories by reading the code; Task 2 captures the baseline and builds the gate; every task from 3 onward runs that gate; Task 13 verifies removal and exercises each preserved capability through its real path. The four signature changes are the only caller-observable differences and each is logged with its reason and flagged for sign-off.

**Risk concentrated in two places.** Task 9 (scheduler) can change what a *new* record contains without changing any stored record, which the parity gate cannot see — Step 8 checks that directly. Task 10 (publishability) can change which rows count as publishable, which the gate *can* see, and an `analysis.json` diff there is the loudest signal in this plan.
