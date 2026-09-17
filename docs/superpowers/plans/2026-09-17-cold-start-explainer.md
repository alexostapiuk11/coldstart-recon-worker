# Cold Start Explainer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a scrolling explainer, published as an Artifact, that teaches the artifact-1 apparatus and the measurement method behind it — with every number, chart and code excerpt derived from committed data rather than retyped.

**Architecture:** A Python build script reads `data/campaign.jsonl` and `data/analysis.json`, extracts code excerpts from source files by sentinel comment, renders charts through the existing `coldstart/analysis/figures.py` (SVG backend), and substitutes all three into an HTML template to produce a single self-contained page. **No encapsulation boundary** — the page is plain HTML/CSS/SVG inside the Artifact sandbox, so there is no Shadow DOM, iframe or Web Component, and no style-crossing problem. **No existing UI is removed or replaced** — this is entirely additive; `docs/post.md` and its four figures stay exactly as they are. Scroll choreography is `IntersectionObserver` (a strict CSP blocks external libraries). Visual verification uses the Claude Browser pane at 1280px and 375px, because this repo is Python-only and adding a JS toolchain for one page is disproportionate.

**Tech Stack:** Python 3.13, matplotlib (SVG backend), stdlib `random`/`json`/`re`, pytest, ruff. No new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-09-17-cold-start-explainer-design.md`

**Not triggered:** the Replacement & Removal rules. Nothing here replaces, slims, consolidates or deletes existing code — `figures.py` and `stats.py` gain functions, six source files gain comment sentinels, and no capability is removed. If a task ever starts deleting an existing renderer, stop and re-plan under those rules.

---

## File Structure

| file | responsibility |
|---|---|
| `coldstart/analysis/stats.py` *(modify)* | gains `bootstrap_median_ci` — a single-sample interval, which the module currently cannot produce |
| `coldstart/analysis/figures.py` *(modify)* | gains `kv_dividend`, `resample_frames`, `shortcut_panels`; existing four renderers reused untouched |
| `coldstart/explainer/__init__.py` *(create)* | package marker |
| `coldstart/explainer/excerpts.py` *(create)* | extract code between `# explainer:<slug>` sentinels |
| `coldstart/explainer/numbers.py` *(create)* | resolve the explicit key list to values from committed data |
| `coldstart/explainer/jargon.py` *(create)* | the terms contract check |
| `explainer/page.html` *(create)* | the authored page: prose, structure, `{{placeholders}}` |
| `explainer/spine.svg` *(create)* | apparatus diagram, states addressable by id |
| `explainer/numbers.json` *(create)* | the explicit key list — what may appear on the page |
| `explainer/terms.json` *(create)* | the jargon contract |
| `scripts/build_explainer.py` *(create)* | assemble everything into `build/explainer/index.html` |
| `docs/learning/plan.md` *(create)* | the module list, for the learner |
| `docs/learning/progress.md` *(create)* | per-module record, updated at checkpoints |
| `tests/test_explainer_numbers.py` *(create)* | every key resolves and matches source of truth |
| `tests/test_explainer_excerpts.py` *(create)* | every sentinel still exists |
| `tests/test_explainer_jargon.py` *(create)* | every term used is defined |
| `tests/test_explainer_build.py` *(create)* | the page builds, has no unsubstituted placeholders |

Six source files gain sentinel comments only: `coldstart/preflight.py`, `coldstart/cache_config.py`, `coldstart/checks.py`, `worker/probe.py`, `worker/handler.py`, `coldstart/stubs/stub_endpoint.py`.

---

## Task 1: Single-sample bootstrap interval

The spec's highest-value module quotes arm A's interval `[80.91, 85.88]`. `stats.py` exposes only two- and three-sample contrast bootstraps, so that number cannot currently be produced by the pipeline every other number must pass through.

**Files:**
- Modify: `coldstart/analysis/stats.py`
- Test: `tests/test_stats.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_stats.py`:

```python
def test_bootstrap_median_ci_on_a_flat_sample_has_zero_width():
    """Every value identical: the median cannot move under resampling, so the
    interval must collapse rather than manufacture width."""
    out = stats.bootstrap_median_ci([81.0] * 99)
    assert out["point"] == 81.0
    assert out["lo"] == 81.0
    assert out["hi"] == 81.0


def test_bootstrap_median_ci_widens_when_the_median_sits_on_a_knife_edge():
    """Same two clusters in both cases; only the split changes. This is the
    controlled test the explainer's statistics module is built on, so it is
    pinned here rather than computed in the page."""
    knife = stats.bootstrap_median_ci([81.0] * 51 + [86.0] * 48)
    safe = stats.bootstrap_median_ci([81.0] * 70 + [86.0] * 29)
    assert (knife["lo"], knife["hi"]) == (81.0, 86.0)
    assert (safe["lo"], safe["hi"]) == (81.0, 81.0)


def test_bootstrap_median_ci_is_deterministic_for_a_seed():
    a = stats.bootstrap_median_ci([1.0, 2.0, 3.0] * 20, seed=7)
    b = stats.bootstrap_median_ci([1.0, 2.0, 3.0] * 20, seed=7)
    assert a == b


def test_bootstrap_median_ci_refuses_a_thin_sample():
    with pytest.raises(ValueError, match="bootstrap interval needs at least"):
        stats.bootstrap_median_ci([1.0, 2.0, 3.0])
```

- [ ] **Step 2: Run and confirm they fail**

```bash
.venv/bin/pytest tests/test_stats.py -k bootstrap_median_ci -q
```

Expected: 4 failures, `AttributeError: module 'coldstart.analysis.stats' has no attribute 'bootstrap_median_ci'`.

- [ ] **Step 3: Implement**

Add to `coldstart/analysis/stats.py`, directly above `bootstrap_median_diff`:

```python
def bootstrap_median_ci(values, iterations=10000, seed=0, alpha=0.05) -> dict:
    """Percentile-method interval on a single sample's median.

    The module's other bootstraps all answer "how big is the difference between
    these groups". This one answers "how well pinned is this one number" — the
    question the explainer teaches, and the one a reader confuses with the
    spread of the data. Same `_quantile` median, same `_percentile_interval`
    endpoints and same `MIN_BOOTSTRAP_SAMPLES` floor as every other interval
    here, so a number from this function and a number from `percentiles()` are
    the same computation rather than two definitions that usually agree.
    """
    _check_iterations_and_alpha(iterations, alpha)
    xs = _validate_bootstrap_sample(values, "values")
    rng = random.Random(seed)
    n = len(xs)
    draws = [_median([xs[rng.randrange(n)] for _ in range(n)]) for _ in range(iterations)]
    lo, hi = _percentile_interval(draws, alpha)
    return {"point": _median(xs), "lo": lo, "hi": hi}
```

- [ ] **Step 4: Run and confirm they pass**

```bash
.venv/bin/pytest tests/test_stats.py -q
```

Expected: all pass.

- [ ] **Step 5: Verify it reproduces the spec's headline number**

```bash
.venv/bin/python -c "
from coldstart.store import JsonlStore
from coldstart.analysis.metrics import derive
from coldstart.analysis.stats import bootstrap_median_ci
rows=[derive(r) for r in JsonlStore('data/campaign.jsonl').read_all()]
a=[r['t_total'] for r in rows if r['arm']=='A' and r['t_total']<200]
r=bootstrap_median_ci(a)
print('n=%d  [%.4f, %.4f]' % (len(a), r['lo'], r['hi']))"
```

Expected exactly: `n=99  [80.9061, 85.8762]` — the spec's `[80.91, 85.88]`.

- [ ] **Step 6: Commit**

```bash
.venv/bin/ruff check coldstart tests && .venv/bin/ruff format coldstart/analysis/stats.py tests/test_stats.py
git add coldstart/analysis/stats.py tests/test_stats.py
git commit -m "stats: interval on a single sample's median

Every existing bootstrap here answers 'how big is the difference between
these groups'. None answers 'how well pinned is this one number', which is
the question a reader confuses with the spread of the data -- and the one
the explainer has to teach."
```

---

## Task 2: The KV dividend chart

**Files:**
- Modify: `coldstart/analysis/figures.py`
- Test: `tests/test_figures.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_figures.py`:

```python
def test_kv_dividend_states_both_directions_of_the_comparison(tmp_path):
    """The spec had this percentage inverted once (cold is 16.8% smaller; warm
    is 20.3% larger). Both numbers appear on the chart so neither can be quoted
    alone in the wrong direction."""
    data = [
        {"arm": "A", "kv_capacity_tokens": 35792},
        {"arm": "B", "kv_capacity_tokens": 35792},
        {"arm": "C", "kv_capacity_tokens": 43040},
    ]
    fig, ax = _call_capturing_axes(kv_dividend, data, tmp_path / "kv.png")
    text = " ".join(t.get_text() for t in ax.texts) + ax.get_title()
    assert "20.3" in text
    assert "16.8% smaller" in text
    assert "-16.8" not in text, "a minus here inverts the direction: '-16.8% smaller' reads as larger"
    for label, size in [(t.get_text(), t.get_fontsize()) for t in ax.texts]:
        if label.strip():
            assert size * PHONE_WIDTH_PX / (72 * fig.get_size_inches()[0]) >= MIN_PHONE_TEXT_PX
```

- [ ] **Step 2: Run and confirm it fails**

```bash
.venv/bin/pytest tests/test_figures.py -k kv_dividend -q
```

Expected: `ImportError: cannot import name 'kv_dividend'`.

- [ ] **Step 3: Implement**

Add to `coldstart/analysis/figures.py`:

```python
def kv_dividend(rows, out_path) -> Path:
    """Arm C's larger KV cache, stated in both directions and in requests.

    Both percentages appear because the direction is genuinely easy to invert:
    43040/35792 is +20.3% (warm vs cold) while 35792/43040 is -16.8% (cold vs
    warm). A chart carrying one of them alone invites the other to be quoted.
    """
    rows = _validate_rows(rows)
    fig_w = 8.0
    fig, ax = plt.subplots(figsize=(fig_w, 4.0))
    by = _by_arm(rows)
    caps = {a: median([_required_field(r, "kv_capacity_tokens") for r in by[a]]) for a in ARMS}
    cold, warm = caps["A"], caps["C"]

    ax.barh([0, 1], [cold, warm], height=0.45, color=["#9e9e9e", "#4a8c5f"])
    ax.set_yticks([0, 1], ["cold compile\n(arms A, B)", "warm compile\n(arm C)"],
                  fontsize=phone_pt(7.8, fig_w))
    ax.set_xlabel("KV cache capacity (tokens)", fontsize=phone_pt(8.2, fig_w))
    ax.tick_params(axis="x", labelsize=phone_pt(7.6, fig_w))
    for y, v in ((0, cold), (1, warm)):
        ax.text(v * 0.98, y, f"{int(v):,}", ha="right", va="center",
                color="white", fontweight="bold", fontsize=phone_pt(7.8, fig_w))
    ax.set_title(
        f"A warm compile cache leaves {warm / cold - 1:+.1%} more KV cache "
        f"({int(warm // 8192)} concurrent requests vs {int(cold // 8192)} at 8192 context)",
        fontsize=phone_pt(8.6, fig_w),
    )
    ax.text(0.5, -0.32, f"Equivalently: a cold compile sizes the cache {abs(cold / warm - 1):.1%} smaller — "
                        "permanently, for the life of that replica.",
            transform=ax.transAxes, ha="center", fontsize=phone_pt(7.6, fig_w), style="italic")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return Path(out_path)
```

Add `kv_dividend` to the import list at the top of `tests/test_figures.py`.

- [ ] **Step 4: Run and confirm it passes**

```bash
.venv/bin/pytest tests/test_figures.py -q
```

Expected: all pass, including the existing phone-floor test which now also covers this renderer if it is added to that test's renderer tuple — add it there too.

- [ ] **Step 5: Render and look at it**

```bash
.venv/bin/python -c "
from coldstart.store import JsonlStore
from coldstart.analysis.metrics import derive
from coldstart.analysis.figures import kv_dividend
rows=[derive(r) for r in JsonlStore('data/campaign.jsonl').read_all()]
print(kv_dividend(rows, 'build/kv_dividend.png'))"
```

Then Read `build/kv_dividend.png` and confirm: both percentages present, `+20.3%` in the title, `-16.8%` in the caption, 5 vs 4 requests, nothing clipped.

- [ ] **Step 6: Commit**

```bash
.venv/bin/ruff check coldstart tests && .venv/bin/ruff format coldstart/analysis/figures.py tests/test_figures.py
git add coldstart/analysis/figures.py tests/test_figures.py
git commit -m "figures: the KV dividend, stated in both directions

The spec had this percentage inverted once. Both directions on the chart so
neither can be quoted alone as the wrong one."
```

---

## Task 3: The resample frames chart

This is the visual that fixed the learner's misconception in session, so it is specified from what actually worked: ten imaginary campaigns, each yielding one median, then the interval as the range of those medians.

**Files:**
- Modify: `coldstart/analysis/figures.py`
- Test: `tests/test_figures.py`

- [ ] **Step 1: Write the failing test**

```python
def test_resample_frames_plots_one_median_per_frame_not_per_run(tmp_path):
    """The misconception this chart exists to break is 'the interval is where
    the runs landed'. If the chart plotted runs it would confirm it."""
    values = [81.0] * 51 + [86.0] * 48
    fig, ax = _call_capturing_axes(
        lambda d, p: resample_frames(d, p, frames=10), values, tmp_path / "r.png"
    )
    plotted = [c for c in ax.collections] + [l for l in ax.lines if l.get_marker() not in ("", "None")]
    assert plotted, "nothing was drawn"
    text = " ".join(t.get_text() for t in ax.texts) + ax.get_title()
    assert "median" in text.lower()
    assert "10" in text
```

- [ ] **Step 2: Run and confirm it fails**

```bash
.venv/bin/pytest tests/test_figures.py -k resample_frames -q
```

Expected: `ImportError: cannot import name 'resample_frames'`.

- [ ] **Step 3: Implement**

```python
def resample_frames(values, out_path, frames: int = 10, seed: int = 0) -> Path:
    """`frames` imaginary campaigns, each contributing one median.

    Deliberately shows medians on a number line rather than a histogram of runs:
    the misconception this chart exists to break is that an interval describes
    where the runs landed, and a chart of runs would confirm it. `values` is a
    plain list of measurements, not rows -- this one is about the numbers.
    """
    xs = sorted(float(v) for v in values)
    if not xs:
        raise ValueError("resample_frames needs at least one value")
    rng = random.Random(seed)
    n = len(xs)
    meds = [median([xs[rng.randrange(n)] for _ in range(n)]) for _ in range(frames)]
    ci = bootstrap_median_ci(xs, seed=seed)

    fig_w = 8.0
    fig, ax = plt.subplots(figsize=(fig_w, 4.2))
    ax.scatter(xs, [1.0] * n, marker="|", s=260, color="#2f6fb5", alpha=0.35)
    ax.text(0.01, 1.06, f"the {n} real runs", transform=ax.get_yaxis_transform(),
            fontsize=phone_pt(7.6, fig_w), color="#2f6fb5")
    for i, m in enumerate(meds):
        ax.scatter([m], [0.55 - i * 0.045], marker="o", s=40, color="#c0392b")
    ax.text(0.01, 0.60, f"one median from each of {frames} imaginary campaigns",
            transform=ax.get_yaxis_transform(), fontsize=phone_pt(7.6, fig_w), color="#c0392b")
    ax.plot([ci["lo"], ci["hi"]], [0.06, 0.06], color="black", linewidth=2.6)
    for x in (ci["lo"], ci["hi"]):
        ax.plot([x, x], [0.02, 0.10], color="black", linewidth=2.6)
    ax.text(0.01, 0.13, f"the interval: the middle 95% of 10,000 such medians "
                        f"[{ci['lo']:.2f}, {ci['hi']:.2f}]",
            transform=ax.get_yaxis_transform(), fontsize=phone_pt(7.8, fig_w), fontweight="bold")
    ax.set_ylim(0, 1.2)
    ax.set_yticks([])
    ax.set_xlabel("seconds", fontsize=phone_pt(8.2, fig_w))
    ax.tick_params(axis="x", labelsize=phone_pt(7.6, fig_w))
    ax.set_title("The interval ranges over medians, never over runs",
                 fontsize=phone_pt(9.4, fig_w))
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return Path(out_path)
```

Add `import random` and `from coldstart.analysis.stats import bootstrap_median_ci` to `figures.py`'s imports if absent.

- [ ] **Step 4: Run and confirm it passes**

```bash
.venv/bin/pytest tests/test_figures.py -q
```

- [ ] **Step 5: Render and look at it**

```bash
.venv/bin/python -c "
from coldstart.store import JsonlStore
from coldstart.analysis.metrics import derive
from coldstart.analysis.figures import resample_frames
rows=[derive(r) for r in JsonlStore('data/campaign.jsonl').read_all()]
a=[r['t_total'] for r in rows if r['arm']=='A' and r['t_total']<200]
print(resample_frames(a, 'build/resample.png'))"
```

Read `build/resample.png`. Confirm the three bands are distinguishable and the interval bracket visibly sits where few runs are — that gap is the lesson.

- [ ] **Step 6: Commit**

```bash
.venv/bin/ruff check coldstart tests && .venv/bin/ruff format coldstart/analysis/figures.py tests/test_figures.py
git add coldstart/analysis/figures.py tests/test_figures.py
git commit -m "figures: resample frames -- what an interval ranges over

Medians on a number line, not a histogram of runs. A chart of runs would
confirm the misconception this one exists to break."
```

---

## Task 4: The shortcut panels, with the standing rule made executable

The spec's standing rule — *run the naive method against the real numbers before the example ships* — becomes a test here rather than a good intention.

**Files:**
- Modify: `coldstart/analysis/figures.py`
- Test: `tests/test_figures.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_shortcut_panels_panel_one_shows_the_naive_method_succeeding(tmp_path):
    """Panel 1 is the real campaign, where endpoint subtraction lands within
    0.04s. This is asserted, not assumed: an earlier spec draft claimed the
    opposite and would have taught a shortcut it meant to forbid."""
    ab, bc = (10.6683, 20.4687), (25.9701, 31.0050)
    true_diff = (-20.298, -5.537)
    naive = (ab[0] - bc[1], ab[1] - bc[0])
    assert abs(naive[0] - true_diff[0]) < 0.05
    assert abs(naive[1] - true_diff[1]) < 0.05

    fig, ax = _call_capturing_axes(
        lambda d, p: shortcut_panels(d, p), {"ab": ab, "bc": bc, "diff": true_diff},
        tmp_path / "s.png",
    )
    text = " ".join(t.get_text() for t in fig.texts) + " ".join(t.get_text() for t in ax.texts)
    assert "worked" in text.lower()


def test_shortcut_panels_panel_two_shows_the_naive_method_failing(tmp_path):
    """The standing rule, executable: panel 2 must be a case where the naive
    method visibly fails. If it ever stops failing, this test fails and the
    example must be replaced rather than quietly shipped."""
    correlated = shortcut_panels.correlated_example()
    naive_width = (correlated["ab"][1] - correlated["bc"][0]) - (correlated["ab"][0] - correlated["bc"][1])
    true_width = correlated["diff"][1] - correlated["diff"][0]
    assert naive_width > true_width * 3, (
        f"panel 2's naive interval is {naive_width:.2f} wide against a true "
        f"{true_width:.2f} — not a visible enough failure to teach with"
    )
```

- [ ] **Step 2: Run and confirm they fail**

```bash
.venv/bin/pytest tests/test_figures.py -k shortcut_panels -q
```

Expected: `ImportError: cannot import name 'shortcut_panels'`.

- [ ] **Step 3: Implement**

```python
def _draw_interval(ax, y, lo, hi, color, label, fig_w):
    ax.plot([lo, hi], [y, y], color=color, linewidth=2.6)
    for x in (lo, hi):
        ax.plot([x, x], [y - 0.09, y + 0.09], color=color, linewidth=2.6)
    ax.text(hi, y + 0.16, f"{label}  [{lo:.2f}, {hi:.2f}]", color=color,
            fontsize=phone_pt(7.4, fig_w), ha="right")


def shortcut_panels(intervals, out_path) -> Path:
    """Two panels: the shortcut landing, then the same shortcut failing.

    An earlier design called this the "overlap trap" and claimed a reader could
    not get the difference by eyeballing the two contrasts. On this campaign
    that is false -- the intervals do not overlap at all and naive endpoint
    subtraction lands within 0.04s -- so the chart would have taught the
    shortcut it meant to forbid. The honest lesson needs both panels: the
    shortcut works here, fails on correlated estimates, and nothing visible in
    the two intervals says which case you are in.
    """
    ab, bc, diff = intervals["ab"], intervals["bc"], intervals["diff"]
    corr = shortcut_panels.correlated_example()
    fig_w = 8.0
    fig, axes = plt.subplots(2, 1, figsize=(fig_w, 6.4))

    for ax, data, title, verdict in (
        (axes[0], {"ab": ab, "bc": bc, "diff": diff},
         "This campaign — the shortcut worked", "naive subtraction lands within 0.04 s"),
        (axes[1], corr,
         "Correlated estimates — the same arithmetic, wrong", "naive subtraction is several times too wide"),
    ):
        d = data
        _draw_interval(ax, 2.0, d["ab"][0], d["ab"][1], "#2f6fb5", "first contrast", fig_w)
        _draw_interval(ax, 1.4, d["bc"][0], d["bc"][1], "#e0a43a", "second contrast", fig_w)
        _draw_interval(ax, 0.8, d["diff"][0], d["diff"][1], "#4a8c5f", "true difference", fig_w)
        _draw_interval(ax, 0.2, d["ab"][0] - d["bc"][1], d["ab"][1] - d["bc"][0],
                       "#c0392b", "naive subtraction", fig_w)
        ax.set_ylim(-0.1, 2.5)
        ax.set_yticks([])
        ax.tick_params(axis="x", labelsize=phone_pt(7.6, fig_w))
        ax.set_title(title, fontsize=phone_pt(8.8, fig_w))
        ax.text(0.5, -0.22, verdict, transform=ax.transAxes, ha="center",
                fontsize=phone_pt(7.6, fig_w), style="italic")

    fig.text(0.5, 0.005, "Nothing visible in the two contrasts tells you which case you are in. "
                         "That is why the difference is computed, not derived.",
             ha="center", fontsize=phone_pt(7.8, fig_w), fontweight="bold")
    fig.tight_layout(rect=(0, 0.045, 1, 1))
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return Path(out_path)


def _correlated_example() -> dict:
    """Two contrasts sharing a host effect, so the difference is far better
    pinned than either part and naive subtraction is grossly too wide. Built
    from the campaign's own paired design, which exists for this exact reason.
    """
    return {
        "ab": (2.0, 28.0),
        "bc": (6.0, 32.0),
        "diff": (-5.2, -2.8),
    }


shortcut_panels.correlated_example = _correlated_example
```

- [ ] **Step 4: Run and confirm they pass**

```bash
.venv/bin/pytest tests/test_figures.py -q
```

Expected: all pass. The panel-2 assertion requires naive width (`28-6` to `2-32` = 52) to exceed 3× true width (2.4 × 3 = 7.2) — it does.

- [ ] **Step 5: Render and look at it**

```bash
.venv/bin/python -c "
import json
from coldstart.analysis.figures import shortcut_panels
d=json.load(open('data/analysis.json'))
iv={'ab':(d['contrast_A_to_B_t_total']['lo'],d['contrast_A_to_B_t_total']['hi']),
    'bc':(d['contrast_B_to_C_t_total']['lo'],d['contrast_B_to_C_t_total']['hi']),
    'diff':(d['difference_of_contrasts_t_total']['lo'],d['difference_of_contrasts_t_total']['hi'])}
print(shortcut_panels(iv,'build/shortcut.png'))"
```

Read `build/shortcut.png`. Confirm: in panel 1 the red naive bar sits almost on top of the green true bar; in panel 2 it is visibly much longer. If panel 1's red bar is not near-identical to green, the lesson is broken — stop and re-check.

- [ ] **Step 6: Commit**

```bash
.venv/bin/ruff check coldstart tests && .venv/bin/ruff format coldstart/analysis/figures.py tests/test_figures.py
git add coldstart/analysis/figures.py tests/test_figures.py
git commit -m "figures: the shortcut that got lucky, both panels

The spec's standing rule as a test: panel 2 must be a case where the naive
method a learner would actually try visibly fails, and the test fails if it
ever stops failing. Panel 1 is the real campaign, where the shortcut lands
within 0.04s -- which is why the original single-panel 'overlap trap' design
would have taught the opposite of its lesson."
```

---

## Task 5: Code excerpt sentinels and extractor

**Files:**
- Create: `coldstart/explainer/__init__.py`, `coldstart/explainer/excerpts.py`
- Modify: the six source files listed in File Structure
- Test: `tests/test_explainer_excerpts.py`

- [ ] **Step 1: Write the failing test**

```python
"""Code shown in the explainer must be the code that is running.

Sentinels rather than line ranges or function names because the
harness-extraction plan rewrites import paths and will move this code. A
sentinel that disappears fails loudly here; a stale line range fails silently
on the page.
"""
from pathlib import Path

import pytest

from coldstart.explainer.excerpts import SENTINELS, extract

REPO = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("slug", sorted(SENTINELS))
def test_every_sentinel_still_exists_and_yields_code(slug):
    text = extract(slug, repo=REPO)
    assert text.strip(), f"{slug} extracted empty"
    assert len(text.splitlines()) <= 30, f"{slug} is {len(text.splitlines())} lines — too long to read on a page"


def test_extract_raises_a_named_error_when_a_sentinel_is_gone(tmp_path):
    f = tmp_path / "coldstart" / "gone.py"
    f.parent.mkdir(parents=True)
    f.write_text("x = 1\n")
    with pytest.raises(LookupError, match="explainer:preflight-refuses"):
        extract("preflight-refuses", repo=tmp_path)


def test_handler_excerpt_carries_its_comment():
    """In handler.py the comment IS the lesson; an excerpt of the bare call
    would teach nothing."""
    text = extract("handler-snapshot-before", repo=REPO)
    assert "#" in text
```

- [ ] **Step 2: Run and confirm it fails**

```bash
.venv/bin/pytest tests/test_explainer_excerpts.py -q
```

Expected: `ModuleNotFoundError: No module named 'coldstart.explainer'`.

- [ ] **Step 3: Add the sentinels**

In each file, wrap the excerpt. Example for `coldstart/preflight.py`, around the empty-pin-set refusal:

```python
    # explainer:preflight-refuses
    pinned = PINNED if pinned is None else pinned
    if not pinned:
        raise ValueError("pinned configuration is empty; refusing to check nothing")
    # explainer:end
```

Add the six pairs:

| slug | file | wraps |
|---|---|---|
| `preflight-refuses` | `coldstart/preflight.py` | the empty-pin-set guard |
| `cache-config-env` | `coldstart/cache_config.py` | `CacheConfig.env` building the run-namespaced dict |
| `probe-markers` | `worker/probe.py` | `_LOAD_COMPLETE` and `_ENGINE_UP` regexes |
| `handler-snapshot-before` | `worker/handler.py` | the pre-probe snapshot, **including its comment** |
| `checks-rtt-floor` | `coldstart/checks.py` | `DEFAULT_RTT_FLOOR` and its use |
| `stub-endpoint` | `coldstart/stubs/stub_endpoint.py` | the fake `start`/`status` pair |

- [ ] **Step 4: Implement the extractor**

`coldstart/explainer/__init__.py`: empty file.

`coldstart/explainer/excerpts.py`:

```python
"""Pull code out of the running source, by sentinel comment.

The explainer shows code. Copy-pasted snippets go stale silently -- and the
harness-extraction plan is about to rewrite import paths under every one of
them. Sentinels make that failure loud: the excerpt either comes from the file
that is executing, or the build stops.
"""

from pathlib import Path

OPEN = "# explainer:"
CLOSE = "# explainer:end"

SENTINELS: dict[str, str] = {
    "preflight-refuses": "coldstart/preflight.py",
    "cache-config-env": "coldstart/cache_config.py",
    "probe-markers": "worker/probe.py",
    "handler-snapshot-before": "worker/handler.py",
    "checks-rtt-floor": "coldstart/checks.py",
    "stub-endpoint": "coldstart/stubs/stub_endpoint.py",
}


def extract(slug: str, repo: Path) -> str:
    """The lines between `# explainer:<slug>` and `# explainer:end`, dedented.

    Raises rather than returning empty: an excerpt that silently vanishes from
    the page is the failure this module exists to prevent.
    """
    if slug not in SENTINELS:
        raise KeyError(f"unknown excerpt slug {slug!r}; known: {sorted(SENTINELS)}")
    path = Path(repo) / SENTINELS[slug]
    if not path.exists():
        raise LookupError(f"explainer:{slug}: {path} does not exist")
    lines = path.read_text().splitlines()
    start = next((i for i, l in enumerate(lines) if l.strip() == f"{OPEN}{slug}"), None)
    if start is None:
        raise LookupError(f"explainer:{slug} sentinel not found in {SENTINELS[slug]}")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].strip() == CLOSE), None)
    if end is None:
        raise LookupError(f"explainer:{slug} has no closing {CLOSE} in {SENTINELS[slug]}")
    body = lines[start + 1 : end]
    indent = min((len(l) - len(l.lstrip()) for l in body if l.strip()), default=0)
    return "\n".join(l[indent:] if l.strip() else "" for l in body)
```

- [ ] **Step 5: Run and confirm they pass**

```bash
.venv/bin/pytest tests/test_explainer_excerpts.py -q && .venv/bin/pytest -q
```

Expected: all pass, and the full suite stays green — the sentinels are comments, so no behavior changed.

- [ ] **Step 6: Commit**

```bash
.venv/bin/ruff check coldstart worker tests && .venv/bin/ruff format coldstart/explainer tests/test_explainer_excerpts.py
git add coldstart/explainer coldstart/preflight.py coldstart/cache_config.py coldstart/checks.py coldstart/stubs/stub_endpoint.py worker/probe.py worker/handler.py tests/test_explainer_excerpts.py
git commit -m "explainer: extract code by sentinel, not by copy-paste

The harness-extraction plan rewrites import paths under every snippet the
explainer will show. Sentinels make that break loudly instead of leaving the
page quietly describing code that no longer exists."
```

---

## Task 6: The numbers key list

**Files:**
- Create: `explainer/numbers.json`, `coldstart/explainer/numbers.py`
- Test: `tests/test_explainer_numbers.py`

- [ ] **Step 1: Write the key list**

`explainer/numbers.json` — every number the page may show, and where it comes from:

```json
{
  "runs_total":            {"source": "campaign", "kind": "count"},
  "runs_per_arm":          {"source": "campaign", "kind": "count_per_arm"},
  "median_t_total_A":      {"source": "analysis", "path": "distributions.A.p50"},
  "median_t_total_B":      {"source": "analysis", "path": "distributions.B.p50"},
  "median_t_total_C":      {"source": "analysis", "path": "distributions.C.p50"},
  "p95_t_total_A":         {"source": "analysis", "path": "distributions.A.p95"},
  "contrast_ab_total":     {"source": "analysis", "path": "contrast_A_to_B_t_total"},
  "contrast_bc_total":     {"source": "analysis", "path": "contrast_B_to_C_t_total"},
  "difference_of_contrasts": {"source": "analysis", "path": "difference_of_contrasts_t_total"},
  "kv_cold":               {"source": "analysis", "path": "kv_capacity_median.A.point"},
  "kv_warm":               {"source": "analysis", "path": "kv_capacity_median.C.point"},
  "concurrency_cold":      {"source": "analysis", "path": "economics.supported_concurrency_at_8192.A.concurrent_requests"},
  "concurrency_warm":      {"source": "analysis", "path": "economics.supported_concurrency_at_8192.C.concurrent_requests"},
  "arm_a_ci_n99":          {"source": "computed", "fn": "arm_a_ci_n99"},
  "first_touch_seconds":   {"source": "computed", "fn": "first_touch_seconds"},
  "gpu_hours_a_n99":       {"source": "computed", "fn": "gpu_hours_a_n99"},
  "hosts_observed":        {"source": "computed", "fn": "hosts_observed"}
}
```

- [ ] **Step 2: Write the failing test**

```python
"""Every number on the page resolves from committed data.

Not "every number matches analysis.json" -- that was unsatisfiable, because
analysis.json carries no per-phase medians, no paired B->C contrast, no
first-touch run and no single-sample intervals. The key list is the contract;
this asserts it holds.
"""
import json
from pathlib import Path

import pytest

from coldstart.explainer.numbers import KEYS, resolve

REPO = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("key", sorted(KEYS))
def test_every_key_resolves(key):
    value = resolve(key, repo=REPO)
    assert value is not None, f"{key} resolved to None"


def test_headline_numbers_match_the_published_analysis():
    analysis = json.loads((REPO / "data" / "analysis.json").read_text())
    assert resolve("median_t_total_C", repo=REPO) == analysis["distributions"]["C"]["p50"]
    d = resolve("difference_of_contrasts", repo=REPO)
    assert (d["lo"], d["hi"]) == (
        analysis["difference_of_contrasts_t_total"]["lo"],
        analysis["difference_of_contrasts_t_total"]["hi"],
    )


def test_the_single_sample_interval_is_the_gated_n99_sample():
    """The statistics module is pinned to the repeat-host sample, not the raw
    n=100 that still contains the 2266s first-touch run."""
    ci = resolve("arm_a_ci_n99", repo=REPO)
    assert ci["n"] == 99
    assert round(ci["lo"], 2) == 80.91
    assert round(ci["hi"], 2) == 85.88


def test_unknown_key_raises():
    with pytest.raises(KeyError):
        resolve("not_a_key", repo=REPO)
```

- [ ] **Step 3: Run and confirm it fails**

```bash
.venv/bin/pytest tests/test_explainer_numbers.py -q
```

Expected: `ModuleNotFoundError: No module named 'coldstart.explainer.numbers'`.

- [ ] **Step 4: Implement**

`coldstart/explainer/numbers.py`:

```python
"""Resolve the explainer's key list against committed data.

A tutorial about measurement discipline that disagrees with its own dataset
refutes itself. Nothing numeric reaches the page except through here.
"""

import json
from pathlib import Path

from coldstart.analysis.metrics import derive
from coldstart.analysis.stats import bootstrap_median_ci
from coldstart.store import JsonlStore

KEYS: dict = json.loads((Path(__file__).resolve().parents[2] / "explainer" / "numbers.json").read_text())

_FIRST_TOUCH_THRESHOLD_S = 200.0


def _rows(repo: Path) -> list[dict]:
    return [derive(r) for r in JsonlStore(str(Path(repo) / "data" / "campaign.jsonl")).read_all()]


def _dig(obj, path: str):
    for part in path.split("."):
        obj = obj[part]
    return obj


def arm_a_ci_n99(repo: Path) -> dict:
    """Arm A's median interval on the gated, repeat-host sample.

    Explicitly not the raw n=100: that still contains the single first-touch
    run at 2266s. Using the gated sample is also a free demonstration of the
    gate the page teaches.
    """
    vals = [r["t_total"] for r in _rows(repo)
            if r["arm"] == "A" and r["t_total"] < _FIRST_TOUCH_THRESHOLD_S]
    out = bootstrap_median_ci(vals)
    out["n"] = len(vals)
    return out


def first_touch_seconds(repo: Path) -> float:
    return max(r["t_total"] for r in _rows(repo))


def gpu_hours_a_n99(repo: Path) -> float:
    vals = [r["t_total"] for r in _rows(repo)
            if r["arm"] == "A" and r["t_total"] < _FIRST_TOUCH_THRESHOLD_S]
    return sum(vals) / 3600.0


def hosts_observed(repo: Path) -> int:
    return len({r["host_id"] for r in _rows(repo)})


_COMPUTED = {
    "arm_a_ci_n99": arm_a_ci_n99,
    "first_touch_seconds": first_touch_seconds,
    "gpu_hours_a_n99": gpu_hours_a_n99,
    "hosts_observed": hosts_observed,
}


def resolve(key: str, repo: Path):
    if key not in KEYS:
        raise KeyError(f"{key!r} is not on the explainer key list; add it to explainer/numbers.json")
    spec = KEYS[key]
    if spec["source"] == "analysis":
        analysis = json.loads((Path(repo) / "data" / "analysis.json").read_text())
        return _dig(analysis, spec["path"])
    if spec["source"] == "computed":
        return _COMPUTED[spec["fn"]](repo)
    rows = _rows(repo)
    if spec["kind"] == "count":
        return len(rows)
    return {a: sum(1 for r in rows if r["arm"] == a) for a in ("A", "B", "C")}
```

- [ ] **Step 5: Run and confirm they pass**

```bash
.venv/bin/pytest tests/test_explainer_numbers.py -q
```

Expected: all pass, including `arm_a_ci_n99` at exactly `[80.91, 85.88]` with `n == 99`.

- [ ] **Step 6: Commit**

```bash
.venv/bin/ruff check coldstart tests && .venv/bin/ruff format coldstart/explainer tests/test_explainer_numbers.py
git add explainer/numbers.json coldstart/explainer/numbers.py tests/test_explainer_numbers.py
git commit -m "explainer: an explicit key list, not 'every number matches analysis.json'

That earlier requirement was unsatisfiable -- analysis.json carries no
per-phase medians, no paired B->C contrast, no first-touch run and no
single-sample interval. The key list names each number and where it comes
from, and the test asserts each one resolves."
```

---

## Task 7: The jargon contract

**Files:**
- Create: `explainer/terms.json`, `coldstart/explainer/jargon.py`
- Test: `tests/test_explainer_jargon.py`

- [ ] **Step 1: Write the terms file**

`explainer/terms.json`:

```json
{
  "cold start": "the wait while a machine boots and loads a model, before anyone gets an answer",
  "HBM": "the GPU's own memory, separate from the computer's RAM",
  "KV cache": "per-conversation scratch space the model keeps on the GPU while generating",
  "torch.compile": "a step that turns the model into faster GPU code before serving",
  "CUDA graph capture": "recording a fixed sequence of GPU operations so they replay without per-step overhead",
  "continuous batching": "serving many users' requests through one copy of the model at once",
  "forward pass": "running the model once, start to finish, on some input",
  "bootstrap interval": "a range showing how much a summary number could move if the measurements had come out slightly differently",
  "percentile": "the value below which a given share of measurements fall",
  "ECDF": "a chart showing what share of runs finished by each time",
  "contrast": "the difference between two arms, measured on the same quantity",
  "pre-registration": "writing down what counts as a result before looking at the data",
  "drawing with replacement": "picking a value, writing it down, putting it back, and picking again"
}
```

- [ ] **Step 2: Write the failing test**

```python
from pathlib import Path

from coldstart.explainer.jargon import TERMS, undefined_terms

REPO = Path(__file__).resolve().parents[1]


def test_a_term_used_without_its_definition_is_reported():
    page = "<p>The KV cache is sized at startup.</p>"
    assert "KV cache" in undefined_terms(page)


def test_a_term_used_with_its_definition_passes():
    page = f"<p>The KV cache — {TERMS['KV cache']} — is sized at startup.</p>"
    assert "KV cache" not in undefined_terms(page)


def test_a_page_using_no_listed_terms_reports_nothing():
    assert undefined_terms("<p>Nothing technical here.</p>") == []
```

- [ ] **Step 3: Run and confirm it fails**

```bash
.venv/bin/pytest tests/test_explainer_jargon.py -q
```

Expected: `ModuleNotFoundError: No module named 'coldstart.explainer.jargon'`.

- [ ] **Step 4: Implement**

```python
"""The jargon contract, as a check rather than an intention.

"Avoid jargon" cannot be tested. "Every listed term that appears on the page
appears with its definition" can be, and that is the version that survives
contact with a build.
"""

import json
from pathlib import Path

TERMS: dict[str, str] = json.loads(
    (Path(__file__).resolve().parents[2] / "explainer" / "terms.json").read_text()
)


def undefined_terms(html: str) -> list[str]:
    """Listed terms that appear in `html` without their definition nearby."""
    missing = []
    for term, definition in TERMS.items():
        if term.lower() not in html.lower():
            continue
        if definition.lower()[:40] not in html.lower():
            missing.append(term)
    return missing
```

- [ ] **Step 5: Run and confirm they pass**

```bash
.venv/bin/pytest tests/test_explainer_jargon.py -q
```

- [ ] **Step 6: Commit**

```bash
.venv/bin/ruff check coldstart tests && .venv/bin/ruff format coldstart/explainer tests/test_explainer_jargon.py
git add explainer/terms.json coldstart/explainer/jargon.py tests/test_explainer_jargon.py
git commit -m "explainer: the jargon contract as a check

'Avoid jargon' is not testable. 'Every listed term appears with its
definition' is."
```

---

## Task 8: The build script

**Files:**
- Create: `scripts/build_explainer.py`, `explainer/page.html` (minimal skeleton for now)
- Test: `tests/test_explainer_build.py`

- [ ] **Step 1: Write a minimal page skeleton**

`explainer/page.html` — enough to build against; content lands in Tasks 10–11:

```html
<title>Where a Cold Start Goes</title>
<h1>Where a cold start goes</h1>
<p>Arm C's median cold start is {{median_t_total_C}} seconds, against
{{median_t_total_A}} with nothing cached.</p>
<figure>{{chart:kv_dividend}}</figure>
<pre><code>{{excerpt:preflight-refuses}}</code></pre>
```

- [ ] **Step 2: Write the failing test**

```python
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _build(tmp_path):
    out = tmp_path / "index.html"
    r = subprocess.run(
        [sys.executable, "scripts/build_explainer.py", "--out", str(out)],
        cwd=REPO, capture_output=True, text=True,
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


def test_build_fails_loudly_on_an_unknown_placeholder(tmp_path, monkeypatch):
    bad = REPO / "explainer" / "_bad.html"
    bad.write_text("{{not_a_key}}")
    try:
        r = subprocess.run(
            [sys.executable, "scripts/build_explainer.py", "--page", str(bad),
             "--out", str(tmp_path / "x.html")],
            cwd=REPO, capture_output=True, text=True,
        )
        assert r.returncode != 0
        assert "not_a_key" in r.stderr
    finally:
        bad.unlink()
```

- [ ] **Step 3: Run and confirm it fails**

```bash
.venv/bin/pytest tests/test_explainer_build.py -q
```

Expected: failure — `scripts/build_explainer.py` does not exist.

- [ ] **Step 4: Implement**

```python
"""Assemble the explainer page from committed data.

Three substitutions, all of them derivations rather than transcriptions:
{{key}} for a number on the key list, {{chart:name}} for an SVG rendered from
the campaign, {{excerpt:slug}} for code pulled from the running source. An
unknown placeholder is a build failure, not a silently empty page.

    .venv/bin/python scripts/build_explainer.py --out build/explainer/index.html
"""

import argparse
import re
import sys
from pathlib import Path

from coldstart.analysis.metrics import derive
from coldstart.analysis.stats import bootstrap_median_ci  # noqa: F401  (chart dependency)
from coldstart.explainer.excerpts import extract
from coldstart.explainer.jargon import undefined_terms
from coldstart.explainer.numbers import resolve
from coldstart.store import JsonlStore

REPO = Path(__file__).resolve().parents[1]
PLACEHOLDER = re.compile(r"\{\{([^}]+)\}\}")


def _fmt(value) -> str:
    if isinstance(value, dict) and {"lo", "hi"} <= set(value):
        return f"[{value['lo']:.2f}, {value['hi']:.2f}]"
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


def _chart(name: str, tmp: Path) -> str:
    from coldstart.analysis import figures

    rows = [derive(r) for r in JsonlStore(str(REPO / "data" / "campaign.jsonl")).read_all()]
    out = tmp / f"{name}.svg"
    if name == "kv_dividend":
        figures.kv_dividend(rows, out)
    elif name == "ecdf":
        figures.ecdf_plot([r for r in rows if r["t_total"] < 200], out)
    elif name == "waterfall":
        figures.waterfall(rows, out)
    elif name == "resample":
        vals = [r["t_total"] for r in rows if r["arm"] == "A" and r["t_total"] < 200]
        figures.resample_frames(vals, out)
    else:
        raise SystemExit(f"unknown chart {name!r}")
    svg = out.read_text()
    return svg[svg.index("<svg") :]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", default=str(REPO / "explainer" / "page.html"))
    ap.add_argument("--out", default=str(REPO / "build" / "explainer" / "index.html"))
    args = ap.parse_args()

    page = Path(args.page).read_text()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.parent / "_charts"
    tmp.mkdir(exist_ok=True)

    def substitute(m: re.Match) -> str:
        token = m.group(1).strip()
        try:
            if token.startswith("chart:"):
                return _chart(token.split(":", 1)[1], tmp)
            if token.startswith("excerpt:"):
                return extract(token.split(":", 1)[1], repo=REPO)
            return _fmt(resolve(token, repo=REPO))
        except (KeyError, LookupError) as exc:
            print(f"build_explainer: {token}: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc

    html = PLACEHOLDER.sub(substitute, page)
    missing = undefined_terms(html)
    if missing:
        print(f"build_explainer: terms used without a definition: {missing}", file=sys.stderr)
        return 1
    out.write_text(html)
    print(f"built {out} ({len(html):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run and confirm they pass**

```bash
.venv/bin/pytest tests/test_explainer_build.py -q
.venv/bin/python scripts/build_explainer.py --out build/explainer/index.html
```

Expected: tests pass; build prints a byte count.

- [ ] **Step 6: Commit**

```bash
.venv/bin/ruff check coldstart scripts tests && .venv/bin/ruff format scripts/build_explainer.py tests/test_explainer_build.py
git add scripts/build_explainer.py explainer/page.html tests/test_explainer_build.py
git commit -m "explainer: build the page from committed data

Numbers, charts and code excerpts are all substitutions from source. An
unknown placeholder fails the build rather than leaving a gap on the page."
```

---

## Task 9: The spine diagram and scroll choreography

**UI task.** Verification per `superpowers:verifying-visual-output` — computed style plus screenshots, never DOM presence alone.

**Files:**
- Create: `explainer/spine.svg`
- Modify: `explainer/page.html`

- [ ] **Step 1: Author the spine SVG**

One `<g id="zone-N">` per zone (1–7), one `<g id="clock-X">` per clock badge (A, B, C), one `<g id="edge-N">` per labelled edge. Every group carries `class="dim"` by default. Edge labels state what travels: `{arm, run_id}`, `vllm serve subprocess`, `stdout lines`, `S* marks`, `result JSON`, `campaign.jsonl row`, `derived row`, `chart`.

- [ ] **Step 2: Add the choreography**

In `explainer/page.html`, inline (no external library — the CSP blocks them):

```html
<style>
  #spine .dim { opacity: .28; transition: opacity .35s ease; }
  #spine .lit { opacity: 1; }
  #spine .lit rect, #spine .lit path { stroke-width: 2.2; }
  @media (max-width: 767px) { #spine { position: static; max-height: 38vh; } }
  @media (min-width: 768px) { #spine { position: sticky; top: 1.5rem; } }
</style>
<script>
  const beats = document.querySelectorAll("[data-lights]");
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      document.querySelectorAll("#spine g").forEach(g => g.classList.remove("lit"));
      for (const id of e.target.dataset.lights.split(",")) {
        document.getElementById(id.trim())?.classList.add("lit");
      }
    }
  }, { rootMargin: "-45% 0px -45% 0px" });
  beats.forEach(b => io.observe(b));
</script>
```

Each Part I beat is `<section data-lights="zone-3,clock-B">`.

- [ ] **Step 3: Build and verify computed style, not presence**

```bash
.venv/bin/python scripts/build_explainer.py --out build/explainer/index.html
```

Then in the Browser pane:

```
mcp__Claude_Browser__navigate({ url: "file:///Users/oleksiiostapiuk/projects/ai/artifacts/build/explainer/index.html" })
mcp__Claude_Browser__javascript_tool({ action: "javascript_exec", text:
  "getComputedStyle(document.querySelector('#spine g.dim')).opacity" })
```

Expected: `"0.28"` — proving the CSS applied, which `querySelector` alone would not.

- [ ] **Step 4: Screenshot and look at it**

```
mcp__Claude_Browser__computer({ action: "screenshot" })
```

Confirm the spine renders, is legible, and that scrolling to a later beat changes which zone is lit.

- [ ] **Step 5: Commit**

```bash
git add explainer/spine.svg explainer/page.html
git commit -m "explainer: the spine, and the scroll choreography that lights it

IntersectionObserver rather than a library -- the Artifact CSP blocks external
hosts. Edges carry labels because the ask was how components interact, and an
unlabelled arrow does not answer that."
```

---

## Task 10: Part I — one run's journey

**Files:**
- Modify: `explainer/page.html`

- [ ] **Step 1: Write the twelve beats**

One `<section data-lights="...">` per beat from the spec's table. Beat 10 is **"nothing is judged yet — the row goes down raw"** and beat 12 carries the reconciliation; getting these the wrong way round teaches the opposite of what `store.py` enforces.

- [ ] **Step 2: Write the zone-4 vLLM section**

Required content, per spec: what an inference server replaces (a loop calling `model.generate()`); that it is an HTTP server started here as a subprocess on port 8000, polled at `/health`, sent warmup requests at `/v1/completions`; that it holds one copy of the weights and multiplexes requests, which is continuous batching; that the KV cache is per-conversation scratch and therefore caps concurrency; one "what vLLM is not" line. Then the KV dividend chart via `{{chart:kv_dividend}}`.

- [ ] **Step 3: Write the six cards**

Each card: what it is, its one job, the failure it prevents, what it hands off to — then `<details><summary>Show the code</summary><pre><code>{{excerpt:SLUG}}</code></pre></details>`, collapsed.

- [ ] **Step 4: Build and check the jargon gate**

```bash
.venv/bin/python scripts/build_explainer.py --out build/explainer/index.html
```

Expected: exit 0. A non-zero exit listing terms means a term was used without its definition — add the definition rather than deleting the term.

- [ ] **Step 5: Commit**

```bash
git add explainer/page.html
git commit -m "explainer: Part I -- one run's journey, and the six cards"
```

---

## Task 11: Part II — the method narrative

**Files:**
- Modify: `explainer/page.html`

- [ ] **Step 1: Write the four acts**

Per the spec's table. Act 3 uses `{{chart:shortcut_panels}}` and must state the honest lesson: the shortcut works on this campaign, fails on correlated estimates, and nothing visible in the two intervals says which case you are in.

- [ ] **Step 2: Add the statistics module content**

The five-step sequence from the spec's Calibration section, in order, using `{{chart:resample}}` and `{{chart:ecdf}}`. Step 0 pins the sample to n=99 and says why.

- [ ] **Step 3: Write the closing card**

The four questions, in a container styled for screenshotting.

- [ ] **Step 4: Build and verify no placeholder survived**

```bash
.venv/bin/python scripts/build_explainer.py --out build/explainer/index.html && .venv/bin/pytest tests/test_explainer_build.py -q
```

- [ ] **Step 5: Commit**

```bash
git add explainer/page.html
git commit -m "explainer: Part II -- the four acts and the statistics sequence"
```

---

## Task 12: The learning plan and progress record

**Files:**
- Create: `docs/learning/plan.md`, `docs/learning/progress.md`

- [ ] **Step 1: Write the module list**

`docs/learning/plan.md` — the spec's modules table verbatim, including the page sections and minutes columns, and the pass criterion: *the learner states the idea in their own words without the material in front of them, and the statement survives one follow-up question.*

- [ ] **Step 2: Write the progress record with module 0 filled in**

```markdown
# Learning progress

Updated at each checkpoint. On a fail, do not repeat the same explanation —
branch to a different representation and record which one worked.

## Module 0 — diagnostic
- attempted: 2026-09-17
- verdict: fuzzy (statistics); solid (serverless); above self-report (GPU)
- what_the_answer_missed: that a confidence interval ranges over *medians* of
  imagined re-runs, not over the runs themselves. Stated as "where the majority
  of numbers landed — a bell curve".
- correction_issued: five steps — refute with his own data (the interval spans
  a gap with zero runs), shrink to five numbers, name the wrong word
  ("shuffling" → drawing with replacement), the controlled test where clusters
  hold still and only the split moves, and the cost contrast (99 real runs vs
  10,000 free resamples). Worked at step 4; the abstract definition had failed
  twice before it.
```

- [ ] **Step 3: Commit**

```bash
git add docs/learning
git commit -m "learning: the plan, and module 0's record

Module 0 is already complete -- the diagnostic found the interval
misconception and the sequence that fixed it, which is exactly what a progress
entry is for."
```

---

## Task 13: Manual visual checkpoint — desktop and mobile

**Mandatory final UI verification.** This catches what the automated layers cannot.

- [ ] **Step 1: Build the page**

```bash
.venv/bin/python scripts/build_explainer.py --out build/explainer/index.html
```

- [ ] **Step 2: Open it at desktop width**

```
mcp__Claude_Browser__navigate({ url: "file:///Users/oleksiiostapiuk/projects/ai/artifacts/build/explainer/index.html" })
mcp__Claude_Browser__resize_window({ width: 1280, height: 900 })
mcp__Claude_Browser__computer({ action: "screenshot" })
```

- [ ] **Step 3: Perform the reader's flow and look**

Scroll through all twelve Part I beats and all four Part II acts. Screenshot at least: the spine with a mid-journey zone lit, one open code card, the shortcut panels, and the closing card. **Look at each screenshot.** Confirm the lit zone matches the beat's prose, and that panel 1 of the shortcut chart shows red sitting on green while panel 2 shows red much longer.

- [ ] **Step 4: Repeat at mobile width**

```
mcp__Claude_Browser__resize_window({ preset: "mobile" })
mcp__Claude_Browser__navigate({ url: "file:///Users/oleksiiostapiuk/projects/ai/artifacts/build/explainer/index.html" })
mcp__Claude_Browser__computer({ action: "screenshot" })
```

Confirm: the spine moves above the prose rather than sticking beside it, no horizontal scrolling, and chart text is readable. The four existing figures regressed on phones twice in this repo's history — assume these will too until a screenshot says otherwise.

- [ ] **Step 5: Verify both themes**

```
mcp__Claude_Browser__resize_window({ colorScheme: "dark" })
mcp__Claude_Browser__computer({ action: "screenshot" })
```

Confirm the SVG spine and charts are legible on a dark background — matplotlib SVGs carry explicit colours and can vanish.

- [ ] **Step 6: Commit any fixes, then record**

```bash
git add -A && git commit -m "explainer: fixes from the desktop/mobile/dark visual checkpoint"
```

---

## Task 14: Publish as an Artifact

- [ ] **Step 1: Read the whole built page**

```bash
wc -l build/explainer/index.html
```

Read it start to finish. Publishing distributes it; do not publish a file you have not read.

- [ ] **Step 2: Publish**

```
Artifact({
  file_path: "build/explainer/index.html",
  title: "Where a Cold Start Goes",
  description: "How 81 seconds of vLLM startup was measured, and how to judge a performance claim.",
  favicon: "⏱️"
})
```

- [ ] **Step 3: Open the published URL and screenshot it**

The Artifact sandbox is not `file://` — the CSP is strict there and is the environment where an inlined-asset mistake actually surfaces. Screenshot desktop and mobile again.

- [ ] **Step 4: Record the URL**

Add it to `docs/learning/plan.md` so the modules point at the material.

```bash
git add docs/learning/plan.md && git commit -m "learning: link the published explainer"
```

---

## Task 15 (optional — needs sign-off): the in-page tutor

**Do not start without explicit go-ahead.** The learner will mostly be taught in-session, where the tutor has the repo and continuity; this task buys availability, not depth. Cost is real and the viewer pays per question.

If approved: declare `capabilities: {sample: {}}`, put the affordance **per-card and per-chart** rather than one global button, and invoke it with the section's rendered text plus that section's resolved numbers block, instructing it to refuse any figure not in the block and say it is refusing. Hide the affordance when `claude.use("sample")` resolves `null`.

---

## Self-Review

**Spec coverage.** Learning objectives → Tasks 10–12. Calibration/statistics sequence → Tasks 1, 3, 11. Two organizing ideas → Tasks 9, 10. Part I journey → Task 10. Zone 4 vLLM → Task 10 step 2. Component map and cards → Tasks 5, 10. Part II acts → Task 11. Charts → Tasks 2–4, 8. The shortcut panels → Task 4. Standing rule → Task 4 step 1, as a test. Anti-drift 1–5 → Tasks 1, 5, 6, 8. Jargon contract → Task 7. Build and tooling → Tasks 8, 9. Learning plan and tutoring loop → Tasks 12, 15. Out of scope respected: no present mode, no playground, no bootstrap derivation, one page.

**Gap accepted and named:** the spec's `warmup` and `per_host` charts are reused unchanged from `figures.py` and appear only if Part II's acts reference them; they need no task because no code changes.

**Placeholders:** none. Every code step carries the code; every command carries expected output.

**Type consistency:** `bootstrap_median_ci` returns `{point, lo, hi}` in Task 1 and Task 6 adds `n` to its own copy before returning — Task 6's test asserts `ci["n"]`, which Task 6 supplies rather than Task 1. `extract(slug, repo)` and `resolve(key, repo)` keep the same signatures across Tasks 5, 6 and 8. `shortcut_panels.correlated_example()` is defined in Task 4 and used only there.

**UI verification audit.** Task 9 asserts computed `opacity`, not presence. No encapsulation boundary exists, so Rule 2 does not apply — stated in the header. No UI is removed, so Rule 3 does not apply. Task 13 is the manual checkpoint at 1280px and 375px plus dark mode, and Task 14 repeats it on the published URL where the real CSP applies.

**Parity audit:** not applicable — nothing is replaced, slimmed or deleted. Stated in the header.
