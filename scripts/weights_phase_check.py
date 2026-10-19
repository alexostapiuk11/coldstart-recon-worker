"""What the `T_weights` phase is made of, and what the S6 mark actually measures.

Four things `docs/post.md` states that `data/analysis.json` does not carry, derived
here from `data/campaign.jsonl` so a reader can re-derive them with no GPU:

    .venv/bin/python scripts/weights_phase_check.py --store data/campaign.jsonl

1. `T_weights` runs from `S2_acquisition_start` -- stamped just BEFORE `vllm serve`
   is launched -- to `S3_load_done`, the engine's "Model loading took" line. It is
   process start-up plus loading, not loading alone. vLLM reports its own loading
   time on that very line, so the two can be separated: start-up = T_weights minus
   the reported loading seconds.
2. Each run's phases sum to that run's `T_total` to within clock-read rounding
   (tens of microseconds); a column of per-phase MEDIANS does not sum to the
   median total, because a median is not additive.
3. The `S6_first_token` mark is stamped after request 1's whole 16-token reply has
   been read, so the "S6" phase is request 1's full latency. The time to first
   token proper is the per-request `ttft` field.
4. KV capacity does not vary within an arm.
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coldstart.analysis.metrics import derive
from coldstart.schema import RunRecord
from harness.stats import bootstrap_paired_median_diff, median, within_host_triples
from harness.store import JsonlStore

ARMS = ("A", "B", "C")

# Bootstrap seeds. A->B uses the seed `scripts/analyse.py` uses for the same
# interval, so `T_weights` A->B reproduces `paired_A_to_B_t_weights` in
# `data/analysis.json` to the last digit instead of differing by Monte Carlo noise.
# B->C has no entry in analysis.json and uses the module default.
SEEDS = {("A", "B"): 4, ("B", "C"): 0}

# The rows of the post's decomposition table, in its order. `s4_unattributed` is
# the S4 remainder after the identified sub-phases and the merged S4a/S4d.
PHASES = (
    "t_platform",
    "t_s1",
    "t_weights",
    "t_s4b",
    "t_s4c",
    "t_s4e",
    "s4_unattributed",
    "t_s5",
    "t_s6",
)

# vLLM's own report of how long the model load took, on the same log line the
# probe uses to stamp S3. Group 2 is the seconds.
_LOAD_LINE = re.compile(r"Model loading took ([\d.]+) GiB and ([\d.]+) seconds")


def _reported_load_seconds(log_lines: list[str]) -> float:
    for line in log_lines:
        found = _LOAD_LINE.search(line)
        if found:
            return float(found.group(2))
    raise ValueError("no 'Model loading took' line in the engine log")


def _rows(store: Path) -> list[dict]:
    """Derived rows, each carrying vLLM's reported load seconds and the start-up
    that precedes it."""
    rows = []
    for record in JsonlStore(str(store), RunRecord).read_all():
        row = derive(record)
        load = _reported_load_seconds(record.engine["log_lines"])
        row["vllm_load"] = load
        row["startup"] = row["t_weights"] - load
        rows.append(row)
    return rows


def compute(store: Path) -> dict:
    rows = _rows(Path(store))
    by_arm = {a: [r for r in rows if r["arm"] == a] for a in ARMS}

    table = {a: {p: median([r[p] for r in by_arm[a]]) for p in PHASES} for a in ARMS}
    median_total = {a: median([r["t_total"] for r in by_arm[a]]) for a in ARMS}
    # Summed from the two-decimal values a reader sees in the table, so the
    # published sum row is the arithmetic they would do themselves.
    sum_as_printed = {a: round(sum(round(v, 2) for v in table[a].values()), 2) for a in ARMS}

    triples = within_host_triples(rows)
    paired = {
        f"{x}->{y}": {
            key: bootstrap_paired_median_diff(triples, x, y, value=key, seed=SEEDS[(x, y)])
            for key in ("t_weights", "vllm_load", "startup")
        }
        for x, y in (("A", "B"), ("B", "C"))
    }

    return {
        "table": table,
        "median_total": median_total,
        "sum_as_printed": sum_as_printed,
        "per_run_phase_sum_max_error": max(
            abs(r["t_total"] - sum(r[p] for p in PHASES)) for r in rows
        ),
        "load": {
            a: {
                "t_weights": median([r["t_weights"] for r in by_arm[a]]),
                "vllm_load": median([r["vllm_load"] for r in by_arm[a]]),
                "startup": median([r["startup"] for r in by_arm[a]]),
            }
            for a in ARMS
        },
        "paired": paired,
        "paired_triples": len(triples),
        "request1": {
            a: {
                "ttft": median([r["warmup"][0]["ttft"] for r in by_arm[a]]),
                "end_to_end": median([r["warmup"][0]["end_to_end"] for r in by_arm[a]]),
            }
            for a in ARMS
        },
        "kv_capacity_values": {
            a: sorted({r["kv_capacity_tokens"] for r in by_arm[a]}) for a in ARMS
        },
    }


def _interval(d: dict) -> str:
    return f"{d['point']:.2f} [{d['lo']:.2f}, {d['hi']:.2f}]"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="data/campaign.jsonl")
    out = compute(Path(ap.parse_args().store))

    print("Decomposition table: per-phase medians vs the median total (s)")
    for a in ARMS:
        gap = out["sum_as_printed"][a] - out["median_total"][a]
        print(
            f"  arm {a}: sum of rows {out['sum_as_printed'][a]:.2f}   "
            f"median total {out['median_total'][a]:.2f}   gap {gap:+.2f}"
        )
    print(
        f"  per-run |T_total - sum of phases|, worst case: "
        f"{out['per_run_phase_sum_max_error']:.1e} s"
    )

    print("\nT_weights = launch of `vllm serve` -> 'Model loading took' line (medians, s)")
    print(f"  {'arm':4}{'T_weights':>11}{'vLLM-reported load':>21}{'start-up before it':>21}")
    for a in ARMS:
        row = out["load"][a]
        print(f"  {a:4}{row['t_weights']:>11.2f}{row['vllm_load']:>21.2f}{row['startup']:>21.2f}")

    print(f"\nPaired medians of differences over {out['paired_triples']} within-host triples (s)")
    for pair, metrics in out["paired"].items():
        for key, label in (
            ("t_weights", "T_weights"),
            ("vllm_load", "vLLM-reported load"),
            ("startup", "start-up before load"),
        ):
            print(f"  {pair}  {label:22} {_interval(metrics[key])}")

    print("\nRequest 1: S6 'first token' mark vs the real time to first token (medians, s)")
    for a in ARMS:
        r1 = out["request1"][a]
        print(
            f"  arm {a}: whole request {r1['end_to_end']:.4f}   time to first token {r1['ttft']:.4f}"
        )

    print("\nKV capacity values seen per arm:", out["kv_capacity_values"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
