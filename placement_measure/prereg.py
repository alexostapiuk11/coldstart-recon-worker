"""The first pre-registration step's values, as code (amendment §3).

`docs/experiment-a4.md` states them in prose and
`tests/test_placement_measure_prereg.py` fails if the two disagree, so the
document a reader checks and the values a job runs on cannot drift apart.
Committed before the reconnaissance run, because recon is itself paid and its
go/no-go must be fixed before its answer is seen. Everything chosen after
recon -- the request shape, the grid, the design -- is the second step's.

Revisions are the commit each checkpoint's `main` pointed at on 2026-10-04,
read from the Hugging Face model API. Artifact 5 reads the primary model, its
revision, the GPU class and the vLLM base digest from here (its plan 2).
"""

from placement_measure.engine import EngineSpec

__all__ = [
    "CANDIDATES", "FALLBACK", "GO_NO_GO_MIN_REQUESTS", "MAX_MODEL_LEN", "MAX_NUM_SEQS",
    "PRIMARY", "SLEEP_GMU", "SOLO_GMU", "SPLIT_GMU", "T_MAX", "engine",
]

# Checkpoint -> revision. All Qwen3ForCausalLM; the four 4B ones share every
# shape, and differ in rope_theta (1e6 for Qwen3-4B and -Base, 5e6 for the
# -2507 pair) and maximum length (amendment §3).
CANDIDATES = {
    "Qwen/Qwen3-4B": "1cfa9a7208912126459214e8b04321603b3df60c",
    "Qwen/Qwen3-4B-Base": "906bfd4b4dc7f14ee4320094d8b41684abff8539",
    "Qwen/Qwen3-4B-Instruct-2507": "cdbee75f17c01a7cc42f958dc650907174af0554",
    "Qwen/Qwen3-4B-Thinking-2507": "768f209d9ea81521153ed38c47d515654e938aea",
    "Qwen/Qwen3-1.7B": "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e",
}
PRIMARY = "Qwen/Qwen3-4B"
FALLBACK = "Qwen/Qwen3-1.7B"

GPU_TYPE = "NVIDIA GeForce RTX 4090"
NETWORK_VOLUME = "9c7ut2slrd"
VLLM_VERSION = "0.27.1"
# worker/Dockerfile's ARG VLLM_DIGEST, which artifacts 1, 2, 4 and 5 share.
VLLM_BASE_DIGEST = "sha256:0a51ea5b4ae2dc5d81890e5173f54203d2a3ae0cfffe51b8fd2afd4391bfd967"

# The per-request token ceiling. The request shape, fixed in step 2, is at or
# below it, so `--max-model-len` equals it.
T_MAX = 2048
MAX_MODEL_LEN = T_MAX
# Pinned rather than defaulted, as the service sweep pins it: vLLM logs a
# defaulted value only at DEBUG, so a run could not record its batch limit.
MAX_NUM_SEQS = 256
# Each of two co-resident engines. vLLM's limit is per instance
# (CacheConfig.gpu_memory_utilization, v0.27.1), so two at 0.45 is its
# documented way to share a card, leaving 10% for both CUDA contexts.
SPLIT_GMU = 0.45
# A lone engine: artifact 1's measured budget (21.64 GiB at 0.92, fixtures/README.md).
SOLO_GMU = 0.92
# The sleep probe's two engines start one while the other sleeps; each at 0.80
# leaves room for the sleeping one's residue, whose size is what it measures.
SLEEP_GMU = 0.80

# Go/no-go: both engines healthy at SPLIT_GMU, and each one's logged KV
# capacity at least this many T_MAX-token requests.
GO_NO_GO_MIN_REQUESTS = 8
GO_NO_GO_TOKENS = GO_NO_GO_MIN_REQUESTS * T_MAX

# A swap's memory is released when the card reads at most its idle level plus
# this; the wait gives up after RELEASE_TIMEOUT_S and records that it did.
RELEASE_TOLERANCE_MIB = 512
RELEASE_TIMEOUT_S = 120
HF_HOME = "/runpod-volume/hf"  # worker/Dockerfile's ENV HF_HOME
JOB_BUDGET_S = 1800  # the endpoint's executionTimeout


def engine(model: str, gmu: float, extra_args=()) -> EngineSpec:
    """An engine on a pre-registered checkpoint, every other flag pinned."""
    return EngineSpec(model, CANDIDATES[model], gmu, MAX_MODEL_LEN, MAX_NUM_SEQS, tuple(extra_args))
