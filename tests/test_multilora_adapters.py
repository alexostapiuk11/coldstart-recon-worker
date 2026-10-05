import json

import numpy as np
import pytest
from safetensors.numpy import load_file

from multilora.adapters import (
    adapter_checksum,
    adapter_parameter_count,
    inspect_adapter,
    module_shapes,
    write_synthetic_adapter,
)

TINY = {
    "hidden_size": 8,
    "num_attention_heads": 2,
    "num_key_value_heads": 1,
    "head_dim": 4,
    "intermediate_size": 16,
    "num_hidden_layers": 2,
}
QWEN3_4B_SHAPE = {
    "hidden_size": 2560,
    "num_attention_heads": 32,
    "num_key_value_heads": 8,
    "head_dim": 128,
    "intermediate_size": 9728,
    "num_hidden_layers": 36,
}
ALL = ("q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj")


def test_qwen3_4b_rank_16_matches_the_amendments_size_estimate():
    """Amendment §3c: ~33.0M parameters, ~63 MiB at fp16 per adapter."""
    params = adapter_parameter_count(QWEN3_4B_SHAPE, 16, ALL)
    assert params == 33_030_144
    assert params * 2 / 2**20 == pytest.approx(63.0, abs=0.1)


def test_grouped_query_attention_shrinks_k_and_v():
    shapes = module_shapes(TINY)
    assert shapes["q_proj"] == (8, 8)
    assert shapes["k_proj"] == (8, 4)
    assert shapes["down_proj"] == (16, 8)


def test_the_written_adapter_has_peft_names_and_shapes(tmp_path):
    write_synthetic_adapter(
        tmp_path / "a00", config=TINY, base_model="m", rank=3, target_modules=ALL, seed=1
    )
    tensors = load_file(str(tmp_path / "a00" / "adapter_model.safetensors"))
    assert len(tensors) == 2 * 7 * 2
    a = tensors["base_model.model.model.layers.1.self_attn.k_proj.lora_A.weight"]
    b = tensors["base_model.model.model.layers.1.self_attn.k_proj.lora_B.weight"]
    assert a.shape == (3, 8) and b.shape == (4, 3)
    assert a.dtype == np.float16
    assert "base_model.model.model.layers.0.mlp.up_proj.lora_B.weight" in tensors
    cfg = json.loads((tmp_path / "a00" / "adapter_config.json").read_text())
    assert cfg["r"] == 3 and cfg["peft_type"] == "LORA"
    assert cfg["target_modules"] == sorted(ALL)


def test_the_same_seed_writes_the_same_bytes(tmp_path):
    kw = {"config": TINY, "base_model": "m", "rank": 2, "target_modules": ALL}
    one = write_synthetic_adapter(tmp_path / "x", seed=4, **kw)
    two = write_synthetic_adapter(tmp_path / "y", seed=4, **kw)
    other = write_synthetic_adapter(tmp_path / "z", seed=5, **kw)
    assert one == two != other
    assert adapter_checksum(tmp_path / "x") == one


def test_inspect_reads_rank_and_modules_back(tmp_path):
    write_synthetic_adapter(
        tmp_path / "a", config=TINY, base_model="m", rank=2,
        target_modules=("q_proj", "v_proj"), seed=0,
    )
    assert inspect_adapter(tmp_path / "a") == {
        "rank": 2, "target_modules": ["q_proj", "v_proj"], "tensors": 8,
    }


def test_unsupported_modules_are_refused(tmp_path):
    with pytest.raises(ValueError, match="lm_head"):
        write_synthetic_adapter(
            tmp_path / "a", config=TINY, base_model="m", rank=2,
            target_modules=("lm_head",), seed=0,
        )


def test_a_real_adapter_qualifies_only_within_rank_and_modules():
    from multilora.adapters import real_adapter_qualifies

    ok = {"peft_type": "LORA", "r": 8, "target_modules": ["q_proj", "v_proj"]}
    assert real_adapter_qualifies(ok, rank=16, target_modules=ALL) == (True, "qualifies")
    too_big = {**ok, "r": 32}
    assert real_adapter_qualifies(too_big, rank=16, target_modules=ALL)[0] is False
    outside = {**ok, "target_modules": ["q_proj", "lm_head"]}
    assert "lm_head" in real_adapter_qualifies(outside, rank=16, target_modules=ALL)[1]
    pattern = {**ok, "target_modules": "all-linear"}
    assert real_adapter_qualifies(pattern, rank=16, target_modules=ALL)[0] is False


def test_selection_is_deterministic_and_keeps_every_rejection_reason():
    from multilora.adapters import select_real_adapters

    good = {"peft_type": "LORA", "r": 16, "target_modules": ["q_proj"]}
    cands = [
        {"id": "z/one", "sha": "1", "config": good},
        {"id": "a/two", "sha": "2", "config": good},
        {"id": "m/big", "sha": "3", "config": {**good, "r": 64}},
    ]
    res = select_real_adapters(cands, rank=16, target_modules=ALL, count=2)
    assert res["selected"] == [("a/two", "2"), ("z/one", "1")]
    assert set(res["rejected"]) == {"m/big"} and res["enough"]
    assert select_real_adapters(cands, rank=16, target_modules=ALL, count=3)["enough"] is False
