# Harness Extraction — Fidelity Baseline

Captured before any module moved. `scripts/parity_check.sh` re-checks all of it.

## Suite

- `pytest -q`: **949 passed**
- `ruff check .`: **All checks passed**

The plan quotes 527 as the baseline. That number is from 2026-09-03; the suite
has since gained artifact 2's simulator and statistical layer, its figure
guards, and the explainer's tests. 949 is the count at the commit this baseline
was captured. **Do not treat the plan's per-task "expected count" arithmetic as
absolute** — carry it forward from 949, and treat any *decrease* as a test file
that stopped being collected rather than as a stale constant.

## Published artifact-1 output — sha256

| File | sha256 |
|---|---|
| `data/analysis.json` | `1c30e2310a70e56ac0bdd68d6e4dcdf0dba9e3a5a374bf8792dd48e372a70e95` |
| `docs/figures/waterfall.png` | `e45925a04901b169ac605a0b823783795d53dd97719dbcd7b3d0c625a1bf72f2` |
| `docs/figures/warmup.png` | `c6b127f8bd7b503687576f6745aff4dec611357ef10a057dd88acc157ae75731` |
| `docs/figures/ecdf.png` | `93a130f40467a9583e94659e5d47110865c4825760a583874e0e902aef38e501` |
| `docs/figures/per_host.png` | `51d104044e76529302413c73c81de8ff7e63d913d59738636a04ac871f486949` |

These match the digests the plan recorded against `build/figures-final/` — the
two directories hold byte-identical copies, verified with `cmp` when this
baseline was taken.

**The gate compares against `docs/figures/`, not `build/figures-final/`.** The
plan named the latter, and `build/` is gitignored, so a gate pointed there
silently cannot run on a fresh clone. `docs/figures/` is also the copy the post
actually links — artifact 1's pre-publish gate caught the post linking into the
ignored `build/` directory, which is why the tracked copy exists at all.
`tests/test_published_figures.py` independently guards the tracked copies
against drift.

The `*-phone.png` variants are downscales of the four above (artifact-1 campaign
plan, Task 11 Step 4), not separate renders. Pixel-identical sources mean
identical downscales, so the gate covers them transitively.

## Reproduce

```bash
./scripts/parity_check.sh
```

Or by hand:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/analyse.py --store data/campaign.jsonl | diff - data/analysis.json
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/render_figures.py --store data/campaign.jsonl --out /tmp/f
cmp /tmp/f/waterfall.png docs/figures/waterfall.png
```

## Known latent defect, recorded so a parity failure is not misread

`annotate_first_touch`'s docstring claims its ordering is "independent of read
order". It is not — the ordering depends on `run_index` being present on the
rows handed to it, and `metrics.derive()` drops that field. `autoscale`'s
adapter hit this and works around it by re-attaching `run_index` before the
call. `scripts/render_figures.py` is on the same path.

This is pre-existing and artifact 1's published numbers were produced with it,
so the parity gate passing is the correct outcome. Flagged here because
`annotate_first_touch` moves to `harness/publish.py` in Task 10: if a parity
failure appears there, this is the first thing to check, and fixing the
docstring-versus-behavior mismatch is a **separate** change from the move.
