# LLM serving on a GPU: chat brief

## How to use this brief

Paste this whole file into an AI chat, then paste the prompt at the end (it is already the last section). Ask clarifying questions about anything below. About 20 minutes to study.

## Concepts

Used by: a1, a2, a4, a5

- **GPU memory (HBM)**: The GPU's own fast memory, fixed in size. **Weights**, **scratch space** and the **KV cache** share it. Think of it as: A kitchen counter of fixed size: the recipe book takes most of it, a prep area stays clear, order notes fill the rest. Why it matters: The KV cache gets whatever weights and scratch leave, so free memory decides how many users you can serve.
- **Weights**: The model's learned numbers, on the GPU before it can answer: about 16 GB for an 8B model at 2 bytes per parameter. Think of it as: The recipe book: big, never edited, on the counter before cooking starts. Why it matters: Loading them sits inside the longest phase of artifact 1's cold start; a weight cache cut that phase by about 15 s.
- **KV cache**: While generating, the model keeps the **keys (K) and values (V)** of every token so far instead of recomputing them. Q is not cached. Think of it as: Each open order's notes, one line per token: long orders take more counter, so fewer fit. Why it matters: Each request holds cache in proportion to its length, so the cache divides into a number of concurrent requests; past that, new ones wait.
- **vLLM**: The serving engine here. At startup it loads the weights, runs the model once to see what memory is left, and gives that to the KV cache. Think of it as: Before opening, cook the biggest order once to see how much counter cooking needs; order notes get the rest. Why it matters: That **memory-profiling** run is in every cold start, and it sets the cache size.
- **Continuous batching**: One copy of the model serving many users' requests at once. A fresh replica takes work as soon as it is ready. Think of it as: One kitchen cooking many orders at once: more dishes per hour, each a little slower. Why it matters: In artifact 2, as requests in flight rose to 128, one replica's throughput rose and bent while latency rose gently.
- **Cold start**: The wait from a request being queued to a brand-new replica's first token. Think of it as: Opening a kitchen from empty when a crowd arrives: get a building, bring in the recipe book, prep, then cook. Why it matters: It is artifact 1's subject: a median 81.12 s with nothing cached, mostly launching and loading the model, then compiling.
- **Serverless GPUs**: GPU replicas added when traffic needs them and removed after. Before your code runs, the platform queues the request, finds a machine and starts a container. Think of it as: Renting kitchens as crowds come and go, paying even while one is still opening (artifact 2 counts every replica-second). Why it matters: Nothing of yours runs during the platform's part, so it is found by subtraction: total time minus the replica's own time.
- **torch.compile and CUDA graphs**: Startup steps that pay now to be faster later. **torch.compile** makes faster GPU code and caches it on disk; **CUDA graph capture** records GPU launches for every token to replay. Why it matters: A warm compile cache cut compiling to 0.33 s; graph capture took the same time in every arm, cached or not.

## Views

### What a replica does before it answers (concept)

One replica's cold start, in order (two short engine steps not drawn). Each cache shortens one step, as marked. Nothing before 'ready' serves a user.

- **Platform**: queue, machine, container; found by subtraction
- **Launch, load weights**: weight cache shortens this
- **Compile**: compile cache shortens this
- **Memory profiling**: one forward pass; sets KV cache size
- **CUDA graph capture**: flat 4 s, cached or not
- **Health check: ready**: now accepts work
- **First request**: first token to a user
- Platform → Launch, load weights
- Launch, load weights → Compile
- Compile → Memory profiling
- Memory profiling → CUDA graph capture
- CUDA graph capture → Health check: ready
- Health check: ready → First request

## Results as meaning

### Where a 24 GB card's memory goes

- Axis: Gigabytes, rounded: artifact 1's 24 GB card, with an 8B model's weights at 2 bytes per parameter.
- Read it as: The weights are a fixed block; the KV cache gets whatever is left after them and scratch, which is why cache size limits concurrency.
- RTX 4090 serving an 8B model: Weights 16, Everything else: scratch space and the KV cache 8 (GB)

### Where a cold start's time goes

- Axis: Seconds, each phase's median over 100 cold starts with nothing cached (artifact 1, arm A).
- Read it as: The coloured segments are most of the wait, and where the two caches act. Platform time is a residual found by subtraction, not just queueing. Medians do not add: these sum to 82.49 s, not the 81.12 s median total.
- Nothing cached (arm A): Platform (by subtraction) 4.37, Server launch to model loaded 45.83, Compile 19.01, Memory profiling 0.09, Graph capture 4.0, Unattributed 4.46, Ready check 4.43, First token 0.3 (s)

## Recall questions

- Q: Why does KV cache size limit concurrency, and what changes if requests get shorter?
  A: Each request keeps K and V for every token so far, so its cache grows with its length. The cache is a token budget: shorter requests fit more of them.
- Q: Why must the engine run the model once before serving anyone?
  A: Free memory depends on what a forward pass needs, and the only way to know is to run one at the largest batch, record the peak, and give the rest to the KV cache.
- Q: Why can a cold compile cost KV cache capacity, not only seconds?
  A: The compiler's working memory is still on the GPU during profiling, so the profiler sees less free memory and sizes a smaller cache for the replica's whole life.
- Q: What do you trade by skipping CUDA graph capture?
  A: Capture removes per-step launch overhead from every later token. Skipping it saves startup once and pays on every token: arguably fine for a short-lived replica only.
- Q: Why is a compile cache more fragile than a weight cache?
  A: Its key includes engine version, model, GPU and flags, which change routinely, so an upgrade silently makes it cold. Weights never change.
- Q: What changes if a new replica lands on a host that never pulled the image?
  A: The image pull happens before your code runs, and neither cache touches it: artifact 1's one such run took 2266.6 s.

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
