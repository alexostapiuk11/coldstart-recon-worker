"""Submit artifact 5's reconnaissance probes and save each outcome verbatim.

    set -a; . ./.env; set +a
    .venv/bin/python scripts/a5_recon_capture.py --concurrency 64 \
        --dataset-args "--dataset-name random --random-input-len 14 --random-output-len 16"

Publishes nothing. Writes fixtures/a5/<label>.json and never overwrites one:
a committed capture is evidence, and reconnaissance re-runs get new labels.
"""

import argparse
import json
import shlex
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.runpod.submitter import HttpTransport, RunPodSubmitter
from multilora.cli import require_credentials
from multilora.recon import recon_payloads

OUT = Path(__file__).resolve().parents[1] / "fixtures" / "a5"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--concurrency", type=int, required=True)
    ap.add_argument("--dataset-args", required=True)
    ap.add_argument("--adapter-seed", type=int, default=1)
    ap.add_argument("--real-candidates", help="fixtures/a5/real_adapter_candidates.json")
    ap.add_argument("--only", nargs="*", help="labels to run; default all")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    key, endpoint_id = require_credentials()
    real = []
    if args.real_candidates:
        real = [tuple(x) for x in json.loads(Path(args.real_candidates).read_text())["selected"]]
    payloads = recon_payloads(
        concurrency=args.concurrency, dataset_args=shlex.split(args.dataset_args),
        adapter_seed=args.adapter_seed, real_candidates=real,
    )
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    submitter = RunPodSubmitter(HttpTransport(endpoint_id, key))
    for payload in payloads:
        label = payload["label"]
        if args.only and label not in args.only:
            continue
        path = out / f"{label}.json"
        if path.exists():
            print(f"[skip] {path} exists; captures are never overwritten")
            continue
        outcome = submitter.submit_payload(payload)
        path.write_text(json.dumps(
            {"label": label, "payload": payload, "outcome": asdict(outcome)}, indent=1, sort_keys=True
        ))
        print(f"[{'ok' if outcome.error is None else 'FAILED'}] {path} {outcome.error or ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
