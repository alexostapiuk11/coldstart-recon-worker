"""Artifact 4's private explainer page is built from the committed data and keeps its structure.

The page is `explainer/a4/page.html`, built by `scripts/a4_build_explainer.py` from
`explainer/a4/page.template.html` and the committed analysis. A page that has drifted from
its data is the failure this guards: a number in a study guide that no longer matches the
post is worse than none."""

import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import a4_build_explainer as build

TEMPLATE = (REPO / "explainer" / "a4" / "page.template.html").read_text()
PAGE = (REPO / "explainer" / "a4" / "page.html").read_text()
DATA = build.data()
MODULES = ("m1", "m2", "m3", "m4", "m5", "m6", "m7")


def _get(path: str):
    node = DATA
    for key in path.split("."):
        node = node[int(key)] if isinstance(node, list) else node[key]
    return node


def test_the_page_is_what_the_template_and_data_build():
    assert PAGE == build.build(), "explainer/a4/page.html is stale: run scripts/a4_build_explainer.py"


def test_the_embedded_data_is_the_committed_analysis():
    blob = re.search(r'<script id="data" type="application/json">(.*?)</script>', PAGE, re.DOTALL).group(1)
    embedded = json.loads(blob.replace("<\\/", "</"))
    analysis = json.loads((REPO / "data" / "a4" / "analysis.json").read_text())
    assert embedded["slo"] == analysis["design"]["slo_seconds"]
    assert embedded["swap"]["median"] == analysis["inputs"]["swaps"]["simulated"]["p50"]
    assert embedded["validation"]["outcome"] == analysis["validation"]["outcome"] == "failed"


@pytest.mark.parametrize("path", sorted(set(re.findall(r'data-v="([^"]+)"', TEMPLATE))))
def test_every_bound_number_resolves_in_the_data(path):
    if path == "a1.total":  # summed by the page from the stage medians
        return
    assert _get(path) is not None


@pytest.mark.parametrize("module", MODULES)
def test_each_module_has_a_checkpoint_and_a_passing_answer(module):
    section = re.search(rf'<section class="mod" id="{module}".*?</section>', TEMPLATE, re.DOTALL).group(0)
    assert 'class="cp"' in section and "What a passing answer contains" in section


@pytest.mark.parametrize("module", ("m2", "m4", "m5"))
def test_the_prediction_modules_hide_their_chart_until_a_pick(module):
    section = re.search(rf'<section class="mod" id="{module}".*?</section>', TEMPLATE, re.DOTALL).group(0)
    assert "Predict first" in section and "hidden" in section


def test_the_cost_table_reproduces_the_posts_reference_costs():
    post = (REPO / "docs" / "post-a4.md").read_text()
    ref = next(p for p in DATA["regimes"][DATA["reference"]["regime"]]["points"]
               if p["s"] == DATA["reference"]["s"])
    for strategy in ("dedicate", "swap", "colocate"):
        month = ref["strategies"][strategy]["m"] * DATA["hours_month"] * DATA["rate"]
        assert f"${month / DATA['n_models']:,.2f}" in post


def test_the_page_names_no_external_script_and_one_stylesheet_host():
    assert "<script src" not in PAGE
    hosts = set(re.findall(r'href="(https://[^/"]+)', PAGE))
    assert hosts <= {"https://fonts.googleapis.com", "https://fonts.gstatic.com"}
