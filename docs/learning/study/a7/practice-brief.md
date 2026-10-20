# Practice: the book, the sync and the pause: practice brief

## How to use this brief

Paste this whole file into an AI chat. The last section is the prompt that makes the chat quiz you; lines marked KEY and RED FLAG are the answers, hidden from you until you have tried. Practice for: The anatomy of a matching engine's tail. About 35 minutes.

## Objectives

- Trace five orders through a price-time book and state each trade price, each scan and why the price is the resting one.
- Say why replaying the sequenced input must reproduce the output hash, and name four things that would break it.
- For a stall of a given length at a given rate, count what a closed loop records against what an open loop scores.
- From one sync time, bound a D2 message's wait and a D3 ceiling, and say which inputs were measured.
- Decide whether G1 pauses reach the p99.99 by comparing total paused time with 0.01% of the window.
- State three things the study did not test: power loss, scans in the tail, a tuned JVM.

## Check yourself first

### Check 1

Q: A load generator sends the next request only when the last response arrives. What happens to its record of a 1 s stall?
KEY: It sends one request instead of the many that were due, so the stall is sampled once and the tail is under-reported. An open loop fixes send times in advance and scores latency from the intended time.
If missed, review: Coordinated omission

### Check 2

Q: What does write() guarantee that fdatasync() does not, and what does fdatasync() add?
KEY: write() puts bytes in the page cache: they survive a killed process, not a kernel crash or power loss. fdatasync() returns once the data is on stable storage; a drive with a volatile write cache must flush first.
If missed, review: Page-cache write, fdatasync, group commit

### Check 3

Q: Why can a single thread over a totally ordered input be replayed to the same state, and what could break that?
KEY: Its output depends on nothing but the input, so the same input gives the same state. Breakers: hash-ordered iteration, clock reads, floating-point prices, threads in the core.
If missed, review: Deterministic replay

## Estimation drills

### Estimate 1: The durability budget: D2's tail, H3a and D3's ceiling

Problem: At 20,000/s the ungated p99.99 (D1) is 1.39 µs. One in-pipeline fdatasync has median 23.5 µs and p99.99 48.4 µs; a batch write takes 0.55 µs; fio's isolated median is 14.66 µs. Estimate (a) a range for D2's p99.99, (b) the least D2 over D1 and whether H3a (under 2.00x) could hold, (c) D3's ceiling, (d) whether D3 can serve 100,000/s.

KEY steps:

1. (a) A gated message waits for the rest of the sync in flight (0 to S), then its batch's write (0.55 µs) and its batch's whole sync (S): between S and 2S + 0.55 µs.
2. With S from 23.5 µs (median) to 48.4 µs (p99.99): about 24 µs to 97.4 µs (2 x 48.4 + 0.55 = 97.35). Measured D2 p99.99: 72.1 µs, inside the range. A rough bracket, not a prediction.
3. (b) Any gated reply waits for a whole sync: even fio's 14.66 µs gives D2 / D1 >= 14.66 / 1.39 = 10.5. H3a needs under 2.00x: S + 0.55 write under 2 x 1.39 = 2.78 µs, so S under 2.23 µs (2.78 if the write is ignored). No sync measured is that fast. Measured: 52.0x.
4. (c) Ceiling = 1 / time per order. Fio's median gives 1 / 14.66 µs = 68,200/s, an overestimate: the median sits below the mean, and it ignores the write and the hand-offs. Fio's write IOPS (57,264 on h2; 1 / IOPS = 17.5 µs, a write-plus-sync cycle, not a mean sync latency) gives about 57,000/s.
5. Measured: saturated D3 forks sustained 23,929 to 23,979/s: about 41.8 µs per order (1 / 23,929), 35% of 68,200. Why is not separated.
6. (d) At 100,000/s the offered work is 100,000 x 41.8 µs = 4.18 s per second; even at fio's median it is 1.47. It saturates: the backlog grows by about 76,000 orders a second. Observed: saturated on all three hosts, in no test.

KEY answer: D2 p99.99 between about 24 and 97 µs (measured 72.1). D2 is at least 10.5 times D1, so H3a could not hold. fio's median puts D3's ceiling near 68,200/s (an overestimate); D3 reached 23,929/s, so 100,000/s saturates.

### Estimate 2: The pause budget: how many G1 pauses reach the p99.99?

Problem: Queue + park at E1: a G1 pause lasts about 2.5 ms (medians 2.49 to 2.68 ms). The window is max(60 s, 2,000,000 messages): 200 s at 10,000/s, 60 s at 100,000 and 500,000/s. How many pauses per window put one at the p99.99, and what do 1, 2 and 5 to 7 pauses at those rates give?

KEY steps:

1. Arrivals are evenly spread, so a pause of length L delays about rate x L messages (a floor: the backlog after it adds more).
2. The p99.99 rank is 0.01% of the window's messages: 0.0001 x rate x T. n pauses reach it when rate x L x n > 0.0001 x rate x T.
3. The rate cancels in this inequality: n x L > 0.0001 x T. It still matters through n: higher rates produced more pauses per window here (1, 2, 5 to 7). A 60 s window needs more than 6 ms of pause in total; a 200 s window, more than 20 ms.
4. At 2.5 ms: 60 s needs 3 pauses (two give 5 ms, under 6 ms); 200 s needs more than 8.
5. Data: 10,000/s, 1 pause of 2.68 ms: about 27 vs rank 200, no. 100,000/s, 2 pauses: about 500 vs 600, short of it; 9 of 30 launches had queue + park over 100 µs. 500,000/s, 5 to 7 pauses: about 7,500 vs 3,000, yes; 30 of 30.

KEY answer: A pause shows at p99.99 once total paused time exceeds 0.01% of the window: 6 ms per 60 s. Pause count and length decide it; higher rates produced more pauses here (1, 2, 5 to 7), so the rate acts through the count. The ring arms had no pauses. Arithmetic and a floor; post hoc.

## Deep-dive drills

Ordered easy to hard.

### Drill 1 of 12

Q: A buy limit order crosses two ask levels. Walk through what FastEngine does.
KEY: It takes the best ask level and fills the oldest order there first, at the resting order's price. A fully filled maker is unlinked and its pool node freed. When a level empties, the best ask moves to the next non-empty level by scanning outward. When the limit stops crossing, any remainder rests at the back of its own level. Cost follows the orders and levels touched (walkthrough 2, seq 20).
RED FLAG: "It finds the best matching order": no FIFO, no resting-price rule; or a sorted map that allocates per order, with no thought for the cost of touching levels.

### Drill 2 of 12

Q: Why does the matcher run on one thread? Isn't that a bottleneck?
KEY: One writer needs no locks and applies messages in one total order, so replaying the journal rebuilds the same state and the output hash shows it. Throughput scales by sharding symbols across engines, which the money view assumes; the study did not run shards. At a median match_service of 80 ns (D2, 20,000/s), one thread is not this workload's limit.
RED FLAG: A lock per book and several matching threads, with no answer for a deterministic order or for replay.

### Drill 3 of 12

Q: Your generator waits for each response. A 10 ms stall hits at 100,000/s. What does it record, and what should it?
KEY: It records one slow request; 1,000 were due (100,000 x 0.010 s). An open loop scores all 1,000 from their intended send times; if evenly spaced, the slowest 100 wait over 9 ms. So a closed loop can hide about 1,000 messages, 1% of that second's 100,000. Bridge: wrk2's README says it measures from when each request was due and that wrk's model suffers coordinated omission.
RED FLAG: "Run it longer" or "add client threads": still a closed loop, so a stall is still sampled once per connection.

### Drill 4 of 12

Q: Ring or ArrayBlockingQueue: what actually differs, and what did the study measure?
KEY: The ring is a preallocated array with one writer per sequence counter: publish with a release store, consume with an acquire read, counters padded against false sharing; with busy-spin, no lock (the blocking strategy enters a monitor per publish), no allocation (spec Module 7). The queue has one lock for both ends, and a thread that must wait allocates a wait node and parks. Measured: the ring arms allocated nothing; the queue + park matcher thread allocated about 32 B per voluntary context switch at 10,000/s.
RED FLAG: "The ring is lock-free, so it is always faster." At 10,000/s a parking ring (5.32 µs) was slower than a spinning queue (4.08 µs).

### Drill 5 of 12

Q: Group commit amortises the sync. Why is D2's p99.99 about 52 times D1's?
KEY: Amortising helps throughput, not the wait: every gated reply waits for at least one whole sync, plus the rest of the one in flight if it arrives mid-sync. Even fio's 14.66 µs against D1's 1.39 µs is 10.5 times; the pipeline's median sync was 23.5 µs. 52.0x is this setup at 20,000/s, not a property of group commit.
RED FLAG: "Group commit makes durability nearly free."

### Drill 6 of 12

Q: Spin or park a hand-off: how do you decide?
KEY: Parking added about 1.7 µs per hop at the median at 10,000/s (ring match wait 0.18 to 1.92 µs), and spinning keeps cores busy: three of six, $0.205/h per host here. Spin when microseconds have a price and cores are free; park otherwise. At 500,000/s the parking ring's p99.99 was 5.56 µs, so parking was not what hurt there. Bridge: CUDA's runtime offers spin, yield and blocking-sync device flags for the same trade.
RED FLAG: "Always spin", or "parking is free", with no price on the core.

### Drill 7 of 12

Q: D1 never waits for disk. What exactly can go wrong, and what would fix it?
KEY: A response can leave before its order is in the page cache, so a killed JVM loses an answered order: 3 of 10 laptop kills at D1 failed the crash check. Gating release on the write would cover a process crash, since the page cache survives a killed JVM (the post's reasoning; not run here). fdatasync adds kernel-crash and power-loss safety, which the study could not test.
RED FLAG: "The page cache makes it durable", with no crash model.

### Drill 8 of 12

Q: A 2.68 ms G1 pause at 10,000/s did not show in the queue + park arm's 6.13 µs p99.99. Why?
KEY: A p99.99 registers a pause only when the messages it delays outnumber 0.01% of the window. One pause delays about 27 messages (a floor) against a rank of 200 in 2,000,000. Same test in time: total paused time must exceed 0.01% of the window, 20 ms in a 200 s window; one 2.68 ms pause is far under.
RED FLAG: "There was no pause."

### Drill 9 of 12

Q: At 500,000/s the queue's p99.99 was about 2 ms. Is that the queue or the GC?
KEY: Both, and the split is post hoc. The allocation is structural (the queue's waiters allocate; the ring arms allocated nothing); the pause length is partly configuration (one G1 thread on a shared core). By arithmetic, 5 to 7 pauses of about 2.5 ms delay about 7,500 messages against a rank of 3,000. Verdicts are unchanged; a tuned JVM was not tested.
RED FLAG: "Java is slow", or blaming the queue's algorithm with no rank arithmetic.

### Drill 10 of 12

Q: Fio says a sync takes 14.66 µs, so D3 should reach 68,200/s. It saturated near 23,900. What do you say?
KEY: 1 / median overestimates: capacity is 1 / mean service time, the sync's median sits below its mean, and it ignores the write and the hand-offs. Fio's 17.5 µs is 1 / its write IOPS, a write-plus-sync cycle, not a mean sync latency (about 57,000/s). The saturated forks took about 41.8 µs per order, 35% of the ceiling. Why the pipeline is slower than fio was not separated; interrupts on the journaler's core are a candidate, untested.
RED FLAG: "Fio was wrong", or no capacity reasoning.

### Drill 11 of 12

Q: A tail message overlaps a safepoint. Is the safepoint its cause?
KEY: Not on overlap: slow messages overlap more of everything because they last longer. Credit a cause when it covers at least 50% of the message's excess over the fork's median, inside its busy period, and compare with a null: the event timeline shifted 200 times. Publish what no cause covers: the residual was 6.66% to 10.1% of tail messages at D0 and D1.
RED FLAG: "It overlapped, so yes."

### Drill 12 of 12

Q: You ran 2,000,000 messages. Why not trust that run's own interval on p99.99?
KEY: Messages from one JVM share its JIT decisions, memory layout and host, so they are not independent. Same-seed launches differed 5.64 to 8.90 times more than one run's error implies (H4). The launch is the unit; intervals go over rounds, per host and pooled.
RED FLAG: Bootstrapping the 2,000,000 messages.

## Design scenario

Prompt: Design the order-entry path for a venue with 400 symbols and 300,000 messages/s at peak. An acknowledged order must survive the loss of one host, and the ack p99.99 target is 500 µs. What do you build, what do you measure first, and what would change your design?

KEY outline:

1. Shape: shard symbols across independent single-writer matchers; each shard has a sequencer (a seq per message), a journal beside the matcher, and release gated by the durable sequence number, never by a clock. The study ran one shard; sharding was assumed, not measured.
2. Surviving a host loss means a replicated journal: acknowledge after a replica has persisted. The study measured only local syncs (23.5 µs median here, far worse on a drive with a volatile write cache); the replica round trip is the next study's question, not a number you may quote.
3. Hand-offs: preallocated rings; spin only where microseconds pay for the cores. Verify no allocation on the hot path by method (per-thread allocated bytes, an Epsilon-GC cell), not by assumption.
4. Capacity: per shard, utilisation = rate x time per order; use mean service time, not the median; keep the durability stage well below saturation (D3 saturated at 100,000/s here).
5. Measure first: open-loop at Poisson and at bursty rates, one clock per host, per-stage percentiles up to what the sample supports (at least 100 samples above), tail attribution with a published residual, repeated launches across hosts.
6. What would change it: a sync distribution that is slow or bimodal in place; GC pauses reaching the rank; a network round trip that dominates the budget.

KEY pitfalls:

- Benchmarking closed loop, or reporting a p99.99 from too few samples.
- Claiming power-loss safety from a kill-the-JVM test: the study's crash check tests process crashes only.
- Quoting 1 / median sync as capacity, or fio's sync time as the in-pipeline one.
- Gating release on wall-clock time instead of a sequence number, or letting a hash-ordered map, a clock read or a float price into the matcher.
- Treating synthetic Poisson load on thin books as real order flow.

## Lab

Cost: runs on your machine
Goal: Run the engine's own order book on the five walkthrough orders, count the empty slots each scan skips, and check that the book and a reference engine agree.
Note: No paid API, GPU or cloud. Reads the study's repo; modifies nothing in it.

Setup:

- JDK 25 (the study used Temurin 25.0.4.1); any recent JDK should compile these files.
- A scratch folder OUTSIDE ~/projects/matching-engine-tail. Copy the 13 files of engine/src/main/java/mtail/engine/ into it. Never build inside the study's repo.
- In the copy of FastEngine.java, add a counter to the two scan loops in unlink() (one for bids, one for asks) and print it.

Steps:

1. Write a Trace class: one FastEngine on Band.standard(), an ExecutionSink that prints fills and cancel acks, and messages built as OrderMsg (type, seq, orderId, symbol 0, side, priceTicks, qty).
2. Setup orders, seq 16 to 19: SELL S1 5 at 10,002; SELL S2 3 at 10,002; SELL S3 10 at 10,004; BUY B1 4 at 9,999.
3. Then seq 20: BUY B9 10 at 10,004; 21: SELL S4 6 at 10,004; 22: CANCEL S3; 23: BUY B10 7 at 10,004; 24: SELL S5 3 at 9,999. Compile with javac and run.
4. Compare the fills, the cancel ack and the scan counts with walkthrough 2 (1, 2,044 and 4 empty slots at seq 20, 23, 24).
5. Feed the same nine messages to ReferenceEngine, folding both engines' events into an OutputHash each; the two hashes and bookStateHash() values must match.
6. Move S3 to 12,000 and rerun: seq 20 now fills S1 and S2 only, and the scan after the 10,002 level empties grows to the whole gap. Then time many repeats of one order that empties the best level, next level 1 tick away against far away (warm up first).

Record:

- Fills and cancel acks per message
- Empty slots skipped per scan
- Equal or unequal output hashes, FastEngine against ReferenceEngine
- Nanoseconds per apply, near against far next level (your machine only)

KEY expected result: A prediction, not run for this page: the fills, prices and scan counts match walkthrough 2, which was produced with the same method; the two engines' hashes are equal; the far-level case takes longer per call than the near one. Your nanoseconds are not comparable with the study's, and nothing here shows whether scans reach the study's measured tail.
KEY what it shows: The book's rules, that scan cost follows empty slots, and that two independently written engines must agree on every event: the idea behind the hash gate.

## Calculator

A sync time, the D2 bracket and the D3 ceiling Defaults are measured in this study (S = the median in-pipeline sync at 20,000/s, 23.5 µs). Arithmetic bounds, not a queueing model. S = 48.4 (p99.99) gives the slow end, but a tail value overstates utilisation. D3 reached 35% of the fio-based ceiling: read it as an overestimate.

Inputs (default, range):

- Sync time S: 23.5 µs (range 1 to 2000)
- Batch write time: 0.55 µs (range 0.1 to 50)
- Ungated p99.99 (D1): 1.39 µs (range 0.5 to 10)
- Offered rate: 20000 /s (range 1000 to 200000)

Outputs at the defaults:

- D2 least: S + write = 24.05 µs  [sync + write]
- D2 most: 2S + write = 47.55 µs  [2 * sync + write]
- D2 over D1, at least = 17.3 x  [(sync + write) / base]
- S that would meet H3a = 2.23 µs  [2 * base - write]
- D3 ceiling, 1 / (S + write) = 41,580 /s  [1000000 / (sync + write)]
- D3 utilisation at the rate = 0.48  [rate * (sync + write) / 1000000]

## Recall cards

- [book] Price-time priority in one sentence? -> KEY: Best price first; at the same price, the oldest order first.
- [book] At what price does a crossing trade execute? -> KEY: The resting (maker) order's price: in walkthrough 2, seq 24 sells with a limit of 9,999 and trades at 10,004.
- [book] FastEngine's book layout? -> KEY: Per symbol and side, an array of price levels (4,097: reference +-2,048 ticks), each a FIFO of pooled order nodes; an id-to-node map for cancels; best bid and ask kept as indices; integer ticks; nothing allocated. A price outside the band is rejected.
- [book] [draw] Draw the book after seq 20 and after seq 23 of walkthrough 2. -> KEY: After seq 20: asks 10,004 [S3 8]; bids 9,999 [B1 4]. After seq 23: no asks; bids 10,004 [B10 1] and 9,999 [B1 4].
- [book] What does emptying the best level cost, and what is not known? -> KEY: A scan outward to the next non-empty level: up to the band's edge, 2,044 empty slots at seq 23. Whether such scans show in the measured match tail was not tested.
- [determinism] What breaks replay determinism in the engine's rules? -> KEY: Wall-clock reads, hash-ordered iteration, hashCode dependence, threads inside the matcher, randomness not from the seed, floating-point prices (spec 4.3).
- [determinism] Sequencer, journal, replay: how do they fit, and what is the bridge? -> KEY: The sequencer fixes the order, the journal records it, replay rebuilds the state: state-machine replication without consensus (spec Module 2). A Raft-replicated state machine has the same shape with consensus agreeing the order.
- [co] Closed against open loop: which under-reports, and what is the HTTP bridge? -> KEY: Closed loop: a stall is sampled once. Open loop scores from the intended time. wrk2 (-R) is the open-loop fork of wrk, per its README.
- [co] 100,000/s and a 10 ms stall: closed against open? -> KEY: Closed records 1 slow request; open scores all 1,000 due, the slowest 100 over 9 ms if evenly spaced.
- [co] [draw] Draw a closed-loop and an open-loop client across a stall. -> KEY: Closed: one request waits, nothing else is sent. Open: sends stay on the schedule and each is scored from its intended time, so the due ones pile up as slow samples.
- [samples] How many messages before p99.99 may be reported? -> KEY: At least 100 samples above it: n x (1 - q) >= 100, so 1,000,000 messages for p99.99 and 10,000 for p99. Here 2,000,000 leave 200 above p99.99.
- [ring] What makes a one-producer ring with busy-spin lock-free and allocation-free? -> KEY: Preallocated slots; one writer per sequence counter; release store to publish, acquire read to consume; counters on separate cache lines (spec Module 7). With the blocking wait strategy, each publish enters a monitor.
- [ring] [draw] Draw an 8-slot ring with the producer at sequence 11 and the consumer through 3. Can sequence 12 be published? (toy numbers) -> KEY: No. Sequence 12 reuses slot 4, still holding unconsumed sequence 4 (12 - 8 = 4 > 3). The producer waits: spin, or park.
- [queue] Why does queue + park allocate even with no contention? -> KEY: A take on an empty queue waits on a condition. At 10,000/s the matcher thread allocated 62,375,392 B over 1,947,577 voluntary context switches: about 32.0 B per park, consistent with a wait node per park (JDK internals not read here).
- [wait] Cost of parking against spinning, and the GPU bridge? -> KEY: About 1.7 µs per hop at the median at 10,000/s; spinning three of six cores is $0.205/h per host. CUDA's spin and blocking-sync device flags are the same trade (CUDA runtime docs).
- [gc] Why does an allocation-free thread still stop for GC? -> KEY: A G1 pause is a global safepoint: every Java thread stops, so the generator and the ring consumers wait too.
- [gc] When does a pause reach the p99.99? -> KEY: When the messages it delays exceed 0.01% of the window: total paused time over 0.01% of the window, 6 ms per 60 s. At 10,000, 100,000 and 500,000/s: 27 against 200, 500 against 600, 7,500 against 3,000 (floors).
- [durability] What survives what: write against fdatasync? -> KEY: write: a killed JVM, not a kernel crash or power loss. fdatasync: all three, on drives that honour it; check the volatile-write-cache bit (VWC 0 here). Kafka's default posture is the page-cache one (D1), per the post; not checked in Kafka's docs.
- [durability] [draw] Draw one D2 message from arrival to release. -> KEY: Arrives mid-sync A; waits; journaler drains batch B, write, one fdatasync, stores durableSeq; Output, spinning on durableSeq, releases it. Up to about two syncs.
- [durability] Why could H3a (D2 under 2.00x D1) not hold? -> KEY: A gated reply waits for a whole sync: even 14.66 µs against 1.39 µs is 10.5 times. Measured: 52.0 times. The rule was fixed at design approval and kept.
- [capacity] D3's ceiling: formula, and what was measured? -> KEY: 1 / mean service time per order. Fio's median gave 68,200/s (an overestimate); the saturated forks sustained 23,929/s, about 41.8 µs per order.
- [attribution] Share against credit? -> KEY: Share: the fraction of a message's latency spent in a stage (H1). Credit: a cause covers at least 50% of the message's excess over the median, counted per message (H6).

## Review schedule

- Day 1, after the page: Draw the container view from memory; redo walkthrough 2 for seq 20 and 24 on paper; cards 1 to 10.
- Day 3: Cards 11 to 22 out loud; redo the 10 ms stall and the pause budget (estimation 2) closed book; drills 1 to 6.
- Day 7: Estimation 1 from the prompt only; drills 7 to 12; the lab if not yet run.
- Day 21: The 2-minute pitch timed; the design scenario in 20 minutes; interview mode in brief.md as a skeptic, deep.

## Assumed numbers

Not from the study page's sources:

- 400: Scenario parameter chosen for the exercise: the number of symbols. Not from the study.
- 300,000: Scenario parameter chosen for the exercise: peak messages per second. Not from the study.
- 500: Scenario parameter chosen for the exercise: the ack p99.99 target in microseconds. Not from the study.
- 9,999 10,004 12,000 10,002: Prices of the made-up toy book in walkthrough 2 and the lab, in integer ticks around the reference price 10,000. Not from a run of the campaign.
- 10.5: worked out, 14.66 / 1.39 = 10.55: fio's median sync over D1's 20,000/s p99.99 (the post, durability section).
- 14.66: worked out, recon.md: fio fdatasync p50 14,656 ns on h2, in microseconds to two decimals.
- 97.35: worked out, 2 x 48.4 + 0.55 = 97.35 microseconds.
- 97.4: worked out, 97.35 rounded to one decimal.
- 2.78: worked out, 2 x 1.39 = 2.78 microseconds.
- 17.5: worked out, 1 / 57,264 IOPS = 17.46 microseconds: fio's write IOPS inverted, a write-plus-sync cycle, not a mean sync latency (recon.md, h2).
- 41.8: worked out, 1 / 23,929 per second = 41.79 microseconds per order.
- 4.18: worked out, 100,000 x 41.8 microseconds = 4.18 seconds of work per second.
- 1.47: worked out, 100,000 x 14.66 microseconds = 1.466 seconds of work per second.
- 68,200: worked out, 1 / 14.656 microseconds = 68,231 per second, rounded as the unit does.
- 57,000: worked out, 1 / 17.5 microseconds = 57,100 per second; fio reported 57,264 IOPS (recon.md, h2), about 57,000.
- 76,000: worked out, 100,000 offered - 23,929 sustained = 76,071 per second, about 76,000.
- 0.0001: worked out, 0.01% as a fraction.
- 2.5: worked out, The G1 pause length used in the estimation: the medians were 2.49 to 2.68 ms (the post).
- 7,500: worked out, 6 pauses x 2.5 ms x 500,000 per second = 7,500 messages (the post's own arithmetic).
- 32.0: worked out, 62,375,392 B / 1,947,577 voluntary context switches = 32.03 B (results-a7.md 11.4, E1-ABQ_PARK-D1-10000, matcher thread).
- 1.7: worked out, 1,923.5 - 180.0 = 1,743.5 ns at the median (results-a7.md 6, ring match_wait, 10,000/s).
- 0.18: worked out, results-a7.md 6, E1-RING_SPIN-D1-10000 match_wait p50 180.0 ns.
- 1.92: worked out, results-a7.md 6, E1-RING_PARK-D1-10000 match_wait p50 1923.5 ns.
- 4,097: worked out, 2 x 2048 + 1, Band.levels().
- 2,044: worked out, Empty slots the seq 23 scan skips, confirmed by running FastEngine with a counter in a scratch copy.
- 1,000: worked out, 100,000 per second x 0.010 s.
- 1,000,000: worked out, n x (1 - q) >= 100 with q = 0.9999 gives n >= 1,000,000.
- 10,000: worked out, n x (1 - q) >= 100 with q = 0.99 gives n >= 10,000.
- 62,375,392: worked out, results-a7.md 11.4 allocated_bytes_delta, matcher, E1-ABQ_PARK-D1-10000.
- 1,947,577: worked out, results-a7.md 11.4 voluntary_cs_delta, matcher, E1-ABQ_PARK-D1-10000.
- 2.23: worked out, 2 x 1.39 - 0.55 = 2.23 microseconds: the sync that would meet H3a once the batch write is counted.

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
