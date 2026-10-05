from a4_fakes import Clock

from placement_measure.metrics import running_from_text, wait_running


def test_running_requests_sum_every_series_and_ignore_comments():
    text = (
        "# HELP vllm:num_requests_running Number of requests in model execution batches.\n"
        'vllm:num_requests_running{engine="0",model_name="m"} 3.0\n'
        'vllm:num_requests_running{engine="1",model_name="m"} 2.0\n'
        'vllm:num_requests_running_total 99\n'
        'vllm:num_requests_waiting{engine="0"} 7.0\n'
    )
    assert running_from_text(text) == 5.0
    assert running_from_text("# nothing\n") is None


def test_wait_running_returns_once_the_load_is_reached():
    clock = Clock(0.0)

    class R:
        def __init__(self, n):
            self.text = f"vllm:num_requests_running 0\nvllm:num_requests_running{{e=\"0\"}} {n}\n"

        def raise_for_status(self):
            pass

    loads = iter([0, 2, 4, 8])
    out = wait_running("http://x", at_least=8, timeout_s=10, get=lambda url, timeout: R(next(loads)),
                       clock=clock, sleep=clock.sleep)
    assert out["reached"] and out["last"]["running"] == 8
