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
