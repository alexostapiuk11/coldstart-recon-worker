# Reconnaissance — RunPod setup

`capture.py` submits jobs to a RunPod serverless endpoint and saves the raw
result verbatim into `fixtures/`. It publishes nothing: the sample is far too
small and the configuration is not frozen.

Everything downstream of this directory is blocked on it. `coldstart/vllm_logs.py`
parses log lines copied out of `fixtures/vllm_logs/startup_0.log`, and
`coldstart/runpod_api.py` maps the lifecycle fields actually present in
`fixtures/runpod_api/status_0.json`. The plan forbids inventing either.

## Human setup — cannot be automated from here

1. Create a RunPod account and generate an API key.
2. Build `worker/` for **linux/amd64** and push it to a registry RunPod can pull:
   ```
   docker buildx build --platform linux/amd64 -t <registry>/coldstart-recon:v1 --push worker/
   ```
   The base image is amd64-only, so an arm64 Mac must cross-build.
3. Create a serverless endpoint on that image, pinned to **one** 24 GB GPU type
   and **one** region. Both are held fixed for the whole campaign.
4. Create a network volume; it mounts at `/runpod-volume` (see `HF_HOME` in the
   Dockerfile).
5. Set the endpoint env var `MODEL_ID`. Start with `Qwen/Qwen3-0.6B` for the
   smoke run, then switch to the pinned Qwen3-8B revision.

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
