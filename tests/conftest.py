import pytest

from multilora.prereg import Preregistration


def example_prereg(**overrides) -> Preregistration:
    """Values for tests only. The real ones live in multilora/prereg_values.py."""
    values = {
        "concurrency": 64,
        "rank": 16,
        "target_modules": (
            "q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj",
        ),
        "gate_adapters": 4,
        "warmup_requests_per_adapter": 2,
        "scrape_interval_s": 1.0,
        "knee_threshold": 0.10,
        "request_tokens": 30,
        "context_length_tokens": 8192,
        "slo_ttft_p95_s": 2.0,
        "requests_per_tenant_month": 100_000.0,
        "peak_to_average": 3.0,
        "gpu_hourly_rate": 1.0,
        "schedule_seed": 5,
        "include_diagnostic": True,
        "include_control": True,
        "bench_dataset_args": (
            "--dataset-name", "random", "--random-input-len", "14", "--random-output-len", "16",
        ),
        "real_adapters": tuple((f"example/adapter-{i}", f"rev{i}") for i in range(4)),
    }
    values.update(overrides)
    return Preregistration(**values)


@pytest.fixture
def prereg() -> Preregistration:
    return example_prereg()
