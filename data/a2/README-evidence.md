# Artifact 2: evidence copied out of `build/`

The post's load-balancer findings and its headline frontier sweep rest on files
that were only in `build/`, which is git-ignored. This directory holds the
copies. Nothing here was edited; the step files are gzipped, byte for byte
otherwise.

**The five load-balancer probes are evidence for the post's load-balancer
findings. They are not pre-registered measurements.** They were run to find out
whether RunPod's load balancer could carry the validation gate's traffic, and
the endpoint settings changed between them on purpose. None has a hypothesis,
a threshold or a verdict in `docs/experiment-a2.md`.

All dates are 2026-10-05, from the mtimes of the files in `build/`. The commit
is the last one to touch `scripts/a2_lb_probe.py`, `scripts/a2_lb_common.py` or
the validation constants before the run. Each is "approximately": a run may have
used a working tree that was not yet committed, and the mtimes record when the
files were written, not when the run began.

## Load-balancer probes: `lb-probes/probe-N/`

Each directory holds `summary.json` and one `step-<rate>.jsonl.gz` per step.
`<rate>` is the step's target rate in requests per second. A row is one request
(`index`, `scheduled`, `sent`, `dispatched`, `latency`, `status`, `error`,
`headers`). `summary.json` holds `status`, the warm-up's aggregate statistics
and the per-step statistics under `steps`; its `workers` and `release` records
are empty in all five. The number of rows in each step file equals
`steps[<rate>].requests`.

| Probe | Written (local time) | Endpoint settings | Driver | Steps run | Status |
|---|---|---|---|---|---|
| 1 | 00:35-00:39 | scaler value 4, 2 workers | `16ca9bd` | 25, 50, 100 | stopped: `RuntimeError: can't start new thread` |
| 2 | 01:39-01:42 | scaler value 128, 2 workers | `c7861fe`, no 502 retry | 25-450 | complete |
| 3 | 02:01-02:04 | scaler value 128, 2 workers | `d26599c`, 502 retried once and marked | 25-450 | complete |
| 4 | 09:45-09:48 | scaler value 512, 1 worker, the old endpoint | `2d2d921` | 25-210 | complete |
| 5 | 12:28-12:30 | scaler value 512, 1 worker, the new endpoint, the new image | `e5741ce` | 25-210 | complete |

Steps: probes 2 and 3 ran 25, 50, 100, 200, 300 and 450 requests per second;
probes 4 and 5 ran 25, 50, 100, 150, 180 and 210.

Notes on each:
- **Probe 1** delivered about 17 requests per second whatever was offered:
  client p50 rose to 52 s while server p50 stayed 0.31 s, so requests waited in
  the load balancer, not in the engine. The ceiling is attributed to the
  endpoint's scaler value of 4: probe 2, on the same two workers with the
  scaler value at 128, ran every step with client p50 under 1 s
  (`docs/runbook-a2-validation.md`). Separately, the driver stopped early
  because it could not start another thread, which is why the driver was
  changed afterwards (`c7861fe`, `6dc761f`).
- **Probe 2** has no retry of a 502 that the load balancer returns without
  reaching a worker. **Probe 3** retries it once and marks the row with the
  `a2-driver-lb-retry` header.
- **Probe 4** is the first run after the gate was cut to one replica (amendment
  2026-10-05, second), since the load balancer fills workers in turn.
- **Probe 5** is the only one whose rows carry `x-a2-server-received`, the
  engine-arrival stamp (amendment 2026-10-05, third). The scaler value and the
  worker count are the same as probe 4's.

The endpoint's scaler value, worker count and image are RunPod settings, not
code. They are recorded here from the run notes in
`docs/runbook-a2-validation.md` and the session that ran them; the files
themselves do not contain them. The endpoint ids are not in the files and are not recorded here.

The endpoint settings of probes 1-3 (2 workers) cannot be recreated by the
current scripts: `VALIDATION_REPLICAS` in `autoscale/validation_schedule.py` is
1 since `2d2d921`.

To rerun a probe (spends money; reads `RUNPOD_API_KEY` and
`RUNPOD_A2_LB_ENDPOINT_ID`, and refuses a non-empty `--out`):

    .venv/bin/python scripts/a2_lb_probe.py --out build/a2-lb-probe-N

`--preflight-only` checks the endpoint and writes nothing. For probes 1-3 check
out the commit in the table first.

## Headline frontier sweep: `frontier-sweep.json`

The sweep cache that `scripts/a2_render_figures.py` writes as
`<out>/sweep-cache.json`: the sweep of every policy threshold on the committed
measured service curve (`data/a2/service-curve.json`), against
`data/campaign.jsonl`, with the keys `curve`, `identity`, `sources`, `swept` and
`gaps`. Its `identity` block fixes the traffic: additional replicas at peak 0.5,
baseline fraction 0.7, sustain 190 s, seed 17, 30 repetitions, until 400 s,
maximum 12 replicas. Its `gaps` are four paired-repetition gaps (30 pairs each):

| Gap | Point | Interval |
|---|---|---|
| arm A | 0.082 | 0.050 to 1.061 |
| arm C | 3.955 | 3.516 to 4.558 |
| ramp arm A | 8.249 | 7.894 to 8.598 |
| ramp arm C | 10.873 | 10.617 to 11.052 |

Written 2026-10-05 00:01 local time from `build/a2-figures-k05/`. The script's
last commit before then is `f505735` (2026-10-04 22:13), approximately. The
`k05` in the directory name is the 0.5 above.

To recreate it (the sweep takes hours; `--refresh` ignores a cache that is
already there, and a cache from other inputs is refused):

    .venv/bin/python scripts/a2_render_figures.py --out build/a2-figures-k05

The sweep is on the committed curve, which is one host's. The failed validation
and `docs/findings-a2-validation-host-speed.md` apply to every number in it.

## Checks

`tests/test_a2_evidence_files.py` checks that each probe has its steps with the
right row counts, that probe 1 stopped early, and that the sweep is the 0.5
sweep with the four gaps and arm C's 3.955.

Before copying, every file was scanned for `rpa_`, `SECRET`, `API_KEY`,
`Authorization`, `Bearer` and `token`, case-insensitively. There were no hits.
The only request headers in the rows are `x-a2-worker`, `x-a2-server-latency-ms`,
`x-a2-server-received` and `a2-driver-lb-retry`.
