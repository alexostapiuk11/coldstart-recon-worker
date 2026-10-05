"""The pre-registration is one thing in two places: `multilora/prereg_values.py`,
which the code runs on, and `docs/experiment-a5.md`, which a reader sees. These
tests fail if they disagree, or if a value that reconnaissance determined was
written down differently from what reconnaissance measured."""

import json
from pathlib import Path

from multilora.prereg import prereg_table
from multilora.prereg_values import PREREG

REPO = Path(__file__).resolve().parents[1]
DOC = REPO / "docs" / "experiment-a5.md"
CANDIDATES = REPO / "fixtures" / "a5" / "real_adapter_candidates.json"
REPORT = REPO / "fixtures" / "a5" / "recon_report.json"


def test_the_document_embeds_the_exact_values_the_code_runs_on():
    assert prereg_table(PREREG) in DOC.read_text()


def test_the_gate_uses_the_adapters_the_search_selected():
    selected = [tuple(x) for x in json.loads(CANDIDATES.read_text())["selected"]]
    assert selected == list(PREREG.real_adapters)


def test_the_request_shape_is_the_measured_prompt_and_sixteen_tokens():
    tokens = json.loads(REPORT.read_text())["request_shape_prompt_tokens"]
    assert len(tokens) == 1, f"the tokenizer gave different counts across probes: {tokens}"
    args = list(PREREG.bench_dataset_args)
    assert args[args.index("--random-input-len") + 1] == str(tokens[0])
    assert args[args.index("--random-output-len") + 1] == "16"
    assert PREREG.request_tokens == tokens[0] + 16
