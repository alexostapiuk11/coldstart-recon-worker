# Which duplicate-payment defense holds: chat brief

## How to use this brief

Paste this whole file into an AI chat, then paste the prompt at the end (it is already the last section). Ask clarifying questions about anything below. About 45 minutes to study.

Read first: How these experiments earn trust (P2), Delivery guarantees and duplicate payments (P3).

## Why it exists

**Question:** **Campaign running; results pending: this page shows requirements, design, predictions and controls only.** A payment service records each payment in its own database and publishes it to Kafka; a ledger consumer applies it to balances in a second Postgres. Under real broker, process and network faults, which defense keeps every recorded payment applied exactly once: none (N), Kafka transactions (P3: idempotence) (K), an idempotency key at the sink (P3: key) (I), or an outbox (P3: dualwrite) plus that key (O+I)? And at which boundary does each one stop? One laptop, public software, 760 pre-registered trials.

**Requirements that drove everything:**

- Every payment committed in the source database is applied exactly once, and every balance equals opening + credits − debits over the source's payments, computed without reading anything the consumer wrote. *Why:* The source row is the business record of the payment. Conservation alone is useless here: double-entry keeps the total constant, so a duplicate or a loss never trips it. The review upgraded the invariant to per-account reconciliation.
- Attribute every loss and every extra apply to the producer side (source ↔ Kafka), the consumer side (Kafka ↔ ledger), or unattributable. *Why:* The defenses guard different boundaries, so a count without a birthplace cannot say which one failed. Unattributable applies are reported, never split by guesswork.
- Compare whole pipelines in which each contrast, N→K, N→I and I→O+I, adds exactly one defense. *Why:* The four defenses do not sit on one axis: ranked head to head, they would compare things at different layers.
- Inject real kills, pauses and network blackholes, at code hooks in the weakest window (can it break?) and at random times (how often?), and confirm each fault took effect. *Why:* The closest prior work simulated its faults inside the application. Random faults rarely land in narrow windows, so without targeted cells a zero would mean little.
- Before the campaign, show in real trials that the checker catches a duplicate and a loss when they happen, and stays silent when no fault runs. *Why:* A zero only means something if the harness can see a nonzero (controls (P3: controls)).
- Commit the hypotheses, fault matrix, void rules, gate and analysis before the first measured trial; no early stopping, no extension, and no anomaly output read until the campaign ends. *Why:* With 4 stacks × 9 cells, a result can be argued into shape afterwards. A pre-registration (P2: prereg) tag and dated amendments (P2: amendment) show which rules came first; reconnaissance ran before the tag and is not a result.

## Need to know first

- **Four stacks, three contrasts**: Same client, topic, two consumers, schema and failure policy; only the defense differs. **N**: dual write, at-least-once (P3: atleast) consumer. **K**: dual write, consumer offsets inside a Kafka transaction. **I**: dual write, key checked in the ledger transaction. **O+I**: outbox relayed by Debezium, plus the key. **N→K**, **N→I** and **I→O+I** each add one defense. Every producer is idempotent; O+I's needs a config override.
- **Nine cells, two timings**: Six faults plus a no-fault control (F0); the design matrix names them and the boundary map shows which gap each tests. F5 is a zombie (P3: groups) consumer. **Random-time** cells (F1–F3, F4-con-r; 30 trials per stack, as for F0) ask how often; **targeted** cells (a code hook; 10 trials) ask whether.
- **The commit-window duty cycle**: The share of a consumer's running time between its ledger `COMMIT` returning and its Kafka progress committing (`commitSync` for N and I, `commitTransaction` for K), measured in F0 trials over 20–50 s, the window random kills draw from (the analysis sums both consumers' windows over 60 s). A random kill duplicates only if it lands inside the window, so the duty cycle should predict the F4-con-r duplicate rate (H5).
- **Paired blocks, McNemar**: A **block** is one cell and one seed run on all four stacks in random order: the same fault schedule and payment stream. A void trial voids its whole block, re-run with a new seed, so analysed blocks stay paired (P2: pairing). For N vs K, the exact McNemar test uses only blocks where exactly one of the two had a duplicate (**discordant**); Newcombe's paired interval (method 10), over all the cell's blocks, gives a plausible range for the difference. Two contrasts are confirmatory: N vs K in F4-con-r (H5) and in F1+F2 (H4b).
- **Zero bound, rule of three**: The trial is the unit: payments in one trial share a fault and are never pooled. If 0 of N trials show an anomaly, the per-trial probability is below 1 − 0.05^(1/N), one-sided 95%. The **rule of three**, about 3/N, approximates it.
- **The detection gate**: Run after the pre-registration tag, before the campaign, and not counted in it: the checker on synthetic histories, two positive controls (P3: controls) on **N only**, and a negative control of five no-fault trials per stack. All four must pass; the rules are in the gate chart below.

## How it works 1 of 3: One K batch, killed in the commit window

A prediction (H1), not a result: values illustrate one payment. Only N has been seen duplicating this way (in the gate); K's abort-and-recommit path has not been run on a real cluster under a fault.

| Step | What happens | Ledger rows, 1 payment | Committed offset | Kafka transaction | payments-applied | Consumer K process |
|---|---|---|---|---|---|---|
| 1 | K polls a batch. `beginTransaction()` is client-local: the broker has heard nothing, so a kill now would leave no Kafka transaction to abort. | 0 | start of this batch | none at the broker | nothing | running |
| 2 | The ledger transaction commits to Postgres first. Kafka is not part of it, so this row is permanent whatever Kafka does next. (Decision: Postgres first, one state at the hook) | **1, committed** | start of this batch | none at the broker | nothing | running |
| 3 | K sends the record and adds its offsets: open, unseen. In one unscored diagnostic run (`diag_k1`, 200/s, 120 s), 67% and 65% of transactions retried the commit after ~100 ms, widening this window (H5). | 1, committed | start of this batch | **open; records, offsets pending** | **pending, hidden** | running |
| 4 | F4-con-t sends SIGKILL at `before_kafka_commit`: row committed, transaction open and never finished. Nothing in the dead process can undo the row. (Decision: Crash-only, every mode) | 1, committed | start of this batch | open; records, offsets pending | pending, hidden | **killed** |
| 5 | It restarts 5 s later; `initTransactions()` on the same `transactional.id` aborts the open transaction. Had it not come back, `transaction.timeout.ms` (60 s default) would. | 1, committed | start of this batch | **aborted** | **aborted, hidden** | **restarted** |
| 6 | The offsets were never committed, so the group resumes from the last committed offset and delivers the same batch again. | 1, committed | **unchanged** | aborted | aborted, hidden | restarted |
| 7 | K has no key check, so the Postgres commit runs again, and K sends the record in a new Kafka transaction. The ledger has the batch twice; Postgres was never in the aborted one. | **2, same partition and offset** | unchanged | **new one, open** | **1 aborted, 1 pending** | restarted |
| 8 | If nothing interferes, the second `commitTransaction` succeeds: offsets move on. A `read_committed` reader sees the payment once, a `read_uncommitted` one also the aborted copy. Kafka is consistent; the ledger is not. | 2, same partition and offset | **past this batch** | **committed** | **once; aborted copy in log** | **running** |

Bold cells changed in that step.

**Takeaway:** Output once, ledger twice: Kafka's transaction ended cleanly, but Postgres was never in it. H1 needs ledger duplicates in at least 8 of 10 F4-con-t trials (output once is reported beside it). No K result here.

## How it works 2 of 3: A producer-side loss: killed after the source commit

Observed in the detection gate on stack N (`gate_prod_1`, cell F4-svc), not a campaign result. H3 predicts K and I lose too.

| Step | What happens | Topic payments | Payment service | Client |
|---|---|---|---|---|
| 1 | The client sends `p00004003`; the service commits it to the source database. The payment now exists, and the source is the authority. | no record yet | running | waiting |
| 2 | The `after_source_commit` hook holds the service: committed, nothing sent. The orchestrator sees the fire 61 ms later and kills the service 424 ms after it fired. | no record yet | **killed** | waiting |
| 3 | The send never happens. Two payments reached the source in the 240 ms around the hook and were never published: this one and one other in-flight request. | **never published** | killed | waiting |
| 4 | The client saw both as `info` (timeout or reset), never `ok`. The service restarts after 5 s. | never published | **restarted** | **info, not ok** |
| 5 | The checker finds the payment in the source and not in the topic: a loss with a topic gap, born on the producer side. | never published | restarted | info, not ok |

Bold cells changed in that step.

**Takeaway:** Gap P: a crash between source commit and send loses the payment. H3 predicts O+I, whose outbox row is written in the source commit, loses none.

## How it works 3 of 3: A zombie consumer: paused, replaced, then it writes

Observed on N in reconnaissance (all 17 F5 trials), except steps 3 and 4's ledger count. K and I are predictions (H1, H2).

| Step | What happens | Consumer A | Group | Ledger rows, 1 payment |
|---|---|---|---|---|
| 1 | A polls a batch; the `after_poll` hook holds it and the orchestrator runs `docker pause` on A. Batch in hand, no database work yet. | paused, batch held | generation 1: A | 0 |
| 2 | With no heartbeat for `session.timeout.ms` (10 s), the coordinator moves A's partitions to B. In all 17 recon trials the generation went from 1 to 2 while the paused consumer (A or B) was paused. | paused, batch held | **generation 2: B** | 0 |
| 3 | B resumes from the last committed offset, gets the same batch and applies it (documented semantics; not in the recon record). | paused, batch held | generation 2: B | **1 (B)** |
| 4 | A unpauses 5 to 20 s (seeded) past the session timeout. Its first act is the `db_commit` of its held batch; Postgres cannot tell A is stale. About 0.1 s on, its offset commit is refused with `CommitFailedException`. | **wrote, then refused** | generation 2: B | **2 (B, then A)** |
| 5 | Crash-only: A exits and restarts into the next generation. Fencing stopped the Kafka commit, not the ledger write. | **exited, restarted** | generation 2: B | 2 (B, then A) |

Bold cells changed in that step.

**Takeaway:** The zombie wrote, then its commit failed; the ledger holds the payment twice (B's apply is documented semantics, not in the recon record). H1 predicts the same for K; H2, that I's key insert skips.

## System views (C4)

### Who and what the experiment touches (context)

Public software on one laptop; no employer system appears. The rules are tagged in git before the trials they govern. Bundles stay in runs/, and no anomaly output is read while the campaign runs.

- **Author**: designs, pre-registers, runs
- **Prior art**: Jepsen, Stripe keys, Debezium outbox
- **Pre-registration**: tags prereg-v1, campaign-v1
- **ledger-faults**: 4 stacks × 9 cells; a checker
- **Reader**: payments, distributed-systems hiring managers
- **Public software**: Kafka 4.3.1, Postgres 17, Debezium 3.7
- **One laptop**: 16 GB Apple M4; 8 GB Docker VM
- **Trial bundles**: one per trial in runs/; sealed
- Author → ledger-faults: designs, runs
- Prior art → ledger-faults: gap it fills
- Pre-registration → ledger-faults: fixes the rules
- ledger-faults → Reader: boundary map (pending)
- ledger-faults → Public software: pinned images
- ledger-faults → One laptop: one host
- ledger-faults → Trial bundles: writes

### The pipeline and the harness around it (container)

O+I runs consumer mode I; its service writes the outbox row in the payment's own transaction and never talks to Kafka. Every Kafka client goes through its own role's proxies: one proxy at the bootstrap address would fault nothing after the first metadata response. Admin and readback traffic stays off the proxies.

- **Client**: 200/s open loop; assigns payment_id
- **payment-service**: dual write (N, K, I) or outbox (O+I)
- **Toxiproxy**: per-role broker proxies; ledger-db, per consumer
- **Kafka ×3, KRaft**: payments: 6 partitions, RF 3
- **source-db**: payments, outbox: the authority
- **Debezium on Connect**: WAL slot to topic; O+I only
- **ledger-consumer A, B**: one group; mode N, K or I
- **Orchestrator**: seeded schedule; kills, pauses, toxics, hooks
- **Checker + analysis**: Python over each trial's bundle
- **ledger-db**: accounts, apply_log, processed
- Client → payment-service: HTTP
- payment-service → source-db: INSERT, COMMIT
- payment-service → Toxiproxy: send (N, K, I)
- source-db → Debezium on Connect: WAL (O+I)
- Debezium on Connect → Toxiproxy: relay (O+I)
- Toxiproxy → Kafka ×3, KRaft: role listeners
- Kafka ×3, KRaft → ledger-consumer A, B: poll, via proxy
- ledger-consumer A, B → ledger-db: batch txn, own proxy
- Orchestrator → ledger-consumer A, B: kill, pause, hooks
- Orchestrator → Checker + analysis: bundle

### Inside one ledger consumer: where the defenses sit (component)

Every mode runs this loop; only the key check (N and K skip it) and the Kafka step differ. K's step is traced in the walkthrough above. Hooks are named code points: disarmed, one volatile read; armed, they block until released or killed.

- **Poll a batch**: 100 ms poll, up to 500 records
- **after_poll hook**: batch in hand, no DB work (F5)
- **Key check (I, O+I)**: processed ON CONFLICT, same txn
- **Apply in Postgres**: apply_log rows, sorted increments
- **before_ledger_commit**: statements done, COMMIT not sent (F6)
- **Postgres COMMIT**: db_commit logged after it returns
- **before_kafka_commit**: ledger committed, Kafka not (F4-con-t)
- **Kafka progress**: N, I: commitSync; K: commitTransaction
- **Crash-only exit**: roll back, log, Runtime.halt(1)
- **Event log**: JSONL: polls, commits, rebalances
- Poll a batch → after_poll hook
- after_poll hook → Key check (I, O+I): I, O+I
- Key check (I, O+I) → Apply in Postgres: new keys only
- Apply in Postgres → before_ledger_commit
- before_ledger_commit → Postgres COMMIT: COMMIT
- Postgres COMMIT → before_kafka_commit
- before_kafka_commit → Kafka progress
- Kafka progress → Poll a batch: next batch
- Kafka progress → Crash-only exit: any error, any step
- Postgres COMMIT → Event log: db_commit

### Observed in the detection gate (stack N), not a campaign result (dynamic)

Trial `gate_cons_1`, a positive control on N in cell F4-con-t, as `docs/gate.md` reads it from the timelines. The ledger commit lands, the offset commit never does, so the batch comes back. The same order of events is what H1 predicts for K; nothing has shown K doing it yet.

- **Kafka partition 1**
- **Group coordinator**
- **consumer-A**: stack N
- **ledger-db**
- **Orchestrator**: injects the fault

1. Kafka partition 1 -> consumer-A: poll returns (1, 646) (payment p00004001)
2. consumer-A -> ledger-db: apply, COMMIT (db_txid 1898860)
3. ledger-db -> consumer-A: committed [reply]
4. Note over consumer-A: hook holds at before_kafka_commit (pending offsets {1: 647})
5. Orchestrator -> consumer-A: SIGKILL [fault]
6. consumer-A: killed in the commit window [crash]
7. consumer-A -> Group coordinator: commitSync({1: 647}) [never sent]
   (gap: 4.4 s later, as logged (matrix: 5 s))
8. Orchestrator -> consumer-A: docker start
9. Group coordinator -> consumer-A: generation 2: partition 1 back (from the last committed offset) [reply]
10. Kafka partition 1 -> consumer-A: poll redelivers (1, 646) [redelivered]
11. consumer-A -> ledger-db: apply, COMMIT again (db_txid 1899467, 10.1 s after the first) [applied twice]
12. Note over Kafka partition 1 to ledger-db: same (partition, offset) twice: consumer side

## Core decisions

### Whole pipelines, one change each

**Problem:** The brief listed four defenses as alternatives, but the outbox guards the producer side, Kafka transactions cover only Kafka-to-Kafka work, and the key works at the sink.

**Options considered:**

- Rank the four defenses head to head
- Add offsets stored in Postgres as a fifth arm
- Leave Connect's default, the relay producer's idempotence off
- Four whole pipelines, N, K, I and O+I, each contrast adding one defense, every producer idempotent

**Chosen:** Four whole pipelines, N, K, I and O+I, each contrast adding one defense, every producer idempotent

**Why:** Ranked head to head the defenses would compare things at different layers. Offsets in Postgres is correct and Kafka's docs recommend it, but it guards the consumer side as I does and breaks the three-contrast structure. With Connect's default, I→O+I would change two things at once. The client assigns `payment_id` at the origin, and every defense depends on that.

**Cost:** A reader running Debezium as shipped has a non-idempotent relay (`max.in.flight=1`) whose retries can duplicate: stated, not measured. Offsets in Postgres and KIP-618's exactly-once source are explained or named, not measured.

### Postgres first, one state at the hook

**Problem:** A crash between the ledger commit and Kafka's progress commit is where consumer-side duplicates are born, so the order of the two commits, and where the targeted kill lands, decide what is measured.

**Options considered:**

- Commit Kafka first, then Postgres
- Kill K before any Kafka work (the first draft's hook)
- Postgres first in every mode; `before_kafka_commit` placed per mode, for K after `sendOffsetsToTransaction`

**Chosen:** Postgres first in every mode; `before_kafka_commit` placed per mode, for K after `sendOffsetsToTransaction`

**Why:** Postgres first is the common order; the reverse trades duplicates for losses, which the post states by reasoning and does not measure. At the first draft's hook K had no broker-side transaction, so K and N ran the same code path; the review moved it. Now every stack is hit with the ledger committed and Kafka's progress not.

**Cost:** Results hold for this commit order only: a reader whose Postgres commits after Kafka is outside what is measured. K's commit step also carries Kafka's default ~100 ms `CONCURRENT_TRANSACTIONS` retry (reconnaissance; rates in How it works); it is left as is, named, and lengthens the window H5 measures.

### Crash-only, every mode

**Problem:** Outcomes in F1, F2, F5 and F6 depend on what a consumer does on an error; error handling must not become a second variable between stacks.

**Options considered:**

- Textbook in-process recovery: abort, seek, continue
- Crash-only: any exception in apply or commit rolls back if it can, logs, and halts; a supervisor restarts the process after 2 s

**Chosen:** Crash-only: any exception in apply or commit rolls back if it can, logs, and halts; a supervisor restarts the process after 2 s

**Why:** For these exceptions crash-only reaches the textbook outcome, resuming from the last committed offsets, and it is what an orchestrated deployment does by default. It removes the abort, seek and continue path, where a missed `seek` silently skips a batch and where KAFKA-17582 would act. The exit is `Runtime.halt(1)` with no client closed, so every crash looks the same to the group and the coordinator.

**Cost:** In-process recovery is unmeasured and named out of scope. A loss hypothesis about KAFKA-17582 was dropped before pre-registration: this design gives the bug no route to the ledger, so a zero would have read as evidence it never had.

### Real faults, checked

**Problem:** A defense can only be judged against faults that really happen to processes and the network, and a fault that silently did nothing would produce a false zero.

**Options considered:**

- Simulate faults inside the application, as the closest prior work does
- One Toxiproxy in front of the bootstrap address
- Random-time faults only
- Real kills, pauses and blackholes via per-role proxies; random (30) and targeted (10) cells; a check per cell

**Chosen:** Real kills, pauses and blackholes via per-role proxies; random (30) and targeted (10) cells; a check per cell

**Why:** Simulated faults are what the closest prior work used. Clients connect to what brokers advertise, so one bootstrap proxy would fault nothing after the first metadata response. Targeted cells ask whether, random cells how often. The manipulation check (P3: injector) reads only orchestrator, broker and process state; a failed check voids the trial and its block, and no trial is voided for what the checker found.

**Cost:** One laptop: combined KRaft, no database failover, no disk faults, no inter-broker partitions. Host contention needed two added void reasons (`host_swap_out`, then `host_degraded` in amendment A1); contention that starts after 20 s is not caught.

### Source as oracle, apply log

**Problem:** To say 'applied exactly once' and 'born here', the checker needs a truth independent of the consumer and a record of each apply's `(partition, offset)`.

**Options considered:**

- A unique applied table
- An 'unknown' bucket for timed-out requests
- A linearizability checker
- Count each payment in the source, topic and append-only `apply_log`; the source resolves `info`; attribute by offset

**Chosen:** Count each payment in the source, topic and append-only `apply_log`; the source resolves `info`; attribute by offset

**Why:** A unique applied table would hide the very duplicates N and K are expected to produce. The review dropped 'unknown' because it contradicted the source-as-authority rule. With unique IDs and commuting increments, counting each ID (P3: history) is a complete check, and order is not part of the invariant, so no linearizability checker is needed. The offset splits a duplicate into a redelivery or a re-send.

**Cost:** Order is not checked: a defense that holds here may not hold for a ledger with overdraft rules. The experiment can resolve `info`; a real client cannot. An apply whose offset is absent from the readback stays unattributable.

### Pre-register, gate, pair, seal

**Problem:** With 4 stacks × 9 cells on a noisy laptop, a result could be argued into shape afterwards, and a blind checker would give false zeros.

**Options considered:**

- Pool payments into a per-payment rate
- Look at results mid-campaign; stop early or extend
- Newcombe's method 8, as the plan's code first had it
- Against host contention: an operating condition, or a mechanical guard
- Rules tagged first; a detection gate; paired blocks with method 10 and McNemar; both contention fixes; a sealed campaign

**Chosen:** Rules tagged first; a detection gate; paired blocks with method 10 and McNemar; both contention fixes; a sealed campaign

**Why:** Payments in one trial share a fault, so the trial is the unit. Not reading results rules out any decision that depends on them. The implementer found the plan's φ lacked method 10's continuity correction (that is method 8); plan and code were fixed and checked against Newcombe's Table III before the campaign-v1 tag. The gate showed contention degrading 5 of 42 trials, so amendment A1 chose both the condition and a guard.

**Cost:** About 50–55 h of unattended runtime, and 30 trials per stack resolve only large differences, so H5 may end inconclusive. Reconnaissance ran before the tag; one rule (C-R, on cap refusals) was set after seeing its data, disclosed. The gate's positive controls ran on N only.

## Relationships

**Requirements and the decisions that meet them:**

- R1: Every payment committed in the source database is applied exactly once, and every balance equals opening + credits − debits over the source's payments, computed without reading anything the consumer wrote.
  - `checker` Source as oracle, apply log: Expected balances come from the source alone, never from what the consumer wrote.
- R2: Attribute every loss and every extra apply to the producer side (source ↔ Kafka), the consumer side (Kafka ↔ ledger), or unattributable.
  - `stacks` Whole pipelines, one change each: Each defense sits at the boundary it guards, so an anomaly's birthplace names the defense that missed it.
  - `checker` Source as oracle, apply log: Same offset: consumer side; different offset: producer side; offset missing: unattributable.
- R3: Compare whole pipelines in which each contrast, N→K, N→I and I→O+I, adds exactly one defense.
  - `stacks` Whole pipelines, one change each: N→K, N→I and I→O+I each add one defense; forcing the relay idempotent keeps I→O+I to one change.
  - `order` Postgres first, one state at the hook: The same commit order in every mode keeps N→K about the transaction, not about ordering.
  - `crash` Crash-only, every mode: One policy for N, K and I keeps error handling out of every contrast.
- R4: Inject real kills, pauses and network blackholes, at code hooks in the weakest window (can it break?) and at random times (how often?), and confirm each fault took effect.
  - `order` Postgres first, one state at the hook: The targeted cell F4-con-t can only ask whether a stack breaks if the kill lands in the same window for each.
  - `faults` Real faults, checked: Nine cells with two timings, each fault confirmed by a check that never reads the ledger.
- R5: Before the campaign, show in real trials that the checker catches a duplicate and a loss when they happen, and stays silent when no fault runs.
  - `faults` Real faults, checked: A fault that did nothing voids its block instead of passing as a clean zero.
  - `trust` Pre-register, gate, pair, seal: The gate's controls run before the campaign and must pass before it may start.
- R6: Commit the hypotheses, fault matrix, void rules, gate and analysis before the first measured trial; no early stopping, no extension, and no anomaly output read until the campaign ends.
  - `trust` Pre-register, gate, pair, seal: prereg-v1 precedes every gate and campaign trial; campaign-v1 precedes the first campaign trial.

**Decisions and the concepts they use:**

- `stacks` Whole pipelines, one change each uses Four stacks, three contrasts: The stacks are this decision.
- `order` Postgres first, one state at the hook uses The commit-window duty cycle: The hook sits inside the commit window; H5 measures how much time each stack spends there.
- `order` Postgres first, one state at the hook uses Nine cells, two timings: F4-con-t is the cell that fires this hook.
- `crash` Crash-only, every mode uses Four stacks, three contrasts: The policy is shared by every stack, like the client and schema.
- `faults` Real faults, checked uses Nine cells, two timings: The matrix is this decision in table form.
- `checker` Source as oracle, apply log uses The detection gate: The gate tested this checker on synthetic histories and on real controls.
- `trust` Pre-register, gate, pair, seal uses Paired blocks, McNemar: Paired blocks make N vs K a paired contrast with McNemar and Newcombe.
- `trust` Pre-register, gate, pair, seal uses Zero bound, rule of three: A clean cell is reported as a bound, not as safety.
- `trust` Pre-register, gate, pair, seal uses The detection gate: The gate is the control that makes a zero meaningful.

**Results and the decisions they support:**

- Gate controls on N (not a campaign result) → `trust` Pre-register, gate, pair, seal, `checker` Source as oracle, apply log
- The design: each stack's defense, each cell → `stacks` Whole pipelines, one change each, `faults` Real faults, checked
- Boundary map: gaps left open (predicted) → `stacks` Whole pipelines, one change each
- Predictions H1–H6 (pending) → `order` Postgres first, one state at the hook, `trust` Pre-register, gate, pair, seal
- What a zero claims (formula, not data) → `trust` Pre-register, gate, pair, seal
- K's commit step in recon (not a result) → `order` Postgres first, one state at the hook
- Attribution: five observations, three birthplaces → `checker` Source as oracle, apply log
- Fencing: neither stops the ledger write → `order` Postgres first, one state at the hook

## Implementation flow

11 steps in 5 phases, 5 milestones.

Milestones: 4. Reconnaissance A: rate, VM, K's commit step (2026-10-08 to 10-10 (−07:00)); 6. Reconnaissance B: F2, F5, F6 and the checks (2026-10-10 to 10-12 (−07:00)); 7. Pre-register, tag prereg-v1 (2026-10-12 11:23 (−07:00)); 8. Run the detection gate (2026-10-12 (−07:00)); 11. Amendments A1–A4, tag campaign-v1, start (2026-10-12 23:54 (−07:00)).

### Phase 1 of 5: Design (1 step)

1. **Reframe the brief into a two-boundary experiment**: First draft; an independent review moved K's hook, added the crash-only policy, H5, the producer and negative controls and per-account reconciliation; approved the same day.
   - Output: the approved spec: 4 stacks, 9 cells, H1–H6 with falsifiers, the detection gate, a learning guide
   - When: 2026-10-08 (−07:00)
   - Decision: `stacks` Whole pipelines, one change each
   - Evidence: 27309f692b in ~/projects/ledger-faults (first draft); d5e891140f in ~/projects/ledger-faults (review applied); a462af2c19 in ~/projects/ledger-faults (approved)

### Phase 2 of 5: Build (2 steps)

2. **Cluster, per-role listeners, service and consumers**: Three combined KRaft nodes; nine role proxies, verified by blackholing one role (F3 kept); the service in dual-write and outbox modes; consumers N and I, then K with Postgres first, all crash-only.
   - Output: a runnable pipeline in every stack mode; no fault injection yet
   - When: 2026-10-08 to 10-09 (−07:00)
   - Decision: `order` Postgres first, one state at the hook
   - Evidence: 15a39cf386 in ~/projects/ledger-faults (three KRaft nodes); f7bb16dd5b in ~/projects/ledger-faults (per-role listeners); b53a622819 in ~/projects/ledger-faults (service modes); fb274427d4 in ~/projects/ledger-faults (K, Postgres first)
3. **Checker on synthetic histories**: Counting over source, topic readback and apply_log; every anomaly class and attribution row tested on synthetic fixtures.
   - Output: checker/: classification and attribution per spec §6
   - When: 2026-10-09 (−07:00)
   - Decision: `checker` Source as oracle, apply log
   - Evidence: bf1c9f34da in ~/projects/ledger-faults (classification, attribution)

### Phase 3 of 5: Reconnoitre (3 steps)

4. **Reconnaissance A: rate, VM, K's commit step** [MILESTONE]: The rate rule failed first; after seeing that data it stopped counting cap refusals as errors (C-R, disclosed). VM stalls traced to the host swapping the Docker VM. `diag_k1` explained K's flat ~148 ms commit step. Values frozen, then re-verified on an 8 GB VM.
   - Output: docs/recon-part-a.md: 200/s, 8 GB VM, 512m heaps, swappiness 1; "Nothing here is a result."
   - When: 2026-10-08 to 10-10 (−07:00)
   - Decision: `faults` Real faults, checked
   - Evidence: e3413ea877 in ~/projects/ledger-faults (diag_k1); 181ce23666 in ~/projects/ledger-faults (host swap in the VM rule); 2cdf2f3db6 in ~/projects/ledger-faults (re-verified, frozen)
5. **Hooks, orchestrator and manipulation checks**: Hooks with a control channel; a seeded schedule per cell; injectors and a supervisor; per-cell manipulation checks and the void order.
   - Output: orchestrator/ and manip/: every cell injectable, every trial gets a verdict
   - When: 2026-10-10 (−07:00)
   - Decision: `faults` Real faults, checked
   - Evidence: e5107452a1 in ~/projects/ledger-faults (hooks); 1c370360b4 in ~/projects/ledger-faults (seeded schedule); 95fcd961b2 in ~/projects/ledger-faults (manipulation checks)
6. **Reconnaissance B: F2, F5, F6 and the checks** [MILESTONE]: F2's first set stopped on an observer bug, a harness error, fixed; F5's count restarted after host-swap voids (the zombie is traced in How it works). F6 kept at 10 of 10.
   - Output: docs/recon-part-b.md: session.timeout.ms 10 s, F2 20–60 s, F6 kept; part B frozen
   - When: 2026-10-10 to 10-12 (−07:00)
   - Decision: `faults` Real faults, checked
   - Evidence: 3aded02ae7 in ~/projects/ledger-faults (F5 frozen); 531735691f in ~/projects/ledger-faults (F6 kept); 38ebe49113 in ~/projects/ledger-faults (part B frozen)

### Phase 4 of 5: Pre-register and gate (2 steps)

7. **Pre-register, tag prereg-v1** [MILESTONE]: docs/experiment.md copies the spec's hypotheses, matrix, checks, gate and analysis verbatim by line range, with reconnaissance's frozen values and dated amendments. Tagged after reconnaissance, before any gate or campaign trial.
   - Output: docs/experiment.md at tag prereg-v1
   - When: 2026-10-12 11:23 (−07:00)
   - Decision: `trust` Pre-register, gate, pair, seal
   - Evidence: ba5ce52669 in ~/projects/ledger-faults (checker gate-set audit); c7ba566e78 in ~/projects/ledger-faults (tag prereg-v1)
8. **Run the detection gate** [MILESTONE]: The evaluator was committed minutes after the tag, before the first gate trial. 42 trials, two voids replaced. Five showed host contention; that became amendment A1.
   - Output: docs/gate.md: GATE PASS; positive controls on N only
   - When: 2026-10-12 (−07:00)
   - Decision: `trust` Pre-register, gate, pair, seal
   - Evidence: 9fb3bd3cb2 in ~/projects/ledger-faults (evaluator first); 9e42d3700a in ~/projects/ledger-faults (gate trials run); ddf2e522fa in ~/projects/ledger-faults (verdict recorded)

### Phase 5 of 5: Prepare the campaign (3 steps)

9. **Contention guard, block plan and runner**: `host_degraded` voids a campaign trial with over 100 cap refusals in its 5–20 s window; the 190-block plan is derived by code and committed; the runner resumes, replaces void blocks and reads only harness integrity.
   - Output: manip host_degraded; docs/campaign/campaign-plan.tsv; python -m campaign
   - When: 2026-10-12 (−07:00)
   - Decision: `trust` Pre-register, gate, pair, seal
   - Evidence: d38175470c in ~/projects/ledger-faults (host_degraded (A1)); 9ac7ceb7d4 in ~/projects/ledger-faults (block plan (A2)); 06f5c70723 in ~/projects/ledger-faults (runner (A2))
10. **Analysis code, with the Newcombe method fix**: Writing the statistics, the implementer noted the plan's φ had no continuity correction: Newcombe's method 8, not the pre-registered method 10. Plan and code were fixed within a minute and checked on Table III: 18, 12, 2, 18 gives 0.0562 to 0.3290.
   - Output: analysis/: Wilson, zero bound, Newcombe method 10, exact McNemar, H1–H6 evaluators
   - When: 2026-10-12 (−07:00)
   - Decision: `trust` Pre-register, gate, pair, seal
   - Evidence: 125767c80f in ~/projects/ledger-faults (method 8 flagged); 16d7a7784e in ~/projects/ledger-faults (plan fixed); 51e29fa724 in ~/projects/ledger-faults (code fixed); 78f4545345 in ~/projects/ledger-faults (evaluators)
11. **Amendments A1–A4, tag campaign-v1, start** [MILESTONE]: A1 contention, A2 the runner, A3 analysis definitions, A4 cost runs, appended in one dated commit and tagged (06:54 UTC on 10-13). The runner refuses campaign runs unless HEAD contains the tag; the campaign runs after it.
   - Output: tag campaign-v1; the campaign running, its anomaly output unread until it ends
   - When: 2026-10-12 23:54 (−07:00)
   - Decision: `trust` Pre-register, gate, pair, seal
   - Evidence: b613be0d48 in ~/projects/ledger-faults (A1–A4; tag campaign-v1)

## Results as meaning

### Gate controls on N (not a campaign result)

- Axis: One row per control of the pre-registered gate; counts are valid trials. A positive control passes when the anomaly appears, so green here means the checker saw what it had to.
- Read it as: Each control cleared its rule. Five trials had host CPU contention (thousands of cap refusals). Without them: 8 and 9 positives, 19 clean negatives; `docs/gate.md` calls that a pass, though 19 is short of the literal 20 of 20.
- How it is computed: docs/gate.md: CONSUMER 10/10, PRODUCER 10/10, NEGATIVE 20/20, SYNTHETIC pass. 42 trials, 2 void and replaced. Contended: 2 consumer, 1 producer, 2 negative (one of them void).

| trials | Pass rule | Observed | Void, replaced | Without contended (5 trials left out) |
|---|---|---|---|---|
| Consumer positive (N, F4-con-t) | duplicate in ≥ 8 of 10 [rule] | 10 of 10 duplicated [observed, passed] (1–9 duplicates per trial, all consumer side) | 1, host swap-out [observed, void] | 8 positive [observed, passed] |
| Producer positive (N, F4-svc) | loss in ≥ 8 of 10 [rule] | 10 of 10 lost, topic gap [observed, passed] (1–15 losses per trial, all producer side, none acked) | none [observed, passed] | 9 positive [observed, passed] |
| Negative (F0, five per stack) | 20 of 20 clean [rule] | 20 of 20 clean [observed, passed] (no class flagged in any trial, all four stacks) | 1, host swap-out [observed, void] | 19 clean [observed, passed] |
| Synthetic checker (every class planted) | classify every class [rule] | 44 passed, 26 rows [observed, passed] (one row per anomaly class and attribution row) | n/a [not applicable] | n/a [not applicable] |

- Note: Gate passed 2026-10-12, after the prereg-v1 tag, before any campaign trial; not counted in the campaign.
- So: see decisions `trust`, `checker`

### The design: each stack's defense, each cell

- Axis: Rows: the nine cells. Columns: stacks. Each cell names the guard that fault meets in that stack.
- Read it as: F0 is the in-campaign negative control; the boundary map below says which gap each fault tests.
- How it is computed: 4 stacks × (5 cells × 30 + 4 cells × 10) = 760 trials; 760 ÷ 4 = 190 blocks (docs/experiment.md §4).

| design | N (naive baseline) | K (Kafka transactions) | I (key at the sink) | O+I (outbox plus the key) |
|---|---|---|---|---|
| F0 (no fault · 30) | control [design] | control [design] | control [design] | control [design] |
| F1 (broker kill · both · 30) | dual write; offsets [design] | dual write; Kafka txn [design] | dual write; key [design] | outbox; key [design] |
| F2 (broker pause · both · 30) | dual write; offsets [design] | dual write; Kafka txn [design] | dual write; key [design] | outbox; key [design] |
| F3 (producer blackhole · 30) | dual write [design] | dual write [design] | dual write [design] | outbox relay (Connect) [design] (F3's producer role is Connect for O+I; its delivery timeout is unlimited) |
| F4-svc (kill after source commit · 10) | dual write [design] | dual write [design] | dual write [design] | outbox row, same commit [design] |
| F4-con-r (random consumer kill · 30) | offsets after commit [design] | Kafka txn, Postgres outside [design] | key in ledger txn [design] | key in ledger txn [design] |
| F4-con-t (commit-window kill · 10) | offsets after commit [design] | Kafka txn, Postgres outside [design] | key in ledger txn [design] | key in ledger txn [design] |
| F5 (zombie consumer · 10) | offsets after commit [design] | Kafka txn, Postgres outside [design] | key in ledger txn [design] | key in ledger txn [design] |
| F6 (COMMIT reply lost · 10) | offsets after commit [design] | Kafka txn, Postgres outside [design] | key in ledger txn [design] | key in ledger txn [design] |

- Note: Row sub: the fault, 'both' where it can stress both sides, and trials per stack. Every cell is design, not a result.
- So: see decisions `stacks`, `faults`

### Boundary map: gaps left open (predicted)

- Axis: Rows: the stacks. Columns: the two commit gaps, and the hypotheses that test them.
- Read it as: A crash in gap P loses a payment; in gap C it applies again. Predicted: the outbox closes P, the key closes C, and K's transaction leaves C open (H5: wider).

| prediction | Gap P: source→Kafka (COMMIT to Kafka ack) | Gap C: ledger→Kafka (COMMIT to Kafka commit) | Hypotheses |
|---|---|---|---|
| N | a kill loses it [seen in the gate (N only), open] | a kill repeats it [seen in the gate (N only), open] | gate: both seen [seen in the gate (N only)] |
| K | same dual write [predicted, open] | window predicted wider [predicted, open] | H1, H5; H3, H4 [predicted] |
| I | same dual write [predicted, open] | closed by the key [predicted, closed] | H2; H3 [predicted] |
| O+I | outbox in the commit [predicted, closed] | closed by the key [predicted, closed] | H2, H3 [predicted] |

- Note: Gap P: F3, F4-svc. Gap C: F4-con-r, F4-con-t, F5, F6. F1, F2: both. Pre-registered, not results.
- So: see decision `stacks`

### Predictions H1–H6 (pending)

- Axis: One row per hypothesis, condensed from pre-registration §7 (verbatim from the spec). Tone is what the prediction expects.
- Read it as: H4 is stated as uncertain, and all-zero there is publishable. No result has been read.

| prediction | Stacks, cells | Prediction | Falsified if | Result |
|---|---|---|---|---|
| H1 the boundary | K · F4-con-t and F5 [fixed] | K duplicates in ≥ 8 of 10, each cell [predicted, anomaly or cost expected] (each duplicate once in payments-applied: output once, ledger twice) | K below 8 of 10 in either cell [fixed] | pending [pending] |
| H2 key at the sink | I and O+I · all nine cells [fixed] | zero duplicates, zero balance off [predicted, no anomaly expected] (A3 reads balance off as the residual after losses, so H2 and H3 agree) | a single duplicate or balance off [fixed] | pending [pending] |
| H3 the dual write | N, K, I · F4-svc, F3; O+I all [fixed] | N, K, I lose ≥ 8 of 10 F4-svc; O+I none [predicted, anomaly or cost expected] (also a loss in every F3 trial longer than delivery.timeout.ms (120 s)) | < 8 of 10, a clean long F3, or O+I loss [fixed] | pending [pending] |
| H4 broker death (genuinely uncertain) | all stacks · F1, F2 [fixed] | no loss; K dup in more trials than N [predicted, mixed, uncertain] (and each K or N duplicate trial has its logged txn or commitSync error) | any loss; K ≤ N; a cause missing [fixed] | pending [pending] |
| H5 commit window (the non-obvious one) | N vs K · F4-con-r; duty F0 [fixed] | K duty cycle > N's; K dup more often [predicted, anomaly or cost expected] (paired interval including 0: inconclusive, never 'no difference') | K's duplicate share ≤ N's [fixed] | pending [pending] |
| H6 cost | cost runs, no fault [fixed] | I's rate within 10% of N; K, O+I add p50 [predicted] (max sustainable rate; p50 end-to-end latency; K vs O+I not predicted) | I > 10% slower; K or O+I p50 ≤ N's [fixed] (with non-overlapping run ranges; overlap is inconclusive) | pending [pending] (cost runs need new images, built after the campaign (a planned amendment A5)) |

- Note: Pre-registered at tag prereg-v1 (2026-10-12); results pending.
- So: see decisions `order`, `trust`

### What a zero claims (formula, not data)

- Axis: x: trials in one cell for one stack. y: the one-sided 95% upper bound on that stack's per-trial failure probability when every trial is clean.
- Read it as: Cutting random cells to 20, the last item on the cut list, would weaken 0.095 to 0.139. The rule of three sits just above the exact bound.
- How it is computed: 1 − 0.05^(1/N): 0.259 at 10 and 0.095 at 30 (docs/experiment.md §10); 0.139 at 20 (spec cut list); every 3/N computed here.
- Axes: x is trials per stack in a cell (N); y is 95% upper bound when 0 of N show an anomaly (per-trial probability)
- exact: 1 − 0.05^(1/N): 10: 0.259, 20: 0.139, 30: 0.095
- rule of three: 3/N (points): 10: 0.3, 20: 0.15, 30: 0.1
- Reference: targeted cells at x = 10
- Reference: random-time cells at x = 30
- Note: Computed from the formula; no trial data.
- So: see decision `trust`

### K's commit step in recon (not a result)

- Axis: Diagnostic `diag_k1`: stack K alone, 200/s for 120 s, no fault, unscored. Step, as diag_k1 defines it: from `sendOffsetsToTransaction` to `commitTransaction` returning (the earlier ~148 ms step was timed from the Postgres commit); both consumers alike.
- Read it as: When a consumer sends the next transaction's offsets before the coordinator has finished the last one's markers, it is refused once with `CONCURRENT_TRANSACTIONS` and waits about 100 ms. Reconnaissance read each K consumer as near 100% busy in its commit step.
- How it is computed: docs/recon-part-a.md: 2 vs 104 ms offset commit, 48 vs 149 ms whole step; 638 of 951 (67%) and 626 of 968 (65%) retried. Rest = step median − offset median.
- no retry (about a third): offset commit 2, rest of the step 46 (ms, median)
- one retry (65–67%): offset commit 104, rest of the step 45 (ms, median)
- So: see decision `order`

### Attribution: five observations, three birthplaces

- Axis: Rows: what the checker sees. Columns: its birthplace, and whether the gate showed it.
- Read it as: Same offset: the consumer side. New offset or topic gap: the producer side. A missing offset is unattributable, never guessed. A relay re-send would land at a new offset, so an offset is no key (reasoned, not measured).

| attribution | Born at | Seen in the gate |
|---|---|---|
| Topic gap | producer side: loss [rule] | p00004003 (F4-svc) [seen on N] |
| In topic, not applied | consumer side: loss [rule] | n/a [not shown] |
| Same offset twice | consumer side: redelivery [rule] | p00004001 at (1, 646) [seen on N] |
| New offset, same id | producer side: topic duplicate [rule] | n/a [not shown] |
| Offset not in readback | unattributable [rule] | n/a [not shown] |

- So: see decision `checker`

### Fencing: neither stops the ledger write

- Axis: Rows: issuer, what it rejects, where seen, effect on the ledger.
- Read it as: Generation fencing refuses a stale consumer's offset commit after its Postgres write. Epoch fencing guards one transactional.id against its own earlier run, so it cannot stop F5's zombie.

| fencing | Generation | Epoch |
|---|---|---|
| Issued by | group coordinator [rule] | transaction coordinator [rule] |
| Rejects | offset commit from an old generation [rule] | an older run of the same id [rule] |
| Seen here in | F5 on N: commitSync refused [seen on N in recon] | F4-con-t on K: restart aborts txn [predicted] |
| Stops the duplicate? | No: Postgres committed first [rule, no] | No: B has its own id [rule, no] |

- Note: KIP-447 added the generation check to K's TxnOffsetCommit.
- So: see decision `order`

## Interview card

**30-second pitch:** I built a fault-injection harness that asks which duplicate-payment defense holds between Kafka and a Postgres ledger: none, Kafka transactions, an idempotency key at the sink, or an outbox plus that key. Real kills, pauses and blackholes hit each pipeline, and a checker with the source database as the authority says whether every payment was applied exactly once and where any anomaly was born. A detection gate on the naive stack caught a duplicate and a loss, 10 of 10 each. The predictions were tagged before any gate or campaign trial; the campaign's results are sealed until it ends.

**2-minute version:** Teams say "exactly-once", but the usual defenses guard different boundaries: the outbox the producer side, Kafka transactions only Kafka-to-Kafka work, an idempotency key the sink. So I built four whole pipelines, each contrast adding one defense, on one laptop with public software, and a harness that injects real faults: broker kills and pauses, a producer blackhole, consumer kills at random times and at a code hook in the commit window, a zombie consumer, a lost COMMIT reply. A checker treats the source database as the authority and uses each apply's (partition, offset) to tell a redelivery from a re-send. The rules were tagged after reconnaissance and before the first gate trial, with dated amendments before the first campaign trial. H1 predicts Kafka transactions still double-post when killed after the Postgres commit. H5, the non-obvious one, predicts they make a random crash more likely to double-post, because the transaction commit widens the window between the ledger commit and Kafka's progress. A detection gate on the naive stack showed the checker sees a duplicate and a loss when they happen. The 760-trial campaign is running and I don't read its anomaly output until it ends, so today I can give you the design and the bets, not the answers.

**Hard follow-ups:**

- Q: Do your consumers commit the database before or after Kafka, and what does that do to your duplicate rate under crashes?
  A: Postgres first, then Kafka's progress, in every stack. A crash between the two leaves the ledger committed and the offset not, so the batch is redelivered and applied again unless the sink checks a key; the gate showed it on N, the record at (1, 646) applied again 10.1 s later. Kafka first trades duplicates for losses; that I state by reasoning, not measurement. How often a random crash lands in the window depends on the time spent there: H5 predicts K spends more, because of the ~100 ms commit retry reconnaissance saw (How it works, step 3). The campaign will measure the rates.
- Q: Kafka has exactly-once. Why doesn't K solve it?
  A: A Kafka transaction commits Kafka partitions and consumer offsets atomically; Postgres is not a participant, and KIP-939, two-phase commit with external participants, had not shipped as of October 2026 (its code was reverted for Kafka 4.2). By the documented semantics, a kill after K's Postgres commit and before `commitTransaction` ends in an abort, a redelivery and a second Postgres commit (How it works). H1 predicts duplicates in at least 8 of 10 such trials, and in the zombie cell; the campaign will say.
- Q: Why not store offsets in Postgres in the same transaction?
  A: It is correct, Kafka's docs recommend it, and it guards the consumer side as I does; as a fifth arm it would break the one-change contrasts. It deduplicates by (partition, offset), though, and an outbox relay's re-send lands at a new offset, so it would not catch O+I's relay duplicates. Only a key carried from the origin catches those.
- Q: How do you know a zero isn't a blind checker, or a fault that never happened?
  A: The detection gate, run after the tag: 44 synthetic tests covering 26 class and attribution rows; on N, commit-window kills gave a consumer-side duplicate in 10 of 10 trials and kills after the source commit a producer-side loss in 10 of 10; 20 of 20 no-fault trials across the four stacks were clean. Every campaign trial also gets a per-cell manipulation check that never reads the ledger; a failed one voids the block. The gap: the positive controls ran on N only.
- Q: Your zombie consumer: which fencing stops it, and does it stop the duplicate write?
  A: Generation fencing, at the offset commit: the group coordinator rejects a commit from an old generation. On N that is the ordinary check on `commitSync` in the classic group protocol; KIP-447 added the same check to K's `TxnOffsetCommit`. In reconnaissance on N, in all 17 F5 trials, the paused consumer's first act after unpause was a `db_commit` of the batch it held, then `CommitFailedException` about 0.1 s later. The Postgres write is another system's commit and has already happened, so fencing stops the Kafka commit, not the ledger write. Epoch fencing protects a `transactional.id` from its own earlier incarnation, and it is what aborts K's open transaction when K restarts. It cannot stop this zombie, because the consumer that took the partitions has its own `transactional.id`. For K, H1 predicts the same duplicate at `TxnOffsetCommit`.
- Q: What came before your pre-registration tag?
  A: Reconnaissance A and B: the rate, the VM, Debezium's lifecycle, the F2, F5 and F6 decision rules, and the manipulation checks on real trials. Their values were frozen into the pre-registration and none is reported as a result. One recon rule (C-R: cap refusals are not rate-rule errors) was set after seeing data, and is disclosed. The tag came before any gate or campaign trial, and the analysis code and amendments A1–A4 were tagged campaign-v1 before the first campaign trial.

**Limits (what I must not claim):** No campaign result is reported here: the campaign is running and its anomaly output is unread, so nothing here says which defense held. The gate's positive controls ran on N only; nothing yet shows K duplicating. When results exist they will hold for one laptop (combined KRaft, one Docker VM), this configuration (acks=all, Postgres before Kafka, crash-only recovery, the classic group protocol, these versions) and these faults; no overdraft rule, so ordering is untested; no database failover, disk faults or inter-broker partitions; client retries to the API are excluded; no production fault frequency is claimed. Reconnaissance numbers come from earlier environments and are not results.

## Recall questions

- Q: Under F4-svc, how does a dual-write stack lose a payment, and why should O+I not?
  A: The service commits the source row, is killed before sending, and the payment never reaches the topic: a loss with a topic gap, born on the producer side. O+I writes the outbox row in the same commit, and the relay publishes it later.
- Q: Where does the commit-window hook sit for K, and why not before the Kafka work?
  A: After the Postgres commit, the payments-applied sends and `sendOffsetsToTransaction`, before `commitTransaction`. Earlier the broker has no transaction yet (How it works, step 1), so K would run N's code path.
- Q: In `gate_cons_1`, what tells the checker the duplicate was born on the consumer side?
  A: The extra apply has the same (partition, offset), (1, 646), as the first: a redelivery. A different offset for the same payment would mean a re-send, born on the producer side.
- Q: Why pair random-time cells with targeted cells?
  A: Random faults rarely land in narrow windows, so a random zero alone would mean little. Targeted cells ask whether a defense can break at all; random cells how often it does under realistic timing.
- Q: Suppose I shows 0 anomalies in 30 trials of a cell. What could you claim?
  A: That its per-trial probability for that fault is below about 9.5% (one-sided 95%), on this setup. Not that the defense is safe in general.
- Q: Why does one void trial void its whole block?
  A: So every analysed block keeps all four stacks with the same fault schedule and payment stream: the pairing the N vs K contrasts rely on. The block is re-run with a new seed.
- Q: What is the commit-window duty cycle, and why should it predict F4-con-r duplicates?
  A: The share of running time between a ledger `COMMIT` returning and Kafka progress committing. A random kill duplicates only if it lands in that window, so a wider window should mean more duplicates (H5).
- Q: Why is a trial voided by a failed manipulation check but never by the checker's output?
  A: The check asks whether the fault happened, from orchestrator, broker and process state. Voiding on the checker's output would let results decide which trials count.
- Q: Why crash-only rather than in-process recovery?
  A: It reaches the same outcome (resume from the last committed offsets), is what orchestrators do by default, keeps error handling out of the contrasts, and removes the abort-seek-continue path where skip bugs live.
- Q: What does the passed detection gate not tell you?
  A: Anything about K, I or O+I under faults: both positive controls ran on N. Nor any campaign rate: the gate's trials are not counted in the campaign.

Sources: see the page

## Interview mode (paste this to an AI chat)

You are my interview coach. The brief above is the only ground truth about my project;
do not add facts it does not contain, and say "the brief does not say" when asked.

Settings (I may change these at any time):
- AUDIENCE: hiring manager | senior peer | skeptic
  (hiring manager: impact, ownership, trade-offs, what I would do differently;
   senior peer: technical depth on the decisions; skeptic: pushes on every hand-wave)
- DEPTH: pitch (30 s answer) | standard (2 to 5 minutes of follow-ups) | deep (three
  levels of "why")
- MODE: ask (you interview me) | quiz (recall questions, one at a time) | grade (I paste
  an answer, you grade it against the brief)

Default: AUDIENCE = hiring manager, DEPTH = standard, MODE = ask.

Rules:
1. One question at a time. Wait for my answer.
2. Do not reveal the brief's answers before I have answered.
3. After each answer, say what was solid, what was missing, and which stated limit I
   should have admitted. Keep it to five lines.
4. Never let me claim more than the brief supports. If I overstate, ask me to cut it
   back, and quote the limit.
5. I am a software engineer, not a researcher: reward clear reasoning about decisions
   and trade-offs over memorised numbers. A number is only useful to me as evidence for
   an answer.
6. Start now with my current settings and the first question.
