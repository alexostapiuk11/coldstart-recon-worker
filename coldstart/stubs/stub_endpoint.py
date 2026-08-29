"""In-process stand-in for the RunPod endpoint. No network, no cost."""

import random
import uuid

from coldstart.cache_config import resolve
from coldstart.stubs.stub_engine import replay_log_lines

# Plausible ground truth in seconds. Values are arbitrary but ordered so the
# analysis has a known answer to recover.
ARM_PROFILE = {
    "A": {"t_weights": 95.0, "s4b": 40.0},
    "B": {"t_weights": 30.0, "s4b": 40.0},
    "C": {"t_weights": 30.0, "s4b": 3.0},
}

# Deliberate, non-zero gap between one request's completion and the next
# request's dispatch (driver-side round trip / scheduling overhead). If this
# were zero, t_dispatch_mono would equal the cumulative sum of prior end_to_end
# values, and the stub could no longer distinguish a real per-request offset
# from the summing inference metrics.t_fast_seconds refuses to make (B5) -- it
# would exercise the fix without ever being able to catch its regression.
WARMUP_DISPATCH_GAP = 0.05


class StubEndpoint:
    """In-process stand-in for the RunPod endpoint. No network, no cost."""

    def __init__(self, seed: int = 0, hosts: int = 6):
        self._rng = random.Random(seed)
        self._hosts = [f"host-{i}" for i in range(hosts)]
        self._seen: set[str] = set()

    def run(self, arm: str, run_id: str) -> dict:
        prof = ARM_PROFILE[arm]
        config = resolve(arm)
        jitter = self._rng.lognormvariate(0.0, 0.25)
        host = self._rng.choice(self._hosts)
        host_factor = 1.0 + 0.15 * self._hosts.index(host)

        t_weights = prof["t_weights"] * jitter * host_factor
        s4b = prof["s4b"] * jitter
        s1 = 4.0 * jitter
        s4_other = 25.0 * jitter
        # S5 is its own stage -- engine up to the health endpoint answering.
        # Collapsing it into S4 here would let the analysis fold S5 into the
        # bracket off-GPU with nothing to catch it.
        s5 = 6.0 * jitter
        t_platform = 18.0 * self._rng.lognormvariate(0.0, 0.4)

        t_s3_load_done = s1 + t_weights
        t_s4_end = t_s3_load_done + s4b + s4_other
        t_s5_ready = t_s4_end + s5

        steady = 2.0
        warmup = []
        t_dispatch = t_s5_ready  # request 1 dispatches the instant the server is ready
        for i in range(10):
            penalty = 1.0 + 2.0 * (0.55**i)
            e2e = steady * penalty
            warmup.append(
                {
                    "req_index": i,
                    "t_dispatch_mono": t_dispatch,
                    "ttft": e2e * 0.25,
                    "end_to_end": e2e,
                }
            )
            t_dispatch += e2e + WARMUP_DISPATCH_GAP * jitter

        first_touch = host not in self._seen
        self._seen.add(host)

        # Read back from the per-request offsets, never recomputed by summing
        # end_to_end -- that sum is the zero-gap assumption B5 exists to remove.
        t_first_token = warmup[0]["t_dispatch_mono"] + warmup[0]["ttft"]
        t_warmup_done = warmup[-1]["t_dispatch_mono"] + warmup[-1]["end_to_end"]

        marks = [
            {"stage": "S1_imports_done", "t_mono": s1},
            {"stage": "S2_acquisition_start", "t_mono": s1},
            {"stage": "S3_load_done", "t_mono": t_s3_load_done},
            # Device init begins the instant weights are resident, as in the probe.
            {"stage": "S4_start", "t_mono": t_s3_load_done},
            {"stage": "S4_end", "t_mono": t_s4_end},
            {"stage": "S5_ready", "t_mono": t_s5_ready},
            {"stage": "S6_request1_dispatch", "t_mono": warmup[0]["t_dispatch_mono"]},
            {"stage": "S6_first_token", "t_mono": t_first_token},
            {"stage": "S7_warmup_done", "t_mono": t_warmup_done},
        ]

        return {
            "job_id": str(uuid.uuid4()),
            "run_id": run_id,
            "arm": arm,
            "healthy": True,
            "log_lines": replay_log_lines(compile_warm=config.compile_cache_warm),
            "warmup": warmup,
            "clock_B": {"t0_wall": 0.0, "marks": marks},
            "host": {
                "host_id": host,
                "gpu_model": "stub",
                "driver_version": "0",
                "first_touch": first_touch,
            },
            # Same provenance the real handler returns, so a record assembled
            # from the stub has the same shape as one from a real run.
            "cache_config": {
                "arm": config.arm,
                "weights_source": config.weights_source,
                "compile_cache_warm": config.compile_cache_warm,
                "env": config.env(run_id),
            },
            "compile_cache_observed": config.compile_cache_warm,
            "synthetic_truth": {
                "t_weights": t_weights,
                # Matches derive()'s definition (t_process is the S6_first_token
                # mark), so the ground truth is the quantity the analysis
                # actually recovers rather than a differently-drawn boundary.
                "t_process": t_first_token,
                "t_platform": t_platform,
                "s4b": s4b,
            },
        }
