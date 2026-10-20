# A6 practice: duplicate-payment defenses: practice brief

## How to use this brief

Paste this whole file into an AI chat. The last section is the prompt that makes the chat quiz you; lines marked KEY and RED FLAG are the answers, hidden from you until you have tried. Practice for: Which duplicate-payment defense holds. About 35 minutes.

## Objectives

- Draw the two commit gaps (source to Kafka, ledger to Kafka) and place N, K, I and O+I on them as predictions.
- For F4-svc, F4-con-t, F5 and F6, say which stack is predicted to lose or duplicate, at which gap, and by what mechanism.
- Walk K's commit-window kill through the abort and the redelivery, and say why the ledger has two applies and payments-applied one.
- Classify an extra apply as consumer-side, producer-side or unattributable from its (partition, offset) and the topic readback.
- Compute the one-sided 95% zero bound for N trials, and say why the trial, not the payment, is the unit.
- Say what the passed detection gate does not show, and which statements on the page are predictions rather than results.

## Check yourself first

### Check 1

Q: A consumer commits its Postgres transaction, then its Kafka offset, and is SIGKILLed between the two. Which records come back after the restart, and why?
KEY: Everything from the last committed offset, which includes the batch already in the ledger. Progress is recorded only after the Postgres commit, so the old offset still stands and the batch is delivered again.
If missed, review: Offsets, committed after the work (P3: offsets)

### Check 2

Q: An idempotent producer retries a send after a timeout. Later the whole process restarts and sends the same payment again. Which of the two extra copies can the broker drop?
KEY: Only the in-session retry. Idempotence works within one producer session; the restarted process is a new session, so its copy is new to the broker. The same holds for a relay re-sending.
If missed, review: Idempotent producer versus transactions (P3: idempotence)

### Check 3

Q: 0 anomalies in 10 targeted trials: what per-trial probability can you exclude at one-sided 95%?
KEY: Anything above about 0.259, from 1 − 0.05^(1/10). The rule of three, 3/10, gives 0.3, just above it. The trial is the unit; the payments inside one trial share its fault.
If missed, review: Zero bound, rule of three

## Estimation drills

### Estimate 1: How many clean trials bound a failure rate below 1%?

Problem: A cell shows 0 anomalies in N trials for one stack. How large must N be for the one-sided 95% upper bound on the per-trial failure probability to fall below 1%, and how does that compare with the campaign's 30-trial random cells?

KEY steps:

1. The bound is 1 − 0.05^(1/N). Set it to 0.01: 0.05^(1/N) = 0.99.
2. Take logs: (1/N) × ln 0.05 = ln 0.99, so N = ln 0.05 ÷ ln 0.99.
3. ln 0.05 is about −2.9957 and ln 0.99 about −0.01005, so N is about 298.07. Round up: 299 trials.
4. The rule of three, 3/N = 0.01, gives N = 300, just above the exact 299 (the approximation sits slightly above the exact bound).
5. A random cell has 30 trials per stack: 0 of 30 bounds the rate below 0.095. 299 trials is about ten times as many (299 ÷ 30 = 9.97).

KEY answer: About 299 clean trials (300 by the rule of three), roughly ten times a 30-trial random cell. A clean cell bounds a failure rate; it never shows a defense is safe in general.

### Estimate 2: What can 30 paired blocks resolve under McNemar?

Problem: For N vs K in one cell, b is the number of blocks where only K duplicated and c where only N did. With the exact two-sided McNemar test on the discordant blocks, how many discordant blocks, all in one direction, give p below 0.05? What about a mixed split such as 8 and 2?

KEY steps:

1. Only discordant blocks count. With n = b + c of them and no real difference, each is a fair coin.
2. Exact two-sided p = 2 × P(X ≤ min(b, c)), with X binomial(n, 0.5).
3. All one way: (5, 0) gives 2 × 0.5^5 = 0.0625, above 0.05; (6, 0) gives 2 × 0.5^6 = 0.03125, below it.
4. A mixed split needs more: (8, 2) has n = 10 and P(X ≤ 2) = (1 + 10 + 45) ÷ 1024, so p = 112 ÷ 1024 = 0.109.
5. So at least 6 discordant blocks, all one way, are needed; with 30 blocks per contrast cell only a large difference can resolve.

KEY answer: 6 discordant blocks all in one direction (p = 0.03125); 5 gives 0.0625 and an 8-to-2 split 0.109. This is arithmetic on hypothetical counts, not a prediction of what the campaign will show.

## Deep-dive drills

Ordered easy to hard.

### Drill 1 of 11

Q: Why is exactly-once delivery the wrong goal, and what do you build instead?
KEY: Over a network that drops acknowledgements, delivery is at-least-once or at-most-once. You build exactly-once effect: make a repeat harmless at the sink, with an id assigned at the origin and checked in the same transaction as the state change. Then you measure that it holds under faults rather than assume it.
RED FLAG: Turn on Kafka exactly-once and you have it end to end.

### Drill 2 of 11

Q: Your consumer commits Postgres and then the offset. Why that order, and what does the reverse do?
KEY: Postgres first turns a crash between the two into a duplicate, which a key can absorb. Offset first turns it into a loss: progress says done, the ledger never got the batch, and nothing downstream can repair that. Prefer the failure you can neutralise. The unit argues the reverse by reasoning; it is not measured.
RED FLAG: The order doesn't matter if you retry.

### Drill 3 of 11

Q: Why isn't a Kafka offset a good idempotency key?
KEY: It names a log position, not a payment. A producer-side re-send, such as an outbox relay's, lands at a new offset, and an offset key treats it as new. An id assigned at the origin is identical on every copy. This is reasoning from the spec; relay re-sends are not measured here.
RED FLAG: Offsets are unique, so they dedupe.

### Drill 4 of 11

Q: K is killed after its Postgres commit and before commitTransaction. Walk me through recovery.
KEY: The broker holds an open transaction with pending payments-applied records and pending offsets. On restart, initTransactions on the same transactional.id aborts it; transaction.timeout.ms (60 s default) would if the process never returned. The committed offset is still the old one, so the batch is redelivered and the Postgres commit runs again; the first one stands. Output once at read_committed, ledger twice. H1 predicts this; no K fault trial has run.
RED FLAG: The Kafka transaction rolls back the Postgres write.

### Drill 5 of 11

Q: A zombie consumer wakes with a batch in hand. Which mechanism rejects it, where, and does that stop the duplicate?
KEY: Generation fencing, at the offset commit: the coordinator refuses a commit from an old generation. On N, reconnaissance saw CommitFailedException about 0.1 s after the zombie's db_commit in all 17 F5 trials; KIP-447 gave K's TxnOffsetCommit the same check. The Postgres write has already happened. Epoch fencing does not help: the consumer that took the partitions has its own transactional.id. Only a check inside the ledger transaction (the key, or offsets stored in Postgres) can stop it (H2 predicts the key).
RED FLAG: Fencing stops the zombie from writing.

### Drill 6 of 11

Q: F6: the ledger COMMIT reaches Postgres, the reply is lost, and the client's socket times out. What happens in N and in I?
KEY: The consumer cannot tell whether the commit happened. Crash-only exits without committing the offset, so the batch is redelivered. Predicted: N applies it twice. In I the key row committed with the first attempt, so the replay conflicts and is skipped (H2 predicts that; not run). It is the Two Generals problem at the database boundary; an idempotent apply is the clean answer short of reading state back.
RED FLAG: The commit failed, so nothing was written.

### Drill 7 of 11

Q: Stack I: two consumers, the zombie and the new owner, apply the same payment_id at READ COMMITTED. Can both apply it?
KEY: No. INSERT ... ON CONFLICT DO NOTHING on the unique key makes the second inserter wait for the first transaction to finish. If the first commits, the second sees the conflict, gets no row back and skips the balance update; if it aborts, the second proceeds. Putting the key insert and the balance update in one transaction is what makes this safe. This is standard Postgres behaviour; confirm it on your version.
RED FLAG: Check the processed table first and insert in a separate step, or say only SERIALIZABLE works.

### Drill 8 of 11

Q: The detection gate passed. What does it not tell you?
KEY: Both positive controls ran on N only, so nothing yet shows K, I or O+I duplicating or holding under faults. Gate trials are not campaign data. Five trials ran under host contention; the pass holds without them (8 and 9 positives, 19 clean negatives against a literal 20 of 20), and that is disclosed. Each campaign trial also needs its own manipulation check.
RED FLAG: The harness is validated, so a zero for I means it is safe.

### Drill 9 of 11

Q: Why random-time cells and targeted cells?
KEY: Targeted cells ask whether a defense can break at all: the fault lands in its weakest window, 10 trials, and 0 of 10 bounds the per-trial probability below 0.259. Random cells ask how often under realistic timing: 30 trials, and 0 of 30 bounds it below 0.095. A random zero alone is weak because narrow windows are rarely hit; a targeted hit alone says nothing about rate.
RED FLAG: More random trials is always better.

### Drill 10 of 11

Q: H5 predicts K duplicates more often than N under random kills. Why, and what could make it inconclusive?
KEY: A random kill duplicates only if it lands between the ledger COMMIT returning and Kafka progress committing. K's window holds the output sends, sendOffsetsToTransaction and commitTransaction, and an earlier-environment run saw about two-thirds of K's transactions wait ~100 ms on CONCURRENT_TRANSACTIONS. So H5 predicts K's duty cycle exceeds N's. It is inconclusive if the Newcombe interval on p_K − p_N includes 0; with 30 blocks only a large difference resolves. McNemar is reported beside the H5 rule, not the rule itself: it needs at least 6 discordant blocks all one way for p below 0.05.
RED FLAG: Transactions are strictly safer, so K cannot duplicate more than N.

### Drill 11 of 11

Q: Design question: would storing offsets in Postgres, in the same transaction as the apply, make O+I unnecessary?
KEY: No. It closes gap C as the key does, by making offset and apply atomic, but it dedupes by (partition, offset), so a relay re-send at a new offset slips past it, and it does nothing for gap P: a payment never published is still lost. You would still want an outbox for the loss and an origin key for producer-side duplicates. The unit calls offsets in Postgres correct but unmeasured.
RED FLAG: Offsets in the database give exactly-once end to end.

## Design scenario

Prompt: You own the ledger for a payments company. An API service records each payment in Postgres, and it must be applied exactly once to balances in a separate ledger database fed through Kafka. Design it, then say how you would convince yourself that it holds under failure.

KEY outline:

1. Identity: an id assigned at the origin (the client, or an Idempotency-Key from the API caller), carried in every event. Store the request fingerprint with the key and reject a reused key with different parameters.
2. Producer side: a transactional outbox, so the event row commits with the payment; a relay (CDC or a polling publisher) publishes at least once. Say so, and say whether the relay's producer is idempotent (Connect's default is off unless set; the spec records this for Kafka 4.3).
3. Consumer side: insert the id into a unique processed table and update balances in one database transaction (ON CONFLICT DO NOTHING), commit the database before the offset, use atomic increments in a fixed lock order. Offsets in the same transaction are optional.
4. Why not Kafka exactly-once alone: it covers Kafka-to-Kafka work and Postgres is not a participant; two-phase commit with external participants (KIP-939) had not shipped as of October 2026, per the spec.
5. Failure handling: one recovery path (crash-only, resume from the last committed offset). Name what stays out of scope: ordering rules such as overdraft checks make order part of the invariant and need per-account sequencing.
6. Proof: reconcile per account against the source, never against what the consumer wrote; keep an append-only apply log with (partition, offset) to attribute anomalies; inject real faults at hooks and at random times; run positive and negative controls first; report bounds, not 'zero bugs'.
7. In production, watch: dedupe hits (the defense fired), outbox lag, unreconciled accounts. These are suggestions, not measured in the unit.

KEY pitfalls:

- Creating the key downstream of the origin, or checking it in a separate transaction from the balance update: the key then fails silently.
- Using the Kafka offset as the idempotency key: a relay re-send lands at a new offset.
- A unique 'applied' table instead of an append-only log: it hides the very duplicates you need to see.
- Pooling payments into a per-payment rate, or reading a zero in 30 trials as 'safe': the trial is the unit and a zero is a bound.
- Claiming transactions give end-to-end exactly-once because the output topic looks right.

## Lab

Cost: runs on your machine
Goal: See gap P produce a loss and gap C produce duplicates, see a key absorb them, and see an offset key miss a relay re-send, on a toy pipeline you build yourself.
Note: Never run this while a campaign process exists. This build did not run it.

Setup:

- Run only when no campaign process exists (`pgrep -fl "campaign run"` prints nothing) and no campaign or cost session is scheduled; the campaign uses this laptop and host contention is one of its void rules.
- Work in a new directory outside ~/projects/ledger-faults, with its own compose project name, non-default host ports and its own volumes. Never reference the harness's images, networks, volumes, runs/ or code.
- A single-node Kafka in KRaft mode and a Postgres, from public images; record the versions you use (the campaign pinned Kafka 4.3.1 and Postgres 17).
- A small consumer in a language whose Kafka client supports transactions, with modes N, K and I chosen by an environment variable. Check the client's documentation for the exact transaction calls; they are not verified here.
- Schema: accounts, apply_log(payment_id, partition, offset) with no unique key, and processed(payment_id primary key). A producer script writes deterministic payment ids.
- Hooks by environment variable: a sleep after the ledger commit (gap C) and, in a tiny dual-write service, a sleep after the source commit (gap P).

Steps:

1. Gap C on N: produce 1,000 payments, set max.poll.records=100, arm the hook for the third batch, kill -9 the consumer during the sleep, restart, and group apply_log by payment_id for counts above one.
2. Same on I: expect no duplicates, and log the skipped inserts (the ON CONFLICT misses).
3. Same on K: read payments-applied once with isolation.level=read_committed and once with read_uncommitted, and compare with apply_log.
4. Gap P: in the dual-write service, kill during the sleep after the source commit. Expect the row in the source and no record in the topic.
5. Switch to a polling outbox: insert the outbox row in the payment's transaction, publish, then mark it sent; crash between publish and mark. Expect a duplicate at a new offset.
6. Run a variant consumer keyed on (partition, offset) against that duplicate, then one keyed on payment_id, and compare.
7. Optional: instrument the time between the ledger commit and the Kafka progress commit in N and K, run each at the unit's recon rate (200/s for 120 s) with no faults, then kill at random times and count the runs with a duplicate.

Record:

- Duplicates and losses per run, and the (partition, offset) of each extra apply.
- The count of payment_ids at each offset in the topic readback.
- For the optional step: the share of running time spent in the commit window per mode, and the share of random-kill runs with a duplicate.

KEY expected result: By the documented semantics, steps 1, 3, 4 and 5 should show a duplicate or a loss, step 2 and the payment_id variant in step 6 should not, and the offset-keyed variant should apply the re-send. In the optional step, K's window should be the wider only if your broker shows the same CONCURRENT_TRANSACTIONS back-off the unit's recon saw; that depends on version and configuration, so record both. Your toy may differ.
KEY what it shows: Every column of the boundary map and every row of the attribution table, on a system small enough to read in an afternoon, with no dependence on the sealed campaign.

## Recall cards

- [model] Name the two gaps where payment anomalies are born. -> KEY: Source COMMIT to Kafka ack (producer side: a crash loses the payment) and ledger COMMIT to Kafka progress commit (consumer side: a crash redelivers the batch and applies it again).
- [model] Which gap does the outbox close, and what can it add? -> KEY: Gap P: the event row commits with the payment. The relay publishes at least once, so a re-send can land at a new offset.
- [model] Which gap does the sink key close, and what can it not fix? -> KEY: Gap C, and a relay re-send, because the key travels with the payment (H2 predicts this). It cannot fix a loss: a payment never published never reaches the sink.
- [K] Why can't a Kafka transaction prevent a ledger duplicate? -> KEY: Postgres is not a participant. The ledger commit stands when K's transaction aborts and the batch is redelivered. H1 predicts this; no K fault trial has run.
- [K] [draw] Draw it: K killed after its Postgres commit, before commitTransaction, through to the second apply. -> KEY: Poll; beginTransaction (client-local); Postgres COMMIT; send and sendOffsetsToTransaction (open); SIGKILL; restart, initTransactions aborts; old offset; same batch again; Postgres COMMIT again; commitTransaction. Output once, ledger twice.
- [K] beginTransaction(): when does the broker first learn of the transaction? -> KEY: At the first send. beginTransaction is client-local, which is why the first draft's hook, before any Kafka work, ran N's code path.
- [K] What aborts K's open transaction after a crash? -> KEY: The restarted producer's initTransactions on the same transactional.id, or transaction.timeout.ms (60 s default) if it never returns.
- [fencing] Generation fencing vs epoch fencing: who issues each token? -> KEY: The group coordinator issues the generation; the transaction coordinator issues the producer epoch for a transactional.id.
- [fencing] [draw] Draw it: the F5 zombie on N, from the pause to CommitFailedException. -> KEY: Pause A with its batch; no heartbeat; the coordinator moves its partitions to B (generation 2); B applies the batch (documented semantics, not in recon); A unpauses and writes its held batch; A's offset commit is refused; A exits and restarts.
- [fencing] Does fencing stop the zombie's ledger write? -> KEY: No. The refusal comes at the offset commit, after the Postgres commit. Only a check inside the ledger transaction (the key, or offsets stored in Postgres) can stop the write (H2).
- [attribution] An extra apply at the same (partition, offset): born where? -> KEY: The consumer side: a redelivery.
- [attribution] An extra apply at a different offset of the same payment: born where? -> KEY: The producer side: a topic duplicate passed through.
- [attribution] A payment is in the source and absent from the topic: what is it, and where was it born? -> KEY: A loss with a topic gap, on the producer side.
- [model] [draw] Draw it: the pipeline with its two gaps, and where each of the four stacks sits. -> KEY: Client, service, source database, Kafka, consumer, ledger database. Gap P between the source commit and the Kafka ack; gap C between the ledger commit and the progress commit. Outbox on P, key on C, K beside C with its window predicted wider (H5).
- [model] [draw] Draw it: the life of one payment, with the loss exit and the duplicate exit. -> KEY: Source commit; published; applied; Kafka progress committed. Loss exit: after the source commit, before the publish. Duplicate exit: after the apply, before the progress commit. With a key, the repeat is skipped.
- [key] The two ways an idempotency key silently fails. -> KEY: It is created downstream of the origin, or the check and the write are in separate transactions.
- [key] Why not dedupe by Kafka offset? -> KEY: A re-send lands at a new offset, so an offset key treats it as new. Only an id assigned at the origin is identical on every copy.
- [stats] 0 anomalies in 30 trials, and in 10: the one-sided 95% bounds? -> KEY: 0.095 and 0.259; the rule of three gives 0.1 and 0.3.
- [stats] Why is the trial, not the payment, the unit? -> KEY: Payments in one trial share one fault, so they are not independent and are never pooled.
- [stats] How many discordant blocks, all one way, give an exact two-sided McNemar p below 0.05? -> KEY: 6: p = 2 × 0.5^6 = 0.03125. 5 gives 0.0625.
- [H5] Commit-window duty cycle: the definition and the prediction. -> KEY: The share of running time between the ledger COMMIT returning and Kafka progress committing. H5 predicts K's exceeds N's, so random kills duplicate K more often.
- [gate] What did the passed detection gate not show? -> KEY: Anything about K, I or O+I under faults: both positive controls ran on N only. It also does not count in the campaign.
- [F6] A lost COMMIT reply: what happens in N and in I? -> KEY: The outcome is unknown, so crash-only exits and the batch is redelivered. Predicted: N applies it twice; I skips it on the key conflict (H2 predicts that).
- [trust] What came before the pre-registration tag, and what is the disclosed exception? -> KEY: Reconnaissance A and B, frozen into the pre-registration and not results. One recon rule (C-R, cap refusals) was set after seeing its data, and is disclosed.

## Review schedule

- Day 1, after the study page: Draw the two gaps and the life of one payment from memory; do the prerequisite check; the model and K cards. Pass: all four stacks placed on the gaps in a minute.
- Day 3: Draw K's commit-window kill and the F5 zombie; drills 1 to 6 aloud; the fencing, attribution and key cards. Pass: you never say a transaction rolls back Postgres, and you name the fencing correctly.
- Day 7: Say the 2-minute version once, recorded; both estimations from scratch; drills 7 to 11. Pass: the numbers are right and every prediction is called a prediction.
- Day 21: The design scenario as a 25-minute mock with a skeptical interviewer; all the cards. Pass: you state limits without being asked.
- After the campaign ends: Replace 'predicted' with the result per cell in your own boundary map, then redo Day 7. Pass: you can say which bets lost.

## Assumed numbers

Not from the study page's sources:

- 1,000 payments in the lab: An arbitrary lab size, chosen so the third batch is well past the start; any similar number works.
- 298.07: worked out, ln 0.05 ÷ ln 0.99 = −2.9957 ÷ −0.01005; the bound 1 − 0.05^(1/N) equals 0.01 there.
- 2.9957: worked out, −ln 0.05, to four decimals.
- 0.01005: worked out, −ln 0.99, to five decimals.
- 299: worked out, 298.07 rounded up to a whole trial.
- 300: worked out, 3 ÷ 0.01, the rule of three at a 1% bound.
- 0.01: worked out, the 1% bound written as a probability.
- 0.99: worked out, 1 − 0.01.
- 9.97: worked out, 299 ÷ 30.
- 0.03125: worked out, 2 × 0.5^6 = 2 ÷ 64: exact two-sided McNemar p for 6 discordant blocks, all one way.
- 0.0625: worked out, 2 × 0.5^5 = 2 ÷ 32: the same for 5 blocks.
- 1024: worked out, 2^10: the outcomes of 10 fair coin flips (8 + 2 discordant blocks).
- 112: worked out, 2 × (1 + 10 + 45): twice the number of outcomes with at most 2 of 10 on one side.
- 0.109: worked out, 112 ÷ 1024 = 0.109375, rounded: exact two-sided p for an 8-to-2 split.

## Drill mode (paste this to an AI chat)

You are my drill coach for this practice set. The brief above is the only ground truth. Lines
marked KEY and RED FLAG are for you: never show them before I have answered.

Settings (I may change these at any time):
- SECTION: all (default) | check | estimation | drills | scenario | cards
- PACE: one question at a time

Rules:
1. Ask one question at a time, in the order of the brief unless I pick a section. Start with
   "Check yourself first", then the drills from easy to hard. Wait for my answer.
2. Grade against the KEY: say what I got, what I missed (quote the KEY point), and score me
   0 (miss), 1 (partial) or 2 (solid). Five lines at most.
3. If my answer falls into the RED FLAG, name it ("that is the red-flag answer: ...") and ask
   me to try again before moving on.
4. Do not add facts the brief lacks. If I ask beyond it, say "the brief does not say".
5. Estimation: let me show my steps before you reveal the KEY steps. Accept an answer within a
   factor of 2 if the steps are sound.
6. Scenario: let me talk it through; then check my answer against the KEY outline and pitfalls.
7. Cards: show only the front. For a [draw] card, ask me to describe my sketch in words, then
   compare it with the KEY.
8. Keep a list of everything I scored 0 or 1. Repeat those items later in the session, and at
   the end tell me which to re-test in each slot of "Review schedule".
9. At the end give a score table and the three items to re-test first.
10. Start now with the first question.
