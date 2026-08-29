from pathlib import Path

from coldstart.vllm_logs import parse_engine_log

FIXTURE = Path("fixtures/vllm_logs/startup_0.log")
WARM_FIXTURE = Path("fixtures/vllm_logs/startup_1.log")


def test_parses_the_real_capture():
    result = parse_engine_log(FIXTURE.read_text())
    assert result.phases, "no phases parsed from the real capture"
    for name, seconds in result.phases.items():
        assert name in {"S4a", "S4b", "S4c", "S4d", "S4e"}
        assert seconds >= 0.0


def test_parses_the_three_subphases_this_version_delineates():
    p = parse_engine_log(FIXTURE.read_text()).phases
    assert p["S4b"] == 38.96
    assert p["S4c"] == 0.16
    assert p["S4e"] == 6.0


def test_subphases_without_a_duration_line_are_merged_not_zero():
    """S4a and S4d have no duration line in this version. Absent, never 0.0 —
    a zero would be indistinguishable from a real instantaneous phase."""
    r = parse_engine_log(FIXTURE.read_text())
    assert "S4a" not in r.phases
    assert "S4d" not in r.phases
    assert set(r.merged) == {"S4a", "S4d"}


def test_s4b_is_the_total_not_a_partial_compile_line():
    """The log also carries 'Compiling a graph ... takes 26.37 s' and 'Dynamo
    bytecode transform time: 7.43 s'. T_compile is the total, not a component."""
    assert parse_engine_log(FIXTURE.read_text()).phases["S4b"] == 38.96


def test_warm_compile_cache_still_parses():
    """A cache hit reports 0.30 s. Must parse, not be mistaken for absent."""
    p = parse_engine_log(WARM_FIXTURE.read_text()).phases
    assert p["S4b"] == 0.30


def test_extracts_kv_capacity_tokens_directly():
    """This version reports token capacity directly and emits no block count
    or block size, so the capacity must not be reconstructed by multiplication."""
    info = parse_engine_log(FIXTURE.read_text()).engine_info
    assert info["kv_capacity_tokens"] == 35792
    assert "kv_cache_blocks" not in info
    assert "block_size" not in info


def test_extracts_engine_version_and_model():
    info = parse_engine_log(FIXTURE.read_text()).engine_info
    assert info["vllm_version"] == "0.27.1"
    assert info["model"] == "Qwen/Qwen3-8B"


def test_unparseable_text_yields_empty_phases_not_an_exception():
    result = parse_engine_log("nothing useful here\nat all\n")
    assert result.phases == {}
    assert result.engine_info == {}
    assert result.merged == []


def test_merged_phases_are_reported():
    assert isinstance(parse_engine_log(FIXTURE.read_text()).merged, list)


def test_progress_bar_lines_are_not_mistaken_for_phases():
    """~1 line in 6 is a tqdm bar carrying 'it/s' and percentages."""
    bars = (
        "Capturing CUDA graphs (PIECEWISE):  47%|####  | 24/51 [00:00<00:00, 40.22it/s]\n"
        "Loading safetensors checkpoint shards:  40% Completed | 2/5 [00:01<00:02,  1.11it/s]\n"
    )
    assert parse_engine_log(bars).phases == {}
