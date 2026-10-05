import ast
import math
import textwrap
from pathlib import Path

import pytest

from autoscale.service import SERVICE_CURVE_PLACEHOLDER, ServiceCurve
from autoscale.traffic import (
    ADDITIONAL_REPLICAS_AT_PEAK,
    BASELINE_FRACTION_OF_SATURATION,
    RAMP_SECONDS,
    SUSTAIN_SECONDS,
    saturation_rps,
    spike_shape,
)

REPO = Path(__file__).resolve().parents[1]


def test_saturation_is_the_best_point_not_the_last():
    """Continuous batching makes throughput non-monotonic past the knee. On the
    placeholder the top point (64 at 2.10 s) sustains 30.5 rps while 32 at
    0.95 s sustains 33.7 -- reading the last point understates saturation 9%."""
    assert saturation_rps(SERVICE_CURVE_PLACEHOLDER) == pytest.approx(32 / 0.95)
    assert saturation_rps(SERVICE_CURVE_PLACEHOLDER) > 64 / 2.10


@pytest.mark.parametrize(
    ("points", "match"),
    [
        pytest.param([(0, 0.3, 1.0, 0.1)], "at least two points", id="too_few_points"),
        pytest.param(
            [(-1, 0.3, 1.0, 0.1), (0, 0.3, 1.0, 0.1)],
            "serve at negative concurrency",
            id="negative_concurrency",
        ),
        pytest.param(
            [(0, 0.3, 1.0, 0.1), (0, 0.3, 1.0, 0.1)], "distinct", id="duplicate_concurrency"
        ),
    ],
)
def test_every_constructible_curve_has_a_positive_concurrency_point(points, match):
    """`saturation_rps` takes a max over points with positive concurrency and
    has no empty-case guard, because ServiceCurve makes the empty case
    unconstructible: at least two points, distinct concurrencies, none
    negative -- so at least one is positive. Each of those three guarantees is
    pinned separately, matched against ServiceCurve's own refusal message, so
    that if any one of them is relaxed this fails instead of `saturation_rps`
    raising a context-free `max()` error (too few points, or the only point
    negative) or a silent division by zero (duplicate concurrencies)."""
    with pytest.raises(ValueError, match=match):
        ServiceCurve(points=points, measured=False)


def test_a_zero_concurrency_point_does_not_poison_saturation():
    """ServiceCurve accepts concurrency 0 (an idle replica is a legitimate
    measurement, and `is_extrapolating`/`_interpolate` both treat below-range
    queries as ordinary clamping, not a corner case). `saturation_rps` filters
    to `c > 0` before taking the max specifically so this point cannot become
    `0 / latency_at(0)` -- 0.0 divided by a finite latency, which Python
    raises ZeroDivisionError on rather than returning nan. Without the
    filter, any curve measured down to an idle replica would make
    `saturation_rps` raise on every call instead of returning the rate at the
    curve's actual best operating point."""
    curve = ServiceCurve(points=[(0, 0.0, 0.0, 0.0), (1, 0.5, 50.0, 0.9)], measured=False)
    result = saturation_rps(curve)
    assert math.isfinite(result)
    assert result > 0


def test_the_step_follows_the_preregistered_rule():
    sat = saturation_rps(SERVICE_CURVE_PLACEHOLDER)
    shape = spike_shape(SERVICE_CURVE_PLACEHOLDER, "step")
    assert shape.kind == "step"
    assert shape.baseline_rate == pytest.approx(0.70 * sat, rel=1e-15)
    assert shape.k == pytest.approx((0.70 + 0.5) / 0.70, rel=1e-12)
    assert shape.ramp == 0.0
    assert shape.sustain == 190.0


def test_the_ramp_is_half_the_sustain():
    assert spike_shape(SERVICE_CURVE_PLACEHOLDER, "ramp").ramp == 95.0


def test_a_reduced_window_keeps_r_equal_to_d_over_two():
    """The end-to-end test halves the window for speed. R = D/2 must hold there
    too, which is why the ramp is derived rather than accepted."""
    shape = spike_shape(SERVICE_CURVE_PLACEHOLDER, "ramp", sustain=95.0)
    assert shape.ramp == 47.5


def test_a_candidate_regime_can_be_measured_before_it_is_adopted():
    shape = spike_shape(
        SERVICE_CURVE_PLACEHOLDER, "step", baseline_fraction=0.40, additional_replicas=0.5
    )
    assert shape.k == pytest.approx((0.40 + 0.5) / 0.40)


@pytest.mark.parametrize("name", ["sustain", "baseline_fraction", "additional_replicas"])
@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
def test_non_positive_or_non_finite_parameters_are_refused(name, bad):
    with pytest.raises(ValueError, match=name):
        spike_shape(SERVICE_CURVE_PLACEHOLDER, "step", **{name: bad})


def test_a_zero_sustain_message_names_its_own_consequence():
    """Every refused parameter gets its own consequence, not one generic
    sentence shared by all three -- the `(name, value, consequence)` pattern
    `autoscale/arrivals.py` already uses for `SpikeShape`'s own fields. A
    reader debugging `sustain=0` should not have to work out, from a message
    written for `additional_replicas`, why a zero sustain is a problem."""
    with pytest.raises(ValueError, match="holds the peak for no time"):
        spike_shape(SERVICE_CURVE_PLACEHOLDER, "step", sustain=0.0)


def test_an_infinite_baseline_fraction_message_names_its_own_consequence():
    """The consequence text has to cover the infinite/NaN case too, not just
    zero and negative -- a message that only explains why zero is bad would
    say nothing useful about why `float('inf')` is bad."""
    with pytest.raises(ValueError, match="poisons"):
        spike_shape(SERVICE_CURVE_PLACEHOLDER, "step", baseline_fraction=float("inf"))


@pytest.mark.parametrize("name", ["sustain", "baseline_fraction", "additional_replicas"])
def test_a_bool_is_refused_even_though_it_passes_isfinite(name):
    """`bool` is a subclass of `int` in Python: `math.isfinite(True)` is
    `True` and `True > 0`, so without an explicit type check a caller who
    passes `sustain=True` -- easy to do by accident from a stray boolean
    expression -- would silently get `sustain=1.0` (one second) instead of an
    error naming the mistake. `TypeError`, not `ValueError`: this is a wrong
    type, not a wrong (if otherwise valid) value."""
    with pytest.raises(TypeError, match=name):
        spike_shape(SERVICE_CURVE_PLACEHOLDER, "step", **{name: True})


def test_the_constants_are_the_ones_the_preregistration_states():
    """An amendment to the traffic model is a change to a pre-registered
    quantity. It has to touch the document, not just this module."""
    prereg = (REPO / "docs" / "experiment-a2.md").read_text()
    assert BASELINE_FRACTION_OF_SATURATION == 0.70
    assert "baseline = **70%** of measured saturation" in prereg
    assert ADDITIONAL_REPLICAS_AT_PEAK == 0.5
    assert "**0.5 additional replicas**" in prereg
    assert SUSTAIN_SECONDS == 190.0
    assert "rounded to **190 s**" in prereg
    assert RAMP_SECONDS == 95.0
    assert "= **95 s**" in prereg


def test_the_bits_are_pinned_not_just_the_algebra():
    """Every other assertion in this file uses `pytest.approx`, which is
    exactly the tolerance that let a real regression through review: changing
    `peak` from `baseline + additional_replicas * saturation` (this module's
    order) to the algebraically equal `(baseline_fraction + additional_replicas)
    * saturation` moves `k` by one ulp for the default step shape and for
    several `(baseline_fraction, additional_replicas)` pairs on the
    placeholder curve, and all of this file's other 19 tests still passed.

    This repository's figures hang on these exact bits: `spike_shape`'s `k`
    feeds `arrival_times`'s thinning accept/reject test in
    `autoscale/arrivals.py` (`rng.random() <= rate_at(shape, t) / max_rate`),
    so a one-ulp change in `k` can flip a single candidate's accept/reject and
    change which timestamps land in the arrival trace -- silently, since nothing
    downstream raises on it.

    The only record of what the OLD copies actually produced is
    `build/plan2a-baseline/shapes.json` (Task 1's baseline), which is
    gitignored; the copies that produced it survived until Task 11 deleted
    them. These hex literals are taken from that file with `float.hex()`, so
    this test keeps that bit-level evidence alive where the baseline file
    cannot: version control.
    """
    sat = saturation_rps(SERVICE_CURVE_PLACEHOLDER)
    assert sat == float.fromhex("0x1.0d79435e50d79p+5")

    # The 0.25 step, the default the baseline file recorded (amended to 0.5 on
    # 2026-10-04, second; the validation gate still runs this spike), passed
    # explicitly so the recorded bits stay checked.
    step = spike_shape(SERVICE_CURVE_PLACEHOLDER, "step", additional_replicas=0.25)
    assert step.baseline_rate == float.fromhex("0x1.79435e50d7943p+4")
    assert step.k == float.fromhex("0x1.5b6db6db6db6ep+0")
    # The current default, pinned from this module's own order of operations.
    now = spike_shape(SERVICE_CURVE_PLACEHOLDER, "step")
    assert now.baseline_rate == float.fromhex("0x1.79435e50d7943p+4")
    assert now.k == float.fromhex("0x1.b6db6db6db6dbp+0")

    # baseline_fraction=0.10, additional_replicas=1 -- one of the candidates
    # the regime probe screens. `k = 1 + additional_replicas / baseline_fraction`
    # (algebraically equal to this module's `peak / baseline`) evaluates to
    # 11.0 exactly here, one ulp below the 11.000000000000002 this module
    # actually produces -- a rejected rewrite, not a rounding choice.
    candidate_a = spike_shape(
        SERVICE_CURVE_PLACEHOLDER, "step", baseline_fraction=0.10, additional_replicas=1
    )
    assert candidate_a.baseline_rate == float.fromhex("0x1.af286bca1af28p+1")
    assert candidate_a.k == float.fromhex("0x1.6000000000001p+3")

    # baseline_fraction=0.20, additional_replicas=2 -- same rejected rewrite,
    # same one-ulp disagreement, at a different point in the candidate grid.
    candidate_b = spike_shape(
        SERVICE_CURVE_PLACEHOLDER, "step", baseline_fraction=0.20, additional_replicas=2
    )
    assert candidate_b.baseline_rate == float.fromhex("0x1.af286bca1af28p+2")
    assert candidate_b.k == float.fromhex("0x1.6000000000001p+3")


# The derivation's one home. Everything else that computes saturation from the
# service curve is a copy, whatever it is named.
DERIVATION_HOME = Path("autoscale") / "traffic.py"
SCANNED_DIRS = ("scripts", "tests", "autoscale")
SHIM_NAMES = ("_saturation_rps", "_preregistered_shape")
RENDER = REPO / "scripts" / "a2_render_figures.py"
# The keywords that turn `spike_shape` into a candidate regime or a different
# window. The production render must pass none of them.
NON_PREREGISTERED_KEYWORDS = ("baseline_fraction", "additional_replicas", "sustain")


def _called_name(call: ast.Call) -> str | None:
    """`f(...)` and `module.f(...)` both name `f`; a guard that only read
    `ast.Name` would miss `arrivals.SpikeShape(...)`."""
    return getattr(call.func, "id", None) or getattr(call.func, "attr", None)


def _saturation_maxes(tree: ast.AST) -> list[int]:
    """Lines of every `max(...)` call whose source reads the service curve's
    latency lookup -- the derivation's signature, independent of what the
    function holding it is called or what it builds afterwards."""
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and _called_name(node) == "max"
        and "latency_at" in ast.unparse(node)
    ]


def _local_derivations(root: Path) -> list[str]:
    """Every copy of the saturation derivation under `root` outside its home.

    String constants that mention the lookup are parsed as Python too: the
    cross-process program in `tests/test_a2_end_to_end.py` hid a copy inside a
    string literal, which neither Task 1's grep nor a name-based guard saw. A
    string that does not parse (prose, an error message) is not code and is
    skipped rather than reported.
    """
    found = []
    for directory in SCANNED_DIRS:
        for path in sorted((root / directory).rglob("*.py")):
            rel = path.relative_to(root)
            if rel == DERIVATION_HOME:
                continue
            tree = ast.parse(path.read_text())
            found += [f"{rel}:{line}" for line in _saturation_maxes(tree)]
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                    continue
                if "latency_at" not in node.value:
                    continue
                try:
                    inner = ast.parse(textwrap.dedent(node.value))
                except SyntaxError:
                    continue
                if _saturation_maxes(inner):
                    found.append(f"{rel}:{node.lineno} (code inside a string)")
    return found


def _script_constructions(root: Path) -> list[str]:
    """Every way a script can build a spike itself: calling `SpikeShape` by
    name or through a module, importing it under another name (which a call
    check by name would then miss), or reviving a deleted shim, sync or async."""
    found = []
    for path in sorted((root / "scripts").glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and _called_name(node) == "SpikeShape":
                found.append(f"{path.name}:{node.lineno}")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                node.name in SHIM_NAMES
            ):
                found.append(f"{path.name}:{node.name}")
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                found += [
                    f"{path.name}:{node.lineno} (SpikeShape imported as {alias.asname})"
                    for alias in node.names
                    if alias.name.rpartition(".")[2] == "SpikeShape"
                    and alias.asname not in (None, "SpikeShape")
                ]
    return found


def test_nothing_derives_saturation_outside_its_one_home():
    """The consolidation, made permanent. Before plan 2a this derivation lived
    as six copies in four files -- the render script, the noise floor, the
    regime probe (twice) and the end-to-end test (twice, once inside a string)
    -- and they agreed only because a test compared two of them and an
    amendment was applied by hand in each. The next copy would be the seventh.

    Detects the derivation's signature, a saturation `max(...)` over the
    service curve, rather than the `SpikeShape` name: the sixth copy built its
    shape the same way under a different variable and was missed by a check
    that looked only at scripts. Parses rather than greps, so prose that
    mentions the lookup is not a violation."""
    offenders = _local_derivations(REPO)
    assert offenders == [], (
        f"{offenders} compute saturation from the service curve locally. Use "
        "autoscale.traffic -- a second copy stops implementing the "
        "pre-registered rule the moment the service curve or an amendment "
        "changes one and not the other"
    )


def test_no_script_constructs_a_spike_shape_itself():
    """Scripts are where the published numbers come from, so for them the ban is
    stricter than the signature check above: no script builds a `SpikeShape`
    at all, by any spelling, and the two deleted shims stay deleted. Naming the
    type in an annotation is allowed -- `_sweep` does -- constructing it is not."""
    offenders = _script_constructions(REPO)
    assert offenders == [], (
        f"{offenders} construct the traffic model locally. Use "
        "autoscale.traffic.spike_shape -- a script that builds its own shape "
        "publishes numbers from a rule nothing else checks"
    )


def test_the_render_draws_the_preregistered_spike_not_a_candidate():
    """`spike_shape`'s overrides exist so the diagnostics can measure a
    candidate regime before it is adopted. The production render passing one
    would publish figures from a traffic model the pre-registration does not
    state, with every other check in this file still green, because they
    test `spike_shape` and not what the render asks it for."""
    tree = ast.parse(RENDER.read_text())
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _called_name(node) == "spike_shape"
    ]
    assert calls, (
        f"{RENDER.name} no longer calls spike_shape, so this test checks "
        "nothing; find where the render's traffic model comes from now"
    )
    overrides = [
        f"line {call.lineno}: {kw.arg or '**kwargs'}"
        for call in calls
        for kw in call.keywords
        if kw.arg is None or kw.arg in NON_PREREGISTERED_KEYWORDS
    ]
    assert overrides == [], (
        f"{RENDER.name} overrides the pre-registered traffic model at {overrides}; "
        "its figures would then be a candidate regime presented as the result"
    )
