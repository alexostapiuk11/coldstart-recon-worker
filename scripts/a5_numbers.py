"""Write, or check, the numbers block in artifact 5's post.

    .venv/bin/python scripts/a5_numbers.py            # rewrite the block
    .venv/bin/python scripts/a5_numbers.py --check    # exit 1 if it is stale
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from multilora.numbers import block_in, numbers_block, replace_block

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--analysis", default=str(REPO / "data" / "a5" / "analysis.json"))
    ap.add_argument("--post", default=str(REPO / "docs" / "post-a5.md"))
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    block = numbers_block(json.loads(Path(args.analysis).read_text()))
    post = Path(args.post)
    text = post.read_text()
    if args.check:
        if block_in(text) != block:
            print("stale: run scripts/a5_numbers.py", file=sys.stderr)
            return 1
        print("numbers block is current")
        return 0
    post.write_text(replace_block(text, block))
    print(f"[ok] {post}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
