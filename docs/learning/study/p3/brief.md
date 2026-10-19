# Delivery guarantees and duplicate payments: chat brief

## How to use this brief

Paste this whole file into an AI chat, then paste the prompt at the end (it is already the last section). Ask clarifying questions about anything below. About 20 minutes to study.

## Concepts

Used by: a6

- **At-least-once, and exactly-once effect**: **At-least-once**: a message may repeat, never be lost. Exactly-once *delivery* over a network that drops acknowledgements is impossible; systems give exactly-once **effect**: repeats made harmless. Think of it as: A courier who redelivers whenever unsure you signed: you never miss a parcel, sometimes you get two. Why it matters: A6's consumers are all at-least-once; dual-write producers can also lose. Its stacks, **N** (naive), **K** (Kafka transactions), **I** (key at the sink) and **O+I** (outbox plus key), differ in where, and whether, repeats are made harmless.
- **Offsets, committed after the work**: A consumer's progress in a partition is an **offset**: the next position to read. A6's consumers commit it only after their Postgres commit, so a crash in between means the batch is redelivered from the old offset. Think of it as: A bookmark moved only after you finish the chapter: fall asleep first and you reread the chapter. Why it matters: That gap is the **commit window**. Cell F4-con-t kills a consumer exactly there; on N it is the detection gate's planted duplicate.
- **Idempotent producer versus transactions**: An **idempotent producer** lets the broker drop a retried batch it already wrote, within one producer session; a restarted process or a relay re-sending is new to it. A Kafka **transaction** commits Kafka writes and consumer offsets atomically; Postgres is not a participant. Why it matters: So K can still apply a batch twice: die between its Postgres commit and `commitTransaction`, and the batch is redelivered while the Postgres commit stands. A6's H1 tests this.
- **Consumer groups, rebalances, zombies**: A group splits partitions among live members. One silent past `session.timeout.ms` loses them and a new **generation** starts; an offset commit from an old generation is rejected: **generation fencing**. A **zombie**, paused and woken with a batch in hand, can still write outside Kafka. Think of it as: A worker dozes off holding a task; it is reassigned. He wakes and finishes it anyway, and only his timesheet is rejected. Why it matters: Cell F5 makes one. In reconnaissance on N it wrote its batch to Postgres, then failed its offset commit, in all 17 F5 trials. On K, **epoch fencing** does not apply: each instance has its own `transactional.id`.
- **The dual write, and the outbox**: Commit the database, then send to Kafka: two commits in two systems. A crash or send timeout between them leaves a recorded payment never published. The **outbox** writes the payment and an 'event to publish' row in one transaction; a relay (Debezium, reading the database log) publishes it later, **at least once**. Think of it as: Diary, then a text to a friend: if the phone dies in between, the friend never hears. The outbox writes the text in the diary; a courier sends it, maybe twice. Why it matters: N, K and I dual-write; cell F4-svc kills the service right after its source commit. O+I's outbox moves duplicates downstream rather than removing them, so it still needs the key.
- **Idempotency key at the sink**: A unique `payment_id`, assigned at the origin, inserted into a `processed` table in **the same transaction** as the balance update: a repeat conflicts and is skipped. It breaks if the key is made downstream, or check and write are separate transactions. Think of it as: A ticket barcode printed at purchase and scanned at the gate: a second scan is refused. A barcode printed at the gate would defeat it. Why it matters: Why not dedupe by Kafka offset? A relay's re-send lands at a **new** offset; only a key carried from the origin catches it. I and O+I bet on this key.
- **Checking a history: ok, fail, info**: Jepsen-style, record each request as **ok**, **fail** (here: provably never reached the service) or **info** (a timeout or 5xx: may or may not have happened). With unique IDs and commuting increments, counting each ID in source, topic and apply log is a complete check. Think of it as: A payment page that timed out: the money may or may not have gone; only the statement says. Why it matters: A6's source database is the authority and resolves every info. The apply log keeps each apply's `(partition, offset)`: same offset means a redelivery, a new offset a re-send.
- **Real faults, and checking they landed**: **SIGKILL** ends a process with no cleanup. **`docker pause`** freezes it; it wakes unaware time passed. A Toxiproxy **blackhole** keeps a connection open and drops the bytes; disabling a proxy instead resets connections, which fail fast: a different fault. The seed fixes the **schedule**, not the outcome. Why it matters: A **manipulation check**, reading only orchestrator, broker and process state, confirms each A6 trial's fault took effect. A trial is void if not, and never because of what the checker found.
- **Positive and negative controls**: A zero means something only if the harness can see a nonzero. A **positive control** runs a case that must produce the anomaly; a **negative control**, one that must produce none. Think of it as: Testing a smoke alarm with test smoke before trusting its silence. Why it matters: A6's detection gate, run before the campaign, planted a duplicate and a loss on N only, ran no-fault trials on every stack and tested the checker on synthetic histories. It passed.

## Views

### Where a duplicate can enter (concept)

Two routes repeat a payment: the outbox relay re-reading after a crash, at a new offset, and redelivery to a restarted consumer, at the same offset. The producer's own retries are dropped by the broker. The key is checked last.

- **Client**: assigns payment_id at the origin
- **payment-service**: commits the source; sends in N, K, I
- **Kafka**: payments topic
- **Ledger consumer**: applies, commits Postgres, then its offset
- **source-db**: the payment's record: the authority
- **Outbox relay**: O+I only: Debezium
- **ledger-db**: balances, apply log; key in I, O+I
- Client → payment-service: HTTP
- payment-service → source-db: commit
- payment-service → Kafka: send: retries deduped
- source-db → Outbox relay: outbox rows
- Outbox relay → Kafka: re-send: new offset
- Kafka → Ledger consumer: redeliver: same offset
- Ledger consumer → ledger-db: apply, COMMIT

### One batch, two commits (concept)

Every A6 consumer commits Postgres, then its Kafka progress. A crash in between is the commit window: the ledger has the batch, the offset does not.

- **Poll a batch**: records with (partition, offset)
- **Apply in Postgres**: balances, apply log; key check in I, O+I
- **Postgres COMMIT**: the ledger now has the batch
- **Commit offset**: N, I, O+I: commitSync; K: commitTransaction
- **Crash in between**: ledger committed, offset not
- **Restart**: resumes at the last committed offset
- **Same batch again**: applied twice unless the key skips it
- Poll a batch → Apply in Postgres
- Apply in Postgres → Postgres COMMIT
- Postgres COMMIT → Commit offset: then
- Postgres COMMIT → Crash in between: SIGKILL
- Crash in between → Restart
- Restart → Same batch again: redelivered

## Recall questions

- Q: A consumer is killed after its Postgres commit but before its offset commit. What happens on restart?
  A: It resumes from the last committed offset, so the batch is redelivered and applied again: an extra apply at the same (partition, offset), unless the sink checks a key.
- Q: Why is a Kafka offset a bad idempotency key under an outbox relay?
  A: After a crash the relay re-reads and re-sends, and the copy lands at a new offset: to an offset key it is a new message. A key assigned at the origin is the same on every copy.
- Q: K commits its offsets inside a Kafka transaction. How can it still apply a payment twice?
  A: Its Postgres commit is outside the transaction. Die after it and before `commitTransaction`: the transaction aborts on restart, the batch is redelivered, the Postgres commit stands.
- Q: A zombie consumer wakes with a batch in hand. Which fencing stops it, and does that stop the duplicate?
  A: Generation fencing, at its offset commit. Its Postgres write is another system's commit and has already happened, so fencing stops the Kafka commit, not the ledger write.
- Q: Why is a timed-out request recorded as info, not fail?
  A: It may have reached the service and been recorded. Calling it fail would turn real deliveries into false anomalies; in A6 the source database resolves it, which a real client cannot do.
- Q: A cell shows zero duplicates. What must hold before that zero means anything?
  A: The checker must be able to see a duplicate (a positive control that produced one), and the fault must have taken effect in each trial (its manipulation check).

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
