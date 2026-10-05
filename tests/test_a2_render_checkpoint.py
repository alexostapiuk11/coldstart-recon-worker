"""The figure sweep checkpoints each sweep as it finishes, so a refusal or a
crash late in an hours-long run does not throw the finished sweeps away."""

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import a2_render_figures as render

from autoscale.coldstart_ecdf import LagDistribution
from autoscale.frontier import PolicyPoint
from autoscale.service import SERVICE_CURVE_PLACEHOLDER

EXPECTED_TAGS = [
    "arm A", "arm C",
    *[f"modeled lag {lag:g}s" for lag in render.SWEPT_LAGS],
    "ramp arm A", "ramp arm C",
    "sensitivity arm A", "sensitivity arm C",
    "sensitivity ramp arm A", "sensitivity ramp arm C",
]


def _pp(signal, up=1.0):
    return PolicyPoint(cost_samples=(10.0, 11.0), p99_samples=(0.5, 0.6), signal=signal,
                       scale_up_at=up, scale_down_at=0.0, rep_indices=(0, 3))


def _identity(**over):
    return {**render.sweep_identity("placeholder", "data/campaign.jsonl"), **over}


class FakeSweeps:
    """Stands in for `run_sweep`: counts calls, can fail on the Nth."""

    def __init__(self, fail_on=None):
        self.calls = 0
        self.fail_on = fail_on

    def __call__(self, config, seed, allow_unmeasured=False, signals=None):
        self.calls += 1
        if self.calls == self.fail_on:
            raise KeyboardInterrupt
        names = signals or ("queue_depth", "in_flight_concurrency", "utilization")
        return [_pp(s) for s in names], [f"{names[0]}:replica_never_served"]


@pytest.fixture
def offline(monkeypatch):
    """No store read and no bootstrap: the gap step refuses the way the
    measured run's did, after every sweep has finished."""
    monkeypatch.setattr(render, "load_measured_lags",
                        lambda store: {"A": LagDistribution([60.0]), "C": LagDistribution([20.0])})
    monkeypatch.setattr(render, "iso_cost_budget", lambda per_signal: 1.0)
    monkeypatch.setattr(render, "gap_at_iso_cost", lambda per_signal, cost, **kw: 0.0)

    def refuse(*a, **kw):
        raise ValueError("3 of 8 frontier points have fewer than 20 surviving repetitions; x")

    monkeypatch.setattr(render, "gap_interval", refuse)


def test_points_and_discards_round_trip_through_the_checkpoint_file(tmp_path):
    path = tmp_path / "cp.json"
    cp = render.SweepCheckpoint(path, _identity())
    assert cp.tags == []
    cp.put("arm A", [_pp("queue_depth"), _pp("utilization", 0.5)], ["queue_depth:x"])
    again = render.SweepCheckpoint(path, _identity())
    assert again.tags == ["arm A"]
    assert again.get("arm A") == ([_pp("queue_depth"), _pp("utilization", 0.5)], ["queue_depth:x"])
    assert again.get("arm C") is None


def test_a_checkpoint_from_another_curve_store_or_grid_is_refused(tmp_path):
    path = tmp_path / "cp.json"
    render.SweepCheckpoint(path, _identity()).put("arm A", [_pp("queue_depth")], [])
    for changed in (_identity(curve="data/a2/service-curve.json"),
                    _identity(store="other.jsonl"),
                    _identity(repetitions=31),
                    _identity(additional_replicas=0.25)):
        with pytest.raises(SystemExit, match="checkpoint"):
            render.SweepCheckpoint(path, changed)


def test_the_identity_names_what_the_sweeps_depend_on():
    ident = render.sweep_identity("placeholder", "data/campaign.jsonl")
    for key in ("curve", "store", "baseline_fraction", "additional_replicas", "sustain",
                "seed", "until", "repetitions", "cooldown", "evaluate_every", "max_replicas",
                "thresholds", "swept_lags"):
        assert key in ident, key
    assert ident["thresholds"]["utilization_throughput"]
    json.dumps(ident)  # it is written to the file as-is


def test_every_sweep_is_checkpointed_before_the_gap_refusal(tmp_path, monkeypatch, offline):
    fake = FakeSweeps()
    monkeypatch.setattr(render, "run_sweep", fake)
    cp = render.SweepCheckpoint(tmp_path / "cp.json", _identity())
    with pytest.raises(ValueError, match="fewer than 20"):
        render._run_everything("data/campaign.jsonl", SERVICE_CURVE_PLACEHOLDER, cp)
    assert fake.calls == len(EXPECTED_TAGS)
    assert render.SweepCheckpoint(tmp_path / "cp.json", _identity()).tags == EXPECTED_TAGS


def test_a_rerun_reuses_the_checkpoint_and_sweeps_nothing(tmp_path, monkeypatch, offline, capsys):
    monkeypatch.setattr(render, "run_sweep", FakeSweeps())
    path = tmp_path / "cp.json"
    with pytest.raises(ValueError):
        render._run_everything("data/campaign.jsonl", SERVICE_CURVE_PLACEHOLDER,
                               render.SweepCheckpoint(path, _identity()))
    first = capsys.readouterr().out
    second_run = FakeSweeps()
    monkeypatch.setattr(render, "run_sweep", second_run)
    with pytest.raises(ValueError, match="fewer than 20"):
        render._run_everything("data/campaign.jsonl", SERVICE_CURVE_PLACEHOLDER,
                               render.SweepCheckpoint(path, _identity()))
    assert second_run.calls == 0
    out = capsys.readouterr().out
    # The discard counts are published per signal, so a reused sweep prints
    # the same discard line as the run that produced it.
    discard_lines = [ln for ln in first.splitlines() if "discards" in ln]
    assert discard_lines and all(ln in out for ln in discard_lines)
    assert "from the checkpoint" in out


def test_an_interrupted_run_resumes_at_the_sweep_it_stopped_in(tmp_path, monkeypatch, offline):
    monkeypatch.setattr(render, "run_sweep", FakeSweeps(fail_on=3))
    path = tmp_path / "cp.json"
    with pytest.raises(KeyboardInterrupt):
        render._run_everything("data/campaign.jsonl", SERVICE_CURVE_PLACEHOLDER,
                               render.SweepCheckpoint(path, _identity()))
    assert render.SweepCheckpoint(path, _identity()).tags == EXPECTED_TAGS[:2]
    rest = FakeSweeps()
    monkeypatch.setattr(render, "run_sweep", rest)
    with pytest.raises(ValueError):
        render._run_everything("data/campaign.jsonl", SERVICE_CURVE_PLACEHOLDER,
                               render.SweepCheckpoint(path, _identity()))
    assert rest.calls == len(EXPECTED_TAGS) - 2


def test_without_a_checkpoint_nothing_is_written(tmp_path, monkeypatch, offline):
    monkeypatch.setattr(render, "run_sweep", FakeSweeps())
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError):
        render._run_everything("data/campaign.jsonl", SERVICE_CURVE_PLACEHOLDER)
    assert list(tmp_path.iterdir()) == []


def test_refresh_discards_the_checkpoint_and_a_plain_run_keeps_it(tmp_path):
    path = tmp_path / "sweep-checkpoint.json"
    render.SweepCheckpoint(path, _identity()).put("arm A", [_pp("queue_depth")], [])
    assert render.open_checkpoint(tmp_path, _identity(), refresh=False).tags == ["arm A"]
    assert render.open_checkpoint(tmp_path, _identity(), refresh=True).tags == []
    assert not path.exists()


def test_a_cache_from_other_sweep_inputs_or_with_none_recorded_is_refused():
    ident = _identity()
    render.check_cache_identity({"identity": ident}, ident)
    with pytest.raises(SystemExit, match="does not record"):
        render.check_cache_identity({"curve": "placeholder"}, ident)
    with pytest.raises(SystemExit, match="additional_replicas"):
        render.check_cache_identity({"identity": _identity(additional_replicas=0.25)}, ident)


def test_the_cache_records_its_identity(tmp_path):
    path = tmp_path / "cache.json"
    render._dump(path, {"arm A": [_pp("queue_depth")]}, {}, {}, "placeholder", _identity())
    *_, raw = render._load(path)
    render.check_cache_identity(raw, _identity())
