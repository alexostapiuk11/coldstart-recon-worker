"""Synthetic LoRA adapters, written in the PEFT on-disk format.

For serving cost only shape matters -- rank and which modules are wrapped --
never the values inside (amendment §5 of the August design; the equivalence
gate checks it rather than asserting it). So the sweep's adapters are drawn
from a seeded normal distribution at a fixed scale, written where the worker
serves them, and identified by a checksum stored with the run.

Shapes come from the base model's own `config.json`, not from a table in this
file, so the writer cannot disagree with the checkpoint it is written for.
"""

import hashlib
import json
from pathlib import Path

import numpy as np
from safetensors import safe_open
from safetensors.numpy import save_file

# Fixed, and recorded here rather than per run: the weights must be identical
# across instances for a checksum to mean anything. 0.01 keeps activations near
# the base model's, which matters only for generated text -- serving cost does
# not depend on it, and ignore-EOS fixes output length regardless.
INIT_STD = 0.01

_ATTENTION = ("q_proj", "k_proj", "v_proj", "o_proj")
_MLP = ("gate_proj", "up_proj", "down_proj")


def module_shapes(config: dict) -> dict[str, tuple[int, int]]:
    """(in_features, out_features) per projection, from a HF decoder config."""
    hidden = config["hidden_size"]
    heads = config["num_attention_heads"]
    kv_heads = config.get("num_key_value_heads", heads)
    head_dim = config.get("head_dim") or hidden // heads
    inter = config["intermediate_size"]
    return {
        "q_proj": (hidden, heads * head_dim),
        "k_proj": (hidden, kv_heads * head_dim),
        "v_proj": (hidden, kv_heads * head_dim),
        "o_proj": (heads * head_dim, hidden),
        "gate_proj": (hidden, inter),
        "up_proj": (hidden, inter),
        "down_proj": (inter, hidden),
    }


def _module_path(layer: int, module: str) -> str:
    block = "self_attn" if module in _ATTENTION else "mlp"
    return f"base_model.model.model.layers.{layer}.{block}.{module}"


def adapter_parameter_count(config: dict, rank: int, target_modules) -> int:
    shapes = module_shapes(config)
    per_layer = sum(rank * (shapes[m][0] + shapes[m][1]) for m in target_modules)
    return per_layer * config["num_hidden_layers"]


def write_synthetic_adapter(
    path,
    *,
    config: dict,
    base_model: str,
    rank: int,
    target_modules,
    seed: int,
) -> str:
    """Write one adapter directory and return its sha256 checksum."""
    unknown = set(target_modules) - set(_ATTENTION + _MLP)
    if unknown:
        raise ValueError(f"unsupported target modules {sorted(unknown)}")
    if rank <= 0:
        raise ValueError(f"rank must be positive, got {rank}")
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    shapes = module_shapes(config)
    rng = np.random.default_rng(seed)
    tensors: dict[str, np.ndarray] = {}
    for layer in range(config["num_hidden_layers"]):
        for module in sorted(target_modules):
            in_f, out_f = shapes[module]
            prefix = _module_path(layer, module)
            tensors[f"{prefix}.lora_A.weight"] = (
                rng.standard_normal((rank, in_f), dtype=np.float32) * INIT_STD
            ).astype(np.float16)
            tensors[f"{prefix}.lora_B.weight"] = (
                rng.standard_normal((out_f, rank), dtype=np.float32) * INIT_STD
            ).astype(np.float16)
    save_file(tensors, str(path / "adapter_model.safetensors"))
    adapter_config = {
        "base_model_name_or_path": base_model,
        "bias": "none",
        "fan_in_fan_out": False,
        "inference_mode": True,
        "lora_alpha": rank,
        "lora_dropout": 0.0,
        "peft_type": "LORA",
        "r": rank,
        "target_modules": sorted(target_modules),
        "task_type": "CAUSAL_LM",
    }
    (path / "adapter_config.json").write_text(json.dumps(adapter_config, sort_keys=True))
    return adapter_checksum(path)


def adapter_checksum(path) -> str:
    path = Path(path)
    digest = hashlib.sha256()
    for name in ("adapter_config.json", "adapter_model.safetensors"):
        digest.update((path / name).read_bytes())
    return digest.hexdigest()


def inspect_adapter(path) -> dict:
    """Rank and wrapped modules of any PEFT adapter on disk, real or synthetic.
    Used to check a public adapter qualifies for the gate (R10)."""
    path = Path(path)
    cfg = json.loads((path / "adapter_config.json").read_text())
    modules: set[str] = set()
    with safe_open(str(path / "adapter_model.safetensors"), framework="numpy") as f:
        keys = list(f.keys())
    for key in keys:
        parts = key.split(".")
        if "lora_A" in parts:
            modules.add(parts[parts.index("lora_A") - 1])
    return {"rank": cfg["r"], "target_modules": sorted(modules), "tensors": len(keys)}


def real_adapter_qualifies(adapter_config: dict, *, rank: int, target_modules) -> tuple[bool, str]:
    """Whether a public adapter can stand in the equivalence gate (R10).

    Its rank must not exceed `max_lora_rank`, because the kernel runs at the
    buffer rank and a larger adapter would not load. Its modules must be a
    subset of the fixed set, so it occupies the same wrapped layers."""
    if adapter_config.get("peft_type") != "LORA":
        return False, f"peft_type is {adapter_config.get('peft_type')!r}, not LORA"
    r = adapter_config.get("r")
    if not isinstance(r, int) or r > rank:
        return False, f"rank {r!r} exceeds max_lora_rank {rank}"
    modules = adapter_config.get("target_modules") or []
    if isinstance(modules, str):
        return False, f"target_modules is a pattern {modules!r}, not a list"
    extra = sorted(set(modules) - set(target_modules))
    if extra:
        return False, f"targets modules outside the fixed set: {extra}"
    return True, "qualifies"


def select_real_adapters(candidates, *, rank: int, target_modules, count: int) -> dict:
    """Pick `count` qualifying public adapters, deterministically: sorted by
    repo id, so rerunning the search cannot quietly pick different adapters.
    `candidates` is [{"id", "sha", "config"}]; every rejection keeps its reason."""
    selected, rejected = [], {}
    for c in sorted(candidates, key=lambda c: c["id"]):
        ok, reason = real_adapter_qualifies(c["config"], rank=rank, target_modules=target_modules)
        if ok and len(selected) < count:
            selected.append((c["id"], c["sha"]))
        elif not ok:
            rejected[c["id"]] = reason
    return {"selected": selected, "rejected": rejected, "enough": len(selected) == count}
