"""Assemble the explainer page from committed data.

Four substitutions, all derivations rather than transcriptions:
{{key}} for a number on the key list, {{chart:name}} for an SVG rendered from
the campaign, {{excerpt:slug}} for code pulled from the running source, and
{{spine}} for the hand-authored apparatus diagram, kept in its own file so it
stays editable as a drawing. An unknown placeholder is a build failure, not a
silently empty page.

    .venv/bin/python scripts/build_explainer.py --out build/explainer/index.html
"""

import argparse
import html as html_mod
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coldstart.analysis.metrics import derive, rows_for_arm
from coldstart.explainer.excerpts import extract
from coldstart.explainer.jargon import TERMS, undefined_terms
from coldstart.explainer.numbers import resolve
from coldstart.schema import RunRecord
from harness.store import JsonlStore

REPO = Path(__file__).resolve().parents[1]
PLACEHOLDER = re.compile(r"\{\{([^}]+)\}\}")

# The gate the page itself teaches: the one first-touch run at 2266s is a
# different population from the other 99 and does not belong in a distribution
# chart. Kept as a named constant so it reads as a decision, not a magic number.
FIRST_TOUCH_THRESHOLD_S = 200.0


_METADATA = re.compile(r"<metadata>.*?</metadata>", re.DOTALL)
_SVG_ID = re.compile(r'\bid="([^"]+)"')
# The three places an id is written or referenced. Rewriting only inside these
# contexts keeps a stray match in ordinary text from being renamed.
_ID_CONTEXT = re.compile(r'(\bid="|url\(#|xlink:href="#|\bhref="#)([^"()]+)("|\))')


def _namespace_ids(svg: str, prefix: str) -> str:
    """Rename every element id in one chart's SVG, and every reference to it.

    Two problems at once. matplotlib names glyph definitions deterministically
    (`id="DejaVuSans-48"`), so two charts inlined into the same document both
    declare them and a browser resolves every reference to whichever came
    first -- the second chart would render the first chart's glyphs. And it
    mints clip-path ids from a per-figure random hash, so the same data built
    twice produced pages differing in thousands of characters.

    Numbering by order of first appearance fixes both. It cannot depend on the
    random text (sorting on it just moves the randomness into the numbering,
    which is the bug this replaced), and the document's structure is stable, so
    the same data yields the same page byte for byte.
    """
    order: list[str] = []
    seen: set[str] = set()
    for match in _SVG_ID.finditer(svg):
        raw = match.group(1)
        if raw not in seen:
            seen.add(raw)
            order.append(raw)
    mapping = {raw: f"{prefix}-{n}" for n, raw in enumerate(order)}

    def rewrite(match: re.Match) -> str:
        opener, raw, closer = match.group(1), match.group(2), match.group(3)
        return f"{opener}{mapping.get(raw, raw)}{closer}"

    return _ID_CONTEXT.sub(rewrite, svg)


# Regions whose text is not prose and must never be rewritten: code the reader
# is meant to read verbatim, the chart SVGs, the page's own script and style,
# and every HTML tag. re.split keeps the separators, so the odd indices of the
# result are exactly the protected spans.
_PROTECTED = re.compile(
    # A backreference, not an alternation of closing names. Written as
    # `</(?:pre|code|svg|...)>` an <svg> could be closed by the first </style>
    # inside it -- matplotlib emits one -- which ended the protected span early
    # and let the rest of every chart be rewritten as if it were prose.
    # Headings are protected alongside the verbatim regions, for a different
    # reason: the revealed definition is block-level, so a term inside an <h1>
    # splits the heading across the panel. A reader meets every term in prose
    # anyway, which is where the affordance belongs.
    r"<(pre|code|script|style|svg|h1|h2|h3|h4|title|summary)\b[^>]*>.*?</\1\s*>",
    re.DOTALL | re.IGNORECASE,
)
_TAG = re.compile(r"<[^>]+>|<!--.*?-->", re.DOTALL)


def _prose_spans(html: str):
    """The (start, end) ranges of `html` that are prose a reader reads.

    Everything else -- verbatim code, the chart SVGs, the page's own script and
    style, every tag and comment -- is skipped. Yielded in order so a caller can
    rebuild the document without reordering anything.
    """
    blocked = [m.span() for m in _PROTECTED.finditer(html)]
    for m in _TAG.finditer(html):
        if not any(s <= m.start() < e for s, e in blocked):
            blocked.append(m.span())
    blocked.sort()
    cursor = 0
    for start, end in blocked:
        if start > cursor:
            yield cursor, start
        cursor = max(cursor, end)
    if cursor < len(html):
        yield cursor, len(html)


def _glossary(html: str, terms: dict[str, str]) -> str:
    """Make every defined term clickable, revealing its own definition inline.

    The page defines each term once, in the paragraph that introduces it. Four
    thousand words later a reader who has forgotten one has to go hunting. This
    costs no tokens, asks no consent, and cannot contradict the page, because
    the text it shows IS the page's own definition -- the same string the build
    gate already requires to be present.

    Verified before relying on it: no definition contains another term, and no
    term is a substring of another, so wrapping cannot nest or corrupt a
    definition's contiguous text.
    """
    if not terms:
        return html
    pattern = re.compile(
        "|".join(re.escape(k) for k in sorted(terms, key=len, reverse=True))
    )

    def wrap(match: re.Match) -> str:
        term = match.group(0)
        return (
            f'<span class="gloss"><button type="button" class="term" '
            f'aria-expanded="false">{html_mod.escape(term)}</button>'
            f'<span class="def" hidden>{html_mod.escape(terms[term])}</span></span>'
        )

    out = []
    cursor = 0
    for start, end in _prose_spans(html):
        out.append(html[cursor:start])
        out.append(pattern.sub(wrap, html[start:end]))
        cursor = end
    out.append(html[cursor:])
    return "".join(out)


def _fmt(value) -> str:
    if isinstance(value, dict) and {"lo", "hi"} <= set(value):
        return f"[{value['lo']:.2f}, {value['hi']:.2f}]"
    if isinstance(value, float):
        # A count that arrives as a float -- kv_capacity_tokens comes through
        # median(), which returns one -- is still a count. Rendering it as
        # "35792.0 tokens" reads as a measurement with spurious precision, and
        # disagrees with the same figure formatted "35,792" inside the chart
        # right next to it. Seconds keep the one decimal place.
        if value.is_integer():
            return f"{int(value):,}"
        return f"{value:.1f}"
    return str(value)


class _Charts:
    """Renders a named chart to inline SVG, reading the campaign at most once."""

    def __init__(self, repo: Path, tmp: Path) -> None:
        self.repo = repo
        self.tmp = tmp
        self._rows: list[dict] | None = None
        self._chart_index = 0

    def rows(self) -> list[dict]:
        if self._rows is None:
            store = JsonlStore(str(self.repo / "data" / "campaign.jsonl"), RunRecord)
            self._rows = [derive(r) for r in store.read_all()]
        return self._rows

    def render(self, name: str) -> str:
        from coldstart.analysis import figures

        rows = self.rows()
        out = self.tmp / f"{name}.svg"
        if name == "kv_dividend":
            figures.kv_dividend(rows, out)
        elif name == "ecdf":
            figures.ecdf_plot([r for r in rows if r["t_total"] < FIRST_TOUCH_THRESHOLD_S], out)
        elif name == "waterfall":
            figures.waterfall(rows, out)
        elif name == "resample":
            # rows_for_arm rather than `r["arm"] == "A"`: arm-conditional logic
            # is confined to analysis/ by spec 6.3, and scripts/ should not be
            # the file that breaks the habit even though the scanner in
            # tests/test_arm_isolation.py does not currently look here.
            vals = [
                r["t_total"]
                for r in rows_for_arm(rows, "A")
                if r["t_total"] < FIRST_TOUCH_THRESHOLD_S
            ]
            figures.resample_frames(vals, out)
        elif name == "per_host":
            # Every row, not the gated 99: the whole point of the figure is
            # that all 300 paid runs landed on one host, and filtering first
            # would make the count drawn on the chart disagree with the
            # sentence standing next to it.
            figures.per_host_medians(rows, out)
        elif name == "shortcut":
            # shortcut_panels takes three already-computed intervals rather
            # than rows -- its lower panel is a constructed counter-example,
            # not anything this campaign measured. The upper panel's endpoints
            # come back through resolve() so the numbers drawn here are the
            # same objects the prose cites, instead of a second derivation
            # free to drift from it.
            intervals = {}
            for short, key in (
                ("ab", "contrast_ab_total"),
                ("bc", "contrast_bc_total"),
                ("diff", "difference_of_contrasts"),
            ):
                ci = resolve(key, repo=self.repo)
                intervals[short] = (ci["lo"], ci["hi"])
            figures.shortcut_panels(intervals, out)
        else:
            raise LookupError(f"unknown chart {name!r}")
        svg = out.read_text()
        # matplotlib writes an XML declaration and a DOCTYPE ahead of the root
        # element; neither is legal inside an HTML document, so drop them.
        svg = svg[svg.index("<svg") :]
        svg = _METADATA.sub("", svg)
        self._chart_index += 1
        return _namespace_ids(svg, f"c{self._chart_index}")


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
    charts = _Charts(REPO, tmp)

    def substitute(m: re.Match) -> str:
        token = m.group(1).strip()
        try:
            if token == "spine":
                # Not escaped, and deliberately not id-namespaced the way charts
                # are: the scroll choreography looks these groups up by their
                # literal ids, so rewriting them would silently unwire the page.
                # Chart ids get namespaced because matplotlib picks them; these
                # are picked by hand, and there is exactly one spine.
                return (REPO / "explainer" / "spine.svg").read_text().strip()
            if token.startswith("chart:"):
                # Not escaped: the SVG has to reach the page as markup.
                return charts.render(token.split(":", 1)[1])
            if token.startswith("excerpt:"):
                # Escaped: source code carries < and &, and unescaped it would
                # silently truncate or mangle the listing inside <pre><code>.
                return html_mod.escape(extract(token.split(":", 1)[1], repo=REPO))
            return _fmt(resolve(token, repo=REPO))
        except (KeyError, LookupError) as exc:
            print(f"build_explainer: {token}: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc

    html = PLACEHOLDER.sub(substitute, page)
    # Gate first, glossary second. The gate asserts each definition appears as
    # contiguous text; wrapping inserts markup between a term and its
    # definition, so running it the other way round would fail the check the
    # glossary depends on being true.
    missing = undefined_terms(html)
    if missing:
        print(f"build_explainer: terms used without a definition: {missing}", file=sys.stderr)
        return 1
    html = _glossary(html, TERMS)
    out.write_text(html)
    print(f"built {out} ({len(html):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
