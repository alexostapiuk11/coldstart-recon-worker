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
