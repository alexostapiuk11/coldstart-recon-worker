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
2. The image is built for you. `.github/workflows/build-worker.yml` builds
   `worker/` natively on an amd64 runner and pushes to
   `ghcr.io/alexostapiuk11/coldstart-recon-worker` on every push that touches
   `worker/`, or on demand from the Actions tab. It is not built locally: the
   base image is amd64-only, so an arm64 Mac would emulate, and the runner's
   `GITHUB_TOKEN` already has write access to this namespace.

   Take the **digest** from the run summary, not the `:latest` tag. Tags drift,
   and the reproducibility claim needs a reader to get the same engine.

   **The package is public**, verified by an anonymous pull of the manifest, so
   RunPod needs no registry credentials. If you ever flip it private, add
   credentials to the endpoint or the pull fails.

   Current image, built from `ebdec67` and confirmed `linux/amd64`:

   ```
   ghcr.io/alexostapiuk11/coldstart-recon-worker@sha256:c85c6c4428e84d06fd6555f7957a65900908889f66f041004179c1119b017b1d
   ```

   Re-check any later build with:

   ```
   TOKEN=$(curl -s "https://ghcr.io/token?service=ghcr.io&scope=repository:alexostapiuk11/coldstart-recon-worker:pull" | python3 -c "import json,sys;print(json.load(sys.stdin)['token'])")
   curl -sI -H "Authorization: Bearer $TOKEN" https://ghcr.io/v2/alexostapiuk11/coldstart-recon-worker/manifests/artifact-1-harness | grep -i docker-content-digest
   ```

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
