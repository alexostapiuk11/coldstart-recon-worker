# Budget decision record: artifacts 4 and 5

**Dated 2026-11-20. Recorded retrospectively.** Artifacts 4 and 5 had already been
run (their spend was incurred 2026-10-05 to 2026-10-07) when this was written. This
file was not written in advance, and it does not show the decision was documented
before the money was spent. It records the owner's answer, given on 2026-11-20 when
asked what the record should state.

## The decision

> Authorised under the $200 portfolio cap, with the spec's cut order applied as
> needed. No separate envelope for artifacts 4 and 5; they draw on the original $200
> total.

Background: `docs/superpowers/specs/2026-09-26-multi-model-serving-economics-scope.md`
§9 says "the funding decision still cannot be made" (2026-09-26), that the $30-45
estimate was incomplete, and that the decision covers artifacts 4 and 5 together. It
proposed a paid cut order: interference-grid resolution first, then validation
repeats down to three, then the sleep-mode arm. `docs/dod-a4.md` recorded the gap:
spend was authorised in conversation and the account topped up, but no file recorded
the option chosen.

## What was spent

- **Artifact 4: $25.23** over 22.77 billed hours, 248 jobs (`docs/spend-a4.md`, from
  RunPod's billing API; confirmed against the RunPod console 2026-11-20).
- **Artifact 5: $14.48** over 13.06 billed hours, read from the billing API on
  2026-10-07 (`docs/experiment-a5.md`, "Actual spend": measurement endpoint $13.80,
  reconnaissance endpoint $0.68). That section is the artifact's own record. I found
  no separate `spend-a5.md`, and I found no record in the files that the owner
  confirmed A5's figure against the console. Network-volume storage is not included.
- **Combined, A4 + A5: $39.71**, about 20% of the $200 cap. Artifacts 1 and 2 also
  draw on the same $200; their spend is not counted here (`docs/spend-a2.md`;
  artifact 1's was never recorded, per the spec).

## Which proposed cuts the evidence shows were taken

Checked in `docs/experiment-a4.md`, `data/a4/analysis.json` and the post. The files
show what was run; they do not record that any run was cut under the owner's
decision, so "taken" below means "the run is smaller than the spec's full option",
not "a cut was decided at the time".

1. **Interference-grid resolution: reduced.** `analysis.json` `inputs.surface` has
   own levels 1, 2, 4, 8, 16, 32, 64 and neighbour levels 0, 16, 32, 64 (28 cells).
   Neighbour concurrency 1 to 15 was not measured; `placement/colocated.py`
   interpolates between grid points. `docs/dod-a4.md` and
   `docs/findings-a4-interference-sensitivity.md` state this, and the latter shows
   the fleet size does not depend on the range at this SLO.
2. **Validation repeats: three.** The registration (`docs/experiment-a4.md`, band)
   fixes exactly 3 real repeats, and `analysis.json` `validation` shows three
   (swaps real: 10, 10, 10; one host). The spec's text does not name a larger
   starting number, so I cannot show a reduction from a higher count; it is at the
   floor the cut order names.
3. **Sleep-mode arm: not cut.** It was run, 8 switches, median 5.0 s
   (`docs/post-a4.md`; registered in `docs/experiment-a4.md`).

## Closes

This record closes `a4-dod-budget-record` (the "Budget decision made explicitly,
with the option recorded" item in `docs/dod-a4.md`).
