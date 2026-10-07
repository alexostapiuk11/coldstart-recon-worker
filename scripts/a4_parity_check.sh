#!/usr/bin/env bash
# Every published artifact-4 number and pixel, re-derived from the committed
# stores. Artifact 1's scripts/parity_check.sh, pointed at artifact 4.
#
# The analysis re-runs the sweep unless build/a4-sweep holds its cached
# evaluations. On a fresh clone that is hours of CPU; with the cache, seconds.
# The cache key covers every input, so a stale cache is never reused.
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
# The cell stores that count: the original campaign, the re-run designs 1a and 1b, the
# retries of 1c and 1d, and the top-up 1e. The first attempts at 1c and 1d
# (cells-ramp-1c.jsonl, cells-ramp-1d.jsonl) hold only jobs that timed out in the queue
# when the account had no credit; they are evidence in docs/spend-a4.md and are not read.
CELLS="--cells data/a4/cells.jsonl --cells data/a4/cells-ramp-1a.jsonl --cells data/a4/cells-ramp-1b.jsonl --cells data/a4/cells-ramp-1c-retry.jsonl --cells data/a4/cells-ramp-1d-retry.jsonl --cells data/a4/cells-ramp-1e.jsonl"
# shellcheck disable=SC2086
$PY scripts/a4_analyse.py $CELLS --swaps data/a4/swaps.jsonl --sleep data/a4/sleep.jsonl \
  --replay data/a4/replay.jsonl --out "$OUT/analysis.json" > /dev/null
if ! diff -q "$OUT/analysis.json" data/a4/analysis.json > /dev/null; then
  echo "PARITY FAILURE: analysis output differs from data/a4/analysis.json"
  diff "$OUT/analysis.json" data/a4/analysis.json | head -40
  exit 1
fi
echo "analysis.json: identical"

echo "== artifact 5's file =="
$PY scripts/a4_cost_file.py --analysis data/a4/analysis.json --out "$OUT/cost.json" > /dev/null
cmp -s "$OUT/cost.json" data/a4/cost_per_tenant.json || { echo "PARITY FAILURE: cost_per_tenant.json"; exit 1; }
echo "cost_per_tenant.json: identical"

echo "== figures: every published pixel =="
$PY scripts/a4_render_figures.py --analysis data/a4/analysis.json --out "$OUT/figures" > /dev/null
for f in crossover deciles interference swap_stages; do
  for v in "$f" "$f-phone"; do
    cmp -s "$OUT/figures/$v.png" "docs/figures/a4/$v.png" || { echo "PARITY FAILURE: $v.png"; exit 1; }
  done
  echo "$f.png: identical"
done

echo
echo "PARITY OK"
