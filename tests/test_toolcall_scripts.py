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
from toolcall.numbers import numbers_block

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
    assert render.main(["--analysis", str(stub_analysis), "--out", str(out),
                        "--allow-stub"]) == 0
    expected = {f"{name}{suffix}.png" for name in FIGURES for suffix in ("", "-phone")}
    assert len(expected) == 8
    assert {p.name for p in out.iterdir()} == expected
    for name in FIGURES:
        with Image.open(out / f"{name}.png") as full, \
                Image.open(out / f"{name}-phone.png") as phone:
            assert phone.width == PHONE_WIDTH_PX == 375
            assert full.width > phone.width
    assert plt.get_fignums() == []
    said = capsys.readouterr().out
    assert said.count("[ok]") == 4
    assert "stub layouts" in said


def test_two_renders_of_one_analysis_are_byte_identical(stub_analysis, tmp_path):
    for sub in ("a", "b"):
        assert render.main(["--analysis", str(stub_analysis), "--out", str(tmp_path / sub),
                            "--allow-stub"]) == 0
    for name in FIGURES:
        for suffix in ("", "-phone"):
            f = f"{name}{suffix}.png"
            assert (tmp_path / "a" / f).read_bytes() == (tmp_path / "b" / f).read_bytes(), f


def test_the_stub_analysis_carries_its_own_not_data_marker(stub_analysis):
    a = json.loads(stub_analysis.read_text())
    assert a["NOT_DATA"] == "stub output from toolcall.stub; never publish"
    assert (stub_analysis.parent / "STUB").exists()


def test_the_renderer_refuses_a_stub_analysis_without_allow_stub(stub_analysis, tmp_path, capsys):
    out = tmp_path / "figures"
    assert render.main(["--analysis", str(stub_analysis), "--out", str(out)]) != 0
    assert "NOT_DATA" in capsys.readouterr().err
    assert not out.exists()


def test_numbers_block_refuses_a_stub_analysis(stub_analysis):
    with pytest.raises(ValueError, match="NOT_DATA"):
        numbers_block(json.loads(stub_analysis.read_text()))


def test_the_renderer_names_the_keys_an_old_analysis_lacks_and_writes_nothing(
        stub_analysis, tmp_path):
    a = json.loads(stub_analysis.read_text())
    del a["recovery_reps"]
    del a["flakiness"]["units"]
    old = tmp_path / "old.json"
    old.write_text(json.dumps(a))
    out = tmp_path / "figures"
    with pytest.raises(ValueError, match=r"recovery_reps.*flakiness\.units|flakiness\.units.*"
                                         r"recovery_reps") as e:
        render.main(["--analysis", str(old), "--out", str(out), "--allow-stub"])
    assert "re-analys" in str(e.value)
    assert not out.exists()


def test_stub_demo_refuses_a_non_empty_out(tmp_path, capsys):
    out = tmp_path / "already"
    out.mkdir()
    keep = out / "keep.txt"
    keep.write_text("mine")
    assert stub_demo.main(["--out", str(out)]) != 0
    assert f"{out} is not empty; choose a new --out" in capsys.readouterr().err
    assert [p.name for p in out.iterdir()] == ["keep.txt"]
    assert keep.read_text() == "mine"


def test_stub_demo_refuses_an_out_that_is_a_file(tmp_path, capsys):
    out = tmp_path / "afile"
    out.write_text("mine")
    assert stub_demo.main(["--out", str(out)]) != 0
    assert "choose a new --out" in capsys.readouterr().err
    assert out.read_text() == "mine"


@pytest.mark.parametrize("argv", [["--iterations", "99"], ["--calls", "5", "--no-calls", "2"],
                                  ["--calls", "-1"]])
def test_stub_demo_bad_arguments_exit_cleanly_and_leave_no_directory(tmp_path, capsys, argv):
    out = tmp_path / "never"
    with pytest.raises(SystemExit) as e:
        stub_demo.main(["--out", str(out), *argv])
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert "Traceback" not in err and "error:" in err
    assert not out.exists()

