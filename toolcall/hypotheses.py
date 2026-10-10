"""H1-H5 as amended (amendment §2), each one estimand, one direction and one
p-value, with Holm's correction across the testable ones (§4f).

Failure rate is the share of graded repetitions not CORRECT. Every effect is a
risk difference on that scale, and every p-value is a one-sided cluster-
bootstrap p-value: the share of draws on the wrong side of zero.

- H1: interaction(richness, count) on failure rate < 0.
- H2: main(strictness) on MALFORMED + WRONG_PARAMS < 0, and main(strictness)
  on WRONG_TOOL with its 90% interval inside +/- delta2. Holm uses the first
  part's p-value; H2 is supported only if Holm rejects it and the equivalence
  part also passes.
- H3: main(count) on WRONG_TOOL > 0, and larger than |main(richness)| and
  |main(strictness)| on WRONG_TOOL. An intersection-union test: its p-value is
  the largest of the three one-sided p-values.
- H4: identical-retry rate, opaque minus actionable, > 0, over persistent error
  kinds and injected conversations, per scenario averaged over the recovery
  cells. Not testable if the opaque rate's point estimate is under the floor,
  or if fewer scenarios than the bootstrap floor have both formats.
- H5: |main(count) on failure rate| minus |the same contrast on the A/A rows|
  > 0.
"""

from collections import defaultdict

from harness.stats import MIN_BOOTSTRAP_SAMPLES
from toolcall.effects import (
    average,
    cluster_bootstrap,
    contrast,
    half_rows,
    holm,
    rate_rows,
)
from toolcall.grader import FAILURES
from toolcall.scenarios import PERSISTENT_KINDS


def _kw(prereg) -> dict:
    return {"iterations": prereg.iterations, "seed": prereg.bootstrap_seed,
            "alpha": prereg.alpha}


def _h1(outcomes, prereg) -> dict:
    rows = rate_rows(outcomes, FAILURES)
    r = cluster_bootstrap(rows, lambda rs: average(
        contrast(x, "interaction:richness:count") for x in rs), **_kw(prereg))
    return {"estimand": "interaction(richness, count) on failure rate", "direction": "< 0",
            **r, "p": r["p_ge_0"]}


def _h2(outcomes, prereg) -> dict:
    rows = rate_rows(outcomes, ("MALFORMED", "WRONG_PARAMS"))
    a = cluster_bootstrap(rows, lambda rs: average(
        contrast(x, "main:strictness") for x in rs), **_kw(prereg))
    wt = rate_rows(outcomes, ("WRONG_TOOL",))
    kw = {**_kw(prereg), "alpha": 2 * prereg.alpha}  # a 90% interval: two one-sided tests
    b = cluster_bootstrap(wt, lambda rs: average(contrast(x, "main:strictness") for x in rs),
                          **kw)
    equivalent = -prereg.delta2 < b["lo"] and b["hi"] < prereg.delta2
    return {"estimand": "main(strictness) on MALFORMED + WRONG_PARAMS", "direction": "< 0",
            **a, "p": a["p_le_0"],
            "equivalence": {"estimand": "main(strictness) on WRONG_TOOL",
                            "margin": prereg.delta2, **b, "passes": equivalent}}


def _h3(outcomes, prereg) -> dict:
    rows = rate_rows(outcomes, ("WRONG_TOOL",))
    kw = _kw(prereg)

    def stat(name):
        def f(rs):
            t = average(contrast(x, "main:count") for x in rs)
            if name == "count":
                return t
            other = average(contrast(x, f"main:{name}") for x in rs)
            return t - abs(other)
        return f

    parts = {name: cluster_bootstrap(rows, stat(name), **kw)
             for name in ("count", "richness", "strictness")}
    p = max(part["p_le_0"] for part in parts.values())
    return {"estimand": "main(count) on WRONG_TOOL, and its margin over the other two",
            "direction": "> 0", **parts["count"], "p": p,
            "margins": {"over_richness": parts["richness"],
                        "over_strictness": parts["strictness"]}}


def _h4(recovery_records, prereg) -> dict:
    by: dict = defaultdict(lambda: defaultdict(list))
    for r in recovery_records:
        if r.excluded or not r.injected or r.error_kind not in PERSISTENT_KINDS:
            continue
        if r.identical_retry is None:
            continue
        by[r.scenario_id][r.fmt].append(bool(r.identical_retry))
    units = [
        (sum(v["opaque"]) / len(v["opaque"]), sum(v["actionable"]) / len(v["actionable"]))
        for _, v in sorted(by.items())
        if v.get("opaque") and v.get("actionable")
    ]
    base = {"estimand": "identical-retry rate, opaque minus actionable", "direction": "> 0",
            "n_scenarios": len(units), "floor": prereg.identical_retry_floor}
    if len(units) < MIN_BOOTSTRAP_SAMPLES:
        return {**base, "testable": False,
                "reason": f"{len(units)} scenarios with both formats; the bootstrap floor is "
                          f"{MIN_BOOTSTRAP_SAMPLES}"}
    opaque = average(o for o, _ in units)
    if opaque < prereg.identical_retry_floor:
        return {**base, "testable": False, "opaque_rate": opaque,
                "reason": f"opaque identical-retry rate {opaque:.3f} is below the floor"}
    r = cluster_bootstrap(units, lambda us: average(o - a for o, a in us), **_kw(prereg))
    return {**base, **r, "testable": True, "opaque_rate": opaque, "p": r["p_le_0"]}


def _h5(outcomes, prereg) -> dict:
    rows = rate_rows(outcomes, FAILURES)
    aa = half_rows(outcomes, FAILURES)
    pairs = list(zip(rows, aa))

    def stat(ps):
        t = average(contrast(r, "main:count") for r, _ in ps)
        a = average(contrast(h, "main:count") for _, h in ps)
        return abs(t) - abs(a)

    r = cluster_bootstrap(pairs, stat, **_kw(prereg))
    return {"estimand": "|main(count) on failure| minus |the A/A contrast|",
            "direction": "> 0", **r, "p": r["p_le_0"]}


def evaluate(outcomes, recovery_records, prereg) -> dict:
    out = {"H1": _h1(outcomes, prereg), "H2": _h2(outcomes, prereg),
           "H3": _h3(outcomes, prereg), "H4": _h4(recovery_records, prereg),
           "H5": _h5(outcomes, prereg)}
    testable = {k: v["p"] for k, v in out.items() if v.get("testable", True)}
    rejected = holm(testable, prereg.alpha)
    for key, h in out.items():
        if key not in testable:
            h["verdict"] = "not testable"
            continue
        h["holm_rejects"] = rejected[key]
        supported = rejected[key] and (key != "H2" or h["equivalence"]["passes"])
        h["verdict"] = "supported" if supported else "not supported"
    return out
