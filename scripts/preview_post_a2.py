"""Write build/post-a2-preview.html: artifact 2's post rendered in a browser, for the
final read-through at desktop and phone width.

No Markdown package is installed, so the page embeds the post's text and renders it
client-side with marked. The figures are inlined as data URIs, because the
browser pane opens a local file as a static snapshot in which relative image paths
do not resolve. Rejected: a Python Markdown dependency added only for a preview the
publishing site will render its own way; the preview is for eyes, not for bytes.
"""

import base64
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
POST = REPO / "docs" / "post-a2.md"
OUT = REPO / "build" / "post-a2-preview.html"

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Artifact 2 post preview</title>
<style>
 body {{ max-width: 760px; margin: 0 auto; padding: 16px; background: #fff; color: #222;
        font: 17px/1.55 Georgia, serif; }}
 img {{ max-width: 100%; height: auto; display: block; margin: 1em 0; }}
 table {{ border-collapse: collapse; display: block; overflow-x: auto; font-size: 0.85em; }}
 th, td {{ border: 1px solid #ccc; padding: 4px 8px; }}
 pre, code {{ font-size: 0.85em; overflow-x: auto; }}
 blockquote {{ border-left: 4px solid #c0392b; margin-left: 0; padding-left: 12px; }}
</style></head><body>
<div id="post"></div>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<script>
 const md = {md};
 document.getElementById("post").innerHTML = marked.parse(md);
</script>
</body></html>
"""


def main() -> None:
    def inline(m: re.Match) -> str:
        data = base64.b64encode((REPO / "docs" / m.group(1)).read_bytes()).decode()
        return f"](data:image/png;base64,{data})"

    md = re.sub(r"\]\((figures/a2/[\w-]+\.png)\)", inline, POST.read_text())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(PAGE.format(md=json.dumps(md)))
    print(OUT)


if __name__ == "__main__":
    main()
