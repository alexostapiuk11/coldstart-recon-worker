# Artifact 4 — reconnaissance record

Run on 2026-10-05. Every figure below is read from a capture in
`fixtures/a4/recon/`, saved verbatim by `scripts/a4_recon_capture.py`, or from
`fixtures/a4/recon-report.json`, which `scripts/a4_recon_report.py` computes from
those captures. Captures that did not answer their question are kept in
`fixtures/a4/recon-failed/` and are not counted (section 9).

## 1. Image, endpoint and spend

- **Image:** `ghcr.io/alexostapiuk11/coldstart-recon-worker@sha256:d8bc338a2bc7694c62ec615fd5dde927dbc03d0047a927212023151e5a9046d0`.
  The image's `org.opencontainers.image.revision` label reads
  `91e760dea2bbcae73a6c102aadbeb8f531573a0b`, so it was built from that commit,
  which has the replay and sleep job kinds. Base: `vllm/vllm-openai:v0.27.1`
  (CUDA 13.0.2), the digest pinned in `worker/Dockerfile`.
- **Template** `fru0y0r3a0`, **endpoint** `nnypnh9drkq5ux`: RTX 4090, EU-RO-1,
  network volume `9c7ut2slrd`, `workersMin` 0, `workersMax` 1, idle timeout
  5 s, execution timeout 1,800,000 ms, FlashBoot off. FlashBoot is not in the
  pin set; it was set off at provisioning and read back, as artifact 1's
  endpoint has it. `allowedCudaVersions` is `["13.0"]`, set during the run (section 9).
- **Volume:** the run enlarged `9c7ut2slrd` from 50 GB to 100 GB. The first
  `stage` hit `Disk quota exceeded` on the two checkpoints that did not fit.
- **Execution time, from the captures' `clock_C`:** the eight answering jobs
  ran 1,257 s in total; the three discarded attempts ran another 163 s.
  Queue and cold-start waits (`delay_ms`) are separate and whether they are
  billed was not established.
- **Spend, from RunPod's billing API** (`GET /v1/billing/endpoints` for endpoint
  `nnypnh9drkq5ux`, read 2026-10-05 after the last job): **$0.4988 for 1,623.2 s
  billed**, in three hourly buckets (06:00 UTC $0.0464, 07:00 $0.1979, 08:00
  $0.2544), with 720 disk GB-units billed for the day, as the API reports them.
  That covers all eleven submissions, the three discarded ones included. Billed
  time is 1,623 s against 1,420 s of execution in the captures, so some start-up
  time is billed and the queue waits are probably not; this was not separated.
  The implied rate is $0.000307 per second, $1.106 per hour. Step 2 registered
  $1.1095 per hour, from an earlier partial read of the same record
  (`placement/registered.py`); the 0.3% difference is not a reason to change a
  registered value, and the campaigns' own spend is read from the same record.
  The network volume's storage charge is separate and not in this figure.

## 2. Go/no-go (`coresidency-primary`, `coresidency-fallback`)

Two engines at `--gpu-memory-utilization 0.45`, `--max-model-len 2048`. The
criterion is both healthy and each logged KV capacity at least 16,384 tokens
(8 x T_max).

| Pair | Healthy | KV capacity, engines A and B | Result |
|---|---|---|---|
| Primary: Qwen3-4B + Qwen3-4B-Base | both | 9,456 and 9,520 tokens | **fail** |
| Fallback: Qwen3-1.7B + Qwen3-1.7B | both | 55,104 and 64,976 tokens | **pass** |

The pre-registered rule applies: the model class is **Qwen3-1.7B**
(`docs/experiment-a4.md`, "The go/no-go"). The change is a pre-registered branch,
not an amendment.

## 3. Compile reuse (`swaps-compile`, `swaps-cache`)

Because the class is the fallback, the swap jobs were rebuilt for it
(`--model-class fallback`, commit `dcd528c`): each swaps Qwen3-1.7B against
itself. The 4B family was not swapped.

- In `swaps-compile`, the first engine compiled (S4b 25.14 s). All four
  swap-ins were cache hits (S4b 0.15, 0.17, 0.16 and 0.15 s).
- In `swaps-cache`, all four swap-ins were cache hits (S4b 0.18, 0.15, 0.16 and
  0.15 s).
- Later jobs on other hosts compiled on their first engine in about 35.5 s
  (`early-start`, `sleep`), so the compile time varies by host. No rule depends
  on that figure, only on whether a swap-in is a hit.
- **Not answered:** whether same-architecture checkpoints share the compile
  cache across `rope_theta`. That question needs the 4B family, which the class
  change made unnecessary: step 2's validation set for this class is three
  tenants of one checkpoint. `compile_shared` is true in the report only because
  every swap here was a same-checkpoint swap.

## 4. Page cache (`swaps-cache`)

- `drop_caches` failed on both cold swaps: `Read-only file system`.
- `fadvise` succeeded on both. `Cached:` fell by 3,360,168 and 3,360,180 KiB,
  about 3.20 GiB.
- The pre-registered rule needs a drop of at least 0.5 of one 4B checkpoint's
  weights, 0.5 x 7.49 GiB, about 3.75 GiB. The drop is short of it, so
  **page-cache eviction does not work** under the rule, and the swap campaign is
  warm only: a stated limit.
- The Qwen3-1.7B checkpoint is 3.78 GiB, so `fadvise` on its files could clear
  the threshold only by evicting nearly all of it. The result reflects the
  fixed threshold and the fallback checkpoint's size; it does not show that
  eviction cannot work on a 4B checkpoint, which was not run.
- Swap times: warm 33.29 and 28.98 s; cold 32.75 and 32.74 s. Eviction made no
  visible difference here.
- The simulator draws from warm swaps whose incoming engine hit the compile
  cache (amendment §5): the six values in section 7.

## 5. Memory release and early start (`swaps-cache`, `swaps-compile`, `early-start`)

- Memory was released at the first poll in all eight swaps: median 0.021 s,
  maximum 0.022 s. None went unreleased.
- `early-start`: with the first engine torn down (0.87 s), the card read 510 MiB
  (the idle level), and the second engine came up healthy. A successor does not
  have to wait for anything beyond the first engine's exit.

## 6. Sleep mode (`sleep`)

- Works: sleep, `is_sleeping`, the second engine's start and sleep, wake, and a
  completion after the wake all returned 200.
- Sleep took 4.92 s for the first engine and 4.60 s for the second; wake took
  0.70 s.
- With one engine asleep the card read 2,069 MiB in use, against 20,081 MiB awake.
  The host memory a sleeping engine holds was not measured, so sleep is
  **reported beside the crossover and never simulated** (amendment §6, decision 9).

## 7. What plan 3 now has

`placement.step2.measurement_design(report)` reads the report with no
`NotDecidable` stop:

| Item | Value |
|---|---|
| Model class | Qwen/Qwen3-1.7B |
| Request shape | 1,792 input and 256 output tokens, split ceiling of 26 requests |
| KV capacity | 55,104 tokens at the split; 168,464 solo (warm compile cache), so a solo ceiling of 82 |
| Own levels | 1, 2, 4, 8, 16, 32, 64 |
| Neighbour levels | 0, 16, 32, 64 |
| Solo levels | 1, 2, 4, 8, 16, 32, 64, 128 |
| Held-out cells | `pair:o24:n48`, `pair:o48:n24` |
| Validation set | three tenants of Qwen3-1.7B |
| Swap campaign | warm only; one pair (the checkpoint to itself); 16 repeats |
| Sleep campaign | measured, 8 repeats, never simulated |
| Provisional swap samples for the screen | 33.29, 28.98, 35.07, 28.73, 28.98, 28.72 s |

## 8. Decisions for the owner

- **Console spend and GPU rate** for this run (section 1).
- **Artifact 5's base model.** The model class changed to the fallback, so
  artifact 5's base model changes with it (amendment §11). That is a message to
  artifact 5's session, not an edit to its files.
- **Eviction.** The threshold cannot be met on the 3.78 GiB fallback checkpoint
  by `fadvise`, so the cold-swap arm is dropped by rule. A different threshold
  would be an amendment.
- **Pin set.** FlashBoot (off) and `allowedCudaVersions` (`["13.0"]`) are set on
  the endpoint but not in `placement_measure/pins.py`, so the preflight cannot
  catch either drifting.
- The bursty-regime sizing gap (amendment §14) was decided on 2026-10-04 and is
  recorded in `docs/experiment-a4.md`; reconnaissance did not contradict it.

## 9. Attempts that did not answer, kept as evidence

- `recon-failed/stage.json`: the first `stage`. Three of five checkpoints
  staged, two failed with `Disk quota exceeded` (50 GB volume). The job returned
  `ok` and its payload said `complete: false`. Re-run after the volume was
  enlarged to 100 GB; the capture in `recon/` has `complete: true` and all five
  checkpoints.
- `recon-failed/early-start.json` and `early-start-attempt2.json`: both engines
  failed to start on host `d8fh7jv9yagn74` with CUDA `Error 804: forward
  compatibility was attempted on non supported HW`. The base image needs a
  driver that supports CUDA 13.0 (its `NVIDIA_REQUIRE_CUDA` is `cuda>=13.0`
  with legacy driver branches), and that host's did not. The report would have
  read these as "early start: no". After `allowedCudaVersions` was set to
  `["13.0"]`, the third attempt ran on `br0rhshc7qnros` and answered.
- Hosts seen: `6vj93wgksg0tiz` (help, stage, both co-residency jobs, both swap
  jobs), `br0rhshc7qnros` (early-start), `tc78a2607a7lhr` (sleep).
- The capture script prints `ok` when a job returns, whether or not its probe
  answered. Every capture was read before it was relied on.
