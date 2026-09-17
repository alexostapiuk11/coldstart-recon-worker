import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _build(tmp_path):
    out = tmp_path / "index.html"
    r = subprocess.run(
        [sys.executable, "scripts/build_explainer.py", "--out", str(out)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    return out.read_text()


def test_build_leaves_no_unsubstituted_placeholders(tmp_path):
    html = _build(tmp_path)
    assert "{{" not in html, "a placeholder survived the build"


def test_build_substitutes_a_number_from_committed_data(tmp_path):
    html = _build(tmp_path)
    assert "39.4" in html  # arm C median, from analysis.json


def test_build_inlines_the_chart_as_svg_not_a_link(tmp_path):
    html = _build(tmp_path)
    assert "<svg" in html
    assert ".png" not in html


def test_build_inlines_the_spine_with_its_group_ids_intact(tmp_path):
    """The spine lives in its own file, but must reach the page inline.

    And it must arrive with its ids unchanged: the scroll choreography looks
    the zone and clock groups up by literal id, so an id-namespacing pass like
    the one charts get would leave a diagram that renders and never lights.
    """
    page = tmp_path / "page.html"
    # The diagram labels a vLLM step "size KV cache", so the page it lands in
    # owes that definition. Carrying it here keeps this test about inlining
    # rather than about the jargon gate -- but it is worth seeing that the gate
    # reaches into the spine at all.
    page.write_text(
        "<p>a KV cache is per-conversation scratch space the model keeps on the"
        " GPU while generating</p><div>{{spine}}</div>"
    )
    out = tmp_path / "spine.html"
    r = subprocess.run(
        [sys.executable, "scripts/build_explainer.py", "--page", str(page), "--out", str(out)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    html = out.read_text()
    assert '<svg id="spine"' in html
    for group in ("zone-1", "zone-7", "clock-A", "clock-C", "edge-1"):
        assert f'id="{group}"' in html, f"{group} did not survive the build"


def test_build_fails_loudly_on_an_unknown_placeholder(tmp_path):
    bad = REPO / "explainer" / "_bad.html"
    bad.write_text("{{not_a_key}}")
    try:
        r = subprocess.run(
            [
                sys.executable,
                "scripts/build_explainer.py",
                "--page",
                str(bad),
                "--out",
                str(tmp_path / "x.html"),
            ],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
        )
        assert r.returncode != 0
        assert "not_a_key" in r.stderr
    finally:
        bad.unlink()


def test_build_escapes_html_special_characters_in_a_code_excerpt(tmp_path):
    """An excerpt carrying `<` must reach the page as `&lt;`, not as markup.

    The default page's excerpt happens to contain no HTML-special character,
    so without this the escaping is never exercised and could be dropped
    without a single test turning red. `checks-rtt-floor` has both `<` and `>`.
    """
    page = tmp_path / "page.html"
    page.write_text("<pre><code>{{excerpt:checks-rtt-floor}}</code></pre>")
    out = tmp_path / "escaped.html"
    r = subprocess.run(
        [sys.executable, "scripts/build_explainer.py", "--page", str(page), "--out", str(out)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    html = out.read_text()
    assert "&lt;" in html
    body = html[len("<pre><code>") : -len("</code></pre>")]
    assert "<" not in body, "an unescaped angle bracket would be parsed as a tag"
