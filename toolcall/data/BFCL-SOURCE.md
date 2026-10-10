# BFCL seed: source and license

Fourteen scenarios in this suite start from entries in the Berkeley Function
Calling Leaderboard (BFCL). Each one records its BFCL id and the commit below in
its `source` field.

- Repository: https://github.com/ShishirPatil/gorilla
- Commit: `6ea57973c7a6097fd7c5915698c54c17c5b1b6c8` (2026-03-23)
- License: Apache License 2.0. It is in `LICENSE` at the repository root and
  `license: apache-2.0` in the front matter of
  `berkeley-function-call-leaderboard/bfcl_eval/data/README.md`. The
  leaderboard's `pyproject.toml` declares it too.
- Fetched: 2026-10-09, with the author's permission. These six files were
  fetched from `raw.githubusercontent.com` at that commit; the repository was
  not cloned:
  - `LICENSE`
  - `berkeley-function-call-leaderboard/bfcl_eval/data/BFCL_v4_simple_python.json`
  - `berkeley-function-call-leaderboard/bfcl_eval/data/BFCL_v4_multiple.json`
  - `berkeley-function-call-leaderboard/bfcl_eval/data/BFCL_v4_irrelevance.json`
  - `berkeley-function-call-leaderboard/bfcl_eval/data/possible_answer/BFCL_v4_simple_python.json`
  - `berkeley-function-call-leaderboard/bfcl_eval/data/possible_answer/BFCL_v4_multiple.json`

## Entries imported

All of them come from `BFCL_v4_simple_python`:

| Domain | BFCL ids |
|---|---|
| weather | `simple_python_78`, `simple_python_185`, `simple_python_186`, `simple_python_187`, `simple_python_188` |
| units | `simple_python_365`, `simple_python_366`, `simple_python_378`, `simple_python_388`, `simple_python_390`, `simple_python_393` |
| travel | `simple_python_36`, `simple_python_85`, `simple_python_86` |

`scripts/a3_import_bfcl.py` converted each entry to a draft. An author then
finished it: terse and rich descriptions, a low set, confusables and, where
needed, a recovery block. The user message and the ground-truth values come
from BFCL; where finishing changed a tool's name or parameters to fit this
suite's library, the scenario's `notes` say so. Entries that do not survive
authoring or the pilot's band are listed in the post with the reason.
