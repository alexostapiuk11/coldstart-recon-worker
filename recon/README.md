# Reconnaissance — RunPod setup

`capture.py` submits jobs to a RunPod serverless endpoint and saves the raw
result verbatim into `fixtures/`. It publishes nothing: the sample is far too
small and the configuration is not frozen.

Everything downstream of this directory is blocked on it. `harness/vllm_logs.py`
parses log lines copied out of `fixtures/vllm_logs/startup_0.log`, and
`harness/runpod/api.py` maps the lifecycle fields actually present in
`fixtures/runpod_api/status_0.json`. The plan forbids inventing either.

## Provisioned infrastructure

Created via the RunPod REST API (`https://rest.runpod.io/v1`), not the console.
`RUNPOD_API_KEY` and `RUNPOD_ENDPOINT_ID` live in `.env`, which is gitignored.

| Resource | ID | Notes |
|---|---|---|
| Template | `mzadx4qugv` | image pinned by digest, `MODEL_ID`, 60GB container disk |
| Network volume | `9c7ut2slrd` | 50GB, EU-RO-1 |
| Endpoint | `ka5mryakkxumew` | RTX 4090 (`ADA_24`), min 0 / max 1, 5s idle, 30min exec |

### Three things that will bite anyone reproducing this

**FlashBoot silently ignores `false` at creation.** `POST /endpoints` with
`{"flashboot": false}` returns an endpoint with `flashboot: true`. It only sticks
via a follow-up `POST /endpoints/{id}/update`. This is not cosmetic: FlashBoot
caches worker state specifically to accelerate cold starts, so leaving it on
means measuring RunPod's cache instead of the arms, and the numbers would look
entirely plausible. Re-read the endpoint and assert `flashboot == false` before
any campaign run rather than trusting the create call.

**The datacenter is fixed when the endpoint is created.** `dataCenterIds` reads
back as `None` over REST, and the real binding comes from the attached network
volume — visible as `locations` in the GraphQL API. Repointing an endpoint at a
volume in a different datacenter does *not* move it; the endpoint has to be
deleted and recreated.

**24GB capacity is volatile.** US-KS-2 has no 24GB GPUs at all. US-TX-3 and
US-NC-1 advertised RTX 4090 and then went to `available: false` within minutes,
which presents as a worker flapping between `ready` and `throttled` while the job
sits in queue forever — not as an error. EU-RO-1 was the only datacenter holding
Medium stock. Check availability before a campaign run:

```
curl -s -X POST "https://api.runpod.io/graphql?api_key=$RUNPOD_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"query":"query { dataCenters { id gpuAvailability { gpuTypeId available stockStatus } } }"}'
```

## Remaining human setup

1. A RunPod account and API key. Everything else above is scriptable.
2. Set the endpoint env var `MODEL_ID`: `Qwen/Qwen3-0.6B` for the smoke run, the
   pinned Qwen3-8B revision for the real capture.

## Run

```
export RUNPOD_API_KEY=...
export RUNPOD_ENDPOINT_ID=...

.venv/bin/python recon/capture.py 1   # smoke, tiny model, costs cents
.venv/bin/python recon/capture.py 3   # pinned model, costs a few dollars
```

Never commit the key. `.env` and `secrets/` are already ignored.

## Then answer the three questions

Record the answers in `fixtures/README.md` (template in plan Task 6, Step 4):

- **Q1** — which `S4` sub-phases this engine version delineates in its log, verbatim.
- **Q2** — which lifecycle fields the status payload exposes, and therefore
  whether the residual can be split into queue vs bring-up.
- **Q3** — whether this version compiles at startup. If **no**, H3 and arm C are
  dropped and the scheduler reverts to two arms.

Q3 decides whether the experiment has two arms or three, so answer it before
any paid campaign run.

## Artifact 2 capture (spec §9 Q1/Q2)

Needs an endpoint whose `workersMax` is at least 2. Artifact 1's
`ka5mryakkxumew` is provisioned max 1, and the capture never writes
`workersMax`: that is the cost ceiling, and it is the operator's to set. Rather
than raise that endpoint's ceiling, which would leave it no longer matching
artifact 1's records, provision a new one with `workersMin 0`, `workersMax` at
least 2, `idleTimeout` 5 s, the same image, and a volume in a datacenter with
verified 24GB stock. Then force `flashboot: false` with a follow-up
`POST /endpoints/{id}/update` (create silently ignores `false`).

**The template must override `dockerStartCmd` to
`python3 -u /opt/recon_handler.py`.** The image's default `CMD` is the
measurement handler (`worker/Dockerfile`), which requires `arm` and `run_id` in
its input (`worker/handler.py`). The capture submits `{"recon": true}`, so on
the default command every job fails with a `KeyError` — four paid cold starts
that capture nothing about Q2.

```
export RUNPOD_API_KEY=...
export RUNPOD_A2_ENDPOINT_ID=...    # NOT artifact 1's RUNPOD_ENDPOINT_ID

.venv/bin/python recon/capture_a2.py --preflight-only   # free: one GET, writes nothing
.venv/bin/python recon/capture_a2.py                     # spends: 4 jobs + a pinned window
.venv/bin/python recon/analyse_a2.py fixtures/a2_recon
```

The full run submits four jobs (two bursts of `WORKERS` = 2), pins `workersMin`
at 2 for `SCALE_OBSERVE_SECONDS` (10 minutes), then watches for another 10
minutes after setting it back to 0. Its cost is small against the spec §13
envelope, but it is real, and running it is the operator's decision. Record the
answers in `docs/recon-a2.md`.

**Worst-case wall time is about 3 h 26 min**: 12,360 s, from the constants in
`capture_a2.py`. That is two bursts that each run to `JOB_TIMEOUT_SECONDS`
(2 × 5400), the `IDLE_WAIT_SECONDS` gap (60), the two scale windows
(2 × 600) and a restore that uses all of `RESTORE_DEADLINE_SECONDS` (300).
HTTP time is on top: each request can take up to its 30 s timeout, and a
409/5xx retry adds up to 15 s of backoff. A job that is not terminal by its
deadline is saved as `burstN_i.timeout.json` and stops the run there, so a
timeout in burst1 ends it after about 5400 + 300 s.

The run refuses to write into a non-empty `fixtures/a2_recon/`, so move an
earlier run aside first. Secrets are redacted before anything is written: any
`env` key is dropped whole, and within a string only the secret itself is
replaced (the API key, and `hf_`/`rpa_` followed by 20 or more letters or
digits), so the log lines around it survive. As a second check, run this
before committing, and expect no output. It uses the same token shapes as the
script; tested with macOS's BSD grep.

```
grep -rE '\bhf_[A-Za-z0-9]{20,}|\brpa_[A-Za-z0-9]{20,}' fixtures/a2_recon
```

**If the run ends with `RESTORE FAILED`, the endpoint may still be pinned and
billing.** Release it, then confirm the result it prints shows `workersMin` 0:

```
.venv/bin/python recon/capture_a2.py --restore   # sets workersMin 0 and re-reads; writes nothing
```

The run also restores on Ctrl-C, `kill` (SIGTERM) and a closed terminal
(SIGHUP). A `kill -9` cannot be caught, so run `--restore` after one.
