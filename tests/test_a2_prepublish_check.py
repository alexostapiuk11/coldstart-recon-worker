"""scripts/a2_prepublish_check.py refuses artifact 2's post while a placeholder stands.

The date's refusal is tested on the real files: until the owner sets the date the
check must fail, and a test that only fed it doctored copies could pass while the
real post shipped with "PUBLICATION-DATE" in its byline. The spend is recorded
(docs/spend-a2.md), so its refusal is tested on a doctored copy that puts the
placeholder and the null spend back.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "a2_prepublish_check.py"
POST = REPO / "docs" / "post-a2.md"
ANALYSIS = REPO / "data" / "a2" / "post-analysis.json"
BYLINE = "· PUBLICATION-DATE ·"
SPEND_LINE = "SPEND-PENDING: the owner reads the RunPod console before publication."


def _run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
                          cwd=REPO, check=False)


def _write(tmp_path, post_text: str, spend="real") -> tuple[str, str]:
    post = tmp_path / "post.md"
    post.write_text(post_text)
    analysis = json.loads(ANALYSIS.read_text())
    if spend is None:
        analysis["spend"] = None
    a = tmp_path / "analysis.json"
    a.write_text(json.dumps(analysis))
    return str(post), str(a)


def test_the_real_post_is_refused_for_its_date_only():
    r = _run()
    assert r.returncode != 0
    out = r.stdout + r.stderr
    assert "PUBLICATION-DATE" in out
    assert "SPEND-PENDING" not in out and "spend is null" not in out
    assert "ok" not in out.split()


def test_a_post_with_the_date_set_passes(tmp_path):
    # What the owner does: the byline's date. The header comment, which names both
    # placeholders to document them, is left as it is and must not be refused.
    text = POST.read_text()
    assert text.count(BYLINE) == 1
    post, a = _write(tmp_path, text.replace(BYLINE, "· 2026-10-20 ·"))
    r = _run("--post", post, "--analysis", a)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.strip() == "ok"


def test_a_spend_placeholder_and_a_null_spend_are_refused(tmp_path):
    text = POST.read_text().replace(BYLINE, "· 2026-10-20 ·") + "\n" + SPEND_LINE + "\n"
    post, a = _write(tmp_path, text, spend=None)
    r = _run("--post", post, "--analysis", a)
    assert r.returncode != 0
    out = r.stdout + r.stderr
    assert "SPEND-PENDING" in out and "spend is null" in out
    assert "PUBLICATION-DATE" not in out


def test_a_placeholder_outside_the_header_comment_is_still_refused(tmp_path):
    post, a = _write(tmp_path, POST.read_text().replace(BYLINE, "· 2026-10-20 ·")
                     + "\n<!-- a note -->\nPUBLICATION-DATE\n")
    r = _run("--post", post, "--analysis", a)
    assert r.returncode != 0 and "PUBLICATION-DATE" in r.stdout + r.stderr


def test_each_problem_is_named_on_its_own(tmp_path):
    # Only the spend left null: the two placeholders are gone, so only the spend is named.
    post, a = _write(tmp_path, POST.read_text().replace(BYLINE, "· 2026-10-20 ·"), spend=None)
    r = _run("--post", post, "--analysis", a)
    assert r.returncode != 0
    out = r.stdout + r.stderr
    assert "spend" in out and "PUBLICATION-DATE" not in out and "SPEND-PENDING" not in out
