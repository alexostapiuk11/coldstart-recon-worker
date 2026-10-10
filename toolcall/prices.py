"""Per-token prices, pinned with their source and the date they were read.

Cost in this artifact is computed from each response's own `usage`, times these
prices. The spend record (docs/spend-a3.md) compares that computation with
what the provider billed (amendment §8). A price change between the pilot and
the campaign is caught there; this table is re-read at pre-registration step 2.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Price:
    input: float  # USD per million uncached input tokens
    cached: float  # USD per million cache-read input tokens
    cache_write: float  # USD per million cache-write input tokens (Anthropic only)
    output: float  # USD per million output tokens, reasoning included
    source: str
    read: str  # the date the source was read
    check: str  # "docs" or "secondary", as amendment §0's labels


PRICES = {
    "gpt-5.4-mini-2026-03-17": Price(
        0.75, 0.075, 0.0, 4.50,
        "https://developers.openai.com/api/docs/models/gpt-5.4-mini", "2026-10-08", "docs"),
    "gpt-5.4-nano-2026-03-17": Price(
        0.20, 0.02, 0.0, 1.25,
        "https://developers.openai.com/api/docs/models/gpt-5.4-nano", "2026-10-08", "secondary"),
    "claude-sonnet-5-5": Price(
        2.00, 0.20, 2.50, 10.00,
        "https://platform.claude.com/docs/en/about-claude/pricing", "2026-10-08", "docs"),
}


def cost_usd(model: str, usage: dict) -> float:
    """`usage` is the normalized dict toolcall.providers parsers return:
    `input` counts every input token, cached and cache-written included."""
    if model not in PRICES:
        raise KeyError(f"no pinned price for {model!r}; add it with its source first")
    p = PRICES[model]
    uncached = usage["input"] - usage["cached"] - usage["cache_write"]
    if uncached < 0:
        raise ValueError(f"usage has more cached than total input tokens: {usage}")
    return (
        uncached * p.input
        + usage["cached"] * p.cached
        + usage["cache_write"] * p.cache_write
        + usage["output"] * p.output
    ) / 1e6
