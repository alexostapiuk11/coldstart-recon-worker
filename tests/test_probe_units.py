import itertools
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

import probe as probe_mod

from coldstart.analysis import metrics
from coldstart.recorder import StageRecorder

CAPTURES = [ROOT / f"fixtures/vllm_logs/startup_{i}.log" for i in range(3)]

LOAD_LINE = (
    "(EngineCore pid=340) INFO 08-28 23:29:10 [model_runner.py:329] "
    "Model loading took 15.27 GiB and 36.382166 seconds"
)
ENGINE_UP_LINE = (
    "(EngineCore pid=340) INFO 08-28 23:30:03 [core.py:348] "
    "init engine (profile, create kv cache, warmup model) took 53.73 s (compilation: 38.96 s)"
)


# --- the pre-registered warmup trio is imported, never reimplemented ---------


def test_warmup_trio_is_imported_not_reimplemented():
    """Two copies of a pre-registered definition are two copies free to drift.

    Identity, not equality: a local re-definition with the same behaviour today
    would still pass an equality check and diverge later.
    """
    assert probe_mod.steady_state_latency is metrics.steady_state_latency
    assert probe_mod.warmup_penalty is metrics.warmup_penalty
    assert probe_mod.time_to_fast_index is metrics.time_to_fast_index
    assert probe_mod.FAST_TOLERANCE == metrics.FAST_TOLERANCE


# --- log predicates, taken from the real captures ---------------------------


def test_load_complete_matches_exactly_one_line_in_every_capture():
    for path in CAPTURES:
        hits = [ln for ln in path.read_text().splitlines() if probe_mod._is_load_complete(ln)]
        assert len(hits) == 1, f"{path.name}: {len(hits)} matches"


def test_engine_up_matches_exactly_one_line_in_every_capture():
    for path in CAPTURES:
        hits = [ln for ln in path.read_text().splitlines() if probe_mod._is_engine_up(ln)]
        assert len(hits) == 1, f"{path.name}: {len(hits)} matches"


def test_load_completes_before_the_engine_reports_up_in_every_capture():
    for path in CAPTURES:
        lines = path.read_text().splitlines()
        load = next(i for i, ln in enumerate(lines) if probe_mod._is_load_complete(ln))
        up = next(i for i, ln in enumerate(lines) if probe_mod._is_engine_up(ln))
        assert load < up, f"{path.name}: S4_end at {up} precedes S3_load_done at {load}"


def test_load_complete_is_not_the_weight_loader_line():
    """"Loading weights took 34.35 seconds" is an earlier, different event --
    the weight loader, not the model being resident on GPU."""
    assert probe_mod._is_load_complete(LOAD_LINE)
    assert not probe_mod._is_load_complete(
        "(EngineCore pid=340) INFO [default_loader.py:430] Loading weights took 34.35 seconds"
    )


def test_engine_up_is_not_the_api_server_starting():
    """S4_end is the engine's own init summary. The API server lines are S5:
    marking S4_end there would fold all of S5 into S4."""
    assert probe_mod._is_engine_up(ENGINE_UP_LINE)
    assert not probe_mod._is_engine_up(
        "(APIServer pid=130) INFO [api_server.py:682] Starting vLLM server on http://0.0.0.0:8000"
    )
    assert not probe_mod._is_engine_up("(APIServer pid=130) INFO:     Application startup complete.")


# --- run_probe, driven against the real capture -----------------------------


class _Unhealthy:
    status_code = 503


class _FakeResponse:
    status_code = 200

    def __init__(self, chunks=(b"a", b"b")):
        self._chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        return None

    def iter_lines(self):
        yield from self._chunks


class _FakeProc:
    def __init__(self, lines, drained):
        self._lines, self._drained = lines, drained
        self.stdout = self._gen()
        self.terminated = False

    def _gen(self):
        for line in self._lines:
            yield line + "\n"
        self._drained.set()

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        return None


@pytest.fixture
def fake_engine(monkeypatch):
    """Replays the real capture through run_probe with no GPU."""
    drained = threading.Event()
    lines = CAPTURES[0].read_text().splitlines()
    proc = _FakeProc(lines, drained)

    monkeypatch.setattr(probe_mod.subprocess, "Popen", lambda *a, **k: proc)
    # Health only answers once the log is fully drained, so the drain thread's
    # marks land before S5_ready exactly as they do on a real startup.
    monkeypatch.setattr(
        probe_mod.requests,
        "get",
        lambda *a, **k: _FakeResponse() if drained.is_set() else _Unhealthy(),
    )
    monkeypatch.setattr(probe_mod.requests, "post", lambda *a, **k: _FakeResponse())
    return proc


def _counter_recorder():
    """One tick per clock read, so every mark and dispatch is exact."""
    return StageRecorder(clock=itertools.count(0.0, 1.0).__next__)


def test_run_probe_marks_the_full_stage_sequence(fake_engine):
    rec = _counter_recorder()
    result = probe_mod.run_probe(rec, "Qwen/Qwen3-8B", health_timeout=10.0)
    assert result["healthy"] is True
    stages = [m["stage"] for m in result["clock_B"]["marks"]]
    for expected in (
        "S1_imports_done",
        "S2_acquisition_start",
        "S3_load_done",
        "S4_start",
        "S4_end",
        "S5_ready",
        "S6_request1_dispatch",
        "S6_first_token",
        "S7_warmup_done",
    ):
        assert expected in stages, f"missing {expected}"


def test_s4_bracket_is_strictly_inside_s3_and_s5(fake_engine):
    rec = _counter_recorder()
    result = probe_mod.run_probe(rec, "Qwen/Qwen3-8B", health_timeout=10.0)
    assert rec.at("S4_start") < rec.at("S4_end") < rec.at("S5_ready")

    # "Device init begins the instant weights land" cannot mean byte-equal
    # marks -- mark() reads the clock once per call, so two reads always
    # differ. The contract that is actually checkable is adjacency: S4_start
    # immediately follows S3_load_done with nothing in between, so no stage
    # can be smuggled into the gap.
    stages = [m["stage"] for m in result["clock_B"]["marks"]]
    assert stages.index("S4_start") == stages.index("S3_load_done") + 1
    assert rec.at("S4_start") >= rec.at("S3_load_done")


def test_every_warmup_record_carries_t_dispatch_mono(fake_engine):
    rec = _counter_recorder()
    result = probe_mod.run_probe(rec, "Qwen/Qwen3-8B", health_timeout=10.0)
    assert len(result["warmup"]) == probe_mod.WARMUP_REQUESTS
    for w in result["warmup"]:
        assert w["t_dispatch_mono"] is not None
        assert w["end_to_end"] >= 0.0


def test_request_one_dispatch_matches_the_s6_mark(fake_engine):
    """Both name the same instant on the same clock, from two call sites.

    They must not drift: metrics.t_fast_seconds subtracts t_dispatch_mono from
    the S7_warmup_done mark, so a different origin makes the tail negative.
    """
    rec = _counter_recorder()
    result = probe_mod.run_probe(rec, "Qwen/Qwen3-8B", health_timeout=10.0)
    dispatch = result["warmup"][0]["t_dispatch_mono"]
    mark = rec.at("S6_request1_dispatch")
    assert dispatch >= mark
    assert dispatch < rec.at("S6_first_token")


def test_t_fast_seconds_is_computable_from_the_probe_output(fake_engine):
    """The end-to-end point of the t_dispatch_mono contract: a real bundle
    must yield a T_fast, not the 'probe has not shipped' reason."""
    rec = _counter_recorder()
    result = probe_mod.run_probe(rec, "Qwen/Qwen3-8B", health_timeout=10.0)
    warmup = result["warmup"]
    steady = metrics.steady_state_latency(warmup)
    idx = metrics.time_to_fast_index(warmup, steady)
    marks = {m["stage"]: m["t_mono"] for m in result["clock_B"]["marks"]}
    value, reason = metrics.t_fast_seconds(
        warmup, idx, t_total_job=10_000.0, t_warmup_done_mono=marks["S7_warmup_done"]
    )
    assert reason is None, reason
    assert value is not None


def test_unhealthy_start_returns_no_warmup_and_terminates(monkeypatch):
    drained = threading.Event()
    proc = _FakeProc([], drained)
    monkeypatch.setattr(probe_mod.subprocess, "Popen", lambda *a, **k: proc)
    monkeypatch.setattr(probe_mod.requests, "get", lambda *a, **k: _Unhealthy())
    rec = _counter_recorder()
    result = probe_mod.run_probe(rec, "Qwen/Qwen3-8B", health_timeout=0.3)
    assert result["healthy"] is False
    assert result["warmup"] == []
    assert proc.terminated is True
    assert "derived" not in result
