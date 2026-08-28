# Reconnaissance captures

Captured 2026-08-28 against endpoint `ka5mryakkxumew`, GPU NVIDIA RTX 4090 (24 GB),
region EU-RO-1, image digest
`sha256:14b22033a8d65f230c3ca4df2b0e69500b57e3296dec3a7ca8b88548b628aa4f`,
vLLM 0.27.1, model `Qwen/Qwen3-8B` revision
`b968826d9c46dd6066d109eabc6255188de91218`, `--max-model-len 8192`,
`gpu_memory_utilization` at the 0.9 default.

Published as fixtures, not as results. Sample size is 3, all three runs landed on
one worker, and nothing here is a measurement of anything.

## Q1 — engine log format

All five S4 sub-stages are delineated. Lines are verbatim, with the
`(EngineCore pid=N) INFO <timestamp>` prefix stripped:

- **S4a device init:** `[gpu_worker.py:385] Using V2 Model Runner`, then
  `[model_runner.py:308] Loading model from scratch...` and
  `[cuda.py:482] Using FLASH_ATTN attention backend out of potential backends: [...]`
- **S4a weights:** `[default_loader.py:430] Loading weights took 34.35 seconds` and
  `[model_runner.py:329] Model loading took 15.27 GiB and 36.382166 seconds`.
  When weights are *not* already local, a further line appears first:
  `[weight_utils.py:530] Time spent downloading weights for <model>: 16.051640 seconds`
- **S4b compilation:** `[monitor.py:53] torch.compile took 38.96 s in total`, preceded by
  `[backends.py:1094] Using cache directory: /root/.cache/vllm/torch_compile_cache/<hash>/rank_0_0/backbone for vLLM's torch.compile`
- **S4c memory profiling:** `[monitor.py:81] Initial profiling/warmup run took 0.16 s`
- **S4d KV allocation:** `[gpu_worker.py:563] Available KV cache memory: 4.92 GiB` and
  `[kv_cache_utils.py:2235] GPU KV cache size: 35,792 tokens`
- **S4e graph capture:** `[model_runner.py:791] Graph capturing finished in 6 secs, took 0.56 GiB`
- **Summary:** `[core.py:348] init engine (profile, create kv cache, warmup model) took 53.73 s (compilation: 38.96 s)`

Sub-stages this version does not delineate: none of the five. All are separable.

**Two parser hazards.**

1. The weight-download line is *optional* — it is absent whenever weights are already
   on disk. A parser that requires it will fail on every warm run, which is most of
   arms B and C.
2. Roughly a sixth of all lines are tqdm progress bars carrying carriage returns, both
   `Loading safetensors checkpoint shards:  40% Completed | 2/5 [00:01<00:02, 1.11it/s]`
   and `Capturing CUDA graphs (PIECEWISE):  47%|...| 24/51 [00:00<00:00, 40.22it/s]`.
   These interleave with INFO lines and must be tolerated, not parsed.

## Q2 — platform API lifecycle fields

Fields present in the status payload: `delayTime`, `executionTime`, `id`, `status`,
`workerId`.

- queued-at exposed: **no** (only `delayTime`, a duration)
- started-at exposed: **no** (only `executionTime`, a duration)
- => residual **can** be split into queue vs execution, using durations rather than
  absolute timestamps.

`runpod_api.py`'s `FIELD_MAP` as specified in the plan (`delayTime` -> `delay_ms`,
`executionTime` -> `execution_ms`) is correct against these payloads.

## Q3 — compile-at-startup

Does this version compile at startup: **yes.**

```
[monitor.py:53]     torch.compile took 38.96 s in total
[backends.py:1094]  Using cache directory: /root/.cache/vllm/torch_compile_cache/905735a5a3/rank_0_0/backbone
[decorators.py:708] saved AOT compiled function to /root/.cache/vllm/torch_compile_cache/torch_aot_compile/<hash>/rank_0_0/model
```

Cache location observed: `/root/.cache/vllm/torch_compile_cache/` — container disk,
under `VLLM_CACHE_ROOT`.

=> **H3 and arm C: RETAINED.** The three-arm design stands.

Compilation is not a marginal cost. It is 38.96 s of a 53.73 s engine init, about 72%,
and the same ratio held on a 0.6B smoke run (19.37 s of 26.89 s). Arm C is plausibly
the largest single lever in the experiment.

## What these three runs accidentally demonstrated

All three jobs landed on worker `iiewfw59dqskoe`, because `idleTimeout` is 5 s and the
captures were submitted back to back. The container therefore survived between jobs,
and `VLLM_CACHE_ROOT` pointed at the container default rather than a per-run path:

| | run 0 | run 1 | run 2 |
|---|---|---|---|
| `torch.compile` | 38.96 s | 0.30 s | 0.29 s |
| Loading weights | 34.35 s | 3.97 s | 4.06 s |
| init engine | 53.73 s | 12.89 s | 9.46 s |
| GPU KV cache | 35,792 tok | 43,040 tok | 43,040 tok |
| peak activation | 1.18 GiB | 0.19 GiB | 0.19 GiB |

This is the spec's "compile cache leaking into a cold arm" risk, reproduced by accident.
`CacheConfig.env()` namespaces cold paths by `run_id` precisely to prevent it; the recon
handler does not apply `CacheConfig`, which is why it happened here. The Task 11 probe
must, and per-run engine-output verification is the detector.

**A compile is not only slow, it is also memory-expensive at profiling time.** Peak
activation is 1.18 GiB when compiling and 0.19 GiB on a cache hit, with every other
memory term identical. Inductor's autotuning workspace is live during the profiling
forward pass, so a cold compile shrinks the KV budget by ~1 GiB — 35,792 tokens versus
43,040, a 20% swing, which is the difference between 4 and 5 supported sequences at
8192. Arm C should therefore be expected to buy KV capacity as well as latency. The
spec does not currently predict this, and it is worth stating as a hypothesis rather
than a result: n=1 per condition here, and confounded by worker reuse.

## Known gaps in these fixtures

- **No cold weight-download log for 8B.** All three runs found weights already staged
  on the volume, so none carries the `Time spent downloading weights` line. The pattern
  above was taken from the 0.6B smoke capture and from a failed 8B run. Arm A produces
  this line on every run, so the Task 7 parser needs a fixture that has it.
- **No genuinely cold container.** Runs 1 and 2 reused a warm worker. There is no
  capture here of a second *cold* start.
