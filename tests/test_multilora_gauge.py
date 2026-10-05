from multilora.gauge import distinct_running, running_adapters
from multilora.records import InstanceRecord

SCRAPE = """# HELP vllm:lora_requests_info Running stats on lora requests.
# TYPE vllm:lora_requests_info gauge
vllm:lora_requests_info{max_lora="16",running_lora_adapters="a00",waiting_lora_adapters=""} 1.7590001e+09
vllm:lora_requests_info{max_lora="16",running_lora_adapters="a03,a01,a02",waiting_lora_adapters="a04"} 1.7590009e+09
vllm:lora_requests_info{max_lora="16",running_lora_adapters="",waiting_lora_adapters=""} 1.7590005e+09
vllm:num_requests_running{model_name="m"} 3.0
"""


def test_the_newest_series_is_the_current_state():
    assert running_adapters(SCRAPE) == ["a01", "a02", "a03"]


def test_an_absent_gauge_is_none_not_empty():
    assert running_adapters("vllm:num_requests_running 3.0\n") is None


def test_an_idle_scheduler_is_an_empty_list():
    idle = 'vllm:lora_requests_info{max_lora="4",running_lora_adapters="",waiting_lora_adapters=""} 5.0\n'
    assert running_adapters(idle) == []


def test_distinct_running_is_per_regime_and_skips_missing_samples():
    rec = InstanceRecord(
        1, 0, 0, "sweep-N4", "r", "ok", None, None, {},
        phases=[{"phase_index": 0, "regime": "spread"}, {"phase_index": 1, "regime": "concentrated"}],
        gauge_samples=[
            {"phase_index": 0, "t": 1.0, "running": ["a00", "a01", "a02"]},
            {"phase_index": 0, "t": 2.0, "running": None},
            {"phase_index": 1, "t": 3.0, "running": ["a00"]},
        ],
    )
    assert distinct_running(rec, "spread") == [3]
    assert distinct_running(rec, "concentrated") == [1]
