# LLM serving on a GPU: chat brief

## How to use this brief

Paste this whole file into an AI chat, then paste the prompt at the end (it is already the last section). Ask clarifying questions about anything below. About 20 minutes to study.

## Concepts

Used by: a1, a2, a4, a5

- **GPU memory (HBM)**: The GPU's own fast memory, separate from the computer's RAM, and fixed in size. Three main things share it: the model **weights**, **scratch space** for one forward pass, and the **KV cache**. Think of it as: A fixed-size desk: the reference book takes most of it, a work area stays clear, and the rest holds open notebooks, one per conversation. Why it matters: What is left after weights and scratch is the cache, so "how much memory is left" and "how many users can I serve" are the same question. Artifact 1 used a 24 GB RTX 4090.
- **Weights**: The model's learned numbers. They must be on the GPU before it can answer anything. An 8B model at 2 bytes per parameter is about 16 GB. Think of it as: The reference book: big, never edited, and it has to be on the desk before work starts. Why it matters: Downloading and loading them is part of the longest phase of artifact 1's cold starts, server launch to model loaded (a median 45.83 s in arm A). vLLM's own "Model loading took" line was 17.40 s of that; much of the rest is server and engine start before loading. Weights never change, so a weight cache stays valid until you switch models.
- **KV cache**: When generating, the model re-reads everything written so far. To avoid recomputing it, it stores the **keys (K) and values (V)** for every token. Only K and V are cached; Q is not. Think of it as: A notebook per conversation that gains a line with every token. The desk only has room for so many open notebooks. Why it matters: Each active request holds cache in proportion to its length, so **the cache size divides into a number of concurrent requests**. Run out and new requests wait. In artifact 1 with a cold compile cache, 35,792 tokens of cache fit 4 requests at the full 8192-token context (5 with a warm compile cache); shorter requests fit more, which is how artifact 2 ran 128 in flight.
- **vLLM**: The serving engine in these artifacts. At startup it loads the weights, runs the model once to see what memory is left, gives that to the KV cache, and reports ready. Then it serves many requests at once. Think of it as: A restaurant's dress rehearsal: cook the biggest order once, see how much counter space is left, then set out that many tables. Why it matters: There is no way to ask a GPU how much memory will be free except to run the model once. That **memory-profiling** run is in every cold start, and it is where artifact 1's KV capacity number comes from.
- **Continuous batching**: Serving many users' requests through one copy of the model at once. A fresh replica takes work the instant it reports ready. Think of it as: One bus instead of a taxi each: more riders per hour, each trip a bit slower, and riders get on and off at every stop. Floor space (the KV cache) is fixed, so how many fit depends on what each rider carries. Why it matters: Artifact 2 measured one replica serving 1 to 128 requests in flight: throughput rises and bends while latency rises gently. At 256 the engine died of CUDA out of memory at its first step (post-a2 does not say why). A just-ready replica serves real users at once.
- **Cold start**: The wait while a machine boots and loads a model, before anyone gets an answer: from the request being queued to the first token. Think of it as: Opening a restaurant from an empty building each time a crowd shows up: get the keys, deliver the stock, set up the kitchen, then serve the first dish. Why it matters: It is artifact 1's subject: with nothing cached the median was 81.12 s, mostly server launch to model loaded, then compiling. Artifact 2 asks whether this delay changes which autoscaling signal works best.
- **Serverless GPUs**: You rent GPU replicas that are added when traffic needs them and removed afterwards, and cost scales with how long replicas run (artifact 2 counts replica-seconds, starting ones included). Before your code runs, the platform queues the request, finds a machine, creates a container and pulls the image. Think of it as: Calling a taxi instead of owning a car: you pay per ride, and the artifacts' cost model also counts the time it takes to reach you. Why it matters: Every new replica pays a cold start, even with warm caches. The platform part, `T_platform`, cannot be instrumented because nothing of yours is running yet; it is found by subtraction. A host that has never pulled the image is far worse: artifact 1's one such run took 2266.6 s.
- **torch.compile and CUDA graphs**: Two startup steps that pay now to be faster later. **torch.compile** turns the model into faster GPU code and caches it on disk. **CUDA graph capture** records a fixed sequence of GPU operations so every token replays it without per-step launch overhead. Think of it as: Meal prep: chopping on Sunday costs an hour but makes weeknight dinners quicker. The compile step's prep can be frozen and reused (until the recipe changes); the graph-capture step's prep is redone every time a kitchen opens. Why it matters: Both sit inside every cold start: compiling took 19.01 s with an empty cache and 0.33 s with a warm one; graph capture a flat 4.00 s. A compile cache goes cold on a change of engine version, model, GPU type or engine flags.

## System views (C4)

### Where GPU memory goes (concept)

One fixed pool. Weights and scratch are taken first; the KV cache gets the rest, and that sets how many requests run at once.

- **GPU memory (HBM)**: fixed size, e.g. 24 GB
- **Weights**: about 16 GB for an 8B model
- **Scratch space**: for one forward pass
- **KV cache**: K and V per token; the rest
- **Concurrent requests**: how many fit at once
- GPU memory (HBM) → Weights: holds
- GPU memory (HBM) → Scratch space: holds
- GPU memory (HBM) → KV cache: holds the rest
- KV cache → Concurrent requests: divides into

### What a replica does before it answers (concept)

The main phases of a vLLM replica's cold start, in order (device setup and KV allocation, merged as 'unattributed' in the chart, are not drawn). Everything up to the health check happens before any user is served.

- **Platform queue**: find a machine, start a container
- **Launch, load weights**: server and engine start; weights into HBM
- **Compile**: torch.compile, or its cache
- **Memory profiling**: one forward pass; sizes KV cache
- **CUDA graph capture**: record kernel launches
- **Health check: ready**: now accepts work
- **First request**: first token to a user
- Platform queue → Launch, load weights
- Launch, load weights → Compile
- Compile → Memory profiling
- Memory profiling → CUDA graph capture
- CUDA graph capture → Health check: ready
- Health check: ready → First request

## Results as meaning

### Where a cold start's time goes

- Axis: Seconds, the median of each phase over 100 runs of artifact 1's arm A (weights from the hub, no compile cache).
- Read it as: The longest segments are where the waiting happens: server launch to model loaded (the post calls it T_weights; it includes server and engine start, and vLLM's own model loading was 17.40 s of it), then compiling. This unit uses the chart only to show that shape. Each segment is its own median, and medians do not add: these sum to 82.49 s, not the 81.12 s median total (in arm C they sum to less than the total).
- Nothing cached (arm A): Platform queue 4.37, Server launch to model loaded 45.83, Compile 19.01, Memory profiling 0.09, CUDA graph capture 4.0, Unattributed 4.46, Ready (health poll) 4.43, Cold first token 0.3 (s)

## Recall questions

- Q: Why does the KV cache size decide how many requests run at once?
  A: Each active request keeps K and V for every token so far, in proportion to its length. So the cache divides into a number of concurrent requests (35,792 tokens fit 4 full-length 8192-token requests). Past that, new requests wait.
- Q: Why must the engine run the model once before serving anyone?
  A: It cannot know how much scratch memory a forward pass needs until it tries one. It runs a profiling pass at the largest batch it must support, records peak memory, and gives the remainder to the KV cache.
- Q: Why is a serverless GPU's first request slow?
  A: No replica is running yet. The platform queues the request, finds a machine and starts a container; then the engine loads the weights, compiles, profiles memory, captures CUDA graphs and passes its health check, all before the first token.
- Q: Why can a cold compile cost KV cache capacity, not only seconds?
  A: The compiler's working memory is still on the GPU during the profiling pass, so the profiler sees less free memory and sizes the cache smaller, for the life of the replica.
- Q: Why not skip CUDA graph capture to start faster?
  A: Capture removes per-step launch overhead from every later token. Skipping it (`--enforce-eager`) saves its startup seconds once and pays on every token after. That is arguably worth it for a replica that answers briefly and dies, not for one serving millions of tokens.
- Q: Why is a compile cache more fragile than a weight cache?
  A: Its key includes the engine version, model, GPU and flags, all of which change routinely, so an upgrade silently makes it cold. Weights never change, so their cache stays valid until you switch models.

## Sources

- `docs/post.md`: ## What was measured
- `docs/post.md`: ## The decomposition
- `docs/post.md`: ## KV capacity — the second dividend
- `docs/post.md`: ### The number that dwarfs all of them
- `docs/post.md`: ## The four mechanisms
- `docs/superpowers/specs/2026-08-17-cold-start-decomposition-design.md`: ### Module 1 — What lives in GPU memory
- `docs/superpowers/specs/2026-08-17-cold-start-decomposition-design.md`: ### Module 2 — The KV cache, and why it *is* your concurrency limit
- `docs/superpowers/specs/2026-08-17-cold-start-decomposition-design.md`: ### Module 3 — Why the engine runs the model before serving anyone
- `docs/superpowers/specs/2026-08-17-cold-start-decomposition-design.md`: ### Module 4 — CUDA graphs: paying at startup to be faster later
- `docs/superpowers/specs/2026-08-17-cold-start-decomposition-design.md`: ### Module 5 — Compilation, and the cache you did not know you had
- `docs/superpowers/specs/2026-08-17-cold-start-decomposition-design.md`: ### Module 6 — What happens before your code exists
- `docs/post-a2.md`: ## The question
- `docs/post-a2.md`: ## What was measured and what was simulated
- `docs/post-a2.md`: ## The service curve
- `explainer/terms.json`: "continuous batching"
- `docs/learning/progress.md`: Q is not cached, only K and V

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
