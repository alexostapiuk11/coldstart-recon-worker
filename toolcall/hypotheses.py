"""H1-H5 as amended (amendment §2), each one estimand, one direction and one
p-value, with Holm's correction across the testable ones (§4f).

Failure rate is the share of graded repetitions not CORRECT. Every effect is a
risk difference on that scale, and every p-value is a one-sided cluster-
bootstrap p-value: the share of draws on the wrong side of zero. "Wrong side"
means the side opposite the claim: a claim that an effect is negative (H1, H2)
reads `p_ge_0`, the mass at or above zero; a claim that it is positive (H3, H4,
and H5's difference part) reads `p_le_0`. Reading the other tail would give a
p near 1 for a true effect, and that hypothesis could never be rejected.

- H1: interaction(richness, count) on failure rate < 0.
- H2: main(strictness) on MALFORMED + WRONG_PARAMS < 0, and main(strictness)
  on WRONG_TOOL with its 90% interval inside +/- delta2. Holm uses the first
  part's p-value (`p_ge_0`, the claim is negative); H2 is supported only if
  Holm rejects it and the equivalence part also passes. `failed_part` says
  which one failed: "difference", "equivalence", or None when supported.
- H3: main(count) on WRONG_TOOL > 0, and larger than |main(richness)| and
  |main(strictness)| on WRONG_TOOL. An intersection-union test: its p-value is
  the largest of the three one-sided p-values. The top level carries the count
  effect's point and interval; every part's own p-values are in `parts`.
- H4: identical-retry rate, opaque minus actionable, > 0, over persistent error
  kinds and injected conversations. The rate is computed per scenario, recovery
  cell and format; a (scenario, cell) counts only where both formats were run
  there, so the two formats are always compared on the same cells; a scenario's
  difference is the mean of its per-cell differences (equal cell weight), and
  the bootstrap is over scenarios. The floor rule reads the opaque rate
  averaged the same way (same cells, same weights, then over scenarios). Not
  testable if that opaque rate is under the floor, or if fewer scenarios than
  the bootstrap floor have a cell with both formats.
- H5: main(count) on failure rate is real and larger than the same contrast on
  the A/A rows. An intersection-union test: p is the larger of (a) the one-sided
  p of |t| - |a| <= 0 and (b) the two-sided bootstrap p of t = 0, where t is the
  count contrast and a the A/A one. With near-deterministic reruns a is ~0, so
  (a) alone is ~|t| > 0 on every draw and rejects whatever the data; (b) is what
  requires t to be distinguishable from zero. Both p-values come from the same
  resamples (the same seed draws the same scenario indices), `parts` has both,
  and `count_effect` the count contrast's own point and interval.

Every hypothesis reads the one analysable scenario set the caller passes in
(`evaluate(..., scenarios=...)`), so the headline effects and the hypotheses
cannot disagree about which scenarios were analysed. H5 alone may use fewer: a
scenario with an empty even or odd half in any cell has no A/A contrast, so it
is dropped from H5 only and disclosed there.
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
from toolcall.formulation import CELLS
from toolcall.grader import FAILURES
from toolcall.scenarios import PERSISTENT_KINDS


def bootstrap_params(prereg) -> dict:
    """The one place the pre-registered bootstrap settings are read: every
    bootstrap in the analysis and the hypotheses takes `**bootstrap_params(p)`,
    so no call can carry its own iterations, seed or alpha. The keys are the
    names `cluster_bootstrap` and `cost_per_success` both take."""
    return {"iterations": prereg.iterations, "seed": prereg.bootstrap_seed,
            "alpha": prereg.alpha}


def _h1(outcomes, scenarios, prereg) -> dict:
    rows = rate_rows(outcomes, FAILURES, scenarios=scenarios)
    r = cluster_bootstrap(rows, lambda rs: average(
        contrast(x, "interaction:richness:count") for x in rs), **bootstrap_params(prereg))
    return {"estimand": "interaction(richness, count) on failure rate", "direction": "< 0",
            **r, "p": r["p_ge_0"]}


def _h2(outcomes, scenarios, prereg) -> dict:
    rows = rate_rows(outcomes, ("MALFORMED", "WRONG_PARAMS"), scenarios=scenarios)
    a = cluster_bootstrap(rows, lambda rs: average(
        contrast(x, "main:strictness") for x in rs), **bootstrap_params(prereg))
    wt = rate_rows(outcomes, ("WRONG_TOOL",), scenarios=scenarios)
    # a 90% interval: two one-sided tests
    kw = {**bootstrap_params(prereg), "alpha": 2 * prereg.alpha}
    b = cluster_bootstrap(wt, lambda rs: average(contrast(x, "main:strictness") for x in rs),
                          **kw)
    equivalent = -prereg.delta2 < b["lo"] and b["hi"] < prereg.delta2
    return {"estimand": "main(strictness) on MALFORMED + WRONG_PARAMS", "direction": "< 0",
            **a, "p": a["p_ge_0"],
            "equivalence": {"estimand": "main(strictness) on WRONG_TOOL",
                            "margin": prereg.delta2, **b, "passes": equivalent}}


def _h3(outcomes, scenarios, prereg) -> dict:
    rows = rate_rows(outcomes, ("WRONG_TOOL",), scenarios=scenarios)
    kw = bootstrap_params(prereg)

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
    count = parts["count"]
    # The count part's own one-sided p-values live in parts["count"] only: the
    # top-level p is the maximum over all three parts, a different number.
    return {"estimand": "main(count) on WRONG_TOOL, and its margin over the other two",
            "direction": "> 0",
            **{k: count[k] for k in ("point", "lo", "hi", "n_scenarios", "iterations", "alpha")},
            "p": p, "parts": parts}


def _h4(recovery_records, prereg) -> dict:
    by: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for r in recovery_records:
        if r.excluded or not r.injected or r.error_kind not in PERSISTENT_KINDS:
            continue
        if r.identical_retry is None:
            continue
        by[r.scenario_id][r.cell][r.fmt].append(bool(r.identical_retry))
    units = []
    for _, cells in sorted(by.items()):
        # Only cells where both formats ran: opaque and actionable are then
        # compared on the same cells, whatever cells either format lost.
        both = [v for _, v in sorted(cells.items()) if v.get("opaque") and v.get("actionable")]
        if both:
            units.append((average(sum(v["opaque"]) / len(v["opaque"]) for v in both),
                          average(sum(v["actionable"]) / len(v["actionable"]) for v in both)))
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
    r = cluster_bootstrap(units, lambda us: average(o - a for o, a in us),
                          **bootstrap_params(prereg))
    return {**base, **r, "testable": True, "opaque_rate": opaque, "p": r["p_le_0"]}


def _has_both_halves(outcomes, sid) -> bool:
    for cell in CELLS:
        reps = outcomes.get(sid, {}).get(cell.name, [])
        if not any(b % 2 == 0 for b, _ in reps) or not any(b % 2 == 1 for b, _ in reps):
            return False
    return True


def _h5(outcomes, scenarios, prereg) -> dict:
    keep = [s for s in sorted(scenarios) if _has_both_halves(outcomes, s)]
    dropped = [s for s in sorted(scenarios) if s not in set(keep)]
    base = {"estimand": "|main(count) on failure| minus |the A/A contrast|",
            "direction": "> 0", "n_scenarios": len(keep), "dropped_scenarios": dropped}
    if len(keep) < MIN_BOOTSTRAP_SAMPLES:
        return {**base, "testable": False,
                "reason": f"{len(keep)} scenarios with both halves in every cell; the "
                          f"bootstrap floor is {MIN_BOOTSTRAP_SAMPLES}"}
    # Both row sets come from the one `keep` list, so the zip pairs a scenario's
    # failure rates with its own A/A contrasts and nothing else.
    rows = rate_rows(outcomes, FAILURES, scenarios=keep)
    aa = half_rows(outcomes, FAILURES, scenarios=keep)
    assert len(rows) == len(aa) == len(keep), "H5 rows and A/A rows must cover one scenario list"
    pairs = list(zip(rows, aa, strict=True))

    def count_stat(ps):
        return average(contrast(r, "main:count") for r, _ in ps)

    def difference_stat(ps):
        a = average(contrast(h, "main:count") for _, h in ps)
        return abs(count_stat(ps)) - abs(a)

    # The same seed resamples the same scenario indices (the statistic never
    # touches the generator), so both p-values are read off the same draws.
    kw = bootstrap_params(prereg)
    diff = cluster_bootstrap(pairs, difference_stat, **kw)
    count = cluster_bootstrap(pairs, count_stat, **kw)
    p_difference = diff["p_le_0"]
    p_nonzero = min(1.0, 2 * min(count["p_le_0"], count["p_ge_0"]))
    return {**base, **diff, "testable": True, "p": max(p_difference, p_nonzero),
            "count_effect": {k: count[k] for k in ("point", "lo", "hi")},
            "parts": {"abs_count_minus_abs_aa": {"p": p_difference},
                      "count_effect_nonzero": {"p": p_nonzero}}}


def evaluate(outcomes, recovery_records, prereg, scenarios=None) -> dict:
    """`scenarios`: the analysable set (default: every scenario in `outcomes`)."""
    scenarios = sorted(scenarios if scenarios is not None else outcomes)
    out = {"H1": _h1(outcomes, scenarios, prereg), "H2": _h2(outcomes, scenarios, prereg),
           "H3": _h3(outcomes, scenarios, prereg), "H4": _h4(recovery_records, prereg),
           "H5": _h5(outcomes, scenarios, prereg)}
    testable = {k: v["p"] for k, v in out.items() if v.get("testable", True)}
    rejected = holm(testable, prereg.alpha)
    for key, h in out.items():
        if key not in testable:
            h["verdict"] = "not testable"
            continue
        h["holm_rejects"] = rejected[key]
        supported = rejected[key] and (key != "H2" or h["equivalence"]["passes"])
        h["verdict"] = "supported" if supported else "not supported"
        if key == "H2":
            h["failed_part"] = (None if supported
                                else "difference" if not rejected[key] else "equivalence")
    return out
