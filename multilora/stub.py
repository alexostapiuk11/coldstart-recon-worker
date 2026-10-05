"""A GPU-free stand-in for artifact 5's worker.

`StubInstanceEndpoint.run(payload)` returns exactly the payload shape the real
worker returns (see `multilora.records`), built from a small timing model with
a known registered-slot cost, a known heterogeneity cost and a known gauge
cost. Tests use it to check that the analysis recovers what was put in; the
figure scripts use it to lay out charts before any paid run. Nothing it
produces is data, and nothing in it is published.

Drive it through `harness.submit.PayloadStubSubmitter(endpoint.run)`. That is
the harness's GPU-free twin of `RunPodSubmitter.submit_payload`: it round-trips
payload and output through JSON as the real transport does, and records an
unhealthy engine as a failure exactly as the real submitter does. A second
stub submitter here would be one more copy of that decision to drift.
"""

import math
import random
from dataclasses import dataclass

from multilora.conditions import REAL, SPREAD, SYNTHETIC

OUTPUT_TOKENS = 16


@dataclass(frozen=True)
class StubModel:
    base_tps: float = 2400.0
    slot_cost_per_doubling: float = 0.01
    heterogeneity_per_doubling: float = 0.05
    specialize_recovers: float = 0.8
    gauge_cost_at_top: float = 0.01
    base_ttft_s: float = 0.08
    kv_tokens_at_one: int = 90_000
    kv_tokens_per_slot: int = 440
    cold_compile_kv_loss: int = 7_000
    cold_compile_every: int = 0
    fail_every: int = 0
    synthetic_bias: float = 0.0
    noise: float = 0.02


class StubInstanceEndpoint:
    def __init__(self, model: StubModel | None = None, seed: int = 0):
        self.model = model or StubModel()
        self.seed = seed
        self.calls = 0

    def _tps(self, regime, n_slots, n_active, specialize, stats_off, rng) -> float:
        m = self.model
        slot = m.slot_cost_per_doubling * math.log2(n_slots)
        if specialize:
            slot *= 1 - m.specialize_recovers
        tps = m.base_tps * (1 - slot)
        if regime in (SPREAD, REAL, SYNTHETIC):
            tps *= 1 - m.heterogeneity_per_doubling * math.log2(n_active)
            if not stats_off:
                tps *= 1 - m.gauge_cost_at_top * math.log2(n_active) / 6
        if regime == SYNTHETIC:
            tps *= 1 + m.synthetic_bias
        return tps * (1 + m.noise * rng.gauss(0.0, 1.0))

    def run(self, payload: dict) -> dict:
        self.calls += 1
        m = self.model
        rng = random.Random(self.seed * 1_000_003 + payload["run_index"])
        if m.fail_every and self.calls % m.fail_every == 0:
            return {"healthy": False, "log_lines": ["torch.OutOfMemoryError: CUDA out of memory"]}
        cold = bool(m.cold_compile_every) and self.calls % m.cold_compile_every == 0
        n_slots = payload["n_slots"]
        kv = m.kv_tokens_at_one - m.kv_tokens_per_slot * (n_slots - 1)
        if cold:
            kv -= m.cold_compile_kv_loss
        log = [
            "Initializing a V1 LLM engine (v0.27.1) with config: model='Qwen/Qwen3-4B'",
            f"torch.compile took {38.5 if cold else 0.3:.2f} s in total",
            f"GPU KV cache size: {kv:,} tokens",
        ]
        if cold:
            log.insert(1, "Using cache directory: /runpod-volume/vllm-cache/torch_compile_cache/"
                          f"stub{n_slots:03d}/rank_0_0/backbone")
        conc = payload["concurrency"]
        n_req = payload["requests_per_phase"]
        phases, samples = [], []
        for spec in payload["phases"]:
            n_active = min(len(spec["adapters"]), conc)
            tps = self._tps(
                spec["regime"], n_slots, n_active,
                payload["specialize_active_lora"], payload["disable_log_stats"], rng,
            )
            median_ttft = m.base_ttft_s * m.base_tps / tps
            ttfts = [median_ttft * math.exp(0.15 * rng.gauss(0.0, 1.0)) for _ in range(n_req)]
            phases.append({
                "phase_index": spec["phase_index"],
                "regime": spec["regime"],
                "adapters": spec["adapters"],
                "concurrency": conc,
                "num_requests": n_req,
                "duration_s": n_req * OUTPUT_TOKENS / tps,
                "completed": n_req,
                "failed": 0,
                "ttfts": ttfts,
                "output_lens": [OUTPUT_TOKENS] * n_req,
                "errors": [""] * n_req,
            })
            running = None if payload["disable_log_stats"] else sorted(spec["adapters"][:n_active])
            samples += [
                {"phase_index": spec["phase_index"], "t": float(i), "running": running}
                for i in range(3)
            ]
        return {
            "healthy": True,
            "log_lines": log,
            "served_cmd": ["vllm", "serve", "Qwen/Qwen3-4B", "--max-loras", str(n_slots)],
            "host": {"host_id": "stub-container", "gpu_model": "stub", "vcpus": 16},
            "adapters": {name: f"stub-{name}" for name in payload["registered"]},
            "phases": phases,
            "gauge_samples": samples,
        }
