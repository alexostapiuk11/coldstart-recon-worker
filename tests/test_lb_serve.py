"""lb_serve starts the service curve's exact engine, plus the middleware and nothing else."""

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "worker"))

import lb_serve

CURVE = json.loads((REPO / "data" / "a2" / "service-curve.json").read_text())
ENV = {"MODEL_ID": "Qwen/Qwen3-8B", "MODEL_REVISION": "b968826d9c46dd6066d109eabc6255188de91218",
       "MAX_MODEL_LEN": "8192", "PORT": "8000"}


def test_the_command_is_the_curves_served_cmd_plus_the_middleware():
    assert lb_serve.command(ENV) == [*CURVE["served_cmd"], "--middleware", lb_serve.MIDDLEWARE]


def test_the_port_comes_from_the_platform():
    cmd = lb_serve.command({**ENV, "PORT": "9001"})
    assert cmd[cmd.index("--port") + 1] == "9001"


@pytest.mark.parametrize("name", ["MODEL_ID", "MODEL_REVISION", "MAX_MODEL_LEN", "PORT"])
def test_a_missing_variable_is_refused_by_name(name):
    with pytest.raises(KeyError, match=name):
        lb_serve.command({k: v for k, v in ENV.items() if k != name})


def test_the_dockerfile_copies_both_files():
    text = (REPO / "worker" / "Dockerfile").read_text()
    assert "COPY worker/lb_serve.py /opt/lb_serve.py" in text
    assert "COPY worker/a2_middleware.py /opt/a2_middleware.py" in text


def test_main_execs_vllm_with_the_command(monkeypatch):
    calls = []
    monkeypatch.setattr(lb_serve.os, "execvp", lambda f, a: calls.append((f, a)))
    monkeypatch.setattr(lb_serve.os, "environ", dict(ENV))
    lb_serve.main()
    assert calls == [("vllm", lb_serve.command(ENV))]
