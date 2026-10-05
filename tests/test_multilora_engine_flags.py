"""Every flag artifact 5 passes exists in the pinned engine and client.

Reads the help text reconnaissance captured from the image itself
(fixtures/a5/help.json). A flag vLLM renamed or never had would otherwise
surface as an engine that refuses to start on the first paid instance."""

import json
from pathlib import Path

from multilora.prereg_values import PREREG
from multilora.serving import BENCH_FLAGS, ENGINE_FLAGS, SPECIALIZE_FLAG

HELP = Path(__file__).resolve().parents[1] / "fixtures" / "a5" / "help.json"


def _text(key: str) -> str:
    out = json.loads(HELP.read_text())["outcome"]["payload"][key]
    return out["stdout"] + out["stderr"]


def test_every_engine_flag_the_worker_passes_exists():
    needed = [f for f in ENGINE_FLAGS if f != SPECIALIZE_FLAG or PREREG.include_diagnostic]
    assert [f for f in needed if f not in _text("serve_help")] == []


def test_every_bench_flag_the_phases_need_exists():
    assert [f for f in BENCH_FLAGS if f not in _text("bench_help")] == []
