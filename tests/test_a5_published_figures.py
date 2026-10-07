"""The figures artifact 5's post links are the ones its committed analysis
produces. Same reasoning as tests/test_published_figures.py for artifact 1:
a stale PNG is as broken a claim as a stale number, and nothing else in the
suite can see it. Renders are deterministic (verified 2026-09-26: two renders
of one analysis are byte-identical), so the comparison is exact."""

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PUBLISHED = REPO / "docs" / "figures" / "a5"
ANALYSIS = REPO / "data" / "a5" / "analysis.json"
FIGURES = ("throughput_ttft", "kv_capacity", "equivalence", "cost_per_tenant")


@pytest.fixture(scope="module")
def fresh(tmp_path_factory):
    out = tmp_path_factory.mktemp("a5-figures")
    done = subprocess.run(
        [sys.executable, "scripts/a5_render_figures.py", "--analysis", str(ANALYSIS),
         "--out", str(out)],
        cwd=REPO, capture_output=True, text=True, check=False,
    )
    assert done.returncode == 0, done.stderr
    return out


@pytest.mark.parametrize("name", [f"{f}{s}" for f in FIGURES for s in ("", "-phone")])
def test_the_published_figure_matches_a_fresh_render(fresh, name):
    published = PUBLISHED / f"{name}.png"
    assert published.read_bytes() == (fresh / f"{name}.png").read_bytes(), (
        f"{published} differs from a fresh render of {ANALYSIS}; re-render with "
        "scripts/a5_render_figures.py and look at it before committing"
    )


def test_git_tracks_every_published_figure():
    tracked = subprocess.run(
        ["git", "ls-files", str(PUBLISHED.relative_to(REPO))],
        cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout.split()
    expected = {f"docs/figures/a5/{f}{s}.png" for f in FIGURES for s in ("", "-phone")}
    assert expected <= set(tracked)
