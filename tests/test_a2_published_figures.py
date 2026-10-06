"""Artifact 2's published figures are a fresh render's bytes, tracked, with phone copies."""

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PUB = REPO / "docs" / "figures" / "a2"
NAMES = ("attempts", "load_balancer", "host_speed", "simulator_answer", "service_curve")


@pytest.fixture(scope="module")
def fresh(tmp_path_factory):
    out = tmp_path_factory.mktemp("render")
    subprocess.run([sys.executable, str(REPO / "scripts" / "a2_render_post_figures.py"),
                    "--out", str(out)], check=True, cwd=REPO,
                   env={"PYTHONDONTWRITEBYTECODE": "1", "PATH": "/usr/bin:/bin",
                        "MPLBACKEND": "Agg"})
    return out


@pytest.mark.parametrize("name", NAMES)
def test_published_figure_matches_a_fresh_render(fresh, name):
    assert (PUB / f"{name}.png").read_bytes() == (fresh / f"{name}.png").read_bytes()


@pytest.mark.parametrize("name", NAMES)
def test_phone_variant_is_published_and_tracked(name):
    for f in (f"{name}.png", f"{name}-phone.png"):
        assert (PUB / f).exists()
        tracked = subprocess.run(["git", "ls-files", "--error-unmatch", str(PUB / f)],
                                 cwd=REPO, capture_output=True, check=False)
        assert tracked.returncode == 0, f
