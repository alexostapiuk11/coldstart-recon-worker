# Runbook — artifact 1 campaign

How to run the cold-start measurement campaign against the live RunPod
endpoint, and what to do when it doesn't go cleanly. The pinned configuration
this campaign depends on is in `docs/experiment.md`; this file is about
operating it, not re-litigating what's pinned.

## Prerequisites

- `.env` in the repo root (gitignored) with `RUNPOD_API_KEY` and
  `RUNPOD_ENDPOINT_ID`.
- `HF_TOKEN` set as an environment variable on the RunPod template, in the
  RunPod console (Templates → the pinned template, id `mzadx4qugv` — see the
  "Provisioned infrastructure" table in `recon/README.md` — → Environment
  Variables). Use a read-scoped Hugging Face token.

  Arm A re-downloads the full model from the Hub on every one of its ~100
  runs. Unauthenticated Hub requests are rate-limited more aggressively, and
  hitting that limit mid-campaign would inflate arm A's `t_weights` for a
  reason that has nothing to do with the arm's cache configuration — it would
  look like a real effect. This has to be set by hand in the console; it is
  not something a script here can set, and the token must never be committed
  to this repo or written into `.env`.

- The endpoint matches the pinned configuration in `docs/experiment.md`
  (FlashBoot off, RTX 4090, the pinned network volume and template, workers
  min 0). `scripts/run_window.py` checks this automatically before every
  window (see "Pre-flight gate" below) — this bullet is about the state you
  should expect going in, not an extra manual check.

## Before every window: check capacity

RTX 4090 capacity in EU-RO-1 is volatile (see `recon/README.md`, "24GB
capacity is volatile"). Check it before starting a window:

```bash
set -a; . ./.env; set +a
curl -s -X POST "https://api.runpod.io/graphql?api_key=$RUNPOD_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"query":"query { dataCenters { id gpuAvailability { gpuTypeId available stockStatus } } }"}' \
  | .venv/bin/python -c "
import json,sys
d=json.load(sys.stdin)
for dc in d['data']['dataCenters']:
    if dc['id'] != 'EU-RO-1': continue
    for g in dc.get('gpuAvailability') or []:
        if g['gpuTypeId'] == 'NVIDIA GeForce RTX 4090':
            print('EU-RO-1 RTX 4090:', g['available'], g.get('stockStatus'))
"
```

Expected: `EU-RO-1 RTX 4090: True <stock>`. If `False`, do not start a
window. A queued job with no capacity behind it presents as a worker flapping
between `ready` and `throttled` while the job waits indefinitely — not as an
error you'll notice quickly. This check needs `.env` and talks to the RunPod
API directly; it is not run automatically as part of `run_window.py`.

## Pre-flight gate (automatic)

Every invocation of `scripts/run_window.py` fetches the endpoint's current
configuration and checks it against the pins in `coldstart/preflight.py`
(FlashBoot, GPU type, network volume id, template id, workers min) *before*
submitting any job. If anything has drifted, it raises `PreflightError` and
exits without spending anything — you'll see output like:

```
endpoint does not match the pinned configuration; refusing to spend:
  flashboot: True, expected False
```

This means the endpoint's actual configuration in the RunPod console has
changed from what's pinned in `docs/experiment.md` — most commonly FlashBoot
having been turned back on. Fix the endpoint in the console (or update the
pin and treat the campaign boundary as ended — see `docs/experiment.md`,
"Any change to a value above ends the experiment"). Do not weaken or bypass
this check to get a window running; it exists because an endpoint with
FlashBoot on produces a complete, plausible dataset that measures RunPod's
cache instead of the arms, and nothing downstream would reveal that.

## Running a window

```bash
set -a; . ./.env; set +a
.venv/bin/python scripts/run_window.py --triples 100 --resume
```

- `--triples` is the size of the **whole campaign schedule**, not this
  window. Every invocation of `run_window.py` for a given campaign must pass
  the same `--triples` (and the same `--store`) — the schedule is
  deterministically rebuilt from `arms`/`triples`/the fixed seed each time,
  and `--resume` skips whatever `run_index` values are already recorded.
  Running a window is just "start it, let it run, stop it when you want,
  resume tomorrow with the same `--triples`."
- `--resume` skips runs already present in `--store` (matched by
  `run_index`) instead of re-running them. Omitting it is no longer just "a
  choice you make when starting fresh" — if `--store` already holds records
  and `--resume` is not passed, `run_window.py` now refuses to start at all.
  See "Refusing to restart from zero" below.
- `--store` defaults to an **absolute, repo-root-anchored** path,
  `<repo>/data/campaign.jsonl` (`scripts/run_window.py:36`) — not a
  cwd-relative one. This is deliberate: `run_campaign`'s resume-drift guard
  only checks records that are actually present, so a cwd-relative default
  invoked from a different directory (a different terminal, a tmux pane, a
  cron entry) would silently open a fresh, empty store, pass the drift check
  trivially, and restart the "resumed" campaign from `run_index` 0 —
  re-submitting and re-paying for every run already collected. Passing
  `--store` explicitly always overrides the default.

  **`scripts/analyse.py`'s `--store` default is different: it is still
  cwd-relative (`"data/campaign.jsonl"`).** The two scripts do not behave
  alike. Always pass `--store` explicitly to `analyse.py` if you are not
  running it from the repo root, and don't assume "it worked with no flags
  for `run_window.py`" tells you anything about `analyse.py`.
- Use one store file per campaign — see "Resume drift" below for why.
- Stopping with Ctrl-C is safe. `KeyboardInterrupt` is not treated as a run
  failure and the store is append-only; nothing already written is touched.
- When the invocation ends (schedule exhausted, or you stopped it), it
  prints a tally line, e.g.:

  ```
  [done] 12 runs; failed=2 ok=10 (arm B: 2 failed); store=/path/to/data/campaign.jsonl
  ```

  This comes from `RunTally.summary()` (`scripts/run_window.py`) — total
  runs this invocation, a count per outcome, and, only when failures
  occurred, a per-arm breakdown of which arm they landed on. Look at the
  per-arm breakdown, not just the pass/fail total: one arm failing
  systematically (rather than failures spread evenly) is the signal that
  something about that arm's configuration is broken, not just noise, and is
  worth stopping to investigate before running another window.

## Resume drift: `ValueError` on resume

`run_campaign` (`coldstart/driver.py`) validates, on every `--resume`, that
every record already in the store matches the arm the freshly rebuilt
schedule assigns to that `run_index`. If you see:

```
ValueError: resume: stored run_index N has arm 'B' on disk, but the rebuilt
schedule assigns it arm 'A'. ...
```

or

```
ValueError: resume: stored run_index N falls beyond the rebuilt schedule,
which only covers 0..M for the given arms/triples/seed. ...
```

this means `run_window.py` was invoked with a different `--triples` (or a
different arm list, or store) than produced the data already on disk — most
likely a typo'd `--triples` value. **Do not work around this by clearing the
error or hand-editing the store.** Figure out the `--triples` value the
original window actually used (check earlier terminal output, or the highest
`run_index` plus the schedule's arm ratios) and re-run `--resume` with that
value. This check exists specifically to catch a resume that would otherwise
splice two different interleavings into one store — silently, since the
resulting file still looks like one well-formed campaign.

This guard also assumes **one store file per campaign**: it checks every
record in the store against the current schedule, so a store that
accumulated more than one independent, non-resumed campaign will trip a
false positive on a legitimate resume. Keep separate `--store` paths for
separate campaigns.

## Refusing to restart from zero: missing `--resume` on a non-empty store

Before submitting anything, `run_window.py` also checks whether `--store`
already holds records and `--resume` was not passed
(`_guard_against_silent_restart`, `scripts/run_window.py:97-124`). If so it
exits immediately, without contacting RunPod, printing:

```
refusing to start: N record(s) already exist in <store path> and --resume
was not passed. Continuing would re-submit and re-pay for every one of
them, and nothing downstream de-duplicates by run_index. Pass --resume to
continue the existing campaign, or --force-restart if you really mean to
start over from run_index 0.
```

This guard exists because forgetting `--resume` on, say, day three of a
campaign would otherwise silently re-submit and re-pay for every
already-completed run and append duplicate `run_index` rows to the store —
nothing downstream de-duplicates by `run_index`, so this would both bias the
dataset and waste money, without any error to flag it.

What to do: almost always, pass `--resume` — this is the normal case, and
matches "Running a window" above. Pass `--force-restart` only when you are
deliberately discarding the existing campaign and starting over from
`run_index` 0 (e.g. the store belongs to an aborted or unrelated run and you
want a clean slate under the same path). `--force-restart` does not delete
or touch the existing records; it just lets the script proceed despite them
and prints a `[warning]` line naming how many existing records it is
ignoring. If you use it, treat the store as no longer a clean single-campaign
history — move the old file aside first if you might need it later.

## Truncated store: `ValueError` on read

If a run (or your terminal) is killed mid-write, the JSONL store can end
with a truncated last line. `JsonlStore.read_all()` (`coldstart/store.py`)
detects this and raises a `ValueError` naming the file and the offending
line number, rather than silently dropping it:

```
ValueError: data/campaign.jsonl: line N is not valid JSON (...). A line
truncated mid-write is the signature of a process killed mid-append ...
```

To recover: confirm the bad line is the **last** line in the file (`wc -l`
the store, compare to the line number in the error), then delete just that
line — for example `sed -i '' '$d' data/campaign.jsonl` if it's the final
line, or open the file and remove it manually. Do not touch any other line.
Then re-run with `--resume`; the run that produced the truncated record
will be re-submitted since its `run_index` is no longer in the store.

## After every window

```bash
.venv/bin/python scripts/analyse.py --store data/campaign.jsonl
```

This is the analysis script that derives the published metrics from the
store (failure rate by arm, discard table, the bootstrap contrasts — see
`docs/experiment.md` for what's reported). Run it after every window and
check the per-arm counts, failure rate, and discard rate before deciding
whether to run another window or whether the stopping rule
(`docs/experiment.md`, "Stopping rule") has been met.
