"""Assemble the explainer page from committed data.

Three substitutions, all derivations rather than transcriptions:
{{key}} for a number on the key list, {{chart:name}} for an SVG rendered from
the campaign, {{excerpt:slug}} for code pulled from the running source. An
unknown placeholder is a build failure, not a silently empty page.

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
from coldstart.explainer.jargon import undefined_terms
from coldstart.explainer.numbers import resolve
from coldstart.store import JsonlStore

REPO = Path(__file__).resolve().parents[1]
PLACEHOLDER = re.compile(r"\{\{([^}]+)\}\}")

# The gate the page itself teaches: the one first-touch run at 2266s is a
# different population from the other 99 and does not belong in a distribution
# chart. Kept as a named constant so it reads as a decision, not a magic number.
FIRST_TOUCH_THRESHOLD_S = 200.0


def _fmt(value) -> str:
    if isinstance(value, dict) and {"lo", "hi"} <= set(value):
        return f"[{value['lo']:.2f}, {value['hi']:.2f}]"
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


class _Charts:
    """Renders a named chart to inline SVG, reading the campaign at most once."""

    def __init__(self, repo: Path, tmp: Path) -> None:
        self.repo = repo
        self.tmp = tmp
        self._rows: list[dict] | None = None

    def rows(self) -> list[dict]:
        if self._rows is None:
            store = JsonlStore(str(self.repo / "data" / "campaign.jsonl"))
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
        else:
            raise LookupError(f"unknown chart {name!r}")
        svg = out.read_text()
        # matplotlib writes an XML declaration and a DOCTYPE ahead of the root
        # element; neither is legal inside an HTML document, so drop them.
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
    charts = _Charts(REPO, tmp)

    def substitute(m: re.Match) -> str:
        token = m.group(1).strip()
        try:
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
    missing = undefined_terms(html)
    if missing:
        print(f"build_explainer: terms used without a definition: {missing}", file=sys.stderr)
        return 1
    out.write_text(html)
    print(f"built {out} ({len(html):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
