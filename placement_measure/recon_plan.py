"""The reconnaissance jobs, built from the pre-registered values.

One list, so the capture script and its tests agree on what is submitted, and
a reader can see every paid job before any is run (`--list`).

The swap order is chosen so each answer is readable from one job's S4b
readings: the first engine of a fresh worker compiles; after it, a successor
whose S4b is a cache hit shares the compile cache. Qwen3-4B and -Base share
`rope_theta`; the -2507 pair shares a different one. The two crossings
(-Base to -Instruct-2507, -Thinking-2507 back to Qwen3-4B) test whether the
difference matters (amendment §3). One pair runs warm and cold, to see whether
eviction changes the swap (§5).

The first four jobs do not depend on the model class. The last four do: if the
primary failed its go/no-go and the fallback passed, the measured checkpoint is
`Qwen/Qwen3-1.7B` and has no siblings to cross, so those four run it against
itself -- step 2 makes its validation set three tenants of it and its
neighbour a second engine of it. The swap sequences keep the primary plan's
cache states, so the two plans differ in the checkpoint only.
"""

from placement_measure.prereg import (
    CANDIDATES,
    FALLBACK,
    HF_HOME,
    JOB_BUDGET_S,
    PRIMARY,
    RELEASE_TIMEOUT_S,
    RELEASE_TOLERANCE_MIB,
    SLEEP_GMU,
    SOLO_GMU,
    SPLIT_GMU,
    engine,
)

__all__ = ["recon_jobs"]

BASE = "Qwen/Qwen3-4B-Base"
INSTRUCT = "Qwen/Qwen3-4B-Instruct-2507"
THINKING = "Qwen/Qwen3-4B-Thinking-2507"


def _swap(a: str, b: str, cold: bool) -> dict:
    return {"a": engine(a, SOLO_GMU).to_dict(), "b": engine(b, SOLO_GMU).to_dict(), "cold": cold}


def recon_jobs(model_class: str = PRIMARY) -> list[dict]:
    if model_class not in (PRIMARY, FALLBACK):
        raise ValueError(f"model class {model_class!r} is neither the primary nor the fallback")
    common = {"job_budget_s": JOB_BUDGET_S}
    swap_common = {**common, "probe": "swaps", "hf_home": HF_HOME,
                   "release_tolerance_mib": RELEASE_TOLERANCE_MIB,
                   "release_timeout_s": RELEASE_TIMEOUT_S}
    sleepy = ("--enable-sleep-mode",)
    if model_class == PRIMARY:
        compile_swaps = [_swap(PRIMARY, BASE, False), _swap(BASE, INSTRUCT, False),
                         _swap(INSTRUCT, THINKING, False), _swap(THINKING, PRIMARY, False)]
        cache_swaps = [_swap(PRIMARY, BASE, False), _swap(BASE, PRIMARY, True),
                       _swap(PRIMARY, BASE, True), _swap(BASE, PRIMARY, False)]
        measured, neighbour = PRIMARY, BASE
    else:
        compile_swaps = [_swap(FALLBACK, FALLBACK, False) for _ in range(4)]
        cache_swaps = [_swap(FALLBACK, FALLBACK, cold) for cold in (False, True, True, False)]
        measured, neighbour = FALLBACK, FALLBACK
    return [
        {**common, "label": "help", "probe": "help"},
        {**common, "label": "stage", "probe": "stage",
         "models": [{"model": m, "revision": r} for m, r in CANDIDATES.items()]},
        {**common, "label": "coresidency-primary", "probe": "coresidency",
         "a": engine(PRIMARY, SPLIT_GMU).to_dict(), "b": engine(BASE, SPLIT_GMU).to_dict()},
        {**common, "label": "coresidency-fallback", "probe": "coresidency",
         "a": engine(FALLBACK, SPLIT_GMU).to_dict(), "b": engine(FALLBACK, SPLIT_GMU).to_dict()},
        {**swap_common, "label": "swaps-compile", "swaps": compile_swaps},
        {**swap_common, "label": "swaps-cache", "swaps": cache_swaps},
        {**common, "label": "early-start", "probe": "early_start",
         "a": engine(measured, SOLO_GMU).to_dict(), "b": engine(neighbour, SOLO_GMU).to_dict()},
        {**common, "label": "sleep", "probe": "sleep",
         "a": engine(measured, SLEEP_GMU, sleepy).to_dict(),
         "b": engine(neighbour, SLEEP_GMU, sleepy).to_dict()},
    ]
