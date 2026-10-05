import json
from pathlib import Path

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


BASE = "Qwen/Qwen3-4B"
EVIDENCE = Path(__file__).resolve().parents[1] / "fixtures" / "a5" / "real_adapter_candidates.json"
# A real adapter the gate can use: same rank, same modules, plain LoRA, causal LM,
# trained on exactly the pinned base. Each mutation below breaks one rule item.
VALID = {
    "peft_type": "LORA",
    "r": 16,
    "lora_alpha": 32,
    "target_modules": list(ALL),
    "task_type": "CAUSAL_LM",
    "base_model_name_or_path": BASE,
    "bias": "none",
    "modules_to_save": None,
    "use_dora": False,
    "use_rslora": False,
    "rank_pattern": {},
    "alpha_pattern": {},
    "lora_bias": False,
    "fan_in_fan_out": False,
}


def _without(key):
    return {k: v for k, v in VALID.items() if k != key}


def test_a_fully_matching_adapter_qualifies_whatever_its_alpha():
    from multilora.adapters import real_adapter_qualifies

    kw = {"rank": 16, "target_modules": ALL, "base_model": BASE}
    assert real_adapter_qualifies(VALID, **kw) == (True, "qualifies")
    # lora_alpha only scales the delta; it does not change the kernel's work
    assert real_adapter_qualifies({**VALID, "lora_alpha": 7}, **kw) == (True, "qualifies")
    # module order is irrelevant; a missing bias key means "none"; fan_in_fan_out may be None
    assert real_adapter_qualifies({**VALID, "target_modules": sorted(ALL)}, **kw)[0] is True
    assert real_adapter_qualifies(_without("bias"), **kw)[0] is True
    assert real_adapter_qualifies({**VALID, "fan_in_fan_out": None}, **kw)[0] is True


@pytest.mark.parametrize(
    "config, keyword",
    [
        ({**VALID, "peft_type": "IA3"}, "peft_type"),
        ({**VALID, "r": 8}, "rank 8 is not the gate's rank 16"),
        ({**VALID, "r": 32}, "rank 32 is not the gate's rank 16"),
        ({**VALID, "r": True}, "rank True"),
        ({**VALID, "r": "16"}, "rank '16'"),
        (_without("r"), "rank None"),
        ({**VALID, "target_modules": "all-linear"}, "pattern"),
        ({**VALID, "target_modules": tuple(ALL)}, "must be a list of module names"),
        ({**VALID, "target_modules": set(ALL)}, "must be a list of module names"),
        ({**VALID, "target_modules": dict.fromkeys(ALL, 1)}, "must be a list of module names"),
        ({**VALID, "target_modules": [["q_proj"]]}, "must be a list of module names"),
        ({**VALID, "target_modules": [*ALL, None]}, "must be a list of module names"),
        ({**VALID, "target_modules": [*ALL, 7]}, "must be a list of module names"),
        ({**VALID, "target_modules": list(ALL[:-1])}, "does not target: ['down_proj']"),
        ({**VALID, "target_modules": [*ALL, "lm_head"]}, "outside the fixed set: ['lm_head']"),
        ({**VALID, "task_type": "SEQ_CLS"}, "task_type is 'SEQ_CLS'"),
        ({**VALID, "task_type": None}, "task_type is None"),
        (_without("task_type"), "task_type is None"),
        ({**VALID, "modules_to_save": ["score"]}, "modules_to_save is ['score']"),
        ({**VALID, "use_dora": True}, "use_dora"),
        ({**VALID, "use_rslora": True}, "use_rslora"),
        ({**VALID, "rank_pattern": {"q_proj": 8}}, "rank_pattern"),
        ({**VALID, "alpha_pattern": {"q_proj": 8}}, "alpha_pattern"),
        ({**VALID, "lora_bias": True}, "lora_bias"),
        ({**VALID, "fan_in_fan_out": True}, "fan_in_fan_out"),
        ({**VALID, "bias": "all"}, "bias is 'all'"),
        ({**VALID, "base_model_name_or_path": "Qwen/Qwen3-4B-Base"}, "'Qwen/Qwen3-4B-Base'"),
        (_without("base_model_name_or_path"), "base_model_name_or_path is None"),
    ],
    ids=[
        "not-lora", "rank-8", "rank-32", "rank-bool", "rank-str", "rank-missing",
        "modules-pattern", "modules-tuple", "modules-set", "modules-dict",
        "modules-nested-list", "modules-with-none", "modules-with-int", "module-missing", "module-extra", "seq-cls", "task-none",
        "task-missing", "modules-to-save", "dora", "rslora", "rank-pattern",
        "alpha-pattern", "lora-bias", "fan-in-fan-out", "bias-all", "wrong-base",
        "base-missing",
    ],
)
def test_each_rule_rejects_with_a_reason_naming_it(config, keyword):
    from multilora.adapters import real_adapter_qualifies

    ok, reason = real_adapter_qualifies(config, rank=16, target_modules=ALL, base_model=BASE)
    assert ok is False
    assert keyword in reason


def test_a_repeated_module_name_still_matches_the_fixed_set():
    from multilora.adapters import real_adapter_qualifies

    doubled = {**VALID, "target_modules": [*ALL, "q_proj"]}
    kw = {"rank": 16, "target_modules": ALL, "base_model": BASE}
    assert real_adapter_qualifies(doubled, **kw) == (True, "qualifies")


def test_one_malformed_config_is_rejected_without_aborting_the_selection():
    from multilora.adapters import select_real_adapters

    cands = [
        {"id": "a/ok", "sha": "1", "config": VALID},
        {"id": "b/bad", "sha": "2", "config": {**VALID, "target_modules": [["q_proj"]]}},
        {"id": "c/ok", "sha": "3", "config": VALID},
    ]
    res = select_real_adapters(cands, rank=16, target_modules=ALL, count=2, base_model=BASE)
    assert res["selected"] == [("a/ok", "1"), ("c/ok", "3")]
    assert list(res["rejected"]) == ["b/bad"]
    assert "must be a list of module names" in res["rejected"]["b/bad"]
    assert res["enough"] is True


def test_the_first_failing_rule_is_the_reason_given():
    from multilora.adapters import real_adapter_qualifies

    both = {**VALID, "r": 8, "task_type": "SEQ_CLS", "base_model_name_or_path": "x"}
    reason = real_adapter_qualifies(both, rank=16, target_modules=ALL, base_model=BASE)[1]
    assert reason == "rank 8 is not the gate's rank 16"


def test_the_base_model_cannot_be_left_out():
    from multilora.adapters import real_adapter_qualifies, select_real_adapters

    with pytest.raises(TypeError):
        real_adapter_qualifies(VALID, rank=16, target_modules=ALL)
    with pytest.raises(TypeError):
        select_real_adapters([], rank=16, target_modules=ALL, count=1)


def test_selection_is_deterministic_and_keeps_every_rejection_reason():
    from multilora.adapters import select_real_adapters

    cands = [
        {"id": "z/one", "sha": "1", "config": VALID},
        {"id": "a/two", "sha": "2", "config": VALID},
        {"id": "m/small", "sha": "3", "config": {**VALID, "r": 8}},
        {"id": "b/head", "sha": "4", "config": {**VALID, "task_type": "SEQ_CLS"}},
        {"id": "y/three", "sha": "5", "config": VALID},
    ]
    kw = {"rank": 16, "target_modules": ALL, "base_model": BASE}
    res = select_real_adapters(cands, count=2, **kw)
    assert res["selected"] == [("a/two", "2"), ("y/three", "5")]
    assert res["rejected"] == {
        "b/head": "task_type is 'SEQ_CLS', not CAUSAL_LM",
        "m/small": "rank 8 is not the gate's rank 16",
    }
    assert res["enough"] is True
    assert select_real_adapters(list(reversed(cands)), count=2, **kw) == res
    short = select_real_adapters(cands, count=4, **kw)
    assert short["selected"] == [("a/two", "2"), ("y/three", "5"), ("z/one", "1")]
    assert short["enough"] is False


def test_reselection_rederives_the_choice_and_keeps_the_evidence():
    from multilora.adapters import reselect_from_evidence

    evidence = {
        "query": {"base": BASE, "rank": 16, "count": 1, "limit": 100},
        "seen": [
            {"id": "b/ok", "sha": "2", "base": BASE, "config": VALID},
            {"id": "a/rank8", "sha": "1", "base": BASE, "config": {**VALID, "r": 8}},
        ],
        "selected": [["a/rank8", "1"]],
        "rejected": {},
        "enough": True,
    }
    before = json.loads(json.dumps(evidence))
    out = reselect_from_evidence(
        evidence, rank=16, target_modules=ALL, count=1, base_model=BASE
    )
    assert evidence == before  # input untouched
    assert out["seen"] == before["seen"] and out["query"] == before["query"]
    assert out["selected"] == [["b/ok", "2"]]
    assert out["rejected"] == {"a/rank8": "rank 8 is not the gate's rank 16"}
    assert out["enough"] is True
    assert out["rule"] == "strict-v2"
    assert out["reselect"] == {
        "rank": 16, "target_modules": list(ALL), "count": 1, "base_model": BASE,
    }
    assert json.loads(json.dumps(out)) == out


def test_the_committed_selection_is_what_the_rule_picks_from_the_committed_evidence():
    """Offline: the pinned adapters follow from the committed Hub snapshot and
    this rule, so neither can change without the other."""
    from multilora.adapters import reselect_from_evidence

    evidence = json.loads(EVIDENCE.read_text())
    out = reselect_from_evidence(
        evidence, rank=16, target_modules=ALL, count=4, base_model=BASE
    )
    assert out["selected"] == evidence["selected"]
    assert out["rejected"] == evidence["rejected"]
    assert out["enough"] is True and evidence["enough"] is True
    assert evidence["rule"] == "strict-v2"
