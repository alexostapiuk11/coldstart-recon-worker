"""The pre-registered parameters, as one validated object.

Every analysis and every job payload takes a `Preregistration` rather than
reading module constants, so the values that fix the experiment live in one
place: `multilora/prereg_values.py`, committed with `docs/experiment-a5.md`
before the first paid run. The git timestamp on that pair is the evidence the
values were fixed in advance.

The defaulted fields below are fixed by the approved design (amendment §4) and
are not expected to change. The others are fixed after reconnaissance.
"""

import math
from dataclasses import dataclass, fields

from harness.stats import MIN_BOOTSTRAP_SAMPLES, MIN_SAMPLES


@dataclass(frozen=True)
class Preregistration:
    concurrency: int  # C, amendment §3e
    rank: int  # r, also max_lora_rank, amendment §3a
    target_modules: tuple[str, ...]
    gate_adapters: int  # G, amendment §4
    warmup_requests_per_adapter: int  # [w], amendment §4
    scrape_interval_s: float  # amendment §3a
    knee_threshold: float  # tau, a fraction of throughput per doubling, amendment §4
    request_tokens: int  # prompt + output tokens at the inherited request shape
    context_length_tokens: int  # the production context length, amendment §3c
    slo_ttft_p95_s: float
    requests_per_tenant_month: float
    peak_to_average: float
    gpu_hourly_rate: float  # taken from artifact 4's committed assumptions
    schedule_seed: int
    include_diagnostic: bool  # amendment §3b; cut first if budget binds
    include_control: bool  # amendment §3a; cut before the diagnostic
    bench_dataset_args: tuple[str, ...]  # the inherited request shape, as bench serve arguments
    real_adapters: tuple[tuple[str, str], ...]  # (repo id, revision) per real gate adapter
    sweep: tuple[int, ...] = (1, 2, 4, 8, 16, 32, 64)
    concentrated_k: int = 1
    instances_per_condition: int = 24
    phases_per_regime: int = 2
    diagnostic_points: tuple[int, ...] = (1, 16, 64)
    control_point: int = 64
    gate_instances: int = 24  # Amendment 1: the gate's own size

    def __post_init__(self) -> None:
        positive_ints = {
            "concurrency": self.concurrency,
            "rank": self.rank,
            "gate_adapters": self.gate_adapters,
            "warmup_requests_per_adapter": self.warmup_requests_per_adapter,
            "request_tokens": self.request_tokens,
            "context_length_tokens": self.context_length_tokens,
            "concentrated_k": self.concentrated_k,
            "phases_per_regime": self.phases_per_regime,
        }
        for name, value in positive_ints.items():
            if not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive int, got {value!r}")
        positive_floats = {
            "scrape_interval_s": self.scrape_interval_s,
            "slo_ttft_p95_s": self.slo_ttft_p95_s,
            "requests_per_tenant_month": self.requests_per_tenant_month,
            "peak_to_average": self.peak_to_average,
            "gpu_hourly_rate": self.gpu_hourly_rate,
        }
        for name, value in positive_floats.items():
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive, got {value!r}")
        if not 0.0 < self.knee_threshold < 1.0:
            raise ValueError(f"knee_threshold must be in (0, 1), got {self.knee_threshold!r}")
        if not self.target_modules:
            raise ValueError("target_modules must not be empty")
        if not self.bench_dataset_args:
            raise ValueError("bench_dataset_args must not be empty")
        if len(self.real_adapters) != self.gate_adapters:
            raise ValueError(
                f"real_adapters has {len(self.real_adapters)} entries; gate_adapters is "
                f"{self.gate_adapters}"
            )
        for entry in self.real_adapters:
            if len(entry) != 2 or not all(entry):
                raise ValueError(f"each real adapter is (repo id, revision), got {entry!r}")
        if list(self.sweep) != sorted(set(self.sweep)) or self.sweep[0] != 1:
            raise ValueError(f"sweep must be strictly increasing from 1, got {self.sweep!r}")
        for lo, hi in zip(self.sweep, self.sweep[1:]):
            if hi != 2 * lo:
                raise ValueError(
                    f"sweep must double at every step so the knee is a doubling, got {self.sweep!r}"
                )
        if self.sweep[-1] > self.concurrency:
            raise ValueError(
                f"sweep top {self.sweep[-1]} exceeds concurrency {self.concurrency}: the spread "
                "regime cannot hold more adapters in flight than requests (amendment §3e). "
                "Lower the sweep's top to the concurrency instead."
            )
        if self.concentrated_k >= self.sweep[1]:
            raise ValueError("concentrated_k must be below the second sweep point")
        if self.instances_per_condition < MIN_BOOTSTRAP_SAMPLES:
            raise ValueError(
                f"instances_per_condition {self.instances_per_condition} is below the "
                f"bootstrap floor {MIN_BOOTSTRAP_SAMPLES}"
            )
        gate_n = self.gate_instances
        if isinstance(gate_n, bool) or not isinstance(gate_n, int) or gate_n < MIN_BOOTSTRAP_SAMPLES:
            raise ValueError(
                f"gate_instances must be an int at or above the bootstrap floor "
                f"{MIN_BOOTSTRAP_SAMPLES}, got {gate_n!r}"
            )
        if not set(self.diagnostic_points) <= set(self.sweep):
            raise ValueError("diagnostic_points must be sweep points")
        if self.control_point not in self.sweep:
            raise ValueError("control_point must be a sweep point")

    @property
    def equivalence_margin(self) -> float:
        """delta = tau / 2 (amendment §4): a synthetic bias below half the knee
        threshold cannot move the knee by itself."""
        return self.knee_threshold / 2

    @property
    def requests_per_phase(self) -> int:
        """max(80, 10 x C): 80 is the p95 sample floor (amendment §4)."""
        return max(MIN_SAMPLES["p95"], 10 * self.concurrency)

    @property
    def gate_slots(self) -> int:
        """The gate registers G real and G synthetic adapters."""
        return 2 * self.gate_adapters


def prereg_table(prereg: Preregistration) -> str:
    """Every pre-registered value as a markdown table. `docs/experiment-a5.md`
    embeds this exact text, and a test fails if the two ever disagree, so the
    document a reader sees and the object the code runs on are one thing."""
    lines = ["| parameter | value |", "|---|---|"]
    for f in fields(prereg):
        lines.append(f"| `{f.name}` | `{getattr(prereg, f.name)!r}` |")
    lines.append(f"| `equivalence_margin` (derived) | `{prereg.equivalence_margin!r}` |")
    lines.append(f"| `requests_per_phase` (derived) | `{prereg.requests_per_phase!r}` |")
    return "\n".join(lines)
