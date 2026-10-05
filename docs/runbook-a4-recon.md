# Runbook: artifact 4's paid reconnaissance

For the owner; not a plan step. Do not run any of this without the owner's
say-so. It rents a GPU.

**Before starting:** `docs/experiment-a4.md` step 1 is committed (its git
timestamp must predate every capture), and the image has been rebuilt with
artifact 4's handlers.

**A. Image.** Push the commits that add `placement_measure/` and the two
`worker/a4_*_handler.py` files. CI (`build-worker.yml`) rebuilds the worker
image because `placement_measure/**` and `worker/**` changed; its summary
prints `ghcr.io/<repo>@sha256:...`. Record that digest; the reconnaissance
record cites it. The base image, vLLM 0.27.1, is unchanged.

**B. Template.** A new one; artifacts 1 and 2's stay as they are.
- Image: the digest from A, never a tag.
- `dockerStartCmd`: `python3 -u /opt/a4_recon_handler.py`. On the default
  command every job fails with `KeyError: 'arm'` (artifact 1's handler).
- No model environment variables: artifact 4's jobs name their checkpoints in
  the payload, pinned by `placement_measure/prereg.py`.
- Container disk as artifact 1's template; network volume `9c7ut2slrd`.

**C. Endpoint.** GPU `NVIDIA GeForce RTX 4090`; `workersMin` 0; `workersMax` 1;
`idleTimeout` 5 s; `executionTimeoutMs` 1800000; the template from B.

**D. Free preflight.** One GET, no job.

```bash
set -a; . ./.env; set +a   # RUNPOD_API_KEY, RUNPOD_A4_ENDPOINT_ID
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a4_recon_capture.py --list
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a4_recon_capture.py --preflight-only --template-id <template id>
```

Expected: eight jobs listed, then `[preflight] endpoint <id> matches artifact 4's pin set`.

**E. Cost estimate.** Eight jobs. Rough wall time per job, from artifact 2's
pilot on this image (8B engine startup 84.5 s cold, 30.6 s warm; teardown
0.5 s) and nothing measured for the 4B checkpoints yet:

| Job | What runs | Estimate |
|---|---|---|
| `help` | two `--help=all` calls | 1–2 min |
| `stage` | download five checkpoints, about 36 GB, to the volume | 5–15 min, UNVERIFIED volume throughput |
| `coresidency-primary`, `-fallback` | two engine starts each | 3–5 min each |
| `swaps-compile`, `swaps-cache` | four swaps each, two starts per swap | 8–15 min each |
| `early-start` | two starts | 2–4 min |
| `sleep` | two starts, two sleeps, one wake | 3–6 min |

That is roughly 35–70 GPU-minutes. Price it with RunPod's per-second rate on
the day, read off the console (UNVERIFIED; the shared tooling plan's item 13).
The first job on a new endpoint may queue for the image pull: artifact 2's
pilot waited 743 s, and its balance change suggests the wait was not billed
(moderate confidence). The staged checkpoints add about 36 GB to the network
volume's storage bill, at a monthly rate also read off the console.

**F. Run, in this order.** Each job's outcome is saved as it lands, and a file
that exists is never overwritten.

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a4_recon_capture.py --template-id <id> --only help,stage
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a4_recon_capture.py --template-id <id> --only coresidency-primary,coresidency-fallback
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a4_recon_report.py
```

Stop here and read the go/no-go. If the primary pair fails and the fallback
passes, the model class changes and the remaining jobs should be rebuilt for
it before they are run; that is an edit to `placement_measure/recon_plan.py`,
reviewed like any other. If both fail, stop: the design changes (scope
amendment §3). Otherwise:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a4_recon_capture.py --template-id <id> --only swaps-compile,swaps-cache,early-start,sleep
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a4_recon_report.py
```

**F2. If a job fails.** Added after review; not part of the plan's text.
`a4_recon_capture.py` saves a failed job's outcome like any other and then
goes on to the next job in the same `--only` batch, so a failure does not stop
the spend by itself. Read the `[capture] <label>: ...` lines as they print.
When a stop point matters, run the batch one label at a time (`--only
swaps-compile`, then `--only swaps-cache`, and so on), and stop after any line
that is not `ok`: a failed `stage` means no later job has its checkpoints. The
bound on a single job is the endpoint's `executionTimeoutMs` (30 minutes) with
`workersMax` 1.

A capture file that exists is never overwritten, and the check covers every
label in the batch before any job is submitted, so one existing file aborts the
whole batch and spends nothing. To re-run a failed job, move its file out of
`fixtures/a4/recon/` (for example into `fixtures/a4/recon-failed/`, committed:
it is evidence that the attempt happened) and run `--only <that label>` alone.
`a4_recon_report.py` reads only `fixtures/a4/recon/`, so the moved-aside file is
not counted; say in `docs/recon-a4.md` that it was re-run and why.

**G. After the run.** Commit `fixtures/a4/recon/` and
`fixtures/a4/recon-report.json`, record the image digest from A and the
console's spend, and write `docs/recon-a4.md` from the report's output. Plan 3
starts from that record.
