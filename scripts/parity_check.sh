#!/usr/bin/env bash
# Every published artifact-1 number and pixel, re-derived from the stored
# records. Run after every refactor step: this is the gate that a move changed
# nothing, and "the tests pass" is not that gate -- the tests exercise the code,
# this exercises the published result.
#
# Figures are compared against docs/figures/, NOT build/figures-final/. Both
# directories hold byte-identical copies today, but build/ is gitignored, so a
# gate pointed at it silently cannot run on a fresh clone -- and docs/figures/
# is the copy the post actually links. That distinction is not hypothetical:
# artifact 1's pre-publish gate caught the post linking into the ignored build/
# directory, which is why the tracked copy exists at all.
#
# PYTHONDONTWRITEBYTECODE=1 throughout: .pyc invalidation keys on mtime-seconds
# plus size, and `git mv` preserves neither reliably across a fast refactor, so
# a stale bytecode cache can make a moved module look like it still works.
set -euo pipefail

PY=.venv/bin/python
export PYTHONDONTWRITEBYTECODE=1
OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT

echo "== tests =="
$PY -m pytest -q

echo "== lint =="
$PY -m ruff check .

echo "== analysis: every published number =="
$PY scripts/analyse.py --store data/campaign.jsonl > "$OUT/analysis.json"
if ! diff -q "$OUT/analysis.json" data/analysis.json > /dev/null; then
  echo "PARITY FAILURE: analysis output differs from data/analysis.json"
  diff "$OUT/analysis.json" data/analysis.json | head -40
  exit 1
fi
echo "analysis.json: identical"

echo "== figures: every published pixel =="
$PY scripts/render_figures.py --store data/campaign.jsonl --out "$OUT/figures" > /dev/null
for f in waterfall warmup ecdf per_host; do
  if ! cmp -s "$OUT/figures/$f.png" "docs/figures/$f.png"; then
    echo "PARITY FAILURE: $f.png differs from docs/figures/$f.png"
    exit 1
  fi
  echo "$f.png: identical"
done

echo
echo "PARITY OK"
