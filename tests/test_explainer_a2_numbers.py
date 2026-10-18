"""Every number on the page resolves from committed data, and agrees with the post.

The key list is the contract. A page that disagrees with its own dataset refutes
itself, the same reason artifact 1's explainer has this file.
"""

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
POST = (REPO / "docs" / "post-a2.md").read_text()
PREREG = (REPO / "docs" / "experiment-a2.md").read_text()
A = json.loads((REPO / "data/a2/post-analysis.json").read_text())


def _module():
    if "_build_explainer_a2" in sys.modules:
        return sys.modules["_build_explainer_a2"]
    spec = importlib.util.spec_from_file_location(
        "_build_explainer_a2", REPO / "scripts" / "build_explainer_a2.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["_build_explainer_a2"] = module
    spec.loader.exec_module(module)
    return module


B = _module()


@pytest.mark.parametrize("key", sorted(B.KEYS))
def test_every_key_resolves_to_a_nonempty_string(key):
    out = B.resolve(key, REPO)
    assert isinstance(out, str) and out.strip(), key


def test_unknown_key_raises():
    with pytest.raises(KeyError):
        B.resolve("not_a_key", REPO)


def test_every_spec_has_a_known_source_and_format():
    for key, spec in B.KEYS.items():
        assert spec["src"] in {"analysis", "curve", "sweep", "computed", "const"}, key
        assert re.fullmatch(r"s|d|f\d|pct\d?|ms\d?", spec["fmt"]), key


# The post states these values; the page must state the same strings. Each is
# searched for in docs/post-a2.md as the rendered text, so the check fails if either
# the data, the formatting or the post moves.
IN_THE_POST = {
    "cap_cost": "3,095", "other_a": "2,535", "other_c": "2,320", "other_ra": "2,875",
    "other_rc": "2,448", "lag_a": "81.07", "lag_c": "39.37", "p1_delivered_median": "17.1",
    "p1_server50": "0.31", "p1_client50": "21.74", "host_count": "6", "host_measured": "3",
    "max_engine": "2.59", "max_cal": "0.060", "util_policies": "19", "return_leg": "0.1",
    "p1_cap": "4", "sat": "211.2", "base": "147.8", "peak": "253.4", "peak_x": "1.20",
    "sustain": "190", "every": "5", "cap": "12", "until": "400", "cooldown": "30",
    "top_c": "128", "ex_c": "256", "max_seqs": "256", "p1_ceiling_rps": "25",
    "grid_util": "0.5, 0.65, 0.8, 0.9, 0.95", "bins_judged": "37",
}


@pytest.mark.parametrize("key,needle", sorted(IN_THE_POST.items()))
def test_the_rendered_value_appears_in_the_post(key, needle):
    rendered = B.resolve(key, REPO)
    assert rendered.startswith(needle) or needle in rendered, (key, rendered, needle)
    assert needle in POST + PREREG, f"{needle!r} is in neither the post nor the pre-registration"


def test_the_verdict_numbers_match_the_post_wording():
    assert f"{B.resolve('engine_misses', REPO)} of {B.resolve('bins_judged', REPO)} judged bins" in POST
    assert f"{B.resolve('cal_misses', REPO)} of {B.resolve('bins_judged', REPO)} judged bins" in POST
    assert f"**{B.resolve('pct_engine', REPO)}%**" in POST
    assert f"**{B.resolve('pct_cal', REPO)}%**" in POST


def test_the_margins_and_at_cap_ranges_match_the_post_table():
    assert f"+{B.resolve('margin_worse_a', REPO)} ms" in POST
    assert f"+{B.resolve('margin_better_a', REPO)} ms" in POST
    lo = f"{A['simulator']['h2_noise']['per_sweep']['arm A']['at_cap_policy_p99_s']['min']:.2f}"
    hi = f"{A['simulator']['h2_noise']['per_sweep']['arm A']['at_cap_policy_p99_s']['max']:.2f}"
    assert f"{lo}–{hi} s" in POST


def test_cap_cost_formula_reproduces_the_stated_total():
    """3,095 is not a fitted number: one replica for 400 s plus one more at every 30 s
    cooldown from the 5 s check to the cap of 12, as post-analysis.json defines it."""
    assert B.cap_cost_check(REPO) == 3095
    assert round(A["simulator"]["h2_censoring"]["cap_cost_replica_s"]) == 3095


def test_saturation_is_the_curves_top_level_over_its_latency():
    top = json.loads((REPO / "data/a2/service-curve.json").read_text())["levels"][-1]
    assert abs(B.saturation(REPO) - top["concurrency"] / top["latency_s"]) < 1e-9
    assert round(B.saturation(REPO), 1) == 211.2
    assert round(B.toy_peak(REPO) / B.saturation(REPO), 2) == 1.20


def test_probe_one_numbers_are_the_checkpoint_numbers():
    """The plan's module 2 checkpoint quotes 2.62 and 2.65 in flight, 17.10 req/s,
    a p50 of 0.310 s and a ceiling of about 26 req/s. All of them come from the data."""
    plan = B.plan_checkpoints(REPO)[2]
    assert f"{B.p1_w1(REPO):.2f}" in plan and f"{B.p1_w2(REPO):.2f}" in plan
    assert f"{B.p1_step(REPO, '50')['delivered_rate_rps']:.2f}" in plan
    assert f"{B.p1_server50(REPO):.3f}" in plan
    assert round(B.p1_ceiling_rps(REPO)) == 26
    assert "≈ 26" in plan
    # the check the page shows: (2.62 + 2.65) / 17.10 = 0.308 s
    assert f"{B.p1_time_in_engine(REPO):.3f}" == "0.308"


def test_one_worker_rows_are_a_hand_computed_interpolation():
    rows = {(r["probe"], r["step"]): r for r in B.one_worker_rows(REPO)}
    assert len(rows) == 6
    r = rows[("2", 100)]
    # worker 1 held 37.661377 on average, delivered 100.566081 req/s
    assert abs(r["W"] - 37.661377118189044 / 100.56608073426946) < 1e-12
    lv = {x["concurrency"]: x["latency_s"] for x in
          json.loads((REPO / "data/a2/service-curve.json").read_text())["levels"]}
    want = lv[32] + (37.661377118189044 - 32) / 32 * (lv[64] - lv[32])
    assert abs(r["curve"] - want) < 1e-12
    assert all(x["diff"] < 0 for x in rows.values()), "W is below the curve in every row"


def test_mc_defaults_are_derived_not_typed():
    assert B.resolve("spread_default", REPO) == "1.2"
    assert B.resolve("mc_truth", REPO) == "0.459"
    assert abs(B.factor_engine(REPO) - 1 / 0.8558851671535963) < 1e-12
    assert abs(B.factor_calibrated(REPO) - 1 / 1.1271088407707246) < 1e-12
    assert 0.8 <= B.factor_calibrated(REPO) < 1 < B.factor_engine(REPO) <= 1.2


def test_the_exercise_is_self_check_seven_as_the_spec_words_it():
    spec = (REPO / B.SPEC).read_text()
    a, b = B.EXERCISE
    assert f"({a[0]}, {a[1]}) and ({b[0]}, {b[1]})" in spec


def test_selfchecks_parse_from_the_spec():
    sc = B.spec_selfchecks(REPO)
    assert {5, 6, 7, 8} <= set(sc)
    assert "dead time" in sc[5].lower() and "cooldown" in sc[6].lower()
    assert "dominated" in sc[7] and "arrival" in sc[8]


# Prose carries no hand-typed data number. Every digit string outside a slot, a tag, a
# script or a style must be on this list, each with its reason.
ALLOWED_PROSE_NUMBERS = {
    "0", "1", "2", "3", "4", "5", "6", "7", "8",  # module numbers, probe numbers
    "1.00",  # the host factor of a model with the right speed
    "4090", "3-8",  # RTX 4090, Qwen3-8B: names
    "8B",
}


def test_prose_holds_no_hand_typed_data_number():
    page = PAGE_TEXT = (REPO / "explainer_a2" / "page.html").read_text()
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", PAGE_TEXT, flags=re.DOTALL)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    text = re.sub(r"\{\{[^}]*\}\}", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&\w+;", " ", text)
    text = re.sub(r"\bp(50|99)s?\b", " ", text)
    text = re.sub(r"\b[Qq]wen3-8B\b|\bRTX 4090\b", " ", text)
    text = re.sub(r"\b13b\b", " ", text)
    found = set(re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?", text))
    stray = sorted(f for f in found if f not in ALLOWED_PROSE_NUMBERS)
    assert not stray, f"hand-typed numbers in prose, which belong in numbers.json: {stray}"
    assert page
