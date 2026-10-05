from pathlib import Path

from multilora.engine import compile_state, engine_facts

LOGS = Path(__file__).resolve().parents[1] / "fixtures" / "vllm_logs"


def _lines(name: str) -> list[str]:
    return (LOGS / name).read_text().splitlines()


def test_a_first_ever_compile_is_cold_and_names_its_cache_directory():
    facts = engine_facts(_lines("startup_0.log"))
    assert facts["compile_state"] == "cold"
    assert facts["s4b_seconds"] == 38.96
    assert facts["kv_capacity_tokens"] == 35_792
    assert facts["cache_dir"].endswith("/torch_compile_cache/905735a5a3/rank_0_0/backbone")


def test_a_cache_hit_is_warm():
    facts = engine_facts(_lines("startup_1.log"))
    assert facts["compile_state"] == "warm"
    assert facts["kv_capacity_tokens"] == 43_040


def test_a_log_without_a_compile_line_is_unknown_not_warm():
    assert engine_facts(["some unrelated line"])["compile_state"] == "unknown"


def test_the_threshold_is_artifact_ones_priming_criterion():
    assert compile_state(0.99) == "warm"
    assert compile_state(1.0) == "cold"
    assert compile_state(None) == "unknown"
