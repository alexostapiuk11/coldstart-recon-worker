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
