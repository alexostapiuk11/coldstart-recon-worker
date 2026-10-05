from multilora.sampler import GaugeSampler

SCRAPE = (
    'vllm:lora_requests_info{max_lora="4",running_lora_adapters="a01,a00",'
    'waiting_lora_adapters=""} 9.0\n'
)


def test_nothing_is_recorded_between_phases():
    s = GaugeSampler(lambda: SCRAPE, interval=1.0, clock=lambda: 5.0)
    s.sample_once()
    assert s.samples == []


def test_a_sample_is_tagged_with_the_current_phase():
    s = GaugeSampler(lambda: SCRAPE, interval=1.0, clock=lambda: 5.0)
    s.set_phase(2)
    s.sample_once()
    assert s.samples == [{"phase_index": 2, "t": 5.0, "running": ["a00", "a01"]}]


def test_a_failed_scrape_is_a_recorded_gap():
    def boom():
        raise OSError("connection refused")

    s = GaugeSampler(boom, interval=1.0, clock=lambda: 1.0)
    s.set_phase(0)
    s.sample_once()
    assert s.samples == [{"phase_index": 0, "t": 1.0, "running": None}]


def test_the_thread_samples_until_exit():
    s = GaugeSampler(lambda: SCRAPE, interval=0.01)
    s.set_phase(1)
    with s:
        import time

        time.sleep(0.1)
    count = len(s.samples)
    assert count >= 3
    assert all(x["phase_index"] == 1 for x in s.samples)
    import time

    time.sleep(0.05)
    assert len(s.samples) == count, "no samples after exit"
