"""Produce a stub analysis for laying out artifact 5's figures. NOT DATA.

    .venv/bin/python scripts/a5_stub_demo.py --out build/a5-stub

Runs both schedules against the stub worker and writes analysis.json. Every
value comes from `multilora.stub.StubModel`; nothing here may be published.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.store import JsonlStore
from harness.submit import PayloadStubSubmitter
from multilora.analysis import analyse
from multilora.campaign import run
from multilora.conditions import campaign_schedule, gate_schedule
from multilora.prereg import Preregistration
from multilora.records import InstanceRecord
from multilora.stub import StubInstanceEndpoint

DEMO = Preregistration(
    concurrency=64, rank=16,
    target_modules=("q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"),
    gate_adapters=4, warmup_requests_per_adapter=2, scrape_interval_s=1.0, knee_threshold=0.08,
    request_tokens=30, context_length_tokens=8192, slo_ttft_p95_s=2.0,
    requests_per_tenant_month=100_000.0, peak_to_average=3.0, gpu_hourly_rate=1.0,
    schedule_seed=1, include_diagnostic=True, include_control=True,
    bench_dataset_args=("--dataset-name", "random", "--random-input-len", "14",
                        "--random-output-len", "16"),
    real_adapters=tuple((f"example/adapter-{i}", f"rev{i}") for i in range(4)),
)
DEMO_A4 = {
    "gpu_hourly_rate": 1.0,
    "n_models": 20,
    "reference": {"regime": "low-locality", "s": 1.1},
    "rows": [{
        "regime": "low-locality", "s": 1.1,
        "dedicated_cost_per_tenant_month": 730.0,
        "swapped_cost_per_tenant_month": 120.0,
        "sleep_mode_cost_per_tenant_month": None,
    }],
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    records = {}
    for name, schedule in (("campaign", campaign_schedule(DEMO)), ("gate", gate_schedule(DEMO))):
        path = out / f"{name}.jsonl"
        path.unlink(missing_ok=True)
        store = JsonlStore(path, InstanceRecord)
        run(schedule, PayloadStubSubmitter(StubInstanceEndpoint(seed=3).run), store, DEMO)
        records[name] = store.read_all()
    result = analyse(records["campaign"], records["gate"], DEMO, a4=DEMO_A4, iterations=2000)
    result["NOT_DATA"] = "stub output from multilora.stub; never publish"
    (out / "analysis.json").write_text(json.dumps(result, indent=1, sort_keys=True))
    print(f"[ok] {out / 'analysis.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
