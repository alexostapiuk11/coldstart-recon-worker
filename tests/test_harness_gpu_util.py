"""The nvidia-smi sampler, with the command runner faked: no GPU here."""

import subprocess
import threading
import time

import pytest

from harness.gpu_util import DEFAULT_INTERVAL_S, QUERY, GpuUtilSampler


class FakeSmi:
    def __init__(self, outputs, returncode=0, delay=0.0):
        self.outputs = list(outputs)
        self.returncode = returncode
        self.delay = delay
        self.calls = []
        self.lock = threading.Lock()
        self.second_call = threading.Event()
        self.in_call = threading.Event()

    def __call__(self, cmd, **kwargs):
        with self.lock:
            self.calls.append((cmd, kwargs))
            out = self.outputs.pop(0) if len(self.outputs) > 1 else self.outputs[0]
            if len(self.calls) >= 2:
                self.second_call.set()
        self.in_call.set()
        if self.delay:
            time.sleep(self.delay)  # a slow nvidia-smi, still running when the block ends
        return subprocess.CompletedProcess(cmd, self.returncode, out, "boom")


class RecordingStop:
    """Stands in for the sampler's stop Event: records each wait, stops after `n`."""

    def __init__(self, n):
        self.n = n
        self.waits = []

    def wait(self, timeout):
        self.waits.append(timeout)
        return len(self.waits) >= self.n

    def set(self):
        pass

    def clear(self):
        pass


def _clock(values):
    it = iter(values)
    return lambda: next(it)


def test_the_default_interval_is_half_a_second():
    assert DEFAULT_INTERVAL_S == 0.5
    assert GpuUtilSampler(run=FakeSmi(["1"])).interval == 0.5


def test_the_loop_waits_one_interval_between_samples_without_real_time():
    smi = FakeSmi(["20", "30", "40"])
    sampler = GpuUtilSampler(run=smi)
    sampler._stop = RecordingStop(3)
    sampler._loop()
    assert sampler._stop.waits == [0.5, 0.5, 0.5]
    assert len(sampler.samples) == 3


def test_a_custom_interval_is_the_one_waited():
    sampler = GpuUtilSampler(interval=0.125, run=FakeSmi(["20"]))
    sampler._stop = RecordingStop(1)
    sampler._loop()
    assert sampler._stop.waits == [0.125]


def test_the_query_is_utilization_gpu_for_one_gpu_without_units():
    smi = FakeSmi(["37\n"])
    sampler = GpuUtilSampler(run=smi, gpu_index=0)
    sampler.sample_once()
    cmd, kwargs = smi.calls[0]
    assert cmd == [*QUERY, "--id=0"]
    assert "--query-gpu=utilization.gpu" in cmd
    assert "--format=csv,noheader,nounits" in cmd
    assert kwargs["check"] is False
    assert kwargs["timeout"] == 5.0


def test_samples_keep_the_raw_text_and_the_time_since_start():
    sampler = GpuUtilSampler(run=FakeSmi(["37\n"]), clock=_clock([100.0, 100.5]))
    assert sampler.sample_once() == {"t_s": 0.5, "raw": "37", "util_pct": 37.0}


def test_the_run_summary_is_the_median_as_a_fraction():
    sampler = GpuUtilSampler(run=FakeSmi(["10", "90", "50"]))
    for _ in range(3):
        sampler.sample_once()
    assert sampler.median_fraction() == pytest.approx(0.5)


def test_the_summary_is_the_median_not_the_mean():
    # mean is 40 %, median is 10 %: the ramp-up edge must not drag the figure
    sampler = GpuUtilSampler(run=FakeSmi(["10", "10", "100"]))
    for _ in range(3):
        sampler.sample_once()
    assert sampler.median_fraction() == pytest.approx(0.10)


def test_the_fraction_is_zero_to_one_not_a_percentage():
    sampler = GpuUtilSampler(run=FakeSmi(["100"]))
    sampler.sample_once()
    assert sampler.median_fraction() == pytest.approx(1.0)
    assert sampler.summary()["gpu_util"] <= 1.0


@pytest.mark.parametrize("raw", ["0", "100"])
def test_the_bounds_of_the_range_are_readable(raw):
    sample = GpuUtilSampler(run=FakeSmi([raw])).sample_once()
    assert sample["util_pct"] == float(raw)
    assert "error" not in sample


@pytest.mark.parametrize("raw", ["[N/A]", "137", "-1", "40\n41", "", "abc"])
def test_an_unreadable_sample_is_kept_but_never_counted(raw):
    sampler = GpuUtilSampler(run=FakeSmi([raw, "80"]))
    bad = sampler.sample_once()
    sampler.sample_once()
    assert bad["util_pct"] is None
    assert "error" in bad
    assert bad["raw"] == raw.strip()
    assert sampler.median_fraction() == pytest.approx(0.8)
    assert sampler.summary()["n_valid"] == 1
    assert sampler.summary()["n_samples"] == 2


def test_a_run_of_only_unreadable_samples_reports_none_not_zero():
    sampler = GpuUtilSampler(run=FakeSmi(["[N/A]"]))
    sampler.sample_once()
    assert sampler.median_fraction() is None
    assert sampler.summary()["gpu_util"] is None


def test_a_failing_nvidia_smi_is_a_sample_with_an_error_not_a_raise():
    def run(cmd, **kwargs):
        raise FileNotFoundError("nvidia-smi")

    sampler = GpuUtilSampler(run=run)
    sample = sampler.sample_once()
    assert sample["util_pct"] is None
    assert "FileNotFoundError" in sample["error"]
    assert sampler.median_fraction() is None


def test_a_nonzero_exit_is_recorded_with_its_stderr():
    sampler = GpuUtilSampler(run=FakeSmi(["50"], returncode=9))
    assert sampler.sample_once()["error"] == "exit 9: boom"


def test_the_thread_samples_from_entry_and_stops_at_exit():
    smi = FakeSmi(["42"])
    with GpuUtilSampler(interval=0.01, run=smi) as sampler:
        assert smi.second_call.wait(timeout=5.0), "the thread never took a second sample"
    calls_at_exit = len(smi.calls)
    assert calls_at_exit >= 2
    assert not sampler._thread.is_alive()
    # joined, so nothing can still be sampling; a short real wait would only add flake
    assert len(smi.calls) == calls_at_exit, "sampling continued after the run ended"
    assert sampler.summary()["gpu_util"] == pytest.approx(0.42)
    assert len(sampler.summary()["samples"]) == calls_at_exit


def test_exit_joins_the_thread_even_while_a_query_is_in_flight():
    smi = FakeSmi(["42"], delay=0.2)
    with GpuUtilSampler(interval=0.01, run=smi) as sampler:
        assert smi.in_call.wait(timeout=5.0)
    # the query is still running when the block ends; exit must wait for it
    assert not sampler._thread.is_alive()


def test_a_run_shorter_than_one_interval_still_gets_a_sample():
    with GpuUtilSampler(interval=60.0, run=FakeSmi(["70"])) as sampler:
        pass
    assert sampler.summary()["n_valid"] == 1
