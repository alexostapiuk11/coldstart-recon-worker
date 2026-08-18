# Distribution and Network Track — Design

**Date:** 2026-08-17
**Status:** Approved design
**Type:** Ongoing track, not an artifact. Runs in parallel with artifacts 1–5.

---

## 1. Purpose

The artifacts are evidence. This track is how the evidence reaches people who can act on it.

It exists because the stated success criteria are *not* artifact completion:

- Recruiters and engineers at target companies initiating contact.
- A linkable body of work that makes "ML platform / inference infrastructure" read as
  description rather than aspiration.
- Interviews where the technical evaluation is partly complete before it starts.
- A network of roughly 100–150 relevant engineers at target companies.

**Explicitly not success:** followers, impressions, viral reach, general audience growth.

**This track has the longest lead time in the portfolio.** Network accumulation cannot be
compressed by publishing faster, which is why it starts before artifact 1 ships.

---

## 2. The binding constraint

**Hours, not ideas.**

| | |
|---|---|
| Total available | 144–312 hours (8–12 hrs/week × 18–26 weeks) |
| Artifacts 1–4 | ~210–305 hours |
| **Residual for this track** | **~40–60 hours realistically** |

That is 2–3 hours a week. **Any plan requiring daily engagement, regular original posting, or
sustained community presence is not executable**, and attempting it will consume artifact hours —
the wrong trade, since without the artifacts there is nothing to distribute.

The design constraint is therefore **maximum signal per hour, with the artifacts as the engine.**
Not a content strategy. A leverage strategy.

Second constraint, different in kind: this track involves real people, cannot be debugged, and its
mistakes are visible and semi-permanent. That argues for a small number of deliberate actions over
volume.

---

## 3. Network definition — tiered

The "100–150 engineers" figure is a target for the *aware* tier, not for relationships.

| Tier | Definition | Target | Cost per person |
|---|---|---|---|
| **Aware** | Read the work, recognize the name | 100–150+ | Near-zero; the artifacts generate it |
| **Reachable** | Would reply to a direct message | 40–60 | Minutes, concentrated post-publication |
| **Conversed** | Real technical exchange; would take your call | 15–25 | Hours. The expensive tier |

**Why tiering rather than one number:** 100–150 at relationship depth is arithmetically
impossible. At an hour or two each that is 150–300 hours, exceeding the entire remaining budget
including the artifacts.

The tiers also do different jobs. *Aware* makes the name familiar when a recruiter mentions it
internally, and needs volume. *Conversed* produces referrals and warm intros, and 15–25 people who
genuinely rate you is enough to reach most teams in the NYC inference-infra world, which is small.
*Reachable* is the pool the conversed tier gets drawn from over time.

Mapped to the success criteria: inbound contact is fed by *aware*; pre-completed technical
evaluation by *aware* plus *reachable*; referrals almost entirely by *conversed*.

---

## 4. The deep tier is technical exchange, not calls

### The referral objection, taken seriously

A one-hour conversation does not make someone able to vouch for how you work. Two things were
being conflated:

**Weak referral** — "I'll submit your resume" — moves you from the cold-apply pile to a recruiter
screen. The referrer risks little; their internal question is "will I be embarrassed if this person
interviews badly?" Published work plus one conversation clears that bar easily.

**Strong advocacy** — "I want this person on my team" — requires evidence of how you think. A
conversation does not produce it.

### What resolves it

**The artifacts carry the evidence a referrer normally cannot.** The usual referral comes from
someone who worked adjacent to you years ago and remembers you were fine — vague impressions, no
legible proof. Someone who has read the cold-start decomposition has seen you isolate a variable,
refuse a percentile your sample cannot support, and name a confound that would have flattered you.
That is more evidence of engineering judgment than most referrers possess about most candidates,
and unlike impressions it is transferable: they can forward a link, not a vibe.

So the conversation's job is smaller — confirming you are a real person, pleasant to deal with, who
did the work. One hour is plenty for that.

### The design consequence

**Weight the deep tier toward asynchronous technical exchange, with calls reserved for top target
companies.** Exchange means: someone challenges your methodology and you answer well; someone runs
your harness and you help them through a problem; an issue thread on the repo goes somewhere real;
you give a genuinely useful answer about their system.

Each shows you reasoning under mild pressure, which is closer to what working with you is like than
any call. They fit 20-minute gaps rather than scheduled hours, and they leave a public trace others
can see. **A person who reviewed your harness code knows more about you than someone who had coffee
with you.**

Calls stay worthwhile for the handful of companies you most want, where a human relationship changes
whether your name surfaces in a hiring discussion you are not in.

### Also: referrals may not be the main path

For inference-infra roles the hiring managers are usually technical and do read. "Hiring manager
encounters the work and reaches out" needs no referrer at all, and it is what the success criteria
actually describe.

---

## 5. Channel mix

| Channel | Hours | What it produces |
|---|---|---|
| **Upstream contribution** | 15–20 | Permanent public evidence; contact with exactly the right engineers |
| **Publication-linked outreach** | 12–15 | Three concentrated bursts, one per artifact |
| **NYC in-person** | 10–15 | The conversed tier; several conversations per evening |
| **Light community presence** | 5–10 | Context for the above. Not a growth channel |
| **Tracking** | 3–5 | Knowing what worked |

### Upstream contribution is the highest-leverage item

Months of instrumenting vLLM's startup path in fine detail will surface things: a phase boundary
that is not logged, a docs page wrong about caching behavior, a startup log line that would help
everyone, possibly a real bug. **These get found whether or not you look for them**, because
careful measurement is how such things get found.

A merged PR to vLLM is public, permanent, attributable, and technically legible in a way no post
is. It puts your name in a repository every target reads. And it is evidence of the thing a
referrer specifically cannot vouch for — that you can work in unfamiliar production code and
improve it, not just measure it from outside.

Cost is low because the discovery is a byproduct. Two or three small, well-scoped observability or
docs PRs over the period is realistic.

**The trap: do not hunt for something to contribute.** Manufactured contributions are obvious and
waste hours you do not have. Take what the measurement work hands you.

### Community presence stays deliberately light

Enough that you are not a stranger arriving with a link; not so much that it becomes a sink. The
goal is being a recognizable name in one or two places, not a fixture in five.

---

## 6. Publication-linked outreach — the motion

Three bursts, one per publication, 4–5 hours each.

**Why tied to publication:** the artifact is a permission structure. "Here is something I measured
that bears on what your team does" is a legitimate message between engineers. "I would like to
connect" is not, and it gets ignored while mildly damaging you. The window is days, not weeks.

| Step | Time |
|---|---|
| Build or refresh the list of named people at target companies | 30–45 min |
| Send 15–25 individually written messages | 2–3 hrs |
| Handle replies properly | 1–1.5 hrs |

Across three publications: 45–75 contacts, yielding perhaps 15–30 real exchanges — most of the
*reachable* tier and the pool *conversed* is drawn from.

**Message shape:** ask a real technical question their team would have a view on, using the artifact
as the reason for asking. Roughly *"I measured X and got Z, which surprised me because W — you have
worked on [specific thing], does that match what you see at scale?"* A question invites a reply; a
link invites nothing. And after each artifact there are genuine open questions: the unattributable
residual, whether the compile-cache result holds elsewhere, whether anyone else sees the flakiness.

**Four failure modes, all avoidable:**

- **Anything near-identical sent to multiple people.** Detectable, it circulates, and the
  reputational damage is permanent and not worth 20 contacts.
- **Asking for anything in the first message** — no referral, no intro, no "are you hiring." The
  fastest way to end the exchange. The first message asks only for an opinion.
- **Following up more than once.** Silence is an answer.
- **Sending this to recruiters.** Wrong audience for a technical question; they reach the work
  through amplification instead.

---

## 7. Target list

Size: **30–50 companies, of which 10–15 are genuinely targeted** — worth a meetup conversation and
a real relationship. The ceiling is set by the outreach math (15–25 messages × 3 publications), not
by ambition. A list of 200 is a list you cannot act on.

### The structural finding

**The topically-closest category is the weakest on NYC presence, and the strongest NYC presence
sits in categories that people targeting "AI infra" routinely skip.** Build the list accordingly.

### Tier 1 — verified, NYC, in lane

| Company | Evidence | Confidence |
|---|---|---|
| **Anthropic** | All 16 floors of 330 Hudson St; from <500 NYC staff at start of 2026 to >1,000 by year end; teams span AI research and engineering, and **compute**; existing office at 155 Ave of the Americas; NYC is its second-largest hub | Verified |
| **Perplexity** | Posts MTS **AI Inference Engineer** and **AI Infrastructure Engineer**; NYC among locations; runs its own inference engine across dozens of model architectures under tight latency and cost budgets | Verified |
| **NVIDIA** | **Senior Software Engineer, TensorRT Inference — New York.** The strongest big-tech match: inference serving specifically, in metro | Verified |
| **Jane Street** | NYC ML Engineer role explicitly requiring experience *building and maintaining training and inference infrastructure*, working on their ML platform | Verified |
| **OpenAI** | 90,000 sq ft at the Puck Building, SoHo | Verified (office; roles unchecked) |
| **Runway** | NYC-headquartered, generative video, genuinely hard inference problems | Verified (HQ; roles partial) |

### Tier 2 — real, verify per-role

**Google DeepMind** — a *Software Engineer, Model Inference* posting exists whose work is optimizing
and deploying LLMs like Gemini onto production infrastructure, and Glassdoor lists 27 Google
DeepMind roles in New York. **Location on that specific posting is unconfirmed** — Google's careers
site is JS-rendered and blocks automated reading. Check manually.

**Meta** — an *AI/HPC Network Engineer* role in New York, sitting in Meta's AI Training and
Inference Infrastructure org. Note the nuance: the NYC role is **networking, not serving**. Around
24 Meta AI jobs in NYC skew toward data science, research, and solution architecture.

**NYC AI application companies** — Hebbia, Decagon, Sierra, Harvey, Writer, Glean. Heavy applied/AI
engineer hiring, mixed NYC/SF. Check each posting's location.

**Amazon / AWS and Microsoft** — no direct NYC ML-infra posting surfaced; searches returned
contractor and vendor listings. **Unverified.** Worth a manual pass, not worth assuming.

**Two Sigma, Citadel, Bloomberg, Hudson River Trading, Point72** — the finance thesis rests on Jane
Street's concrete posting plus structural reasoning, **not** on a verified per-firm survey. These
need your check against live boards before earning list slots.

### Tier 3 — topically perfect, geographically weak

**Baseten** (~200 staff, planning to triple), **Fireworks** ($1.5B raised, expanding compute
infrastructure and engineering), **Together, Modal, Anyscale**. Their entire product is what the
artifacts measure, and **NYC engineering presence could not be confirmed for any of them.** Treat as
remote-or-relocate. Do not let topical fit pull the list away from where you can actually work.

### Why finance is weighted more than a generic AI-infra search would

- **NYC-native engineering orgs, not satellite offices.** Decision-makers and headcount are local —
  the difference between competing for a local slot and competing nationally for a remote one.
- **Your profile is what they hire.** Backend and cloud depth moving toward ML systems is a
  well-worn path in. They care less about whether you have shipped a model than whether you can
  reason about latency, tails, and systems under load.
- **The artifacts match how they read.** Pre-registered hypotheses, ECDFs instead of means, an
  explicitly unattributable residual, and a refusal to report p99 from 100 samples read like a
  research note in that world. What a startup reader finds admirably careful, a quant infra lead
  finds *normal and correct* — and notices that most candidates do not write this way.

### Finding named people

**Target people who have publicly written or spoken about serving and inference** — engineering blog
authors, conference speakers, GitHub contributors under the company org, people who post
substantively.

Not because they matter more, but because the outreach is a genuine technical question, and a
question about cold-start attribution lands very differently with someone who has published on
serving than with a random senior engineer who happens to work there. Better reply rate, and their
opinion travels internally.

This compounds with upstream contribution: contributors to the projects you are measuring are
disproportionately employed at exactly these companies.

**Market context for calibration:** NYC ML infrastructure roles run roughly $117k–$350k, with a
senior posting observed at $200–230k, and postings that name **vLLM, Triton, and TorchServe**
directly.

---

## 8. AI Engineer New York 2026 — October 12–14

In your metro, with your target audience in the room, roughly eight weeks out.

**It creates a tempting deadline for artifact 1. Do not take it.** Rushing artifact 1 to have a link
by October is precisely the failure mode the portfolio is built to avoid, and a thin artifact is
worse than no artifact.

**Go anyway.** An evening of conversations feeds the *conversed* tier faster than any other channel
available, and "I am measuring cold-start decomposition on vLLM right now" is a perfectly good thing
to say. The ticket is a separate budget line from the $200 compute envelope and gets decided on its
own terms.

---

## 9. Cadence

**Continuous, low intensity (2–3 hrs/week):** light community presence; upstream contribution when
the measurement work hands you something; tracking upkeep.

**Event-driven bursts:** publication-linked outreach, 4–5 hours in the days following each of the
three publications.

**Calendar-driven:** NYC events as they occur, including the October conference.

**Starts now**, before artifact 1 publishes, because the *aware* and *reachable* tiers have lead
time that publishing cannot compress.

---

## 10. Tracking

One file in the repo, or any low-friction equivalent. Recorded per contact: company, person, channel,
date, what was asked, whether they replied, what they engaged with.

**Which parts of a post drew engagement is the design input to the next artifact.** Artifact 2's
final parameters and artifact 4's framing are deliberately unfinalized so they can absorb this.

Tracked outcomes, against §1: inbound contacts from target companies; warm conversations initiated;
count in each network tier; interviews where the artifact was referenced before you raised it.

**Not tracked, deliberately:** impressions, followers, upvotes.

---

## 11. Resolves the deferred decision from artifact 1

Artifact 1 §9 recorded an open decision: choosing the hiring audience dropped practitioner-community
distribution, which removed the only source of peer validation from unaffiliated engineers.

**This track resolves it.** Technical exchange in practitioner spaces — upstream contribution, repo
threads, and light community presence — is exactly where strong advocacy comes from, and it is
budgeted here rather than left out. The audience decision for the *posts* stands unchanged; the
*exchange* happens where practitioners are.

---

## 12. Risks

| Risk | Handling |
|---|---|
| Track consumes artifact hours | Hard cap of 2–3 hrs/week; artifacts have priority; outreach is bursty not continuous |
| Outreach reads as transactional | Publication as permission structure; question not pitch; nothing asked for in first contact |
| Mass-message reputational damage | Every message individually written, no exceptions |
| Hunting for contributions instead of taking what surfaces | Contribution only from measurement byproducts |
| Conference pulls artifact 1 forward and thins it | Explicit decision not to treat October as a deadline |
| Target list built on unverified assumptions | Confidence marked per entry; Tier 2 and 3 require manual verification before outreach |
| Nothing lands despite doing the work | Inbound is not fully controllable. The artifacts retain standalone value as interview evidence and petition evidence regardless |

---

## 13. Definition of done

This track has no completion state, but it has checkpoints:

- Target list populated to 30–50 companies with 10–15 marked primary, every Tier 2/3 entry manually
  verified against a live posting before any outreach.
- Named individuals identified per primary company, filtered to those who have published or spoken
  on serving and inference.
- Tracking file in place before the first outreach burst.
- October conference decision made explicitly, with the ticket treated as a separate budget line.
- Light community presence established in one or two places **before** artifact 1 publishes.
- One outreach burst executed per publication, 15–25 individually written messages each.
- At least one upstream contribution submitted, arising from measurement work rather than sought out.
- Network tier counts reviewed after each publication, with the next artifact's framing informed by
  what drew engagement.
