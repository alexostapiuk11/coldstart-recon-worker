import importlib.util
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pytest
from PIL import Image

from harness.figure_guards import PHONE_WIDTH_PX
from toolcall.figures import FIGURES

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


stub_demo = _load("a3_stub_demo")
render = _load("a3_render_figures")


@pytest.fixture(scope="module")
def stub_analysis(tmp_path_factory) -> Path:
    """One small stub analysis (NOT DATA), shared by the tests that need one. 60 call
    scenarios is the least that leaves recovery enough scenarios for all four figures."""
    out = tmp_path_factory.mktemp("a3-stub") / "run"
    assert stub_demo.main(["--out", str(out), "--calls", "60", "--no-calls", "4",
                           "--iterations", "100"]) == 0
    return out / "analysis.json"


def test_render_writes_eight_files_and_leaves_no_figure_open(stub_analysis, tmp_path, capsys):
    plt.close("all")
    out = tmp_path / "figures"
    assert render.main(["--analysis", str(stub_analysis), "--out", str(out)]) == 0
    expected = {f"{name}{suffix}.png" for name in FIGURES for suffix in ("", "-phone")}
    assert len(expected) == 8
    assert {p.name for p in out.iterdir()} == expected
    for name in FIGURES:
        with Image.open(out / f"{name}.png") as full, \
                Image.open(out / f"{name}-phone.png") as phone:
            assert phone.width == PHONE_WIDTH_PX == 375
            assert full.width > phone.width
    assert plt.get_fignums() == []
    assert capsys.readouterr().out.count("[ok]") == 4


def test_stub_analysis_is_labelled_stub_and_has_a_marker(stub_analysis):
    assert (stub_analysis.parent / "STUB").exists()
    assert isinstance(json.loads(stub_analysis.read_text()), dict)


def test_stub_demo_refuses_a_non_empty_out(tmp_path, capsys):
    out = tmp_path / "already"
    out.mkdir()
    keep = out / "keep.txt"
    keep.write_text("mine")
    assert stub_demo.main(["--out", str(out)]) != 0
    assert f"{out} is not empty; choose a new --out" in capsys.readouterr().err
    assert [p.name for p in out.iterdir()] == ["keep.txt"]
    assert keep.read_text() == "mine"
