# Learning progress

One record per module, written at each checkpoint. Read this before teaching
anything — re-explaining what already landed is the specific boredom failure
this file exists to prevent.

Verdicts: `solid` | `fuzzy` | `not_attempted`.

---

## Module 0 — diagnostic

- **attempted:** 2026-09-17
- **verdict:** mixed — see below
- **what the answers showed:**

| area | verdict | detail |
|---|---|---|
| serverless, containers | **solid** | Explained the cold-start mechanism correctly and unprompted, including warm-keeping. Cut from the material; it needed one sentence, not the section budgeted for it. |
| GPU memory, weights | **above self-report** | Self-reported "models run on GPUs, not much more", then named activations and the K/Q/V matrices unprompted. Did not complete the consequence chain (finite memory → ceiling on context length, fixed at startup). One correction owed and issued: **Q is not cached, only K and V.** |
| intervals | **fuzzy** | See below. Promoted to module 2. |
| the repo source | **not_attempted** | Directed the work, read summaries. The six code cards are new material, so each needs setup before the code appears. |

### The interval misconception, and what fixed it

- **what the answer missed:** that a confidence interval ranges over *medians of
  imagined re-runs*, not over the runs themselves. Stated as *"where the majority
  of numbers landed — a bell curve, most values in that range."*
- **correction issued, and what actually worked:**

  A first, abstract correction failed. The belief was then restated almost
  unchanged — which is the evidence that defining the concept does not shift it.
  Five steps did:

  1. Refute with his own data — arm A's interval spans a stretch where zero runs
     landed and excludes a value where nine did.
  2. Shrink the example to five numbers so the mechanism is visible.
  3. Name the misleading word: "shuffling" is reordering, which never moves a
     median. It is **drawing with replacement**.
  4. **The controlled test** — same two clusters, change only the split: 51/48
     gives a 5.00 s interval, 70/29 gives 0.00 s. This is the step that worked,
     and it is the only one where his own model made a prediction that was then
     falsified in front of him.
  5. Separate evidence from computation — 99 real runs cost GPU-hours and set the
     width; 10,000 resamples are free and change nothing.

  **Trap to remember:** arm A's interval runs ~81→86, exactly where its two
  clusters sit, so arm A alone *confirms* the wrong model. Step 4 is not optional.

- **also found, in the other direction:** a claim in the teaching material —
  "the interval shrinks as runs accumulate" — was contradicted by the campaign's
  own data. The questions caught it before it shipped.

---

## Modules 1–8

`not_attempted`.

---

# Artifact 2 — the autoscaling signal

The modules are in `plan.md`, under "Learning plan — artifact 2".

**Before the build, nothing was recorded.** The design spec's definition of
done asked for §13b's modules to be worked through before each build stage;
this file has no record that they were, so the build is treated as having run
first. The modules are now placed before publication instead: module 8's
teach-back is the post's last check, after the owner's own read.

| # | module | verdict | attempted |
|---|---|---|---|
| 0 | diagnostic | `not_attempted` | — |
| 1 | continuous batching and the service curve | `not_attempted` | — |
| 2 | Little's Law, checked on real data | `not_attempted` | — |
| 3 | why GPU utilisation is blind | `not_attempted` | — |
| 4 | dead time and cooldowns | `not_attempted` | — |
| 5 | frontiers, dominance and the iso-cost slice | `not_attempted` | — |
| 6 | the validation gate, and why it failed | `not_attempted` | — |
| 7 | what could not be concluded | `not_attempted` | — |
| 8 | teach it back | `not_attempted` | — |

**Carried over from artifact 1's module 0:** intervals were the largest gap,
and the controlled test (same clusters, different split) is what fixed it.
Artifact 2's post leans on bootstrap intervals in the H3 table and in the
iso-cost argument, so module 5 should open by checking that the fix held,
not by re-teaching it.

---

# Artifact 5 — how many LoRA adapters fit on one GPU

The modules are in `plan.md`, under "Learning plan — artifact 5".

**Before the build, nothing was recorded.** The design spec's definition of
done asked for §12b's modules to be worked through before each build stage;
this file has no record that they were, so the build is treated as having run
first, as for artifact 2. The modules are placed before the post is published:
module 7's teach-back is the post's last check, after the owner's own read.
Nothing below is a verdict. Every row is `not_attempted` until a checkpoint is
run and its answer recorded here.

| # | module | verdict | attempted |
|---|---|---|---|
| 0 | diagnostic | `not_attempted` | — |
| 1 | what an adapter is, and what rank sets | `not_attempted` | — |
| 2 | registered is not active | `not_attempted` | — |
| 3 | spread vs interval, then the knee | `not_attempted` | — |
| 4 | Little's law and the three bounds | `not_attempted` | — |
| 5 | the equivalence gate, and the amendments | `not_attempted` | — |
| 6 | the cost bars, and what cannot be concluded | `not_attempted` | — |
| 7 | teach it back | `not_attempted` | — |

**Carried over, and what is and is not known:**

- **Intervals.** Artifact 1's module 0 found them the largest gap, and the
  controlled test fixed it there. Nothing since has checked that it held:
  artifact 2's modules, which lean on intervals, are all `not_attempted`.
  Module 3 opens by testing it, on the post's own sentence that the bars say
  where the median would land and not where one start lands.
- **Little's law.** Artifact 2's module 2 teaches it on real data and has no
  recorded attempt. Module 4 here cannot assume it. If artifact 2's module 2 is
  run first, module 4 shortens; if not, module 4 is the first time it is
  taught.
- **The validation gate.** Artifact 2's module 6 is the same shape as module 5
  here (a pre-registered test, a failure to pass it, amendments). If they are
  both run, do artifact 2's first and open module 5 by asking what differs: a
  gate that came back *inconclusive* is not a gate that failed.
- **Self-check 8 is the diagnostic's prediction.** §12b's "flat to 32 and then
  sharp" is contradicted by the data (the knee is between 8 and 16 and the
  spread line is already falling at 2 and 4 slots). Record the answer given
  before the chart is shown; module 2 then checks it.

**One open item found while writing the plan, not yet resolved.** The post's
memory section says 42,864 tokens of KV hold 1,478 requests of 29 tokens, in the
same paragraph that counts 2,048 tokens for 64 such requests "in 16-token
blocks", which is 32 tokens each. In blocks the figure is 42,864 ÷ 32 = 1,339.
The conclusion (KV never binds at this shape; either figure is over twenty times
the 64 in flight) is unchanged. Module 4's last question asks for the
recomputation. If the post is corrected, the correction is appended as a dated
note and this item is closed here.
