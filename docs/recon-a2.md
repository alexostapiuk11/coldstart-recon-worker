# Artifact 2 — reconnaissance record (spec §9)

**Date:** 2026-09-17
**Verdict: NOT YET DECIDABLE. Q1 and Q2 are unanswered, and cannot be answered
from any capture now in the repository.** Q3 is answered from existing data and
its answer stands.

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
   re-check, since `recon/README.md` documents that availability flaps.
2. Submit concurrently, enough to force a second worker.
3. Record, per job: `workerId`, `delayTime`, `executionTime`, and the vLLM
   startup log. A second *distinct* `workerId` whose log shows a full S4
   (weights load, compile, KV allocation) is a genuine cold start; one that skips
   those stages is a warm-host restart, and §9's table then drops the
   confirmatory gate and publishes the reason.
4. Exercise scale-up and scale-down explicitly, timing acknowledgement against
   effect, to answer Q1.

Cost is in the same band as artifact 1's recon — the spec's §13 estimate of
$35–60 covers reconnaissance plus the sweep.

**Until this runs, `SERVICE_CURVE_PLACEHOLDER.measured` stays `False` and every
artifact 2 number is a demonstration that the machinery works, not a result.**
