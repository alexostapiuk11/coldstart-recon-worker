"""Run one of artifact 4's measurement campaigns on a RunPod endpoint.

    set -a; . ./.env; set +a
    .venv/bin/python scripts/a4_measure.py --kind cell --design <design.json> \\
        --template-id <id> --store data/a4/cells.jsonl [--resume] [--preflight-only]

Reads RUNPOD_API_KEY and RUNPOD_A4_ENDPOINT_ID; the template must run
`python3 -u /opt/a4_measure_handler.py`. The design file holds a SwapDesign or
CellDesign's fields, written by the second pre-registration step. `--store`
has no default: each campaign gets its own store, because the resume guard
assumes a store holds one campaign.
"""

import argparse
import json
import os
import sys
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.campaign import run_campaign
from harness.runpod.preflight import assert_endpoint_matches, fetch_endpoint
from harness.runpod.submitter import HttpTransport, RunPodSubmitter
from harness.store import JsonlStore
from placement_measure.campaigns import CellDesign, SleepDesign, SwapDesign
from placement_measure.pins import pins
from placement_measure.records import A4Run, build_record

DESIGNS = {"swap": SwapDesign, "cell": CellDesign, "sleep": SleepDesign}


def load_design(kind: str, path) -> SwapDesign | CellDesign:
    raw = json.loads(Path(path).read_text())
    fields = {k: tuple(tuple(x) if isinstance(x, list) else x for x in v) if isinstance(v, list)
              else v for k, v in raw.items()}
    return DESIGNS[kind](**fields)


def run_measurement(design, kind: str, submit_payload, store_path, *, source: str,
                    resume: bool = False):
    return run_campaign(
        design.schedule(),
        lambda scheduled, run_id: submit_payload(design.payload(scheduled, run_id)),
        partial(build_record, kind=kind, source=source),
        JsonlStore(store_path, A4Run),
        index_of=lambda r: r.run_index, condition_of=lambda r: r.condition,
        on_run=lambda r: print(f"[run {r.run_index}] {r.condition}: {r.outcome}", flush=True),
        resume=resume,
    )


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--kind", choices=sorted(DESIGNS), required=True)
    ap.add_argument("--design", required=True)
    ap.add_argument("--template-id")
    ap.add_argument("--store")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--preflight-only", action="store_true")
    args = ap.parse_args(argv)
    design = load_design(args.kind, args.design)
    key, endpoint = os.environ["RUNPOD_API_KEY"], os.environ["RUNPOD_A4_ENDPOINT_ID"]
    assert_endpoint_matches(fetch_endpoint(endpoint, key), pins(args.template_id))
    print(f"[preflight] endpoint {endpoint} matches artifact 4's pin set", flush=True)
    if args.preflight_only:
        return
    if not args.store:
        raise SystemExit("--store is required for a paid run; each campaign gets its own")
    print(f"{len(design.schedule())} jobs", flush=True)
    run_measurement(design, args.kind, RunPodSubmitter(HttpTransport(endpoint, key)).submit_payload,
                    args.store, source="runpod", resume=args.resume)


if __name__ == "__main__":
    main()
