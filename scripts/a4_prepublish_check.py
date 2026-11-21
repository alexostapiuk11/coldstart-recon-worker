"""Refuse to call artifact 4's post publishable while a placeholder stands.

    python scripts/a4_prepublish_check.py [--post docs/post-a4.md]
                                          [--analysis data/a4/analysis.json]

Prints each problem with what it would cost the published post and exits 1, or
prints "ok" and exits 0. It refuses:

- `PUBLICATION-DATE` in the post: the byline would carry a placeholder for a date;
- `DRAFT for the owner's review` in the post: the post would publish with its
  draft banner;
- `spend` null in the analysis: no number in the post could come from a measured
  spend, so any spend figure would have been typed by hand.

HTML comments are skipped: the post's header comment names the placeholders to
document them, and refusing it would make the check impossible to pass.
Rejected: a checklist in the plan alone, which a tired owner can tick without
looking; this reads the files that will ship.
"""

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
POST = REPO / "docs" / "post-a4.md"
ANALYSIS = REPO / "data" / "a4" / "analysis.json"

PLACEHOLDERS = {
    "PUBLICATION-DATE": "the byline would publish a placeholder instead of the publication "
                        "date; set it to the date the post goes live",
    "DRAFT for the owner's review": "the post would publish with its draft banner; A4 loses the DRAFT "
                                    "line when it is dated (spec §4 step 2)",
}
COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def problems(post_text: str, analysis: dict) -> list[str]:
    body = COMMENT.sub("", post_text)
    found = []
    for token, consequence in PLACEHOLDERS.items():
        lines = [i for i, line in enumerate(body.splitlines(), 1) if token in line]
        if lines:
            found.append(f"{token} is still in the post (outside comments, {len(lines)} "
                         f"line(s)): {consequence}")
    if analysis.get("spend") is None:
        found.append("spend is null in data/a4/analysis.json: the post's spend could not come from a "
                     "measured record, so any figure in it would be typed by hand. docs/spend-a4.md "
                     "holds $25.2311 over 248 jobs and 22.77 billed hours, read from the billing API; "
                     "the owner confirms that total against the RunPod console, then it is recorded in "
                     "the analysis and this check passes")
    return found


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--post", type=Path, default=POST)
    ap.add_argument("--analysis", type=Path, default=ANALYSIS)
    args = ap.parse_args(argv)
    found = problems(args.post.read_text(), json.loads(args.analysis.read_text()))
    if found:
        print(f"refused: {args.post} is not ready to publish", file=sys.stderr)
        for p in found:
            print(f"- {p}", file=sys.stderr)
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
