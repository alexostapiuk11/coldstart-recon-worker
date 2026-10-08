# Artifact 4: definition-of-done check

**Checked:** 2026-10-07, at `d7cf0c3`, for plan 3 Task 28 Step 3. The items are
amendment §12's deltas (`docs/superpowers/specs/2026-09-26-multi-model-serving-economics-scope.md`)
and every item of August §13 that they leave standing. Each met item names the
file or commit that meets it. An item marked **UNMET** or **OWNER** stops
publication until the owner acts or decides.

Test and lint state when checked: the full suite passes and `ruff check .` is clean.
`scripts/a4_parity_check.sh` was not re-run in this check (it needs the sweep cache
under `build/a4-sweep`); the post's verbatim-number and published-figure tests are
part of the suite and pass.

## Amendment §12 deltas

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | Gates in §2 met for each kind of work | met | GPU-free work, figures and measurement each landed after their gates: plan 1 (`0e61ef4`, `d16618a`, 2026-10-04), figures (`429fa1d`), measurement from 2026-10-05 |
| 2 | **The post is published after artifact 2's post** | **OWNER, not yet** | `python scripts/a2_prepublish_check.py` still refuses artifact 2's post: `PUBLICATION-DATE` is in it |
| 3 | `docs/experiment-a4.md` committed in two dated steps | met | Step 1 `c356e4b` (2026-10-04 17:54), before reconnaissance `c60602d` (2026-10-05 01:57). Step 2 rules `39e88f9` (2026-10-04 19:50), before the recon answers were read. Step 2 values `b17c8ac` (2026-10-05 02:36), before the cell campaigns. Later changes are dated amendments, each committed before the data it governs (`8e8b3ac`, `b8b74ac`, `4778350`, top-ups `df31bc1`, `71921be`). The ranking-blind screen's data (`d16ff5e`, 02:23) is committed before the values it informed, as step 1 specifies |
| 4 | Model set and revisions recorded, go/no-go outcome, and the fallback's | met | `docs/recon-a4.md` §2: primary pair failed, fallback pair passed at 55,104 and 64,976 tokens; revision `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e` in every swap record's `spec.revision` and in `data/a4/cost_per_tenant.json` (`model`) |
| 5 | For every swap: teardown timed to memory release, `S4b`, page-cache state, target pair | met | All 16 swap records in `data/a4/swaps.jsonl` carry `teardown_s`, `release.seconds`, `s4b_s`, `cold` and `cache`, and the `condition` string names source and target (checked by script on 2026-10-07) |
| 6 | No `placement/` function name collides with `harness.stats`, `harness.figure_guards` or `autoscale.stats` | met | `tests/test_placement_no_reimplementation.py` (`05d17c0`), passing |
| 7 | Transitive import-boundary test passes | met | `tests/test_placement_boundary.py` (`0c26826`), passing |
| 8 | This artifact's own spend recorded | met, **OWNER to confirm** | `docs/spend-a4.md`: $25.2311, 248 jobs, 22.77 hours billed, read from the billing API (`9251b05`). The file says the owner confirms the total against the RunPod console |

## August §13 items that stand

| Item | Status | Evidence |
|---|---|---|
| Learning-guide modules (§12b) worked through before the build stage | **UNMET / OWNER** | `docs/learning/plan.md` and `progress.md` hold modules for artifacts 1, 2 and 5 and none for artifact 4. Artifacts 2 and 5 moved their modules to before publication; the same decision is open here |
| Budget decision made explicitly, with the option recorded | **UNMET / OWNER (record)** | Amendment §9 says the funding decision "still cannot be made" (2026-09-26). The spend was authorised in conversation and the account was topped up, but no file records the option chosen. `docs/spend-a4.md` states the spend, not the decision |
| Reconnaissance completed: mechanism, split, go/no-go | met | `docs/recon-a4.md`, `docs/runbook-a4-recon.md` |
| Model set fits all three strategies on one 24 GB card | met for the fallback | `docs/recon-a4.md` §2 (the primary did not fit; the post says so) |
| Pre-registration extended, committed before the first sweep | met | item 3 above |
| Swap latency distribution measured, mechanism stated | met | `data/a4/swaps.jsonl` (16 swaps, median 37.8 s), stage table in the post, `data/a4/analysis.json` `inputs.stages` |
| Co-location interference curve measured across the load split | met, with a gap | 28 cells, neighbour levels 0, 16, 32, 64 (`data/a4/analysis.json` `inputs.surface`). Neighbour concurrency 1 to 15 was not measured; the simulator interpolates it linearly (`placement/colocated.py`). `docs/findings-a4-interference-sensitivity.md` shows the fleet does not depend on that range at this SLO, and the post says so |
| KV capacity under split measured | met | 55,104 tokens split, 168,464 solo (`inputs.kv`); the split value is a pinned budget (amendment 2026-10-05) |
| Simulator exercised end to end against synthetic inputs with no GPU | met | `placement/placeholders.py`, `scripts/a4_sweep.py` (`0e61ef4`, `d16618a`) |
| Replay validation run; tolerance band established; simulator inside it or the miss reported | met (the miss is reported) | `data/a4/replay.jsonl`, `validation` in `data/a4/analysis.json`: failed, 10 of 13 bins; `docs/findings-a4-validation-swap-cost.md` |
| Skew sweep completed at both locality regimes | met | `analysis.json` `regimes`; bursty s = 0.6 is "not evaluable" by the registered rule |
| Crossover boundary identified and stated as a decision rule | met | spread: colocate, s = 0.6–2.0; bursty: swap, s = 0.8–2.0; the estimator reports no crossover along the skew axis in either regime |
| Four figures rendered and visually inspected, validated point marked | met on the machine checks; **OWNER to look** | `docs/figures/a4/` (four, plus phone copies), byte-compared to the render by `tests/test_a4_published_figures.py`; layout defects fixed in `8cb096b` with geometry tests; the validated point is drawn in the bursty column of the crossover figure (`placement/figures.py`). Nothing replaces the owner's own look at the final PNGs |
| All four required explanations present, plus the adapter exclusion | met in text, see the review | `tests/test_a4_post.py` holds the key phrases. The interference and KV explanations were tightened in the 2026-10-07 post review |
| Post published at a permanent slug, linking the shared repo | **OWNER, not yet** | slug `/experiments/multi-model-placement` is in the post; publication waits on artifact 2 |
| Headline in systems units and money, with all conversion assumptions published | met (post edit, 2026-10-07) | The lead now states the rate's source, that every GPU runs all month (730 hours), and that per million tokens counts output tokens only (256 per request) at the offered load |
| Pre-publish boundary gate completed | **OWNER, not yet** | Artifacts 1 and 2's gate has no artifact 4 counterpart. `scripts/a2_prepublish_check.py` is hard-wired to `docs/post-a2.md`, so for this post the owner runs the boundary check by hand or a4's equivalent is written first |

## What stops publication

1. Artifact 2's post is not published.
2. No learning-guide record and no recorded budget decision for artifact 4.
3. The owner's own confirmations: spend against the console, a look at the final
   figures, `PUBLICATION-DATE`, and the boundary gate.
