"""The LB probe and its shared pieces, with no network."""

import sys
from pathlib import Path
from typing import ClassVar

import pytest
import requests

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import a2_lb_common as common
import a2_lb_probe as probe

from harness.open_loop import Outcome


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("the probe test touched the network")
    monkeypatch.setattr(requests, "get", refuse)
    monkeypatch.setattr(requests, "post", refuse)


def test_the_url_and_payload_match_the_curves_request_shape():
    assert common.lb_url("abc123") == "https://abc123.api.runpod.ai/v1/completions"
    p = common.payload()
    assert len(p["prompt"]) == 13 and all(isinstance(t, int) for t in p["prompt"])
    assert p["max_tokens"] == 16 and p["ignore_eos"] is True
    assert "temperature" not in p and p["model"] == "Qwen/Qwen3-8B"


def test_constant_rate_spaces_requests_evenly():
    s = common.constant_rate(4.0, 2.0)
    assert s == (0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75)


def _o(i, status=200, worker="w1", client=0.5, server_ms="300.0", sent=None):
    sent = i * 0.1 if sent is None else sent
    headers = {} if worker is None else {common.WORKER: worker, common.SERVER_LATENCY: server_ms}
    return Outcome(i, i * 0.1, sent, client if status else None, status, headers,
                   None if status else "err")


def test_summarize_counts_shares_latencies_and_jitter():
    outs = [_o(0), _o(1, worker="w2"), _o(2, worker="w2"), _o(3, status=503), _o(4, sent=0.9)]
    s = common.summarize(outs)
    assert s["requests"] == 5 and s["non_200"] == 1
    assert s["worker_share"] == {"w1": 0.5, "w2": 0.5}
    assert s["client_p50_s"] == pytest.approx(0.5)
    assert s["server_p50_s"] == pytest.approx(0.3)
    assert s["client_minus_server_p50_s"] == pytest.approx(0.2)
    assert s["max_jitter_s"] == pytest.approx(0.5)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class FakeReplay:
    """Answers each warm-up chunk from a script of worker ids.

    None answers 503; "headerless" answers 200 without the worker header. Each
    call advances `clock` by `seconds`, so a chunk that hangs shows as wall time.
    """

    def __init__(self, chunks, clock=None, seconds=0.0):
        self.chunks = list(chunks)
        self.kwargs = []
        self.clock = clock
        self.seconds = seconds

    def __call__(self, schedule, send, **kw):
        self.kwargs.append(kw)
        if self.clock is not None:
            self.clock.t += self.seconds
        workers = self.chunks.pop(0)
        outs = []
        for i, (t, w) in enumerate(zip(schedule, workers * len(schedule), strict=False)):
            headers = {common.WORKER: w} if w and w != "headerless" else {}
            outs.append(Outcome(i, t, t, 0.3, 200 if w else 503, headers))
        return outs


def _warm(rep, clock, **kw):
    args = {"workers": 2, "rps": 2.0, "min_clean": 30.0, "max_seconds": 600.0,
            "chunk_seconds": 5.0, "replay_fn": rep, "clock": clock}
    args.update(kw)
    return common.warm_up(lambda i: (200, {}), **args)


def test_warm_up_returns_once_all_workers_answered_cleanly_long_enough():
    clock = Clock()
    rep = FakeReplay([["w1"]] + [["w1", "w2"]] * 7, clock, 5.0)
    summary = {}
    assert _warm(rep, clock, summary_out=summary) == ["w1", "w2"]
    # 30 s of clean chunks at 5 s each is 6 chunks; returning earlier would skip min_clean
    assert len(rep.kwargs) == 6 and len(rep.chunks) == 2
    assert rep.kwargs[0] == {"max_in_flight": 64, "start_delay": 0.1}
    assert summary["worker_share"] == {"w1": 0.5, "w2": 0.5} and summary["non_200"] == 0


def test_a_non_200_chunk_resets_the_clean_streak():
    clock = Clock()
    rep = FakeReplay([["w1", "w2"]] * 3 + [[None]] + [["w1", "w2"]] * 8, clock, 5.0)
    assert _warm(rep, clock) == ["w1", "w2"]
    assert len(rep.kwargs) == 3 + 1 + 6


def test_warm_up_refuses_more_workers_than_pinned():
    clock = Clock()
    rep = FakeReplay([["w1", "w2", "w3"]], clock, 5.0)
    with pytest.raises(RuntimeError, match="3 distinct workers"):
        _warm(rep, clock)


def test_a_slow_chunk_ends_warm_up_on_wall_time_not_chunk_count():
    clock = Clock()
    rep = FakeReplay([["w1"]] * 10, clock, 400.0)
    with pytest.raises(TimeoutError, match="1 of 2"):
        _warm(rep, clock, max_seconds=900.0)
    # 400 s per chunk: the deadline passes after the third, not after 900 / 5 chunks
    assert len(rep.kwargs) == 3


def test_warm_up_checks_the_deadline_before_the_first_chunk():
    clock = Clock()
    rep = FakeReplay([["w1", "w2"]], clock, 5.0)
    with pytest.raises(TimeoutError):
        _warm(rep, clock, max_seconds=0.0)
    assert rep.kwargs == []


def test_warm_up_fails_fast_when_200s_never_carry_the_worker_header():
    clock = Clock()
    rep = FakeReplay([["headerless"]] * 10, clock, 5.0)
    with pytest.raises(RuntimeError, match="x-a2-worker"):
        _warm(rep, clock)
    assert len(rep.kwargs) == 6  # at min_clean, long before the 600 s deadline


def test_acceptance_reads_the_amendments_three_conditions():
    ok = {"non_200": 0, "errors": 0, "worker_share": {"a": 0.5, "b": 0.5}, "max_jitter_s": 0.1}
    assert probe.accept(ok, workers=2) == (True, [])
    bad = {"non_200": 2, "errors": 0, "worker_share": {"a": 0.8, "b": 0.2}, "max_jitter_s": 0.4}
    passed, why = probe.accept(bad, workers=2)
    assert not passed and len(why) == 3


def test_acceptance_single_conditions_and_exact_boundaries():
    base = {"non_200": 0, "errors": 0, "worker_share": {"a": 0.5, "b": 0.5}, "max_jitter_s": 0.1}
    passed, why = probe.accept({**base, "errors": 1}, workers=2)
    assert not passed and len(why) == 1 and "errors" in why[0]
    passed, why = probe.accept({**base, "worker_share": {"a": 1.0}}, workers=2)
    assert not passed and len(why) == 1 and "worker shares" in why[0]
    passed, why = probe.accept({**base, "max_jitter_s": 0.26}, workers=2)
    assert not passed and len(why) == 1 and "jitter" in why[0]
    edge = {**base, "worker_share": {"a": 0.35, "b": 0.65}, "max_jitter_s": 0.25}
    assert probe.accept(edge, workers=2) == (True, [])
    assert probe.accept({**base, "worker_share": {}}, workers=2)[0] is False


def test_summarize_with_no_200s_has_no_shares_or_latencies():
    s = common.summarize([_o(0, status=503), Outcome(1, 0.1, 0.1, None, None, {}, "boom")])
    assert s["requests"] == 2 and s["worker_share"] == {}
    assert s["client_p50_s"] is None and s["server_p50_s"] is None
    assert s["client_minus_server_p50_s"] is None and s["headerless_200"] == 0
    assert s["non_200"] == 1 and s["errors"] == 1


def test_summarize_counts_200s_without_the_worker_header():
    assert common.summarize([_o(0), _o(1, worker=None)])["headerless_200"] == 1


def test_the_ladder_and_thresholds_are_the_amendments():
    assert probe.RATES == (25.0, 50.0, 100.0, 200.0, 300.0, 450.0)
    assert probe.STEP_SECONDS == 30.0
    assert probe.MIN_WORKER_SHARE == 0.35 and probe.MAX_JITTER_S == 0.25
    assert probe.LADDER_MAX_IN_FLIGHT == 4096 and probe.EARLY_STOP_FAILURE_FRACTION == 0.5


class FakeResource:
    RLIMIT_NOFILE = 8
    RLIM_INFINITY = 2**63 - 1

    def __init__(self, soft, hard, can_set=True):
        self.limits = (soft, hard)
        self.can_set = can_set
        self.sets = []

    def getrlimit(self, which):
        return self.limits

    def setrlimit(self, which, limits):
        self.sets.append(limits)
        if not self.can_set:
            raise ValueError("current limit exceeds maximum limit")
        self.limits = limits


def test_the_open_files_limit_is_left_alone_when_high_enough():
    res = FakeResource(10240, 10240)
    common.ensure_fd_limit(8192, res)
    assert res.sets == []


def test_a_low_soft_limit_is_raised_up_to_the_hard_limit():
    res = FakeResource(256, FakeResource.RLIM_INFINITY)
    common.ensure_fd_limit(8192, res)
    assert res.limits == (8192, FakeResource.RLIM_INFINITY)
    res = FakeResource(256, 9000)
    common.ensure_fd_limit(8192, res)
    assert res.limits == (8192, 9000)


def test_a_limit_that_cannot_be_raised_is_refused_naming_the_sockets():
    for res in (FakeResource(256, 1024), FakeResource(256, 10240, can_set=False)):
        with pytest.raises(SystemExit, match="pool threads each hold a socket.*ulimit -n 8192"):
            common.ensure_fd_limit(8192, res)


# --- main(), with a fake pin and a fake replay -------------------------------------

KEY = "sk-fake-key-for-tests-0123"


class FakePin:
    instances: ClassVar[list] = []

    def __init__(self, endpoint_id, api_key, *, workers):
        self.log = []
        self.release_error = None
        FakePin.instances.append(self)

    def preflight(self):
        self.log.append("preflight")
        return {"workersMin": 0, "workersMax": 2}

    def __enter__(self):
        self.log.append("pin")
        return self

    def __exit__(self, *exc):
        self.log.append("release")
        if self.release_error:
            raise self.release_error
        return False


@pytest.fixture
def rig(monkeypatch, tmp_path):
    FakePin.instances = []
    monkeypatch.setenv("RUNPOD_API_KEY", KEY)
    monkeypatch.setenv("RUNPOD_A2_LB_ENDPOINT_ID", "ep123")
    monkeypatch.setattr(probe, "WorkerPin", FakePin)
    monkeypatch.setattr(probe, "unwind_on_hangup_and_term", lambda: None)
    monkeypatch.setattr(probe, "ensure_fd_limit", lambda needed: None)
    monkeypatch.setattr(probe, "sender", lambda *a: (lambda i: (200, {})))
    monkeypatch.setattr(probe, "warm_up",
                        lambda send, summary_out=None, **kw: (summary_out.update(
                            {"requests": 3, "headerless_200": 0}), ["w1", "w2"])[1])
    monkeypatch.setattr(probe, "RATES", (10.0, 20.0, 30.0))
    monkeypatch.setattr(probe, "STEP_SECONDS", 1.0)
    calls = []

    def set_replay(behaviour):
        def fake(schedule, send, **kw):
            calls.append(kw)
            return behaviour(len(calls), schedule)
        monkeypatch.setattr(probe, "replay", fake)

    def good(n, schedule):
        return [Outcome(i, t, t, 0.5, 200, {common.WORKER: "w1" if i % 2 else "w2",
                                            common.SERVER_LATENCY: "300"})
                for i, t in enumerate(schedule)]

    set_replay(good)
    out = tmp_path / "probe"
    return {"out": out, "calls": calls, "set_replay": set_replay, "good": good}


def _summary(out):
    import json
    return json.loads((out / "summary.json").read_text())


def test_main_runs_the_ladder_and_leaves_a_complete_summary(rig, capsys):
    probe.main(["--out", str(rig["out"])])
    s = _summary(rig["out"])
    assert s["status"] == "complete" and s["release"] == "ok" and s["workers"] == ["w1", "w2"]
    assert list(s["steps"]) == ["10", "20", "30"] and s["warmup"]["requests"] == 3
    assert all(kw == {"max_in_flight": 4096} for kw in rig["calls"])
    assert FakePin.instances[0].log == ["pin", "release"]
    assert "[accept] PASS" in capsys.readouterr().out


def test_main_refuses_a_non_empty_out_dir_before_pinning(rig):
    rig["out"].mkdir()
    (rig["out"] / "old.json").write_text("{}")
    with pytest.raises(SystemExit, match="not empty"):
        probe.main(["--out", str(rig["out"])])
    assert all("pin" not in p.log for p in FakePin.instances)
    assert rig["calls"] == []


def test_main_preflight_only_writes_nothing(rig, capsys):
    probe.main(["--out", str(rig["out"]), "--preflight-only"])
    assert not rig["out"].exists() and rig["calls"] == []
    assert FakePin.instances[0].log == ["preflight"]
    assert "nothing written" in capsys.readouterr().out


def test_a_mid_ladder_failure_releases_and_keeps_the_completed_steps(rig):
    def fails_second(n, schedule):
        if n == 2:
            raise RuntimeError("the driver broke")
        return rig["good"](n, schedule)

    rig["set_replay"](fails_second)
    with pytest.raises(RuntimeError, match="driver broke"):
        probe.main(["--out", str(rig["out"])])
    s = _summary(rig["out"])
    assert list(s["steps"]) == ["10"] and s["status"].startswith("stopped: RuntimeError")
    assert s["release"] == "ok" and FakePin.instances[0].log == ["pin", "release"]


def test_a_majority_failing_step_stops_the_ladder_and_acceptance_is_not_evaluable(rig, capsys):
    def breaks_second(n, schedule):
        if n == 2:
            return [Outcome(i, t, t, 0.1, 503, {}) for i, t in enumerate(schedule)]
        return rig["good"](n, schedule)

    rig["set_replay"](breaks_second)
    probe.main(["--out", str(rig["out"])])
    s = _summary(rig["out"])
    assert len(rig["calls"]) == 2 and list(s["steps"]) == ["10", "20"]
    assert s["status"].startswith("stopped: 100% of the 20 req/s step")
    assert FakePin.instances[0].log == ["pin", "release"]
    out = capsys.readouterr().out
    assert "[accept] not evaluable" in out and "[accept] PASS" not in out


def test_the_top_step_failing_is_evaluated_not_skipped(rig, capsys):
    def breaks_last(n, schedule):
        if n == 3:
            return [Outcome(i, t, t, 0.1, 503, {}) for i, t in enumerate(schedule)]
        return rig["good"](n, schedule)

    rig["set_replay"](breaks_last)
    probe.main(["--out", str(rig["out"])])
    assert _summary(rig["out"])["status"] == "complete"
    assert "[accept] FAIL" in capsys.readouterr().out


def test_a_release_failure_after_a_complete_ladder_still_leaves_the_summary(rig, monkeypatch):
    class FailingPin(FakePin):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.release_error = probe.ReleaseFailed("RELEASE FAILED: set it by hand")

    monkeypatch.setattr(probe, "WorkerPin", FailingPin)
    with pytest.raises(probe.ReleaseFailed):
        probe.main(["--out", str(rig["out"])])
    s = _summary(rig["out"])
    assert s["status"] == "complete" and s["release"] == "FAILED"
    assert "RELEASE FAILED" in s["error"] and list(s["steps"]) == ["10", "20", "30"]


def test_a_warm_up_failure_is_recorded_with_its_last_chunk(rig, monkeypatch):
    def failing(send, summary_out=None, **kw):
        summary_out.update({"requests": 100, "non_200": 100})
        raise TimeoutError("0 of 2 pinned workers answered")

    monkeypatch.setattr(probe, "warm_up", failing)
    with pytest.raises(TimeoutError):
        probe.main(["--out", str(rig["out"])])
    s = _summary(rig["out"])
    assert s["status"].startswith("stopped: TimeoutError") and s["warmup"]["non_200"] == 100
    assert s["steps"] == {} and FakePin.instances[0].log == ["pin", "release"]


def test_the_api_key_is_written_nowhere(rig, capsys):
    probe.main(["--out", str(rig["out"])])
    for f in rig["out"].iterdir():
        assert KEY not in f.read_text()
    captured = capsys.readouterr()
    assert KEY not in captured.out + captured.err


def _with_resource(monkeypatch, res):
    """Route main()'s ensure_fd_limit(8192) at a fake resource module; returns the call log."""
    calls = []

    def fake(needed):
        calls.append(needed)
        common.ensure_fd_limit(needed, res)

    monkeypatch.setattr(probe, "ensure_fd_limit", fake)
    return calls


def test_main_refuses_a_too_low_open_files_limit_before_any_pin_or_write(rig, monkeypatch):
    _with_resource(monkeypatch, FakeResource(256, 1024))  # the hard limit is below the need
    with pytest.raises(SystemExit, match="pool threads each hold a socket.*ulimit -n 8192"):
        probe.main(["--out", str(rig["out"])])
    assert FakePin.instances[0].log == [] and rig["calls"] == []
    assert not rig["out"].exists()


def test_main_raises_the_soft_limit_before_pinning(rig, monkeypatch):
    res = FakeResource(256, FakeResource.RLIM_INFINITY)
    calls = _with_resource(monkeypatch, res)
    probe.main(["--out", str(rig["out"])])
    assert calls == [8192] and res.limits[0] == 8192


def test_preflight_only_does_not_touch_the_open_files_limit(rig, monkeypatch):
    calls = _with_resource(monkeypatch, FakeResource(256, 1024))
    probe.main(["--out", str(rig["out"]), "--preflight-only"])
    assert calls == []
