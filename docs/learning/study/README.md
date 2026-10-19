# Study units: interview preparation for the portfolio artifacts

Built from one `content.json` per unit by `scripts/build_study.py`; each unit has a visual
page (`page.html`) and a pasteable chat brief (`brief.md`). Design:
`docs/superpowers/specs/2026-10-18-interview-learning-resources-design.md`.

## How to study

1. Read P1 once (about 20 minutes). It explains GPU memory, the KV cache, vLLM, cold starts.
2. For an artifact: read its page top to bottom (about 45 minutes), then answer the recall
   check out loud before opening each answer.
3. Paste the unit's `brief.md` into an AI chat. Its last section is the interview-mode
   prompt: set AUDIENCE (hiring manager, senior peer, skeptic), DEPTH (pitch, standard, deep)
   and MODE (ask, quiz, grade).

## Units

| unit | title | min | files |
|---|---|---|---|
| p1 | LLM serving on a GPU | 20 | `p1/page.html`, `p1/brief.md` |
| p2 | How these experiments earn trust | 20 | `p2/page.html`, `p2/brief.md` |
| a1 | Where a vLLM cold start goes | 45 | `a1/page.html`, `a1/brief.md` |
| a2 | An autoscaling simulator that failed its own test | 45 | `a2/page.html`, `a2/brief.md` |
| a4 | Dedicate, swap or share | 45 | `a4/page.html`, `a4/brief.md` |
| a5 | How many LoRA adapters fit on one GPU | 45 | `a5/page.html`, `a5/brief.md` |
| a7 | The anatomy of a matching engine's tail | 45 | `a7/page.html`, `a7/brief.md` |

The unit for artifact 6 (in `~/projects/ledger-faults`) is not built yet.

## Published pages

Private Artifacts.

| unit | page |
|---|---|
| p1 | https://claude.ai/artifact/ERS8Z3tRWUkSD4131zgwzY |
| p2 | https://claude.ai/artifact/A4MJnGXGWMBmi5z5ntxZBz |
| a1 | https://claude.ai/artifact/2WmMh5z8C1bcehAmMurWQe |
| a2 | https://claude.ai/artifact/7HwprMXHbJWfYWouMhLfDR |
| a4 | https://claude.ai/artifact/RsJ9cD9eNMWorL5EgVgrat |
| a5 | https://claude.ai/artifact/SAgFc2UtJ4GuyyRX3ZZmu2 |
| a7 | https://claude.ai/artifact/6mvtEiZeGL1qtiR2ySxif5 |

The published copy is the page body only (the Artifact tool adds its own document wrapper);
the source is `docs/learning/study/<unit>/page.html`.

## Notes

- `inventory-a1-explainer.md` records what the older A1 explainer does and which parts the
  new unit keeps, moves to P1, or leaves to the old page.
- Rebuild after editing a `content.json`: `.venv/bin/python scripts/build_study.py`. A test
  fails if a page or brief is stale, if a number is not in a cited source, or if a cited
  section is missing.
