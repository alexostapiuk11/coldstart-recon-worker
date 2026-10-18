"""The page's widget code, run under Node against the Python it mirrors.

The frontier is the one that matters: the page draws its own frontier in the browser,
and a frontier drawn differently from autoscale.frontier.pareto_frontier would put a
wrong picture under the post's numbers. So explainer_a2/lib.js is loaded as written
(not a port of it) and its answers are compared with Python's, on all thirteen sweeps
in data/a2/frontier-sweep.json and on tied-cost cases built for the purpose.
"""

import importlib.util
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from autoscale.frontier import PolicyPoint, iso_cost_budget, pareto_frontier

REPO = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

RUNNER = r"""
const fs = require("fs"), vm = require("vm");
const code = fs.readFileSync(process.argv[1], "utf8");
const A2 = vm.runInNewContext(code + "; A2");
const input = JSON.parse(fs.readFileSync(0, "utf8"));
const out = {};
for (const [name, call] of Object.entries(input)) {
  out[name] = eval("(" + call.fn + ")")(A2, call.args);
}
process.stdout.write(JSON.stringify(out));
"""


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


def node(calls: dict) -> dict:
    r = subprocess.run([NODE, "-e", RUNNER, str(REPO / "explainer_a2" / "lib.js")],
                       input=json.dumps(calls), capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


SWEEPS = json.loads((REPO / "data/a2/frontier-sweep.json").read_text())["sources"]
ANALYSIS = B.analysis(REPO)


def _policies(rows):
    """{signal: [[cost, p99, up, down]]} with the medians Python's PolicyPoint takes."""
    by = {}
    for p in B._points(rows):
        by.setdefault(p.signal, []).append([p.cost, p.p99, p.scale_up_at, p.scale_down_at])
    return by


def _py_frontier(rows, signal):
    pts = [p for p in B._points(rows) if p.signal == signal]
    return [[p.cost, p.p99, p.scale_up_at, p.scale_down_at] for p in pareto_frontier(pts)]


def test_the_scripts_parse():
    for name in ("lib.js", "ui.js"):
        r = subprocess.run([NODE, "--check", str(REPO / "explainer_a2" / name)],
                           capture_output=True, text=True, check=False)
        assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("label", sorted(SWEEPS))
def test_js_frontier_equals_pareto_frontier_on_every_sweep(label):
    policies = _policies(SWEEPS[label])
    got = node({"f": {"fn": "(A2,a)=>{const r=A2.sweepFrontiers(a);const o={};"
                            "for(const s in r)o[s]=r[s].frontier.map(p=>[p.cost,p.p99,p.up,p.down]);return o}",
                    "args": policies}})["f"]
    assert set(got) == set(policies)
    for signal in policies:
        assert got[signal] == _py_frontier(SWEEPS[label], signal), (label, signal)


@pytest.mark.parametrize("label", ["arm A", "arm C", "ramp arm A", "ramp arm C"])
def test_js_iso_budget_and_reach_equal_the_posts(label):
    policies = _policies(SWEEPS[label])
    got = node({"b": {"fn": "(A2,a)=>{const r=A2.sweepFrontiers(a.p);const fr={};"
                            "for(const s in r)fr[s]=r[s].frontier;"
                            "const reach={};for(const s in fr){const b=A2.bestAtBudget(fr[s],a.budget);"
                            "reach[s]=b&&b.p99}"
                            "return {rule:A2.isoBudget(fr),reach}}",
                    "args": {"p": policies, "budget": 3095}}})["b"]
    py_front = {s: pareto_frontier([p for p in B._points(SWEEPS[label]) if p.signal == s])
                for s in B.SIGNAL_ORDER}
    assert got["rule"] == iso_cost_budget(py_front)
    for signal, reached in ANALYSIS["simulator"]["sweeps"][label]["reached"].items():
        assert got["reach"][signal] == reached["p99_s"], (label, signal)
    assert round(got["rule"]) == 3095


def test_js_frontier_matches_python_on_ties_and_float_dust():
    """Built for the case the Python docstring describes: nineteen policies with the same
    cost to the 13th digit, where an exact comparison publishes a staircase of dust."""
    import random

    rng = random.Random(3)
    rows = []
    for k in range(40):
        cost = 670.0 * (1 + rng.choice([0, 4e-15, -3e-15, 7e-16])) if k < 25 else rng.uniform(600, 900)
        rows.append([cost, rng.uniform(1, 12)])
    pts = [PolicyPoint(cost_samples=(c,), p99_samples=(p,), signal="s", scale_up_at=float(i),
                       scale_down_at=0.0) for i, (c, p) in enumerate(rows)]
    want = [[p.cost, p.p99, p.scale_up_at] for p in pareto_frontier(pts)]
    got = node({"f": {"fn": "(A2,a)=>A2.pareto(a.map((r,i)=>({cost:r[0],p99:r[1],up:i}))).map(p=>[p.cost,p.p99,p.up])",
                      "args": rows}})["f"]
    assert got == want
    assert len(got) < len(rows)


def test_the_blobs_frontier_inputs_are_pythons_medians():
    blob = B.build_blob(REPO)
    for sweep in blob["sweeps"]:
        py = {s: [[p.cost, p.p99, p.scale_up_at, p.scale_down_at] for p in B._points(SWEEPS[sweep["key"]])
                  if p.signal == s] for s in B.SIGNAL_ORDER}
        assert sweep["policies"] == py


def test_curve_readout_at_a_measured_level_and_between_levels():
    levels = B.build_blob(REPO)["curve"]["levels"]
    out = node({
        "at64": {"fn": "(A2,a)=>A2.curveAt(a,64,false)", "args": levels},
        "at48": {"fn": "(A2,a)=>A2.curveAt(a,48,false)", "args": levels},
        "at129": {"fn": "(A2,a)=>A2.curveAt(a,129,false)", "args": levels},
        "half": {"fn": "(A2,a)=>A2.curveAt(a,0.5,true)", "args": levels},
        "nohalf": {"fn": "(A2,a)=>A2.curveAt(a,0.5,false)", "args": levels},
    })
    lv = {x["c"]: x for x in levels}
    assert out["at64"]["lat"] == lv[64]["lat"] and out["at64"]["measured"] is True
    assert out["at64"]["perReq"] == lv[64]["tps"] / 64
    f = (48 - 32) / 32
    assert abs(out["at48"]["lat"] - (lv[32]["lat"] + f * (lv[64]["lat"] - lv[32]["lat"]))) < 1e-12
    assert abs(out["at48"]["tps"] - (lv[32]["tps"] + f * (lv[64]["tps"] - lv[32]["tps"]))) < 1e-9
    assert out["at48"]["measured"] is False
    assert out["at129"] is None, "the curve is not extrapolated past 128"
    assert out["nohalf"] is None and abs(out["half"]["tps"] - lv[1]["tps"] / 2) < 1e-12
    # the figures the readout shows at 64: 0.439 s, 2,233 tokens/s, 34.9 per request
    assert f"{out['at64']['lat']:.3f}" == "0.439"
    assert f"{out['at64']['tps']:,.0f}" == "2,233"
    assert f"{out['at64']['perReq']:.1f}" == "34.9"


def test_littles_law_solves_each_unknown_and_refuses_ambiguity():
    out = node({
        "L": {"fn": "(A2,a)=>A2.little({L:null,lambda:100,W:0.4})", "args": None},
        "lam": {"fn": "(A2,a)=>A2.little({L:40,lambda:null,W:0.4})", "args": None},
        "W": {"fn": "(A2,a)=>A2.little({L:40,lambda:100,W:null})", "args": None},
        "two": {"fn": "(A2,a)=>A2.little({L:null,lambda:null,W:1})", "args": None},
        "zero": {"fn": "(A2,a)=>A2.little({L:5,lambda:null,W:0})", "args": None},
    })
    assert out["L"]["L"] == 40 and out["lam"]["lambda"] == 100 and out["W"]["W"] == 0.4
    assert out["two"] is None and out["zero"]["lambda"] is None


def test_little_rows_are_the_hand_computation_for_probe_one_step_fifty():
    blob = B.build_blob(REPO)
    rows = node({"r": {"fn": "(A2,a)=>A2.twoWorkerRows(a,'1')", "args": blob["probes"]}})["r"]
    r50 = next(r for r in rows if r["step"] == 50)
    s = ANALYSIS["load_balancer"]["probes"]["1"]["steps"]["50"]
    w = s["per_worker_concurrency"]
    want = (w["worker 1"]["mean"] + w["worker 2"]["mean"]) / s["delivered_rate_rps"]
    assert r50["W"] == want
    assert f"{r50['W']:.3f}" == "0.308" and f"{r50['serverP50']:.3f}" == "0.310"
    assert f"{r50['means'][0]:.2f}" == "2.62" and f"{r50['means'][1]:.2f}" == "2.65"
    assert [r["step"] for r in rows] == [25, 50, 100]


def test_one_worker_rows_equal_the_python_reference():
    blob = B.build_blob(REPO)
    rows = node({"r": {"fn": "(A2,a)=>A2.oneWorkerRows(a.p,a.l,['2','3'])",
                       "args": {"p": blob["probes"], "l": blob["curve"]["levels"]}}})["r"]
    ref = B.one_worker_rows(REPO)
    assert len(rows) == len(ref) == 6
    for js, py in zip(rows, ref, strict=True):
        assert js["probe"] == py["probe"] and js["step"] == py["step"]
        assert abs(js["W"] - py["W"]) < 1e-12 and abs(js["curve"] - py["curve"]) < 1e-12
        assert abs(js["diffCurve"] - py["diff"]) < 1e-12


def test_toy_default_run_matches_the_hand_trace():
    """Lag 81.07 s, cooldown 30 s, the registered 1.20x peak: the spike starts at 30 s,
    the first check after it is at 35 s and requests a replica, the next requests are
    held by the cooldown to 65, 95 and 125 s, the first replica is ready at 116.07 s."""
    t = B.build_blob(REPO)["toy"]
    args = {"lag": t["lag_A"], "cooldown": 30, "peakX": t["peak_x"], "sat": t["sat"], "base": t["base"],
            "sustain": t["sustain"], "until": t["until"], "evalEvery": t["eval_every"],
            "maxReplicas": t["max_replicas"], "spikeStart": t["spike_start"], "upAt": t["up_at"]}
    r = node({"t": {"fn": "(A2,a)=>{const r=A2.toy(a);return {firstReq:r.firstReq,firstReady:r.firstReady,"
                          "requested:r.requestedFinal,needed:r.needed,peakB:r.peakB,"
                          "peakWait:r.peakWait,above:r.secondsAbove1}}", "args": args}})["t"]
    assert r["firstReq"] == 35.0
    assert abs(r["firstReady"] - (35 + t["lag_A"])) < 0.25
    assert r["requested"] == 5 and r["needed"] == 2
    # fluid arithmetic: the backlog grows at (peak - one replica's capacity) until a second is ready
    excess = t["sat"] * t["peak_x"] - t["sat"]
    assert abs(r["peakB"] - excess * (r["firstReady"] - 30)) < 0.02 * r["peakB"]


def test_toy_cooldown_zero_overshoots_to_the_cap_and_a_short_lag_does_not():
    t = B.build_blob(REPO)["toy"]

    def run(lag, cooldown, peak_x):
        args = {"lag": lag, "cooldown": cooldown, "peakX": peak_x, "sat": t["sat"], "base": t["base"],
                "sustain": t["sustain"], "until": t["until"], "evalEvery": t["eval_every"],
                "maxReplicas": t["max_replicas"], "spikeStart": t["spike_start"], "upAt": t["up_at"]}
        return node({"t": {"fn": "(A2,a)=>{const r=A2.toy(a);return {n:r.requestedFinal,b:r.peakB}}",
                           "args": args}})["t"]

    assert run(t["lag_A"], 0, t["peak_x"])["n"] == t["max_replicas"]
    assert run(5, 30, t["peak_x"])["n"] == 2
    slow = run(t["lag_C"], 60, 2.5)
    quick = run(t["lag_C"], 0, 2.5)
    assert slow["b"] > quick["b"], "a long cooldown responds more slowly when more than one replica is needed"


def test_monte_carlo_a_perfect_model_misses_about_the_analytic_share():
    mc = B.build_blob(REPO)["mc"]
    args = {"bins": mc["bins"], "truth": mc["truth"], "factor": 1.0, "spread": mc["spread_default"] / 100,
            "tol": mc["tol"], "minBins": mc["min_bins"], "maxMissFraction": mc["max_miss_fraction"]}
    far = dict(args, spread=0.15)
    off = dict(args, factor=1.13)
    r = node({
        "default": {"fn": "(A2,a)=>A2.mcMany(a,A2.mulberry32(11),4000)", "args": args},
        "wide": {"fn": "(A2,a)=>A2.mcMany(a,A2.mulberry32(12),4000)", "args": far},
        "off": {"fn": "(A2,a)=>{const x=A2.mcRun(a,A2.mulberry32(5));return {m:x.misses,"
                      "p:A2.mcPasses(x.misses,a.bins,a.minBins,a.maxMissFraction)}}", "args": off},
        "exp": {"fn": "(A2,a)=>[A2.perfectMissProb(a.spread,a.truth,a.tol),"
                      "A2.perfectMissProb(0.15,a.truth,a.tol)]", "args": args},
        "lim": {"fn": "(A2,a)=>[A2.mcPasses(18,37,10,0.5),A2.mcPasses(19,37,10,0.5),A2.mcPasses(0,9,10,0.5)]",
                "args": None},
    })
    q = 0.5 * math.erfc(args["tol"] / (args["spread"] * args["truth"]) / math.sqrt(2))
    assert abs(r["exp"][0] - 2 * q**3) < 1e-6
    q15 = 0.5 * math.erfc(args["tol"] / (0.15 * args["truth"]) / math.sqrt(2))
    assert abs(r["exp"][1] - 2 * q15**3) < 1e-6
    assert abs(r["default"]["meanMissFraction"] - r["exp"][0]) < 0.01
    assert abs(r["wide"]["meanMissFraction"] - 0.25) < 0.015, "tends to the rule's one in four"
    assert r["off"]["m"] == 37 and r["off"]["p"] is False
    assert r["lim"] == [True, False, False], "18 of 37 passes, 19 fails, nine bins are too few"
    assert r["default"]["passShare"] > 0.99


def test_symlog_is_continuous_at_the_threshold_and_odd():
    r = node({"s": {"fn": "(A2,a)=>[A2.symlog(0.01,0.01),A2.symlog(0.0100001,0.01),A2.symlog(-6,0.01),"
                          "A2.symlog(6,0.01),A2.symlog(0,0.01)]", "args": None}})["s"]
    assert abs(r[0] - r[1]) < 1e-4 and r[2] == -r[3] and r[4] == 0


def test_dominance_in_the_two_policy_exercise():
    r = node({
        "ex": {"fn": "(A2,a)=>A2.dominatedFlags([{cost:100,dmg:50},{cost:120,dmg:40}])", "args": None},
        "dom": {"fn": "(A2,a)=>A2.dominatedFlags([{cost:100,dmg:50},{cost:90,dmg:40}])", "args": None},
        "tie": {"fn": "(A2,a)=>A2.dominatedFlags([{cost:100,dmg:50},{cost:100,dmg:50}])", "args": None},
    })
    assert r["ex"] == [False, False]
    assert r["dom"] == [True, False]
    assert r["tie"] == [False, False], "equal points do not dominate each other"
