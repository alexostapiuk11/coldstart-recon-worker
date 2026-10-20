# The anatomy of a matching engine's tail: chat brief

## How to use this brief

Paste this whole file into an AI chat, then paste the prompt at the end (it is already the last section). Ask clarifying questions about anything below. About 45 minutes to study.

Read first: How these experiments earn trust (P2).

## Why it exists

**Question:** Under open-loop load on commodity hardware, where do a deterministic Java matching pipeline's slowest 0.01% of messages spend their time, how much do the hand-off design and the durability policy move that tail, and how much of it is the JVM launch and the host? Three rented bare-metal servers, one JVM per run, no network; nothing comparable to kernel-bypass or FPGA systems.

**Requirements that drove everything:**

- Credit each message in a run's slowest 0.01% to measured causes, test inferred causes against a null, and publish what no cause covers as a residual. *Why:* A search of public writing found latency trees with no distributions (Coinbase) and engines that exclude journaling (exchange-core), not an attributed p99.99 with its blind part named.
- Score every message from its intended send time on a schedule fixed in advance, with every stamp from one host's clock and no network. *Why:* A generator that waits for responses under-samples stalls (coordinated omission); stamps from different clocks cannot be subtracted.
- E1 swaps only the `Channel` (all three hand-offs at once); E2 swaps only the `Durability`, its hand-off fixed at ring + busy-spin in advance. *Why:* Then any difference comes from that one object; picking E2's hand-off from E1's winner would make the design depend on data.
- Commit H1 to H6 with thresholds and decision rules, plus exclusion, stopping and headline rules, before the first campaign fork. *Why:* Six of eight verdicts came out fails or mixed; only a timestamped pre-registration (P2: prereg) shows they were not chosen after the campaign's data.
- The JVM launch on one host is the unit: contrasts within rounds, intervals (P2: interval) over rounds, per host and pooled. *Why:* Messages from one JVM share its JIT decisions, memory layout and host; an interval over them looks tight and means little.
- Every fork: replay reproduces the live output hashes, and at D2 and D3 no response leaves before its order is durable; host settings read back every round. *Why:* A fast wrong engine, a leaky gate or a silently reverted setting would void every latency number.

## Need to know first

- **Coordinated omission, open versus closed loop**: **Closed loop**: send the next request when the last response arrives. During a stall it sends one request instead of the many that were due, so the stall is sampled once and the tail under-reported (Gil Tene named this). **Open loop**: send times are fixed in advance and latency runs from the **intended** time, so a generator that falls behind counts against the system.
- **HdrHistogram and what a p99.99 rests on**: p99.99 (P2: percentiles): the latency 99.99% of messages stay at or under. **HdrHistogram** keeps 3 significant digits over a huge range and merges without loss. A percentile is reported only with at least 100 samples above it: 2,000,000 messages leave 200 above p99.99 but 20 above p99.999, so this study reports nothing past p99.99.
- **The Disruptor ring, the queue, and wait strategies**: **Ring buffer**: a preallocated array with sequence counters; one producer and one consumer allocate nothing; with busy-spin they take no lock (the blocking strategy enters a monitor per publish). `ArrayBlockingQueue`: one lock for both ends; a thread that must wait (lock held, or an empty queue in the park arm) enqueues a wait node (allocates) and parks. **Wait strategy**: what an idle consumer does, **busy-spin** (poll in a loop, burning a core) or **park** (sleep until woken).
- **Page-cache write, fdatasync, group commit**: `write` lands in the **page cache**: it survives a killed JVM, not a kernel crash or power loss. `fdatasync` returns once data is on stable storage; a drive with a volatile write cache must flush first (these report none, VWC 0). **D0** no journal; **D1** page-cache write, response not gated; **D2** group commit: up to 4,096 entries per `fdatasync`; **D3** one `fdatasync` per order.
- **JVM safepoints and G1 pauses**: Some JVM operations stop **every** Java thread: GC pauses, some deoptimisation. So a thread that allocates nothing still stops when another thread's allocation triggers a collection; a **handshake** acts on one thread without stopping the rest. Here: G1 with one GC thread on the housekeeping core. The generator stops too, but latency runs from the intended time, so the stop counts.
- **Deterministic replay and the hash gate**: One thread over a totally ordered input, depending on nothing else: replaying the input rebuilds the same state. Breakers: hash-ordered iteration, clock reads, floating-point prices, threads in the core; the engine has none. The matcher's rolling output hash, checkpointed every million sequence numbers, must reappear when a fresh matcher replays the journal.
- **Tail attribution against a shifted null**: **Excess**: a tail message's latency minus the fork's median. **Busy period**: back to when the in-flight count last rose above its median. A cause is credited if it covers **at least 50% of the excess**: durability wait and matcher path from the message's own stamps; safepoints and **sentinel gaps** (idle polls over 5 µs apart) by time in the busy period, checked against a **null** of 200 circular shifts. Credits are non-exclusive; uncredited is **residual**.

## How it works

One order, m, arrives mid-sync at D2 (ring + busy-spin). The path is from the code; each timing is a separate stage percentile from the 20,000/s cell, not a trace of m. Stage values do not sum to the end-to-end median.

| Step | What happens | Journaler (core 4) | Order m | durableSeq vs m | Output (core 5) | Measured at 20,000/s |
|---|---|---|---|---|---|---|
| 1 | Gateway decodes m, gives it a seq and fans it out. The journaler is already inside `fdatasync` for batch A, which began before m arrived. This is the case to follow: m lands mid-sync. (Decision: Journal beside the matcher; release gated by sequence number) | fdatasync of batch A | sequenced, fanned out | below m | waiting for m | no number: the setup |
| 2 | The match branch is quick: `match_service` median is 80 ns. Output takes m from the matcher, then spins re-reading `durableSeq` until it reaches m's seq. It is below, so m is matched but held. | fdatasync of batch A | **matched, held by Output** | below m | **spinning: durableSeq < m** | **match_service p50: 80 ns** |
| 3 | On the journal side m sits in its channel: the journaler is one thread, inside the sync, so it cannot drain. `journal_wait` p99 is 38.2 µs here, 0.27 µs at D1. That fits this wait; the data does not isolate it. | fdatasync of batch A | **queued, journaler busy** | below m | spinning: durableSeq < m | **journal_wait p99: 38.2 µs** |
| 4 | Sync A returns and the journaler stores `durableSeq` = A's last seq: still below m, so Output keeps spinning. The journaler drains everything queued in one snapshot, up to 4,096: batch B, m among it. | **draining batch B (m inside)** | **in batch B** | **A's last: still below m** | spinning: durableSeq < m | **batch cap: 4,096 (the code)** |
| 5 | One `write()` puts all of B in the page cache. Written is not durable: a page-cache write survives a killed JVM, not power loss. `journal_write` median is 0.55 µs. | **write() of batch B** | **in the page cache** | A's last: still below m | spinning: durableSeq < m | **journal_write p50: 0.55 µs** |
| 6 | Then one `fdatasync` for the whole batch. m waits all of it, and every message in B shares this sync's end as its durable time. Per sync, not per message: median 23.5 µs, p99.99 48.4 µs. (Decision: Sweep durability where per-order sync can keep up) | **fdatasync of batch B** | **waiting on B's sync** | A's last: still below m | spinning: durableSeq < m | **sync p50 23.5, p99.99 48.4 µs** |
| 7 | The sync returns and the journaler stores `durableSeq` = B's last seq, after the stamps. Output now reads a value at least m's seq, stamps RELEASED and m leaves. m paid the rest of A's sync, a write and B's sync. | **back to its channel** | **released** | **B's last: at least m** | **released m** | **e2e p99.99, D2: 72.1 µs** |
| 8 | At D1 Output never spins on `durableSeq`, so the journal side stops mattering to the response. The journal still writes beside the matcher, but nothing waits for it: end-to-end p99.99 is 1.39 µs. | **write() only, nobody waits** | **released when matched** | **not read at D1** | **releases at once** | **e2e p99.99, D1: 1.39 µs** |

Bold cells changed in that step.

**Takeaway:** A D2 message pays its own batch's sync, plus the rest of the one in flight if it arrives mid-sync: up to about two syncs. D2's 72.1 µs p99.99 is about 1.5 times the 48.4 µs p99.99 sync (arithmetic, not a breakdown).

## System views (C4)

### One fork: five threads, three swapped channels (container)

One JVM per fork, one thread per isolated core. The wire ring is fixed; E1 swaps the three `Channel`s, E2 the `Durability`. Output releases when matched and, at D2 and D3, once the durable sequence reaches the order: latency is the slower branch, not the sum.

- **Generator (core 1)**: Poisson schedule, on time
- **Gateway (core 2)**: decode, sequence, fan-out
- **Matcher (core 3)**: 8 books, price-time
- **Output (core 5)**: releases; D2, D3 wait
- **Stream file**: 45M frames, pre-encoded
- **Journaler (core 4)**: Durability D0 to D3
- **Core 0 housekeeping**: OS, movable IRQs, GC, JIT
- **Journal file**: own drive, pre-written
- Stream file → Generator (core 1): frames
- Generator (core 1) → Gateway (core 2): wire ring (fixed)
- Gateway (core 2) → Matcher (core 3): Channel
- Gateway (core 2) → Journaler (core 4): Channel
- Matcher (core 3) → Output (core 5): Channel
- Journaler (core 4) → Output (core 5): durable seq
- Journaler (core 4) → Journal file: write, fdatasync

### Inside the attribution instrument (component)

The host post-processes the stamps after each window; tail rows, histograms and event logs come home. The non-exclusive credit matrix decides H6; the exclusive bars are for the figure only.

- **Stamp store**: every stage, every message
- **Post-processor**: on host: tail, busy start
- **Tail rows**: at or above p99.99
- **Excess, busy period**: latency minus median
- **Sentinels**: idle polls over 5 µs apart
- **Credit rules**: a cause covers half the excess
- **JVM logs**: safepoints, same clock
- **Credit matrix**: shares + residual; H6
- **Shifted null**: safepoints, gaps; 200 shifts
- **Exclusive bars**: first cause; figure only
- Stamp store → Post-processor
- Post-processor → Tail rows: rows
- Tail rows → Excess, busy period
- Excess, busy period → Credit rules
- Sentinels → Credit rules: gaps
- JVM logs → Credit rules: overlap
- JVM logs → Shifted null: shifted
- Shifted null → Credit matrix: chance level
- Credit rules → Credit matrix
- Credit matrix → Exclusive bars

### One message, generator to response (dynamic)

1 to 6 run inside the fork; 7 is the score; 8 runs after the window. Steps 4 and 5 run side by side; at D0 and D1 the output never waits for 5.

- **1 Due at its time**: generator stamps intended
- **2 Onto the wire ring**: stamped just before write
- **3 Decode, sequence**: gateway fans out
- **4 Match**: price-time; stamp matched
- **5 Journal it**: D2 batch sync; D3 own sync
- **6 Release**: D2, D3 wait for durable seq
- **7 Score it**: released − intended
- **8 Check the fork**: replay hashes; gating
- 1 Due at its time → 2 Onto the wire ring
- 2 Onto the wire ring → 3 Decode, sequence
- 3 Decode, sequence → 4 Match: Channel
- 3 Decode, sequence → 5 Journal it: Channel
- 4 Match → 6 Release: Channel
- 5 Journal it → 6 Release: durable seq
- 6 Release → 7 Score it
- 7 Score it → 8 Check the fork: after the window

### Who and what the study touches (context)

The laptop builds and tests, never produces data. Three rented hosts run the campaign; each host's second NVMe drive holds only the journal.

- **Laptop**: build and tests; never data
- **Prior art**: LMAX, Tene, Yoon
- **Author**: designs, pre-registers
- **Matching-engine tail**: Java pipeline, Python analysis
- **Reader**: platform, trading-firm engineers
- **Vultr bare metal ×3**: EPYC 4245P, six cores
- **Journal NVMe drive**: one per host; VWC 0
- Author → Matching-engine tail: designs, runs
- Matching-engine tail → Reader: post + data
- Laptop → Matching-engine tail: tested code
- Prior art → Matching-engine tail: methods credited
- Matching-engine tail → Vultr bare metal ×3: 840 forks
- Vultr bare metal ×3 → Journal NVMe drive: write, fdatasync

## Core decisions

### Journal beside the matcher; release gated by sequence number

**Problem:** The journal must sit somewhere relative to matching, and the queue and the ring must be swappable in the same places.

**Options considered:**

- LMAX multicast: one ring, matcher and journaler consuming the same slots
- Serial write-ahead: gateway, journal, matcher, output in a line
- Symmetric channels: the gateway fans out to matcher and journaler at every level; output waits for both at D2 and D3

**Chosen:** Symmetric channels: the gateway fans out to matcher and journaler at every level; output waits for both at D2 and D3

**Why:** `ArrayBlockingQueue` cannot multicast, so a multicast ring would give the queue arms another topology, not one swapped object. Serial write-ahead puts durability on the path and inflates its penalty. Beside the matcher, latency is the slower branch, and D0 keeps the fan-out, so D0 against D1 isolates the journal I/O.

**Cost:** At D0 and D1 a response can leave before its order reaches the page cache, so a process crash can lose an answered order (3 of 10 laptop kills at D1 failed the crash check). Power loss was not tested.

### Open-loop from a fixed schedule, stamped in one clock

**Problem:** A tail is only as honest as where its clock starts.

**Options considered:**

- Closed loop: send the next order when the response arrives
- Closed-loop demonstration cells beside the open-loop ones
- A Poisson schedule fixed before the run; latency from the intended send time; every stage stamped by one host's clock

**Chosen:** A Poisson schedule fixed before the run; latency from the intended send time; every stage stamped by one host's clock

**Why:** Closed loop is coordinated omission; demonstration cells were cut for build hours, with Tene cited instead. Stamps on one message make each stage a subtraction, in one host's clock. Frames are pre-encoded, so the generator encodes nothing in the window.

**Cost:** Full stamping added 134–139 ns at the median and 141–166 ns at p99.99 in one calibration cell (exploratory), not netted out. Generator lag includes wire-ring backpressure. No network is measured.

### Split the hand-off into structure and wait strategy

**Problem:** The 2011 Disruptor paper does not say which wait strategy its run used, so its ring-versus-queue gap cannot be split into structure and waiting.

**Options considered:**

- Ring against queue only, the original framing
- Pick E2's hand-off from E1's winner
- A 2×2: `ArrayBlockingQueue` or Disruptor ring, each parking or spinning, same slots and capacity (4,096), at three rates

**Chosen:** A 2×2: `ArrayBlockingQueue` or Disruptor ring, each parking or spinning, same slots and capacity (4,096), at three rates

**Why:** Only a 2×2 splits the gap. **Structure includes its lock**: the queue's lock and wait nodes allocate, and a waiting thread parks, even in the spin arm when two threads collide, so that is measured per thread, not removed. E2 stays at ring + busy-spin whatever E1 shows.

**Cost:** The park arms differ by construction: a ring + park producer facing a full ring sleeps about 50 µs of timer slack; a queue + park producer is signalled. One queue tested. Spinning keeps three of six cores busy: $0.205/h per host.

### Sweep durability where per-order sync can keep up

**Problem:** One `fdatasync` per order caps D3 near one order per sync, so at E1's rates D3 would saturate everywhere.

**Options considered:**

- One rate set for both experiments
- Make D3's saturation a hypothesis
- D0 to D3 at 5,000, 20,000 and 100,000/s; D3's ceiling stated as arithmetic; a recon rule for slow drives

**Chosen:** D0 to D3 at 5,000, 20,000 and 100,000/s; D3's ceiling stated as arithmetic; a recon rule for slow drives

**Why:** The senior review found one rate set left D3 saturated at every hypothesis rate. By arithmetic, 1 ÷ fio's median put D3's ceiling, an upper bound, near 68,200/s, between 20,000 and 100,000. A pre-written journal makes `fdatasync` flush data, not allocation metadata.

**Cost:** Sizes are drive-specific. Saturated D3 forks sustained 23,929–23,979/s, 35% of the arithmetic, and the pipeline's median sync (23.5 µs) sat above fio's 14.7 µs, unexplained. NVMe interrupts land on the journaler's core. Power loss untested.

### Credit causes by coverage of the excess, against a shifted null

**Problem:** Slow messages overlap more of everything because they last longer, so overlap alone proves nothing.

**Options considered:**

- Credit a cause whenever it overlaps a tail message
- One exclusive precedence order, used for the tests too
- Independent credits for causes covering at least 50% of the excess; a shifted null; a published residual

**Chosen:** Independent credits for causes covering at least 50% of the excess; a shifted null; a published residual

**Why:** The design review found overlap biased by each message's length, messages queued behind an ended stall filed as "queueing", and precedence partly deciding H6. Coverage of the excess removes most length bias, busy periods catch the queued messages, independent credits keep order out of tests. Planted cases were recovered before any real bundle.

**Cost:** At D0 and D1, 6.66%–10.1% of tail messages stayed residual. Sentinels see gaps only between idle polls, so the gap null is a lower bound. Handshakes are uncredited (their log lines name no thread). One safepoint can also count as a gap.

### The launch is the unit; intervals over rounds

**Problem:** A fork holds millions of messages, so an interval from them is tiny and assumes they are independent.

**Options considered:**

- Intervals over the messages of one long run
- A percentile bootstrap over the ten rounds
- Resampling forks across rounds
- Launches as the unit: 10 rounds × 28 forks × 3 hosts, contrasts within rounds, intervals over rounds, same-seed replicates

**Chosen:** Launches as the unit: 10 rounds × 28 forks × 3 hosts, contrasts within rounds, intervals over rounds, same-seed replicates

**Why:** Messages in one JVM share its JIT decisions, layout and host. Same-seed replicates change only the launch (H4). A round is one host in one stretch of time, paired (P2: pairing). With ten blocks a percentile bootstrap of a median under-covers; resampling across rounds breaks the pairing.

**Cost:** Hosts share each round's seed, so the 30 blocks are not independent, and the intervals (2nd and 9th of ten values, 97.9%) are coarse. H5 is descriptive; generalising rests on n = 3 hosts.

## Relationships

**Requirements and the decisions that meet them:**

- R1: Credit each message in a run's slowest 0.01% to measured causes, test inferred causes against a null, and publish what no cause covers as a residual.
  - `attr` Credit causes by coverage of the excess, against a shifted null: Independent credits, a null for inferred causes, the residual published.
- R2: Score every message from its intended send time on a schedule fixed in advance, with every stamp from one host's clock and no network.
  - `open` Open-loop from a fixed schedule, stamped in one clock: Latency from the intended time; every stamp one host's `nanoTime`.
- R3: E1 swaps only the `Channel` (all three hand-offs at once); E2 swaps only the `Durability`, its hand-off fixed at ring + busy-spin in advance.
  - `topo` Journal beside the matcher; release gated by sequence number: One `Channel` type at every hand-off, and D0 keeps the fan-out.
  - `e1` Split the hand-off into structure and wait strategy: All three channels swap together; E2's hand-off was fixed before E1 ran.
  - `e2` Sweep durability where per-order sync can keep up: Four `Durability` implementations behind one interface.
- R4: Commit H1 to H6 with thresholds and decision rules, plus exclusion, stopping and headline rules, before the first campaign fork.
  - `e2` Sweep durability where per-order sync can keep up: Rates, recon rule and D3's arithmetic were written down before the campaign.
  - `attr` Credit causes by coverage of the excess, against a shifted null: The 50% rule, the 5 µs gap and the null were fixed before any host ran.
  - `unit` The launch is the unit; intervals over rounds: Pooling, interval and each decision rule were committed first.
- R5: The JVM launch on one host is the unit: contrasts within rounds, intervals (P2: interval) over rounds, per host and pooled.
  - `unit` The launch is the unit; intervals over rounds: Every interval is over rounds or launches, never messages.
- R6: Every fork: replay reproduces the live output hashes, and at D2 and D3 no response leaves before its order is durable; host settings read back every round.
  - `topo` Journal beside the matcher; release gated by sequence number: Release waits on the durable sequence, checked by sequence number on every message. No decision covers the per-round host read-back.

**Decisions and the concepts they use:**

- `topo` Journal beside the matcher; release gated by sequence number uses Deterministic replay and the hash gate: The journal holds the sequenced input that replay rebuilds from.
- `topo` Journal beside the matcher; release gated by sequence number uses Page-cache write, fdatasync, group commit: Where the journal sits decides whether a sync is on the response path.
- `open` Open-loop from a fixed schedule, stamped in one clock uses Coordinated omission, open versus closed loop: The fixed schedule exists to defeat coordinated omission.
- `open` Open-loop from a fixed schedule, stamped in one clock uses HdrHistogram and what a p99.99 rests on: Each stage's distribution is a per-fork HdrHistogram.
- `e1` Split the hand-off into structure and wait strategy uses The Disruptor ring, the queue, and wait strategies: The factors are structure (ring, queue) and wait strategy (spin, park).
- `e1` Split the hand-off into structure and wait strategy uses JVM safepoints and G1 pauses: The queue allocates wait nodes, so its arms meet G1 pauses.
- `e2` Sweep durability where per-order sync can keep up uses Page-cache write, fdatasync, group commit: The four levels are four write-and-sync policies.
- `attr` Credit causes by coverage of the excess, against a shifted null uses Tail attribution against a shifted null: This decision is the attribution method.
- `attr` Credit causes by coverage of the excess, against a shifted null uses JVM safepoints and G1 pauses: Safepoints are an inferred cause the null tests.
- `unit` The launch is the unit; intervals over rounds uses HdrHistogram and what a p99.99 rests on: Each fork contributes one p99.99, resting on at least 200 samples.

**Results and the decisions they support:**

- Who owns the tail, by durability level → `attr` Credit causes by coverage of the excess, against a shifted null, `e2` Sweep durability where per-order sync can keep up
- Hand-off p99.99 against load: ring or queue, spin or park → `e1` Split the hand-off into structure and wait strategy
- Group commit and per-order sync against the page-cache write → `e2` Sweep durability where per-order sync can keep up
- Every pre-registered verdict, as it came out → `unit` The launch is the unit; intervals over rounds
- One run's precision against launch-to-launch spread (H4) → `unit` The launch is the unit; intervals over rounds
- EXPLORATORY, POST HOC: when do the queue's G1 pauses reach the p99.99? → `e1` Split the hand-off into structure and wait strategy

## Implementation flow

10 steps in 5 phases, 5 milestones.

Milestones: 1. Specify, get it reviewed, approve (2026-10-08 (−07:00)); 6. Pre-register and tag (2026-10-10 11:24 (−07:00)); 7. Run 840 forks on three hosts (2026-10-10 to 10-11 (UTC)); 8. Analyse, then rank before drafting (2026-10-11 (−07:00)); 10. Pass the pre-publish gate (2026-10-11 to 10-18 (−07:00)).

### Phase 1 of 5: Design (1 step)

1. **Specify, get it reviewed, approve** [MILESTONE]: First spec, a senior review (approve with fixes: E2's rates, attribution against a null, the queue's lock as structure), revision 3 approved, four plans.
   - Output: the approved design: H1–H6 with thresholds and decision rules, before any host was rented
   - When: 2026-10-08 (−07:00)
   - Decision: `attr` Credit causes by coverage of the excess, against a shifted null
   - Evidence: c829d008da in ~/projects/matching-engine-tail (first spec); 90cbf1dba0 in ~/projects/matching-engine-tail (revision 2 after review); f48ba453fa in ~/projects/matching-engine-tail (approved, revision 3)

### Phase 2 of 5: Build offline (3 steps)

2. **Build the engine and pipeline on the laptop**: Engine with a differential test against a reference engine; four `Channel` kinds; four durability levels; stamps; post-processor. Laptop runs are not data; a D1 crash check failed 3 of 10 kills, so D1's check became informational.
   - Output: engine and pipeline, 390 tests green; laptop runs at five rates (not data)
   - When: 2026-10-08 to 10-09 (−07:00)
   - Decision: `topo` Journal beside the matcher; release gated by sequence number
   - Evidence: 011d333429 in ~/projects/matching-engine-tail (plan 1 exit); e751cd54c2 in ~/projects/matching-engine-tail (D1 not crash-safe)
3. **Amendment 1, before any host**: Plan 1 showed the design silent or wrong in places: the tail's tie rule, the busy period, the queue + spin lock-park row, timeouts. Hypotheses unchanged.
   - Output: a dated amendment (P2: amendment) approved before any host was rented; laptop runs, which are not data, prompted it
   - When: 2026-10-09 (−07:00)
   - Decision: `attr` Credit causes by coverage of the excess, against a shifted null
   - Evidence: a62454e8d4 in ~/projects/matching-engine-tail (amendment 1)
4. **Finish the analysis on planted cases**: Attribution, the shifted null and H1–H6 in code, recovering a planted stall, null event, backlog echo and slow match. Plan 2's laptop round: D3 timed out on macOS.
   - Output: mtail/: every verdict computed from synthetic bundles before any real bundle
   - When: 2026-10-09 (−07:00)
   - Decision: `unit` The launch is the unit; intervals over rounds
   - Evidence: af66b995b2 in ~/projects/matching-engine-tail (four planted cases); 5ed0a641fd in ~/projects/matching-engine-tail (plan 2 exit)

### Phase 3 of 5: Reconnoitre and pre-register (2 steps)

5. **Rent the hosts; reconnaissance on h1**: turbostat found boost not capped (cores near 5.4 GHz); NVMe names swapped across a reboot: both fixed. fio: about 14.7 µs per sync. Single forks per rate on h1, not data; the D3 probe at 100,000/s saturated near 23,900/s.
   - Output: docs/recon.md: 23 of 23 read-back checks on three hosts, three deviations, recon rule keeps 5,000/s
   - When: 2026-10-09 to 10-10 (−07:00)
   - Decision: `e2` Sweep durability where per-order sync can keep up
   - Evidence: f84c0b8c8f in ~/projects/matching-engine-tail (journal by drive serial); 8c9a0bde82 in ~/projects/matching-engine-tail (boost off); 6a06617c90 in ~/projects/matching-engine-tail (D3 probe saturates)
6. **Pre-register and tag** [MILESTONE]: Hypotheses from the design, amendment 1, recon outcomes and three deviations, approved; code pinned. Tagged after the recon forks, 3 min 41 s before the first campaign fork.
   - Output: docs/experiment.md at tag `a7-prereg`; no amendment since
   - When: 2026-10-10 11:24 (−07:00)
   - Decision: `unit` The launch is the unit; intervals over rounds
   - Evidence: ea1240011e in ~/projects/matching-engine-tail (tag a7-prereg, 18:24:42Z)

### Phase 4 of 5: Measure (1 step)

7. **Run 840 forks on three hosts** [MILESTONE]: 28 forks per round, 10 rounds per host in seeded orders, read-back before every round. No stop, no host-check failure, no fork re-run.
   - Output: 840 forks, 0 failed, 30 saturated (exactly D3 at 100,000/s, as predicted); hosts destroyed after
   - When: 2026-10-10 to 10-11 (UTC)
   - Decision: `e1` Split the hand-off into structure and wait strategy
   - Evidence: c6fa16a23e in ~/projects/matching-engine-tail (launched 18:28Z); 17b2e52949 in ~/projects/matching-engine-tail (data committed)

### Phase 5 of 5: Analyse and publish (3 steps)

8. **Analyse, then rank before drafting** [MILESTONE]: analysis.json, byte-identical across two runs; every verdict copied into results-a7.md; the headline ranked by the pre-registered rule before any draft.
   - Output: data/a7/analysis.json and docs/results-a7.md: H2 leads, H4 never leads
   - When: 2026-10-11 (−07:00)
   - Decision: `unit` The launch is the unit; intervals over rounds
   - Evidence: a83741b1d7 in ~/projects/matching-engine-tail (analysis.json); ee30b86bd2 in ~/projects/matching-engine-tail (results-a7.md); e1c2794a62 in ~/projects/matching-engine-tail (headline ranking)
9. **Draft, review, add the post hoc GC check**: Prior-art claims checked first. Review: the queue's load dependence is partly G1 pauses crossing the p99.99 rank, and "met" means the median launch; added as post hoc.
   - Output: docs/post.md and data/a7/exploratory-gc.json, labelled post hoc; no verdict changed
   - When: 2026-10-11 (−07:00)
   - Decision: `e1` Split the hand-off into structure and wait strategy
   - Evidence: 21dc73aac3 in ~/projects/matching-engine-tail (S and U claims checked); cb9b36192c in ~/projects/matching-engine-tail (draft); 9598a22ccb in ~/projects/matching-engine-tail (G1 pauses, post hoc)
10. **Pass the pre-publish gate** [MILESTONE]: Honesty constraints line by line, number drift test, byte-identical re-analysis and figures, tag before first fork. README and LICENSE tripped the pinned-code guard; fixed.
   - Output: every controller check passes; final bill, post URL and licence holder deferred by the owner
   - When: 2026-10-11 to 10-18 (−07:00)
   - Decision: `e2` Sweep durability where per-order sync can keep up
   - Evidence: 5072c8ae75 in ~/projects/matching-engine-tail (controller checks); 6e291d89ea in ~/projects/matching-engine-tail (gate passed); 25b0bb8d95 in ~/projects/matching-engine-tail (merged)

## Results as meaning

### Who owns the tail, by durability level

- Axis: Host h1, ring + busy-spin, 20,000/s, about 2,000 tail messages per level over 10 forks. Each message goes to its first credited cause in a fixed order, for the figure only; h2 and h3 look the same.
- Read it as: No sync on the path: the match stage and its queue are the tail. At D3 and 20,000/s, arrival burst was also credited on 100%, a tie the bars hide.
- How it is computed: results-a7.md §8.2 as percent. Non-exclusive matcher-path credit at D0 and D1: 89.1%–93.1%. Engine service alone: 35.1%–45.1% of a 1.39 µs tail.
- D0 no journal: Matcher path 91.8, Host hiccup 0.3, Residual 7.9 (% of tail messages, first credited cause)
- D1 page cache: Matcher path 90.1, Host hiccup 0.3, Residual 9.6 (% of tail messages, first credited cause)
- D2 group commit: Durability wait 100 (% of tail messages, first credited cause)
- D3 per-order sync: Durability wait 100 (% of tail messages, first credited cause)
- Changed D1 → D2: An fdatasync enters the response path: durability wait takes the whole tail, and p99.99 goes from 1.39 to 72.1 µs.
- So: see decisions `attr`, `e2`

### Hand-off p99.99 against load: ring or queue, spin or park

- Axis: E1 at D1, 30 forks per point over three hosts. H2's D: the wait strategy's effect minus the structure's, in log p99.99; D > 0 means waiting matters more.
- Read it as: 10,000/s: spinning 1.43 and 4.08 µs, parking 5.32 and 6.13; waiting matters more (D +0.257, holds). 500,000/s: the queue arms jump to milliseconds (D −5.957, fails). 100,000/s: mixed. No arm saturated.
- How it is computed: Post "Ring or spin?" table; 2.16 and 2.02 ms drawn as 2,160 and 2,020 µs. D's 97.9% intervals: +0.176 to +0.282, −0.128 to +0.052, −5.996 to −5.813.
- Axes: x is offered rate, messages/s (log scale); y is p99.99, all hosts' forks (µs); log y
- ring + busy-spin: 10000: 1.43 (1.42 to 1.45), 100000: 1.39 (1.38 to 1.41), 500000: 1.53 (1.52 to 1.55)
- ring + park: 10000: 5.32 (5.27 to 5.38), 100000: 5.15 (5.12 to 5.18), 500000: 5.56 (5.53 to 5.58)
- queue + busy-spin: 10000: 4.08 (4.04 to 4.13), 100000: 5.5 (5.33 to 5.79), 500000: 2160 (1980 to 2220)
- queue + park: 10000: 6.13 (5.66 to 6.52), 100000: 8.09 (7.78 to 12.8), 500000: 2020 (1950 to 2280)
- Note: Whiskers: 95% interval over 30 forks.
- So: see decision `e1`

### Group commit and per-order sync against the page-cache write

- Axis: E2, ring + busy-spin, ratios within a round on one host. Pooled p99.99 at 20,000/s: 1.39 µs at D1, 72.1 at D2, 197 at D3; D0 and D1 overlap.
- Read it as: Both refs are pre-registered predictions. Group commit sits about 50× above the page-cache write: H3a fails at both rates, on every host. Per-order sync is over 10×: H3b holds.
- How it is computed: 72.1 ÷ 1.39 = 51.9; the reported 52.0× is e to the median within-round log ratio. D3 at 100,000/s saturated, as arithmetic said, and is in no test.
- Axes: x is offered rate, messages/s (log scale); y is p99.99 ratio to the page-cache write (× D1's p99.99)
- D2 group commit ÷ D1 (points): 5000: 44.9 (44.4 to 46.0), 20000: 52.0 (50.0 to 53.6)
- D3 per-order sync ÷ D1 (points): 5000: 65.0 (64.1 to 66.9)
- Reference: H3a predicted D2 under 2.00× at y = 2 × D1's p99.99
- Reference: H3b predicted D3 over 10.0× at y = 10 × D1's p99.99
- Note: Whiskers: 97.9% interval over ten rounds.
- So: see decision `e2`

### Every pre-registered verdict, as it came out

- Axis: Eight verdicts (H3 and H6 have two parts), each by its pre-registered rule. Default: holds if the pooled interval supports it and all hosts agree; fails if it contradicts it; else mixed.
- Read it as: Fails: H1, H2 (holds, mixed, fails by rate), H3a, H6b (0 of 12 pairs). Mixed: H5; H6a (9 of 12, misses tied with arrival burst). Holds: H3b, H4.
- How it is computed: Post "Every verdict, as it came out"; results-a7.md §4. 72 of 75 (host, cell) pairs eligible; the rest are D3 at 100,000/s.

| verdicts | Predicted | Came out |
|---|---|---|
| H1 (matching is small) | under 10.0% of latency, every cell [pre-registered prediction] | fails: 56.7%–60.5% at D0, D1 [observed, fails] (service only 35.1%–45.1%; 0.127%–0.393% at D2 and D3) |
| H2 (waiting beats structure) | wait moves p99.99 more, every rate [pre-registered prediction] | fails: D +0.257, −0.095, −5.957 [observed, fails] (holds at 10,000/s, mixed at 100,000/s, fails at 500,000/s) |
| H3a (group commit near D1) | D2 within 2.00× of D1 [pre-registered prediction] | fails: 44.9× and 52.0× [observed, fails] (at 5,000/s and 20,000/s) |
| H3b (per-order sync is costly) | D3 over 10.0× D1, lowest rate [pre-registered prediction] | holds: 65.0× [observed, holds] (at 5,000/s) |
| H4 (the launch is the unit) | launch spread over 2.00× run error [pre-registered prediction] | holds: 5.64×, 8.90×, 5.87× [observed, holds] (h1, h2, h3) |
| H5 (hosts differ more at D2) | between-host share larger at D2 [pre-registered prediction] | mixed: 0.00323%–9.07% [observed, mixed] (range at every level and rate) |
| H6a (durability wait leads) | credited most at D2 and D3 [pre-registered prediction] | mixed: 9 of 12 pairs met [observed, mixed] (the three misses are ties with arrival burst) |
| H6b (no cause over half) | none credited over half, D0, D1 [pre-registered prediction] | fails: met in 0 of 12 pairs [observed, fails] |

- Note: Four fail, two mixed, two hold.
- So: see decision `unit`

### One run's precision against launch-to-launch spread (H4)

- Axis: D1 at 100,000/s. Each round, three extra same-seed forks ran back to back: same code, input and host. Bar: SD of log p99.99 across them ÷ the error one fork implies if its messages were independent.
- Read it as: Launches differed by about 2–3% at p99.99 (SD 0.0175–0.0279), several times one run's own error, on all hosts: H4 holds.
- How it is computed: results-a7.md §4.5: h1 0.0175 ÷ 0.00311 = 5.64. That launches differ in JIT and memory layout is the author's reading, not tested.
- h1: 5.64 × within-run standard error
- h2: 8.9 × within-run standard error
- h3: 5.87 × within-run standard error
- pre-registered threshold: 2 × within-run standard error
- So: see decision `unit`

### EXPLORATORY, POST HOC: when do the queue's G1 pauses reach the p99.99?

- Axis: E1's queue arms. Counted after the analysis: every in-window safepoint there was a G1 allocation pause, median 2.49–2.68 ms; the ring arms had none.
- Read it as: A p99.99 registers a pause once the messages it delays outnumber 0.01% of the window: not at 10,000/s, nearly at 100,000/s, far past at 500,000/s. Measured: queue + park over 100 µs in 0, 9 and 30 of 30 launches.
- How it is computed: Pauses per window, queue + park: 1, 2, 5–7. Ring arms: 0 of 180 launches over 100 µs. At 100,000 and 500,000/s, 97.2%–99.1% of the queue arms' gap time lies inside pauses.
- Axes: x is offered rate, messages/s (log scale); y is messages per window (messages); log y
- due during G1 pauses (arithmetic) (points): 10000: 27, 100000: 500, 500000: 7500
- p99.99 rank: 0.01% of the window (points): 10000: 200, 100000: 600, 500000: 3000
- Note: Arithmetic, not measurement: rate × pause length × pauses, per window. It counts only messages due during the pauses, so it is a floor. Changes no verdict.
- So: see decision `e1`

## Interview card

**30-second pitch:** I built a deterministic Java matching engine, ran it open-loop as one in-process pipeline on three rented bare-metal servers, and attributed its slowest messages to causes, with rules fixed before the campaign. The lead finding: which hand-off decision sets the tail depends on load. At low load, spinning versus parking matters more than ring versus queue; at 500,000 messages a second the queue's tail goes to milliseconds while the ring's stays in single microseconds. And once an fdatasync is on the response path, waiting for it is the whole tail.

**2-minute version:** In 2011 the Disruptor paper showed a ring beating a queue, but not whether that was the data structure or the consumer spinning instead of sleeping. I built a deterministic Java matching engine, eight order books behind a sequencer and a journal, as one pipeline of five pinned threads, driven open-loop from each message's intended send time. Two experiments: ring or `ArrayBlockingQueue` crossed with spin or park, and four durability levels from no journal to an fdatasync per order. Six hypotheses pre-registered, 840 JVM launches on three hosts, tail messages attributed against a shifted null with the residual published. Most predictions did not hold, and those are the findings. At 10,000 messages a second waiting mattered more than structure; at 500,000 the queue went to about two milliseconds while the spinning ring stayed at 1.53 µs, and a post hoc count, with arithmetic, puts G1 pauses across the p99.99 rank. With no sync on the path the match stage is the tail; with one, durability wait is all of it, and group commit came out 52 times the page-cache write here, against a predicted under 2. And same-seed JVM launches differed several times more than one run's interval admits.

**Hard follow-ups:**

- Q: Your queue's millisecond tail at 500,000/s: is that the queue, or your one-GC-thread collector setup?
  A: Both. The allocation is structural: the queue's lock and wait nodes allocate (a thread that finds the lock held, or an empty queue in the park arm, enqueues a node and parks), while the ring arms' stages allocated nothing. The pause length is partly configuration: one G1 thread on a core shared with the OS and JIT. The breakdown is post hoc (every queue-arm safepoint a G1 allocation pause, medians 2.49 to 2.68 ms). A better-tuned JVM was not tested.
- Q: Why `ArrayBlockingQueue` at all? Does "ring beats queue" still mean anything?
  A: It is the queue the 2011 comparison used, and the question was structure against waiting, with the lock counted as structure. So the claim is ring against `ArrayBlockingQueue`, one JDK, one collector. No lock-free, non-allocating queue was tested; I would not claim the ring beats queues in general.
- Q: Your drives sync in about 15 µs. What does that tell me about my hardware, and what did you test about power loss?
  A: Only the direction transfers. fio's isolated sync median was about 15 µs on drives that report no volatile write cache, but inside the pipeline the median sync took 23.5 µs, for reasons not separated. One published measurement: 1,643 µs on a consumer drive with a write-back cache, 24 µs on an enterprise one. Check the write-cache bit. Power loss was not tested: the crash check kills the JVM, which tests process-crash safety only, and at D1 a pass is timing.
- Q: The workload is synthetic, Poisson and thin. Which conclusions move with real order flow?
  A: Not tested; a planned sequel uses an IEX-fitted workload. Arrivals were Poisson on purpose, since bursts would confound the rate factor, and the books are thin, about 264 resting orders over 8 symbols. The matcher's cost depends on how many levels a crossing order touches, so matcher-path numbers depend on book shape.
- Q: How much of what you measured is your own instrumentation?
  A: Stamping cost 134–139 ns at the median and 141–166 ns at p99.99 in one calibration cell, exploratory and not netted out, large against a 1.39 µs tail. Logs are synchronous. Sentinels see gaps only between idle polls, handshakes are uncredited, and 6.66%–10.1% of the ungated tail is residual.
- Q: How do you know the rules came before the data?
  A: The hypotheses and their thresholds are in the design approved 2026-10-08, before any host was rented. Amendment 1 changed definitions, not hypotheses, before any host ran; laptop runs (not data) prompted it. Reconnaissance's single forks on h1 (not data) had shown D2's p99.99 at 71,416 ns against D1's 1,417 ns and D3 saturating near 23,900/s; H3a (within 2.00×) was kept, and the pre-registration records this. Tag 18:24:42Z on 2026-10-10, first campaign fork 18:28:23Z, no amendment since.

**Limits (what I must not claim):** Three hosts of one server type and one provider, identical journal drives: n = 3. Synthetic workload, thin books, Poisson arrivals, no fills. In-process, no network. One JDK and one collector (G1, one GC thread); one queue. Process crash tested, not power loss. D3's arithmetic is not a measurement (35% reached). Coarse money: three rates, the median launch; a 1.00× tax means invisible to the grid. Attribution floor: the residual, sentinel blind spots, lower-bound nulls, uncredited handshakes; a pause can also count as a gap. Stamp cost and synchronous logs not netted out. The GC breakdown is post hoc.

## Recall questions

- Q: Why does a closed-loop load generator under-report the tail, and where does this pipeline start each message's clock?
  A: It waits for each response, so a stall is sampled once instead of once per message that was due. Here the schedule is fixed first and latency is released minus intended, so a late generator counts against the system.
- Q: Why does the gateway fan out to the journaler even at D0, and what contrast does that make clean?
  A: So D0 and D1 differ only in the journal I/O (D0 consumes and discards). On these hosts the write cost nothing visible: 1.38 against 1.39 µs at 20,000/s.
- Q: At D2, what does a response wait for, and how is "no response before durable" checked without trusting clocks?
  A: The match and the journaler's durable sequence reaching its own. The output records the durable sequence it saw at release; every message must show one at least its own sequence number.
- Q: An `ArrayBlockingQueue` polled in a spin loop: how can it still park, and why does that matter at 500,000/s?
  A: Its one lock: a contending thread enqueues a node and parks, which allocates. The allocations trigger G1 pauses that stop every thread, and at 500,000/s those delay more messages than the p99.99 rank (post hoc).
- Q: Why does a 2.68 ms G1 pause at 10,000/s not show in the queue + park arm's 6.13 µs p99.99?
  A: A p99.99 sees a pause only if the messages it delays outnumber 0.01% of the window: about 27 due during the pause (a floor: the backlog adds more) against a rank of 200 in 2,000,000 messages (arithmetic, not measurement).
- Q: Why is "group commit costs 52×" not a property of group commit?
  A: It is this setup at 20,000/s: a tiny ungated tail (1.39 µs) against 72.1 µs. fio measured an isolated sync at about 15 µs on drives with no volatile cache, but inside the pipeline the median sync took 23.5 µs, and a D2 message waits between one and two of them (see How it works). The direction transfers; the size does not.
- Q: Why did D3 saturate at 100,000/s, and why was that never a hypothesis?
  A: One `fdatasync` per order: 1 ÷ fio's median sync (14,656 ns on h1) is about 68,200/s, an upper bound that ignores the write and the hand-offs, and the pipeline sustained about 23,900/s. The arithmetic and reconnaissance both pointed there, so it was a stated prediction, not a hypothesis, and the cell left every test.
- Q: A tail message overlaps a safepoint. When is the safepoint credited, and why not on overlap alone?
  A: Only if safepoint time inside its busy period covers at least half its excess over the median. Slow messages overlap more of everything; coverage removes most of that bias, and the shifted null gives chance.
- Q: A colleague shows one fork's very tight interval on p99.99 and calls it the answer. What do you say?
  A: That interval assumes independent messages. Same-seed launches spread 5.64 to 8.90 times one run's own error (H4), so honest intervals are over launches or rounds.

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
