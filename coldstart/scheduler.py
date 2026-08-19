import random
from dataclasses import dataclass


@dataclass(frozen=True)
class ScheduledRun:
    run_index: int
    triple_index: int
    arm: str


def build_schedule(arms: list[str], triples: int, seed: int) -> list[ScheduledRun]:
    """Interleaved, randomized within each triple.

    Blocking all of one arm together would confound the intervention with
    time-varying platform conditions — see spec 5, sample plan.
    """
    rng = random.Random(seed)
    out: list[ScheduledRun] = []
    idx = 0
    for t in range(triples):
        order = list(arms)
        rng.shuffle(order)
        for arm in order:
            out.append(ScheduledRun(run_index=idx, triple_index=t, arm=arm))
            idx += 1
    return out
