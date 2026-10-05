"""Reconnaissance answers, computed from the saved captures. Publishes nothing.

Each capture is what `scripts/a4_recon_capture.py` saved for one job: the
payload it submitted and the submitter's outcome, verbatim. A job that failed
outright has no `payload` in its outcome; its question is then reported as
unanswered, never as a "no".

The go/no-go criterion is the pre-registered one (`prereg.GO_NO_GO_TOKENS`,
amendment §3); this module applies it and does not choose it.
"""

from harness.stats import median
from placement_measure.prereg import GO_NO_GO_MIN_REQUESTS, GO_NO_GO_TOKENS, T_MAX

__all__ = ["COMPILED_ABOVE_S", "render", "report"]

# Artifact 1 published S4b at 19.0 s for a compile and 0.33 s for a cache hit
# (data/analysis.json). A reading above this is a compile; below, a hit. The
# gap is two orders of magnitude, so the threshold's exact value does not
# decide any reading near either published figure.
COMPILED_ABOVE_S = 5.0


def _result(capture: dict) -> dict | None:
    payload = (capture.get("outcome") or {}).get("payload")
    return None if payload is None else payload.get("result")


def _by_label(captures) -> dict[str, dict]:
    return {c["label"]: c for c in captures}


def go_no_go(capture: dict | None) -> dict:
    r = None if capture is None else _result(capture)
    if r is None:
        return {"answered": False, "passed": None, "reason": "the probe produced no result"}
    engines = r["engines"]
    kv = [engines[k]["facts"].get("kv_capacity_tokens") for k in ("a", "b")]
    healthy = [engines[k]["healthy"] for k in ("a", "b")]
    passed = all(healthy) and all(t is not None and t >= GO_NO_GO_TOKENS for t in kv)
    return {"answered": True, "passed": passed, "healthy": healthy, "kv_capacity_tokens": kv,
            "required_tokens": GO_NO_GO_TOKENS,
            "criterion": f"both healthy, each KV >= {GO_NO_GO_MIN_REQUESTS} x T_MAX ({T_MAX})"}


def _swaps(capture: dict | None) -> list[dict]:
    r = None if capture is None else _result(capture)
    return [] if r is None else r["swaps"]


def compile_reuse(capture: dict | None) -> list[dict]:
    out = []
    for s in _swaps(capture):
        b = s.get("b") or {}
        s4b = (b.get("facts") or {}).get("s4b_s")
        out.append({"a": s["a"]["spec"]["model"], "b": (b.get("spec") or {}).get("model"),
                    "b_s4b_s": s4b, "b_compiled": None if s4b is None else s4b > COMPILED_ABOVE_S,
                    "swap_s": s.get("swap_s")})
    return out


def kv_solo(captures) -> list[dict]:
    """Every full-memory engine's logged KV capacity, with its compile state.

    The swap probes start each engine alone at `SOLO_GMU`, so they are the
    solo readings beside the co-residency probe's split ones. Compile state is
    carried because it moves KV capacity: artifact 1 published 35,792 tokens
    without a warm compile cache and 43,040 with one (amendment §5).
    """
    out = []
    for c in captures:
        for s in _swaps(c):
            for side in ("a", "b"):
                engine = s.get(side) or {}
                facts = engine.get("facts") or {}
                s4b = facts.get("s4b_s")
                out.append({"model": (engine.get("spec") or {}).get("model"),
                            "kv_capacity_tokens": facts.get("kv_capacity_tokens"),
                            "s4b_s": s4b,
                            "compiled": None if s4b is None else s4b > COMPILED_ABOVE_S})
    return out


def cache_eviction(capture: dict | None) -> list[dict]:
    out = []
    for s in _swaps(capture):
        cache = s.get("cache") or {}
        b = s.get("b") or {}
        s4b = (b.get("facts") or {}).get("s4b_s")
        common = {"b": (b.get("spec") or {}).get("model"), "swap_s": s.get("swap_s"),
                  "b_compiled": None if s4b is None else s4b > COMPILED_ABOVE_S}
        if not cache.get("requested"):
            out.append({"cold": False, **common})
            continue
        before, after = cache.get("cached_kib_before"), cache.get("cached_kib_after")
        out.append({
            "cold": True, **common,
            "methods_ok": {a["method"]: a["ok"] for a in cache.get("attempts", [])},
            "cached_kib_drop": None if before is None or after is None else before - after,
        })
    return out


def release(captures) -> dict:
    seconds = [s["release"]["seconds"] for c in captures for s in _swaps(c)
               if s.get("release") and s["release"]["released"]]
    unreleased = sum(1 for c in captures for s in _swaps(c)
                     if s.get("release") and not s["release"]["released"])
    return {"n": len(seconds), "median_s": median(seconds) if seconds else None,
            "max_s": max(seconds) if seconds else None, "never_released": unreleased}


def early_start(capture: dict | None) -> dict:
    r = None if capture is None else _result(capture)
    if r is None:
        return {"answered": False}
    return {"answered": True, "b_healthy": r["b"]["healthy"],
            "memory_when_b_started_mib": r["memory_when_b_started"]["used_mib"]}


def sleep_mode(capture: dict | None) -> dict:
    r = None if capture is None else _result(capture)
    if r is None:
        return {"answered": False}

    def status(step):
        return (r.get(step) or {}).get("status")

    works = status("sleep_a") == 200 and status("wake_a") == 200 and status("smoke_a_after_wake") == 200
    return {
        "answered": True, "works": works,
        "sleep_s": (r.get("sleep_a") or {}).get("seconds"),
        "wake_s": (r.get("wake_a") or {}).get("seconds"),
        "memory_sleeping_mib": (r.get("memory_a_asleep") or {}).get("used_mib"),
        "statuses": {k: status(k) for k in ("sleep_a", "is_sleeping_a", "sleep_b", "wake_a",
                                            "smoke_a_after_wake")},
    }


def report(captures) -> dict:
    by = _by_label(captures)
    help_r = None if "help" not in by else _result(by["help"])
    return {
        "help": help_r,
        "staged": None if "stage" not in by else _result(by["stage"]),
        "go_no_go": {"primary": go_no_go(by.get("coresidency-primary")),
                     "fallback": go_no_go(by.get("coresidency-fallback"))},
        "compile_reuse": compile_reuse(by.get("swaps-compile")),
        "cache_eviction": cache_eviction(by.get("swaps-cache")),
        "release": release([by[k] for k in ("swaps-compile", "swaps-cache") if k in by]),
        "kv_solo": kv_solo([by[k] for k in ("swaps-compile", "swaps-cache") if k in by]),
        "early_start": early_start(by.get("early-start")),
        "sleep_mode": sleep_mode(by.get("sleep")),
    }


def render(rep: dict) -> str:
    g = rep["go_no_go"]
    lines = ["# Artifact 4 reconnaissance answers", ""]
    for key in ("primary", "fallback"):
        v = g[key]
        lines.append(f"- go/no-go ({key}): " + (
            "unanswered" if not v["answered"] else
            f"{'PASS' if v['passed'] else 'FAIL'}; KV {v['kv_capacity_tokens']} vs "
            f"{v['required_tokens']} required; healthy {v['healthy']}"))
    for row in rep["compile_reuse"]:
        lines.append(f"- swap {row['a']} -> {row['b']}: S4b {row['b_s4b_s']} s, "
                     f"compiled {row['b_compiled']}, swap {row['swap_s']} s")
    for row in rep["cache_eviction"]:
        lines.append(f"- {'cold' if row['cold'] else 'warm'} swap: {row['swap_s']} s"
                     + (f"; methods {row['methods_ok']}; Cached fell {row['cached_kib_drop']} KiB"
                        if row["cold"] else ""))
    for row in rep["kv_solo"]:
        lines.append(f"- solo engine {row['model']}: KV {row['kv_capacity_tokens']} tokens, "
                     f"compiled {row['compiled']}")
    rel = rep["release"]
    lines.append(f"- memory release: median {rel['median_s']} s, max {rel['max_s']} s over "
                 f"{rel['n']} swaps; never released {rel['never_released']}")
    e = rep["early_start"]
    lines.append("- early start: " + ("unanswered" if not e["answered"] else
                 f"B healthy {e['b_healthy']} with {e['memory_when_b_started_mib']} MiB in use"))
    s = rep["sleep_mode"]
    lines.append("- sleep mode: " + ("unanswered" if not s["answered"] else
                 f"works {s['works']}; sleep {s['sleep_s']} s, wake {s['wake_s']} s, "
                 f"{s['memory_sleeping_mib']} MiB held asleep; statuses {s['statuses']}"))
    return "\n".join(lines) + "\n"
