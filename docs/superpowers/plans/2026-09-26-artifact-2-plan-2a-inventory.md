# Plan 2a — Traffic-Derivation Inventory and Decision Log

Built by reading the code at the commit plan 2a started from. Every capability
carries a decision. A capability in neither column is a planning bug.

The derivation — baseline a fraction of one replica's saturation, `k` sized to
require a number of additional replicas at the measured service rate — lived in
FOUR places, not the three the 2026-09-17 review counted. The fourth,
`tests/test_a2_end_to_end.py`, was a deliberate independent copy: its docstring
says "the derivation is duplicated rather than imported because `scripts/` is
not an importable package". `autoscale/traffic.py` is importable, so that reason
ends with this plan.

## Consolidated into `autoscale/traffic.py` — behavior unchanged

| # | Capability | Where it lived | Becomes |
|---|---|---|---|
| 1 | Saturation = **max** over measured points of `c / latency_at(c)`, `c > 0` — max, not the last point, because continuous batching makes throughput non-monotonic past the knee | `a2_render_figures._saturation_rps`; `a2_end_to_end._shape` (inline copy) | `saturation_rps(curve)` |
| 2 | Baseline = `BASELINE_FRACTION_OF_SATURATION × saturation`; peak = baseline + `ADDITIONAL_REPLICAS_AT_PEAK × saturation`; `k = peak / baseline` — this exact operation order, so floats stay byte-identical | `a2_render_figures._preregistered_shape`; `a2_gap_noise_floor` (override path); `a2_regime_probe._probe` and `._verify` (inline); `a2_end_to_end._shape` | `spike_shape(curve, kind, ...)` |
| 3 | Sustain `D` = 190 s, as the literal `190.0` in four places | render, noise floor, probe `main`, end-to-end (`SUSTAIN = 95.0`, a deliberately halved window) | `SUSTAIN_SECONDS`, and a `sustain=` keyword for the halved test window |
| 4 | Ramp `R` = `D / 2` = 95 s | `a2_render_figures.RAMP_SECONDS`; end-to-end `RAMP = 47.5` | Derived inside `spike_shape` from `sustain`, so no caller can break R = D/2 |
| 5 | `BASELINE_FRACTION_OF_SATURATION = 0.70`, `ADDITIONAL_REPLICAS_AT_PEAK = 0.25`, with provenance comments | render (module constants); end-to-end (duplicate constants) | `autoscale/traffic.py` constants |
| 6 | Candidate override: a caller may pass a different baseline fraction / additional replicas, to measure a candidate regime **before** the pre-registration is amended to adopt it | noise floor (`--baseline-fraction`, `--additional-replicas`, each falling back to the pre-registered value); probe (both stages) | `baseline_fraction=` / `additional_replicas=` keywords |
| 7 | "NOT the pre-registered traffic model" printed whenever the override is used | noise floor | **Preserved in the noise floor**, unchanged |
| 8 | The constants agree with the text of `docs/experiment-a2.md` (`baseline = **70%**`, `**0.25 additional replicas**`) — an amendment must touch the document | `test_the_traffic_constants_match_the_render_script_and_the_preregistration` | `tests/test_traffic.py`, extended to `D` and `R` |
| 9 | Ramp is half the sustain | `test_the_ramp_is_half_the_sustain_as_the_pre_registration_states` (via `render._preregistered_shape`) | Same test, via `spike_shape` |
| 10 | The render script evaluates H3 under both shapes: its source contains `kind="ramp"` and `h3_verdict(` | `test_the_render_script_evaluates_h3_under_both_shapes` | **Preserved.** Task 6 calls `spike_shape(..., kind="ramp")` by keyword so this source check keeps meaning what it says |
| 11 | `render.RAMP_SECONDS == 95.0` is asserted by a test | same test | Preserved: render imports `RAMP_SECONDS` from `autoscale.traffic` |

## Preserved in place — related, deliberately NOT consolidated

| Capability | Where | Why it stays |
|---|---|---|
| `PREREG_BASELINE_FRACTION = 0.40`, `PREREG_ADDITIONAL_REPLICAS = 3`, `PREREG_MAX_REPLICAS = 12` | `a2_regime_probe.py` | The ORIGINAL registration, kept as the origin of the disclosed search. Folding them into the current-rule constants would erase the record of what was amended. |
| `UNTIL = 400.0`, `SEED = 17`, `SWEPT_LAGS` | `a2_render_figures.py` | The render's simulation window and sensitivity sweep, not the traffic model. |
| `UNTIL = 200.0`, `REPETITIONS_UNDER_TEST` | `a2_end_to_end.py` | The test's reduced window, justified in its own comment. |
| Iso-cost budget `min(p.cost for p in points) * 2` | `a2_gap_noise_floor.py` | The **retired** budget rule. Kept because the script's docstring pins a documented historical result (0.314 s, 2026-09-17) computed with it; changing it would make that record irreproducible. Out of scope; flagged. |
| Inline iso-cost budget + gap in `_verify` | `a2_regime_probe.py` | A second copy of `iso_cost_budget`/`gap_at_iso_cost` without the FP-dust tolerance or the completeness guard. Out of scope for plan 2a — it is the budget, not the traffic model — and flagged for a follow-up. Its outputs are pinned by the Task 1 baseline, so a later fix will show its effect. |
| `peak = baseline + additional_replicas * saturation` as a **reported** value | `a2_regime_probe.py` | The probe reports `peak_rps` and `peak_over_saturation`. Recomputing them from the shape (`baseline × k`) can differ in the last bit and break byte parity for a label. The line stays as a report of the inputs, commented as such; it constructs no shape. |
| `SpikeShape(kind="step", baseline_rate=12.0, k=4.0, ramp=0.0, sustain=30.0)` fixtures in `_config()` (line 420) and the cross-process script (line 654) | `tests/test_frontier.py` | **Found by Task 1's Step 1 grep; not in the 2026-09-17 review.** These construct `SpikeShape` directly with arbitrary literal values to exercise `autoscale.sweep.run_sweep`/`SweepConfig` — not the pre-registered traffic model (`sustain=30.0` here vs. the pre-registered `190.0`; `k=4.0` here is a literal, not derived from any saturation measurement). No dependency on `BASELINE_FRACTION_OF_SATURATION`, `ADDITIONAL_REPLICAS_AT_PEAK`, `_saturation_rps`, or `_preregistered_shape`. Out of scope for consolidation: it is test fixture data for the sweep, not a copy of the derivation. |

## Intentionally dropped

| Capability | Why |
|---|---|
| `a2_render_figures._saturation_rps` and `._preregistered_shape` (private) | Replaced by `autoscale.traffic`. Delegating shims survive Tasks 6–10 so the end-to-end test keeps exercising the old entry points as a parity check; Task 11 deletes them once parity is proven. Private helpers of a script — no external caller. |
| The end-to-end test's local copy of the derivation and constants | The reason for the copy ("`scripts/` is not importable") no longer applies. The agreement it guarded becomes structural: there is one copy. |
| The `_preregistered_shape(curve, kind, ramp)` `ramp` argument | R = D/2 is derived, not passed. The Task 6 shim raises if a caller passes a ramp that disagrees, rather than silently ignoring it. |

No caller-observable capability is dropped: every script keeps its CLI, flags,
outputs and printed warnings.
