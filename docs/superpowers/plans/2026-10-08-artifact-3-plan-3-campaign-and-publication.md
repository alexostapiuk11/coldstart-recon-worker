# Artifact 3 Plan 3 — Campaign and Publication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rehearse the paid path on the stub, run the campaign, recovery, slice and exploratory phases, record the spend, and publish the analysis, four figures and post, with every number in the post generated from the committed analysis and tests that fail if anything drifts.

**Architecture:** The same library code as plans 1 and 2. `scripts/a3_run.py` runs each phase through `toolcall.runner`, which refuses to start without an approval covering its estimate and meters every call. `scripts/a3_analyse.py` writes one JSON file; the figures and the post's numbers block are generated from it. `scripts/a3_prepublish_check.py` reads the files that will ship and refuses while anything is unfinished.

**Tech Stack:** Python 3.13, pytest, matplotlib, the `openai` and `anthropic` SDKs, and plan 1's `toolcall/`.

**Spec:** [the amendment](../specs/2026-10-08-tool-calling-reliability-amendment.md), §2 (hypotheses and related work), §8 (budget and spend record), §9 (process), §10 (slug), §12 (definition of done), with the [August design](../specs/2026-08-17-tool-calling-reliability-harness-design.md)'s §8 post structure and required explanations.

**Plan 3 of 3.** [Plan 1](2026-10-08-artifact-3-plan-1-offline-core.md) built the code and the suite; [plan 2](2026-10-08-artifact-3-plan-2-pilot-and-preregistration.md) ran the pilot and committed the pre-registration.

**This plan spends most of artifact 3's budget:** the amount step 2 approved, about $39 by the amendment's estimate (§8, revised in §14), within the $40-60 target. Every paid phase asks the author first, stating its call count and estimate, and the runner stops if metered spend reaches the approved amount.

**How this plan was checked:** every script and test below was run on 2026-10-08 in a clone of `main` with plans 1 and 2's code in place. The whole paid path ran end to end on the stub against a 66-scenario synthetic suite: the campaign, recovery, slice and exploratory phases, the metered spend, a billed figure with a gap (to exercise the explanation rule), the analysis, the four figures and the numbers block. The analysis and the eight figure files were each generated twice and compared byte-identical. The post, published-figures and pre-publish tests passed against that rehearsal, and the pre-publish check refused the rehearsal post for its placeholder date and for each hypothesis verdict its prose did not state. The nine files this plan creates were extracted from this document into a fresh clone beside plans 1 and 2, byte-identical to the tested sources, and ruff was clean on them. The paid phases themselves have not been run.

---

## Prerequisites — do not start before these are true

- [ ] **Plan 2 is complete.** `docs/experiment-a3.md` has its step 2, and `.venv/bin/python -m pytest tests/test_toolcall_prereg_values.py -v` reports 3 passed.
- [ ] **No campaign data exists.** `ls data/a3/` shows only `pilot-*` files and `selection.json`, and `git log --oneline -1 -- docs/experiment-a3.md` is the step-2 commit.
- [ ] **The API keys are set** in the shell by the author (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`), never in chat or a file.
- [ ] **`git status --porcelain` is empty**; work on a branch: `git checkout -b artifact-3-plan-3`.

Publication (Task 12) additionally waits for **artifacts 2 and 4 to publish first** (amendment §1). Everything before it may run now.

---

## File structure

```
toolcall/spend.py               CREATE: metered spend from the stores; the spend record
scripts/
  a3_spend.py                   CREATE: print the metered spend; write data/a3/spend.json
  a3_analyse.py                 CREATE (Task 1): data/a3/analysis.json
  a3_numbers.py                 CREATE: write or check the post's numbers block
  a3_prepublish_check.py        CREATE: refuse the post while anything is unfinished
tests/
  test_toolcall_spend.py        CREATE
  test_a3_published_figures.py  CREATE: figures match a fresh render, byte for byte
  test_a3_post.py               CREATE: numbers, figures, sections, explanations, slug
  test_a3_prepublish_check.py   CREATE
data/a3/                        CREATED BY RUNNING: campaign, recovery, slice, exploratory, spend, analysis
docs/
  figures/a3/                   CREATED BY RUNNING: eight PNGs
  post-a3.md                    CREATE
  spend-a3.md                   CREATE
  dod-a3.md                     CREATE
```

---
## Task 1: Rehearse the whole paid path on the stub

The paid phases are expensive to debug. This runs exactly the same code path, the real suite and the real pre-registration, on the stub model, into `build/a3-rehearsal/`. It also creates the analysis script (it spends nothing) and confirms the analysis and figures are deterministic, which the published-figures test relies on.

**Files:**
- Create: `scripts/a3_analyse.py`

- [ ] **Step 1: Write the analysis script**

Create `scripts/a3_analyse.py`:

```python
"""Write data/a3/analysis.json from the committed stores (plan 3 Task 7).

    .venv/bin/python scripts/a3_analyse.py
    .venv/bin/python scripts/a3_analyse.py --data build/a3-rehearsal --out build/a3-rehearsal/analysis.json

Reads the campaign, recovery, slice and exploratory stores and, if present,
data/a3/spend.json. Spends nothing; needs no network.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.store import JsonlStore
from toolcall.analysis import analyse
from toolcall.prereg_values import PREREG
from toolcall.records import CallRecord, RecoveryRecord
from toolcall.scenarios import load_scenarios
from toolcall.tools import load_library

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=REPO / "data" / "a3")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--suite", type=Path, default=REPO / "toolcall" / "data")
    args = ap.parse_args()
    lib = load_library(args.suite / "tools")
    scenarios = load_scenarios(args.suite / "scenarios", lib)
    d = args.data
    calls = JsonlStore(d / "campaign.jsonl", CallRecord).read_all()
    recs = JsonlStore(d / "recovery.jsonl", RecoveryRecord).read_all()
    slices = {m.model: JsonlStore(d / f"slice-{m.model}.jsonl", CallRecord).read_all()
              for m in PREREG.slice_models}
    explo = JsonlStore(d / "exploratory.jsonl", CallRecord).read_all() or None
    spend_path = d / "spend.json"
    spend = json.loads(spend_path.read_text()) if spend_path.exists() else None
    a = analyse(calls, recs, scenarios, PREREG, slices={k: v for k, v in slices.items() if v},
                exploratory=explo, spend=spend)
    out = args.out or d / "analysis.json"
    out.write_text(json.dumps(a, indent=1, sort_keys=True) + "\n")
    print(f"[ok] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run every phase on the stub**

```bash
for p in campaign recovery slice exploratory; do
  .venv/bin/python scripts/a3_run.py $p --stub
done
```
Expected: per phase, the announcement and `[ok]` lines under `build/a3-rehearsal/`. Write down each phase's call count and estimate; Tasks 2-5 ask for approval with them.

- [ ] **Step 3: Analyse and render it twice**

```bash
.venv/bin/python scripts/a3_analyse.py --data build/a3-rehearsal --out build/a3-rehearsal/analysis.json
cp build/a3-rehearsal/analysis.json build/a3-rehearsal/analysis-1.json
.venv/bin/python scripts/a3_analyse.py --data build/a3-rehearsal --out build/a3-rehearsal/analysis.json
cmp build/a3-rehearsal/analysis.json build/a3-rehearsal/analysis-1.json && echo identical
.venv/bin/python scripts/a3_render_figures.py --analysis build/a3-rehearsal/analysis.json --out build/a3-rehearsal/f1
.venv/bin/python scripts/a3_render_figures.py --analysis build/a3-rehearsal/analysis.json --out build/a3-rehearsal/f2
for f in build/a3-rehearsal/f1/*.png; do cmp -s "$f" "build/a3-rehearsal/f2/$(basename $f)" || echo "DIFF $f"; done; echo compared
```
Expected: `identical`, and `compared` with no `DIFF` line.

- [ ] **Step 4: Confirm nothing touched `data/a3/`**

```bash
ls data/a3/
```
Expected: still only the pilot files and `selection.json`.

- [ ] **Step 5: Commit**

```bash
git add scripts/a3_analyse.py
git commit -m "feat: artifact 3's analysis script, rehearsed on the stub"
```

---

## Task 2: The campaign (paid)

All eight cells × every included scenario × N repetitions on the primary model, interleaved by block (amendment §5). The largest phase: most of the budget.

**Files:**
- Create (by running): `data/a3/campaign.jsonl`

- [ ] **Step 1: Ask for the approval**

Run the phase on the stub first to print its exact call count and estimate:
```bash
.venv/bin/python scripts/a3_run.py campaign --stub
```
Then ask: **"The campaign phase sends <calls> calls (8 cells x S scenarios x N repetitions), estimated $<estimate>. May I run it with --approved-usd <estimate plus 25%, within what step 2 approved>?"** Wait for a yes.

- [ ] **Step 2: Run it (paid)**

```bash
.venv/bin/python scripts/a3_run.py campaign --approved-usd <approved>
```
Expected: the announcement, `[ok]` per store, and the metered spend. If it stops part-way, re-run the same command with `--resume`: stored runs are skipped and a drifted schedule is refused. A `refused:` line means the estimate exceeded the approval: ask again, never raise it unasked.

- [ ] **Step 3: Check the excluded outcomes**

```bash
.venv/bin/python -c "
from harness.store import JsonlStore
from toolcall.analysis import counts_by_cell
from toolcall.records import CallRecord
for cell, c in counts_by_cell(JsonlStore('data/a3/campaign.jsonl', CallRecord).read_all()).items():
    print(cell, c['calls'], 'excluded share', round(c['excluded_share'], 4))
"
```
Expected: eight cells with equal call counts. Any cell above 0.02 is flagged in the post (amendment §4g), not re-run.

- [ ] **Step 4: Commit**

```bash
git add data/a3/campaign.jsonl
git commit -m "data: artifact 3's campaign"
```

---

## Task 3: Recovery (paid)

The baseline and best cells (best by the campaign's own failure rates, the pre-registered rule), every included recovery scenario, both message formats, N conversations each, up to three attempts after the error (amendment §4e).

**Files:**
- Create (by running): `data/a3/recovery.jsonl`

- [ ] **Step 1: Ask for the approval**

Run the phase on the stub first to print its exact call count and estimate:
```bash
.venv/bin/python scripts/a3_run.py recovery --stub
```
Then ask: **"The recovery phase sends <calls> calls (2 cells x 2 formats x recovery scenarios x N, about 3 turns each), estimated $<estimate>. May I run it with --approved-usd <estimate plus 25%, within what step 2 approved>?"** Wait for a yes.

- [ ] **Step 2: Run it (paid)**

```bash
.venv/bin/python scripts/a3_run.py recovery --approved-usd <approved>
```
Expected: the announcement, `[ok]` per store, and the metered spend. If it stops part-way, re-run the same command with `--resume`: stored runs are skipped and a drifted schedule is refused. A `refused:` line means the estimate exceeded the approval: ask again, never raise it unasked.

- [ ] **Step 3: Commit**

```bash
git add data/a3/recovery.jsonl
git commit -m "data: artifact 3's recovery conversations"
```

---

## Task 4: The cross-model slice (paid)

The best and worst cells, every included scenario, N repetitions, on `gpt-5.4-nano-2026-03-17` and `claude-sonnet-5-5` (amendment §3). Sonnet runs with no temperature and thinking `between_tools`; the post discloses both.

**Files:**
- Create (by running): `data/a3/slice-gpt-5.4-nano-2026-03-17.jsonl`, `data/a3/slice-claude-sonnet-5-5.jsonl`

- [ ] **Step 1: Ask for the approval**

Run the phase on the stub first to print its exact call count and estimate:
```bash
.venv/bin/python scripts/a3_run.py slice --stub
```
Then ask: **"The slice phase sends <calls> calls (2 cells x S x N, per slice model), estimated $<estimate>. May I run it with --approved-usd <estimate plus 25%, within what step 2 approved>?"** Wait for a yes.

- [ ] **Step 2: Run it (paid)**

```bash
.venv/bin/python scripts/a3_run.py slice --approved-usd <approved>
```
Expected: the announcement, `[ok]` per store, and the metered spend. If it stops part-way, re-run the same command with `--resume`: stored runs are skipped and a drifted schedule is refused. A `refused:` line means the estimate exceeded the approval: ask again, never raise it unasked.

- [ ] **Step 3: Commit**

```bash
git add data/a3/slice-*.jsonl
git commit -m "data: artifact 3's cross-model slice"
```

---

## Task 5: The exploratory constrained-decoding run (paid; first to cut)

The best cell with provider strict mode on, on the primary model (amendment §4a), labelled exploratory everywhere. **If step 2 cut it, skip this task** and say so in the post's Limits.

**Files:**
- Create (by running): `data/a3/exploratory.jsonl`

- [ ] **Step 1: Ask for the approval**

Run the phase on the stub first to print its exact call count and estimate:
```bash
.venv/bin/python scripts/a3_run.py exploratory --stub
```
Then ask: **"The exploratory phase sends <calls> calls (1 cell x S x N, strict mode on), estimated $<estimate>. May I run it with --approved-usd <estimate plus 25%, within what step 2 approved>?"** Wait for a yes.

- [ ] **Step 2: Run it (paid)**

```bash
.venv/bin/python scripts/a3_run.py exploratory --approved-usd <approved>
```
Expected: the announcement, `[ok]` per store, and the metered spend. If it stops part-way, re-run the same command with `--resume`: stored runs are skipped and a drifted schedule is refused. A `refused:` line means the estimate exceeded the approval: ask again, never raise it unasked.

- [ ] **Step 3: Commit**

```bash
git add data/a3/exploratory.jsonl
git commit -m "data: artifact 3's exploratory constrained-decoding run"
```

---

## Task 6: The spend record

Amendment §8: metered spend from the stores, and billed spend as the providers report it, read by the author. A gap above 5% is explained in the record, and the pre-publish check refuses an unexplained one.

**Files:**
- Create: `toolcall/spend.py`, `scripts/a3_spend.py`, `docs/spend-a3.md`
- Test: `tests/test_toolcall_spend.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_toolcall_spend.py`:

```python
"""The spend record: metered from the stores, compared with what was billed."""

import pytest

from tests.a3_examples import example_prereg, library, scenarios, synthetic_suite
from toolcall.runner import run_phase
from toolcall.spend import metered, spend_record, table


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    d = tmp_path_factory.mktemp("spend")
    scs = scenarios(synthetic_suite(24, 2))
    for phase in ("pilot-baseline", "pilot-recovery"):
        run_phase(phase, example_prereg(), library(), scs, d, stub=True, say=lambda m: None)
    return d


def test_every_store_is_metered_from_its_records(data):
    rows = metered(data)
    assert {r["store"] for r in rows} == {"pilot-baseline.jsonl", "pilot-recovery.jsonl"}
    assert all(r["usd"] > 0 and r["records"] > 0 for r in rows)


def test_a_gap_above_five_percent_needs_explaining(data):
    m = sum(r["usd"] for r in metered(data))
    close = spend_record(data, {"openai": m * 1.04}, "2026-10-30")
    far = spend_record(data, {"openai": m * 1.2}, "2026-10-30")
    assert not close["needs_explanation"] and far["needs_explanation"]
    assert far["gap"] == pytest.approx(0.2)


def test_the_table_states_metered_and_billed_totals(data):
    t = table(spend_record(data, {"openai": 1.0, "anthropic": 0.5}, "2026-10-30"))
    assert "**metered total**" in t and "**billed total** | | | **1.5000**" in t
    assert "billed, anthropic (read 2026-10-30)" in t
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_toolcall_spend.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'toolcall.spend'`.

- [ ] **Step 3: Write the module and the script**

Create `toolcall/spend.py`:

```python
"""What artifact 3 spent, metered from its own records (amendment §8).

Every stored call carries its own usage and the cost at the pinned price, so
the metered total is a sum over the stores. The billed total is what the
providers' usage pages show for the run's dates, read by the owner; the record
states both, and a gap above 5% is explained in docs/spend-a3.md.
"""

import json
from pathlib import Path

from harness.store import JsonlStore
from toolcall.records import CallRecord, RecoveryRecord

TOLERANCE = 0.05


def _records(path: Path):
    for cls in (CallRecord, RecoveryRecord):
        try:
            return JsonlStore(path, cls).read_all()
        except TypeError:
            continue
    raise ValueError(f"{path} holds neither call nor recovery records")


def metered(data: Path) -> list[dict]:
    rows = []
    for path in sorted(Path(data).glob("*.jsonl")):
        recs = _records(path)
        if not recs:
            continue
        rows.append({
            "store": path.name,
            "model": recs[0].model,
            "records": len(recs),
            "usd": sum(r.cost_usd or 0.0 for r in recs),
        })
    return rows


def spend_record(data: Path, billed: dict[str, float], read: str) -> dict:
    rows = metered(data)
    m = sum(r["usd"] for r in rows)
    b = sum(billed.values())
    gap = (b - m) / m if m else None
    return {"metered_usd": m, "billed_usd": b, "billed_by_provider": billed, "read": read,
            "gap": gap, "needs_explanation": gap is not None and abs(gap) > TOLERANCE,
            "stores": rows}


def table(record: dict) -> str:
    lines = ["| store | model | records | metered USD |", "|---|---|---|---|"]
    lines += [f"| `{r['store']}` | `{r['model']}` | {r['records']:,} | {r['usd']:.4f} |"
              for r in record["stores"]]
    lines.append(f"| **metered total** | | | **{record['metered_usd']:.4f}** |")
    for provider, usd in sorted(record["billed_by_provider"].items()):
        lines.append(f"| billed, {provider} (read {record['read']}) | | | {usd:.4f} |")
    lines.append(f"| **billed total** | | | **{record['billed_usd']:.4f}** |")
    return "\n".join(lines)


def write(record: dict, path: Path) -> None:
    Path(path).write_text(json.dumps(record, indent=1, sort_keys=True) + "\n")
```

Create `scripts/a3_spend.py`:

```python
"""Artifact 3's spend: metered from the stores, billed as the owner read it.

    .venv/bin/python scripts/a3_spend.py                      # metered only, prints the table
    .venv/bin/python scripts/a3_spend.py --billed openai=12.34 anthropic=8.90 --read 2026-10-30

With --billed, writes data/a3/spend.json, which the analysis carries into the
post. The billed figures come from the providers' usage pages for the run's
dates, read by the owner; this script does not call any billing API.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from toolcall.spend import metered, spend_record, table, write

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=REPO / "data" / "a3")
    ap.add_argument("--billed", nargs="*", default=[])
    ap.add_argument("--read")
    args = ap.parse_args()
    if not args.billed:
        rows = metered(args.data)
        for r in rows:
            print(f"{r['store']:45s} {r['model']:28s} {r['records']:6d}  ${r['usd']:.4f}")
        print(f"metered total ${sum(r['usd'] for r in rows):.4f}")
        return 0
    if not args.read:
        ap.error("--read (the date the usage pages were read) is required with --billed")
    billed = {k: float(v) for k, v in (x.split("=", 1) for x in args.billed)}
    record = spend_record(args.data, billed, args.read)
    write(record, args.data / "spend.json")
    print(table(record))
    if record["needs_explanation"]:
        print(f"\nThe billed total differs from the metered one by {record['gap']:+.1%}; "
              "docs/spend-a3.md must explain it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_toolcall_spend.py -v`
Expected: 3 passed.

- [ ] **Step 5: Print the metered spend**

```bash
.venv/bin/python scripts/a3_spend.py
```
Expected: one line per store (pilot and campaign), and the metered total.

- [ ] **Step 6: Ask the author for the billed figures**

Ask the author to read the OpenAI and Anthropic usage pages for the dates the pilot and campaign ran, and to give the two totals and the date read, in chat. Then:
```bash
.venv/bin/python scripts/a3_spend.py --billed openai=<usd> anthropic=<usd> --read <YYYY-MM-DD>
```
Expected: the spend table and, if the gap exceeds 5%, a line saying the record must explain it.

- [ ] **Step 7: Write the record**

Create `docs/spend-a3.md` with this structure, every figure from the script's output:
```markdown
# Spend record: artifact 3's paid runs

**Read <date>.** Metered figures come from each response's own usage at the
prices pinned in `toolcall/prices.py`, summed by `scripts/a3_spend.py` over the
committed stores. Billed figures are the providers' usage pages for <dates>,
read by the owner. Amendment §8 requires both.

## What was spent

<the table a3_spend printed>

## Against the estimate

The amendment estimated about $39 (§8, revised in §14); step 2 approved
$<amount>. <one sentence on where the difference came from, by phase>

## Why the totals differ

<only if the gap exceeds 5%: what accounts for it, for example usage-page
rounding or days that include other work on the same account>
```
Append one line to the end of `docs/experiment-a3.md`, below everything else: `Actual spend, read <date>: $<billed> billed, $<metered> metered; see docs/spend-a3.md.`

- [ ] **Step 8: Commit**

```bash
git add toolcall/spend.py scripts/a3_spend.py tests/test_toolcall_spend.py data/a3/spend.json docs/spend-a3.md docs/experiment-a3.md
git commit -m "docs: artifact 3's spend record, metered and billed"
```

---

## Task 7: The analysis

One JSON file holds everything the post reports. It is generated by Task 1's script, committed, and never edited.

**Files:**
- Create (by running): `data/a3/analysis.json`

- [ ] **Step 1: Run it twice and compare**

```bash
.venv/bin/python scripts/a3_analyse.py
cp data/a3/analysis.json build/analysis-check.json
.venv/bin/python scripts/a3_analyse.py
cmp data/a3/analysis.json build/analysis-check.json && echo identical
```
Expected: `[ok] …/data/a3/analysis.json` twice, then `identical`.

- [ ] **Step 2: Read the verdicts**

```bash
.venv/bin/python -c "
import json
a = json.load(open('data/a3/analysis.json'))
for k, h in a['hypotheses'].items():
    print(k, h['verdict'], h.get('reason', ''))
print('best', a['ranked_cells']['best'], 'worst', a['ranked_cells']['worst'])
"
```
Write the verdicts down as they came out. They are published as they are, supported or not; a hypothesis that is not supported is a result, not a defect (the portfolio's pre-registration rule).

- [ ] **Step 3: Commit**

```bash
git add data/a3/analysis.json
git commit -m "data: artifact 3's analysis"
```

---

## Task 8: The published figures

Rendered from the committed analysis, looked at, and tied to it by a test that compares bytes.

**Files:**
- Create (by running): `docs/figures/a3/*.png`
- Test: `tests/test_a3_published_figures.py`

- [ ] **Step 1: Render**

```bash
.venv/bin/python scripts/a3_render_figures.py --analysis data/a3/analysis.json --out docs/figures/a3
```
Expected: four `[ok]` lines, eight files.

- [ ] **Step 2: Look at all eight**

Open each figure and each `-phone.png`. Check, and write in the commit message what you saw: nothing clipped at either width; N in every title; whiskers and intervals drawn; the interaction plot's y axis from 0; the floor line on the identical-retry figure; and, on real data, that no label overlaps a bar. Fix `toolcall/figures.py` and re-render if anything fails (and re-run plan 1's figure tests).

- [ ] **Step 3: Write the test**

Create `tests/test_a3_published_figures.py`:

```python
"""The figures artifact 3's post links are the ones its committed analysis
produces, byte for byte (renders are deterministic: checked on the rehearsal,
plan 3 Task 1). A stale PNG is as broken a claim as a stale number."""

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PUBLISHED = REPO / "docs" / "figures" / "a3"
ANALYSIS = REPO / "data" / "a3" / "analysis.json"
FIGURES = ("taxonomy", "interaction", "flakiness", "identical_retry")


@pytest.fixture(scope="module")
def fresh(tmp_path_factory):
    out = tmp_path_factory.mktemp("a3-figures")
    done = subprocess.run(
        [sys.executable, "scripts/a3_render_figures.py", "--analysis", str(ANALYSIS),
         "--out", str(out)],
        cwd=REPO, capture_output=True, text=True, check=False,
    )
    assert done.returncode == 0, done.stderr
    return out


@pytest.mark.parametrize("name", [f"{f}{s}" for f in FIGURES for s in ("", "-phone")])
def test_the_published_figure_matches_a_fresh_render(fresh, name):
    published = PUBLISHED / f"{name}.png"
    assert published.read_bytes() == (fresh / f"{name}.png").read_bytes(), (
        f"{published} differs from a fresh render of {ANALYSIS}; re-render with "
        "scripts/a3_render_figures.py and look at it before committing"
    )


def test_git_tracks_every_published_figure():
    tracked = subprocess.run(
        ["git", "ls-files", str(PUBLISHED.relative_to(REPO))],
        cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout.split()
    expected = {f"docs/figures/a3/{f}{s}.png" for f in FIGURES for s in ("", "-phone")}
    assert expected <= set(tracked)
```

- [ ] **Step 4: Commit the figures, then run the test**

The git-tracking test needs the files committed:
```bash
git add docs/figures/a3 tests/test_a3_published_figures.py
git commit -m "docs: artifact 3's figures, rendered from the committed analysis and looked at"
.venv/bin/python -m pytest tests/test_a3_published_figures.py -v
```
Expected: 9 passed.

---

## Task 9: The post

The slug was approved with the amendment (§0 item 11, §10): `/experiments/tool-presentation-failure-modes`. The title may be reworded at publication; the slug may not.

**Files:**
- Create: `scripts/a3_numbers.py`, `docs/post-a3.md`
- Test: `tests/test_a3_post.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_a3_post.py`:

```python
"""Artifact 3's post against its data and its own contract.

- The numbers block is exactly what the analysis generates.
- Every figure it links exists beside the post.
- The sections the design requires are present, in order, with related work
  early (August §8, amendment §2).
- Each required explanation has a phrase its argument cannot avoid.
- The permanent slug and the pre-registration link are there."""

import json
import re
from pathlib import Path

import pytest

from toolcall.numbers import block_in, numbers_block

REPO = Path(__file__).resolve().parents[1]
POST = REPO / "docs" / "post-a3.md"
ANALYSIS = REPO / "data" / "a3" / "analysis.json"
FIGURES = ("taxonomy", "interaction", "flakiness", "identical_retry")
SECTIONS = (
    "## The finding",
    "## Which failure moves",
    "## What is already known",
    "## What to change in your agent",
    "## Method",
    "## Results",
    "## Reruns are not where the variance is",
    "## Recovering from a tool error",
    "## What it costs",
    "## Does it hold on other models",
    "## Limits",
    "## Run it on your own agent",
    "## Reproduce it",
    "## Next",
)
REQUIRED = (
    "batch",                    # why temperature 0 is not determinism (August §8)
    "pass rate",                # why a pass rate is the wrong summary
    "different fix",            # why each category points at a different fix
    "LLM judge",                # why a judge would have been a methodological error
    "Guo",                      # the closest prior work on H1 (amendment §2)
    "Noise Floor Audit",        # the closest prior work on H5
    "Gumaan",                   # the closest prior work on H4
    "BFCL",                     # the leaderboard and the public seed
    "canonical schema",         # amendment §4b
    "constrained decoding",     # amendment §4a
    "exploratory",              # every non-registered result is labelled so
)


def _post() -> str:
    return POST.read_text()


def test_the_numbers_block_is_current():
    assert block_in(_post()) == numbers_block(json.loads(ANALYSIS.read_text()))


def test_every_figure_is_linked_and_exists():
    links = set(re.findall(r"\]\((figures/a3/[\w-]+\.png)\)", _post()))
    assert {f"figures/a3/{f}.png" for f in FIGURES} <= links
    for link in links:
        assert (POST.parent / link).is_file(), link


def test_the_required_sections_appear_in_order():
    text = _post()
    positions = [text.find(h + "\n") for h in SECTIONS]
    assert -1 not in positions, [h for h, p in zip(SECTIONS, positions) if p == -1]
    assert positions == sorted(positions)


@pytest.mark.parametrize("phrase", REQUIRED)
def test_each_required_explanation_is_there(phrase):
    assert phrase.lower() in _post().lower()


def test_the_slug_and_the_pre_registration_link():
    text = _post()
    assert "Permanent slug: /experiments/tool-presentation-failure-modes" in text
    assert "experiment-a3.md" in text
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_a3_post.py -v`
Expected: FAIL with `FileNotFoundError` for `docs/post-a3.md`.

- [ ] **Step 3: Write the numbers script**

Create `scripts/a3_numbers.py`:

```python
"""Write, or check, the numbers block in artifact 3's post.

    .venv/bin/python scripts/a3_numbers.py            # rewrite the block
    .venv/bin/python scripts/a3_numbers.py --check    # exit 1 if it is stale
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from toolcall.numbers import block_in, numbers_block, replace_block

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--analysis", default=str(REPO / "data" / "a3" / "analysis.json"))
    ap.add_argument("--post", default=str(REPO / "docs" / "post-a3.md"))
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    block = numbers_block(json.loads(Path(args.analysis).read_text()))
    post = Path(args.post)
    text = post.read_text()
    if args.check:
        if block_in(text) != block:
            print("stale: run scripts/a3_numbers.py", file=sys.stderr)
            return 1
        print("numbers block is current")
        return 0
    post.write_text(replace_block(text, block))
    print(f"[ok] {post}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Write the post**

Use exactly these headings in this order; the test checks them.
```markdown
<!--
Permanent slug: /experiments/tool-presentation-failure-modes
Never changes, per the portfolio contract (artifact 1 spec §3). It names the
question rather than the headline, so the title can still be reworded at
publication without breaking the URL.
-->

# <title: names the engineer-controlled variable, not the models>

**Oleksii Ostapiuk** · PUBLICATION-DATE · `/experiments/tool-presentation-failure-modes`

<lede: what was measured, on which pinned models, on which dates, and that every
number re-derives from committed data with no API call>

Harness, scenarios, raw responses, analysis and figure code:
[github.com/alexostapiuk11/coldstart-recon-worker](https://github.com/alexostapiuk11/coldstart-recon-worker).
The pre-registration, its amendments and the spend record:
[`docs/experiment-a3.md`](experiment-a3.md).

The table below is generated from `data/a3/analysis.json` by
`scripts/a3_numbers.py`, and a test fails if it is edited by hand or left stale.

<!-- a3-numbers:start -->
<!-- a3-numbers:end -->

## The finding

## Which failure moves

![...](figures/a3/taxonomy.png)

## What is already known

## What to change in your agent

## Method

## Results

![...](figures/a3/interaction.png)

## Reruns are not where the variance is

![...](figures/a3/flakiness.png)

## Recovering from a tool error

![...](figures/a3/identical_retry.png)

## What it costs

## Does it hold on other models

## Limits

## Run it on your own agent

## Reproduce it

## Next
```

What each section must contain (August §8, amendment §2, §3 and §4):

- **The finding:** whichever result transfers furthest, by the portfolio's rule: the failure-category breakdown of a presentation effect, or the cost break-even. In systems units and in money, with the assumptions (prices, read date, retry cap). No claim before the interval that licenses it.
- **Which failure moves:** the taxonomy figure, and why each category points at a different fix (required explanation 3). Why a pass rate is the wrong summary for a reliability property (required explanation 2).
- **What is already known:** early, not buried (August §1). BFCL and its V4 format study; τ-bench's pass^k; Guo et al. (2026) as the work H1 replicates, and what this design adds (a balanced factorial, plausible confusables, strictness, the breakdown); the Noise Floor Audit and why H5 is framed against it; Gumaan (2026) and Kraishan (2026) and why the floor rule exists; the vendor guidance that already states some of this as advice without published variance. Cite each with its date.
- **What to change in your agent:** each failure category mapped to its intervention, using the measured effects.
- **Method:** the suite (sources, the band, every candidate with its decision, linked to `docs/experiment-a3.md`); the canonical schema and normalizer v1's rules; the factorial; constrained decoding off, and why (amendment §4a); the pinned snapshots and settings, with temperature disclosed per model; S, N and rho; the cluster bootstrap and Holm; why grading with an LLM judge would have been a methodological error here (required explanation 4).
- **Results:** cell rates by category, the main effects and interactions with intervals, the interaction figure, and each hypothesis's verdict stated in the sentence form the pre-publish check looks for: "H1 is supported." or "H1 is not supported." (or "not testable", with the reason).
- **Reruns are not where the variance is:** why temperature 0 is not determinism, batching and floating-point non-associativity (required explanation 1); the ever-flip fraction per model as a property of those endpoints on those dates; H5's comparison.
- **Recovering from a tool error:** the identical-retry figure, H4's verdict or the floor rule's outcome, recovered and gave-up rates, and the hallucinated-success measure disclosed as a pattern-based proxy.
- **What it costs:** cost per successful call per cell, single attempt and retrying, the gap between the measured retry cost and the geometric formula and why (correlated reruns), and the break-even pairs.
- **Does it hold on other models:** the slice, best minus worst on each model, with Sonnet's no-temperature and thinking settings disclosed. The exploratory constrained-decoding result here, labelled exploratory in those words.
- **Limits:** structurally checkable calls only; enumerable answers only; one suite; synthetic and public scenarios; pinned snapshots on stated dates; 20 tools tests confusability, not catalog size; temperature not settable on Claude; the hallucinated-success proxy; any excluded share above 2%; anything step 2 cut.
- **Run it on your own agent:** the `scripts/a3_diagnose.py` commands from `toolcall/README.md`, the dry run first, prominently.
- **Reproduce it:** from `scripts/a3_analyse.py` onward, which needs no API key.
- **Next:** temperature as a factor, larger catalogs with tool search, real API surfaces with authentication (August §2's sequels).

- [ ] **Step 5: Generate the numbers block**

```bash
.venv/bin/python scripts/a3_numbers.py
```
Expected: `[ok] …/docs/post-a3.md`.

- [ ] **Step 6: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_a3_post.py -v`
Expected: 15 passed.

- [ ] **Step 7: Commit**

```bash
git add scripts/a3_numbers.py docs/post-a3.md tests/test_a3_post.py
git commit -m "docs: artifact 3's post, numbers generated from the analysis"
```

---

## Task 10: Bring your own tools, verified on a tool set not in the suite

August §10: the adoption path is verified by running it against tools the suite does not contain. The synthetic travel suite in `toolcall/stub_suite.py` is not in `toolcall/data/`.

**Files:**

- [ ] **Step 1: Write it out and dry-run it**

```bash
.venv/bin/python -c "from toolcall.stub_suite import write_suite; write_suite('build/a3-byo')"
.venv/bin/python scripts/a3_diagnose.py --tools build/a3-byo/tools --scenarios build/a3-byo/scenarios --dry-run --reps 3
```
Expected: `9 graded calls`, and the six-row table.

- [ ] **Step 2: Ask, then run it for real (paid, about 9 calls, a few cents)**

Ask: **"The bring-your-own check sends 9 calls to gpt-5.4-mini-2026-03-17, estimated under $0.05. May I run it with --approved-usd 0.10?"** With a yes:
```bash
.venv/bin/python scripts/a3_diagnose.py --tools build/a3-byo/tools --scenarios build/a3-byo/scenarios --reps 3 --approved-usd 0.10
```
Expected: the call count and estimate, then the taxonomy table. Copy the table into `docs/dod-a3.md` (Task 11) as the evidence for this item.

---

## Task 11: The pre-publish gate and the definition-of-done record

The portfolio's checklist, as a script that reads the files that will ship (artifact 2's pattern) plus the judgement items no script can check.

**Files:**
- Create: `scripts/a3_prepublish_check.py`, `docs/dod-a3.md`
- Test: `tests/test_a3_prepublish_check.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_a3_prepublish_check.py`:

```python
"""scripts/a3_prepublish_check.py refuses the post while anything is unfinished.

Tested on doctored copies of the real files, so each refusal is shown to fire
on exactly its own cause; and on the real files, which must pass before the
post is published (plan 3 Task 11)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from a3_prepublish_check import problems

from toolcall.numbers import numbers_block

REPO = Path(__file__).resolve().parents[1]
ANALYSIS = json.loads((REPO / "data" / "a3" / "analysis.json").read_text())
SPEND_DOC = (REPO / "docs" / "spend-a3.md").read_text()


def _good_post(a=ANALYSIS) -> str:
    verdicts = " ".join(f"{k} is {h['verdict']}." for k, h in a["hypotheses"].items())
    return f"# Post\n\n{numbers_block(a)}\n\n{verdicts} One exploratory result.\n"


def test_a_finished_post_passes():
    assert problems(_good_post(), ANALYSIS, SPEND_DOC) == []


def test_placeholders_outside_comments_are_refused_and_inside_are_not():
    assert problems(_good_post() + "\nPUBLICATION-DATE\n", ANALYSIS, SPEND_DOC)
    assert problems(_good_post() + "\n<!-- PUBLICATION-DATE -->\n", ANALYSIS, SPEND_DOC) == []


def test_a_null_spend_is_refused():
    a = {**ANALYSIS, "spend": None}
    assert any("spend is null" in p for p in problems(_good_post(a), a))


def test_an_unexplained_spend_gap_is_refused():
    a = {**ANALYSIS, "spend": {**ANALYSIS["spend"], "needs_explanation": True, "gap": 0.2}}
    assert any("differ by" in p for p in problems(_good_post(a), a, spend_doc=""))
    assert problems(_good_post(a), a, spend_doc="## Why the totals differ\n...") == []


def test_a_stale_numbers_block_is_refused():
    stale = _good_post().replace("95% interval", "95% CI", 1)
    assert any("stale" in p for p in problems(stale, ANALYSIS, SPEND_DOC))


def test_an_unstated_verdict_is_refused():
    post = _good_post().replace("H3 is", "H3 was maybe")
    assert any("H3" in p for p in problems(post, ANALYSIS, SPEND_DOC))
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_a3_prepublish_check.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'a3_prepublish_check'`.

- [ ] **Step 3: Write the check**

Create `scripts/a3_prepublish_check.py`:

```python
"""Refuse to call artifact 3's post publishable while anything is unfinished.

    python scripts/a3_prepublish_check.py [--post docs/post-a3.md] [--analysis data/a3/analysis.json]

Prints each problem with what it would cost the published post and exits 1, or
prints "ok" and exits 0. It refuses, as artifact 2's check does:

- `PUBLICATION-DATE` or `SPEND-PENDING` in the post outside HTML comments;
- `spend` null in the analysis, or a billed-versus-metered gap above 5% that
  docs/spend-a3.md does not explain;

and, for artifact 3:

- a numbers block that differs from a fresh generation;
- a hypothesis whose verdict the post does not state in its own words;
- the word "exploratory" missing from the post while the analysis carries an
  exploratory result.
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from toolcall.numbers import block_in, numbers_block

REPO = Path(__file__).resolve().parents[1]
POST = REPO / "docs" / "post-a3.md"
ANALYSIS = REPO / "data" / "a3" / "analysis.json"
SPEND_DOC = REPO / "docs" / "spend-a3.md"
PLACEHOLDERS = {
    "PUBLICATION-DATE": "the byline would publish a placeholder; set the publication date",
    "SPEND-PENDING": "the cost section would publish a note to the owner; record the spend",
}
COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def problems(post_text: str, analysis: dict, spend_doc: str = "") -> list[str]:
    body = COMMENT.sub("", post_text)
    found = [f"{token} is still in the post: {why}"
             for token, why in PLACEHOLDERS.items() if token in body]
    spend = analysis.get("spend")
    if spend is None:
        found.append("spend is null in the analysis: run scripts/a3_spend.py with the billed "
                     "figures, then re-run the analysis")
    elif spend.get("needs_explanation") and "Why the totals differ" not in spend_doc:
        found.append(f"billed and metered spend differ by {spend['gap']:+.1%} and "
                     "docs/spend-a3.md has no 'Why the totals differ' section")
    try:
        if block_in(post_text) != numbers_block(analysis):
            found.append("the numbers block is stale: run scripts/a3_numbers.py")
    except ValueError:
        found.append("the post has no numbers block")
    for key, h in analysis["hypotheses"].items():
        if f"{key} is {h['verdict']}" not in body and f"{key} was {h['verdict']}" not in body:
            found.append(f"the post never states '{key} is {h['verdict']}' in its prose")
    if analysis.get("exploratory_constrained") and "exploratory" not in body.lower():
        found.append("an exploratory result is reported without the word 'exploratory'")
    return found


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--post", type=Path, default=POST)
    ap.add_argument("--analysis", type=Path, default=ANALYSIS)
    ap.add_argument("--spend-doc", type=Path, default=SPEND_DOC)
    args = ap.parse_args(argv)
    spend_doc = args.spend_doc.read_text() if args.spend_doc.exists() else ""
    found = problems(args.post.read_text(), json.loads(args.analysis.read_text()), spend_doc)
    if found:
        print(f"refused: {args.post} is not ready to publish", file=sys.stderr)
        for p in found:
            print(f"- {p}", file=sys.stderr)
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_a3_prepublish_check.py -v`
Expected: 6 passed.

- [ ] **Step 5: Run it on the real post**

```bash
.venv/bin/python scripts/a3_prepublish_check.py
```
Expected now: refused, listing `PUBLICATION-DATE` (set at publication, Task 12) and nothing else. Fix every other problem it lists.

- [ ] **Step 6: The non-negotiable item**

Read the post end to end for one thing only: is every number, diagram and claim derived from this repository's experiment and independent reasoning, with nothing traceable to the author's employer's internal material, designs, tool schemas or domains? Then read every scenario's user message once more for anything resembling insurance or claims workflows.

- [ ] **Step 7: The judgement items**

- [ ] No claim appears before the interval that licenses it.
- [ ] The finding is in systems units and money, with the assumptions stated.
- [ ] All four required explanations are argued, not just mentioned.
- [ ] Related work is early, names Guo et al., the Noise Floor Audit and Gumaan, and says plainly what is new.
- [ ] Every result not in H1-H5 says "exploratory".
- [ ] Temperature is disclosed per model; Sonnet's thinking setting is disclosed.
- [ ] Every Limits item from Task 9 is there.

- [ ] **Step 8: Write the record**

Create `docs/dod-a3.md` from this skeleton, every status `met`, `UNMET` or `OWNER`, with evidence:
```markdown
# Artifact 3: definition-of-done check

**Checked:** <date>, at `<commit>`, for plan 3 Task 11. The items are amendment
§12's additions and every item of August §10 they leave standing. Each met item
names the file or commit that meets it. An item marked **UNMET** or **OWNER**
stops publication until the owner acts or decides.

Test and lint state when checked: <the full suite's result> and `ruff check .`
<result>.

## Amendment §12

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | Twelve sign-offs recorded; amendment approved | | |
| 2 | Boundary and no-reimplementation tests; harness unchanged | | |
| 3 | `docs/experiment-a3.md` in two dated steps, each before its data | | |
| 4 | Every §3 setting recorded per call, request body kept, model id matched | | |
| 5 | Provider strict mode off in all eight cells; canonical-schema grading | | |
| 6 | Excluded outcomes and multi-call counts per cell | | |
| 7 | H4 not testable if the floor rule fired | | |
| 8 | Cost per successful call from recorded order | | |
| 9 | Confidentiality test passing; every sign-off reviewed by the author | | |
| 10 | `docs/spend-a3.md` with the owner's console confirmation | | |
| 11 | `scripts/a3_prepublish_check.py` prints `ok` | | |
| 12 | Published after artifacts 2 and 4 | | |

## August §10 items that stand

| Item | Status | Evidence |
|---|---|---|
| Learning-guide self-check before plan 2 | | `docs/learning/progress.md` |
| Suite: seed licensed and attributed, extension authored, all candidates in the repo | | |
| Pilot at baseline; every candidate's rate and decision published | | |
| Dry-run mode end to end with no API call | | |
| Grader smoke-tested on a local model's output (optional, amendment §9) | | |
| Grader verified on hand-labelled cases, all categories and boundaries | | `tests/test_toolcall_grader.py` |
| Full factorial at or above the floor | | |
| Recovery across both formats | | |
| Cross-model slice on best and worst | | |
| Bootstrap clustered on scenario; Wilson only within a scenario | | |
| Four figures rendered and looked at | | |
| Four required explanations and the related-work section | | `tests/test_a3_post.py` |
| Bring-your-own path verified on tools not in the suite | | Task 10's table, below |
| Post at the permanent slug; repo with scenarios, harness, fixtures, raw results, analysis, figure code | | |
| Headline in systems units and money, assumptions published | | |
| Pre-publish boundary gate | | Task 11's commit |
```

- [ ] **Step 9: Commit**

```bash
git add scripts/a3_prepublish_check.py tests/test_a3_prepublish_check.py docs/dod-a3.md
git commit -m "docs: artifact 3 pre-publish gate and definition-of-done record"
```

---

## Task 12: Full verification and publication

Publication waits for artifacts 2 and 4 (amendment §1).

**Files:**

- [ ] **Step 1: Confirm the order**

```bash
.venv/bin/python scripts/a2_prepublish_check.py
```
Expected: `ok`, and artifact 4's post published. If not, stop here; everything else is done.

- [ ] **Step 2: Set the date and check**

Replace `PUBLICATION-DATE` with the date it goes live, then:
```bash
.venv/bin/python scripts/a3_numbers.py --check
.venv/bin/python scripts/a3_prepublish_check.py
```
Expected: `numbers block is current` and `ok`.

- [ ] **Step 3: Everything, fresh**

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
./scripts/parity_check.sh
```
Expected: every test passes, `All checks passed!`, and `PARITY OK`.

- [ ] **Step 4: Final visual check**

Open `docs/post-a3.md` rendered, at desktop width and at 375 px. Confirm all four figures load from `docs/figures/a3/`, the numbers table renders, and nothing overflows on the phone. This catches the broken-image failure artifact 1's gate found once.

- [ ] **Step 5: Tag and publish**

```bash
git commit -am "docs: artifact 3's post, dated for publication"
git tag -a artifact-3-published -m "Data, code and figures as published for artifact 3"
git push origin artifact-3-published
```
Publish at `/experiments/tool-presentation-failure-modes`, linking the repository. Corrections after this point are dated notes appended to the post, never edits (the portfolio contract).

---

## Self-review notes

**Amendment §12 and August §10 coverage:**

| Item | Where |
|---|---|
| Pre-registration in two steps before the data | Plan 2; this plan's prerequisites check it |
| Full factorial, recovery, slice, exploratory | Tasks 2-5 |
| Spend record, metered and billed, gap explained | Task 6, enforced by Task 11's check |
| Analysis clustered on scenario, Holm, floor rule | Task 7 (plan 1's code) |
| Four figures rendered and looked at; byte-tied to the analysis | Task 8 |
| Post structure, required explanations, related work early, slug | Task 9, `tests/test_a3_post.py` |
| Hypothesis verdicts stated in prose | Task 11's check |
| Bring-your-own path on tools not in the suite | Task 10 |
| Pre-publish boundary gate | Task 11 |
| Published after artifacts 2 and 4 | Task 12 Step 1 |

**What this plan asks the author:** an approval before each paid phase (Tasks 2-5, 10), the billed figures (Task 6), the non-negotiable read (Task 11), and the publication date.

**Placeholders:** `<…>` fields are values a preceding step prints, the author's approved amounts, or the post's own prose, whose requirements are listed. No design decision is left open.

**Replacement and removal:** none.
