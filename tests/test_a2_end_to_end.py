"""The whole path: artifact 1's measured lags -> sweep -> frontiers -> H3.

Spec section 15: the expensive half does not start until the cheap half is
proven. This is the proof -- artifact 1's committed campaign store, read by the
real loader, swept by the real sweep over the real pre-registered threshold
grids, reduced to Pareto frontiers, sliced at an iso-cost budget, rendered by
the real figure code and handed to H3's verdict function. No GPU, no money, no
synthetic lag samples anywhere in it.

WHAT IS REDUCED, AND WHY IT IS STILL THE REAL PATH. The published sweep is
`REPETITIONS = 30` repetitions of every threshold combination over a 400 s
window, for each of seven lag distributions -- about 25 minutes of CPU (see
`scripts/a2_render_figures.py`). A test suite cannot pay that per run, so
these tests reduce exactly three things and nothing else:

  * `REPETITIONS` 30 -> 1, monkeypatched;
  * the window 400 s -> 120 s (and the sustain 190 s -> 60 s with it);
  * in the cross-process test only, the threshold grid to one combination per
    signal, because that test is about seed derivation and not about coverage.

Everything else is the shipping code on the shipping data. What is therefore
NOT proven here: that the published 30-repetition numbers are stable, and that
every threshold combination in the grid behaves. This is a plumbing gate, not
a result -- and the numbers it computes are meaningless in a second, stronger
sense, because `SERVICE_CURVE_PLACEHOLDER` is invented (see
`test_the_placeholder_curve_stays_self_identifying`). Do not quote anything
from this file.
"""

import json
import os
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import pytest

from autoscale import sweep as sweep_module
from autoscale.arrivals import SpikeShape
from autoscale.coldstart_ecdf import load_measured_lags
from autoscale.figures import SIGNAL_ORDER
from autoscale.figures import frontiers as render_frontiers
from autoscale.frontier import gap_at_iso_cost, h3_verdict, pareto_frontier
from autoscale.service import SERVICE_CURVE_PLACEHOLDER
from autoscale.signals import SIGNALS
from autoscale.sweep import THRESHOLDS, SweepConfig, run_sweep

REPO_ROOT = Path(__file__).resolve().parents[1]
# Artifact 1's committed campaign, not a fixture. If this test ever stops
# reading it, the gate stops proving the thing it exists to prove.
STORE = REPO_ROOT / "data" / "campaign.jsonl"

SEED = 17
# Exactly half the real sweep's window (400 / 190 / 95), not an arbitrary
# shrink. At the pre-registered traffic model a shorter window was fine because
# every signal saturated instantly; at the amended one (peak at 0.95x a
# replica's saturation) `queue_depth` needs a real spike before its queue
# crosses even the lowest threshold in its grid, and at 120/60 it was excluded
# as `no_scaling_action` in 5 of 20 (seed, arm, shape) combinations -- so this
# gate certified a two-signal sweep. At 200/95 all three signals survive in
# 20/20, with queue_depth keeping 8-14 of its 19 policies.
UNTIL = 200.0
SUSTAIN = 95.0
RAMP = 47.5
REPETITIONS_UNDER_TEST = 1

BASELINE_FRACTION_OF_SATURATION = 0.70  # docs/experiment-a2.md, amended 2026-09-17
ADDITIONAL_REPLICAS_AT_PEAK = 0.25  # docs/experiment-a2.md, amended 2026-09-17

# Threshold combinations one sweep actually runs: the pre-registered grids,
# less the pairs `Controller` refuses outright (`scale_down_at >= scale_up_at`
# oscillates). Derived from `THRESHOLDS` rather than written as 55, so a grid
# change moves it instead of failing here.
_VALID_COMBINATIONS = sum(
    1 for ups, downs in THRESHOLDS.values() for up in ups for down in downs if down < up
)


def _shape(kind: str, ramp: float) -> SpikeShape:
    """The traffic model as the pre-registration states it: a RULE over the
    service curve, not two literals.

    The plan's draft of this test hardcoded `baseline_rate=2.0, k=4.0`, which
    is roughly a sixth of what the rule gives against the placeholder curve.
    At that load one replica absorbs the whole spike, queue depth never crosses
    even its lowest threshold, and every queue_depth run is discarded as
    `no_scaling_action` -- so the "end to end" test would have exercised two of
    the three signals and passed, which is the exact failure this file is
    supposed to catch. `scripts/a2_render_figures.py` derives the shape the
    same way and for the same reason; the derivation is duplicated rather than
    imported because `scripts/` is not an importable package.
    """
    saturation = max(
        c / SERVICE_CURVE_PLACEHOLDER.latency_at(c)
        for c, _, _, _ in SERVICE_CURVE_PLACEHOLDER.points
        if c > 0
    )
    baseline = BASELINE_FRACTION_OF_SATURATION * saturation
    peak = baseline + ADDITIONAL_REPLICAS_AT_PEAK * saturation
    return SpikeShape(
        kind=kind, baseline_rate=baseline, k=peak / baseline, ramp=ramp, sustain=SUSTAIN
    )


def _sweep(arm: str, lags, shape: SpikeShape):
    """One real sweep, with only the repetition count reduced.

    `allow_unmeasured=True` is required because `SERVICE_CURVE_PLACEHOLDER` is
    invented and `run_sweep` refuses it otherwise. It is typed here to prove
    the PLUMBING runs, never to reach a result; the refusal itself is exercised
    by `test_the_sweep_refuses_the_placeholder_curve_without_the_opt_in`.
    """
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(sweep_module, "REPETITIONS", REPETITIONS_UNDER_TEST)
        return run_sweep(
            SweepConfig(
                shape=shape,
                lags=lags,
                curve=SERVICE_CURVE_PLACEHOLDER,
                arm=arm,
                until=UNTIL,
            ),
            seed=SEED,
            allow_unmeasured=True,  # placeholder curve; plumbing, not a result
        )


def _by_signal(points):
    return {s: [p for p in points if p.signal == s] for s in {p.signal for p in points}}


def _frontiers(points):
    return {s: pareto_frontier(ps) for s, ps in _by_signal(points).items()}


@pytest.fixture(scope="module")
def measured_lags():
    """Artifact 1's real per-arm cold-start lag distributions."""
    return load_measured_lags(STORE)


@pytest.fixture(scope="module")
def swept(measured_lags):
    """Every sweep H3 needs -- both shapes, both measured arms -- run once.

    Module-scoped because these four sweeps are the expensive part of this
    file and every test below reads the same ones; re-running them per test
    would quadruple the cost and prove nothing extra.
    """
    return {
        (kind, arm): _sweep(arm, measured_lags[arm], _shape(kind, ramp))
        for kind, ramp in (("step", 0.0), ("ramp", RAMP))
        for arm in ("A", "C")
    }


def test_the_lags_come_from_artifact_ones_committed_campaign(measured_lags):
    """The medians artifact 1 published, read back through the real loader.

    Pinned so that swapping the store for a fixture, or a regression in the
    first-touch exclusion, fails here rather than downstream where it would
    look like a simulation result.
    """
    assert STORE.exists(), f"{STORE} is artifact 1's committed campaign store"
    assert measured_lags["A"].median() == pytest.approx(81.1, abs=0.05)
    assert measured_lags["C"].median() == pytest.approx(39.4, abs=0.05)
    # 100 runs per arm, less arm A's single first-touch exclusion. The medians
    # alone do not pin this: that excluded run is one draw in a hundred, so
    # pooling it back in moves the median by less than 0.02 s while putting a
    # 2266.6 s platform image-pull into the population the simulator RESAMPLES
    # -- where it is a two-thousand-second scale-up lag, not a rounding error.
    assert len(measured_lags["A"].samples) == 99
    assert len(measured_lags["C"].samples) == 100
    assert max(measured_lags["A"].samples) < 200.0, (
        "arm A's resampling pool contains a draw far outside artifact 1's "
        "39-96 s cold-start norm; the first-on-its-host exclusion did not run"
    )


def test_the_whole_path_runs_on_artifact_ones_real_data(swept):
    """Real store -> real sweep -> frontiers -> iso-cost gaps -> H3's verdict.

    Every assertion here is about the PATH, not about the numbers: the
    placeholder service curve makes the values meaningless, so the test checks
    that each stage produced something structurally publishable and handed it
    to the next.
    """
    gaps = {}
    for key, (points, discards) in swept.items():
        assert points, f"{key} produced no policy points at all"
        # All three signals, on both arms, under both shapes. Two of three is
        # the failure the plan's hardcoded traffic literals produced silently:
        # the frontier figure would then compare a different set of signals
        # per arm, or refuse outright.
        assert set(_by_signal(points)) == set(SIGNALS) == set(SIGNAL_ORDER)
        # Nothing fell off the sweep unaccounted for. At one repetition each
        # valid threshold combination produces exactly one point or exactly
        # one discard, so this is the arithmetic that makes "the sweep ran
        # everything" checkable rather than assumed -- a run silently dropped
        # by a future change would show up here as neither.
        assert len(points) + len(discards) == _VALID_COMBINATIONS
        # Discards are `"{signal}:{reason}"` so the count is publishable per
        # signal, as the pre-registration requires. No exclusion happens to
        # fire at this window on this data, so this loop is a shape guard for
        # whichever future change makes one fire; the populated case is
        # covered by `test_discards_are_attributable_to_a_signal` in
        # tests/test_frontier.py.
        for entry in discards:
            signal, sep, reason = entry.partition(":")
            assert sep and signal in SIGNALS
            assert reason in {"empty_trace", "no_scaling_action", "replica_never_served"}

    fronts = {key: _frontiers(points) for key, (points, _) in swept.items()}

    # ONE budget across both arms and both shapes: an H3 gap read at a
    # different iso-cost per arm is not a comparison. The cheapest policy any
    # frontier can reach is the floor -- below it `gap_at_iso_cost` refuses,
    # which is the documented behaviour, not something to work around.
    budget = max(min(p.cost for p in front) for arm in fronts.values() for front in arm.values())
    for key, arm in fronts.items():
        gaps[key] = gap_at_iso_cost(arm, cost=budget)
        assert gaps[key] >= 0.0, key

    verdict = h3_verdict(
        step_gap_a=gaps[("step", "A")],
        step_gap_c=gaps[("step", "C")],
        ramp_gap_a=gaps[("ramp", "A")],
        ramp_gap_c=gaps[("ramp", "C")],
    )
    # Three states, not two. `evaluable` is False when the arm-A gap was zero,
    # because `gap_c <= gap_a / 2` is satisfied by two zeros and would confirm
    # the artifact's headline out of no effect at all. The path is proven by
    # the verdict HAVING a truth value; which one it is goes deliberately
    # unasserted, because the curve underneath it is invented.
    assert verdict.evaluable is True, verdict.detail
    assert isinstance(verdict.holds, bool)
    assert isinstance(verdict.partial, bool)
    assert not (verdict.holds and verdict.partial)
    assert verdict.detail


def test_the_real_frontiers_render_a_figure(swept, tmp_path):
    """The last stage. `figures.frontiers` refuses any input missing a signal,
    so this both draws the chart and re-checks the sweep's coverage through
    the published code path rather than through this file's own assertion."""
    points, _ = swept[("step", "A")]
    out = tmp_path / "frontiers.png"

    render_frontiers(_by_signal(points), out, context="arm A, step (reduced sweep)")

    assert out.exists() and out.stat().st_size > 0


def test_the_sweep_is_reproducible_from_its_seed(measured_lags, swept):
    """A second, independent invocation of the real sweep on the real data
    reproduces the first exactly -- same points, same discards, same order."""
    points, discards = _sweep("A", measured_lags["A"], _shape("step", 0.0))
    first_points, first_discards = swept[("step", "A")]

    assert points == first_points
    assert discards == first_discards
    assert points, "an empty sweep would compare equal trivially"


def test_the_placeholder_curve_stays_self_identifying():
    """Nothing may publish a number from invented service-curve points without
    saying so. `measured=False` is the flag every guard downstream reads; the
    dataclass is frozen so it cannot be flipped on the shared instance."""
    assert SERVICE_CURVE_PLACEHOLDER.measured is False
    with pytest.raises(FrozenInstanceError):
        SERVICE_CURVE_PLACEHOLDER.measured = True


def test_the_sweep_refuses_the_placeholder_curve_without_the_opt_in(
    measured_lags, monkeypatch
):
    """The refusal that makes `measured=False` load-bearing rather than
    decorative, exercised on this exact end-to-end path: every sweep above had
    to type `allow_unmeasured=True` to run at all.

    `REPETITIONS` is lowered here even though nothing is supposed to run: when
    this test FAILS, the sweep it expected to be refused executes in full, and
    at 30 repetitions that turns a one-line failure into forty seconds of it.
    """
    monkeypatch.setattr(sweep_module, "REPETITIONS", REPETITIONS_UNDER_TEST)
    config = SweepConfig(
        shape=_shape("step", 0.0),
        lags=measured_lags["A"],
        curve=SERVICE_CURVE_PLACEHOLDER,
        arm="A",
        until=UNTIL,
    )

    with pytest.raises(ValueError, match="allow_unmeasured"):
        run_sweep(config, seed=SEED)


# Run in a FRESH interpreter, twice, under two different hash salts. Reduced to
# one threshold combination per signal (see the module docstring): this test is
# about whether the seed derivation survives a new process, and three signal
# names is enough to see string-hash salting, where 55 combinations would only
# make it slower.
_CROSS_PROCESS_PROGRAM = """
import json, sys
import autoscale.sweep as sweep
from autoscale.arrivals import SpikeShape
from autoscale.coldstart_ecdf import load_measured_lags
from autoscale.service import SERVICE_CURVE_PLACEHOLDER

store, until, sustain, seed = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), int(sys.argv[4])
sweep.REPETITIONS = 1
sweep.THRESHOLDS = {
    "queue_depth": ((4.0,), (1.0,)),
    "in_flight_concurrency": ((8.0,), (2.0,)),
    "utilization": ((0.80,), (0.30,)),
}
curve = SERVICE_CURVE_PLACEHOLDER
saturation = max(c / curve.latency_at(c) for c, _, _, _ in curve.points if c > 0)
baseline = 0.40 * saturation
peak = baseline + 3 * saturation
lags = load_measured_lags(store)
points, discards = sweep.run_sweep(
    sweep.SweepConfig(
        shape=SpikeShape(kind="step", baseline_rate=baseline, k=peak / baseline,
                         ramp=0.0, sustain=sustain),
        lags=lags["A"],
        curve=curve,
        arm="A",
        until=until,
    ),
    seed=seed,
    allow_unmeasured=True,
)
json.dump(
    {
        "samples": lags["A"].samples,
        "points": [[p.cost, p.p99, p.signal, p.scale_up_at, p.scale_down_at] for p in points],
        "discards": discards,
    },
    sys.stdout,
)
"""


def _sweep_in_a_fresh_interpreter(hash_seed: str):
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT), "PYTHONHASHSEED": hash_seed}
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            _CROSS_PROCESS_PROGRAM,
            str(STORE),
            str(UNTIL),
            str(SUSTAIN),
            str(SEED),
        ],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
        env=env,
    )
    return json.loads(completed.stdout)


def test_the_sweep_reproduces_across_processes_not_just_within_one():
    """The defect the sha256 seeding exists to prevent, checked on real data.

    The in-process reproducibility test above cannot see it: `hash()` on a str
    is salted per process, so a hash-derived seed is perfectly stable within
    any single interpreter -- including inside that test -- while giving a
    reader who re-runs the artifact different numbers. Two interpreters, two
    different salts, byte-identical output, including the resampled lag
    population the sweep drew from.
    """
    first = _sweep_in_a_fresh_interpreter("0")
    second = _sweep_in_a_fresh_interpreter("12345")

    assert first["points"], "a sweep with no points would compare equal trivially"
    assert first["samples"] == second["samples"]
    assert first["points"] == second["points"]
    assert first["discards"] == second["discards"]


def test_the_traffic_constants_match_the_render_script_and_the_preregistration():
    """The traffic derivation lives in three places -- this file, the render
    script, and docs/experiment-a2.md -- and the first two are duplicated rather
    than shared. A duplicated constant that nothing compares is two constants.

    This bit for real: the pre-registered `k` (3 additional replicas at peak)
    put the peak at 3.4x one replica's saturation, which made every signal
    saturate for the whole spike and every policy deliver an identical p99, and
    the amendment that fixed it had to be applied by hand in both copies. A
    third place that quietly kept the old value would have produced a sweep
    disagreeing with the gate that is supposed to certify it.
    """
    import sys

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import a2_render_figures as render

    assert BASELINE_FRACTION_OF_SATURATION == render.BASELINE_FRACTION_OF_SATURATION
    assert ADDITIONAL_REPLICAS_AT_PEAK == render.ADDITIONAL_REPLICAS_AT_PEAK

    prereg = (REPO_ROOT / "docs" / "experiment-a2.md").read_text()
    assert "baseline = **70%** of measured saturation" in prereg, (
        "the pre-registration no longer states the baseline fraction these "
        "constants implement; one of the two moved without the other"
    )
    assert "**0.25 additional replicas**" in prereg, (
        f"the pre-registration does not state the amended k that "
        f"ADDITIONAL_REPLICAS_AT_PEAK={ADDITIONAL_REPLICAS_AT_PEAK} implements. "
        "Changing the traffic model is an amendment to a pre-registered "
        "quantity, not a code edit"
    )
