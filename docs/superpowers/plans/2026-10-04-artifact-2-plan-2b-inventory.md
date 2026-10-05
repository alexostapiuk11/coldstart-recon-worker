# Plan 2b — Inventory of what the placeholder curve drives, and the "before" baseline

Built by reading the code at HEAD `e3d756a` (suite: 1604 passed). Plan 2b puts
the measured service curve under three scripts and figure 4. Every capability
they have carries a keep/drop decision. A capability in neither column is a
planning bug. Nothing is dropped; two behaviours change on purpose.

## Consumers of the placeholder curve (grep, 2026-10-04)

`grep -rn "SERVICE_CURVE_PLACEHOLDER\|service_curve(\|censoring_onset\|UTILIZATION_CENSOR_AT" autoscale scripts tests recon harness` found what the plan expected, and nothing new:

- production: `scripts/a2_render_figures.py` (import line 34; uses at lines 72, 84, 139, 247, 254, 288), `scripts/a2_gap_noise_floor.py` (import 41; uses at 103, 114, 130), `scripts/a2_regime_probe.py` (import 61 `as CURVE`; `CURVE` used at lines 94, 100, 126, 176, 182, 194, 240);
- figure code: `autoscale/figures.py` (`UTILIZATION_CENSOR_AT` line 120, `censoring_onset` line 634, `service_curve` line 696);
- tests: `test_service.py`, `test_validation.py`, `test_a2_figures.py`, `test_sim.py`, `test_a2_end_to_end.py`, `test_frontier.py`, `test_traffic.py`. `test_sim_policy.py` and `test_signals.py` do not appear in this grep; they do not reference the placeholder by name. `test_a2_service_curve.py` matched only on `build_service_curve(`, which is the measured loader and unrelated.
- not in the grep, but coupled to the scripts: `tests/test_a2_gap_noise_floor.py` runs `a2_gap_noise_floor.py` in a subprocess, with no curve flag on the default run (see the coupling table).

## Capabilities

### From the plan's list (confirmed by reading the code)

| Capability | Where | Decision | How Task N preserves or why dropped |
|---|---|---|---|
| Render figures 1, 2, 4 against the placeholder for a layout draft | `a2_render_figures.main` | **Preserved** | Behind `--placeholder` (Task 6) |
| `WARNING: rendering against the PLACEHOLDER service curve` on stdout | `main` (condition `not SERVICE_CURVE_PLACEHOLDER.measured`) | **Preserved** | Under `--placeholder`. The condition becomes `not curve.measured`, so it can never print on a measured curve and can never be silent on an unmeasured one |
| `allow_unmeasured=True` passed to `run_sweep` | `_sweep` | **Preserved** only under `--placeholder` | The measured path passes `False` (Task 6), so the sweep's own `_require_measured_curve` guard is live on the default path |
| Sweep cache `sweep-cache.json` and `--refresh` | `main`, `_dump`, `_load` | **Preserved** | The cache records which curve it came from, and a cache from the other curve is refused (Task 6). Today the cache holds no curve tag at all (keys: `sources`, `swept`, `gaps`), so the existing `build/a2-figures-final/sweep-cache.json` is a placeholder cache with nothing in it saying so; Task 6 must treat an untagged cache as a placeholder one |
| Per-signal discard report | `_report_discards` | **Preserved** | Unchanged |
| H3 verdict printed under both shapes | `_run_everything` | **Preserved** | Unchanged; `h3_verdict(`, `kind="ramp"` and `iso_cost_budget`/`gap_interval` must stay in the render script's source (see coupling table) |
| `_by_signal` key order (set iteration, so hash-seed order; parity pins `PYTHONHASHSEED=0`) | `_by_signal` | **Changed on purpose** | An explicit `SIGNAL_ORDER` order (plan 2a open item) |
| Figure 4 from `curve.points` and `curve.measured`, censoring shading, note, banner | `figures.service_curve` | **Preserved** for a bare `ServiceCurve` | Byte-identical, checked in Task 6 Step 6 and Task 7 Step 4; intervals, idle point and excluded-level note are added only when a `MeasuredCurve` is passed |
| Figure 2 has no measured/modeled banner | `figures.frontiers` | **Changed on purpose** | Its note names which curve it ran on (Task 7; plan 2a open item) |
| `a2_gap_noise_floor.py` / `a2_regime_probe.py` on the placeholder | both `main` | **Preserved** | Behind `--placeholder`; default becomes the measured curve |
| `RAMP_SECONDS` re-export read by `tests/test_a2_end_to_end.py` | render module | **Preserved** | Keep the `from autoscale.traffic import RAMP_SECONDS  # noqa: F401` line |

### Rows the plan's list misses (found by reading the code)

| Capability | Where | Decision | How Task N preserves or why dropped |
|---|---|---|---|
| The two other scripts import `UNTIL` and `_by_signal` from the render module (`from a2_render_figures import UNTIL, _by_signal` in the noise floor, `UNTIL` in the probe) | noise floor line 36, probe line 54 | **Preserved** | Both names stay importable from `a2_render_figures`; importing it must have no side effect (no argparse, no curve load at module top that can raise). The curve is loaded inside `main`, not at import (Task 6) |
| `_by_signal` is also the source of the per-signal frontier dict passed to figures and to `gap_interval` | render `_run_everything`, `main`; noise floor `main` | **Preserved**, order changed | Same as the `_by_signal` row above; callers read it as a dict, so only iteration order changes |
| Module constants `SEED = 17`, `UNTIL = 400.0`, `SWEPT_LAGS = (20, 40, 60, 80, 120)`, `GAP_BOOTSTRAP_ITERATIONS = 2000` | render | **Preserved** | Unchanged; swapping the curve must not move a pre-registered constant |
| `--store` (default `data/campaign.jsonl`) and `--out` (default `build/a2-figures-draft`) | render, noise floor, probe | **Preserved** | The measured default must not change the lag store |
| `sys.stdout.reconfigure(line_buffering=True)` at the top of each `main` | all three `main`s | **Preserved** | A 25-minute sweep redirected to a file must still show progress |
| Figure 4 renders FIRST and needs no sweep, so it survives a later figure guard refusing | render `main` | **Preserved** | Order kept; on the measured path figure 4 is drawn from the `MeasuredCurve` before the sweep starts |
| Output file names `service_curve.png`, `frontiers.png`, `convergence.png` | render `main` | **Preserved** | The script writes no phone variants; the `*-phone.png` files in `build/a2-figures-final/` are from an earlier render and nothing in the current script produces them |
| `_first_complete`: figure 2 uses the first sweep source with all three signals, and `context=` prints its label ON the figure | render `main` | **Preserved** | Unchanged except Task 7 adds the curve name to the note. With a sensitivity signal in the sweep, "all three" must keep meaning the three `SIGNAL_ORDER` signals, not "every signal present" |
| The modeled-lag panel degrades to a bare gap with `NO INTERVAL` when the paired bootstrap lacks repetitions; `figures.convergence` draws it without a band and says so | render `_run_everything` `except ValueError` | **Preserved** | Unchanged. The four measured gaps (`arm A/C`, `ramp arm A/C`) still raise rather than publish without an interval |
| `blocked` list and `SystemExit` with the explanation of why a figure refused to draw | render `main` | **Preserved**, text goes stale | The explanation cites the 2026-09-17 amended traffic model by name. Task 6 should not edit it blind; Task 5's amendment changes which traffic model is in force, so the text is revisited there, not silently kept |
| `curve_measured=<curve>.measured` passed to `convergence` | render `main` line 288 | **Preserved** | Becomes the loaded curve's flag, so figure 1's banner reads MEASURED only on a measured curve |
| `spike_shape(curve, kind=...)` is called with NO `baseline_fraction`/`additional_replicas`/`sustain` keywords | render lines 84, 139 | **Preserved** | Pinned by `tests/test_traffic.py` (`NON_PREREGISTERED_KEYWORDS`, scans `a2_render_figures.py`). The absolute-rate amendment (Task 4/5) must come in through `autoscale.traffic`, not as keywords in the script |
| No second copy of the saturation derivation in scripts: `test_nothing_derives_saturation_outside_its_one_home` AST-scans `scripts/`, `tests/`, `autoscale/` for a `max(...)` over `latency_at` and for code in string literals | `tests/test_traffic.py` | **Preserved** | `measured_curve.py` and the new scripts must call `saturation_rps`, never inline it |
| Source assertions on the render script: contains `h3_verdict(`, `kind="ramp"`, `iso_cost_budget` or `gap_interval`, and NOT `min(p.cost for p in points) * 2` | `tests/test_a2_end_to_end.py::test_the_render_script_evaluates_h3_under_both_shapes` | **Preserved** | Any rewrite of `_run_everything` keeps those tokens |
| Noise floor: `--seeds` (10), `--reps` (30), `--arm` (A), `--out` (`build/a2-gap-noise-floor.json`), `--baseline-fraction`, `--additional-replicas` | noise floor `main` | **Preserved** | Only `--curve` / `--placeholder` is added |
| Noise floor mutates `sweep_mod.REPETITIONS` and prints `NOTE: repetitions lowered ...` | noise floor `main` | **Preserved** | Unchanged |
| Noise floor prints `NOT the pre-registered traffic model` exactly once under either override flag and never on a default run | noise floor `main`; `tests/test_a2_gap_noise_floor.py` | **Preserved** | The text and the once-only count are unchanged. That test runs the script with no curve flag, so after Task 6 it exercises the MEASURED curve; it must still finish inside its 120 s timeout at 1 seed, 1 repetition, and its default-run assertion must still pass |
| Noise floor's arm line ends with a hard-coded `-- PLACEHOLDER service curve` | noise floor line 120 | **Changed on purpose** | Becomes the curve's own label (placeholder or measured). Leaving it would print "PLACEHOLDER" on a measured run, the exact opposite of what the line is for |
| Noise floor's iso-cost budget is `min(p.cost for p in points) * 2`, not the pre-registered `iso_cost_budget` | noise floor line 138 | **Preserved** (diagnostic rule) | Out of scope for plan 2b; the source assertion above scans only the render script. Noted so nobody reads the noise floor's gap as the published gap |
| Noise floor's `_p99_at` returns None rather than raising; per-seed rows; summary `n`/`mean`/`min`/`max`/`stdev`/`sem`; JSON `{rows, summary}` | noise floor | **Preserved** | Unchanged |
| Noise floor hard-codes `allow_unmeasured=True` in `run_sweep` | noise floor line 135 | **Preserved** only under `--placeholder` | Same rule as the render script's `_sweep` |
| Regime probe `_probe` calls `run_with_policy` DIRECTLY, so it never goes through `run_sweep`'s `_require_measured_curve` guard | probe `_probe` | **Preserved**, flagged | The guard is not live there today and stays out of scope; the probe's header must say which curve it ran on so a placeholder run cannot pass for a measured one |
| Regime probe `_verify` hard-codes `allow_unmeasured=True` | probe line 196 | **Preserved** only under `--placeholder` | Same rule |
| Regime probe prints `PLACEHOLDER service curve. One fixed arrival trace per configuration.` unconditionally | probe `main` | **Changed on purpose** | Names the curve in use (as for the noise floor) |
| Regime probe iterates `sorted(SIGNALS)` and `THRESHOLDS[signal]` | probe `_probe`, `_verify`, `main` | **Preserved** | Task 3 keeps `SIGNALS` as the three headline signals, so the probe does not silently gain a fourth signal; the sensitivity signal lives in `ALL_SIGNALS` |
| Regime probe prose `out of 19/17/19 possible` is hard-coded | probe `main` | **Preserved**, may go stale | Counts depend on the threshold grids, which Task 3 does not change for the headline signals |
| Regime probe's `PREREG_*` origin constants, `VERIFY_SEEDS`, the screen grid and the stage-2 candidate list; `--stage`, `--verify-reps`; JSON `{screen, verify}` | probe | **Preserved** | Unchanged. Note the candidate list was chosen against the placeholder's saturation; on the measured curve it is the same list in fractions of the measured saturation |
| Frontier figure's `UTILIZATION_CENSOR_AT = max(THRESHOLDS["utilization"][0])` (0.95), read off the grid in a subprocess-checked import | `figures.py` line 120; `test_a2_figures.py` lines 686-700 | **Preserved** | Task 3 adds a sensitivity grid equal to utilisation's without touching `THRESHOLDS["utilization"]` |
| `censoring_onset` REFUSES a curve that reaches the threshold and then falls back below it (`ValueError`), and `service_curve` raises through it | `figures.py` 634-672 | **Preserved** | Task 7 must run it on the measured points; if a real measured curve dips, that is a finding, not a reason to loosen the check. Whether the idle point (0 load, 0% GPU) enters `points` or sits beside them decides whether the first-point branch (`points[0][1] >= threshold`) still means what it says |
| Figure 4's note counts `n={len(curve.points)} concurrency levels` | `figures.service_curve` | **Preserved**, may be wrong | If `MeasuredCurve.points` includes the idle point at concurrency 0, the count over-reports levels by one. Task 7 must state N as measured levels, not as `len(points)` |
| Figure 4's x axis is `0 .. 1.04 × max(concurrency)` with the shading running to the same edge | `figures.service_curve` | **Preserved** | Unchanged for the placeholder (max 64); the measured curve reaches 128 |
| `ServiceCurve` is frozen, validates every field (finite, ascending, utilisation in [0, 1]) and requires at least two points; `utilization_at` clamps at 1.0 | `autoscale/service.py` | **Preserved** | `MeasuredCurve` builds a `ServiceCurve`, so it inherits these checks |

## Coupling to watch (tests that constrain how Tasks 6 and 7 may change the scripts)

| Test | What it pins | Consequence |
|---|---|---|
| `tests/test_a2_end_to_end.py::test_the_render_script_evaluates_h3_under_both_shapes` | `render.RAMP_SECONDS == 95.0`; source tokens listed above | Keep the import and the tokens |
| `tests/test_traffic.py::test_nothing_derives_saturation_outside_its_one_home` and the render-keyword guard | no local saturation derivation; no `baseline_fraction`/`additional_replicas`/`sustain` in the render | New code uses `saturation_rps` and `spike_shape` only |
| `tests/test_a2_gap_noise_floor.py` (two tests, subprocess, no curve flag) | the override warning appears once; a default run does not print it | Runs on the measured curve after Task 6; must stay under 120 s and pass |
| `tests/test_a2_figures.py` (placeholder and `WIDE_CURVE` parametrised) | figure 4 geometry, onset, banner, note | Byte-identical for a bare `ServiceCurve` (Task 6 Step 6, Task 7 Step 4) |
| `tests/test_frontier.py` | `run_sweep` refuses an unmeasured curve unless `allow_unmeasured=True` | The default measured path passes `False` |

## Baseline (captured before any change; `build/a2-plan2b-baseline/`, gitignored)

Command: Task 1 Step 3, `PYTHONHASHSEED=0`, HEAD `e3d756a`. Printed:

```
{
 "placeholder_saturation_rps": 33.68421052631579,
 "placeholder_step": {
  "baseline_rate": 23.57894736842105,
  "k": 1.3571428571428572,
  "kind": "step",
  "ramp": 0.0,
  "sustain": 190.0
 },
 "service_curve_placeholder_sha256": "ab5da039210685a105cb88a23376daf3b7abea816e8dc40198218f3765ef27bb"
}
```

- **The plan's expected saturation is wrong.** Step 3 says `≈ 30.48` req/s ("the placeholder's `64/2.10`"). `saturation_rps` is the MAX of `c / latency_at(c)` over the points, not the value at the last point: 32/0.95 = 33.684 beats 64/2.10 = 30.476 and 16/0.52 = 30.769. `tests/test_traffic.py` asserts exactly this (`== 32/0.95`, and `> 64/2.10`). The captured 33.684 is correct; 30.48 is the number the max replaces. Baseline 23.579 rps is 0.70 × 33.684, and the peak is baseline × k = 32.0 rps (0.95 × saturation, i.e. 0.70 plus 0.25 additional replicas), the amended traffic model.
- Files in `build/a2-plan2b-baseline/`: `service_curve_placeholder.png`, `facts.json`, `a2_render_figures.help.txt`, `a2_gap_noise_floor.help.txt`, `a2_regime_probe.help.txt`, `placeholder-sweep-cache.json`.
- `--help` options before the change: render `--store --out --refresh`; noise floor `--seeds --reps --arm --store --out --baseline-fraction --additional-replicas`; probe `--store --arm --out --stage {screen,verify,both} --verify-reps`. None has `--curve` or `--placeholder` yet.
- Placeholder sweep cache: copied from `build/a2-figures-final/sweep-cache.json` (857,637 bytes, sha256 `ffd4f9e0003e628fd5fcda3f0bc32eaed0c49616ddb11216ab7260fbd2299f28`). Keys `sources`, `swept`, `gaps`; sources `arm A`, `arm C`, `modeled lag 20s/40s/60s/80s/120s`, `ramp arm A`, `ramp arm C`, 55 policy points each; no curve tag. The directory also holds `frontiers.png`, `convergence.png` and `*-phone.png` from 2026-09-17.

## Parity audit (Task 14, 2026-10-04)

Every row of the two tables above, exercised through the code as it now is. Each line says
what was run and what it printed, or which test pins the row; "RUN" means the command was
executed in this audit, "TEST" means a named test pins it (and was run: see the last block).
Outputs are in `build/a2-plan2b-audit/` (gitignored). Nothing here is a result: every figure
and number below is a plumbing check on the placeholder curve at a reduced scale.

**How the render script's `--placeholder` path was exercised, and what was not.** The
published sweep is 30 repetitions per policy, about 25 minutes, and a long measured-curve run of
the same script is going in the background (`build/a2-figures-measured/`, not touched here). So the
script was driven the way `tests/test_a2_end_to_end.py` drives the sweep: `sweep.REPETITIONS` 30 -> 1,
by a small driver that then calls `a2_render_figures.main([...])` with `--out build/a2-plan2b-audit/render`.
One deviation from the end-to-end tests, forced by going through `main()`: its four measured gaps
(`arm A`, `arm C`, `ramp arm A`, `ramp arm C`) refuse, correctly, below the bootstrap floor of 20
surviving repetitions (that refusal is itself an inventory row, shown below). So the driver
also sets `autoscale.stats.MIN_BOOTSTRAP_SAMPLES = 1`, and the intervals it prints (`[0.9391, 0.9391]`
over 1 paired repetition) are degenerate. The window (400 s), the grids and the seed were NOT reduced.
A 20-repetition run (about 10 minutes) was also tried and still refused at the ramp arm's gap
("1 of 11 frontier points have fewer than 20 surviving repetitions (fewest: 18)"), because the
pre-registered exclusions leave a point under 20: the guard held, as it should.
Not exercised end to end: the full 30-repetition sweep and its figure content (the background run).

### Render script, from the plan's list

| Row | How | Output |
|---|---|---|
| Render figures 1, 2, 4 on the placeholder | RUN: driver `... --placeholder --out build/a2-plan2b-audit/render --refresh`, exit 0 | `build/a2-plan2b-audit/render/service_curve.png`, `.../frontiers.png`, `.../convergence.png` (all three printed, in that order); directory holds those plus `sweep-cache.json` |
| WARNING on stdout under `--placeholder` | RUN, same | `WARNING: rendering against the PLACEHOLDER service curve. These figures are a layout draft, not a result.` The measured default instead prints `service curve: data/a2/service-curve.json (measured; idle point added)` (RUN, the cache-refusal commands below) |
| `allow_unmeasured` opt-in only on the placeholder | TEST: `tests/test_a2_render_curve_switch.py::test_the_sweep_is_unmeasured_only_on_the_placeholder`; `tests/test_frontier.py::test_an_unmeasured_service_curve_is_refused` and `::test_an_unmeasured_curve_runs_only_on_a_deliberate_opt_in`; `tests/test_a2_end_to_end.py::test_the_sweep_refuses_the_placeholder_curve_without_the_opt_in` | passed (last block) |
| Sweep cache and `--refresh` | RUN: first run `--refresh` wrote the cache; second run without it | `cached the sweep to build/a2-plan2b-audit/render/sweep-cache.json`, then `reusing the cached sweep at build/a2-plan2b-audit/render/sweep-cache.json (--refresh to re-run it)` and the same three figures |
| A cache from the other curve is refused | RUN: the placeholder-tagged cache that run just wrote, copied to a fresh out dir, then rendered on the measured default | `the sweep cache came from curve 'placeholder' but this run is on 'data/a2/service-curve.json'; drawing it would put one curve's frontiers under the other's banner. Use --refresh or another --out` |
| ...and the reverse, and an untagged cache | RUN: a measured-tagged cache under `--placeholder`; an untagged one under `--placeholder`; the real pre-plan-2b cache (`build/a2-plan2b-baseline/placeholder-sweep-cache.json`, no `curve` key) under `--placeholder` | `the sweep cache came from curve 'data/a2/service-curve.json' but this run is on 'placeholder'; ...` and, for both untagged ones, `the sweep cache does not say which service curve it came from (it predates plan 2b); re-run with --refresh rather than draw it under a guessed label` |
| Per-signal discard report | RUN, same driver run | e.g. `arm A: 3 discards (queue_depth/no_scaling_action=1, queue_depth/replica_never_served=2)`, one such line for every source, and for the four sensitivity sources `sensitivity arm A: 0 discards` |
| H3 verdict under both shapes | RUN, same | `step spike: baseline=23.6 rps, k=1.4 (peak 32.0 rps), sustain=190s` ... `ramp spike: baseline=23.6 rps, k=1.4, ramp=95s, sustain=190s`; the four gaps `arm A`, `arm C`, `ramp arm A`, `ramp arm C`; then `H3: holds=False partial=False evaluable=True` / `gap did not halve under either shape` (a plumbing value, not a result) |
| `RAMP_SECONDS` importable | RUN, first line of the driver's output | `RAMP_SECONDS importable: 95.0`; also `tests/test_a2_end_to_end.py::test_the_render_script_evaluates_h3_under_both_shapes` |
| `_by_signal` order is explicit, not hash order | RUN: `_by_signal` over the written cache's `arm A`, under `PYTHONHASHSEED` 0, 1 and 2 | `['queue_depth', 'in_flight_concurrency', 'utilization']` all three times (the `SIGNAL_ORDER` order); TEST: `test_by_signal_orders_keys_by_signal_order_then_name` |
| Figure 4 for a bare `ServiceCurve` is byte-identical | RUN: the Task 6 Step 6 snippet, `service_curve(SERVICE_CURVE_PLACEHOLDER, ...)` against the baseline hash `ab5da039...` | `PLACEHOLDER FIGURE 4 PARITY OK` |
| Figure 2 names its curve | TEST: `tests/test_a2_figures.py::test_figure_2_names_its_curve_only_when_told` and `::test_figure_2_note_stays_on_canvas_with_its_curve_label` | passed |
| `a2_gap_noise_floor.py` / `a2_regime_probe.py` on the placeholder | RUN: the two commands below | see "Diagnostic scripts" |
| `RAMP_SECONDS` re-export | covered above | |

### Render script, rows the plan's list missed

| Row | How | Output |
|---|---|---|
| The other scripts import `UNTIL` and `_by_signal` from the render module; importing has no side effect | RUN: `import a2_render_figures, a2_gap_noise_floor, a2_regime_probe` | `noise floor imports UNTIL/_by_signal from render: True True`, `probe UNTIL: 400.0`; no output, no curve load at import |
| `_by_signal` feeds the per-signal dict to figures and `gap_interval` | RUN: the driver run's four gap lines | `arm A: gap=0.9391s [0.9391, 0.9391] at budget 985.0 replica-seconds (1 paired repetitions; per-signal {'in_flight_concurrency': 1, 'queue_depth': 1, 'utilization': 1})` |
| `SEED`, `UNTIL`, `SWEPT_LAGS`, `GAP_BOOTSTRAP_ITERATIONS` | RUN: print | `SEED 17 UNTIL 400.0 SWEPT_LAGS (20.0, 40.0, 60.0, 80.0, 120.0) GAP_BOOTSTRAP_ITERATIONS 2000` |
| `--store` and `--out` defaults | RUN: both flags passed explicitly in every run above; defaults pinned by `a2_render_figures.help.txt` in the baseline (`--store --out --refresh`, now plus `--curve`/`--placeholder`) | `--out build/a2-plan2b-audit/render` honoured; `--store` default `data/campaign.jsonl` used by every run |
| `sys.stdout.reconfigure(line_buffering=True)` in each `main` | RUN: grep | `scripts/a2_render_figures.py:322`, `scripts/a2_regime_probe.py:251`, `scripts/a2_gap_noise_floor.py:90` |
| Figure 4 renders first and survives a later refusal | RUN: in every cache-refusal run above `service_curve.png` is printed before the cache line and before the refusal; the strict-floor run below drew it before the sweep raised | `build/a2-plan2b-audit/cache-refusal-measured/service_curve.png` printed, then the refusal |
| Output file names `service_curve.png`, `frontiers.png`, `convergence.png`; no phone variants | RUN: `ls build/a2-plan2b-audit/render` | `convergence.png frontiers.png service_curve.png sweep-cache.json` |
| `_first_complete` uses a sweep with all three `SIGNAL_ORDER` signals | RUN: on the written cache, whose sources now include four `sensitivity ...` ones | `first_complete: arm A` (the sensitivity sources hold only `utilization_throughput`, so they cannot be taken for complete) |
| Modeled-lag panel degrades to a bare gap with `NO INTERVAL`; the four measured gaps still raise | RUN: driver with only `REPETITIONS = 1` (floor intact), `--refresh` | `modeled lag 20s: gap=0.8649s at budget 615.0 -- NO INTERVAL (11 of 11 frontier points have fewer than 20 surviving repetitions (fewest: 1))` (and 40/60/80/120 s likewise), then `ValueError: 12 of 12 frontier points have fewer than 20 surviving repetitions (fewest: 1); below that floor ...` from the `arm A` gap |
| `blocked` list and `SystemExit` with the explanation | RUN: the written cache with every `utilization` point removed, rendered `--placeholder` | `frontier figure: no sweep produced a frontier for all three signals. arm A has ['in_flight_concurrency', 'queue_depth']; ...` / `convergence figure: no frontier for signal(s) ['utilization'] on either arm; ...` / `These are the figures' own guards refusing to draw a chart that would read as a comparison it is not.` The text was rewritten in Task 6 (it no longer blames the pre-registered traffic model); see below |
| `curve_measured=<curve>.measured` reaches the banners | TEST: `tests/test_a2_figures.py::test_the_measured_banner_requires_a_measured_service_curve`, `::test_the_measured_banner_is_restored_by_a_measured_curve`, `::test_curve_measured_must_be_stated` | passed |
| `spike_shape` called without non-pre-registered keywords | TEST: `tests/test_traffic.py::test_the_render_draws_the_preregistered_spike_not_a_candidate` | passed |
| No second saturation derivation in `scripts/`, `tests/`, `autoscale/` | TEST: `tests/test_traffic.py::test_nothing_derives_saturation_outside_its_one_home` | passed |
| Source tokens in the render script (`h3_verdict(`, `kind="ramp"`, `iso_cost_budget`/`gap_interval`, no `min(p.cost ...) * 2`) | TEST: `tests/test_a2_end_to_end.py::test_the_render_script_evaluates_h3_under_both_shapes` | passed |
| `ServiceCurve` frozen, validated, at least two points; `utilization_at` clamps at 1.0 | RUN: construct and probe the placeholder | `clamp utilization_at(10**6): 1.0`; `one point -> ValueError a service curve needs at least two points to interpolate`; `frozen -> FrozenInstanceError` |
| `UTILIZATION_CENSOR_AT` follows the grid; the grid is untouched, the sensitivity signal is outside `SIGNALS` | RUN: print | `UTILIZATION_CENSOR_AT 0.95 THRESHOLDS[utilization] ((0.5, 0.65, 0.8, 0.9, 0.95), (0.05, 0.15, 0.3, 0.5))`; `SIGNALS ['in_flight_concurrency', 'queue_depth', 'utilization']`, `ALL_SIGNALS [... 'utilization_throughput']` |
| `censoring_onset` refuses a dip; first-point branch; no censoring when never reached | TEST: `tests/test_a2_figures.py::test_a_utilization_dip_after_the_onset_is_refused`, `::test_censoring_starts_at_the_first_level_when_utilization_is_already_over`, `::test_no_censoring_when_utilization_never_reaches_the_threshold`, `::test_utilization_reaching_the_threshold_exactly_at_the_last_level_starts_censoring_there` | passed |
| Figure 4: N is measured levels, axis starts at zero and runs to `1.04 x max`, shading reaches the edge | TEST: `::test_n_is_stated_on_the_service_curve`, `::test_measured_figure_4_states_runs_levels_and_the_unservable_level`, `::test_every_service_curve_axis_starts_at_zero`, `::test_the_censored_band_reaches_the_right_edge` | passed |

The cache-refusal commands, as run (`$A` is `build/a2-plan2b-audit`):

```
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a2_render_figures.py --placeholder --out $A/cache-refusal-measured    # cache tagged data/a2/service-curve.json
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a2_render_figures.py --placeholder --out $A/cache-refusal-untagged
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a2_render_figures.py --placeholder --out $A/cache-refusal-real-old   # the pre-plan-2b cache
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a2_render_figures.py --out $A/render-measured-on-placeholder-cache    # measured default, placeholder cache
```

### Diagnostic scripts

| Row | Command | Output |
|---|---|---|
| Noise floor on the placeholder; `--seeds`, `--reps`, `--arm`, `--out`; `NOTE: repetitions lowered` | RUN: `.venv/bin/python scripts/a2_gap_noise_floor.py --placeholder --seeds 1 --reps 1 --out build/a2-plan2b-audit/noise-floor.json` | `NOTE: repetitions lowered to 1 from the pre-registered 30` / `arm A: 1 master seeds x 1 reps, baseline=23.6 rps k=1.4 -- PLACEHOLDER service curve` / `seed=1000 gap=2.7617174783473697 per_signal={'queue_depth': 3.9633, 'in_flight_concurrency': 1.6688, 'utilization': 1.2016}` / `SUMMARY { "n": 1 }` / `wrote build/a2-plan2b-audit/noise-floor.json`; JSON keys `['rows', 'summary']` |
| The arm line names the curve (was hard-coded `PLACEHOLDER`) | the line above on `--placeholder`; RUN: `.venv/bin/python scripts/a2_gap_noise_floor.py --seeds 1 --reps 1 --out build/a2-plan2b-audit/noise-floor-measured.json` (no curve flag, so the measured default; source `scripts/a2_gap_noise_floor.py:133`) | `arm A: 1 master seeds x 1 reps, baseline=147.8 rps k=1.4 -- measured service curve` (baseline 147.8 req/s is the amendment's; `gap=None` at 1 repetition is plumbing, not a result) |
| `NOT the pre-registered traffic model` once under an override flag, never on a default run | RUN: the same command with `--baseline-fraction 0.4`, piped to `grep -c`; and without it; TEST `tests/test_a2_gap_noise_floor.py` (3 tests, subprocess) | count `1` with the override (`NOT the pre-registered traffic model: baseline=40% of saturation, 0.25 additional replicas at peak (peak/saturation=0.65)`), count `0` without |
| Regime probe on the placeholder; screen stage; `{screen, verify}` JSON; `PLACEHOLDER service curve.` header; `sorted(SIGNALS)` | RUN: `.venv/bin/python scripts/a2_regime_probe.py --placeholder --stage screen --out build/a2-plan2b-audit/regime-probe.json` | `arm A: saturation/replica=33.7 rps, sustain=190s` / `PLACEHOLDER service curve. One fixed arrival trace per configuration.` / 40 screen rows / `26/40 configurations separate the policies on p99 at all.` / `wrote build/a2-plan2b-audit/regime-probe.json`; JSON keys `['screen', 'verify']`, 40 screen rows |
| Probe's `kept`, `PREREG_*` origin, grid | same run | the `0.10 ... 0.70` base fractions x `0.25 ... 3` additional replicas x cap 12/24 grid, unchanged |
| Noise floor `--arm`, `--store`, `_p99_at`, per-seed rows | RUN above (per-seed row, `p99` per signal) | as above |
| Probe's `_verify`, `--verify-reps`, noise floor's `min(cost) * 2` budget | not run (stage `verify` is long); unchanged code, not touched by plan 2b beyond `allow_unmeasured=not CURVE.measured` | see `tests/test_a2_render_curve_switch.py` for the flags; `--help` listings in the baseline |

### The two behaviours that change on purpose, and the one text that was rewritten

- `_by_signal` order is now `SIGNAL_ORDER`: shown above under three hash seeds.
- Figure 2's note names the curve (TEST above), and the noise floor and the probe name their curve rather than a hard-coded "PLACEHOLDER".
- The `blocked` explanation text: the inventory said it must not be edited blind. It was
  rewritten in Task 6 together with the amendment (the rewritten text appears in the output above:
  "Under the traffic model in force (the measured service curve and the 2026-10-04 amendment in
  docs/experiment-a2.md) ..."). The old claim, LIFO scale-down under the pre-registered traffic model, is
  quoted in the new text as no longer the regime being swept.

### Defects found by the audit

None in the rows above. Two things the audit exposed that are not parity rows:
- A driver that lowers only `REPETITIONS` cannot go through `main()`: the four measured gaps refuse
  below 20 surviving repetitions even at 20 repetitions, because the exclusions thin some frontier
  points. This is the intended refusal (the inventory row says so), not a defect, but anyone smoke-testing
  `main()` needs the floor lowered as well, or the full 30.
- `scripts/a2_lb_probe.py` does not raise or check the open-files limit as `scripts/a2_validate.py`
  does; the runbook tells the owner to `ulimit -n 8192` before the probe. A code fix is Task 11's, not this task's.

### Verification block (this audit)

Targeted tests that pin the TEST rows, run in this audit:

```
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" -q tests/test_a2_render_curve_switch.py tests/test_a2_gap_noise_floor.py \
  "tests/test_a2_end_to_end.py::test_the_render_script_evaluates_h3_under_both_shapes" "tests/test_traffic.py::test_nothing_derives_saturation_outside_its_one_home"
12 passed in 72.66s (0:01:12)
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" -q tests/test_traffic.py::test_the_render_draws_the_preregistered_spike_not_a_candidate tests/test_frontier.py tests/test_a2_figures.py tests/test_signals.py tests/test_sim_policy.py
278 passed in 27.54s
```

Full suite: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -o addopts=""`: `2170 passed, 1 warning in 172.98s (0:02:52)` (more than the 1604 before plan 2b; other sessions also add tests).
`.venv/bin/ruff check .`: `All checks passed!`. `./scripts/parity_check.sh`: `PARITY OK`.
Placeholder figure 4: `PLACEHOLDER FIGURE 4 PARITY OK`.
