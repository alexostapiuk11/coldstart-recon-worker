"""Populate the volume's compile cache so arm C is genuinely warm.

    set -a; . ./.env; set +a
    .venv/bin/python scripts/prime_compile_cache.py

Runs arm C twice and writes to data/priming.jsonl, never to the campaign store:
these are setup, not measurement. Including them would mix a cold compile into
arm C, and arm C's whole premise is that its compile cache was already warm.

Without this step the first arm C run of the campaign compiles cold and writes
the cache, so early arm C runs measure the cold path while later ones measure
the warm one -- an arm that is a mixture, whose apparent effect grows with run
index. The arm-state gate would discard that first run, so the statistics would
survive, but the pre-registered priming record would not exist and the campaign
would silently have paid for a discarded run to do this job.

Costs roughly $0.50. See docs/experiment.md, "Arm C requires a primed volume".
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coldstart.driver import run_campaign
from coldstart.preflight import assert_endpoint_matches, fetch_endpoint
from coldstart.runpod_submitter import HttpTransport, RunPodSubmitter
from coldstart.store import JsonlStore

# Repo-anchored for the same reason run_window.py's store is: a cwd-relative
# default would silently start a fresh file somewhere else.
STORE = Path(__file__).resolve().parents[1] / "data" / "priming.jsonl"

REQUIRED_ENV = ("RUNPOD_API_KEY", "RUNPOD_ENDPOINT_ID")


def _require_credentials() -> tuple[str, str]:
    missing = [name for name in REQUIRED_ENV if name not in os.environ]
    if missing:
        sys.exit(
            f"missing required environment variable(s): {', '.join(missing)} "
            "(see module docstring: `set -a; . ./.env; set +a`)"
        )
    return os.environ["RUNPOD_API_KEY"], os.environ["RUNPOD_ENDPOINT_ID"]


def _report(record) -> None:
    subphases = record.engine.get("s4_subphases") or {}
    print(
        f"[prime] run_index={record.run_index} outcome={record.status['outcome']} "
        f"compile_cache_observed={record.engine.get('compile_cache_observed')} "
        f"S4b={subphases.get('S4b')}",
        flush=True,
    )


def main() -> None:
    key, endpoint_id = _require_credentials()
    assert_endpoint_matches(fetch_endpoint(endpoint_id, key))
    print(f"[preflight] endpoint {endpoint_id} matches the pinned configuration", flush=True)

    store = JsonlStore(STORE)
    run_campaign(
        submitter=RunPodSubmitter(HttpTransport(endpoint_id, key)),
        store=store,
        arms=["C"],
        triples=2,
        seed=1,
        on_run=_report,
    )

    # The check that priming actually worked. The first run compiles cold and
    # writes the cache; the second must find it. If it does not, arm C is not
    # viable as configured -- most likely VLLM_CACHE_ROOT is not reaching the
    # engine, which would mean arm C is silently identical to arm B.
    records = store.read_all()
    last = records[-1]
    observed = last.engine.get("compile_cache_observed")
    s4b = (last.engine.get("s4_subphases") or {}).get("S4b")
    print(f"\n[prime] final run: compile_cache_observed={observed} S4b={s4b}", flush=True)
    if observed is not True:
        sys.exit(
            "priming did not take: the last run still reports "
            f"compile_cache_observed={observed!r}. Do NOT start the campaign -- "
            "arm C would measure a cold compile while claiming a warm one."
        )
    print("[prime] volume is warm; arm C is viable", flush=True)


if __name__ == "__main__":
    main()
