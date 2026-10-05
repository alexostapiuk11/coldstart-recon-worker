import pytest

from placement_measure.engine import EngineSpec, engine_facts, log_tail

SPEC = EngineSpec("Qwen/Qwen3-4B", "1cfa9a72", 0.45, 2048, 256)


def test_serve_args_pin_every_measurement_flag():
    args = SPEC.serve_args()
    assert args[:8] == ["--revision", "1cfa9a72", "--gpu-memory-utilization", "0.45",
                        "--max-model-len", "2048", "--max-num-seqs", "256"]
    assert "--no-enable-prefix-caching" in args
    assert "--port" not in args


@pytest.mark.parametrize("extra", [("--max_num_seqs", "8"), ("--revision=x",), ("--port", "9")])
def test_a_flag_the_spec_owns_cannot_come_back_through_extra_args(extra):
    with pytest.raises(ValueError, match="owns"):
        EngineSpec("Qwen/Qwen3-4B", "r", 0.45, 2048, 256, extra_args=extra)


@pytest.mark.parametrize("kwargs", [{"revision": ""}, {"gpu_memory_utilization": 1.5},
                                    {"max_model_len": 0}])
def test_an_unpinned_or_impossible_engine_is_refused(kwargs):
    base = {"model": "Qwen/Qwen3-4B", "revision": "r", "gpu_memory_utilization": 0.45,
            "max_model_len": 2048, "max_num_seqs": 256}
    with pytest.raises(ValueError):
        EngineSpec(**{**base, **kwargs})


def test_a_spec_round_trips_through_json_shapes():
    spec = EngineSpec("Qwen/Qwen3-4B", "r", 0.45, 2048, 256, extra_args=("--enable-sleep-mode",))
    assert EngineSpec.from_dict(spec.to_dict()) == spec

# The compile line vLLM 0.27.1 logs; tests/a4_fakes.py, written in Task 3, logs the same.
COMPILE_LINE = "(EngineCore pid=340) INFO 10-04 12:00:30 [monitor.py:53] torch.compile took {s} s in total"

def test_engine_facts_read_kv_capacity_compile_time_and_batch_limit():
    from sweep_fakes import KV_LINE, NON_DEFAULT_LINE

    facts = engine_facts([NON_DEFAULT_LINE, KV_LINE, COMPILE_LINE.format(s=0.33)])
    assert facts["kv_capacity_tokens"] == 35792
    assert facts["s4b_s"] == 0.33
    assert facts["max_num_seqs"] == 256


def test_the_log_tail_keeps_the_end_and_the_true_count():
    out = log_tail([f"line {i}" for i in range(500)])
    assert out["log_lines_total"] == 500
    assert out["log_tail"][-1] == "line 499"
    assert len(out["log_tail"]) == 200
