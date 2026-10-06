# Artifact 4 — Pre-registration

Committed in two dated steps, because reconnaissance is itself a paid run and
the request shape depends on what it reports (scope amendment §3). The git
timestamp on each step's commit is the evidence that its values were fixed before the
data they govern existed. `placement_measure/prereg.py` holds step 1's values
as code, and `tests/test_placement_measure_prereg.py` fails if it and this
document disagree.

## Step 1 — fixed before reconnaissance

### Configuration

- **GPU:** `NVIDIA GeForce RTX 4090`, 24 GB, the same class as artifacts 1 and 2.
  Network volume `9c7ut2slrd`; weights are read from it (`HF_HOME=/runpod-volume/hf`).
- **Engine:** vLLM `0.27.1`, base image
  `sha256:0a51ea5b4ae2dc5d81890e5173f54203d2a3ae0cfffe51b8fd2afd4391bfd967`
  (`worker/Dockerfile`'s `ARG VLLM_DIGEST`). The built image's digest is
  recorded in the reconnaissance record, since it is built after this step.
- **Primary model:** `Qwen/Qwen3-4B` at revision `1cfa9a7208912126459214e8b04321603b3df60c`.
  It is also artifact 5's base model (scope amendment, decision 1).
- **Fallback model:** `Qwen/Qwen3-1.7B` at revision `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e`.
- **Candidates for the validation set**, each pinned to the commit its `main`
  pointed at on 2026-10-04:

| Checkpoint | Revision |
|---|---|
| `Qwen/Qwen3-4B` | `1cfa9a7208912126459214e8b04321603b3df60c` |
| `Qwen/Qwen3-4B-Base` | `906bfd4b4dc7f14ee4320094d8b41684abff8539` |
| `Qwen/Qwen3-4B-Instruct-2507` | `cdbee75f17c01a7cc42f958dc650907174af0554` |
| `Qwen/Qwen3-4B-Thinking-2507` | `768f209d9ea81521153ed38c47d515654e938aea` |
| `Qwen/Qwen3-1.7B` | `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e` |

- **Per-request token ceiling:** T_max = `2048`. Every engine runs with
  `--max-model-len 2048`, `--max-num-seqs 256` and `--no-enable-prefix-caching`.
- **Memory:** `--gpu-memory-utilization 0.45` for each of two co-resident
  engines; `0.92` for a lone engine (artifact 1's measured budget); `0.80` for
  each engine in the sleep-mode probe.

### The go/no-go

The model class passes if, with two engines co-resident at `0.45` each, both
reach `/health` and each engine's logged KV capacity is at least `16,384`
tokens (8 × T_max).

- If the primary pair passes, the model class is Qwen3-4B.
- If it fails and the fallback pair passes, the model class is Qwen3-1.7B, and
  the change is recorded in the reconnaissance record.
- If both fail, the design changes rather than the measurement: stop, and
  return to the scope amendment (§3).

`placement_measure/recon_report.py` applies this criterion to the capture; it
does not choose it.

### Swap measurement conditions

- Engines start with `HF_HUB_OFFLINE=1`, so a missing checkpoint fails the
  engine instead of being downloaded during a timed swap.
- A swap's duration is teardown (the engine process exiting) plus memory
  release plus the successor's bring-up to `/health`.
- Memory is released when `memory.used` reads at most the idle level plus
  `512` MiB. The wait gives up after `120` s and records that it did.

### What step 2 fixes, after reconnaissance

The request shape (input and output length, at or below T_max), the
validation checkpoint set, N, the Zipf grid, both locality regimes'
parameters, the offered load, the SLO, the hot-model threshold, the sizing and
pairing rules, the warm-up window, the repetition count, the run-length pilot
rule, the interference grid, the swap campaign's pairs and cache states, and
the validation tolerance construction (scope amendment §12). It also records
the owner's decision on the bursty-regime sizing gap (scope amendment §14).
Step 2 is itself committed in two parts, below: its rules, then its values.

## Step 2, part 1 — rules, fixed before reconnaissance's answers are read

Every value step 2 needs is fixed here as a rule, so that once reconnaissance
reports, the values follow mechanically. `placement/step2.py` holds these rules
as code, and `tests/test_placement_step2_doc.py` fails if it and this section
disagree. A rule whose input reconnaissance did not answer stops the
experiment for the owner's decision; nothing defaults.

### The owner's decision on scope amendment §14

Decided 2026-10-04: in the bursty regime, the hot-model rule and dedicate's
fleet size are set on each model's ON-period load, its average divided by the
duty (`peak_factor` 1 / duty). In the spread regime they use the average. It
remains one rule, applied identically to all three strategies.

### Model class and request shape

- **Model class:** the primary if its go/no-go passed; otherwise the fallback
  if its go/no-go passed; otherwise stop.
- **Output length:** fixed at `256` tokens per request, with `ignore_eos`.
- **Total length:** the shortest of `512`, `1024`, `1536`, `2048` tokens at
  which the split engine's logged KV capacity, divided by the total, is at most
  `32` requests. Input length is the total minus the output length. If even
  T_max leaves 256 or more requests, the KV split cannot bind and the
  experiment stops (scope amendment §4).
- **KV readings used:** the split capacity is the smaller of the two
  co-resident engines'. The solo capacity is the smallest reading of the
  measured checkpoint at full memory with a compile-cache hit; with none, the
  solo grid spans the full range.

### The measurement campaigns

- **Grids:** concurrency levels 1, 2, 4, ... up to the first at least `1.5`
  times the KV ceiling (capacity divided by total length), capped at 256. The
  co-located grid uses the split ceiling for its own levels, and its neighbour
  levels are 0 (idle) and the top three own levels. The solo grid uses the solo
  ceiling.
- **Neighbour checkpoint:** `Qwen/Qwen3-4B-Base` for the 4B class; a second
  engine of `Qwen/Qwen3-1.7B` for the fallback.
- **Held-out cells:** two cells between grid points, never used to build the
  surface, each value rounded down: own 1.5 times the third-from-top own level with neighbour 1.5 times
  the third neighbour level, and own 1.5 times the second-from-top own level
  with neighbour 1.5 times the second neighbour level.
- **Repeats:** each cell `4` times, interleaved; a cell needs `3` valid
  repeats. A run is valid only if its measured engine read the compile cache
  (`S4b` at most 5 s), because compile state moves KV capacity.
- **Compile sharing:** shared if every swap-in in reconnaissance's compile
  probe hit the cache.
- **Validation set:** `Qwen/Qwen3-4B`, `Qwen/Qwen3-4B-Base` and
  `Qwen/Qwen3-4B-Instruct-2507` if the class is 4B and compile is shared;
  otherwise three tenants of the measured checkpoint.
- **Swap campaign:** every ordered pair of distinct checkpoints in the
  validation set (or the one checkpoint swapped to itself), with
  `16` swaps per cache state in total, rounded up per pair.
- **Page-cache eviction works** if, in every cold swap reconnaissance ran, a
  method succeeded and the kernel's `Cached:` figure fell by at least `0.5` of
  one 4B checkpoint's weights. Then swaps are measured cold and warm, and the
  simulator and validation use cold swaps; otherwise warm only, and this is a
  stated limit.
- **Simulated swaps:** drawn from the measured swaps in the simulated cache
  state whose incoming engine hit the compile cache.
- **Sleep mode:** measured `8` times if reconnaissance found it working, and
  reported beside the crossover. It is never simulated: that needs the host
  memory a sleeping model holds, which reconnaissance does not measure (scope
  amendment §6).

### The simulated design

- **Fleet:** N = `20` models; Zipf skews `0.6, 0.8, 1.0, 1.25, 1.5, 2.0`; both
  locality regimes; hot-model fraction `0.7`; warm-up `300` s; bursty mean
  burst `120` s at duty `0.2`; `30` repetitions; run length from the pilot
  rule with `1200` pilot traces; seed `20261004`.
- **Sizing and pairing:** as scope amendment §7, with the §14 decision above.
- **Offered load and SLO:** chosen by a ranking-blind screen from offered loads
  of `4.0`, `2.0` and `1.0` GPUs of saturation and SLOs of `1.0`, `2.0` and
  `4.0` times the simulated swap's median. The screen runs `5` repetitions on
  seed `20261005`, on provisional inputs: the placeholder engines and
  reconnaissance's own swap times. Each evaluable grid point scores the number
  of distinct sized fleets among the three strategies, minus one (0 to 2); a
  candidate's score is the sum. It never looks at which strategy is cheaper.
  The highest score wins; a tie goes to the earlier candidate, offered load
  first, then the tighter SLO, in the order listed.
- **Artifact 5's reference point:** the bursty regime at s = `1.0`.

### The validation gate

- **Trace:** the validation set's three tenants at Zipf s = `1.0`, bursty with
  mean burst `180` s at duty `0.25`, offered at `0.3` of the measured solo
  saturation over a `900` s window. The driver caps requests in flight at the
  solo curve's top measured concurrency.
- **Draw:** the first of seeds `4104` to `4123`, in order, whose replay is
  feasible. Feasible means that the simulator, replaying the draw as the
  prediction below does, finishes its last request within `1200` s, leaves at
  least `10` bins with a median, and swaps at least `4` times. The check runs on
  the measured curve and swaps, before any replay, and reads only predicted
  feasibility, never a verdict. If no draw is feasible, the gate cannot run as
  registered and the owner decides.
- **Band:** exactly `3` real repeats of that one trace, binned at `30` s by
  scheduled arrival. A request counts as unfinished if its scheduled arrival
  plus its latency is past the window, the clock the prediction uses. A repeat
  whose arrivals lag the schedule by more than `0.5` s is refused.
- **Prediction:** the simulator replays the same trace on one GPU holding the
  first tenant, with the solo curve, and every swap at the median of the
  measured swaps in the validation's cache state plus the median page-cache
  eviction, which a cold replay pays before every swap-in and a fleet does not.
- **Pass rule:** at least `10` judged bins, at most `0.5` of them missing,
  band edges widened by `0.001` s (`autoscale/validation_band.py`). The
  predicted swap count must also lie within the real repeats' range, widened by
  `1` either side.
- **Interference check:** each held-out cell passes if the surface's
  prediction lies inside its repeats' range or within `0.1` of their median.
  A failure is reported against the co-locate strategy, not hidden.

## Step 2, part 2 — values, fixed before the first measurement run

Committed 2026-10-05. Every value below is the rules of part 1 applied to
`fixtures/a4/recon-report.json` and `data/a4/screen.json`;
`placement/registered.py` holds them as code, and
`tests/test_placement_registered.py` re-derives them.

- **Model class:** `Qwen/Qwen3-1.7B`.
- **Request shape:** `1792` input and `256` output tokens.
- **KV capacity:** split `55,104` tokens, ceiling `26` requests; solo `168,464` tokens, ceiling `82`.
- **Co-located grid:** own levels `(1, 2, 4, 8, 16, 32, 64)`, neighbour levels `(0, 16, 32, 64)`; held-out cells `('pair:o24:n48', 'pair:o48:n24')`.
- **Solo grid:** `(1, 2, 4, 8, 16, 32, 64, 128)`.
- **Every swap-in in reconnaissance hit the compile cache:** `True`. This covers only the swaps reconnaissance ran; for the fallback class that is the one checkpoint swapped to itself, so it says nothing about other checkpoints.
- **Page-cache eviction works:** `False`; swaps measured warm.
- **Sleep-mode arm measured:** `True`.
- **Validation set:** `('Qwen/Qwen3-1.7B', 'Qwen/Qwen3-1.7B', 'Qwen/Qwen3-1.7B')`.
- **Swap campaign:** Qwen/Qwen3-1.7B to Qwen/Qwen3-1.7B; `16` repeats per pair and state.
- **Screen's choice:** offered load `1.0` GPUs of saturation; SLO `2.0` times the simulated swap's median.
- **GPU hourly rate:** `1.1095` dollars, derived from RunPod's billing API for endpoint nnypnh9drkq5ux (GET /v1/billing/endpoints: $0.2443519 for 792.879 s billed, $0.000308 per second), read 2026-10-05. Artifact 5 reads the same rate from here.

## Amendment, 2026-10-05: the co-located pair's KV memory is pinned

Drafted after the first cell runs failed and before any valid co-located
measurement exists. **It binds only once the owner has signed it off**, and the
cell campaign resumes only after that. Signed off by the owner on 2026-10-05,
after the probe result below.

**Changed:** for the co-located pair in the cell campaign, both engines now also
run with `--kv-cache-memory-bytes` set to `6,319,767,552` (`placement_measure.prereg.SPLIT_KV_BYTES`).
Nothing else about the pair changes: `--gpu-memory-utilization 0.45` for each
engine, the other flags, and solo engines (`0.92`, no pin) are as registered.

**Why.** Two of the three co-located runs the campaign made failed with the same
error, and the third succeeded only because its measured engine compiled:

| Run | Condition | Measured engine | Neighbour engine | Result |
|---|---|---|---|---|
| 0 | `pair:o16:n32` | compiled (S4b 20.21 s), KV 55,104 | cache hit (0.38 s), KV 64,880 | ok |
| 1 | `pair:o32:n0` | cache hit (0.11 s), KV 64,880 | cache hit (0.12 s) | neighbour: CUDA out of memory |
| 3 | `pair:o2:n16` | cache hit (0.12 s), KV 64,976 | cache hit (0.11 s) | neighbour: CUDA out of memory |

In both failures the first engine held 11.84 GiB, the second reached 11.16 GiB
with 0.5 GiB belonging to the worker, and the card (23.52 GiB) had 15 MiB free
when the second engine's CUDA-graph capture asked for 20 MiB more. An engine
that hits the compile cache is given about 64,900 tokens of KV where one that
compiles is given 55,104; two engines at `0.45` fit when one compiles and do not
when both hit. Reconnaissance's fallback pair fit for the same reason (engine A
compiled, 25.1 s, KV 55,104; engine B hit, 0.15 s, KV 64,976;
`fixtures/a4/recon/coresidency-fallback.json`).

Step 2 requires a valid run's measured engine to read the compile cache (`S4b`
at most 5 s), so a valid co-located run needs both engines warm, which is the
case that does not fit. Left as registered, nearly every co-located cell would
fail or be invalid.

**What stays the same.** The registered split KV of `55,104` tokens (ceiling 26,
request shape 1,792 + 256) is the compiled engine's reading, and the pin is the
amount of KV memory that holds exactly that, `3,444` blocks of `16` tokens at
`114,688` bytes of KV per token for Qwen3-1.7B (28 layers, 8 KV heads, head
dimension 128, two bytes, K and V). No registered value in "Step 2, part 2"
changes. The compile-cache validity rule is unchanged. Reconnaissance's go/no-go
ran at `0.45` without the pin and is not re-run.

**Confirmation before the campaign resumes.** `data/a4/kvpin-probe.jsonl` holds
three repeats of `pair:o2:n16` run with the pin (design
`data/a4/designs/kvpin-probe.json`, seed 4199). It confirms the amendment if, in
every run where both engines read the compile cache (`S4b` at most 5 s, at least
two runs), the run is ok, both engines are healthy, and each logs a KV capacity
of exactly `55,104` tokens. If the engines log a different capacity, the byte
value is changed to the one that logs `55,104` and this section is amended
before the campaign resumes. The first run on a fresh worker compiles and is not
counted.

**Probe result (2026-10-05).** All three repeats were ok, on host `lmhp8rvl4z1boc`.
In every run both engines were healthy and logged `55,104` tokens of KV. Runs 1
and 2 are the counted ones (both engines read the compile cache: `S4b` 0.13 and
0.10 s, then 0.11 and 0.12 s): the case that failed twice without the pin. Run 0
compiled its measured engine (17.18 s) and is not counted, but it also logged
`55,104` on both engines. Each run completed all 100 measured requests with none
failed, the neighbour held its level of 16 (median 16 running), and the median
end-to-end latency was 3.1 s in all three. The criterion is met; the byte value
stands.

## Amendment, 2026-10-06 (validity): a neighbour above one engine's capacity counts when it sat at capacity

Made after the cell campaign ran and before any analysis of it. The owner
approved the change on 2026-10-06.

**Changed:** step 2's validity rule for a co-located cell required the neighbour
engine to reach its level (`vllm:num_requests_running` at least the level)
before the measured run. A neighbour level above the capacity of one engine can
never meet that, so for such a level the cell now counts as valid if the ramp
ended with at least `26` requests running (`placement.registered.SPLIT_CEILING`)
and the median running count through the measured run was at least `26`, with
the rest queued. A level at or below `26` must still reach its level, and a
neighbour that ran out of prompts during the measured run still invalidates the
cell. Nothing else in the rule changes.

**Why.** With each engine pinned to the registered split KV (55,104 tokens), at
most about 27 requests of 2,048 tokens run at once, and vLLM queues the rest. Of
the 152 stored cell runs, the neighbour reached its level in 27, and in 49 more
it sat at 26 to 28 running with the rest queued while the rule called it
"never reached". Where the neighbour sat at capacity, latency was the same
whatever the level above it, which is what a saturated neighbour should give:
own 16, 6.36 s at neighbour 32 and 6.34 s at 64; own 64, 18.76 s and 18.67 s.
Neighbour levels 32 and 64 are therefore the same load in effect, and the grid
keeps both. On the stored cell runs this rule makes 98 of the 152 records
valid, from 81.

## Amendment, 2026-10-06 (ramp window): the neighbour's ramp wait can be lengthened

Made after the cell campaign and before any analysis of it. The owner approved
the approach on 2026-10-06; the cell list below needs the owner's confirmation
before it runs.

**Changed:** a cell design may set `ramp_timeout_s`, how long to wait for the
neighbour to reach its load before the measured run starts. The default stays
`60` s, is not sent, and leaves every committed design's payload unchanged.

**Why.** In every cell whose neighbour had 4,032 or more prompts to send, the
ramp ended at 60 s with nothing running, and the neighbour only started during
the measured run, so the first part of that run was measured against no
neighbour. In the cells with 2,688 prompts the neighbour was running by 34 to
60 s. The 60 s wait is shorter than the load generator needs to prepare the
larger prompt sets. This is the probable cause, not yet confirmed.

**Confirmation and re-run.** One run of `pair:o1:n64` with `ramp_timeout_s` 600
(`data/a4/designs/ramp-probe.json`, seed 4299, into `data/a4/ramp-probe.jsonl`)
confirms the cause: with the longer window the neighbour was at capacity when
the ramp ended (28 running), stayed there (median 27, minimum 25), and the run
completed 100 of 100 requests, so it is valid under the validity amendment. It
cannot give the ramp time: for a neighbour level above one engine's capacity the
wait polls for the full level, which is never reached, so it always runs the
whole window. The probe therefore does not count toward any cell and the window
is set another way, which replaces "twice the observed ramp time".

The one reading of how long a neighbour takes to start is the pre-register's own
stored data: with 2,688 neighbour prompts the neighbour was running by 34 s,
about 79 prompts per second. That predicts about 84 s for 6,656 prompts, 166 s
for 13,056 and 327 s for 25,856. The re-run uses twice those times, rounded to
a whole number of 30 s and capped at 600 s, in three designs, four repeats
each, into one store each (the cells still short of three valid repeats under
the validity amendment, eleven cells and 44 runs; their earlier runs stay in
the store as evidence and do not count):
- `data/a4/designs/cells-ramp-1a.json`, window 180 s, into
  `data/a4/cells-ramp-1a.jsonl`: `pair:o1:n16`, `pair:o2:n32`, `pair:o4:n64`,
  `pair:o8:n64`, `pair:o16:n64`, `pair:o24:n48`, `pair:o32:n64`, `pair:o64:n64`
  (at most 6,656 neighbour prompts);
- `data/a4/designs/cells-ramp-1b.json`, window 360 s, into
  `data/a4/cells-ramp-1b.jsonl`: `pair:o1:n32`, `pair:o2:n64` (12,928 and 13,056
  prompts);
- `data/a4/designs/cells-ramp-1c.json`, window 600 s, into
  `data/a4/cells-ramp-1c.jsonl`: `pair:o1:n64` (25,856 prompts).

A run whose neighbour is still not at capacity when its ramp ends is invalid
under the validity amendment, so a window that proves too short shows up as
short cells, not as a wrong number.
