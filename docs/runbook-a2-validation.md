# Runbook: artifact 2's LB probe and the three validation repeats

For the owner; not a plan step. Do not run any of this without the owner's say-so.
Run every command from the repository root.
Nothing here is run by the plan that built it: the probe, the driver, the pin and the
open-loop sender were proven offline, against fakes and a local HTTP server, and have
never touched RunPod.

This runbook describes the code as built (reviewed after plan 2b's task text was
written), not as the plan first described it. Where the two differ, the code wins:
`scripts/a2_lb_probe.py`, `scripts/a2_lb_common.py`, `scripts/a2_validate.py`,
`harness/runpod/pinning.py`, `harness/open_loop.py`, `worker/lb_serve.py`,
`worker/a2_middleware.py` and the amendment of 2026-10-04 in `docs/experiment-a2.md`.
No commit hash is quoted: it would be stale at the next commit.

**Owner decisions this checklist carries out (2026-10-04):** a load-balancing endpoint, with
`workersMax` set by hand to 2 and `workersMin` written only by the driver; nvidia-smi stays the
headline utilisation signal; the gate judges server-side latency; a void repeat runs once more.

**A. Image.**
- Push this plan's commits (the owner's call). `worker/**` changed, so CI (`build-worker.yml`)
  rebuilds the image; read the new `ghcr.io/...@sha256:` digest from its summary.
- Pin templates by digest, never by tag.
- Confirm the image holds `/opt/lb_serve.py` and `/opt/a2_middleware.py`.
  `tests/test_harness_boundary.py` already enforces the COPY lines.

**B. Template (new).**
- Image: the digest from A.
- `dockerStartCmd`: `python3 -u /opt/lb_serve.py`.
- Environment, all of it required. `lb_serve.py` refuses to start without `MODEL_ID`,
  `MODEL_REVISION`, `MAX_MODEL_LEN` and `PORT`, with no defaults, because a default would start
  a different engine than the one the curve measured, and start it without error:
  - `MODEL_ID`, `MODEL_REVISION`, `MAX_MODEL_LEN`: copy them from the sweep template `utujdvq2pp`
    rather than retyping.
  - `PORT=8000`: where vLLM listens, and where the load balancer routes.
  - `PORT_HEALTH=8000` and `HEALTH_CHECK_PATH=/health`: the platform's health probe, aimed at
    vLLM's own `/health`. These two are read by RunPod, not by `lb_serve.py`, so nothing in this
    repository checks them. Per RunPod's documentation the health path defaults to `/ping`, which
    vLLM does not serve; a missing `HEALTH_CHECK_PATH` would show as P1 failing.
- Container disk as the sweep template.

**C. Endpoint (new; type: load balancing; owner via the console).**
- GPU `NVIDIA GeForce RTX 4090`, network volume `9c7ut2slrd` (P7: if the console refuses a
  volume for an LB endpoint, record it and stop; every cold start would then download 16 GB).
- `workersMin` 0, **`workersMax` 2** (owner decision 3), idle timeout 5 s.
- Record its id in `.env` as `RUNPOD_A2_LB_ENDPOINT_ID`.
- The queue endpoints `a8261k5opy1ldl` and `7h0aglrmsjovyc` stay as they are.

**D. Free preflights.**

```bash
set -a; . ./.env; set +a
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a2_lb_probe.py --preflight-only
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a2_validate.py --preflight-only --template-id <id>
```

The two check different things:
- The probe's preflight reads the endpoint and requires `workersMin` 0 and `workersMax` 2. It
  prints `[preflight] <id>: workersMin 0, workersMax 2; nothing written`.
- The validation driver's preflight first runs `assert_endpoint_matches` on the GPU type, the
  network volume and the template id, then the same `workersMin`/`workersMax` check. It prints
  `[preflight] <id> matches the LB pin set and holds workersMax 2; nothing written`.

Both write nothing. `assert_endpoint_matches` fails closed on any absent key. If an LB endpoint
reports a field differently (for example `networkVolumeId`), print the keys as in
`docs/runbook-service-sweep.md` section D, and decide before changing a pin. A refusal on
`workersMax` means the console value is not 2; fix it by hand, because this code never writes it.

**E. Cost.** All figures use RunPod's $1.10/h for an RTX 4090 worker; check the day's rate first.
- One probe is 2 workers x (startup ~1.5 min + warm-up >= 0.5 min + 6 steps x 30 s + release)
  ~ 2 x 6 min. That is about $0.25, or about $0.50 with a cold image pull.
- One repeat is 2 workers x (startup + warm-up + 400 s + release) ~ 2 x 10 min ~ $0.37. Three
  repeats cost about $1.10.
- A void repeat costs another $0.37.
- The ceiling on a warm-up that never succeeds is its 900 s deadline: 2 workers x 15 min is about
  $0.55, spent for no data. A refused or failed run still bills the minutes the workers were pinned.
- Check the balance before and after each, and record the spend for spec §13.

**F. The probe (paid, ~$0.50).**

The 450 req/s step uses up to 4096 pool threads, each holding a socket, and macOS defaults to a
soft limit of 256. The probe raises the soft limit to 8192 itself, after its out-dir check and
before the pin, or refuses there naming the remedy: nothing is pinned or written. `ulimit -n 8192`
is only a fallback, for the case where the hard limit is too low for the probe to raise it.

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a2_lb_probe.py --out build/a2-lb-probe 2>&1 | tee build/a2-lb-probe.log
```

What the probe does, so its log is readable:
- It refuses a non-empty `--out`. It writes a stub `summary.json` (`status: "warming"`) BEFORE the
  pin is attempted, so **a refused pin (the preflight said no) still leaves `summary.json` behind.
  Move the out dir aside (`mv build/a2-lb-probe build/a2-lb-probe.refused`) before running again**,
  or the next run refuses the non-empty directory.
- It pins 2 workers, warms up, then runs 6 constant-rate steps of 30 s: 25, 50, 100, 200, 300 and
  450 req/s, with up to 4096 requests in flight (`LADDER_MAX_IN_FLIGHT`; the replay default of
  1024 would hold only ~2.3 s of latency at 450 req/s and blame the load balancer for the driver's
  own queueing). Each step's requests go to `build/a2-lb-probe/step-<rate>.jsonl`.
- **Warm-up** sends 20 req/s in 5 s chunks until both workers have answered, cleanly, for 30 s. It
  has a wall-clock deadline of 900 s (checked before and after every chunk, so a hung endpoint
  cannot run it past the deadline by chunk arithmetic) and gives up with an error naming how many
  workers answered. It also fails at once, without waiting for the deadline, if responses have
  been 200 for 30 s and none carried `x-a2-worker` (**P5**: the middleware is not loaded, or the
  load balancer strips headers), and fails if more than 2 distinct workers answer.
- **`summary.json` is written incrementally** (atomically, via a temp file), after warm-up and after
  every step, and once more on the way out of any failure. It carries `status`: `warming`,
  `running`, `complete`, or `stopped: <reason>`; the warm-up's last chunk summary, the worker ids,
  the steps, `release` (`ok` or `FAILED`) and `error`. A partial run therefore still leaves its
  evidence.
- **Spend guard:** the ladder stops after any step in which more than 50% of the requests failed
  (non-200 or error), and says so (`[stop] ...`, `status: stopped: ...`). A later step cannot turn a
  failing ladder into a passing one, so continuing would only bill. The acceptance at 450 req/s
  then prints `not evaluable`.

Read P1-P8 off the log and `build/a2-lb-probe/summary.json`:

| # | Look at | If it is not as assumed |
|---|---|---|
| P1 | The warm-up finished, and `[warm] workers [...]` names 2 | The LB never routed to a loading worker. Try `HEALTH_CHECK_PATH` on a tiny shim answering 204 while vLLM loads; that is a code change with a test. |
| P2 | Two distinct workers during warm-up, with no request reaching a third | The pin did not hold on an LB endpoint, or `workersMax` is not 2; stop. |
| P3 | `worker_share` per step | The simulator assumes even balancing. A skewed share at the top step fails acceptance (each worker needs >= 35%). |
| P4 | `non_200` and `errors` at every step | Find the first step with failures. That rate is the LB's ceiling, and the validation load (peak ~401 req/s) must sit below it (an amendment). |
| P5 | `server_p50_s` present at every step, and `headerless_200` 0 | The middleware did not load, or the LB strips headers. Read the engine log; the fix is in `worker/a2_middleware.py` or `lb_serve.py`. |
| P6 | `client_minus_server_p50_s` | WAN plus LB time. Recorded for the post, not judged. |
| P7 | The endpoint was created with the volume | See C. |
| P8 | `max_jitter_s` at 450 req/s | Above 0.25 s, the laptop driver cannot hold the schedule. Run the driver from a CPU pod in EU-RO-1, or lower the load (an amendment). |

The last line is `[accept] PASS` or `[accept] FAIL: ...` (or `not evaluable`, if the 450 req/s
step did not run). The acceptance is the amendment's, at the 450 req/s step only: every response
200, each of the 2 workers serving at least 35%, and max send jitter at most 0.25 s. On FAIL or
`not evaluable`, stop and decide with the owner; the amendment says so, and amends itself before
any repeat.

**G. Three repeats (paid, about $1.10).** Only after `[accept] PASS`:

```bash
ulimit -n 8192   # the driver also raises the soft limit itself, or refuses before the pin
set -o pipefail   # without it, tee's exit status hides a failed repeat from the loop
for k in 1 2 3; do
  PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a2_validate.py --repeat $k --template-id <id> 2>&1 | tee -a build/a2-validation.log || break
done
```

A failed or killed repeat now stops the loop: `set -o pipefail` makes the pipeline carry the
driver's exit status (an explicit kill ends the driver with exit 128 + the signal), and `|| break`
leaves the loop on it, so a later repeat is not paid for after an earlier one failed. A void repeat
is not a failure (the driver exits normally and prints `VOID`), so the loop goes on to the next `k`;
read the void reasons afterwards. Running the repeats one at a time is the conservative
alternative.

What the driver does, in order:
1. **Before any pin:** it checks the slot, and **refuses an unwritable `--out`** (it creates the
   directory and writes then deletes a probe file; finding out after ten minutes of pinned GPUs
   that the record has nowhere to go would waste the run). It then **raises the open-files soft
   limit to 8192, or refuses**, naming the remedy: run `ulimit -n 8192` and start again.
   It then reads the endpoint (GPU, volume, template, `workersMin` 0, `workersMax` 2) and builds
   the one pre-registered schedule (129,876 requests, seed 20261004, drain 30 s).
2. It pins, and warms up as in F (20 req/s; the worker ids it sees are the run's `host_ids`).
3. **A void repeat already in the slot is moved aside only now, after the pin and the warm-up
   succeeded**, just before the replay starts. A run that failed earlier leaves the slot as it was
   and costs no rerun. A valid repeat is never overwritten; the script refuses.
4. It replays the schedule open-loop (4096 in flight), releases the workers, and writes
   `data/a2/validation/repeat-K.json.gz`.

Reading the result line (`[repeat K] ...`):
- It ends with `valid` or `VOID: <reasons>`. A repeat is void if, and only if, any request had no
  200 (including transport errors), a response came from a worker outside the pinned set, or a 200
  lacked a usable server-latency header (absent or unparseable). This is the amendment's three
  rules. **A latency header that is absent or unparseable (not a number, NaN, negative) counts as
  absent**, so it voids. A 200 without the worker header is counted and printed (`N 200s without
  the worker header`) but is not itself a void reason; the latency header rule covers the practical
  case, because the middleware stamps both together.
- A void repeat is run once more with the same `--repeat K`. A second void ends the gate as not
  evaluable, and the script refuses a third; publish the causes. Never run a valid K again.
- **Send jitter above 0.5 s:** the repeat is recorded and is valid, but the line is followed by
  `WARNING: send jitter ... exceeds 0.5 s; --judge will refuse this repeat`. Jitter is not a void
  rule in the amendment, so the run is not voided, and the gate refuses to judge it (`RealRun`).
  That is an owner decision, not an automatic rerun: the options are to accept that the gate is
  not evaluable on this repeat, or to amend (for example a CPU pod in EU-RO-1) before using the
  rerun. Do not rerun by reflex; the one allowed rerun is for voids.
- **A failed write.** If the replay completed but the record could not be written, the raw outcomes
  are dumped to a file in the **system temp directory** and its path is printed to stderr (`the raw
  outcomes are in /.../a2-repeat-K-<stamp>-....json`), and `RecordLost` is raised. **Move that file
  into the repo at once** (for example into `data/a2/validation/`): macOS may purge its temp dir,
  and it is the only copy of ~$0.37 of data.
- **An error after the replay** (for instance `workersMax` changed during the run, or a release
  problem) is recorded in the record's `post_run_error` and printed as `WARNING after the replay`,
  but the repeat is **not voided**: the void list is the signed amendment's, and a new void category
  would burn the one allowed rerun. The owner reads the error and decides what the evidence is worth.
  If the release itself failed, the record also says `release: "FAILED"`; see the end of this file.
- A failure BEFORE the replay completes (warm-up gave up, interrupt) writes no record and leaves the
  slot unchanged, apart from a void moved aside once the replay was about to start (the message says
  which).

**H. Verdict (free).**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a2_validate.py --judge
```

- It refuses unless all three repeats are present and valid, and tells you which is missing.
- It writes `data/a2/validation/verdict.json` and `validation_overlay.png`, and prints a `[judge]`
  line with the outcome, the judged bins, the misses and any host novelty. A `WARNING` line appears
  for each repeat that recorded a `post_run_error`: the verdict stands and you decide what it means.
- Look at the figure at full size and at phone width before calling it done.
- Every miss is published with its magnitude (spec §10), and host novelty is disclosed (recorded,
  not voided).
- Commit `data/a2/validation/` (the owner's call).

**If a run ends with `RELEASE FAILED`, the endpoint may still be pinned and billing.**
- `WorkerPin.release()` retries the release and its verifying re-read together for up to 300 s,
  because RunPod answers 409 for a while after any configuration change. It defers SIGTERM and
  SIGHUP while it runs, so a kill during the release does not abandon it: it finishes, then exits
  with 128 + the signal. SIGKILL cannot be handled, and a power cut or closed laptop is not a
  signal at all.
- Set `workersMin` to 0 in the console, or run, from the repository root:

```bash
set -a; . ./.env; set +a
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -c "from harness.runpod.pinning import WorkerPin; import os; WorkerPin(os.environ['RUNPOD_A2_LB_ENDPOINT_ID'], os.environ['RUNPOD_API_KEY'], workers=2).release()"
```

- Then confirm the spend rate with the GraphQL `myself { currentSpendPerHr }` query.

**Notes on the code as built.**
- Both the probe and the driver raise the open-files soft limit to 8192 before they pin (the shared
  `ensure_fd_limit` in `scripts/a2_lb_common.py`), or refuse. `ulimit -n 8192` is only a fallback.
- `workersMax` is never written by this code. After a run it is re-read, and a change is an error
  (workersMin is back to 0, but the evidence was collected under a ceiling nobody checked).
- The preflights, the pin and the release talk to `https://rest.runpod.io/v1`; the requests go to
  `https://<endpoint id>.api.runpod.ai/v1/completions`. The key is read from `RUNPOD_API_KEY` and is
  never printed or written into a record.
