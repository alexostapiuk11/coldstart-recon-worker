"""Checkpoints are shown as prompts, word for word from the plan, and never answered.

They are worked through with Claude in a session, which records the verdict in
progress.md. A page that answered them would defeat the pass criterion (restate it
unaided, survive one follow-up), which is why this file exists: the equivalent of
artifact 1's excerpts test, whose job was that what the page shows is what is true.
"""

import html as html_mod
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _module():
    if "_build_explainer_a2" in sys.modules:
        return sys.modules["_build_explainer_a2"]
    spec = importlib.util.spec_from_file_location(
        "_build_explainer_a2", REPO / "scripts" / "build_explainer_a2.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["_build_explainer_a2"] = module
    spec.loader.exec_module(module)
    return module


B = _module()


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> str:
    out = tmp_path_factory.mktemp("cp") / "index.html"
    r = subprocess.run([sys.executable, "scripts/build_explainer_a2.py", "--out", str(out)],
                       cwd=REPO, capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
    return out.read_text()


def _plain(fragment: str) -> str:
    # The glossary hides each term's definition inside the box; it is not the box's text.
    fragment = re.sub(r'<span class="def" hidden>.*?</span>', "", fragment, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "", fragment)
    text = html_mod.unescape(text).replace("’", "'")
    return " ".join(text.split())


def _boxes(built: str) -> dict[int, str]:
    out = {}
    for m in re.finditer(r'<aside class="checkpoint".*?</aside>', built, re.DOTALL):
        n = int(re.search(r'data-checkpoint="(\d)"', m.group(0)).group(1))
        out[n] = m.group(0)
    return out


def _quote(box: str) -> str:
    return _plain(re.search(r'<blockquote[^>]*>(.*?)</blockquote>', box, re.DOTALL).group(1))


def test_the_plan_has_a_row_for_each_of_artifact_twos_nine_modules():
    cps = B.plan_checkpoints(REPO)
    assert set(cps) == set(range(9)), sorted(cps)


def test_there_is_a_box_for_modules_one_to_six_and_none_for_the_others(built):
    boxes = _boxes(built)
    assert set(boxes) == {1, 2, 3, 4, 5, 6}
    for mod in (0, 7, 8):
        assert f'id="m{mod}"' not in built


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 6])
def test_each_checkpoint_is_the_plans_text_word_for_word(built, n):
    plan_cell = B.plan_checkpoints(REPO)[n]
    want = " ".join(plan_cell.replace("**", "").replace("`", "").split()).replace("’", "'")
    assert _quote(_boxes(built)[n]) == want


def test_the_plans_module_two_wording_is_the_one_the_page_shows(built):
    q = _quote(_boxes(built)[2])
    assert q.startswith("probe 1 at 50 req/s offered:")
    assert q.endswith("and what would have to be measured to know")


def test_every_box_says_it_is_not_answered_here(built):
    for n, box in _boxes(built).items():
        assert "Not answered here" in box, n
    assert "The checkpoints are not answered on this page" in built


def test_the_top_note_names_modules_zero_seven_and_eight(built):
    note = _plain(built[built.index('<header class="top">'):built.index("</header>")])
    for fragment in ("Modules 0", "7 (what could not be concluded)", "8 (teach it back)",
                     "happen in session"):
        assert fragment in note, fragment


def test_self_check_pointers_show_the_spec_question_and_nothing_more(built):
    sc = B.spec_selfchecks(REPO)
    boxes = _boxes(built)
    for module, numbers in ((4, (5, 6)), (5, (7,)), (6, (8,))):
        text = _plain(boxes[module])
        for k in numbers:
            assert sc[k].replace("’", "'") in text, (module, k)


# Phrases from the post's conclusions. None may appear in a checkpoint box: they are
# what the checkpoint asks the reader to say.
ANSWER_PHRASES = [
    "ran out of memory", "out of memory", "CUDA", "fills one worker", "fill-first",
    "released held requests", "held requests", "returns 502", "closed-loop", "closed loop",
    "open loop", "fixed number of requests in flight", "same arrival trace",
    "seeds different", "different arrival traces", "cold-start draws", "noise floor",
    "scales up at every chance", "scaled to the cap", "queue depth is the worst",
    "over-corrected because", "hypothesis", "reads 1.0 because", "saturates",
    "inside the spread", "cannot rank", "can't rank", "does not constrain",
]


def test_no_box_contains_a_phrase_from_the_posts_conclusions(built):
    for n, box in _boxes(built).items():
        text = _plain(box)
        # the plan's own wording may use some of these words in the question; the
        # check is against anything the page adds, so remove the quoted question
        # and the spec's self-check questions first
        text = text.replace(_quote(box), "")
        for k in B.spec_selfchecks(REPO).values():
            text = text.replace(k.replace("’", "'"), "")
        for phrase in ANSWER_PHRASES:
            assert phrase.lower() not in text.lower(), (n, phrase)


def test_the_page_does_not_carry_the_posts_explanations_of_the_open_questions(built):
    """Two questions are open on purpose or were left open by the post: why the workers
    held about 2.6 requests under a cap of 4 (module 2) and why the calibration
    over-corrected (module 6). The page may say they are open. It must not offer the
    post's hypothesis for the second, nor any for the first."""
    text = _plain(re.sub(r"<(script|style)\b.*?</\1>", " ", built, flags=re.DOTALL))
    for sentence in ("differ in how load arrived", "That this difference is the cause",
                     "closed loop) while the replay", "a hypothesis: it was not tested"):
        assert sentence not in text, sentence
    assert "not established in this repository" in text
    assert "The post says the evidence does not settle why" in text


def test_the_widgets_that_could_answer_a_checkpoint_do_so_only_on_request(built):
    """Self-check 7's widget shows its verdict only after Check, and the 1,000-run
    count of the gate is the page's only statement of the one-in-four, without a
    statement of why a model fails."""
    ui = (REPO / "explainer_a2" / "ui.js").read_text()
    assert "revealed" in ui and 'on("w5c-check"' in ui
    chunk = built[built.index('id="w5c"'):built.index('id="w5c-msg"') + 200]
    assert "is dominated" not in chunk and "on the frontier</label>" in chunk
