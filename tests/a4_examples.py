"""Example reconnaissance reports for plan 3's tests, in the shape
`placement_measure.recon_report.report` returns.

Not a test module. The numbers are invented but plausible: a 4B split engine
logging about 18k tokens of KV, a solo one about 88k, swaps of 30-45 s.
"""

import copy

PRIMARY, BASE = "Qwen/Qwen3-4B", "Qwen/Qwen3-4B-Base"
INSTRUCT, THINKING = "Qwen/Qwen3-4B-Instruct-2507", "Qwen/Qwen3-4B-Thinking-2507"
FALLBACK = "Qwen/Qwen3-1.7B"


def _go(passed, kv):
    return {"answered": True, "passed": passed, "healthy": [True, True],
            "kv_capacity_tokens": list(kv), "required_tokens": 16384}


REPORT = {
    "help": {"serve": {"returncode": 0, "missing": []}, "bench": {"returncode": 0, "missing": []}},
    "staged": {"all_staged": True},
    "go_no_go": {"primary": _go(True, (18_432, 18_100)), "fallback": _go(True, (52_000, 52_000))},
    "compile_reuse": [
        {"a": PRIMARY, "b": BASE, "b_s4b_s": 0.31, "b_compiled": False, "swap_s": 33.0},
        {"a": BASE, "b": INSTRUCT, "b_s4b_s": 0.33, "b_compiled": False, "swap_s": 31.5},
        {"a": INSTRUCT, "b": THINKING, "b_s4b_s": 0.30, "b_compiled": False, "swap_s": 32.2},
        {"a": THINKING, "b": PRIMARY, "b_s4b_s": 0.29, "b_compiled": False, "swap_s": 30.8},
    ],
    "cache_eviction": [
        {"cold": False, "b": BASE, "b_compiled": False, "swap_s": 31.0},
        {"cold": True, "b": PRIMARY, "b_compiled": False, "swap_s": 44.0,
         "methods_ok": {"drop_caches": False, "fadvise": True}, "cached_kib_drop": 7_600_000},
        {"cold": True, "b": BASE, "b_compiled": False, "swap_s": 45.5,
         "methods_ok": {"drop_caches": False, "fadvise": True}, "cached_kib_drop": 7_500_000},
        {"cold": False, "b": PRIMARY, "b_compiled": False, "swap_s": 30.5},
    ],
    "release": {"n": 8, "median_s": 0.9, "max_s": 2.1, "never_released": 0},
    "kv_solo": [
        {"model": PRIMARY, "kv_capacity_tokens": 86_000, "s4b_s": 19.2, "compiled": True},
        {"model": BASE, "kv_capacity_tokens": 88_100, "s4b_s": 0.31, "compiled": False},
        {"model": PRIMARY, "kv_capacity_tokens": 88_300, "s4b_s": 0.29, "compiled": False},
    ],
    "early_start": {"answered": True, "b_healthy": True, "memory_when_b_started_mib": 600},
    "sleep_mode": {"answered": True, "works": True, "sleep_s": 2.1, "wake_s": 3.4,
                   "memory_sleeping_mib": 1400, "statuses": {}},
}


def example_report(**changes) -> dict:
    """A deep copy of REPORT with top-level keys replaced."""
    report = copy.deepcopy(REPORT)
    report.update(copy.deepcopy(changes))
    return report
