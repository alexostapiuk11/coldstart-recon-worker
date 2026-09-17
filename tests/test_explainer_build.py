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
