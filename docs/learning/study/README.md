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
| a1 | Where a vLLM cold start goes | 45 | `a1/page.html`, `a1/brief.md` |

P2 (how these experiments earn trust) and the units for artifacts 2, 4, 5, 6 and 7 are
built after the owner approves the pilot's format.

## Published pages

Private Artifacts.

| unit | page |
|---|---|
| p1 | https://claude.ai/artifact/ERS8Z3tRWUkSD4131zgwzY |
| a1 | https://claude.ai/artifact/2WmMh5z8C1bcehAmMurWQe |

The published copy is the page body only (the Artifact tool adds its own document wrapper);
the source is `docs/learning/study/<unit>/page.html`.

## Notes

- `inventory-a1-explainer.md` records what the older A1 explainer does and which parts the
  new unit keeps, moves to P1, or leaves to the old page.
- Rebuild after editing a `content.json`: `.venv/bin/python scripts/build_study.py`. A test
  fails if a page or brief is stale, if a number is not in a cited source, or if a cited
  section is missing.
