import random
from dataclasses import dataclass


@dataclass(frozen=True)
class ScheduledRun:
    run_index: int
    block_index: int
    condition: str


def build_schedule(conditions: list[str], blocks: int, seed: int) -> list[ScheduledRun]:
    """Interleaved, randomized within each block.

    Blocking all of one condition together would confound the intervention with
    time-varying platform conditions — see artifact 1 spec 5, sample plan.

    The vocabulary is deliberately artifact-neutral. Artifact 1's three arms
    within a triple, artifact 5's two regimes at one registered count, and
    artifact 4's three placement strategies are the same structure; naming it
    "arm" and "triple" here would have made two of those read as a hack.
    `coldstart/driver.py` maps `condition`/`block_index` back onto `RunRecord`'s
    `arm`/`triple_index` fields, so artifact 1's stored records are unchanged.
    """
    rng = random.Random(seed)
    out: list[ScheduledRun] = []
    idx = 0
    for b in range(blocks):
        order = list(conditions)
        rng.shuffle(order)
        for condition in order:
            out.append(ScheduledRun(run_index=idx, block_index=b, condition=condition))
            idx += 1
    return out
