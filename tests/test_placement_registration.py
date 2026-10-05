"""Step 2's values: rendered once from the rules, into code, design files and
the pre-registration, and re-derivable from the committed inputs."""

import importlib.util
import json
from pathlib import Path

import pytest
from a4_examples import example_report
from test_placement_inputs_step2 import _cell

from harness.store import JsonlStore
from placement.registration import (
    SECTION,
    design_files,
    mismatches,
    render_doc,
    render_module,
    values,
)
from placement.step2 import measurement_design
from placement_measure.records import A4Run

REPO = Path(__file__).resolve().parents[1]
SCREEN = {"chosen": {"offered_gpus": 2.0, "slo_swap_multiple": 4.0}}
RATE, PROVENANCE = 0.69, "RunPod serverless RTX 4090 flex price, read from the console 2026-10-14"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _values(report=None):
    return values(measurement_design(report or example_report()), SCREEN, rate=RATE,
                  provenance=PROVENANCE)


def test_the_values_are_the_rules_applied_to_the_report_and_the_screen():
    v = _values()
    assert v["MODEL"] == "Qwen/Qwen3-4B" and (v["INPUT_LEN"], v["OUTPUT_LEN"]) == (768, 256)
    assert v["OFFERED_GPUS"] == 2.0 and v["SLO_SWAP_MULTIPLE"] == 4.0
    assert v["SWAP_COLD_STATES"] == (True, False) and v["SLEEP_MEASURED"] is True
    with pytest.raises(ValueError, match="positive"):
        values(measurement_design(example_report()), SCREEN, rate=0.0, provenance=PROVENANCE)
    with pytest.raises(ValueError, match="provenance"):
        values(measurement_design(example_report()), SCREEN, rate=RATE, provenance=" ")


def test_the_module_holds_literals_that_read_back_as_the_values():
    v = _values()
    namespace: dict = {}
    exec(render_module(v, "2026-10-14"), namespace)  # noqa: S102 -- our own rendered literals
    assert {k: namespace[k] for k in v} == v
    assert mismatches({k: namespace[k] for k in v}, v) == []


def test_mismatches_name_every_difference():
    v = _values()
    drifted = {**v, "INPUT_LEN": 1792}
    drifted.pop("HELD_OUT")
    found = mismatches(drifted, v)
    assert len(found) == 2 and found[0].startswith("HELD_OUT") and "1792" in found[1]


def test_the_doc_section_states_every_decision():
    v = _values()
    doc = render_doc(v, "2026-10-14")
    assert doc.startswith(SECTION) and "Committed 2026-10-14" in doc
    for text in ("`Qwen/Qwen3-4B`", "`768` input", "`18,100` tokens", "`(1, 2, 4, 8, 16, 32)`",
                 "`('pair:o12:n24', 'pair:o24:n12')`", "swaps measured cold and warm",
                 "`0.69` dollars", PROVENANCE):
        assert text in doc, text


def test_a_fallback_without_a_solo_reading_says_so():
    report = example_report()
    report["go_no_go"]["primary"]["passed"] = False
    assert "not measured by reconnaissance" in render_doc(_values(report), "2026-10-14")


def test_the_design_files_load_back_as_the_designs():
    measurement = measurement_design(example_report())
    files = design_files(measurement)
    assert set(files) == {"cells", "swaps", "sleep"}
    a4_measure = _load("a4_measure")
    for kind, name in (("cell", "cells"), ("swap", "swaps"), ("sleep", "sleep")):
        path_json = json.loads(json.dumps(files[name]))
        design = a4_measure.DESIGNS[kind](**{
            k: tuple(tuple(x) if isinstance(x, list) else x for x in val)
            if isinstance(val, list) else val for k, val in path_json.items()})
        assert design == measurement[name], name


def _root(tmp_path):
    (tmp_path / "fixtures" / "a4").mkdir(parents=True)
    (tmp_path / "data" / "a4").mkdir(parents=True)
    (tmp_path / "docs").mkdir()
    (tmp_path / "placement").mkdir()
    (tmp_path / "fixtures/a4/recon-report.json").write_text(json.dumps(example_report()))
    (tmp_path / "data/a4/screen.json").write_text(json.dumps(SCREEN))
    # The document as it stands before step 2's values: after publication the
    # repository's own copy has them, and the script refuses a second section.
    doc = (REPO / "docs" / "experiment-a4.md").read_text().split(SECTION)[0]
    (tmp_path / "docs" / "experiment-a4.md").write_text(doc)
    return tmp_path


def test_the_script_writes_everything_once(tmp_path):
    root = _root(tmp_path)
    script = _load("a4_step2")
    args = ["--root", str(root), "values", "--rate", str(RATE), "--provenance", PROVENANCE,
            "--date", "2026-10-14"]
    script.main(args)
    assert (root / "placement/registered.py").read_text() == render_module(_values(), "2026-10-14")
    assert {p.name for p in (root / "data/a4/designs").iterdir()} == {
        "cells.json", "swaps.json", "sleep.json"}
    doc = (root / "docs/experiment-a4.md").read_text()
    assert doc.count(SECTION) == 1 and doc.index("## Step 2, part 1") < doc.index(SECTION)
    with pytest.raises(SystemExit, match="already has"):
        script.main(args)


def _write_measured(root, measurement):
    """Every cell the registered grids need, three valid repeats each, with
    latency 1 + 0.1 x own, and eight cold and eight warm compile-hit swaps."""
    cells = JsonlStore(root / "data/a4/cells.jsonl", A4Run)
    conditions = ([f"solo:o{c}" for c in measurement["solo_levels"]]
                  + [f"pair:o{o}:n{n}" for o in measurement["own_levels"]
                     for n in measurement["neighbour_levels"]])
    for condition in conditions:
        own = int(condition.split(":")[1][1:])
        for i in range(3):
            cells.append(_cell(condition, 1.0 + 0.1 * own, i=i))
    swaps = JsonlStore(root / "data/a4/swaps.jsonl", A4Run)
    for i in range(16):
        cold = i % 2 == 0
        swaps.append(A4Run(
            run_id=f"s{i}", run_index=i, condition=f"swap:a>b:{'cold' if cold else 'warm'}",
            block_index=0, kind="swap", outcome="ok", failure=None, clock_A={}, source="stub",
            output={"swap_s": 30.0 + i, "cache_s": 2.0, "b": {"facts": {"s4b_s": 0.3}}}))


def test_the_replay_design_is_the_first_feasible_draw_on_the_measured_curve(tmp_path):
    root = _root(tmp_path)
    measurement = measurement_design(example_report())
    _write_measured(root, measurement)
    design = _load("a4_step2").main(["--root", str(root), "replay", "--cells",
                                     "data/a4/cells.jsonl", "--swaps", "data/a4/swaps.jsonl"])
    assert tuple(design["tenants"]) == measurement["validation_set"]
    assert design["max_in_flight"] == measurement["solo_levels"][-1]
    saved = json.loads((root / "data/a4/designs/replay.json").read_text())
    assert saved == json.loads(json.dumps(design))
    check = json.loads((root / "data/a4/designs/replay-check.json").read_text())
    # The cold compile-hit swaps are 30, 32, ..., 44 s: median 37, plus 2 s of eviction.
    assert check["swap_s"] == pytest.approx(39.0)
    assert check["checks"][-1]["feasible"]
