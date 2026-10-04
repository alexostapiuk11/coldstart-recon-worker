"""The noise-floor diagnostic says so whenever it is not running the
pre-registered traffic model (plan 2a inventory, row 7).

Its `--baseline-fraction` / `--additional-replicas` overrides exist to measure a
candidate regime BEFORE the pre-registration is amended to adopt it. Output
from such a run looks exactly like output from the pre-registered model, so
the printed warning is the only thing that keeps a candidate's noise floor
from being quoted as the real one. Until this file, that warning was checked
by hand, once, in a plan step.

Runs the real script in a subprocess rather than importing `main`: the
warning is printed from inside it, and the CLI path (argparse defaults falling
back to the pre-registered constants) is the thing being pinned. One seed and
one repetition keep each run to a few seconds.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
NOISE_FLOOR = REPO / "scripts" / "a2_gap_noise_floor.py"
WARNING = "NOT the pre-registered traffic model"


def _noise_floor(out: Path, *flags: str) -> str:
    """Everything the script printed, stdout and stderr together, so the test
    does not depend on which stream the warning goes to."""
    env = {**os.environ, "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1"}
    done = subprocess.run(
        [sys.executable, str(NOISE_FLOOR), "--seeds", "1", "--reps", "1", *flags,
         "--out", str(out)],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO,
        env=env,
        timeout=120,
    )
    return done.stdout + done.stderr


@pytest.mark.parametrize(
    "override", [("--baseline-fraction", "0.40"), ("--additional-replicas", "0.5")]
)
def test_an_override_run_says_it_is_not_the_preregistered_model(tmp_path, override):
    printed = _noise_floor(tmp_path / "x.json", *override)
    assert printed.count(WARNING) == 1, (
        f"{override} ran a candidate traffic model but printed {WARNING!r} "
        f"{printed.count(WARNING)} times, not once; its noise floor would read "
        "as the pre-registered one"
    )


def test_a_default_run_does_not_claim_to_be_a_candidate(tmp_path):
    """The other half: a warning printed on every run is a warning nobody
    reads, and it would also pass the override test above."""
    printed = _noise_floor(tmp_path / "x.json")
    assert WARNING not in printed, (
        "a run with no overrides says it is not the pre-registered traffic "
        "model; either the default path stopped using the pre-registered "
        "values or the warning lost its condition"
    )
