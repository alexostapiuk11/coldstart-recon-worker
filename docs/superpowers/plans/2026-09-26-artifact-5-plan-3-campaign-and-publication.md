# Artifact 5 Plan 3 — Measurement Campaign and Publication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pin the measurement endpoint, rehearse the paid path without a GPU, prime the compile caches, run the equivalence gate and then the campaign, and publish the analysis, four figures and post, every number re-derivable from committed data.

**Architecture:** The same image and library code as plan 2. `scripts/a5_run.py` drives the harness campaign loop through `multilora.campaign.run`, with a preflight against `multilora/pins.py` before any spend. It refuses to start the campaign until the gate passes. `--stub` runs exactly the same path against the stub worker. Analysis writes one JSON file; the figures and the post's numbers block are generated from it, and tests fail if either drifts.

**Tech Stack:** Python 3.13, pytest, the RunPod serverless API through `harness.runpod`, matplotlib.

**Spec:** [the approved amendment](../specs/2026-09-26-multi-lora-serving-harness-amendment.md), §4 (protocol), §7 (superseded August text) and §8 (definition of done), with the August design's §10 post structure and required explanations.

**Plan 3 of 3.** [Plan 1](2026-09-26-artifact-5-plan-1-gpu-free-core.md) built the library code; [plan 2](2026-09-26-artifact-5-plan-2-recon-and-preregistration.md) built the image, ran reconnaissance and committed the pre-registration.

**This plan spends most of artifact 5's budget:** the amount `scripts/a5_budget.py` printed in plan 2, about $15–25 by the amendment's estimate. Every paid step says so before it runs.

**How this plan was checked:** every script and test below was run on 2026-09-26 in a copy of the repository. The full paid path ran end to end on the stub: priming, the gate, the campaign-before-gate refusal, the campaign, a top-up, per-condition counts, the analysis, the four figures and the post's numbers block. The analysis and the figures were each generated twice and compared byte-identical. The two publication tests passed against that rehearsal output. The git-tracking check could not run there, because the copy had no git history. The paid steps themselves have not been run.

---

## Prerequisites — do not start before these are true

- [ ] **Plan 2 is complete.** `docs/experiment-a5.md` and `multilora/prereg_values.py` are committed, and `tests/test_multilora_prereg_values.py` passes.
- [ ] **Nothing measured has run since the pre-registration commit.** Run `git log --oneline -1 -- docs/experiment-a5.md` and confirm no `data/a5/` file exists yet.
- [ ] **Artifact 4's results file is needed before Task 6, not before measurement.** It is `data/a4/cost_per_tenant.json`, produced by artifact 4's plan 3, in the format agreed on 2026-09-26. Measurement may start without it.
- [ ] **`git status --porcelain` is empty.**

---

## File structure

```
multilora/pins.py          CREATE: the measurement endpoint's pin set (generated)
scripts/
  a5_pins.py               CREATE: print pins.py from the live endpoint
  a5_prime.py              CREATE: two starts per sweep point; the second must be warm
  a5_run.py                CREATE: gate, campaign, or top-up; --stub for rehearsal
  a5_counts.py             CREATE: per-condition counts against the bootstrap floor
  a5_analyse.py            CREATE: data/a5/analysis.json
  a5_numbers.py            CREATE: write or check the post's numbers block
tests/
  test_multilora_pins.py        CREATE
  test_a5_published_figures.py  CREATE: published PNGs match a fresh render
  test_a5_post.py               CREATE: the post against its data and its contract
data/a5/                   priming, gate, campaign and top-up stores; analysis.json
docs/figures/a5/           the four figures and their phone copies, tracked
docs/post-a5.md            the post
```

---

## Task 1: The measurement endpoint and its pins

**Files:**
- Create: `scripts/a5_pins.py`, `multilora/pins.py`, `tests/test_multilora_pins.py`

- [ ] **Step 1: Create the measurement template**

In the RunPod console, duplicate plan 2's reconnaissance template and change one field:

- **Start command:** `python3 -u /opt/a5_handler.py`.

Everything else stays identical: the image digest, the environment, the container disk and the network volume. A separate template is required, not an edit of the reconnaissance one, because the template ID is pinned: editing a pinned template in place is the drift the pins exist to catch.

- [ ] **Step 2: Point the endpoint at it**

Use the reconnaissance endpoint or create a new one, with these settings:

- **GPU:** the pre-registered GPU type.
- **Workers:** `workersMin` 0, `workersMax` 1.
- **FlashBoot:** off.
- **Execution timeout:** 1800 s.

Update `RUNPOD_ENDPOINT_ID` in `.env` if the endpoint changed, then load it with `set -a; . ./.env; set +a`.

- [ ] **Step 3: Write the failing test**

Create `tests/test_multilora_pins.py`:

```python
"""The measurement endpoint's pin set: artifact 1's five fields, with the
platform's own cache off and no warm worker kept, and the GPU the
pre-registration names. Written by scripts/a5_pins.py from the live endpoint."""

from pathlib import Path

from multilora.pins import PINNED

from multilora.cli import PIN_KEYS

REPO = Path(__file__).resolve().parents[1]


def test_the_pin_set_is_the_five_fields_with_the_platform_cache_off():
    assert sorted(PINNED) == sorted(PIN_KEYS)
    assert PINNED["flashboot"] is False
    assert PINNED["workersMin"] == 0


def test_the_pinned_gpu_is_the_one_the_preregistration_names():
    doc = (REPO / "docs" / "experiment-a5.md").read_text()
    assert all(gpu in doc for gpu in PINNED["gpuTypeIds"])
```

Run: `.venv/bin/python -m pytest tests/test_multilora_pins.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'multilora.pins'`.

- [ ] **Step 4: Create the pins script and generate the pins**

Create `scripts/a5_pins.py`:

```python
"""Print multilora/pins.py for the live endpoint.

    set -a; . ./.env; set +a
    .venv/bin/python scripts/a5_pins.py > multilora/pins.py

Refuses an endpoint with FlashBoot on or a warm worker kept (multilora.cli).
"""

import pprint
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.runpod.preflight import fetch_endpoint

from multilora.cli import pins_from_endpoint, require_credentials

TEMPLATE = '''"""Artifact 5's endpoint, pinned. Any change ends the experiment rather than
continuing across it (docs/experiment-a5.md). Generated by scripts/a5_pins.py
from endpoint {endpoint_id}."""

PINNED = {pins}
'''


def main() -> int:
    key, endpoint_id = require_credentials()
    pins = pins_from_endpoint(fetch_endpoint(endpoint_id, key))
    print(TEMPLATE.format(endpoint_id=endpoint_id, pins=pprint.pformat(pins, width=90)), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

```bash
.venv/bin/python scripts/a5_pins.py > multilora/pins.py
```

It refuses an endpoint with FlashBoot on or `workersMin` above 0. Fix the endpoint, not the script.

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_multilora_pins.py -v`
Expected: 2 passed. A failure on the GPU means the endpoint's GPU is not the pre-registered one. That is a boundary violation: fix the endpoint.

- [ ] **Step 6: Commit**

```bash
git add scripts/a5_pins.py multilora/pins.py tests/test_multilora_pins.py
git commit -m "feat: artifact 5's measurement endpoint, pinned"
```

---

## Task 2: Rehearse the whole paid path without a GPU

Everything in Tasks 3–6 runs here first, against the stub, into `build/a5-rehearsal/`, which is gitignored. A defect found here costs nothing.

**Files:**
- Create: `scripts/a5_prime.py`, `scripts/a5_run.py`, `scripts/a5_counts.py`, `scripts/a5_analyse.py`

- [ ] **Step 1: Create the four scripts**

Create `scripts/a5_prime.py`:

```python
"""Prime artifact 5's compile caches: two untimed starts per sweep point
(amendment §3d). Runs once, before the campaign, and is never data.

    set -a; . ./.env; set +a
    .venv/bin/python scripts/a5_prime.py            # the live endpoint
    .venv/bin/python scripts/a5_prime.py --stub     # a GPU-free rehearsal

Writes data/a5/priming.jsonl and exits non-zero unless every sweep point's
second start read warm.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.store import JsonlStore
from multilora.campaign import priming_payloads, priming_verdict
from multilora.cli import submitter_for
from multilora.prereg_values import PREREG
from multilora.records import InstanceRecord, build_record

DATA = Path(__file__).resolve().parents[1] / "data" / "a5"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stub", action="store_true")
    ap.add_argument("--store-dir")
    args = ap.parse_args()
    store_dir = Path(args.store_dir or (DATA.parent.parent / "build" / "a5-rehearsal" if args.stub else DATA))
    store = JsonlStore(store_dir / "priming.jsonl", InstanceRecord)
    if store.read_all():
        raise SystemExit(f"{store.path} already holds priming runs; priming runs once")
    submitter = submitter_for(stub=args.stub)
    for scheduled, payload in priming_payloads(PREREG):
        record = build_record(scheduled, payload["run_id"], submitter.submit_payload(payload))
        store.append(record)
        print(f"[{record.condition} start {record.block_index}] {record.outcome} "
              f"{record.engine.get('compile_state')}", flush=True)
    verdict = priming_verdict(store.read_all())
    print(json.dumps(verdict, indent=1))
    return 0 if all(v["ok"] for v in verdict.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

Create `scripts/a5_run.py`:

```python
"""Run artifact 5's gate or campaign against the live endpoint.

    set -a; . ./.env; set +a
    .venv/bin/python scripts/a5_run.py --which gate
    .venv/bin/python scripts/a5_run.py --which campaign            # refuses unless the gate passed
    .venv/bin/python scripts/a5_run.py --which campaign --resume
    .venv/bin/python scripts/a5_run.py --which topup --conditions sweep-N64 --blocks 3
    .venv/bin/python scripts/a5_run.py --which gate --stub         # GPU-free rehearsal

Refuses to spend unless the endpoint matches multilora/pins.py. Stores go to
data/a5/<which>.jsonl, or build/a5-rehearsal/ with --stub.
"""

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.store import JsonlStore
from multilora.analysis import gate_verdict
from multilora.campaign import run
from multilora.cli import guard_against_silent_restart, submitter_for
from multilora.conditions import campaign_schedule, gate_schedule, topup_schedule
from multilora.prereg_values import PREREG
from multilora.records import InstanceRecord

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", choices=("gate", "campaign", "topup"), required=True)
    ap.add_argument("--conditions", nargs="*", default=[], help="topup only")
    ap.add_argument("--blocks", type=int, default=0, help="topup only")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--force-restart", action="store_true")
    ap.add_argument("--stub", action="store_true")
    ap.add_argument("--store-dir")
    args = ap.parse_args()
    store_dir = Path(args.store_dir or (REPO / "build" / "a5-rehearsal" if args.stub else REPO / "data" / "a5"))
    store = JsonlStore(store_dir / f"{args.which}.jsonl", InstanceRecord)
    guard_against_silent_restart(
        len(store.read_all()), store.path, resume=args.resume, force=args.force_restart
    )
    if args.which in ("campaign", "topup"):
        verdict = gate_verdict(JsonlStore(store_dir / "gate.jsonl", InstanceRecord).read_all(), PREREG)
        if verdict["verdict"] != "pass":
            raise SystemExit(
                f"the equivalence gate reads {verdict['verdict']!r}; the campaign runs only after "
                "it passes (August §8). See the amendment's §4 for what fail and inconclusive mean."
            )
    if args.which == "gate":
        schedule = gate_schedule(PREREG)
    elif args.which == "campaign":
        schedule = campaign_schedule(PREREG)
    else:
        schedule = topup_schedule(PREREG, args.conditions, args.blocks)
    tally = Counter()
    started = time.monotonic()

    def progress(record):
        tally[record.outcome] += 1
        state = record.engine.get("compile_state", "-")
        print(f"[{sum(tally.values()):>4}/{len(schedule)}] run_index={record.run_index:<4} "
              f"{record.condition:<11} {record.outcome:<6} {state:<7} "
              f"{record.failure_class or ''} elapsed={(time.monotonic() - started) / 60:.1f}m",
              flush=True)

    run(schedule, submitter_for(stub=args.stub), store, PREREG, resume=args.resume, on_run=progress)
    print(f"[done] {dict(tally)} store={store.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Create `scripts/a5_counts.py`:

```python
"""Per-condition instance counts, checked before analysis (amendment §4).

    .venv/bin/python scripts/a5_counts.py
    .venv/bin/python scripts/a5_counts.py --store-dir build/a5-rehearsal

Exits 1 and names the conditions below the bootstrap floor of 20 publishable
instances; those are topped up with `scripts/a5_run.py --which topup`.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.store import JsonlStore
from multilora.estimands import publishable_counts
from multilora.prereg_values import PREREG
from multilora.records import InstanceRecord

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store-dir", default=str(REPO / "data" / "a5"))
    args = ap.parse_args()
    d = Path(args.store_dir)
    records = []
    for name in ("gate", "campaign", "topup"):
        records += JsonlStore(d / f"{name}.jsonl", InstanceRecord).read_all()
    counts = publishable_counts(records, PREREG)
    for condition, c in sorted(counts.items()):
        mark = "ok " if c["meets_floor"] else "LOW"
        print(f"[{mark}] {condition:<11} publishable={c['publishable']:>3} "
              f"discarded={c['discarded']:>3} failed={c['failed']:>3}")
    low = [k for k, c in counts.items() if not c["meets_floor"]]
    if low:
        print(f"below the floor: {' '.join(sorted(low))}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Create `scripts/a5_analyse.py`:

```python
"""Assemble artifact 5's analysis from the stores.

    .venv/bin/python scripts/a5_analyse.py --require-a4     # for publication
    .venv/bin/python scripts/a5_analyse.py --store-dir build/a5-rehearsal --out build/a5-rehearsal/analysis.json

Writes data/a5/analysis.json by default. Deterministic: fixed bootstrap
iterations and seed, sorted keys, so a re-run on the same stores is byte-identical.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.store import JsonlStore
from multilora.analysis import analyse
from multilora.prereg_values import PREREG
from multilora.records import InstanceRecord

REPO = Path(__file__).resolve().parents[1]
ITERATIONS = 10000
SEED = 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store-dir", default=str(REPO / "data" / "a5"))
    ap.add_argument("--a4", default=str(REPO / "data" / "a4" / "cost_per_tenant.json"))
    ap.add_argument("--require-a4", action="store_true")
    ap.add_argument("--out")
    args = ap.parse_args()
    store_dir = Path(args.store_dir)
    a4_path = Path(args.a4)
    if args.require_a4 and not a4_path.exists():
        raise SystemExit(f"{a4_path} does not exist; artifact 4's results are required to publish")
    a4 = json.loads(a4_path.read_text()) if a4_path.exists() else None
    campaign = JsonlStore(store_dir / "campaign.jsonl", InstanceRecord).read_all()
    topup = JsonlStore(store_dir / "topup.jsonl", InstanceRecord).read_all()
    if topup:
        print(f"[note] including {len(topup)} top-up instances; the post must disclose them")
    result = analyse(
        campaign + topup,
        JsonlStore(store_dir / "gate.jsonl", InstanceRecord).read_all(),
        PREREG, a4=a4, iterations=ITERATIONS, seed=SEED,
    )
    out = Path(args.out or store_dir / "analysis.json")
    result["topup_instances"] = len(topup)
    out.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    print(f"[ok] {out}: gate {result['gate']['verdict']}, "
          f"tenants {result['tenants'].get('tenants')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Rehearse, in order**

```bash
rm -rf build/a5-rehearsal
.venv/bin/python scripts/a5_prime.py --stub
.venv/bin/python scripts/a5_run.py --which campaign --stub
.venv/bin/python scripts/a5_run.py --which gate --stub
.venv/bin/python scripts/a5_run.py --which gate --stub
.venv/bin/python scripts/a5_run.py --which campaign --stub
.venv/bin/python scripts/a5_counts.py --store-dir build/a5-rehearsal
.venv/bin/python scripts/a5_analyse.py --store-dir build/a5-rehearsal
.venv/bin/python scripts/a5_render_figures.py --analysis build/a5-rehearsal/analysis.json --out build/a5-rehearsal/figures
```

Expected, line by line:

1. The priming verdict prints `"ok": true` for every sweep point, and the exit code is 0.
2. `the equivalence gate reads 'insufficient'; the campaign runs only after it passes`, and nothing runs.
3. `[done] {'ok': 24}` for the gate.
4. `refusing to start: 24 record(s) already exist`, which is the silent-restart guard.
5. `[done] {'ok': N}`, where N is 24 × the number of campaign conditions.
6. Every condition marked `[ok ]`, and exit code 0.
7. `[ok] …analysis.json: gate pass, tenants …`.
8. Three figures rendered, and `[skip] cost_per_tenant` because the rehearsal has no artifact 4 file.

Any other output is a defect to fix before spending.

- [ ] **Step 3: Commit the scripts**

```bash
git add scripts/a5_prime.py scripts/a5_run.py scripts/a5_counts.py scripts/a5_analyse.py
git commit -m "feat: artifact 5's paid-path scripts, rehearsed on the stub"
```

---

## Task 3: Prime the compile caches (paid)

**Paid:** two engine starts per sweep point, 14 at the default sweep, with no timed load.

- [ ] **Step 1: Prime**

```bash
.venv/bin/python scripts/a5_prime.py
```

Expected: a preflight line, one line per start, then the verdict with `"ok": true` for every sweep point, and exit code 0.

- [ ] **Step 2: If any point is not ok, stop**

A second start that read cold means the cache is not persisting on the volume for that `max_loras`. Check the instance's `engine.cache_dir` in `data/a5/priming.jsonl` against the first start's. Do not run the gate on unprimed caches: every instance would be excluded as cold.

- [ ] **Step 3: Commit the priming record**

```bash
git add data/a5/priming.jsonl
git commit -m "data: artifact 5 priming runs (not data; evidence the caches were warm)"
```

---

## Task 4: The equivalence gate (paid)

**Paid:** 24 gate instances. It runs first and alone (August §8).

- [ ] **Step 1: Run the gate**

```bash
.venv/bin/python scripts/a5_run.py --which gate
```

If it is interrupted, rerun it with `--resume`. Expected: `[done] {'ok': 24}` or close to it, since failures are recorded rather than retried.

- [ ] **Step 2: Read the verdict**

```bash
.venv/bin/python -c "
import json
from harness.store import JsonlStore
from multilora.analysis import gate_verdict
from multilora.prereg_values import PREREG
from multilora.records import InstanceRecord
v = gate_verdict(JsonlStore('data/a5/gate.jsonl', InstanceRecord).read_all(), PREREG)
print(v['verdict'], v.get('n'), v.get('reason', ''))
"
```

- [ ] **Step 3: Act on it**
  - `pass`: continue to Task 5.
  - `insufficient`: fewer than 20 usable instances. Run `.venv/bin/python scripts/a5_counts.py` to see why; failures and cold compiles both show there. The gate cannot be topped up: `topup_schedule` refuses it by design, because the gate is one fixed comparison. **Stop**, diagnose from the stored records' `failure_class` and `diagnostics`, and ask the author whether to fix the cause and rerun the gate into a fresh store.
  - `fail` or `inconclusive`: **stop.** This is the August fallback: public adapters only, at the count that can be sourced, with a smaller sweep. That is a redesign and needs the author. A failed gate is itself a publishable finding (August §5).

- [ ] **Step 4: Commit the gate record**

```bash
git add data/a5/gate.jsonl
git commit -m "data: artifact 5 equivalence gate"
```

---

## Task 5: The campaign (paid)

**Paid:** 24 instances per campaign condition, most of the budget. Run it in windows; each job packs as many instances as fit in the 1800 s timeout, and the runner resumes.

- [ ] **Step 1: Run**

```bash
.venv/bin/python scripts/a5_run.py --which campaign
```

After any interruption, continue with the same command plus `--resume`, never `--force-restart`. The runner refuses to start unless the gate passed.

- [ ] **Step 2: Watch the failure column**

Each progress line shows the outcome, compile state and failure class. Stop the window if one condition fails repeatedly, the way artifact 1's disk-exhaustion defect presented: a repeating failure concentrated on one arm biases the comparison through survivorship. Diagnose from `diagnostics.log_lines` in the stored record before resuming.

- [ ] **Step 3: Check the counts**

Run: `.venv/bin/python scripts/a5_counts.py`
Expected: every condition `[ok ]` and exit code 0.

- [ ] **Step 4: Top up any condition below the floor, once**

For each condition marked `LOW`, compute the missing instances as 20 minus its publishable count. Then run:

```bash
.venv/bin/python scripts/a5_run.py --which topup --conditions <LOW conditions> --blocks <largest shortfall>
.venv/bin/python scripts/a5_counts.py
```

Expected: every condition `[ok ]`. Top-ups go to `data/a5/topup.jsonl`, their own store, on their own seed stream, and the post must disclose them; `tests/test_a5_post.py` checks that. If a condition is still low after one top-up, stop and ask the author.

- [ ] **Step 5: Commit the campaign record**

```bash
git add data/a5/campaign.jsonl data/a5/topup.jsonl
git commit -m "data: artifact 5 campaign"
```

If no top-up ran, drop `data/a5/topup.jsonl` from that command.

- [ ] **Step 6: Record the spend**

Read the actual charge for the gate, the priming and the campaign off the RunPod console. Add it to `docs/experiment-a5.md` as a dated note at the end: an appended note, not an edit to the pre-registered text. Artifact 1's campaign never recorded an invoice; this one does.

```bash
git add docs/experiment-a5.md
git commit -m "docs: artifact 5's actual spend, appended"
```

---

## Task 6: The analysis

- [ ] **Step 1: Confirm artifact 4's results exist**

Run: `ls data/a4/cost_per_tenant.json`
If it is absent, stop here. The three-way table is the strongest number in the portfolio, and August §12 says artifact 5 does not publish without it.

- [ ] **Step 2: Analyse**

```bash
.venv/bin/python scripts/a5_analyse.py --require-a4
```

Expected: `[ok] …/data/a5/analysis.json: gate pass, tenants <n>`, plus a top-up note if any ran.

- [ ] **Step 3: Confirm it re-derives**

```bash
.venv/bin/python scripts/a5_analyse.py --require-a4 --out /tmp/a5-check.json
cmp data/a5/analysis.json /tmp/a5-check.json && echo identical
```

Expected: `identical`.

- [ ] **Step 4: Commit**

```bash
git add data/a5/analysis.json
git commit -m "data: artifact 5 analysis"
```

---

## Task 7: The published figures

Visual work. `superpowers:verifying-visual-output` applies: the test proves the published PNGs are the ones the data produces; Step 3 is the eyes-on check at desktop and phone width.

**Files:**
- Create: `docs/figures/a5/*.png`, `tests/test_a5_published_figures.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_a5_published_figures.py`:

```python
"""The figures artifact 5's post links are the ones its committed analysis
produces. Same reasoning as tests/test_published_figures.py for artifact 1:
a stale PNG is as broken a claim as a stale number, and nothing else in the
suite can see it. Renders are deterministic (verified 2026-09-26: two renders
of one analysis are byte-identical), so the comparison is exact."""

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PUBLISHED = REPO / "docs" / "figures" / "a5"
ANALYSIS = REPO / "data" / "a5" / "analysis.json"
FIGURES = ("throughput_ttft", "kv_capacity", "equivalence", "cost_per_tenant")


@pytest.fixture(scope="module")
def fresh(tmp_path_factory):
    out = tmp_path_factory.mktemp("a5-figures")
    done = subprocess.run(
        [sys.executable, "scripts/a5_render_figures.py", "--analysis", str(ANALYSIS),
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
        "scripts/a5_render_figures.py and look at it before committing"
    )


def test_git_tracks_every_published_figure():
    tracked = subprocess.run(
        ["git", "ls-files", str(PUBLISHED.relative_to(REPO))],
        cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout.split()
    expected = {f"docs/figures/a5/{f}{s}.png" for f in FIGURES for s in ("", "-phone")}
    assert expected <= set(tracked)
```

Run: `.venv/bin/python -m pytest tests/test_a5_published_figures.py -v`
Expected: FAIL, because `docs/figures/a5/` does not exist yet.

- [ ] **Step 2: Render into the tracked directory**

```bash
.venv/bin/python scripts/a5_render_figures.py --analysis data/a5/analysis.json --out docs/figures/a5
```

Expected: `[ok]` for all four figures and their phone copies. There is no skip this time, because the analysis carries the cost table.

- [ ] **Step 3: Look at every figure**

Open each of the eight files. For the four desktop figures, check each against this list, and fix `multilora/figures.py` and re-render if any item fails:

- **throughput_ttft:** both regimes with error bars, the gap shaded, y from 0, n in the title, and no legend over data. The shape should agree with the numbers block's heterogeneity cost.
- **kv_capacity:** per-instance dots, a median line, y from 0, and the concurrency note inside the axes. The values should agree with the numbers block's KV range.
- **equivalence:** the verdict in the title matches the gate's, the margin band is τ/2, and the legend sits below the panels.
- **cost_per_tenant:** one bar per strategy, the adapter bar hatched, x from 0, and the assumptions note naming the pre-registered rate.

Then open the four `-phone.png` copies, which are 375 px wide. Every label must be readable without zooming.

- [ ] **Step 4: Run the test to verify it passes, then commit**

Run: `.venv/bin/python -m pytest tests/test_a5_published_figures.py -v`
Expected: every figure comparison passes. `test_git_tracks_every_published_figure` passes only after the `git add` below, so run it again after committing.

```bash
git add docs/figures/a5 tests/test_a5_published_figures.py
git commit -m "docs: artifact 5's figures, rendered from the committed analysis and looked at"
.venv/bin/python -m pytest tests/test_a5_published_figures.py -v
```

---

## Task 8: The post

**Files:**
- Create: `scripts/a5_numbers.py`, `docs/post-a5.md`, `tests/test_a5_post.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_a5_post.py`:

```python
"""Artifact 5's post against its data and its own contract.

- The numbers block is exactly what the analysis generates.
- Every figure it links exists, tracked, beside the post.
- The sections the approved design requires are present, in order.
- Top-up instances, if any, are disclosed.
- No mean appears: the tool's summary statistics never reach the post."""

import json
import re
from pathlib import Path

from multilora.numbers import block_in, numbers_block

REPO = Path(__file__).resolve().parents[1]
POST = REPO / "docs" / "post-a5.md"
ANALYSIS = REPO / "data" / "a5" / "analysis.json"
FIGURES = ("throughput_ttft", "kv_capacity", "equivalence", "cost_per_tenant")
SECTIONS = (
    "## Headline",
    "## The main chart",
    "## Registered is not active",
    "## Tenants per GPU, and what one costs",
    "## Synthetic adapters, and how I know they are valid here",
    "## Method",
    "## Adapters versus swapping models",
    "## Memory is a capacity question",
    "## Limits",
    "## Reproduce it",
    "## Next",
)


def _post() -> str:
    return POST.read_text()


def test_the_numbers_block_is_current():
    assert block_in(_post()) == numbers_block(json.loads(ANALYSIS.read_text()))


def test_every_figure_is_linked_and_exists():
    links = set(re.findall(r"\]\((figures/a5/[\w-]+\.png)\)", _post()))
    assert {f"figures/a5/{f}.png" for f in FIGURES} <= links
    for link in links:
        assert (POST.parent / link).is_file(), link


def test_the_required_sections_appear_in_order():
    text = _post()
    positions = [text.find(h + "\n") for h in SECTIONS]
    assert -1 not in positions, [h for h, p in zip(SECTIONS, positions) if p == -1]
    assert positions == sorted(positions)


def test_top_up_instances_are_disclosed():
    if json.loads(ANALYSIS.read_text()).get("topup_instances"):
        assert "top-up" in _post().lower()


def test_no_mean_is_published():
    """`peak-to-average` is a pre-registered parameter's name, not a statistic.
    Little's law, which the memory bound uses, is written as time in system."""
    text = re.sub(r"peak-to-average", "", _post(), flags=re.IGNORECASE)
    assert not re.search(r"\bmean\b|\baverage\b", text, re.IGNORECASE)
```

Run: `.venv/bin/python -m pytest tests/test_a5_post.py -v`
Expected: FAIL with `FileNotFoundError` for `docs/post-a5.md`.

- [ ] **Step 2: Create the numbers script**

```python
"""Write, or check, the numbers block in artifact 5's post.

    .venv/bin/python scripts/a5_numbers.py            # rewrite the block
    .venv/bin/python scripts/a5_numbers.py --check    # exit 1 if it is stale
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from multilora.numbers import block_in, numbers_block, replace_block

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--analysis", default=str(REPO / "data" / "a5" / "analysis.json"))
    ap.add_argument("--post", default=str(REPO / "docs" / "post-a5.md"))
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    block = numbers_block(json.loads(Path(args.analysis).read_text()))
    post = Path(args.post)
    text = post.read_text()
    if args.check:
        if block_in(text) != block:
            print("stale: run scripts/a5_numbers.py", file=sys.stderr)
            return 1
        print("numbers block is current")
        return 0
    post.write_text(replace_block(text, block))
    print(f"[ok] {post}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Ask the author for the permanent slug and title**

A slug never changes once published (the portfolio contract, artifact 1 spec §3). Propose `/experiments/vllm-multi-lora-capacity` and the August working title "How many LoRA adapters actually fit on one GPU". The title may be reworded at publication; the slug may not.

- [ ] **Step 4: Write `docs/post-a5.md`**

Use exactly these section headings, in this order; the test checks them. Content requirements per section come from the August design's §10 and the amendment.

```markdown
<!--
Permanent slug: /experiments/<slug>
Never changes, per the portfolio contract (artifact 1 spec §3).
-->

# <title>

**<author>** · <publication date> · `/experiments/<slug>`

<one-paragraph lede: what was measured, on what, and that every number
re-derives from committed data>

<!-- a5-numbers:start -->
<!-- a5-numbers:end -->

## Headline

## The main chart

![...](figures/a5/throughput_ttft.png)

## Registered is not active

## Tenants per GPU, and what one costs

![...](figures/a5/cost_per_tenant.png)

## Synthetic adapters, and how I know they are valid here

![...](figures/a5/equivalence.png)

## Method

## Adapters versus swapping models

## Memory is a capacity question

![...](figures/a5/kv_capacity.png)

## Limits

## Reproduce it

## Next
```

What each section must contain:

- **Headline:** the knee as tenants per GPU, and the decomposition claim as the amendment reframed it. State it in systems units and in money, with the conversion assumptions: rate, requests per tenant per month, SLO and peak factor. Every claim appears with its interval, or after the interval that licenses it. Artifact 1's gate failed on exactly this ordering once.
- **The main chart:** what the shaded gap is, in words, and what the intervals range over. They range over medians of re-runs, not over the runs themselves. That is the misconception artifact 1's learning record found.
- **Registered is not active:** why a batch spanning many adapters costs more than one sharing an adapter. That is required explanation 2. Include vLLM's slot mechanism, with `max_loras` as both the slot count and the in-batch cap, from amendment §3a, and the registered-slot cost, with the diagnostic's result if it ran.
- **Tenants per GPU, and what one costs:** which of the three bounds binds, and what the knee means for a per-customer fine-tune product (required explanation 4). Then the cost table from the numbers block, with the adapter column labelled a lower bound on tenants.
- **Synthetic adapters, and how I know they are valid here:** why weight values cannot affect serving cost, and what that licenses (required explanation 1). Then the gate: margin, verdict, and the resolution check.
- **Method:** the sweep, the regimes, the subtraction, the per-instance phase order, the exclusion rules, 24 instances per point, and any top-up, disclosed with its count. Include the pinned image, model and revision, and a link to `docs/experiment-a5.md`.
- **Adapters versus swapping models:** artifact 4's reference point, named by regime and s, and the comparison.
- **Memory is a capacity question:** required explanation 3, reframed by amendment §3c. Loading adapters costs KV capacity, but at this request shape memory cannot move latency, and why. Write Little's law as time in system: `tests/test_a5_post.py` refuses the words "mean" and "average".
- **Limits:** one rank, one request shape, one base model and card, a pinned version in a fast-moving area, the all-resident case only (the resident-versus-swapped mode is a sequel), and the gauge as a sample of scheduler state rather than a per-batch count.
- **Reproduce it:** the commands from plan 3, from `scripts/a5_analyse.py` onward, which need no GPU.
- **Next:** the named sequels: rank as a variable, resident versus swapped, and `specialize_active_lora` as a configuration.

- [ ] **Step 5: Generate the numbers block**

```bash
.venv/bin/python scripts/a5_numbers.py
```

Expected: `[ok] …/docs/post-a5.md`.

- [ ] **Step 6: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_a5_post.py -v`
Expected: 5 passed.

- [ ] **Step 7: Commit**

```bash
git add scripts/a5_numbers.py docs/post-a5.md tests/test_a5_post.py
git commit -m "docs: artifact 5's post, numbers generated from the analysis"
```

---

## Task 9: The pre-publish gate

The portfolio's checklist (artifact 1 spec §8), plus the two failures artifact 1's gate caught once. Record each item's result in the commit message.

- [ ] **Step 1: The non-negotiable item**

Confirm that every number, diagram and claim derives from the rented-hardware experiment and independent reasoning, with nothing traceable to employer internal material. Read the post end to end for this alone.

- [ ] **Step 2: The mechanical items**

```bash
.venv/bin/python scripts/a5_numbers.py --check
.venv/bin/python -m pytest tests/test_a5_post.py tests/test_a5_published_figures.py tests/test_multilora_prereg_values.py -v
git ls-files docs/figures/a5 | wc -l
```

Expected: `numbers block is current`, all tests passing, and `8`.

- [ ] **Step 3: The judgement items**
  - [ ] No claim appears before the interval that licenses it.
  - [ ] The headline is in both systems units and money, with the assumptions stated.
  - [ ] All four required explanations are present (Task 8's list).
  - [ ] Every limit in amendment §8 and August §10 appears under Limits.
  - [ ] The registered-slot cost is never called memory, and memory is presented as capacity.
  - [ ] The adapter cost is labelled an upper bound, and tenants a lower bound.
  - [ ] Any top-up and every exclusion count appear in Method.
  - [ ] Artifact 4's reference point is named, not implied.

- [ ] **Step 4: Commit the gate record**

```bash
git commit --allow-empty -m "docs: artifact 5 pre-publish gate passed

Employer boundary: confirmed. Numbers block current; post, figure and
pre-registration tests pass; 8 figures tracked. Judgement items: all checked."
```

---

## Task 10: Full verification and publication

- [ ] **Step 1: Everything, fresh**

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
./scripts/parity_check.sh
```

Expected: all tests pass, `All checks passed!`, and `PARITY OK`. Artifact 1's published numbers are untouched by artifact 5.

- [ ] **Step 2: Final visual checkpoint**

Open `docs/post-a5.md` rendered, in the repository's web view or a Markdown preview, at desktop width and at 375 px. Confirm that all four figures load from `docs/figures/a5/`, that the numbers table renders, and that nothing overflows at phone width. This catches the broken-image failure artifact 1's gate found.

- [ ] **Step 3: Tag the published state**

```bash
git tag -a artifact-5-published -m "Data, code and figures as published for artifact 5"
git push origin artifact-5-published
```

- [ ] **Step 4: Publish at the permanent slug**

Publish at the author's site under the slug from Task 8, linking the repository. Corrections after this point are appended as dated notes, never edited in (the portfolio contract).

---

## Self-review notes

**Amendment §8 coverage:**

| Definition-of-done item | Where it is met |
|---|---|
| Compile cache primed per N; cold instances excluded; every condition at 20 or more | Tasks 3 and 5; the exclusion rule is plan 1 |
| Instances run as §4 describes | Plan 1's instance runner, driven in Tasks 4 and 5 |
| Gauge overhead reported, or declared unbounded | Analysis in Task 6; the post's Method and Limits |
| No `vllm bench serve` summary statistic in the post | `tests/test_a5_post.py`, plus plan 1's analysis only ever reading the raw arrays |
| Registered-slot cost never called memory; memory as capacity | Task 9's judgement items |
| Adapter column labelled a lower bound on tenants | Plan 1's cost table and figure; Task 9 |
| Four figures rendered and inspected | Task 7 |
| Headline in both units | Task 8 and Task 9 |
| Post at a permanent slug | Tasks 8 and 10 |
| Pre-publish boundary gate | Task 9 |

**What the plan asks the author:** the slug and title (Task 8). It also asks after a gate that fails or is inconclusive, after a condition still low after one top-up, and when artifact 4's results are missing.

**Placeholders:** the `<…>` fields in Task 5's top-up command and in Task 8's post skeleton are values produced by earlier steps, or the post's own prose, whose requirements are listed. No design decision is left open.
