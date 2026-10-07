"""The file artifact 5 reads, held to the contract agreed on 2026-09-26.

`_artifact_5_reads` restates artifact 5's reader rules (its plan 1, Task 13,
`a4_reference_row`): artifact 5's package is not importable from here, so its
rules are copied as a contract, and a change on either side breaks this test
or theirs."""

import importlib.util
import json
from pathlib import Path

import pytest
from a4_evaluations import DESIGN, RATE, swap_dominated, sweep

from placement.analysis import analyse
from placement.cost_file import build

REPO = Path(__file__).resolve().parents[1]
REFERENCE = {"regime": "bursty", "s": 1.0}


def _analysis(evaluations=None, reference=REFERENCE):
    result = analyse(evaluations or sweep(), DESIGN, total_rate=5.0, output_len=256, rate=RATE,
                     reference=reference)
    # `scripts/a4_analyse.py` adds `inputs` after `analyse`; the cost file reads the model from it.
    return {**result, "inputs": {"model": "Qwen/Qwen3-1.7B"}}


def _artifact_5_reads(a4: dict) -> dict:
    missing = [k for k in ("gpu_hourly_rate", "reference", "rows") if k not in a4]
    assert not missing, missing
    ref = a4["reference"]
    matches = [r for r in a4["rows"] if r["regime"] == ref["regime"] and r["s"] == ref["s"]]
    assert len(matches) == 1
    for key in ("dedicated_cost_per_tenant_month", "swapped_cost_per_tenant_month"):
        assert matches[0].get(key) is not None, key
    return matches[0]


def test_the_file_meets_artifact_5s_contract():
    result = build(_analysis())
    row = _artifact_5_reads(result)
    assert result["gpu_hourly_rate"] == 0.69 and result["n_models"] == 20
    # Swap sized 6 GPUs and dedicate 10, over 20 tenants.
    assert row["swapped_cost_per_tenant_month"] < row["dedicated_cost_per_tenant_month"]
    assert row["sleep_mode_cost_per_tenant_month"] is None
    assert len(result["rows"]) == 4 and {r["regime"] for r in result["rows"]} == {"spread", "bursty"}


def test_a_dominated_swap_at_the_reference_is_refused_not_written():
    evaluations = [*sweep()[:3], swap_dominated(1.0, "bursty")]
    with pytest.raises(ValueError, match="no swapped cost"):
        build(_analysis(evaluations))


def test_the_script_writes_the_file(tmp_path):
    analysis = tmp_path / "analysis.json"
    analysis.write_text(json.dumps(_analysis()))
    spec = importlib.util.spec_from_file_location("a4_cost_file", REPO / "scripts" / "a4_cost_file.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    out = tmp_path / "cost.json"
    module.main(["--analysis", str(analysis), "--out", str(out)])
    _artifact_5_reads(json.loads(out.read_text()))


def test_the_file_names_the_model_class_it_was_measured_on():
    """Artifact 5's figure sets its adapter bar (Qwen3-4B) beside this file's bars, so the
    file says which model they are (artifact 5's request, 2026-10-07)."""
    result = build(_analysis())
    assert result["model"] == {"id": "Qwen/Qwen3-1.7B",
                               "revision": "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e"}


def test_an_unregistered_model_is_refused_not_written_without_a_revision():
    analysis = {**_analysis(), "inputs": {"model": "Qwen/Not-A-Registered-Model"}}
    with pytest.raises(ValueError, match="not a registered checkpoint"):
        build(analysis)


def test_adding_the_model_changed_no_existing_value():
    result = build(_analysis())
    assert set(result) == {"gpu_hourly_rate", "rate_provenance", "n_models", "reference", "rows",
                           "source", "model"}
