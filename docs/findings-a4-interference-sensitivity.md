# Finding (exploratory): the co-located fleet survives a several-fold larger interference penalty, and fails first in the bursty regime

**Date:** 2026-10-07
**Status:** exploratory, run after the analysis was published. It does not change
`data/a4/analysis.json`. Reproduce with
`PYTHONPATH=. .venv/bin/python scripts/a4_interference_sensitivity.py`; the output is
`data/a4/exploratory/interference-sensitivity.json`. Spends nothing.

## The question

The interference grid measures a neighbour at concurrency 0, 16, 32 and 64. The
simulator interpolates linearly between 0 and 16 (`placement/colocated.py`), where
lightly loaded tenants sit, so a neighbour at concurrency 1 pays about a sixteenth of
the penalty a neighbour at 16 pays. Nothing measured that range. How much does the
co-located fleet depend on it, and on the penalty's size?

## What was run

The reference skew, s = 1.0, in both regimes, 6 repetitions (not the sweep's 30), with
the same sizing rule. Only the interference surface changes:

| surface | what it is |
|---|---|
| registered | as analysed |
| step | any busy neighbour (concurrency 1 and up) costs what 16 costs; the worst reading of the unmeasured range |
| x4, x8 | the step surface with every busy-neighbour latency multiplied by 4 or 8 |

## Result: GPUs the co-located fleet needs, with the other two for reference

| surface | spread: dedicate / swap / **co-locate** | bursty: dedicate / swap / **co-locate** |
|---|---|---|
| registered | 20 / 13 / **10** | 21 / 10 / **12** |
| step (about 2.2 times) | 20 / 13 / **10** | 21 / 10 / **12** |
| x4 | 20 / 13 / **12** | 21 / 10 / **20** |
| x8 | 20 / 13 / **16** | 21 / 10 / **21** |

- The unmeasured range does not matter at this SLO: the step surface sizes the same
  fleets as the registered one. Co-located latency is about 3 to 6 s against an SLO
  of 75.6 s.
- Multiplying the busy-neighbour latency by 4 leaves the spread regime's co-located
  fleet one GPU short of losing to swapping (12 against 13); by 8 it loses (16 against
  13). In the bursty regime it loses to swapping at 4 (20 against 10) and matches
  dedicating at 8 (21).
- The swap fleet and the bursty-regime rule (swap) do not change under any surface
  tried.

## Limits

One skew, 6 repetitions, one SLO. The multipliers are not measurements: they say how
much room the measured penalty leaves, not what a real neighbour would cost. The
bursty regime has less room than the spread one: it fails between the measured penalty
and 4 times it, the spread regime between 4 and 8 times.
