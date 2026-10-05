from placement_measure.prereg import GO_NO_GO_TOKENS
from placement_measure.recon_report import render, report


def _capture(label, probe, result=None, error=None):
    payload = None if result is None else {"healthy": True, "probe": probe, "result": result}
    return {"label": label, "probe": probe, "submitted": {},
            "outcome": {"clock_A": {}, "payload": payload, "error": error, "diagnostics": None}}


def _engines(kv_a, kv_b, healthy=(True, True)):
    return {"engines": {k: {"healthy": h, "facts": {"kv_capacity_tokens": kv}}
                        for k, kv, h in (("a", kv_a, healthy[0]), ("b", kv_b, healthy[1]))}}


def _swap(a, b, s4b, swap_s, cache=None, released=True, kv=(90000, 88000)):
    return {"a": {"spec": {"model": a}, "facts": {"s4b_s": 19.0, "kv_capacity_tokens": kv[0]}},
            "b": {"spec": {"model": b}, "facts": {"s4b_s": s4b, "kv_capacity_tokens": kv[1]}},
            "swap_s": swap_s, "cache": cache or {"requested": False},
            "release": {"released": released, "seconds": 0.8}}


def test_the_report_applies_the_preregistered_go_no_go():
    rep = report([
        _capture("coresidency-primary", "coresidency", _engines(GO_NO_GO_TOKENS, 20000)),
        _capture("coresidency-fallback", "coresidency", _engines(GO_NO_GO_TOKENS - 1, 90000)),
    ])
    assert rep["go_no_go"]["primary"]["passed"] is True
    assert rep["go_no_go"]["fallback"]["passed"] is False


def test_a_failed_probe_is_unanswered_not_a_no():
    rep = report([_capture("coresidency-primary", "coresidency", error="timeout")])
    assert rep["go_no_go"]["primary"] == {"answered": False, "passed": None,
                                          "reason": "the probe produced no result"}


def test_the_report_reads_compile_reuse_cache_eviction_and_release():
    cold_cache = {"requested": True, "attempts": [{"method": "drop_caches", "ok": False},
                                                  {"method": "fadvise", "ok": True}],
                  "cached_kib_before": 9_000_000, "cached_kib_after": 1_000_000}
    rep = report([
        _capture("swaps-compile", "swaps", {"swaps": [_swap("x", "y", 19.0, 60.0),
                                                      _swap("y", "z", 0.3, 30.0)]}),
        _capture("swaps-cache", "swaps", {"swaps": [_swap("x", "y", 0.3, 45.0, cold_cache),
                                                    _swap("y", "x", 0.3, 28.0, released=False)]}),
    ])
    assert [r["b_compiled"] for r in rep["compile_reuse"]] == [True, False]
    cold = rep["cache_eviction"][0]
    assert (cold["b"], cold["b_compiled"]) == ("y", False)
    assert cold["methods_ok"] == {"drop_caches": False, "fadvise": True}
    assert cold["cached_kib_drop"] == 8_000_000
    assert rep["release"]["n"] == 3 and rep["release"]["never_released"] == 1
    assert "go/no-go (primary): unanswered" in render(rep)


def test_the_report_reads_every_solo_engines_kv_with_its_compile_state():
    rep = report([_capture("swaps-compile", "swaps", {"swaps": [
        _swap("x", "y", 0.3, 30.0, kv=(85000, 91000))]})])
    assert rep["kv_solo"] == [
        {"model": "x", "kv_capacity_tokens": 85000, "s4b_s": 19.0, "compiled": True},
        {"model": "y", "kv_capacity_tokens": 91000, "s4b_s": 0.3, "compiled": False},
    ]
    assert rep["cache_eviction"] == []
    assert "solo engine y: KV 91000 tokens, compiled False" in render(rep)
