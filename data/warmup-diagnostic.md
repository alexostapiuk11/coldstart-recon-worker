# Warmup-length diagnostic

Supporting context, not pre-registered data. Run on a separate endpoint
(`v7x469ngmb7xbn`) against a separate image
(`sha256:4e3439a28ea2317fd445131138f8ddfa88fdefe5e0f2664e1593571f6189f02a`)
with no network volume attached, so it could not touch the campaign's pinned
image, endpoint, primed volume, or store. Arm A throughout. Cost ~$2.

## Question

Window 1's warmup curve is flat: request 1 lands 7.7% above steady state,
inside the ±10% tolerance, so `T_fast` is request 1. Is that a property of the
engine, or of our 16-token warmup request being too small to show anything?

## Result

The first-request overhead is roughly **constant in absolute terms** and the
ratio is dominated by the denominator:

| condition | first-request overhead | ratio |
|---|---|---|
| campaign, 16 tok, long-warm host (n=100) | +21 ms | 1.076 |
| diagnostic, 16 tok, warm worker | +33 ms | 1.116 |
| diagnostic, 16 tok, fresh worker | +61 ms | 1.216 |
| diagnostic, 256 tok, genuine (n=1) | +83 ms | **1.019** |

A fixed ~20–80 ms overhead is 20% of a 0.28 s request and 2% of a 4.4 s one.
"Ready is fast" and "ready is not fast" are both derivable from this system
depending on how large a request you use to ask. The absolute number is the
honest one; the ratio is an artifact of request size.

This does not contradict window 1's finding — it explains it. vLLM runs a
profiling pass and captures 86 CUDA graph shapes before answering `/health`
(see the waterfall's `S4` band), so what remains on the first request is tens
of milliseconds, not seconds.

## Design flaws in this diagnostic, stated

Both weaken it; neither changes the direction of the result.

1. **`max_tokens` does not control generation length here.** The prompt asks
   for "two sentences", so the model emits EOS and stops well before the limit.
   The 16-token and first 256-token runs produced near-identical steady-state
   latency (0.2823 s vs 0.2833 s), which is how the flaw was caught — 16x more
   tokens cannot take the same time. Forcing longer output needs `ignore_eos`
   on the request, not a larger `max_tokens`.
2. **A template env update does not reach an already-running worker.** One of
   the two 256-token runs still had the old environment. Only one run genuinely
   generated 256 tokens, so that condition is n=1.

## What would make this conclusive

Re-run with `ignore_eos: true` and a fixed output length, several runs per
condition, and deliberately alternating fresh and warm workers. The
fresh-vs-warm gap (61 ms vs 33 ms) is the more interesting open question: if
host state matters, window 1's concentration on a single long-warm host
understates what a real scale-up event sees, and the first-touch separation
now implemented is what would expose it across windows 2 and 3.
