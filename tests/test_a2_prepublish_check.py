"""scripts/a2_prepublish_check.py refuses artifact 2's post while a placeholder stands.

The refusal is tested on the real files: until the owner sets the date and the spend,
the check must fail, and a test that only fed it doctored copies could pass while the
real post shipped with "PUBLICATION-DATE" in its byline.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "a2_prepublish_check.py"
POST = REPO / "docs" / "post-a2.md"
ANALYSIS = REPO / "data" / "a2" / "post-analysis.json"


def _run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
                          cwd=REPO, check=False)


def test_the_real_post_is_refused_while_its_placeholders_stand():
    r = _run()
    assert r.returncode != 0
    out = r.stdout + r.stderr
    assert "PUBLICATION-DATE" in out and "SPEND-PENDING" in out and "spend" in out
    assert "ok" not in out.split()


def test_a_post_with_the_date_and_spend_set_passes(tmp_path):
    post = tmp_path / "post.md"
    # What the owner does: the byline's date and the spend line. The header comment, which
    # names both placeholders to document them, is left as it is and must not be refused.
    text = POST.read_text()
    byline = "· PUBLICATION-DATE ·"
    spend = "SPEND-PENDING: the owner reads the RunPod console\nbefore publication."
    assert text.count(byline) == 1 and text.count(spend) == 1
    post.write_text(text.replace(byline, "· 2026-10-20 ·").replace(spend, "$12.34 in all."))
    analysis = json.loads(ANALYSIS.read_text())
    analysis["spend"] = {"total_usd": 12.34}
    a = tmp_path / "analysis.json"
    a.write_text(json.dumps(analysis))
    r = _run("--post", str(post), "--analysis", str(a))
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.strip() == "ok"


def test_a_placeholder_outside_the_header_comment_is_still_refused(tmp_path):
    post = tmp_path / "post.md"
    post.write_text(POST.read_text().replace("· PUBLICATION-DATE ·", "· 2026-10-20 ·")
                    .replace("SPEND-PENDING: the owner", "$12.34; the owner")
                    + "\n<!-- a note -->\nPUBLICATION-DATE\n")
    r = _run("--post", str(post), "--analysis", str(ANALYSIS))
    assert r.returncode != 0 and "PUBLICATION-DATE" in r.stdout + r.stderr


def test_each_problem_is_named_on_its_own(tmp_path):
    # Only the spend left null: the two placeholders are gone, so only the spend is named.
    post = tmp_path / "post.md"
    post.write_text(POST.read_text().replace("· PUBLICATION-DATE ·", "· 2026-10-20 ·")
                    .replace("SPEND-PENDING: the owner", "$12.34; the owner"))
    r = _run("--post", str(post), "--analysis", str(ANALYSIS))
    assert r.returncode != 0
    out = r.stdout + r.stderr
    assert "spend" in out and "PUBLICATION-DATE" not in out and "SPEND-PENDING" not in out
