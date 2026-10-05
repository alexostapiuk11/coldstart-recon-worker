# Runbook: artifact 4's paid measurement campaigns

For the owner; not a plan step. Do not run any of this without the owner's
say-so. It rents a GPU for roughly half a day in total, spread over several
sessions.

**Before starting**, all four must hold, in this order:
1. `docs/recon-a4.md` is committed, and its go/no-go passed for one class.
2. `data/a4/screen.json` is committed.
3. `docs/experiment-a4.md` has its "Step 2, part 2" section,
   `placement/registered.py` exists, and both are committed. Their git
   timestamp must predate every campaign record.
4. The worker image has been rebuilt from a commit containing plan 3's worker
   changes (`placement_measure/replay.py` and the `sleep` and `replay` job kinds).

**A. Image.** Push. CI (`build-worker.yml`) rebuilds the image because
`placement_measure/**` changed; record the digest its summary prints. The
analysis cites it beside reconnaissance's.

**B. Template.** A second template beside the reconnaissance one: the same
image digest, network volume `9c7ut2slrd` and container disk, but
`dockerStartCmd` `python3 -u /opt/a4_measure_handler.py`. Point the endpoint
(`RUNPOD_A4_ENDPOINT_ID`) at it: `workersMin` 0, `workersMax` 1, `idleTimeout`
5 s, `executionTimeoutMs` 1800000. One worker keeps the compile cache warm
across a campaign, so only the first job on a fresh worker compiles.

Added after the 2026-10-05 reconnaissance: the endpoint also needs `flashboot`
`false` (ignored at creation; set it by a follow-up update and read it back) and
`allowedCudaVersions` `["13.0"]`. Both are in `placement_measure/pins.py`, so the
preflight in C fails if either drifts.

**C. Free preflight.** One GET, no job.

```bash
set -a; . ./.env; set +a   # RUNPOD_API_KEY, RUNPOD_A4_ENDPOINT_ID
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a4_measure.py --kind cell --design data/a4/designs/cells.json --template-id <template id> --preflight-only
```

Expected: `[preflight] endpoint <id> matches artifact 4's pin set`.

**D. Cost estimate.** Wall time per job, from artifact 2's pilot on this
image (an 8B engine started in 84.5 s cold and 30.6 s warm) and nothing yet
measured for a 4B engine under load, so every figure here is an estimate:

| Campaign | Jobs at the example design | Per job | GPU time |
|---|---|---|---|
| Cells: solo grid, co-located grid, held-out cells | about 35 cells x 4 repeats = 140 | 2-6 min: one or two engine starts, then a measured run of at least 100 requests | 7-11 h |
| Swaps | 6 pairs x 2 cache states x 3 = 36 | 1-3 min: two engine starts | 1-2 h |
| Sleep mode, if reconnaissance found it working | 8 | 3-5 min | under 1 h |
| Validation replays | 3 | 20-28 min: a 900 s trace plus swaps and drain | about 1.5 h |

`scripts/a4_measure.py` prints the job count before it submits; the exact
count follows from the registered design. Price it with RunPod's per-second
rate on the day, read off the console. At the repository's illustrative
$0.00031/s, about 12 GPU-hours is about $13. **If the budget binds, cut in
the pre-registered order (scope amendment §9): the interference grid's
resolution first.** That is an amendment to step 2, committed before the cut
campaign runs, never a quiet edit to a design file.

*Added after review; not part of the plan's text.* The scope amendment's
order (§9, and decision 10) has three steps, not one: the interference grid's
resolution first, then validation repeats down to three, then the sleep-mode
arm. The first is what the paragraph above names; the other two follow only
if the budget still binds, each as its own committed amendment.

*Added after review.* To price a campaign before spending on it, count its
jobs from the design file. `a4_measure.py` prints the count only after its
preflight and then submits at once. This submits nothing and needs no
credentials (`--kind` is `cell`, `swap`, `sleep` or `replay`):

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -c "
import sys; sys.path.insert(0, 'scripts')
from a4_measure import load_design
print(len(load_design('cell', 'data/a4/designs/cells.json').schedule()))"
```

The cells row above is the product of its two columns, 140 jobs at 2-6 min,
which is 4.7-14 h; the 7-11 h in the last column is the plan's own estimate.
Take the count from the design and the per-job time from the first jobs
actually run.

**E. Cells.** The longest campaign. It resumes where it stopped, so it can run
over several sessions.

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a4_measure.py --kind cell --design data/a4/designs/cells.json --template-id <id> --store data/a4/cells.jsonl
```

To continue after a stop, add `--resume`. When it finishes, list the cells
that are short of valid repeats (a run whose measured engine compiled does not
count):

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -c "
import json
from placement import registered as R
from placement.inputs import load_records, short_cells
from placement.step2 import CELL_MIN_VALID
cells = [f'solo:o{c}' for c in R.SOLO_LEVELS] + [f'pair:o{o}:n{n}' for o in R.OWN_LEVELS for n in R.NEIGHBOUR_LEVELS] + list(R.HELD_OUT)
print(json.dumps(short_cells(load_records(['data/a4/cells.jsonl']), cells, min_repeats=CELL_MIN_VALID, require_warm_compile=True)))"
```

If any are listed, write a top-up design: a copy of `data/a4/designs/cells.json`
with `own_levels` and `neighbour_levels` set to `[]`, `solo` false,
`extra_cells` set to the listed cells, `repeats` 2 and a new `seed`, saved as
`data/a4/designs/cells-topup-1.json` and committed before it runs. Run it into
its own store, `data/a4/cells-topup-1.jsonl`. Every later step takes both
stores (`--cells` twice).

**F. Swaps, then sleep mode** (skip sleep mode if `registered.SLEEP_MEASURED` is False):

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a4_measure.py --kind swap --design data/a4/designs/swaps.json --template-id <id> --store data/a4/swaps.jsonl
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a4_measure.py --kind sleep --design data/a4/designs/sleep.json --template-id <id> --store data/a4/sleep.jsonl
```

**F2. Stop points, failures and the spend bound.** *Added after review; not
part of the plan's text.* `a4_measure.py` records every job as it lands, a
failed one included, and never retries in place. It does not stop on a
failure: a wrong `dockerStartCmd` or a bad template would run every job in the
design, each up to the endpoint's `executionTimeoutMs` of 30 minutes, so the
worst case is the job count times half an hour (about 70 h for 140 cell jobs).
What bounds it is you:
- Watch the first lines it prints, `[run N] <condition>: <outcome>`. If the
  first few are not `ok`, stop it (Ctrl-C). The runs already written stay in
  the store; the cause is fixed before anything resumes.
- `--resume` skips every run already in the store, **failed ones included**: a
  failed run is done, not pending. It also refuses a store whose records
  disagree with the rebuilt schedule, so resume with exactly the original
  design file.
- Cells: a failed run leaves its cell short of valid repeats, and the check in
  E lists it; the top-up in E is the way to fill it.
- Swaps and sleep mode have no top-up in the tooling. Their analysis refuses to
  run when a (cache state, target) combination has no ok swap, or when no
  sleep switch is ok, and that refusal is the signal. Whether to run a further
  campaign into its own store is the owner's decision, as a disclosed
  amendment; do not edit the stores.
- Compare the console's spend with the job count times the per-job time after
  the first session, before the second.

**G. The validation trace, then its replays.** The trace's load is a fraction
of the measured solo saturation, and the pre-registered draw is the first whose
replay the simulator predicts will finish within a job and genuinely swap. So
the design is written from the cell and swap stores, then committed, then run.
Add `--cells` once per cell store, top-ups included:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a4_step2.py replay --cells data/a4/cells.jsonl --swaps data/a4/swaps.jsonl
git add data/a4/designs/replay.json data/a4/designs/replay-check.json && git commit -m "data: artifact 4's validation trace, from the measured curve and swaps"
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a4_measure.py --kind replay --design data/a4/designs/replay.json --template-id <id> --store data/a4/replay.jsonl
```

If the script stops with "no pre-registered validation draw is feasible", do
not run anything: the gate cannot run as registered, and the owner decides,
as an amendment. `replay-check.json` records every draw tried and why.

The gate needs exactly three ok replays. A replay marked failed (a request
errored, or the job budget cut it short) does not count, and a fourth repeat
is not run to replace it: an open repeat count lets the band grow until the
model fits (artifact 2's gate). Stop and record the failure; the owner
decides whether the validation is re-run as a whole, as a disclosed amendment.

The replay payload carries the whole trace, and its output every request's
times. At the example design that is a few hundred kilobytes each way.
RunPod's payload and output limits are UNVERIFIED (the shared tooling plan's
item 12). If a replay comes back truncated or refused, that is the cause.

**H. After the runs.** Commit every store and design file, and record from the
console: the spend per campaign and the image digest. `docs/spend-a4.md`
(plan 3) collects them. The analysis is CPU only, and plan 3's next task.
