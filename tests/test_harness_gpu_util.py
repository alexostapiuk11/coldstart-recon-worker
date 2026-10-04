"""The nvidia-smi sampler, with the command runner faked: no GPU here."""

import subprocess
import threading
import time

import pytest

from harness.gpu_util import DEFAULT_INTERVAL_S, QUERY, GpuUtilSampler, median_in_window


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


def _clock_then_steady(values):
    """The listed readings in order, then the last one forever: for a test that
    lets the real thread run and cannot count its clock reads."""
    it = iter(values)
    last = [values[-1]]

    def read():
        last[0] = next(it, last[0])
        return last[0]

    return read


class StuckThread:
    """A sampling thread whose join timed out: still alive when asked."""

    def join(self, timeout=None):
        pass

    def is_alive(self):
        return True


def test_the_default_interval_is_half_a_second():
    assert DEFAULT_INTERVAL_S == 0.5
    assert GpuUtilSampler(run=FakeSmi(["1"])).interval == 0.5


def test_the_loop_waits_for_the_next_point_of_a_fixed_grid_not_a_fixed_gap():
    # Each sample reads the clock three times (start, end of query, loop). The
    # sampler started at 100.0, so the grid is 100.5, 101.0, 101.5: a query that
    # takes time shortens the wait after it instead of pushing every later
    # sample back, and a query that overruns a grid point waits 0, not less.
    clock = _clock([100.0, 100.0, 100.1, 100.15, 100.5, 100.6, 100.7, 101.0, 102.0, 102.0])
    sampler = GpuUtilSampler(run=FakeSmi(["20", "30", "40"]), clock=clock)
    sampler._stop = RecordingStop(3)
    sampler._loop()
    assert sampler._stop.waits == pytest.approx([0.35, 0.3, 0.0])
    assert len(sampler.samples) == 3


def test_a_custom_interval_is_the_grid_step():
    sampler = GpuUtilSampler(
        interval=0.125, run=FakeSmi(["20"]), clock=_clock([0.0, 0.0, 0.0, 0.0])
    )
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


def test_samples_keep_the_raw_text_the_time_since_start_and_how_long_the_query_took():
    sampler = GpuUtilSampler(run=FakeSmi(["37\n"]), clock=_clock([100.0, 100.5, 100.75]))
    assert sampler.sample_once() == {
        "t_s": 0.5, "query_s": 0.25, "raw": "37", "util_pct": 37.0,
    }


def test_a_failed_query_still_records_how_long_it_took():
    def run(cmd, **kwargs):
        raise FileNotFoundError("nvidia-smi")

    sampler = GpuUtilSampler(run=run, clock=_clock([0.0, 1.0, 4.0]))
    assert sampler.sample_once()["query_s"] == 3.0


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


def test_entering_the_block_restarts_the_sampler_clock():
    # constructed at 100.0, entered at 200.0: sample times and the absolute start
    # in the summary must count from entry, or every sample is placed 100 s late
    clock = _clock_then_steady([100.0, 200.0, 200.5])
    with GpuUtilSampler(interval=60.0, run=FakeSmi(["42"]), clock=clock) as sampler:
        pass
    assert sampler.summary()["t0_monotonic"] == 200.0
    assert sampler.samples[0]["t_s"] == 0.5


def test_the_summary_says_when_it_started_and_ended_on_the_clock_the_samples_use():
    clock = _clock_then_steady([100.0, 200.0, 200.5, 200.5, 207.0])
    with GpuUtilSampler(interval=60.0, run=FakeSmi(["42"]), clock=clock) as sampler:
        pass
    summary = sampler.summary()
    assert summary["t0_monotonic"] == 200.0
    assert summary["t_exit_s"] == 7.0


def test_a_normal_exit_reports_the_thread_stopped():
    with GpuUtilSampler(interval=60.0, run=FakeSmi(["70"])) as sampler:
        pass
    assert sampler.summary()["thread_stopped"] is True


def test_a_join_that_timed_out_is_reported_not_hidden():
    sampler = GpuUtilSampler(run=FakeSmi(["70"]))
    sampler._thread = StuckThread()
    sampler.__exit__(None, None, None)
    assert sampler.summary()["thread_stopped"] is False


def _sample(t_s, pct):
    return {"t_s": t_s, "query_s": 0.05, "raw": str(pct), "util_pct": float(pct)}


def _gpu(samples, *, t0=1000.0, t_exit_s=30.0):
    return {"t0_monotonic": t0, "t_exit_s": t_exit_s, "interval_s": 0.5, "samples": samples}


def test_only_the_samples_inside_the_span_enter_the_windowed_median():
    gpu = _gpu([_sample(1, 0), _sample(2, 0), _sample(10, 90), _sample(11, 90), _sample(25, 0)])
    out = median_in_window(gpu, 1008.0, 1020.0)
    assert out == {"gpu_util": pytest.approx(0.9), "n_in_span": 2, "n_outside_span": 3}


def test_the_span_edges_are_inside_and_unreadable_samples_are_not_counted():
    bad = {"t_s": 10.0, "query_s": 0.05, "raw": "[N/A]", "util_pct": None, "error": "x"}
    gpu = _gpu([_sample(8, 40), bad, _sample(20, 60), _sample(21, 0)])
    out = median_in_window(gpu, 1008.0, 1020.0)
    assert out["n_in_span"] == 2
    assert out["n_outside_span"] == 1
    assert out["gpu_util"] == pytest.approx(0.5)


def test_a_span_with_no_readable_sample_has_no_median_rather_than_borrowing_one():
    out = median_in_window(_gpu([_sample(1, 0), _sample(25, 0)]), 1008.0, 1020.0)
    assert out["gpu_util"] is None
    assert (out["n_in_span"], out["n_outside_span"]) == (0, 2)


def test_a_span_outside_the_samplers_lifetime_means_the_clocks_disagree():
    # the tool's request times are 5000 s after the sampler's whole life: the two
    # processes are not on one clock, and assigning samples by time would be a guess
    with pytest.raises(ValueError, match="clock"):
        median_in_window(_gpu([_sample(1, 90)]), 6000.0, 6010.0)


def test_a_summary_without_an_absolute_start_cannot_be_windowed():
    with pytest.raises(ValueError, match="t0_monotonic"):
        median_in_window({"samples": [_sample(1, 90)]}, 1.0, 2.0)
