"""One engine's configuration, and the facts its startup log states.

Artifact 4's jobs start several engines per job: two co-resident checkpoints,
or a swap from one to another. So the model, its revision and its memory share
travel in the job payload as an `EngineSpec`, not in the endpoint environment
the way the service sweep's single model does (`worker/sweep_handler.py`). The
local driver builds every spec from the pre-registration's pin set, so a
campaign still cannot run two configurations by accident.

Every flag that changes what an engine measures is explicit, even where it
equals vLLM 0.27.1's default: a default that moves in a later version would
change the measurement with no error. Prefix caching is off, as in the service
sweep, so a repeated random prompt cannot be served partly from cache.
"""

import math
from dataclasses import asdict, dataclass

from harness.sweep_worker import max_num_seqs_from_log
from harness.vllm_logs import parse_engine_log

__all__ = ["EngineSpec", "engine_facts", "log_tail"]

# What comes back of an engine's log: the last lines, each capped. Artifact 4
# reads its facts from the whole log before the cap (`engine_facts`); the tail
# is evidence for a human, and the job output's size limit is UNVERIFIED (the
# shared tooling plan's item 12), so it stays small.
LOG_TAIL_LINES = 200
LOG_LINE_CHARS = 2000


@dataclass(frozen=True)
class EngineSpec:
    model: str
    revision: str
    gpu_memory_utilization: float
    max_model_len: int
    max_num_seqs: int
    extra_args: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "extra_args", tuple(self.extra_args))
        if not self.model or not self.revision:
            raise ValueError(
                "an engine needs a model and a pinned revision; an unpinned one "
                "lets the checkpoint move under the experiment between jobs"
            )
        if not (math.isfinite(self.gpu_memory_utilization) and 0 < self.gpu_memory_utilization <= 1):
            raise ValueError(
                f"gpu_memory_utilization {self.gpu_memory_utilization!r} must be in (0, 1]; "
                "vLLM refuses anything else at startup, after the job has paid for the pull"
            )
        for name, value in (("max_model_len", self.max_model_len), ("max_num_seqs", self.max_num_seqs)):
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive int, got {value!r}")
        owned = {"--revision", "--gpu-memory-utilization", "--max-model-len", "--max-num-seqs", "--port"}
        clash = [a for a in self.extra_args if a.split("=", 1)[0].replace("_", "-") in owned]
        if clash:
            raise ValueError(
                f"extra_args {clash} set a flag the spec owns; argparse keeps the last of "
                "two values silently, so the engine would not be the one the spec records"
            )

    def serve_args(self) -> list[str]:
        """Everything after `vllm serve <model>` except `--port`, which
        `harness.serve.served` adds itself."""
        return [
            "--revision", self.revision,
            "--gpu-memory-utilization", str(self.gpu_memory_utilization),
            "--max-model-len", str(self.max_model_len),
            "--max-num-seqs", str(self.max_num_seqs),
            "--no-enable-prefix-caching",
            *self.extra_args,
        ]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["extra_args"] = list(self.extra_args)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "EngineSpec":
        return cls(**{**d, "extra_args": tuple(d.get("extra_args", ()))})


def engine_facts(lines) -> dict:
    """KV capacity, version, compile time and the batch limit, from the whole log.

    `s4b_s` is the `torch.compile took N s in total` reading: artifact 1
    published 19.0 s for a compile and 0.33 s for a cache hit, which is how a
    swap-in's compile state is read rather than inferred (amendment §5).
    """
    parsed = parse_engine_log("\n".join(lines))
    max_num_seqs, source = max_num_seqs_from_log(lines)
    return {
        **parsed.engine_info,
        "s4b_s": parsed.phases.get("S4b"),
        "s4_subphases": parsed.phases,
        "max_num_seqs": max_num_seqs,
        "max_num_seqs_source": source,
    }


def log_tail(lines) -> dict:
    kept = [
        line if len(line) <= LOG_LINE_CHARS else f"{line[:LOG_LINE_CHARS]}...[cut]"
        for line in list(lines)[-LOG_TAIL_LINES:]
    ]
    return {"log_tail": kept, "log_lines_total": len(lines)}
