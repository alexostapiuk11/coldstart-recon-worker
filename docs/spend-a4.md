# Spend record: artifact 4's paid runs

**Drafted 2026-10-07 for the owner to confirm.** Every dollar figure comes from
RunPod's billing API (`GET /v1/billing/endpoints` for endpoint `nnypnh9drkq5ux`,
hourly buckets, last read 2026-10-07 08:16 UTC, two hours after the final job), not
from the console; the owner confirms the total against the console before
publication. Job counts and execution times come
from the committed stores. Scope amendment section 12 requires this artifact's own
spend recorded.

## What the endpoint was billed

| UTC day | Hours billed | Dollars |
|---|---|---|
| 2026-10-05 | 5.70 | $6.32 |
| 2026-10-06 | 14.42 | $15.98 |
| 2026-10-07 | 2.64 | $2.93 |
| **Total** | **22.77** | **$25.23** |

- The implied rate is $0.000308 per second ($1.108 per hour). Step 2
  registered $1.1095 per hour from an earlier partial read of the same record
  (`placement/registered.py`); the difference is 0.1% and the registered value was
  not changed.
- **This is the final figure.** It was read at 08:16 UTC, after the last job (the
  validation replays, finished about 06:17 UTC; the newest bucket is 06:00 UTC), and
  it equals the read taken at the end of the replays: $25.2311 for 81,956 s. No
  hourly bucket has been added since, so no later billing is expected from this
  endpoint's jobs. The endpoint's health still lists one idle worker, which has
  accrued no billing.
- Reconnaissance alone was read separately on 2026-10-05, before any campaign
  started: $0.4988 for 1,623 s (`docs/recon-a4.md`, section 1).

## Per paid step

Execution time is each job's own `clock_C.execution_ms`; the dollar column prices it at
the implied rate above. Queue and cold-start waits before a worker starts are not
billed (the six jobs of the first attempts at designs 1c and 1d each waited 90
minutes for a worker that never started and cost nothing).

| Step | Jobs | ok | Execution hours | At the implied rate | Store |
|---|---|---|---|---|---|
| Reconnaissance (8 answering jobs and 3 discarded attempts) | 11 | 8 | 0.39 | $0.44 | `fixtures/a4/recon/`, `fixtures/a4/recon-failed/` |
| KV-pin probe | 3 | 3 | 0.23 | $0.25 | `data/a4/kvpin-probe.jsonl` |
| Cell campaign | 152 | 144 | 12.18 | $13.50 | `data/a4/cells.jsonl` |
| Cell re-run, design 1a | 32 | 32 | 4.40 | $4.87 | `data/a4/cells-ramp-1a.jsonl` |
| Cell re-run, design 1b | 8 | 5 | 1.21 | $1.34 | `data/a4/cells-ramp-1b.jsonl` |
| Cell re-run, designs 1c and 1d, first attempts (no credit: nothing ran) | 6 | 0 | 0.00 | $0.00 | `data/a4/cells-ramp-1c.jsonl`, `data/a4/cells-ramp-1d.jsonl` |
| Cell re-run, designs 1c and 1d, retries | 6 | 6 | 1.42 | $1.57 | `data/a4/cells-ramp-1c-retry.jsonl`, `data/a4/cells-ramp-1d-retry.jsonl` |
| Cell top-up 1e | 2 | 2 | 0.42 | $0.46 | `data/a4/cells-ramp-1e.jsonl` |
| Ramp probe | 1 | 1 | 0.28 | $0.31 | `data/a4/ramp-probe.jsonl` |
| Swaps | 16 | 16 | 0.36 | $0.40 | `data/a4/swaps.jsonl` |
| Sleep mode | 8 | 8 | 0.21 | $0.24 | `data/a4/sleep.jsonl` |
| Validation replays | 3 | 3 | 0.79 | $0.88 | `data/a4/replay.jsonl` |
| **Total** | **248** | **228** | **21.89** | **$24.26** | |

The execution-time total is $24.26 against $25.23 billed. The
$0.97 difference is worker start-up and the idle seconds each
worker is kept after a job, which are billed but are not in any job's execution time.

## What the plan's estimate missed

The campaigns runbook estimated about 12 GPU-hours, about $13. The jobs the plan
scheduled used 13.54 hours (the cell campaign, swaps, sleep mode and the three
replays), about $15. The other 8.35 hours were not in the plan:
- 7.45 hours re-running co-located cells after the validity and ramp-window
  amendments (designs 1a to 1e), about $8.2;
- 0.51 hours of the two probes that confirmed those amendments;
- 0.39 hours of reconnaissance, which the plan priced separately.

The amendments are in `docs/experiment-a4.md` (2026-10-05 and 2026-10-06); the
co-located pair's memory failures and the neighbour's slow ramp are what made the
re-runs necessary.

## What is not in the endpoint's billing

- **Network volume storage.** The volume `9c7ut2slrd` was enlarged from 50 GB to
  100 GB on 2026-10-05 for the reconnaissance checkpoints. Its monthly charge is
  billed to the account, not the endpoint, and is not in the figures above; the owner
  reads it from the console. It is shared with artifacts 1, 2 and 5.
- **Account credit.** The balance reached zero on 2026-10-06 and workers stopped
  starting until the owner added about $10 on 2026-10-07 (the balance went from
  -$0.01 to $9.99). The balance is a whole-account figure that other artifacts also
  draw on, so it cannot be used to total this artifact.

## Image and endpoint

- **Image:** `ghcr.io/alexostapiuk11/coldstart-recon-worker@sha256:d8bc338a2bc7694c62ec615fd5dde927dbc03d0047a927212023151e5a9046d0`,
  built from commit `91e760d` (its revision label), on `vllm/vllm-openai` v0.27.1,
  CUDA 13.0.2, digest `sha256:0a51ea5b4ae2dc5d81890e5173f54203d2a3ae0cfffe51b8fd2afd4391bfd967`.
  Every paid job above ran on it.
- **Templates:** `fru0y0r3a0` (reconnaissance handler) and `py2mtyfrlq` (measurement
  handler), the same image.
- **Endpoint** `nnypnh9drkq5ux`: RTX 4090, EU-RO-1, network volume `9c7ut2slrd`, 0 to 1
  workers, 5 s idle timeout, 1,800,000 ms execution timeout, FlashBoot off,
  `allowedCudaVersions` `["13.0"]` (pinned in `placement_measure/pins.py` since
  2026-10-05).
