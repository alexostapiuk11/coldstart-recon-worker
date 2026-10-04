# Artifact 2 — reconnaissance record (spec §9)

**Date:** 2026-09-17
**Revised:** 2026-10-03: corrected by plan 2a. Step 3 of "What it would take to
close the gate" now reads the capture with Q2's three-way split, and the
endpoint checklist gains `workersMin` and `idleTimeout`.
**Revised:** 2026-10-04: Q1 and Q2 answered by the capture in `fixtures/a2_recon/`
(next section), and Q3's range measured by the service sweep in `data/a2/`. The
2026-09-17 text below that section is kept as written; where it says "unanswered"
it describes the repository before the capture.
**Verdict: GO. Q1 passes (capacity can be pinned and released through the API).
Q2 shows genuine cold starts, so by §9's table both gates stand as the August
design wrote them.** Q3 is a range-setting measurement and is recorded below.

## 2026-10-04 capture: the answers

Endpoint `7h0aglrmsjovyc` (RTX 4090, EU-RO-1, `workersMin` 0, `workersMax` 2,
`idleTimeout` 5 s, `flashboot` false, re-read after creation because create
ignores `false`), template `ws1ptql2n8` (the sweep's image digest, starting
`/opt/recon_handler.py`). One run of `recon/capture_a2.py`, exit 0, about 28
minutes, $0.57 by the account balance (6.07 → 5.49). Read off
`recon/analyse_a2.py fixtures/a2_recon` and `fixtures/a2_recon/capture.jsonl`.

| job | workerId | delayTime (ms) | executionTime (ms) | torch.compile (s) | KV tokens |
|---|---|---|---|---|---|
| burst1_0 | `t8tnuv6d4x7xm8` | 56,819 | 151,528 | 39.60 | 35,792 |
| burst1_1 | `vutpl4jnz8ql1g` | 149,587 | 77,897 | 18.13 | 35,808 |
| burst2_0 | `ae85x6xif5b57v` | 18,488 | 144,478 | 39.57 | 35,808 |
| burst2_1 | `d4namklhg7dpuc` | 24,318 | 149,504 | 43.95 | 35,792 |

**Q2 — distinct workers under concurrent load: yes. Cold or warm-host restart:
cold.** Each burst's two jobs ran on two different workers at the same time
(burst 1: about 57–208 s and 150–228 s after submission; burst 2: about 18–163 s
and 24–174 s). No workerId repeats across the bursts, 60 s apart with a 5 s idle
timeout, so the host affinity artifact 1 saw (23 of 27 runs on one host) did not
show here. Every job's engine log shows a full startup: a complete
`torch.compile` (18–44 s, against the 0.3 s of a surviving container in
`fixtures/README.md`) and the cold-compile KV size (~35,800 tokens, not the warm
43,040). None of §9's warm cases fits: no container survived, and no host was
reused. What the capture cannot say is whether the image was already on those
hosts. `delayTime` of 18–150 s is far below the 743 s and 1,898 s pulls seen
elsewhere, so the image was probably cached at the hosts or in the datacenter.
That is the platform's normal case, and it is a cold start for the engine. One
compile (burst1_1, 18 s) is about half the others with a full log; it is
unexplained and noted.

**Q1 — replica-count control: yes, through `workersMin`.** `POST
/endpoints/{id}/update` with `{"workersMin": 2}` returned 200 in 0.66 s and
echoed the new value; `{"workersMin": 0}` returned 200 in 0.58 s. Two caveats bound
what was measured:

- **Time to effect from cold was not measured.** The pin was sent about 3 s after
  burst 2's last job finished, inside its worker's 5 s idle timeout, so the two
  workers `/health` reported 0.1 s later may have been burst 2's. Plan 2b's
  open-loop gate pins capacity and then waits for it before sending load, so it
  needs only the acknowledgement, which is synchronous. The closed-loop gate,
  which measures how long a scale-up takes, will measure it.
- **`/health`'s worker counts are not an instrument for billing.** They answered
  (the docstring allowed for a 404), but they flicker between `running` and
  `idle` with no job in flight. They also never reached zero: 598 s after the
  release they still read `idle 1, throttled 1`. At the same time GraphQL listed
  no pods and the spend rate was $0.005/h, which is storage only. Artifact 1's
  long-idle endpoint reads `idle 1` too. The balance is the better evidence. Jobs
  account for 523 s ($0.16 at $0.000306/s), and two workers held for the 604 s pin
  for 1,208 s ($0.37). Together that is $0.53 of the $0.57 spent. So the pin held
  two billed workers for its window, and billing stopped after the release
  (medium confidence: the per-second rate is RunPod's list price, and a balance
  can lag).

**Consequences for plan 2b.** The open-loop gate's capacity pinning is `workersMin
= workersMax = N` through the REST update, then a wait for N workers. Release is
`workersMin` 0, confirmed by a re-read and by the spend rate, not by `/health`. The
closed-loop gate stands: a driven scale-up here is a cold start. Record `host_id`
per replica (§10); the recon handler's output already carries the worker id.

**Q3, measured.** The service sweep (`data/a2/service-curve.json`, 3 repeats per
level, `max_num_seqs` 256, prefix caching off) bends between 64 and 128. Per
doubling, throughput rose about 70–80% up to 64 and 46% from 64 to 128; median
latency went from 0.284 s at 1 to 0.606 s at 128. At 256 the engine died of CUDA
out-of-memory at its first step in 3 of 3 runs, with KV cache use at 11%. So what
binds first is activation memory under `gpu_memory_utilization` 0.92, not KV and
not `max_num_seqs`. The curve stops at 128 and records 256 as unservable.

---

Everything below is read off committed artifacts: `fixtures/runpod_api/`,
`fixtures/vllm_logs/`, `data/campaign.jsonl`, and `recon/README.md`. Nothing
here was newly measured; no GPU was rented to produce it.

## First, a naming collision that has to be cleared

There are **two different sets of questions labelled Q1/Q2/Q3** in this repo,
and they are unrelated:

| | Questions | Status |
|---|---|---|
| `recon/README.md` → `fixtures/README.md` | **Artifact 1's**: engine log format, lifecycle fields, does this version compile at startup | **Answered**, in `fixtures/README.md`, 2026-08-28 |
| Final spec §9 | **Artifact 2's**: replica-count control, distinct workers under concurrent load, where the curve bends | **This document** |

Artifact 1's recon is complete and its answers are good — that is why artifact 1
shipped with three arms. It is not evidence about artifact 2, and the identical
numbering makes it easy to believe the gate has been passed when it has not.

---

## Q1 — Does the platform API expose replica-count control?

**Unanswered.**

The endpoint captured against (`ka5mryakkxumew`) is provisioned **min 0 / max 1**
(`recon/README.md`, "Provisioned infrastructure"). A worker ceiling of one means
no scale-up or scale-down action was ever issued, so none of the three things §9
asks for — the actions, their acknowledgement semantics, their latency — has
been observed.

What *is* established, and is not the same thing: worker bounds are settable at
the REST layer. `recon/README.md` documents `POST /endpoints/{id}/update`
changing endpoint configuration after creation, discovered while forcing
`flashboot: false`. That a config field can be written is weak evidence that
capacity is controllable; it says nothing about whether a scale action is
acknowledged synchronously, how long it takes to take effect, or whether the
count can be pinned reliably enough to drive the open-loop gate.

§9's go/no-go table makes Q1 the hard gate: *"Q1 fails → Stop and redesign.
Without capacity control there is no validation gate, and this artifact does not
publish an unvalidated simulation."* It has not failed. It has not been asked.

## Q2 — Distinct workers under concurrent load; genuine cold start or warm restart?

**Unanswered, and structurally unanswerable from the existing captures.**

All three recon captures landed on **the same worker**:

| fixture | `workerId` | `delayTime` (ms) | `executionTime` (ms) |
|---|---|---|---|
| `status_0.json` | `iiewfw59dqskoe` | 8,577 | 150,577 |
| `status_1.json` | `iiewfw59dqskoe` | 127 | 53,415 |
| `status_2.json` | `iiewfw59dqskoe` | 127 | 50,324 |

`fixtures/README.md` already states this ("all three runs landed on one worker").
The spec's §1 table attributes artifact 1's single-host result to serial
submission — *"artifact 1 submitted serially, so the platform never needed a
second worker"* — which is true and is not the whole reason. There are three
causes, and the committed record documents all of them:

1. **Serial submission.** One job in flight at a time.
2. **The endpoint caps at one worker.** Concurrency alone would not have
   produced a second; it would have produced a queue.
3. **Host affinity.** `docs/experiment.md` (H4) records that with `idleTimeout`
   at its 5 s minimum *"workers do terminate between runs, and RunPod still
   re-allocates the same physical machine because it has the image cached. Across
   27 runs of a discarded first window we observed 2 distinct hosts, one of them
   serving 23 runs."* For the three recon captures specifically,
   `fixtures/README.md` adds a fourth, narrower effect: they were submitted back
   to back inside the idle window, so the *container* survived between jobs —
   which is why runs 1 and 2 show a 0.3 s `torch.compile` against run 0's 39 s.

The third is the one that matters for Q2. Raising the cap and submitting
concurrently fixes causes 1 and 2, but host affinity means a driven scale-up may
still land on a host that already holds the image — which is precisely the
"warm-host restart" outcome §9 asks about. The capture protocol therefore has to
separate three things a single `workerId` conflates: a surviving **container**
(warm compile cache), a re-allocated **host** after termination (image cached,
container cold), and a genuinely **new host** (image pull visible in
`delayTime`).

Answering Q2 needs both: an endpoint with `max > 1`, and concurrent submission.
Neither exists in any committed capture.

Until it is answered, §10's confirmatory gate cannot be either kept or dropped —
it is conditional on exactly this. Note that the **primary** gate (open-loop
trace replay) survives regardless, needing only pinned capacity, which is Q1.

## Q3 — Where does the curve bend, and what binds concurrency first?

**Answered from existing data. KV does not bind at the pinned request shape;
`max_num_seqs` or compute binds first. The spec's conclusion stands — its
supporting number does not.**

The recon log reports, verbatim:

```
[gpu_worker.py:563]   Available KV cache memory: 4.92 GiB
[kv_cache_utils.py:2235] GPU KV cache size: 35,792 tokens
[kv_cache_utils.py:2236] Maximum concurrency for 8,192 tokens per request: 4.37x
```

That 4.37x is the figure for a request occupying the full `--max-model-len` of
8,192 tokens. It is **not** artifact 2's operating point. The spec (§5) pins the
request shape to artifact 1's exact one — `"Explain what a key-value cache does,
in two sentences."` at `max_tokens=16`, roughly 30 tokens — at which the same
cache admits ~1,190 concurrent requests, far above vLLM's `max_num_seqs` default
of 256. So KV is not the binding constraint, and the pilot sweep still has to
record which limit actually is.

Two corrections to how the spec states this.

**1. The cited cache size is arm-specific, and it is the larger of two.** §5
says "a measured 43,040-token cache". Artifact 1 measured *two* values across its
300 runs:

| arm | `engine.kv_capacity_tokens` | runs |
|---|---|---|
| A | 35,792 | 100 |
| B | 35,792 | 100 |
| C | **43,040** | 100 |

The spec quotes arm C's without saying so, which means its safety-margin
calculation uses the most favourable of the two. The conclusion is unaffected —
at ~30 tokens per request the arms admit ~1,190 and ~1,435 concurrent
respectively, and both are comfortably above 256 — but the margin is 20% smaller
than stated for two of the three arms. The recon fixture's 35,792 agrees with
arms A and B, not with the number the spec quotes.

**2. `max_num_seqs` is not in the captured log.** It appears zero times in
`fixtures/vllm_logs/startup_0.log`. The 256 default is asserted by the spec, not
observed here. The pilot sweep should record it rather than inherit the
assumption.

---

## A consequence for the replica model that is worth deciding before the sweep

Arm C's KV cache is **20% larger** than arm A's, measured, in artifact 1's own
data. The mechanism is not merely plausible — `fixtures/README.md` shows it on
a single worker. Between recon run 0 (cold `torch.compile`, 38.96 s) and runs 1–2
(warm, 0.30 s and 0.29 s), peak activation during vLLM's memory profiling fell
from 1.18 GiB to 0.19 GiB and the KV cache rose from 35,792 to 43,040 tokens —
the same two values artifact 1's arms A/B and C report. A cold compile holds
about a gigabyte of transient memory at the moment vLLM sizes the KV cache, and
that gigabyte is what arm C gets back.

Spec §6 models a replica as **absent or serving**, with the arms differing only
in cold-start lag, justified by "per-arm steady-state medians differ by 0.6 ms".
That justification was measured at concurrency 1, where KV cannot bind. If the
arms differ in KV capacity, they differ in *serving capacity*, not only in how
long they take to arrive — and artifact 2 is a simulation about capacity arriving
late.

At the pinned request shape this is almost certainly immaterial: ~1,190 versus
~1,435 concurrent, against a simulated per-replica concurrency in the low tens
and a `max_num_seqs` ceiling of 256 that binds first in both. It is recorded
here because it is a measured asymmetry between the two arms whose comparison is
the whole artifact, and "almost certainly immaterial" should be a written
judgement rather than an oversight.

## A small correction to `fixtures/README.md`, applied

It stated `gpu_memory_utilization` was "at the 0.9 default". The captured log
says otherwise:

```
Desired GPU memory utilization is (0.92, 21.64 GiB)
```

Immaterial to any published result, but it is the parameter that sets the KV
budget that Q3 turns on, so it should read correctly. Corrected in the same
commit as this document, with the old claim noted in place rather than silently
overwritten.

---

## What it would take to close the gate

One capture run, on an endpoint with `max > 1` — provisioned **new** rather
than by raising `ka5mryakkxumew`'s ceiling, so that artifact 1's endpoint stays
as its records describe:

1. Provision an endpoint with `max > 1`, `flashboot: false` (assert it after
   creation — it silently ignores `false` at create time), in a datacenter with
   verified 24GB stock. EU-RO-1 was the only one holding Medium stock in August;
   re-check, since `recon/README.md` documents that availability flaps. Its
   template must start `/opt/recon_handler.py`, not the image's default
   measurement handler, which rejects a recon job (`recon/README.md`, "Artifact
   2 capture"). Set `workersMin` to 0 and `idleTimeout` below 60 s — 5 s, its
   minimum, is recommended — or `recon/capture_a2.py`'s preflight refuses the
   endpoint: a standing worker stays warm between bursts and hides the cold
   start Q2 asks about, and an idle timeout no shorter than the 60 s wait
   between bursts could keep burst 1's containers alive into burst 2.
   `recon/capture_a2.py` automates steps 2–4.
2. Submit concurrently, enough to allow a second worker.
3. Record, per job: `workerId`, `delayTime`, `executionTime`, and the vLLM
   startup log. A person reads these off `recon/analyse_a2.py`'s table; no rule
   is fixed in advance, because the rule is what the capture is meant to
   inform. What each of Q2's three cases looks like:
   - a **surviving container**: warm compile cache, so the log's S4 skips
     compilation or keeps it short — recon runs 1–2's 0.3 s against run 0's
     39 s;
   - a **re-allocated host**: the image is cached but the container is cold, so
     the log shows a full S4 (weights load, compile, KV allocation) and
     `delayTime` shows no image pull;
   - a **new host**: a full S4, plus an image pull visible in `delayTime`.

   A full S4 alone therefore does not mark a genuine cold start, and a second
   distinct `workerId` alone does not separate the last two cases. A driven
   scale-up that lands only on re-allocated hosts is the "warm-host restart"
   outcome §9 asks about; what its table then does with the confirmatory gate,
   and the reason published, is decided there from what the capture shows.
4. Exercise scale-up and scale-down explicitly, timing acknowledgement against
   effect, to answer Q1.

Cost is in the same band as artifact 1's recon — the spec's §13 estimate of
$35–60 covers reconnaissance plus the sweep.

**Until this runs, `SERVICE_CURVE_PLACEHOLDER.measured` stays `False` and every
artifact 2 number is a demonstration that the machinery works, not a result.**
