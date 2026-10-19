# How these experiments earn trust: chat brief

## How to use this brief

Paste this whole file into an AI chat, then paste the prompt at the end (it is already the last section). Ask clarifying questions about anything below. About 20 minutes to study.

## Concepts

Used by: a1, a2, a4, a5, a6, a7

- **Percentiles and the tail**: **p95** is the time 95% of runs finish within; **p50** is the median; the **tail** is the slow end. One huge run drags a mean, so artifacts 1, 2 and 5 publish none for skewed data. Think of it as: Your usual commute is p50; the day the bridge closed is the tail. Their average is no real day. Why it matters: A1 publishes no p99 (at about 100 runs that is one or two runs); A7 publishes p99.99 because every run has at least 200 messages above it.
- **ECDF**: One curve of every run: time across, **share of runs finished by then** up. Every percentile, and the tail, reads off it. Think of it as: Race results: at each clock time, the share of runners over the line. Why it matters: A1's showed arm B's largest repeat-host run (148.2 s) beyond arm A's (111.6 s), despite B's lower median.
- **Spread versus interval**: **Spread** is where single runs land. A 95% **interval** says how far the **median** itself moves between re-runs: a plausible range for the true median. A **bootstrap** imagines the re-runs: it redraws the runs with replacement, 10,000 times, and keeps the middle 95% of medians. Why it matters: A1's arm A interval spans a stretch where no run landed and excludes a value where nine did.
- **Pre-registration**: Commit the hypotheses, analysis, exclusions and stopping rule **before the data exists**. The git timestamp is the evidence. Think of it as: Sealing your prediction in an envelope before the match. Why it matters: A1's predates its campaign data, not three paid reconnaissance captures, and says so; A6's campaign stays unread by its own rule.
- **Paired, interleaved runs**: Run the arms close together in a shuffled order, so a slow hour or a drifting host hits every arm about equally. Arm A today, arm B tomorrow mixes the arm with the day. Think of it as: Weighing two parcels on one scale in the same minute: if the scale drifts, the difference survives. Why it matters: A1 ran 100 shuffled triples, one run per arm; A5 ran both traffic patterns inside every server start.
- **Validation gate**: A test, fixed in advance, that a model must pass against real runs before its answers count: **pass**, **fail**, or **inconclusive** (could not resolve its own margin; not a pass). Think of it as: Checking a new scale against known weights, and remembering it was only checked up to the heaviest. Why it matters: A2's and A4's simulators had to match three real repeats in at least half the time bins; A5's synthetic adapters, real ones within ±5%.
- **Amendment versus forking path**: A **forking path** is an analysis choice that depends on the data seen; unrecorded, no reader can discount it. An **amendment** is a dated, written rule change: what changed, why, what had been seen. One made after the data is still labelled post hoc. Why it matters: A4's amendments are dated and say what had been seen: two came after its cell runs, before their analysis. A5's Amendment 3 extended its gate after an inconclusive verdict, and its post says so.
- **A failed gate is a result**: Publish the failure and every miss, with what is known of the cause. Measured inputs stand; the model's numbers may appear, but only labelled unvalidated. Why it matters: A2's simulator failed twice, 34 of 37 judged bins missed, then 37 of 37; A4's missed 10 of 13, so its GPU counts are not validated.

## Views

### From claim to trust (concept)

A composite of the artifacts, not one artifact's path: A1 had no model, so no gate. The boxes are the cards above: rules, spread, intervals, the gate, fair comparison.

- **A claim**: e.g. one cache saves more than the other
- **Rules fixed first**: pre-registration; later changes dated
- **Measured with spread**: percentiles, ECDF, intervals
- **Model checked by gate**: only where a model stands in; pass, fail or inconclusive
- **Compared fairly**: paired, interleaved runs
- **Limits stated**: what the result cannot claim
- A claim → Rules fixed first
- Rules fixed first → Measured with spread
- Measured with spread → Model checked by gate
- Model checked by gate → Compared fairly
- Compared fairly → Limits stated

## Results as meaning

### Same two clusters, different split: the interval's width

- Axis: Width of the bootstrap interval on the median, in seconds. Two constructed clusters, 99 runs in all; only how many fall in each changes.
- Read it as: Near an even split, redrawn medians land in either cluster, so the interval spans the gap. At 70/29 they all land in the big one. Width follows where the median sits, not how far runs scatter.
- Split 51 / 48: 5 s
- Split 70 / 29: 0 s

### Median versus tail, artifact 1's three cache set-ups

- Axis: Seconds of total cold start, about 100 runs per set-up: p50, p90, p95.
- Read it as: The order holds out to p95, yet B's largest repeat-host run is longer than A's. A handful of runs, but the median ranking is not evidence about the far tail.
- A: nothing cached: p50 81.1, p90 96.3, p95 96.4 (s); largest 111.6 s
- B: weights cached: p50 65.4, p90 85.9, p95 86.4 (s); largest 148.2 s
- C: weights and compile cached: p50 39.4, p90 54.8, p95 54.9 (s)
- Note: Hollow circle: largest repeat-host run, given for A and B only.

### Three gate runs that failed

- Axis: Judged time bins per gate run; a pass allows at most half to miss.
- Read it as: All far past half. A2 missed on one side, then, calibrated, on the other; in A4's misses the simulator always predicted the engine slower than it was.
- A2, attempt one: Missed 34, Not missed 3 (bins)
- A2, attempt two (calibrated): Missed 37 (bins)
- A4: Missed 10, Not missed 3 (bins)

## Recall questions

- Q: What does a 95% bootstrap interval on a median range over?
  A: Medians of imagined re-runs of the experiment, not the runs themselves. It can cover a stretch where no run landed.
- Q: Same two clusters: why does 51/48 give a 5.00 s interval and 70/29 give 0.00 s? Must intervals shrink with more runs?
  A: Near an even split a redrawn median can fall in either cluster, so the interval spans the gap; at 70/29 it almost never leaves the big one. Not necessarily: it shrinks only on average, and a new run can move the split toward even. A1's own data contradicted 'it shrinks as runs accumulate'.
- Q: Why don't 10,000 more resamples make an interval more trustworthy?
  A: Resampling is free computation on the same runs; it adds no evidence. Only real runs, which cost GPU-hours, set the width.
- Q: Why is a failed gate a result, and what may you still conclude?
  A: It is the pre-registered test answering no, which is its job. Measured inputs stand; model output appears only labelled unvalidated, and so does anything built on it.
- Q: What separates an amendment from a forking path?
  A: The record: an amendment is dated in git and says what had been seen, so a reader can weigh it. Recording does not make a data-dependent change neutral, so one made after the data is labelled post hoc, like A1's first-touch rule.
- Q: Why interleave arms instead of running each in a block?
  A: In blocks, drift over time lands on one arm and looks like its effect, inseparable afterwards. Interleaved, drift hits every arm about equally: it adds noise, not a bias.

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
