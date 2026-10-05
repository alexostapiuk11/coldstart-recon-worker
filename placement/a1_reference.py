"""Artifact 1's 8B cold-start stage medians: figure 4's labelled reference bar.

The ONE module in `placement/` allowed to load `coldstart` (amendment §7,
tests/test_placement_boundary.py's ADAPTERS). It reads artifact 1's committed
store through artifact 1's own derivation, so the reference is the number
artifact 1 published, not a re-derivation of it. Nothing in `placement/`
imports this module at module level; `scripts/a4_analyse.py` does, once.

The reference arm is C, weights on the network volume with a warm compile
cache: the closest of artifact 1's arms to the swap the simulator draws, whose
weights come from the volume and whose compile cache is warm (pre-registration
step 2). The magnitudes are an 8B model's, which is why the figure labels them
a reference and never subtracts a swap from them (amendment §5).
"""

from coldstart.analysis.metrics import derive
from coldstart.schema import RunRecord
from harness.stats import median
from harness.store import JsonlStore

__all__ = ["REFERENCE_ARM", "STAGES", "stage_medians"]

REFERENCE_ARM = "C"
# Artifact 1's stage keys, in the order a cold start pays them.
STAGES = ("t_platform", "t_weights", "t_s4_bracket", "t_s5", "t_s6")


def stage_medians(store_path, arm: str = REFERENCE_ARM) -> dict:
    rows = [r for r in (derive(rec) for rec in JsonlStore(store_path, RunRecord).read_all())
            if r["ok"] and r["arm"] == arm and r.get("consistent")
            and all(r.get(k) is not None for k in STAGES)]
    if not rows:
        raise ValueError(f"artifact 1's store has no consistent arm-{arm} run with every stage")
    return {"arm": arm, "n": len(rows), "model": "Qwen/Qwen3-8B",
            "stages": {k: median([r[k] for r in rows]) for k in STAGES}}
