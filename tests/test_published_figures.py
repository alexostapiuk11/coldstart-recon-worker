"""The figures the post links to must be the ones the committed data produces.

`build/` is gitignored, so the four body figures a reader sees are the copies in
`docs/figures/`. Copies rot: a figure fix lands in `coldstart/analysis/figures.py`,
the test suite goes green, and the published PNG still shows the old chart. The
whole claim of this artifact is that every published thing re-derives from
`data/campaign.jsonl`, and a stale image is exactly as much a broken claim as a
stale number -- with the added property that nothing else in the suite can see it.

The renders are deterministic (the bootstrap is seeded and matplotlib writes the
same bytes for the same figure), which is what makes an exact comparison possible
rather than an approximate one.

The `*-phone.png` variants are downscales of these four, produced by the
inspection step in the campaign plan. They are not re-derived here: if the four
sources are byte-identical, their downscales are too.
"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PUBLISHED = REPO / "docs" / "figures"
STORE = REPO / "data" / "campaign.jsonl"
FIGURES = ("waterfall", "warmup", "ecdf", "per_host")


@pytest.fixture(scope="module")
def freshly_rendered(tmp_path_factory):
    """Render through the published path -- the script a reader is told to run --
    rather than by calling the figure functions directly, so a defect in the
    script's partitioning or row selection is caught too."""
    out = tmp_path_factory.mktemp("figures")
    result = subprocess.run(
        [sys.executable, "scripts/render_figures.py", "--store", str(STORE), "--out", str(out)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"render_figures.py failed:\n{result.stderr}"
    return out


@pytest.mark.parametrize("name", FIGURES)
def test_published_figure_matches_a_fresh_render(name, freshly_rendered):
    published = PUBLISHED / f"{name}.png"
    assert published.exists(), (
        f"{published.relative_to(REPO)} is missing -- docs/post.md links to it. "
        "Re-render and copy it in; see docs/runbook.md."
    )
    rendered = freshly_rendered / f"{name}.png"
    assert published.read_bytes() == rendered.read_bytes(), (
        f"{published.relative_to(REPO)} is not what the committed data renders "
        "today. The published figure is stale: re-render and copy it in "
        "(docs/runbook.md), or explain why the render changed."
    )


@pytest.mark.parametrize("name", FIGURES)
def test_the_post_links_the_published_figure(name):
    post = (REPO / "docs" / "post.md").read_text()
    assert f"(figures/{name}.png)" in post, (
        f"docs/post.md does not link figures/{name}.png. A body figure that the "
        "post does not reference is either an unpublished figure or a dead file."
    )


@pytest.mark.parametrize("name", FIGURES)
def test_phone_variant_is_published_for_inspection(name):
    """Spec 7 requires the figures to be legible on a phone, and the campaign
    plan's inspection step downscales each to 375 px to check it. Committing the
    downscales is what makes that check auditable rather than asserted."""
    phone = PUBLISHED / f"{name}-phone.png"
    assert phone.exists(), (
        f"{phone.relative_to(REPO)} is missing -- the phone-width inspection "
        "artifact for this figure. See docs/runbook.md."
    )


def test_published_figures_directory_is_not_gitignored():
    """The defect this whole file exists because of: build/ is gitignored, so
    the four figures the post linked were untracked and a reader cloning the
    repo got four broken images."""
    result = subprocess.run(
        ["git", "check-ignore", str(PUBLISHED / "waterfall.png")],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0, (
        "docs/figures/ is gitignored, so the post's figures will not be "
        "published. This is the exact defect that made docs/post.md link into "
        "the ignored build/ directory."
    )


def test_git_tracks_every_published_figure():
    for name in FIGURES:
        for suffix in ("", "-phone"):
            rel = f"docs/figures/{name}{suffix}.png"
            result = subprocess.run(
                ["git", "ls-files", "--error-unmatch", rel],
                cwd=REPO,
                capture_output=True,
                text=True,
                check=False,
            )
            assert result.returncode == 0, (
                f"{rel} is not tracked by git. It exists locally, so the post "
                "renders on this machine and nowhere else."
            )
