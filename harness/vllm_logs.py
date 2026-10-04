import re
from dataclasses import dataclass, field

# Taken from fixtures/vllm_logs/startup_*.log (vLLM 0.27.1) and recorded in
# fixtures/README.md Q1. Each pattern captures a float in group "sec".
#
# Only three of the five sub-phases carry a duration in this version's output.
# S4a (device init) and S4d (KV allocation) are announced by their results
# rather than their cost -- there is no "device init took N s" line, and KV
# allocation reports a size, not a time. Those two are merged, never invented.
PATTERNS: dict[str, re.Pattern] = {
    # Anchored on "in total" so the partial compile lines that precede it --
    # "Dynamo bytecode transform time: 7.43 s" and "Compiling a graph for
    # compile range (1, 2048) takes 26.37 s" -- cannot be mistaken for T_compile.
    "S4b": re.compile(r"torch\.compile took (?P<sec>[\d.]+) s in total", re.IGNORECASE),
    "S4c": re.compile(r"Initial profiling/warmup run took (?P<sec>[\d.]+) s", re.IGNORECASE),
    "S4e": re.compile(r"Graph capturing finished in (?P<sec>[\d.]+) secs?", re.IGNORECASE),
}

# Sub-phases this version does not delineate. Reported merged, never guessed apart.
MERGED: list[str] = ["S4a", "S4d"]

# This version reports the token capacity directly. It emits neither a block
# count nor a block size, so capacity must be read, not reconstructed by
# multiplication -- see the note in `parse_engine_log`.
KV_TOKENS = re.compile(r"GPU KV cache size: (?P<tokens>[\d,]+) tokens", re.IGNORECASE)

# Kept for engine versions that report blocks instead of tokens. Neither
# appears in the pinned version's output, so neither lands in engine_info
# today; they are here so a version change surfaces as new data rather than
# as a silently missing capacity figure.
KV_BLOCKS = re.compile(r"# GPU blocks: (?P<blocks>[\d,]+)", re.IGNORECASE)
BLOCK_SIZE = re.compile(r"block_size[=: ]+(?P<n>\d+)", re.IGNORECASE)

VERSION = re.compile(r"V1 LLM engine \(v(?P<v>[\d.]+)\)", re.IGNORECASE)
MODEL = re.compile(r"Initializing a V1 LLM engine .*?model='(?P<model>[^']+)'", re.IGNORECASE)


@dataclass
class ParsedLog:
    phases: dict[str, float] = field(default_factory=dict)
    engine_info: dict = field(default_factory=dict)
    merged: list[str] = field(default_factory=list)


def _int_with_commas(raw: str) -> int:
    return int(raw.replace(",", ""))


def parse_engine_log(text: str) -> ParsedLog:
    """Extract S4 sub-phase durations and engine facts from vLLM startup output.

    Absence is never an error, and never a zero: a phase this version does not
    emit is omitted from `phases` and appears in `merged` instead. A 0.0 would
    be indistinguishable from a real instantaneous phase, and `metrics.derive()`
    relies on the absent/zero distinction to populate `merged_phases`. This
    parser is the producer side of that contract.

    The bracketed S4 total from clock B stays authoritative -- see spec 5,
    attribution caveat.
    """
    phases: dict[str, float] = {}
    for name, pat in PATTERNS.items():
        m = pat.search(text)
        if m:
            phases[name] = float(m.group("sec"))

    info: dict = {}

    # Capacity, read directly. `kv_capacity_tokens` is what the engine states;
    # blocks x block_size is a reconstruction this version gives no inputs for.
    m = KV_TOKENS.search(text)
    if m:
        info["kv_capacity_tokens"] = _int_with_commas(m.group("tokens"))
    m = KV_BLOCKS.search(text)
    if m:
        info["kv_cache_blocks"] = _int_with_commas(m.group("blocks"))
    m = BLOCK_SIZE.search(text)
    if m:
        info["block_size"] = int(m.group("n"))

    m = VERSION.search(text)
    if m:
        info["vllm_version"] = m.group("v")
    m = MODEL.search(text)
    if m:
        info["model"] = m.group("model")

    return ParsedLog(phases=phases, engine_info=info, merged=list(MERGED) if phases else [])
