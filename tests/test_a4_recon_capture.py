import importlib.util
import json
from pathlib import Path

import pytest

from harness.submit import SubmitOutcome

ROOT = Path(__file__).resolve().parents[1]


def _script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _outcome(payload=None, error=None, diagnostics=None):
    return SubmitOutcome(clock_A={"t_submit": 0.0, "t_result": 1.0}, payload=payload, error=error,
                         diagnostics=diagnostics)


def test_the_capture_script_never_overwrites_evidence(tmp_path):
    capture = _script("a4_recon_capture").capture
    jobs = [{"label": "help", "probe": "help"}]
    capture(jobs, lambda job: _outcome({"healthy": True}), tmp_path)
    saved = json.loads((tmp_path / "help.json").read_text())
    assert saved["outcome"]["payload"] == {"healthy": True}
    with pytest.raises(SystemExit, match="overwrite"):
        capture(jobs, lambda job: _outcome({"healthy": True}), tmp_path)


def test_the_capture_script_lists_jobs_without_spending(capsys):
    _script("a4_recon_capture").main(["--list"])
    out = capsys.readouterr().out
    assert "coresidency-primary" in out and "sleep" in out


def test_the_model_class_flag_reaches_the_plan(monkeypatch):
    module = _script("a4_recon_capture")
    seen = []

    def spy(model_class):
        seen.append(model_class)
        return [{"label": "help", "probe": "help"}]

    monkeypatch.setattr(module, "recon_jobs", spy)
    module.main(["--list"])
    module.main(["--list", "--model-class", "fallback"])
    assert seen == ["Qwen/Qwen3-4B", "Qwen/Qwen3-1.7B"]
