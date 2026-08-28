# Reconnaissance — RunPod setup

`capture.py` submits jobs to a RunPod serverless endpoint and saves the raw
result verbatim into `fixtures/`. It publishes nothing: the sample is far too
small and the configuration is not frozen.

Everything downstream of this directory is blocked on it. `coldstart/vllm_logs.py`
parses log lines copied out of `fixtures/vllm_logs/startup_0.log`, and
`coldstart/runpod_api.py` maps the lifecycle fields actually present in
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
