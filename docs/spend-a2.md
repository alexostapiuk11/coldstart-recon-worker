# Artifact 2: what it cost

Source: RunPod billing API, `GET /v1/billing/endpoints`, read 2026-10-05; cross-checked
in scale against the owner's console export of daily billing.

The API's rows are committed as returned, in
[`data/a2/billing-endpoints.json`](../data/a2/billing-endpoints.json).
`scripts/a2_post_analysis.py` reads them into the `spend` section of
`data/a2/post-analysis.json`, and `tests/test_a2_post_analysis.py` checks that every
dollar figure and time below is the one computed there.

| item (what ran on that endpoint) | endpoint | day (the API's bucket) | time billed | dollars |
|---|---|---|---:|---:|
| Reconnaissance capture, Q1/Q2 (`docs/recon-a2.md`) | `7h0aglrmsjovyc` | 2026-10-04 | 1,846 s | $0.57 |
| Service-curve sweeps: the pilot, levels 1-64 (superseded, `data/a2/superseded-levels-1-64/`) and the curve's 1-256 campaign | `a8261k5opy1ldl` | 2026-10-04 | 5,904 s | $1.82 |
| Exploratory host re-measurement, `--max-num-seqs` 128 and 256 (`data/a2/exploratory/`) | `a8261k5opy1ldl` | 2026-10-05 | 1,402 s | $0.43 |
| Load-balancer probes 1-4; the two-replica repeat (records not committed); the three one-replica repeats in `data/a2/validation/`; attempt one's void repeat | `lybvnpnt2m327y` | 2026-10-05 | 6,869 s | $2.11 |
| Load-balancer probe 5; attempt one's three judged repeats; attempt two's three repeats | `un0lhqt51q1bvp` | 2026-10-05 | 3,706 s | $1.14 |
| **Artifact 2, total** | 4 endpoints | | **19,726 s (5.5 h)** | **$6.07** |

That is $1.11 per hour of time billed, and it is the rate the post prices with. Each
row on its own comes to $1.108-$1.109 an hour.

**Which run billed to which endpoint.** The validation records name their endpoint
(`endpoint_id`): the three repeats in `data/a2/validation/` and attempt one's void
repeat name `lybvnpnt2m327y`, and attempt one's three judged repeats and all three of
attempt two's name `un0lhqt51q1bvp`. The probe files name no endpoint except probe 1's,
whose timeout errors name `lybvnpnt2m327y`'s hostname. `data/a2/README-evidence.md`
places probe 4 on the old endpoint and probe 5 on the new one. Probes 2 and 3, and
the two-replica repeat, are placed by elimination. `un0lhqt51q1bvp` was created with
the image rebuilt for the engine-arrival stamp, which the third amendment of
2026-10-05 introduced (signed 10:58 Pacific time). Probes 2 and 3 ran at 01:39-02:04
that morning, and the two-replica repeat ran before the second amendment cut the gate
to one replica (09:35). Attempt one's void repeat still ran on `lybvnpnt2m327y` at
12:01. The sweep stores don't name an endpoint. The sweep and recon rows rest on
what each endpoint was created for (recorded with the billing rows, and in
`docs/recon-a2.md` and `docs/runbook-a2-validation.md`).

**Day buckets are the API's.** The API does not say which time zone its days use.
Every run above falls on the same calendar date in UTC and in US Pacific time (the
time zone of the commits and file times), so the attribution doesn't depend on it.

**Not included: network-volume storage.** The console bills it as an account-level
line, shared with the other artifacts, at about $0.117 a day across the export's
period (more on 2026-10-04 and 2026-10-05), per the owner's console export. It is
not an endpoint's cost and is not in the total.

**The console cross-check.** The owner's console export (serverless column, whole
account) shows $2.368 for 2026-10-04 and $18.593 for 2026-10-05. Artifacts 4 and 5
used the same account on both days, so these say nothing per endpoint. They agree
in scale, not to the cent: on 2026-10-04 the API's artifact 2 rows sum to $2.39,
$0.02 more than the console's whole-account figure for that day. The two sources'
day boundaries or rounding may differ; this record doesn't explain the difference.

**Against the session's estimates.** The estimates kept in the publication plan's
Task 13 summed to $6.41. RunPod billed $6.07.

## Artifact 1, for the record

Artifact 1's endpoint, `ka5mryakkxumew` (`docs/experiment.md`), billed **$37.16**
for compute over 120,718 s (33.5 h) in the API's day buckets 2026-08-28 to
2026-09-04, per the same API, read the same day. That covers artifact 1's
reconnaissance (its captures were committed on 2026-08-28) and its campaign (data
committed on 2026-09-02 and 2026-09-03: `68ece63`, `e2ffd6b`, `83ec68f`). The same
storage exclusion applies.
