"""A process-level swap's measured stages, for figure 4.

Amendment §5: figure 4 separates the taxonomy from the magnitude. It shows the
4B swap's own measured stages, each marked paid or skipped under artifact 1's
taxonomy, and puts artifact 1's 8B cold-start medians beside them only as a
labelled reference (`placement.a1_reference`).

From each stored swap:

- `teardown_s`: engine A's process exiting (`Server.stop()`);
- `release_s`: A's GPU memory returning to the idle level;
- B's bring-up, `startup_s`, split by B's own log into weight loading (vLLM's
  "Model loading took ... seconds", artifact 1's S3), engine initialisation
  ("init engine ... took ... s", S4, of which torch.compile is `compile_s`,
  S4b), and the rest: the `vllm serve` process starting and importing (S2,
  which a process-level swap re-pays, amendment §5), the API server, and the
  health poll that ends the swap (S5).

A swap whose log lacks either line is not estimated: the stage split would
otherwise be invented for it. `stage_medians` counts and names such swaps
beside the medians, and refuses only if none can be read.

Compile state comes from the engine's facts (`s4b_s`, read from its whole log
in the container), the same field `placement.inputs.swap_distribution`
filters on, so the figure decomposes exactly the swaps the simulator draws.
"""

import re

from harness.stats import median
from placement_measure.campaigns import parse_swap
from placement_measure.recon_report import COMPILED_ABOVE_S

__all__ = ["STAGES", "stage_medians", "swap_stages"]

MODEL_LOADING = re.compile(r"Model loading took [\d.]+ GiB and (?P<sec>[\d.]+) seconds")
INIT_ENGINE = re.compile(r"init engine \(profile, create kv cache, warmup model\) took "
                         r"(?P<sec>[\d.]+) s")
# In the order a swap pays them.
STAGES = ("teardown_s", "release_s", "process_and_health_s", "weights_s", "engine_init_rest_s",
          "compile_s")


def _last(pattern: re.Pattern, lines) -> float | None:
    found = [float(m["sec"]) for line in lines if (m := pattern.search(line))]
    return found[-1] if found else None


def swap_stages(record) -> dict:
    out = record.output
    b = out.get("b") or {}
    lines = b.get("log_tail") or []
    weights, init = _last(MODEL_LOADING, lines), _last(INIT_ENGINE, lines)
    if weights is None or init is None:
        raise ValueError(f"swap {record.run_id}'s engine log lacks the "
                         f"{'model-loading' if weights is None else 'engine-init'} line; its "
                         "stages cannot be read, and estimating them would invent the split")
    compile_s = (b.get("facts") or {}).get("s4b_s")
    if compile_s is None:
        raise ValueError(f"swap {record.run_id}'s engine facts have no compile time (S4b)")
    rest = b["startup_s"] - weights - init
    if rest < 0:
        raise ValueError(f"swap {record.run_id}: weight loading and engine init ({weights + init:.2f}"
                         f" s) exceed the measured bring-up ({b['startup_s']:.2f} s)")
    return {
        "teardown_s": out["teardown_s"],
        "release_s": out["release"]["seconds"],
        "process_and_health_s": rest,
        "weights_s": weights,
        "engine_init_rest_s": init - compile_s,
        "compile_s": compile_s,
        "swap_s": out["swap_s"],
    }


def stage_medians(records, *, cold: bool, compiled: bool = False) -> dict:
    """Median of each stage over the ok swaps in one cache and compile state:
    the simulated state, so figure 4 decomposes the swap the simulator draws."""
    rows, unreadable = [], []
    for r in records:
        if r.kind != "swap" or r.outcome != "ok" or parse_swap(r.condition)[2] != cold:
            continue
        s4b = ((r.output.get("b") or {}).get("facts") or {}).get("s4b_s")
        # A swap with no compile reading is outside every stratum, as it is
        # for `swap_distribution`.
        if s4b is None or (s4b > COMPILED_ABOVE_S) != compiled:
            continue
        try:
            rows.append(swap_stages(r))
        except ValueError as e:
            unreadable.append({"run_id": r.run_id, "reason": str(e)})
    if not rows:
        raise ValueError(f"no readable ok swap with cold={cold} and compiled={compiled} to "
                         f"decompose ({len(unreadable)} unreadable)")
    return {"n": len(rows), "cold": cold, "compiled": compiled, "unreadable": unreadable,
            "stages": {k: median([row[k] for row in rows]) for k in (*STAGES, "swap_s")}}
