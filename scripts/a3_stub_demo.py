"""A stub analysis, for laying out figures before any data exists. NOT DATA.

    .venv/bin/python scripts/a3_stub_demo.py --out build/a3-stub

Runs the synthetic suite through the campaign and recovery phases on the stub
model, analyses it, and writes analysis.json. Its numbers are planted by
toolcall/stub.py and mean nothing about any real model. It refuses an --out that
already holds anything, and never deletes anything.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.store import JsonlStore
from toolcall.analysis import analyse
from toolcall.prereg import Preregistration
from toolcall.providers import ModelSettings
from toolcall.records import CallRecord, RecoveryRecord
from toolcall.runner import run_phase
from toolcall.stub_suite import library, scenarios, synthetic_suite


def demo_prereg(included, iterations: int = 1000) -> Preregistration:
    return Preregistration(
        primary=ModelSettings("openai", "gpt-5.4-mini-2026-03-17", 0.0,
                              reasoning_effort="none"),
        slice_models=(ModelSettings("openai", "gpt-5.4-nano-2026-03-17", 0.0,
                                    reasoning_effort="none"),),
        baseline_cell="low-terse-loose", band=(0.10, 0.90), pilot_reps=10,
        pilot_cost_scenarios=10, pilot_cost_reps=5, delta2=0.02, identical_retry_floor=0.05,
        n_floor=5, n_cap=20, s_floor=24, alpha=0.05, iterations=iterations, bootstrap_seed=1,
        schedule_seed=1, retry_cap=3, turn_budget=3, normalizer_version=1,
        included=tuple(included), reps=8, recovery_reps=5, slice_reps=5, approved_usd=1.0)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="build/a3-stub")
    ap.add_argument("--calls", type=int, default=60, help="synthetic call scenarios")
    ap.add_argument("--no-calls", type=int, default=6, help="synthetic no-call scenarios")
    ap.add_argument("--iterations", type=int, default=1000, help="bootstrap draws")
    args = ap.parse_args(argv)
    out = Path(args.out)
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        print(f"{out} is not empty; choose a new --out", file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)
    lib, scs = library(), scenarios(synthetic_suite(args.calls, args.no_calls))
    prereg = demo_prereg((s.id for s in scs), args.iterations)
    for phase in ("campaign", "recovery", "slice"):
        run_phase(phase, prereg, lib, scs, out, stub=True)
    calls = JsonlStore(out / "campaign.jsonl", CallRecord).read_all()
    recs = JsonlStore(out / "recovery.jsonl", RecoveryRecord).read_all()
    slices = {m.model: JsonlStore(out / f"slice-{m.model}.jsonl", CallRecord).read_all()
              for m in prereg.slice_models}
    a = analyse(calls, recs, scs, prereg, slices=slices)
    (out / "analysis.json").write_text(json.dumps(a, indent=1, sort_keys=True) + "\n")
    print(f"[ok] {out / 'analysis.json'} (stub, NOT DATA)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
