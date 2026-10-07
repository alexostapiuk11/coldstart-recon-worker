"""The figures artifact 4's post links must be the ones its committed analysis
renders, as tests/test_published_figures.py holds artifact 1's.

`build/` is gitignored, so the published copies live in `docs/figures/a4/`.
A figure fix that lands in `placement/figures.py` without a re-render leaves a
stale PNG that nothing else in the suite can see. Renders are deterministic
(`tests/test_placement_figures.py` checks it), so the comparison is exact."""

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PUBLISHED = REPO / "docs" / "figures" / "a4"
FIGURES = ("crossover", "deciles", "interference", "swap_stages")


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    out = tmp_path_factory.mktemp("a4-figures")
    result = subprocess.run(
        [sys.executable, "scripts/a4_render_figures.py", "--analysis", "data/a4/analysis.json",
         "--out", str(out)],
        cwd=REPO, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    return out


@pytest.mark.parametrize("name", FIGURES)
def test_the_published_figure_is_what_the_analysis_renders(name, rendered):
    published = PUBLISHED / f"{name}.png"
    assert published.exists(), f"{published.relative_to(REPO)} is missing; see plan 3's figure task"
    assert published.read_bytes() == (rendered / f"{name}.png").read_bytes(), (
        f"{published.relative_to(REPO)} is stale: re-render and copy it in, or explain why "
        "the render changed")


@pytest.mark.parametrize("name", FIGURES)
def test_the_phone_copy_is_published_for_inspection(name, rendered):
    phone = PUBLISHED / f"{name}-phone.png"
    assert phone.exists() and phone.read_bytes() == (rendered / f"{name}-phone.png").read_bytes()


@pytest.mark.parametrize("name", FIGURES)
def test_the_post_links_the_figure(name):
    post = (REPO / "docs" / "post-a4.md").read_text()
    assert f"(figures/a4/{name}.png)" in post
