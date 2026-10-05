"""The validation driver's record, slots, repeat flow and verdict, with no network."""

import gzip
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import ClassVar

import pytest
import requests

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import a2_validate as v
from a2_lb_common import SERVER_LATENCY, WORKER

from autoscale.service import ServiceCurve
from autoscale.sim import run_fixed_capacity
from autoscale.validation_schedule import build_schedule
from harness.open_loop import Outcome
from harness.runpod.pinning import ReleaseFailed
from harness.runpod.preflight import PreflightError

CURVE = ServiceCurve(points=[(0, 0.2, 0.0, 0.0), (1, 0.2, 50.0, 1.0), (8, 0.3, 300.0, 1.0)],
                     measured=True)
UNTIL = 200.0
KEY = "sk-fake-key-for-tests-0123"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("the validation test touched the network")
    monkeypatch.setattr(requests, "get", refuse)
    monkeypatch.setattr(requests, "post", refuse)


def _schedule():
    return build_schedule(CURVE, replicas=2, kind="step", until=UNTIL, drain=20.0, seed=1)


def _model_latencies(schedule):
    result = run_fixed_capacity(list(schedule), 2, CURVE, UNTIL)
    by_arrival = dict(result.completed_requests())
    return [by_arrival[t] for t in schedule]


def _outs(schedule, factor=1.0, *, status=200, workers=("w1", "w2"), drop_header_at=None,
          bad_header_at=None, drop_worker_at=None):
    lat = _model_latencies(schedule)
    outs = []
    for i, (t, lt) in enumerate(zip(schedule, lat, strict=True)):
        headers = {WORKER: workers[i % len(workers)], SERVER_LATENCY: f"{lt * factor * 1000:.3f}"}
        if i == drop_header_at:
            headers.pop(SERVER_LATENCY)
        if i == bad_header_at:
            headers[SERVER_LATENCY] = "not-a-number"
        if i == drop_worker_at:
            headers.pop(WORKER)
        outs.append(Outcome(i, t, t, lt * factor + 0.1, status, headers))
    return outs


def _record(schedule, outs, k=1, host_ids=("w1", "w2")):
    return v.record_from(outs, repeat=k, schedule=schedule, host_ids=list(host_ids),
                         endpoint_id="ep", template_id="tpl", started_at="2026-10-05T00:00:00Z",
                         replicas=2, until=UNTIL, seed=1, drain=20.0)


def test_a_clean_repeat_is_not_void_and_keeps_both_latencies():
    s = _schedule()
    rec = _record(s, _outs(s))
    assert rec["void"] == [] and rec["release"] == "ok"
    assert len(rec["server_latency_s"]) == len(rec["client_latency_s"]) == len(s)
    assert rec["client_latency_s"][0] == pytest.approx(rec["server_latency_s"][0] + 0.1)
    assert rec["seed"] == 1 and rec["drain"] == 20.0


def test_void_reasons_non_200_novel_worker_and_missing_header():
    s = _schedule()
    assert "without a 200" in " ".join(_record(s, _outs(s, status=503))["void"])
    assert "outside the pinned set" in " ".join(
        _record(s, _outs(s, workers=("w1", "w2", "w9")))["void"])
    missing = " ".join(_record(s, _outs(s, drop_header_at=3))["void"])
    assert "usable server-latency header (absent or unparseable)" in missing


def test_a_transport_error_row_is_a_non_200_void_reason():
    s = _schedule()
    outs = _outs(s)
    outs[5] = Outcome(5, s[5], s[5], None, None, {}, "ConnectionError: reset")
    void = " ".join(_record(s, outs)["void"])
    assert "1 requests without a 200 (1 of them transport errors)" in void


def test_an_unparseable_server_latency_header_is_void_not_a_crash():
    s = _schedule()
    rec = _record(s, _outs(s, bad_header_at=4))
    assert "usable server-latency header (absent or unparseable)" in " ".join(rec["void"])
    assert rec["server_latency_s"][4] is None


def test_a_200_without_the_worker_header_is_counted_not_voided():
    s = _schedule()
    rec = _record(s, _outs(s, drop_worker_at=2))
    assert rec["headerless_worker_200"] == 1 and rec["void"] == []
    assert _record(s, _outs(s))["headerless_worker_200"] == 0


def test_a_short_outcome_list_is_an_error_not_a_void_reason():
    s = _schedule()
    with pytest.raises(RuntimeError, match="cannot happen.*cannot be trusted"):
        _record(s, _outs(s)[:-1])


def test_a_short_replay_falls_back_with_the_raw_outcomes(tmp_path, monkeypatch):
    d = _fallback_dir(tmp_path, monkeypatch)
    s = _schedule()

    def short(sch, send):
        return _outs(s)[:-1]

    with pytest.raises(v.RecordLost, match="cannot be trusted") as info:
        _run(tmp_path, FakePin(), replay_fn=short)
    fallback = info.value.fallback
    assert fallback is not None and fallback.parent == d
    assert len(json.loads(fallback.read_text())["outcomes"]) == len(s) - 1
    assert not (tmp_path / "repeat-1.json.gz").exists()


def test_slots_never_overwrite_a_valid_repeat_and_allow_one_void_rerun(tmp_path):
    s = _schedule()
    path = v.prepare_slot(tmp_path, 1)
    v.write_record(path, _record(s, _outs(s, status=503)))
    again = v.prepare_slot(tmp_path, 1)
    assert (tmp_path / "repeat-1.void.json.gz").exists() and again == path
    v.write_record(path, _record(s, _outs(s, status=503)))
    with pytest.raises(SystemExit, match="not evaluable"):
        v.prepare_slot(tmp_path, 1)
    v.write_record(v.prepare_slot(tmp_path, 2), _record(s, _outs(s), k=2))
    with pytest.raises(SystemExit, match="never re-run"):
        v.prepare_slot(tmp_path, 2)


def test_check_slot_refuses_without_moving_anything(tmp_path):
    s = _schedule()
    path = v.prepare_slot(tmp_path, 1)
    v.write_record(path, _record(s, _outs(s, status=503)))
    v.check_slot(tmp_path, 1)
    assert path.exists() and not (tmp_path / "repeat-1.void.json.gz").exists()
    v.write_record(v.prepare_slot(tmp_path, 2), _record(s, _outs(s), k=2))
    with pytest.raises(SystemExit, match="never re-run"):
        v.check_slot(tmp_path, 2)


def test_a_record_is_written_atomically(tmp_path):
    s = _schedule()
    path = tmp_path / "repeat-1.json.gz"
    v.write_record(path, _record(s, _outs(s)))
    assert not list(tmp_path.glob("*.tmp")) and v.read_record(path)["repeat"] == 1


@pytest.mark.parametrize("fault", ["replace", "dump"])
def test_a_failed_write_leaves_the_previous_file_intact(tmp_path, monkeypatch, fault):
    s = _schedule()
    path = tmp_path / "repeat-1.json.gz"
    v.write_record(path, _record(s, _outs(s)))
    before = path.read_bytes()

    def boom(*a, **k):
        raise OSError("disk full")

    if fault == "replace":
        monkeypatch.setattr(v.os, "replace", boom)
    else:
        monkeypatch.setattr(v.json, "dump", boom)
    with pytest.raises(OSError, match="disk full"):
        v.write_record(path, _record(s, _outs(s, status=503), k=2))
    assert path.read_bytes() == before and v.read_record(path)["void"] == []
    assert not list(tmp_path.glob("*.tmp"))


def test_an_unwritable_out_dir_is_refused_by_check_slot(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    with pytest.raises(SystemExit, match="cannot write to.*nowhere to put its record"):
        v.check_slot(blocker / "validation", 1)


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_a_read_only_out_dir_is_refused_by_check_slot(tmp_path):
    out = tmp_path / "validation"
    out.mkdir()
    out.chmod(0o500)
    try:
        with pytest.raises(SystemExit, match="cannot write to"):
            v.check_slot(out, 1)
    finally:
        out.chmod(0o700)


def test_check_slot_creates_the_out_dir_and_leaves_nothing_in_it(tmp_path):
    out = tmp_path / "a" / "validation"
    v.check_slot(out, 1)
    assert out.is_dir() and not list(out.iterdir())


class FakePin:
    def __init__(self, release_error=None):
        self.events = []
        self.release_error = release_error

    def __enter__(self):
        self.events.append("pin")
        return self

    def __exit__(self, *exc):
        self.events.append("release")
        if self.release_error:
            raise self.release_error
        return False


def _run(tmp_path, pin, *, replay_fn=None, warm_fn=None, s=None, prepare=None):
    s = s if s is not None else _schedule()

    def warm(send, summary):
        pin.events.append("warm")
        summary.update({"requests": 3})
        return ["w1", "w2"]

    def replay(sch, send):
        pin.events.append("replay")
        return _outs(s)

    return v.run_repeat(
        k=1, schedule=s, pin=pin, send=lambda i: (200, {}), warm_fn=warm_fn or warm,
        replay_fn=replay_fn or replay, endpoint_id="ep", template_id="tpl", replicas=2,
        until=UNTIL, now=lambda: "t", path=tmp_path / "repeat-1.json.gz", seed=1, drain=20.0,
        prepare=prepare)


def test_run_repeat_pins_warms_replays_releases_and_writes(tmp_path):
    pin = FakePin()
    rec = _run(tmp_path, pin)
    # Every paid step sits inside the pin: moving warm-up or the replay out of it breaks this.
    assert pin.events == ["pin", "warm", "replay", "release"]
    assert rec["host_ids"] == ["w1", "w2"] and rec["warmup"] == {"requests": 3}
    assert v.read_record(tmp_path / "repeat-1.json.gz")["void"] == []


def test_run_repeat_releases_and_writes_nothing_when_the_replay_fails(tmp_path):
    pin = FakePin()

    def boom(sch, send):
        raise RuntimeError("network down")

    with pytest.raises(RuntimeError):
        _run(tmp_path, pin, replay_fn=boom)
    assert pin.events == ["pin", "warm", "release"] and not list(tmp_path.iterdir())


def test_run_repeat_writes_nothing_when_warm_up_fails(tmp_path):
    pin = FakePin()

    def gives_up(send, summary):
        raise TimeoutError("0 of 2 workers answered")

    with pytest.raises(TimeoutError):
        _run(tmp_path, pin, warm_fn=gives_up)
    assert pin.events == ["pin", "release"] and not list(tmp_path.iterdir())


def test_a_release_failure_after_the_replay_keeps_a_valid_record(tmp_path):
    pin = FakePin(release_error=ReleaseFailed("RELEASE FAILED: set it by hand"))
    with pytest.raises(ReleaseFailed):
        _run(tmp_path, pin)
    rec = v.read_record(tmp_path / "repeat-1.json.gz")
    assert rec["void"] == [] and rec["release"] == "FAILED"
    assert "RELEASE FAILED" in rec["post_run_error"]


def test_any_other_post_replay_pin_error_is_recorded_not_voided(tmp_path):
    pin = FakePin(release_error=RuntimeError("workersMax is 5 after the run"))
    with pytest.raises(RuntimeError):
        _run(tmp_path, pin)
    rec = v.read_record(tmp_path / "repeat-1.json.gz")
    assert rec["void"] == [] and rec["release"] == "ok"
    assert "workersMax is 5" in rec["post_run_error"]


def test_prepare_runs_after_warm_up_and_before_the_replay(tmp_path):
    pin = FakePin()
    _run(tmp_path, pin, prepare=lambda: pin.events.append("prepare"))
    assert pin.events == ["pin", "warm", "prepare", "replay", "release"]


def test_prepare_does_not_run_when_warm_up_fails(tmp_path):
    pin = FakePin()

    def gives_up(send, summary):
        raise TimeoutError("0 of 2 workers answered")

    with pytest.raises(TimeoutError):
        _run(tmp_path, pin, warm_fn=gives_up, prepare=lambda: pin.events.append("prepare"))
    assert "prepare" not in pin.events


def _fallback_dir(tmp_path, monkeypatch):
    d = tmp_path / "systmp"
    d.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(d))
    return d


def test_a_failed_write_dumps_the_raw_outcomes_and_keeps_the_release_failure_visible(
        tmp_path, monkeypatch, capsys):
    d = _fallback_dir(tmp_path, monkeypatch)

    def no_space(path, record):
        raise PermissionError("read-only file system")

    monkeypatch.setattr(v, "write_record", no_space)
    pin = FakePin(release_error=ReleaseFailed("RELEASE FAILED: set it by hand"))
    with pytest.raises(v.RecordLost) as info:
        _run(tmp_path, pin)
    err = info.value
    assert "RELEASE FAILED: set it by hand" in str(err)
    assert isinstance(err.__cause__, ReleaseFailed)
    assert err.fallback is not None and err.fallback.parent == d
    assert "a2-repeat-1-" in err.fallback.name
    dump = json.loads(err.fallback.read_text())
    assert len(dump["outcomes"]) == len(_schedule()) and dump["context"]["repeat"] == 1
    assert dump["context"]["host_ids"] == ["w1", "w2"]
    assert str(err.fallback) in capsys.readouterr().err


def test_a_failed_write_without_a_release_failure_chains_the_write_error(tmp_path, monkeypatch):
    _fallback_dir(tmp_path, monkeypatch)

    def no_space(path, record):
        raise PermissionError("read-only file system")

    monkeypatch.setattr(v, "write_record", no_space)
    with pytest.raises(v.RecordLost) as info:
        _run(tmp_path, FakePin())
    assert isinstance(info.value.__cause__, PermissionError)
    assert info.value.fallback is not None and info.value.fallback.exists()


def test_a_failed_record_build_also_falls_back(tmp_path, monkeypatch):
    _fallback_dir(tmp_path, monkeypatch)

    def bad(*a, **k):
        raise ValueError("malformed outcome")

    monkeypatch.setattr(v, "record_from", bad)
    with pytest.raises(v.RecordLost, match="malformed outcome"):
        _run(tmp_path, FakePin())


def _three(tmp_path, factors, hosts=(("w1", "w2"),) * 3):
    s = _schedule()
    for k, (f, h) in enumerate(zip(factors, hosts, strict=True), start=1):
        v.write_record(v.prepare_slot(tmp_path, k),
                       _record(s, _outs(s, f, workers=h), k=k, host_ids=h))


def test_judge_passes_a_model_inside_realitys_spread(tmp_path):
    _three(tmp_path, (0.97, 1.0, 1.03))
    verdict = v.judge(tmp_path, CURVE)
    assert verdict["outcome"] == "passed" and verdict["compared"] >= 10
    assert verdict["latency_source"] == "server"
    json.dumps(verdict, allow_nan=False)  # strict JSON: no Infinity or NaN


def test_figure_inputs_come_from_the_records_the_gate_judged(tmp_path):
    _three(tmp_path, (0.97, 1.0, 1.03))
    predicted, band_bins, result, repeats, n = v.figure_inputs(tmp_path, CURVE)
    assert len(repeats) == 3 and n == len(_schedule())
    assert len(predicted) == len(band_bins) == len(repeats[0])
    assert result.outcome == v.judge(tmp_path, CURVE)["outcome"] == "passed"


def test_figure_inputs_refuse_a_missing_or_void_repeat_like_judge(tmp_path):
    s = _schedule()
    v.write_record(v.prepare_slot(tmp_path, 1), _record(s, _outs(s)))
    with pytest.raises(SystemExit, match="repeat 2 is missing"):
        v.figure_inputs(tmp_path, CURVE)
    v.write_record(v.prepare_slot(tmp_path, 2), _record(s, _outs(s, status=503), k=2))
    with pytest.raises(SystemExit, match="repeat 2 is void"):
        v.figure_inputs(tmp_path, CURVE)


def test_judge_fails_a_model_outside_it(tmp_path):
    _three(tmp_path, (1.4, 1.45, 1.5))
    assert v.judge(tmp_path, CURVE)["outcome"] == "failed"


def test_judge_reports_host_novelty_without_voiding(tmp_path):
    _three(tmp_path, (0.97, 1.0, 1.03), hosts=(("w1", "w2"), ("w1", "w2"), ("w1", "w3")))
    verdict = v.judge(tmp_path, CURVE)
    assert verdict["host_novelty"] == {"3": ["w3"]}


def test_judge_refuses_a_missing_or_void_repeat(tmp_path):
    s = _schedule()
    v.write_record(v.prepare_slot(tmp_path, 1), _record(s, _outs(s)))
    with pytest.raises(SystemExit, match="repeat 2"):
        v.judge(tmp_path, CURVE)
    v.write_record(v.prepare_slot(tmp_path, 2), _record(s, _outs(s, status=503), k=2))
    with pytest.raises(SystemExit, match="repeat 2 is void"):
        v.judge(tmp_path, CURVE)


def test_judge_surfaces_a_post_run_error_and_a_void_attempt_file(tmp_path):
    s = _schedule()
    for k in (1, 2, 3):
        rec = _record(s, _outs(s), k=k)
        if k == 2:
            rec["post_run_error"] = "ReleaseFailed: RELEASE FAILED"
        v.write_record(v.prepare_slot(tmp_path, k), rec)
    verdict = v.judge(tmp_path, CURVE)
    assert [r["post_run_error"] for r in verdict["per_repeat"]] == [
        None, "ReleaseFailed: RELEASE FAILED", None]


def test_judge_names_a_void_attempt_when_the_repeat_is_missing(tmp_path):
    s = _schedule()
    v.write_record(v.prepare_slot(tmp_path, 1), _record(s, _outs(s)))
    v.write_record(tmp_path / "repeat-2.void.json.gz", _record(s, _outs(s, status=503), k=2))
    with pytest.raises(SystemExit, match=r"repeat 2 is missing.*earlier void attempt is kept"):
        v.judge(tmp_path, CURVE)


def test_judge_names_a_repeat_the_gate_refuses_for_jitter(tmp_path):
    s = _schedule()
    for k in (1, 2, 3):
        outs = _outs(s)
        if k == 2:
            outs[10] = Outcome(10, s[10], s[10] + 2.0, 0.5, 200, outs[10].headers)
        v.write_record(v.prepare_slot(tmp_path, k), _record(s, outs, k=k))
    with pytest.raises(SystemExit, match="gate refused the repeats.*jitter"):
        v.judge(tmp_path, CURVE)


def test_the_lb_pin_set_names_the_gpu_and_volume():
    assert v.lb_pins("tpl-1") == {"gpuTypeIds": ["NVIDIA GeForce RTX 4090"],
                                  "networkVolumeId": "9c7ut2slrd", "templateId": "tpl-1"}


# --- main(), with a fake pin, a fake endpoint read and a fake replay -------------------


class MainPin:
    instances: ClassVar[list] = []

    def __init__(self, endpoint_id, api_key, *, workers):
        self.log = []
        self.release_error = None
        MainPin.instances.append(self)

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
    MainPin.instances = []
    s = _schedule()
    monkeypatch.setenv("RUNPOD_API_KEY", KEY)
    monkeypatch.setenv("RUNPOD_A2_LB_ENDPOINT_ID", "ep123")
    monkeypatch.setattr(v, "WorkerPin", MainPin)
    monkeypatch.setattr(v, "unwind_on_hangup_and_term", lambda: None)
    monkeypatch.setattr(v, "fetch_endpoint", lambda ep, key: v.lb_pins("tpl-1"))
    monkeypatch.setattr(v, "sender", lambda *a: (lambda i: (200, {})))
    monkeypatch.setattr(v, "build_schedule", lambda *a, **k: s)
    monkeypatch.setattr(v, "load_measured_curve", lambda path: type("M", (), {"curve": CURVE})())
    monkeypatch.setattr(v, "ensure_fd_limit", lambda: None)

    def warm(send, summary_out=None, **kw):
        MainPin.instances[-1].log.append("warm")
        summary_out.update({"requests": 3})
        return ["w1", "w2"]

    monkeypatch.setattr(v, "warm_up", warm)
    calls = []

    def set_replay(behaviour):
        def fake(schedule, send, **kw):
            calls.append(kw)
            MainPin.instances[-1].log.append("replay")
            return behaviour(schedule)
        monkeypatch.setattr(v, "replay", fake)

    set_replay(lambda schedule: _outs(s))
    out = tmp_path / "validation"
    return {"out": out, "calls": calls, "set_replay": set_replay, "schedule": s,
            "argv": ["--repeat", "1", "--template-id", "tpl-1", "--out", str(out)]}


def test_main_refuses_a_valid_slot_before_any_pin(rig):
    s = rig["schedule"]
    v.write_record(v.prepare_slot(rig["out"], 1), _record(s, _outs(s)))
    before = (rig["out"] / "repeat-1.json.gz").read_bytes()
    with pytest.raises(SystemExit, match="never re-run"):
        v.main(rig["argv"])
    assert MainPin.instances == [] and rig["calls"] == []
    assert (rig["out"] / "repeat-1.json.gz").read_bytes() == before


def test_main_refuses_a_twice_void_slot_before_any_pin(rig):
    s = rig["schedule"]
    v.write_record(v.prepare_slot(rig["out"], 1), _record(s, _outs(s, status=503)))
    v.write_record(v.prepare_slot(rig["out"], 1), _record(s, _outs(s, status=503)))
    with pytest.raises(SystemExit, match="not evaluable"):
        v.main(rig["argv"])
    assert MainPin.instances == [] and rig["calls"] == []


def test_main_preflight_only_writes_nothing(rig, capsys):
    v.main(["--preflight-only", "--template-id", "tpl-1", "--out", str(rig["out"])])
    assert not rig["out"].exists() and rig["calls"] == []
    assert MainPin.instances[0].log == ["preflight"]
    assert "nothing written" in capsys.readouterr().out


def test_main_a_repeat_writes_a_record_without_the_api_key(rig, capsys):
    v.main(rig["argv"])
    path = rig["out"] / "repeat-1.json.gz"
    rec = v.read_record(path)
    assert rec["void"] == [] and rec["host_ids"] == ["w1", "w2"] and rec["endpoint_id"] == "ep123"
    assert rec["release"] == "ok" and rec["warmup"] == {"requests": 3}
    assert rig["calls"] == [{"max_in_flight": v.REPLAY_MAX_IN_FLIGHT}]
    assert v.REPLAY_MAX_IN_FLIGHT == 4096
    assert MainPin.instances[0].log == ["preflight", "pin", "warm", "replay", "release"]
    assert KEY not in gzip.decompress(path.read_bytes()).decode()
    captured = capsys.readouterr()
    assert KEY not in captured.out + captured.err and "valid" in captured.out


def test_main_a_release_failure_after_the_replay_still_writes_the_record(rig, monkeypatch):
    class FailingPin(MainPin):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.release_error = ReleaseFailed("RELEASE FAILED: set it by hand")

    monkeypatch.setattr(v, "WorkerPin", FailingPin)
    with pytest.raises(ReleaseFailed):
        v.main(rig["argv"])
    rec = v.read_record(rig["out"] / "repeat-1.json.gz")
    assert rec["release"] == "FAILED" and rec["void"] == [] and len(rec["schedule"]) > 0


def test_main_a_failed_replay_writes_no_record_and_leaves_the_slot_unchanged(rig, capsys):
    def boom(schedule):
        raise RuntimeError("the driver broke")

    rig["set_replay"](boom)
    with pytest.raises(RuntimeError, match="driver broke"):
        v.main(rig["argv"])
    assert not rig["out"].exists() or not list(rig["out"].iterdir())
    assert MainPin.instances[0].log == ["preflight", "pin", "warm", "replay", "release"]
    assert "NO record was written and the slot is unchanged" in capsys.readouterr().err


def test_main_a_void_rerun_moves_the_void_aside_only_after_the_preflight(rig, monkeypatch):
    s = rig["schedule"]
    v.write_record(v.prepare_slot(rig["out"], 1), _record(s, _outs(s, status=503)))

    monkeypatch.setattr(v, "fetch_endpoint", lambda ep, key: {"templateId": "other"})
    with pytest.raises(PreflightError):
        v.main(rig["argv"])
    assert (rig["out"] / "repeat-1.json.gz").exists()
    assert not (rig["out"] / "repeat-1.void.json.gz").exists()
    monkeypatch.setattr(v, "fetch_endpoint", lambda ep, key: v.lb_pins("tpl-1"))
    v.main(rig["argv"])
    assert (rig["out"] / "repeat-1.void.json.gz").exists()
    assert v.read_record(rig["out"] / "repeat-1.json.gz")["void"] == []


def test_main_judge_writes_a_verdict(rig, capsys):
    s = rig["schedule"]
    for k, f in enumerate((0.97, 1.0, 1.03), start=1):
        v.write_record(v.prepare_slot(rig["out"], k), _record(s, _outs(s, f), k=k))
    v.main(["--judge", "--out", str(rig["out"])])
    verdict = json.loads((rig["out"] / "verdict.json").read_text())
    out = capsys.readouterr().out
    assert verdict["outcome"] == "passed" and "[judge] passed" in out
    assert (rig["out"] / "validation_overlay.png").stat().st_size > 0
    assert "validation_overlay.png" in out


def test_main_refuses_an_unwritable_out_before_any_pin(rig, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    argv = ["--repeat", "1", "--template-id", "tpl-1", "--out", str(blocker / "validation")]
    with pytest.raises(SystemExit, match="cannot write to"):
        v.main(argv)
    assert MainPin.instances == [] and rig["calls"] == []


def test_main_refuses_a_too_low_open_files_limit_before_any_pin(rig, monkeypatch):
    def refuse():
        raise SystemExit("the open-files soft limit is 256")

    monkeypatch.setattr(v, "ensure_fd_limit", refuse)
    with pytest.raises(SystemExit, match="open-files"):
        v.main(rig["argv"])
    assert MainPin.instances == [] and rig["calls"] == []


def test_main_moves_a_void_aside_only_once_warm_up_has_succeeded(rig, monkeypatch):
    s = rig["schedule"]
    out = rig["out"]
    v.write_record(v.prepare_slot(out, 1), _record(s, _outs(s, status=503)))
    seen = {}
    orig_warm = v.warm_up

    def watching_warm(send, summary_out=None, **kw):
        seen["at_warm"] = (out / "repeat-1.json.gz").exists(), (
            out / "repeat-1.void.json.gz").exists()
        return orig_warm(send, summary_out=summary_out, **kw)

    monkeypatch.setattr(v, "warm_up", watching_warm)
    rig["set_replay"](lambda schedule: (
        seen.__setitem__("at_replay", ((out / "repeat-1.json.gz").exists(),
                                       (out / "repeat-1.void.json.gz").exists())),
        _outs(s))[1])
    v.main(rig["argv"])
    assert seen["at_warm"] == (True, False)       # void still in the slot while warming
    assert seen["at_replay"] == (False, True)     # moved aside just before the replay
    assert v.read_record(out / "repeat-1.json.gz")["void"] == []


def test_main_a_failed_warm_up_leaves_a_void_slot_untouched(rig, monkeypatch, capsys):
    s = rig["schedule"]
    out = rig["out"]
    v.write_record(v.prepare_slot(out, 1), _record(s, _outs(s, status=503)))
    before = (out / "repeat-1.json.gz").read_bytes()

    def gives_up(send, summary_out=None, **kw):
        raise TimeoutError("0 of 2 pinned workers answered")

    monkeypatch.setattr(v, "warm_up", gives_up)
    with pytest.raises(TimeoutError):
        v.main(rig["argv"])
    assert (out / "repeat-1.json.gz").read_bytes() == before
    assert not (out / "repeat-1.void.json.gz").exists()
    assert "the slot is unchanged" in capsys.readouterr().err


def test_main_a_failed_replay_after_the_void_moved_aside_says_so(rig, capsys):
    s = rig["schedule"]
    out = rig["out"]
    v.write_record(v.prepare_slot(out, 1), _record(s, _outs(s, status=503)))

    def boom(schedule):
        raise RuntimeError("the driver broke")

    rig["set_replay"](boom)
    with pytest.raises(RuntimeError):
        v.main(rig["argv"])
    err = capsys.readouterr().err
    assert "slot is unchanged" not in err and "moved aside" in err
    assert (out / "repeat-1.void.json.gz").exists() and not (out / "repeat-1.json.gz").exists()


def test_main_a_failed_write_after_a_release_failure_names_both(rig, monkeypatch, tmp_path, capsys):
    d = tmp_path / "systmp"
    d.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(d))

    class FailingPin(MainPin):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.release_error = ReleaseFailed("RELEASE FAILED: set it by hand")

    def no_space(path, record):
        raise PermissionError("read-only file system")

    monkeypatch.setattr(v, "WorkerPin", FailingPin)
    monkeypatch.setattr(v, "write_record", no_space)
    with pytest.raises(v.RecordLost, match="RELEASE FAILED: set it by hand"):
        v.main(rig["argv"])
    assert len(list(d.iterdir())) == 1
    assert "raw outcomes are in" in capsys.readouterr().err


def test_main_judge_warns_about_a_recorded_post_run_error(rig, capsys):
    s = rig["schedule"]
    for k, f in enumerate((0.97, 1.0, 1.03), start=1):
        rec = _record(s, _outs(s, f), k=k)
        if k == 3:
            rec["post_run_error"] = "ReleaseFailed: RELEASE FAILED"
        v.write_record(v.prepare_slot(rig["out"], k), rec)
    v.main(["--judge", "--out", str(rig["out"])])
    assert "repeat 3 recorded an error after its replay" in capsys.readouterr().err
