"""Artifact 5's pre-registered values. Committed with docs/experiment-a5.md,
before the first measured run; tests/test_multilora_prereg_values.py keeps the
two identical and ties the measured values to fixtures/a5/."""

from multilora.prereg import Preregistration

# gpu_memory_utilization is NOT a Preregistration field: it is the endpoint env
# A5_GPU_MEMORY_UTILIZATION=0.80, recorded in docs/recon-a5.md ("The memory
# budget") and to be recorded in docs/experiment-a5.md.
PREREG = Preregistration(
    # R2_highest_healthy_slots == 64 and R5_max_distinct_running_at_top == 64
    # (fixtures/a5/recon_report.json), so neither the sweep top nor C is lowered.
    concurrency=64,
    rank=16,  # A5_MAX_LORA_RANK (Task 3)
    target_modules=("q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"),
    gate_adapters=4,
    warmup_requests_per_adapter=2,
    scrape_interval_s=1.0,
    knee_threshold=0.10,  # author, signed off: 10% throughput loss per doubling
    # 13 measured prompt tokens (recon_report.json request_shape_prompt_tokens
    # == [13]) + 16 output tokens.
    request_tokens=29,
    context_length_tokens=8192,  # artifact 1's --max-model-len (docs/post.md)
    slo_ttft_p95_s=1.0,  # author, signed off
    requests_per_tenant_month=100_000.0,  # author, signed off
    peak_to_average=3.0,  # author, signed off
    # Amendment 2 (2026-10-05, docs/experiment-a5.md): artifact 4's registered
    # rate, GPU_HOURLY_RATE in placement/registered.py (commit b17c8ac), derived
    # from RunPod's billing API for endpoint nnypnh9drkq5ux. It replaces the
    # illustrative $1.00/GPU-hour carried over from artifact 1 (docs/post.md),
    # so the economics use one rate across both artifacts.
    gpu_hourly_rate=1.1095,
    schedule_seed=20261001,
    # Cut by the owner on 2026-10-05: lora-N64-specialize ran out of memory at
    # both the 0.85 and 0.80 budgets (docs/recon-a5.md, "The diagnostic is cut").
    include_diagnostic=False,
    include_control=True,  # R7_gauge_exported true; then the budget (scripts/a5_budget.py)
    bench_dataset_args=(
        "--dataset-name", "random",
        "--random-input-len", "13",
        "--random-output-len", "16",
    ),
    # fixtures/a5/real_adapter_candidates.json `selected`, in its order.
    real_adapters=(
        ("AIsakawaii/task_b_method2_qwen4b", "8ba6625bbb5f5a8770109f003ae55fcaef4fb117"),
        (
            "davemaxuellkr/KIRD-project_QLoRa-Qwen3-4B_en-ko",
            "f7eb9b54171b1212347ebb0e3bb26008d81e92db",
        ),
        ("hanghang1024/Qwen3-4b-Qlora-Fin", "47d3fc76a0d748497e726134ee5092e68bb0cacf"),
        ("jacobcd52/qwen3_4b_hacker", "89cb5e72a31c2f2ce53e9c4f9aee9ee38b7c26e2"),
    ),
    # Amendment 1 (2026-10-05, after the first gate was inconclusive): docs/experiment-a5.md
    # Amendment 3 (2026-10-05): 144 + 52 replacements for the instances lost to a host fault; scheduled, not usable
    gate_instances=196,
)
