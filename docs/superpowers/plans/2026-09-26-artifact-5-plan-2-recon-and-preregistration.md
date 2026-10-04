# Artifact 5 Plan 2 — Worker Image, Reconnaissance and Pre-registration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put artifact 5's handlers in the worker image, answer reconnaissance questions R1–R10 on the pinned engine, compute the budget, and commit the pre-registration before any measurement.

**Architecture:** Two thin handler files in `worker/` call plan 1's `multilora.recon.run_probe` and `multilora.instance.run_instance`. The same image serves reconnaissance and, in plan 3, measurement, so both run on one digest. Reconnaissance captures are saved verbatim under `fixtures/a5/` and never overwritten. The answers are computed from them by `multilora.recon_report`, and the pre-registration is tied to them by tests.

**Tech Stack:** Python 3.13, pytest, the RunPod serverless API through `harness.runpod`, GitHub Actions for the image build.

**Spec:** [the approved amendment](../specs/2026-09-26-multi-lora-serving-harness-amendment.md), §6 (reconnaissance) and §8 (definition of done).

**Plan 2 of 3.** [Plan 1](2026-09-26-artifact-5-plan-1-gpu-free-core.md) built and tested every library module this plan calls. Plan 3 primes, measures and publishes.

**This plan spends money.** Reconnaissance is roughly 12 short GPU jobs, estimated at a few dollars; `scripts/a5_budget.py` computes the real campaign cost from those runs. Every paid step names what it runs before it runs it.

**How this plan was checked:** every script and test below was run on 2026-09-26 in a copy of the repository. The capture and report path was exercised end to end against the instance runner with a fake engine, and the two tests that tie the pre-registration to reconnaissance passed against fake captures. The paid steps themselves, which need the live endpoint, have not been run.

---

## Prerequisites — do not start before these are true

- [ ] **Plan 1 is complete**, with its full suite and the parity gate passing.
- [ ] **The shared harness tooling plan has landed.** Artifact 4 owns it (amendment §0 item 3). Run:

```bash
.venv/bin/python -c "
import inspect
from harness.serve import served
from harness.bench import run_bench
s = inspect.signature(served).parameters
b = inspect.signature(run_bench).parameters
assert {'model', 'args', 'env', 'port', 'health_timeout'} <= set(s), s
assert {'model', 'lora_modules', 'lora_assignment', 'max_concurrency', 'num_prompts',
        'dataset_args', 'ignore_eos', 'seed', 'result_dir'} <= set(b), b
print('shared tooling present with the agreed interface')
"
```

Expected: `shared tooling present with the agreed interface`. If a name differs, change only `multilora/serving.py`: it is the one module that calls these.

- [ ] **Artifact 4 has fixed the base model, its revision, the GPU class and the vLLM image.** Read them from `docs/experiment-a4.md`. They are artifact 5's too (amendment §6 prerequisite 2). Write them down now, because Task 3 needs all four:
  - the model ID, expected `Qwen/Qwen3-4B`;
  - the model revision, a commit hash;
  - the GPU type ID, a 24 GB card;
  - the vLLM base digest in `worker/Dockerfile`'s `ARG VLLM_DIGEST`, which both artifacts share because they build one image.
- [ ] **`git status --porcelain` is empty.**

---

## File structure

```
worker/
  a5_recon_handler.py   CREATE: reconnaissance probes, selected by dockerStartCmd
  a5_handler.py         CREATE: one measured instance per job (used in plan 3)
  Dockerfile            MODIFY: COPY multilora and both handlers
.github/workflows/build-worker.yml   MODIFY: rebuild on multilora/** changes
tests/
  test_harness_boundary.py           MODIFY: multilora is a first-party package
  test_multilora_engine_flags.py     CREATE: flags exist in the pinned engine
  test_multilora_prereg_values.py    CREATE: the pre-registration matches its evidence
scripts/
  a5_find_real_adapters.py   CREATE: R10 search, pinned to commits
  a5_recon_capture.py        CREATE: submit probes, save outcomes verbatim
  a5_recon_report.py         CREATE: R1-R9 from the captures
  a5_budget.py               CREATE: campaign cost and the cut decision
multilora/prereg_values.py   CREATE: PREREG, the values the campaign runs on
fixtures/a5/                 CREATE: captures, candidates, the report
docs/
  recon-a5.md               CREATE: the reconnaissance record
  experiment-a5.md          CREATE: the pre-registration
```

`recon/capture.py` is artifact 1's and stays unchanged. `scripts/a5_recon_capture.py` submits through the harness's `submit_payload` instead, which reuses the retrying transport rather than a third copy of it. That is narrower than the amendment's §5 table, which proposed giving `recon/capture.py` new options; the amendment is updated to match.

---

## Task 1: The handlers and the image

**Files:**
- Create: `worker/a5_recon_handler.py`, `worker/a5_handler.py`
- Modify: `worker/Dockerfile`, `tests/test_harness_boundary.py`, `.github/workflows/build-worker.yml`

- [ ] **Step 1: Declare `multilora` first-party**

In `tests/test_harness_boundary.py`, change the constant to:

```python
FIRST_PARTY = {"coldstart", "harness", "multilora", "worker", "recon"}
```

- [ ] **Step 2: Create the two handlers**

Create `worker/a5_recon_handler.py`:

```python
"""Artifact 5 reconnaissance handler. Captures; publishes nothing.
Selected by overriding the template's dockerStartCmd, as recon_handler.py is."""

import runpod

from multilora.recon import run_probe
from multilora.worker_deps import post_json, post_status, real_deps
from multilora.worker_env import instance_kwargs, volume_env


def handler(job):
    payload = job.get("input") or {}
    if payload.get("probe") == "help":
        return run_probe(payload, deps=None, post_status=None)
    return run_probe(
        payload, deps=real_deps(), post_status=post_status, post_json=post_json,
        env=volume_env(), **instance_kwargs(),
    )


runpod.serverless.start({"handler": handler})
```

Create `worker/a5_handler.py`:

```python
"""Artifact 5 measurement handler: one server instance per job.
Selected by overriding the template's dockerStartCmd."""

import runpod

from multilora.instance import run_instance
from multilora.worker_deps import real_deps
from multilora.worker_env import instance_kwargs, volume_env


def handler(job):
    return run_instance(job.get("input") or {}, deps=real_deps(), env=volume_env(), **instance_kwargs())


runpod.serverless.start({"handler": handler})
```

- [ ] **Step 3: Run the boundary tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_harness_boundary.py -v`
Expected: FAIL in `test_dockerfile_copies_every_first_party_package_the_image_imports` with `worker/Dockerfile does not COPY ['multilora']`.

- [ ] **Step 4: Copy the package and handlers into the image**

In `worker/Dockerfile`, after the line `COPY harness /opt/harness`, add:

```dockerfile
# artifact 5's package: worker/a5_handler.py and worker/a5_recon_handler.py import it.
COPY multilora /opt/multilora
```

After the line `COPY worker/handler.py /opt/handler.py`, add:

```dockerfile
COPY worker/a5_handler.py /opt/a5_handler.py
COPY worker/a5_recon_handler.py /opt/a5_recon_handler.py
```

Leave `CMD` alone. Artifact 5's endpoint selects a handler by overriding the template's start command, the way artifact 1 selects `recon_handler.py`.

- [ ] **Step 5: Run the boundary tests again**

Run: `.venv/bin/python -m pytest tests/test_harness_boundary.py -v`
Expected: FAIL in `test_the_ci_image_build_triggers_on_every_copied_package` with `['multilora'] are COPYed into the worker image but absent from build-worker.yml's paths filter`. The guard is doing its job.

- [ ] **Step 6: Rebuild the image when the package changes**

In `.github/workflows/build-worker.yml`, after the `- "harness/**"` entry under `paths:`, add:

```yaml
      # Artifact 5's package, vendored for worker/a5_handler.py and
      # worker/a5_recon_handler.py -- same reasoning as the two above.
      - "multilora/**"
```

- [ ] **Step 7: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 8: Commit and push, then record the image digest**

```bash
git add worker/a5_recon_handler.py worker/a5_handler.py worker/Dockerfile tests/test_harness_boundary.py .github/workflows/build-worker.yml
git commit -m "feat: artifact 5's handlers in the worker image"
git push
```

Open the `build-worker` run for this commit in GitHub Actions. Its summary prints the image reference as `ghcr.io/<repo>@sha256:<digest>`. Copy that reference: Task 3 pins the template to it, and `docs/experiment-a5.md` records it. **Never use a tag.** Artifact 1 re-pinned twice because a tag moved under it.

---

## Task 2: Find real adapters for the gate (R10)

This runs on the laptop, against the Hugging Face Hub, and costs nothing. It must pass before any GPU time: without enough qualifying adapters, the gate cannot run as designed, and amendment §9 makes that a decision for the author.

**Files:**
- Create: `scripts/a5_find_real_adapters.py`, `fixtures/a5/real_adapter_candidates.json`

- [ ] **Step 1: Create the script**

```python
"""Search the Hugging Face Hub for public LoRA adapters the equivalence gate
can use (R10), and record the choice with its reasons.

    .venv/bin/python scripts/a5_find_real_adapters.py --base Qwen/Qwen3-4B \
        --rank 16 --modules q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj --count 4

Writes fixtures/a5/real_adapter_candidates.json: every candidate seen, the
selected (repo, commit) pairs, and each rejection's reason. Pinned to commits,
so the gate serves exactly these adapters however the repos change later.
"""

import argparse
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from multilora.adapters import select_real_adapters

HUB = "https://huggingface.co"
OUT = Path(__file__).resolve().parents[1] / "fixtures" / "a5" / "real_adapter_candidates.json"


def candidates(base: str, limit: int) -> list[dict]:
    found = []
    for variant in (base, f"{base}-Base", f"{base}-Instruct-2507"):
        r = requests.get(f"{HUB}/api/models", params={
            "filter": f"base_model:adapter:{variant}", "limit": limit}, timeout=30)
        r.raise_for_status()
        for model in r.json():
            info = requests.get(f"{HUB}/api/models/{model['id']}", timeout=30).json()
            sha = info.get("sha")
            cfg = requests.get(f"{HUB}/{model['id']}/resolve/{sha}/adapter_config.json", timeout=30)
            if cfg.status_code != 200:
                continue
            found.append({"id": model["id"], "sha": sha, "base": variant, "config": cfg.json()})
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--rank", type=int, required=True)
    ap.add_argument("--modules", required=True)
    ap.add_argument("--count", type=int, required=True)
    ap.add_argument("--limit", type=int, default=100)
    args = ap.parse_args()
    seen = candidates(args.base, args.limit)
    result = select_real_adapters(
        seen, rank=args.rank, target_modules=args.modules.split(","), count=args.count
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"query": vars(args), "seen": seen, **result}, indent=1, sort_keys=True))
    print(f"{len(seen)} seen, {len(result['selected'])} selected, enough={result['enough']}: {OUT}")
    return 0 if result["enough"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the search**

Use the rank and module set Task 3 will pin. The proposal is rank 16 with all seven projections, which gives the amendment §3c size estimate. G = 4 is the proposed gate size.

```bash
.venv/bin/python scripts/a5_find_real_adapters.py --base Qwen/Qwen3-4B --rank 16 --modules q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj --count 4
```

Expected: `N seen, 4 selected, enough=True` and exit code 0.

- [ ] **Step 3: If fewer than four qualify, stop**

Exit code 1 means `enough=False`. Do not continue. Record the count and the rejection reasons from the JSON in `docs/recon-a5.md` under R10, and ask the author which way to go. The amendment's §9 options are a smaller G, adapters trained on a Qwen3-4B variant, or the August fallback. A smaller G still needs 20 or more instances for the bootstrap; the instance count is unaffected.

- [ ] **Step 4: Commit the evidence**

```bash
git add scripts/a5_find_real_adapters.py fixtures/a5/real_adapter_candidates.json
git commit -m "recon: public adapters that qualify for artifact 5's gate, pinned to commits"
```

---

## Task 3: The reconnaissance endpoint

Manual, in the RunPod console. Follow the structure of artifact 1's endpoint in `recon/README.md`, with these values.

- [ ] **Step 1: Create a template**
  - **Image:** the digest reference from Task 1 Step 8.
  - **Start command:** `python3 -u /opt/a5_recon_handler.py`.
  - **Container disk:** 60 GB. Sixty-four rank-16 synthetic adapters take about 4 GB in `/tmp/a5-adapters`.
  - **Network volume:** attached, mounted at `/runpod-volume`. The handler refuses to run without it.
  - **Environment:**
    - `MODEL_ID`: artifact 4's model.
    - `MODEL_REVISION`: artifact 4's revision.
    - `MAX_MODEL_LEN`: `8192`.
    - `A5_MAX_LORA_RANK`: `16`.
    - `A5_TARGET_MODULES`: `q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj`.
    - `VLLM_TUNED_CONFIG_FOLDER` must **not** be set; the handler refuses if it is.

- [ ] **Step 2: Create an endpoint on that template**
  - **GPU:** artifact 4's GPU type ID.
  - **Workers:** `workersMin` 0, `workersMax` 1.
  - **FlashBoot:** off.
  - **Execution timeout:** 1800 s.

- [ ] **Step 3: Put its credentials in `.env`**

`.env` is gitignored. Set `RUNPOD_API_KEY` and `RUNPOD_ENDPOINT_ID`, then load them:

```bash
set -a; . ./.env; set +a
```

---

## Task 4: Capture

**Files:**
- Create: `scripts/a5_recon_capture.py`, `fixtures/a5/*.json`

- [ ] **Step 1: Create the capture script**

```python
"""Submit artifact 5's reconnaissance probes and save each outcome verbatim.

    set -a; . ./.env; set +a
    .venv/bin/python scripts/a5_recon_capture.py --concurrency 64 \
        --dataset-args "--dataset-name random --random-input-len 14 --random-output-len 16"

Publishes nothing. Writes fixtures/a5/<label>.json and never overwrites one:
a committed capture is evidence, and reconnaissance re-runs get new labels.
"""

import argparse
import json
import shlex
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.runpod.submitter import HttpTransport, RunPodSubmitter
from multilora.cli import require_credentials
from multilora.recon import recon_payloads

OUT = Path(__file__).resolve().parents[1] / "fixtures" / "a5"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--concurrency", type=int, required=True)
    ap.add_argument("--dataset-args", required=True)
    ap.add_argument("--adapter-seed", type=int, default=1)
    ap.add_argument("--real-candidates", help="fixtures/a5/real_adapter_candidates.json")
    ap.add_argument("--only", nargs="*", help="labels to run; default all")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    key, endpoint_id = require_credentials()
    real = []
    if args.real_candidates:
        real = [tuple(x) for x in json.loads(Path(args.real_candidates).read_text())["selected"]]
    payloads = recon_payloads(
        concurrency=args.concurrency, dataset_args=shlex.split(args.dataset_args),
        adapter_seed=args.adapter_seed, real_candidates=real,
    )
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    submitter = RunPodSubmitter(HttpTransport(endpoint_id, key))
    for payload in payloads:
        label = payload["label"]
        if args.only and label not in args.only:
            continue
        path = out / f"{label}.json"
        if path.exists():
            print(f"[skip] {path} exists; captures are never overwritten")
            continue
        outcome = submitter.submit_payload(payload)
        path.write_text(json.dumps(
            {"label": label, "payload": payload, "outcome": asdict(outcome)}, indent=1, sort_keys=True
        ))
        print(f"[{'ok' if outcome.error is None else 'FAILED'}] {path} {outcome.error or ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Capture the help text first**

It needs no engine start and settles R4 and R9 cheaply.

```bash
.venv/bin/python scripts/a5_recon_capture.py --concurrency 64 --dataset-args "--dataset-name random --random-input-len 14 --random-output-len 16" --only help
```

Expected: `[ok] fixtures/a5/help.json`.

- [ ] **Step 3: Capture the LoRA probes**

This is the paid step: 8 engine starts, or 9 with the gate probe. Each start is 1, 16 or 64 synthetic adapters with one spread phase of `max(80, 10 × C)` requests. The dataset arguments here are provisional, because the prompt's exact token count is what this step measures. They only have to be valid.

```bash
.venv/bin/python scripts/a5_recon_capture.py --concurrency 64 --dataset-args "--dataset-name random --random-input-len 14 --random-output-len 16" --real-candidates fixtures/a5/real_adapter_candidates.json
```

Expected: one `[ok]` line per label: `lora-N1-first`, `lora-N1-restart`, `lora-N16-first`, `lora-N16-restart`, `lora-N64-first`, `lora-N64-restart`, `lora-N64-specialize`, `lora-N64-no-stats` and `lora-gate-real`. A `[FAILED]` line is an answer, not an error to retry away. The outcome, including an unhealthy engine's log lines, is saved in the file either way.

- [ ] **Step 4: Commit the captures**

```bash
git add scripts/a5_recon_capture.py fixtures/a5/*.json
git commit -m "recon: artifact 5's captures from the pinned engine"
```

---

## Task 5: The answers

**Files:**
- Create: `scripts/a5_recon_report.py`, `fixtures/a5/recon_report.json`, `docs/recon-a5.md`

- [ ] **Step 1: Create the report script**

```python
"""Compute the answers to R1-R9 from fixtures/a5/*.json.

    .venv/bin/python scripts/a5_recon_report.py

Writes fixtures/a5/recon_report.json, which docs/recon-a5.md cites.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from multilora.recon_report import report

DIR = Path(__file__).resolve().parents[1] / "fixtures" / "a5"
SKIP = {"recon_report.json", "real_adapter_candidates.json"}


def main() -> int:
    captures = [json.loads(p.read_text()) for p in sorted(DIR.glob("*.json")) if p.name not in SKIP]
    if not captures:
        raise SystemExit(f"no captures in {DIR}; run scripts/a5_recon_capture.py first")
    answers = report(captures)
    (DIR / "recon_report.json").write_text(json.dumps(answers, indent=1, sort_keys=True))
    print(json.dumps({k: v for k, v in answers.items() if k != "probes"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Compute the answers**

Run: `.venv/bin/python scripts/a5_recon_report.py`
Expected: a JSON object with keys `R1_…` through `R9_…` and `request_shape_prompt_tokens`, and `fixtures/a5/recon_report.json` written.

- [ ] **Step 3: Apply each answer's rule**

These rules were fixed before the data, in amendment §6. Read each answer from the output, apply its rule, and write both into `docs/recon-a5.md` (Step 4).

| Answer | Rule |
|---|---|
| `R1_in_batch_cap_is_max_loras` false | Stop. The engine lacks `--max-loras`; nothing in §3a holds |
| `R2_highest_healthy_slots` below 64 | The sweep's top is the largest power of two at or below it. Below 16, stop and ask the author |
| `R3_every_adapter_answered` false | Stop. Synthetic adapters do not serve, which is August §4's go/no-go |
| `R4_bench_flags_missing` non-empty | Stop, and tell artifact 4's session: the shared wrapper cannot run the phases |
| `R4_engine_flags_missing` non-empty | If it is only `--specialize-active-lora`, the diagnostic is cut. Otherwise stop |
| `R4_phase_arrays_complete` false | Stop. The per-request arrays §3f reads are not produced |
| `R5_max_distinct_running_at_top` below the top point | C cannot keep every adapter in flight. The sweep's top becomes the largest power of two at or below this value |
| `R6_kv_reported_with_lora` false | Stop. KV capacity would need a new measurement, which is an amendment |
| `R7_gauge_exported` false | The manipulation check is by construction only. The gauge control is cut, because there is no gauge to cost |
| `R9_specialize_flag_present` false | The diagnostic is cut |
| `request_shape_prompt_tokens` not one value | Stop. The tokenizer disagreed with itself across probes |
| R10, from Task 2 | Already applied there |

R8's startup times feed Task 6's budget.

- [ ] **Step 4: Write `docs/recon-a5.md`**

Use this structure. Every value comes from `fixtures/a5/recon_report.json` or `fixtures/a5/real_adapter_candidates.json` and names its source key.

```markdown
# Artifact 5 — reconnaissance record (amendment §6)

Captured <date> on image `<digest reference>`, endpoint `<RUNPOD_ENDPOINT_ID>`,
model `<MODEL_ID>` at `<MODEL_REVISION>`. Captures: `fixtures/a5/`. Answers
computed by `scripts/a5_recon_report.py` into `fixtures/a5/recon_report.json`.

| # | Answer | Source key | Rule applied |
|---|---|---|---|
| R1 | ... | `R1_in_batch_cap_is_max_loras` | ... |
| R2 | ... | `R2_highest_healthy_slots` | ... |
| R3 | ... | `R3_every_adapter_answered` | ... |
| R4 | ... | `R4_bench_flags_missing`, `R4_engine_flags_missing`, `R4_phase_arrays_complete` | ... |
| R5 | ... | `R5_max_distinct_running_at_top` | ... |
| R6 | ... | `R6_kv_reported_with_lora` | ... |
| R7 | ... | `R7_gauge_exported` | ... |
| R8 | startup seconds per point, first and restart | `probes.*.startup_s`, `probes.*.compile_state` | feeds the budget |
| R9 | ... | `R9_specialize_flag_present` | ... |
| R10 | ... selected of ... seen | `real_adapter_candidates.json` | ... |
| Request shape | ... prompt tokens + 16 output | `request_shape_prompt_tokens` | fixes `--random-input-len` |

## Decisions carried into the pre-registration

One line per decision the rules produced, for example the sweep's top or a cut condition.
```

Fill every `...` and `<…>`. This file is a record: it states what was observed, and its values are never edited after the pre-registration commits.

- [ ] **Step 5: Commit**

```bash
git add scripts/a5_recon_report.py fixtures/a5/recon_report.json docs/recon-a5.md
git commit -m "recon: artifact 5's answers, computed from the captures, and the rules applied"
```

---

## Task 6: Draft the values, then compute the budget

The budget reads the pre-registered values, and two of those values, whether the diagnostic and the gauge control run, are what the budget decides. So the values are drafted with both included, the budget runs, and the flags are set from its answer.

**Files:**
- Create: `multilora/prereg_values.py`, `scripts/a5_budget.py`, `tests/test_multilora_engine_flags.py`

- [ ] **Step 1: Decide each value**

Every field of `Preregistration` gets a value from one of three sources. **The author signs off the four marked "author"**; confirm them in chat before writing the file.

| Field | Source | Proposed value |
|---|---|---|
| `concurrency` | R5, R2 | 64, or the lowered sweep top |
| `rank` | Task 3's `A5_MAX_LORA_RANK` | 16 |
| `target_modules` | Task 3's `A5_TARGET_MODULES` | the seven projections |
| `gate_adapters` | Task 2 | 4 |
| `warmup_requests_per_adapter` | fixed | 2 |
| `scrape_interval_s` | fixed | 1.0 |
| `knee_threshold` | **author** | 0.10: a 10% throughput loss per doubling of adapters |
| `request_tokens` | `request_shape_prompt_tokens` + 16 | measured |
| `context_length_tokens` | artifact 1's `max-model-len` | 8192 |
| `slo_ttft_p95_s` | **author** | 1.0 |
| `requests_per_tenant_month` | **author** | 100,000 |
| `peak_to_average` | **author** | 3.0 |
| `gpu_hourly_rate` | `gpu_hourly_rate` in artifact 4's committed assumptions | artifact 4's |
| `schedule_seed` | fixed; a date is conventional | 20261001 |
| `include_diagnostic`, `include_control` | Task 5's rules, then this task's budget | start both `True` unless a Task 5 rule cut one |
| `bench_dataset_args` | the request shape | `("--dataset-name", "random", "--random-input-len", "<prompt tokens>", "--random-output-len", "16")` |
| `real_adapters` | `real_adapter_candidates.json` `selected` | the four (repo, commit) pairs |
| `sweep` | R2, R5 | (1, 2, 4, 8, 16, 32, 64) unless lowered |

`equivalence_margin` is τ/2, so the author's τ also sets the gate's margin: 0.05 at τ = 0.10.

- [ ] **Step 2: Write `multilora/prereg_values.py`**

Follow this shape, with Step 1's values:

```python
"""Artifact 5's pre-registered values. Committed with docs/experiment-a5.md,
before the first measured run; tests/test_multilora_prereg_values.py keeps the
two identical and ties the measured values to fixtures/a5/."""

from multilora.prereg import Preregistration

PREREG = Preregistration(
    concurrency=64,
    rank=16,
    target_modules=("q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"),
    gate_adapters=4,
    warmup_requests_per_adapter=2,
    scrape_interval_s=1.0,
    knee_threshold=0.10,
    request_tokens=MEASURED_PROMPT_TOKENS + 16,
    context_length_tokens=8192,
    slo_ttft_p95_s=1.0,
    requests_per_tenant_month=100_000.0,
    peak_to_average=3.0,
    gpu_hourly_rate=ARTIFACT_4_RATE,
    schedule_seed=20261001,
    include_diagnostic=True,
    include_control=True,
    bench_dataset_args=(
        "--dataset-name", "random",
        "--random-input-len", str(MEASURED_PROMPT_TOKENS),
        "--random-output-len", "16",
    ),
    real_adapters=SELECTED_PAIRS,
)
```

`MEASURED_PROMPT_TOKENS`, `ARTIFACT_4_RATE` and `SELECTED_PAIRS` are not names to define. Replace each with its literal value from Step 1's table. `SELECTED_PAIRS` becomes a tuple of four `("repo/id", "commit")` tuples, in the order `real_adapter_candidates.json` lists them. The committed file holds literals only, so a reader sees every value without running anything.

- [ ] **Step 3: Check every flag against the pinned engine's own help text**

Create `tests/test_multilora_engine_flags.py`:

```python
"""Every flag artifact 5 passes exists in the pinned engine and client.

Reads the help text reconnaissance captured from the image itself
(fixtures/a5/help.json). A flag vLLM renamed or never had would otherwise
surface as an engine that refuses to start on the first paid instance."""

import json
from pathlib import Path

from multilora.prereg_values import PREREG
from multilora.serving import BENCH_FLAGS, ENGINE_FLAGS, SPECIALIZE_FLAG

HELP = Path(__file__).resolve().parents[1] / "fixtures" / "a5" / "help.json"


def _text(key: str) -> str:
    out = json.loads(HELP.read_text())["outcome"]["payload"][key]
    return out["stdout"] + out["stderr"]


def test_every_engine_flag_the_worker_passes_exists():
    needed = [f for f in ENGINE_FLAGS if f != SPECIALIZE_FLAG or PREREG.include_diagnostic]
    assert [f for f in needed if f not in _text("serve_help")] == []


def test_every_bench_flag_the_phases_need_exists():
    assert [f for f in BENCH_FLAGS if f not in _text("bench_help")] == []
```

Run: `.venv/bin/python -m pytest tests/test_multilora_engine_flags.py -v`
Expected: 2 passed. A failure names a flag the pinned engine lacks. Apply Task 5's R4 rule and re-draft.

- [ ] **Step 4: Create the budget script**

```python
"""Compute the campaign's cost from reconnaissance timings (amendment §6).

    .venv/bin/python scripts/a5_budget.py

Reads fixtures/a5/recon_report.json and multilora/prereg_values.py. Prints the
estimate and whether the gauge control and the diagnostic fit under $20.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from multilora.prereg_values import PREREG

from multilora.budget import estimate

REPORT = Path(__file__).resolve().parents[1] / "fixtures" / "a5" / "recon_report.json"


def main() -> int:
    probes = json.loads(REPORT.read_text())["probes"]
    timings, cold = {}, {}
    for label, p in probes.items():
        n = p["n_slots"]
        if label.endswith("-restart"):
            timings[n] = {"setup_s": p["setup_s"], "warm_startup_s": p["startup_s"],
                          "seconds_per_request": p["phase_seconds_per_request"]}
        elif label.endswith("-first"):
            cold[n] = p["startup_s"]
    result = estimate(PREREG, timings, cold_startup_s=cold)
    print(json.dumps(result, indent=1))
    return 1 if result["over_cap"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run it**

Run: `.venv/bin/python scripts/a5_budget.py`
Expected: JSON with `steps`, `gpu_hours`, `usd`, `include_control` and `include_diagnostic`, and exit code 0 when the estimate fits under $20. The cut order is fixed: the gauge control first, then the diagnostic.

- [ ] **Step 6: If it exits 1 (`over_cap`), stop**

Even with both cuts, the campaign exceeds $20. The next cut is sweep resolution, which amendment §6 leaves to the author, so ask. Never cut the second regime.

- [ ] **Step 7: Set the two flags from the budget, and rerun it**

Set `include_control` and `include_diagnostic` in `multilora/prereg_values.py` to the values printed. Run `.venv/bin/python scripts/a5_budget.py` again. Expected: the same flags, one step (`as registered`), and exit code 0.

- [ ] **Step 8: Commit the script only**

```bash
git add scripts/a5_budget.py
git commit -m "feat: artifact 5's budget from reconnaissance timings"
```

`multilora/prereg_values.py` and the flag test, which imports it, are committed together with the document in Task 7, so the values carry one timestamp and no commit has a test that cannot import.

`multilora/prereg_values.py` is committed together with its document in Task 7, so the two carry one timestamp.

---

## Task 7: The pre-registration document

The commit at the end of this task is the evidence that the values, rules and hypotheses were fixed before any measured run. Priming in plan 3 comes after it.

**Files:**
- Create: `docs/experiment-a5.md`, `tests/test_multilora_prereg_values.py`
- Commit: `multilora/prereg_values.py` and `tests/test_multilora_engine_flags.py` (written in Task 6)

- [ ] **Step 1: Write the failing test**

Create `tests/test_multilora_prereg_values.py`:

```python
"""The pre-registration is one thing in two places: `multilora/prereg_values.py`,
which the code runs on, and `docs/experiment-a5.md`, which a reader sees. These
tests fail if they disagree, or if a value that reconnaissance determined was
written down differently from what reconnaissance measured."""

import json
from pathlib import Path

from multilora.prereg import prereg_table
from multilora.prereg_values import PREREG

REPO = Path(__file__).resolve().parents[1]
DOC = REPO / "docs" / "experiment-a5.md"
CANDIDATES = REPO / "fixtures" / "a5" / "real_adapter_candidates.json"
REPORT = REPO / "fixtures" / "a5" / "recon_report.json"


def test_the_document_embeds_the_exact_values_the_code_runs_on():
    assert prereg_table(PREREG) in DOC.read_text()


def test_the_gate_uses_the_adapters_the_search_selected():
    selected = [tuple(x) for x in json.loads(CANDIDATES.read_text())["selected"]]
    assert selected == list(PREREG.real_adapters)


def test_the_request_shape_is_the_measured_prompt_and_sixteen_tokens():
    tokens = json.loads(REPORT.read_text())["request_shape_prompt_tokens"]
    assert len(tokens) == 1, f"the tokenizer gave different counts across probes: {tokens}"
    args = list(PREREG.bench_dataset_args)
    assert args[args.index("--random-input-len") + 1] == str(tokens[0])
    assert args[args.index("--random-output-len") + 1] == "16"
    assert PREREG.request_tokens == tokens[0] + 16
```

Run: `.venv/bin/python -m pytest tests/test_multilora_prereg_values.py -v`
Expected: `test_the_document_embeds_the_exact_values_the_code_runs_on` FAILS with `FileNotFoundError` for `docs/experiment-a5.md`. The other two pass. If either of those fails, a value in `prereg_values.py` disagrees with what reconnaissance measured, so fix the value, not the test.

- [ ] **Step 2: Generate the parameter table**

```bash
.venv/bin/python -c "from multilora.prereg import prereg_table; from multilora.prereg_values import PREREG; print(prereg_table(PREREG))"
```

- [ ] **Step 3: Write `docs/experiment-a5.md`**

Paste Step 2's output verbatim under "Parameters". The test fails on any difference.

```markdown
# Artifact 5 — Pre-registration

Committed before the first measured run. The git timestamp on this file and on
`multilora/prereg_values.py` is the evidence the values below were fixed in
advance. Design: docs/superpowers/specs/2026-09-26-multi-lora-serving-harness-amendment.md.

## Configuration held fixed

Image `<digest reference>`, vLLM `<version from fixtures/a5 logs>`, model
`<MODEL_ID>` at `<MODEL_REVISION>`, GPU `<gpu type>`, `max-model-len` 8192,
`max_lora_rank` `<rank>`, target modules `<modules>`, prefix caching off,
`VLLM_TUNED_CONFIG_FOLDER` unset, FlashBoot off, workersMin 0, workersMax 1.
Reconnaissance record: docs/recon-a5.md.

Any change to a value above ends the experiment rather than continuing across
the boundary, as in artifact 1.

## Parameters

<paste prereg_table output here>

## Conditions

Sweep points `<sweep>`, each at 24 instances. Diagnostic at `<points>` with
`specialize_active_lora` on: `<included or cut, and why>`. Gauge control at 64
slots with stats logging off: `<included or cut, and why>`. The gate runs
first, alone, 24 instances. Order within each block is drawn by
`harness.scheduler` from `schedule_seed`.

## Hypotheses

**H1 (heterogeneity).** Spread minus concentrated throughput is negative at
every sweep point above 1 and grows in magnitude with slots.

**H2 (heterogeneity dominates).** At the top sweep point, the heterogeneity
cost in throughput exceeds the registered-slot cost.

**H3 (memory is capacity, not latency).** KV capacity falls with slots, and at
the inherited request shape the KV concurrency ceiling exceeds C at every
point, so memory does not bind (amendment §3c).

**H4 (slot overhead).** With the diagnostic run, most of the registered-slot
cost is the slot-proportional kernel overhead, not memory (amendment §3b).

## Rules fixed now

- Failure: amendment §3f's three-way rule; a phase whose counts disagree with
  the tool's is not trusted.
- Exclusion: an instance whose compile cache read cold (S4b ≥ 1 s) is excluded.
- Gate: amendment §4; margin τ/2; inconclusive is not a pass. The campaign
  does not start unless the gate passes.
- Knee: amendment §4's point-estimate rule on spread throughput.
- Tenants per GPU: the smallest of the slot, throughput and memory bounds.
- Every published quantity is a median across instances with a bootstrap
  interval; no mean is published.
```

Replace every `<…>` with its value from Tasks 1–6. Delete H4 if the diagnostic was cut, and say so in "Conditions".

- [ ] **Step 4: Run the pre-registration tests and the whole suite**

Run: `.venv/bin/python -m pytest tests/test_multilora_prereg_values.py tests/test_multilora_engine_flags.py -v`
Expected: 5 passed.

Run: `.venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit, with nothing measured before this commit**

```bash
git add multilora/prereg_values.py docs/experiment-a5.md tests/test_multilora_prereg_values.py tests/test_multilora_engine_flags.py
git commit -m "docs: artifact 5 pre-registration"
```

---

## Self-review notes

**Amendment §6 coverage:** R1–R9 are captured in Task 4, computed in Task 5 and carried by explicit rules. R10 is Task 2. Budget and cut order are Task 6. The request shape is measured, not assumed (Tasks 4 and 5), and a test ties it into the pre-registration (Task 7).

**Amendment §8 items this plan closes:** `docs/experiment-a5.md` committed before the first paid measured run. R1–R10 answered, with captures committed under `fixtures/a5/`. `multilora` added to `FIRST_PARTY`.

**Where the plan asks the author:** four values in Task 6 (τ, the SLO, requests per tenant per month, and the peak-to-average factor). It also asks after any "stop" in Task 5's rules, and if Task 2 finds too few adapters or Task 6 is over the cap. Everything else follows a rule written before the data.

**Placeholders:** the `<…>` fields in the two documents are values produced by the tasks before them. Each names its source; none is a design decision left open.
