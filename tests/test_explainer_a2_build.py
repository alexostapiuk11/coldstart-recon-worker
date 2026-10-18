"""The page builds from committed data, deterministically, and keeps the page contract.

Mirrors tests/test_explainer_build.py where that applies. Artifact 1's page owns
matplotlib charts; this one draws SVG in the browser, so the checks that were about
inlined chart SVG become checks on the data blob and the widget scripts.
"""

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PAGE = REPO / "explainer_a2" / "page.html"


def _module():
    """Import scripts/build_explainer_a2.py as a module.

    It is a script, not a package member, so there is no import path. Asserting only
    on the built text would not reach the branches (the glossary, the plan parser)
    that these tests need to call directly.
    """
    spec = importlib.util.spec_from_file_location(
        "_build_explainer_a2", REPO / "scripts" / "build_explainer_a2.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["_build_explainer_a2"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> str:
    out = tmp_path_factory.mktemp("a2") / "index.html"
    r = subprocess.run(
        [sys.executable, "scripts/build_explainer_a2.py", "--out", str(out)],
        cwd=REPO, capture_output=True, text=True, check=False,
    )
    assert r.returncode == 0, r.stderr
    return out.read_text()


def test_build_leaves_no_unsubstituted_placeholders(built):
    assert "{{" not in built, "a placeholder survived the build"


def test_the_build_is_byte_reproducible(tmp_path):
    """The page argues that everything on it re-derives from committed files. A build
    that differs from itself run to run would be a poor advertisement for that."""
    outs = []
    for name in ("a", "b"):
        out = tmp_path / f"{name}.html"
        r = subprocess.run(
            [sys.executable, "scripts/build_explainer_a2.py", "--out", str(out)],
            cwd=REPO, capture_output=True, text=True, check=False,
        )
        assert r.returncode == 0, r.stderr
        outs.append(out.read_text())
    assert outs[0] == outs[1]


def test_build_fails_loudly_on_an_unknown_placeholder(tmp_path):
    bad = tmp_path / "bad.html"
    bad.write_text("{{not_a_key}}")
    r = subprocess.run(
        [sys.executable, "scripts/build_explainer_a2.py", "--page", str(bad),
         "--out", str(tmp_path / "x.html")],
        cwd=REPO, capture_output=True, text=True, check=False,
    )
    assert r.returncode != 0
    assert "not_a_key" in r.stderr


def test_every_key_in_numbers_json_is_used_by_the_page():
    """A key nothing reads is a number the page no longer states, kept in the spec
    as if it still were one."""
    page = PAGE.read_text()
    used = set(re.findall(r"\{\{([a-z0-9_]+)\}\}", page))
    spec = json.loads((REPO / "explainer_a2" / "numbers.json").read_text())
    assert set(spec) <= used, sorted(set(spec) - used)


def test_page_is_a_fragment_with_a_title_and_no_external_scripts(built):
    head = built[:8192]
    assert re.search(r"<title>[^<:]{3,40}</title>", head), "title missing, or it has a colon"
    for tag in (r"<!doctype", r"<html\b", r"<head\b", r"<body\b"):
        assert not re.search(tag, built, re.IGNORECASE), f"{tag} belongs to the Artifact skeleton"
    assert "<script src" not in built and "<link rel=\"stylesheet\" href=\"http" in built
    for link in re.findall(r'<link[^>]+href="([^"]+)"', built):
        assert link.startswith("https://fonts.googleapis.com/"), link
    assert 'name="viewport"' in built


def _css(html: str) -> str:
    return re.search(r"<style>(.*?)</style>", html, re.DOTALL).group(1)


def _blocks(css: str):
    """(selector, body) for the three theme blocks."""
    root = re.search(r"(?m)^  :root \{(.*?)^  \}", css, re.DOTALL).group(1)
    media = re.search(
        r'@media \(prefers-color-scheme: dark\) \{\s*:root:not\(\[data-theme="light"\]\) \{(.*?)\n    \}\n  \}',
        css, re.DOTALL).group(1)
    stamped = re.search(r'(?m)^  :root\[data-theme="dark"\] \{(.*?)^  \}', css, re.DOTALL).group(1)
    return root, media, stamped


def test_every_colour_is_a_token_defined_in_bare_root_and_redefined_for_dark(built):
    """The three theme states of artifact 1's page: the bare :root has every token, the
    OS-dark block guards against an explicit light choice, and the stamped block makes
    the toggle win in both directions."""
    css = _css(built)
    root, media, stamped = _blocks(css)
    defined = set(re.findall(r"(--[\w-]+)\s*:", root))
    used = set(re.findall(r"var\((--[\w-]+)", css))
    assert used <= defined, f"tokens used but not defined on :root: {sorted(used - defined)}"
    dark_a = set(re.findall(r"(--[\w-]+)\s*:", media))
    dark_b = set(re.findall(r"(--[\w-]+)\s*:", stamped))
    assert dark_a == dark_b, "the two dark blocks must redefine the same tokens"
    assert dark_a <= defined
    assert "color-scheme: dark" in media and "color-scheme: dark" in stamped
    colour_tokens = {t for t in defined if not t.startswith("--font")}
    assert colour_tokens <= dark_a, f"no dark value for {sorted(colour_tokens - dark_a)}"
    assert re.search(r"body\s*\{[^}]*background:\s*var\(--page\)", css, re.DOTALL)


def test_no_component_rule_uses_a_literal_colour(built):
    css = _css(built)
    root, media, stamped = _blocks(css)
    outside = css.replace(root, "").replace(media, "").replace(stamped, "")
    literals = re.findall(r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|hsla?\([^)]*\)", outside)
    assert not literals, literals


def test_fonts_are_the_artifact_one_trio(built):
    for family in ("IBM+Plex+Sans", "Source+Serif+4", "IBM+Plex+Mono"):
        assert family in built
    assert "font-variant-numeric: tabular-nums" in built


def test_page_is_complete_at_rest_and_respects_reduced_motion(built):
    """Nothing waits on an observer to become visible, and motion is optional."""
    css = _css(built)
    assert "opacity: 0" not in css and "opacity:0" not in css
    assert "IntersectionObserver" not in built
    assert "prefers-reduced-motion" in css


def test_every_range_input_has_a_label_and_a_stable_id(built):
    for m in re.finditer(r'<input id="([^"]+)" type="(range|number)"', built):
        assert f'for="{m.group(1)}"' in built, f"no label for {m.group(1)}"


def test_the_page_embeds_the_data_the_widgets_run_on(built):
    blob = json.loads(re.search(r'<script type="application/json" id="a2-data">(.*?)</script>',
                                built, re.DOTALL).group(1))
    assert {"curve", "probes", "toy", "sweeps", "mc", "validation", "host_speed"} <= set(blob)
    assert len(blob["sweeps"]) == 4
    assert len(built.encode()) < 1_000_000


def test_blob_levels_are_the_service_curve_file():
    m = _module()
    levels = m.build_blob(REPO)["curve"]["levels"]
    raw = json.loads((REPO / "data/a2/service-curve.json").read_text())["levels"]
    assert [lv["c"] for lv in levels] == [lv["concurrency"] for lv in raw]
    assert [lv["lat"] for lv in levels] == [lv["latency_s"] for lv in raw]
    assert [lv["tps"] for lv in levels] == [lv["throughput_tps"] for lv in raw]
    assert m.build_blob(REPO)["curve"]["excluded"]["c"] == 256


def test_probe_blob_keeps_only_probes_one_to_three():
    """post-analysis.json holds no in-flight counts for probes 4 and 5, so a table
    that claimed to cover probe 5 would be inventing them."""
    blob = _module().build_blob(REPO)
    assert set(blob["probes"]) == {"1", "2", "3"}


def test_toy_constants_are_the_registered_spike():
    toy = _module().build_blob(REPO)["toy"]
    assert round(toy["sat"], 1) == 211.2
    assert round(toy["base"], 1) == 147.8
    assert round(toy["sat"] * toy["peak_x"], 1) == 253.4
    assert round(toy["peak_x"], 2) == 1.2
    assert toy["sustain"] == 190.0 and toy["eval_every"] == 5.0
    assert toy["lag_A"] > toy["lag_C"]
    assert round(toy["lag_A"], 2) == 81.07 and round(toy["lag_C"], 2) == 39.37


def test_glossary_wraps_terms_in_prose_only(built):
    assert 'class="gloss"' in built
    assert built.count('class="term"') >= 40
    for pattern in (r"<pre\b.*?</pre\s*>", r"<svg\b.*?</svg\s*>", r"<h[1-4]\b.*?</h[1-4]\s*>",
                    r"<label\b.*?</label\s*>", r"<button\b(?![^>]*class=\"term\").*?</button\s*>",
                    r"<table\b.*?</table\s*>", r"<x-plain\b.*?</x-plain\s*>",
                    r"<script\b.*?</script\s*>", r"<style\b.*?</style\s*>"):
        region = "".join(re.findall(pattern, built, re.DOTALL))
        assert 'class="gloss"' not in region, f"glossary leaked into {pattern}"


def test_widgets_have_a_banner_naming_what_the_data_is(built):
    for word in ("MEASURED", "SIMULATED · FAILED VALIDATION", "SYNTHETIC", "TOY"):
        assert f">{word}" in built or f"{word} <span>" in built or f"{word}</span>" in built, word
    banners = re.findall(r'<x-plain class="banner (\w+)">', built)
    assert {"measured", "sim", "synth", "toy"} <= set(banners)
    # the section that carries simulator numbers is labelled as such, every time
    for wid in ("w3s", "w5", "w5b"):
        chunk = built[built.index(f'id="{wid}"'):][:400]
        assert "SIMULATED · FAILED VALIDATION" in chunk, wid
    assert "SYNTHETIC" in built[built.index('id="w6"'):][:300]
    assert "MEASURED − SIMULATED PREDICTION" in built


def test_the_toy_is_labelled_a_toy_and_runs_one_policy(built):
    chunk = built[built.index('id="w4"'):][:6000]
    chunk = re.sub(r'<span class="def" hidden>.*?</span>', "", chunk, flags=re.DOTALL)
    chunk = re.sub(r"<[^>]+>", "", chunk)
    chunk = re.sub(r"\s+", " ", chunk.replace("&rsquo;", "'"))
    assert "a toy for the idea, not the artifact's simulator" in chunk
    assert "One policy runs" in chunk
    for word in ("signal comparison", "which signal wins"):
        assert word not in chunk
