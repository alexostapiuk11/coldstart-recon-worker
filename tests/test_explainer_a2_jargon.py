"""The jargon contract for artifact 2's page, as a check rather than an intention.

"Avoid jargon" cannot be tested. "Every listed term that appears on the page appears
with its definition, and no other technical word has slipped in unlisted" can.
"""

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

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
TERMS = B.TERMS


def _built(tmp_path) -> str:
    out = tmp_path / "index.html"
    r = subprocess.run([sys.executable, "scripts/build_explainer_a2.py", "--out", str(out)],
                       cwd=REPO, capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
    return out.read_text()


def test_a_term_used_without_its_definition_is_reported():
    assert "KV cache" in B.undefined_terms("<p>The KV cache is sized at startup.</p>")


def test_a_term_used_with_its_definition_passes():
    page = f"<p>The KV cache, {TERMS['KV cache']}, is sized at startup.</p>"
    assert "KV cache" not in B.undefined_terms(page)


def test_a_page_using_no_listed_terms_reports_nothing():
    assert B.undefined_terms("<p>Nothing technical here.</p>") == []


def test_a_term_only_inside_code_is_still_reported():
    assert "max-num-seqs" in B.undefined_terms("<code>--max-num-seqs 128</code>")


def test_a_prefix_of_a_definition_is_not_enough():
    half = TERMS["cooldown"][:20]
    assert "cooldown" in B.undefined_terms(f"<p>A cooldown is {half}</p>")


def test_every_term_is_defined_in_the_template_by_its_own_slot():
    """The definition is pulled from terms.json by `{{def:term}}`, so the sentence the
    reader meets is the string the glossary reveals, and the two cannot drift."""
    page = (REPO / "explainer_a2" / "page.html").read_text()
    slots = set(re.findall(r"\{\{def:([^}]+)\}\}", page))
    assert set(TERMS) <= slots, sorted(set(TERMS) - slots)


def test_the_page_passes_its_own_gate_before_the_glossary_wraps_it():
    """The gate runs on the substituted page and not on the built one: wrapping a term
    puts markup inside any definition that contains another term ("the engine's
    setting" contains "engine"), which would break the contiguous text the gate needs."""
    page = (REPO / "explainer_a2" / "page.html").read_text()
    assert B.undefined_terms(B.substitute(page, REPO)) == []


def test_definitions_are_plain_sentences_fragments():
    for term, definition in TERMS.items():
        assert definition == definition.strip() and not definition.endswith("."), term
        assert len(definition.split()) >= 2, term


def test_the_glossary_matches_case_insensitively_and_plurals():
    html = B.glossary("<p>Replicas and Policies and the Cooldown.</p>")
    assert html.count('class="term"') == 3
    assert ">Replicas<" in html and ">Policies<" in html and ">Cooldown<" in html


def test_the_glossary_does_not_open_inside_a_longer_word():
    html = B.glossary("<p>We combine and robin and ghost.</p>")
    assert 'class="term"' not in html


def test_the_glossary_skips_controls_tables_and_code():
    src = ("<button>replica</button><label>replica</label><table><tr><td>replica</td></tr>"
           "</table><code>replica</code><p>replica</p>")
    assert B.glossary(src).count('class="term"') == 1


def test_longest_term_wins_so_replica_seconds_is_one_term():
    html = B.glossary("<p>3,095 replica-seconds</p>")
    assert html.count('class="term"') == 1 and ">replica-seconds<" in html


# Technical words this page does not define. They are jargon for a strong generalist
# who has not read the code, so they must not appear unless they are added to terms.json.
UNLISTED_JARGON = ["CUDA", "kernel", "Pareto", "percentile", "bootstrap", "symlog", "SLO",
                   "TTFT", "HBM", "ECDF", "DCGM", "p95", "IQR", "quantile", "QPS", "RPS",
                   "tail latency", "autoregressive", "paged attention", "prefix cache"]


def test_no_unlisted_jargon_in_the_visible_prose(tmp_path):
    html = _built(tmp_path)
    prose = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.DOTALL)
    prose = re.sub(r"<[^>]+>", " ", prose)
    for word in UNLISTED_JARGON:
        assert not re.search(rf"(?<![\w-]){re.escape(word)}(?![\w-])", prose, re.IGNORECASE), word
    assert json.loads((REPO / "explainer_a2" / "terms.json").read_text()) == TERMS
