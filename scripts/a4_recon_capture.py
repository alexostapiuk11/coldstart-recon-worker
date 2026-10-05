"""Submit artifact 4's reconnaissance jobs; save every outcome verbatim.

    .venv/bin/python scripts/a4_recon_capture.py --list
    set -a; . ./.env; set +a
    .venv/bin/python scripts/a4_recon_capture.py --preflight-only --template-id <id>
    .venv/bin/python scripts/a4_recon_capture.py --template-id <id> [--only help,stage]
    .venv/bin/python scripts/a4_recon_capture.py --template-id <id> --model-class fallback --only swaps-compile

Reads RUNPOD_API_KEY and RUNPOD_A4_ENDPOINT_ID. The endpoint's template must
run `python3 -u /opt/a4_recon_handler.py`. `--list` prints every job and
spends nothing; `--preflight-only` makes one GET.

Each job's outcome is written to fixtures/a4/recon/<label>.json as it lands,
and an existing file is never overwritten: a capture is evidence, and a re-run
goes under a new label or after the old file is moved by hand.
"""

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.runpod.preflight import assert_endpoint_matches, fetch_endpoint
from harness.runpod.submitter import HttpTransport, RunPodSubmitter
from placement_measure.pins import pins
from placement_measure.prereg import FALLBACK, PRIMARY
from placement_measure.recon_plan import recon_jobs

OUT = Path("fixtures/a4/recon")


def capture(jobs, submit_payload, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    targets = [out_dir / f"{job['label']}.json" for job in jobs]
    existing = [str(p) for p in targets if p.exists()]
    if existing:
        raise SystemExit(f"refusing to overwrite captures {existing}; a capture is evidence")
    written = []
    for job, path in zip(jobs, targets, strict=True):
        outcome = submit_payload(job)
        path.write_text(json.dumps({"label": job["label"], "probe": job["probe"],
                                    "submitted": job, "outcome": asdict(outcome)}, indent=1))
        print(f"[capture] {job['label']}: {'ok' if outcome.error is None else outcome.error}",
              flush=True)
        written.append(path)
    return written


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--preflight-only", action="store_true")
    ap.add_argument("--template-id")
    ap.add_argument("--only", default="")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--model-class", choices=("primary", "fallback"), default="primary",
                    help="the class the go/no-go chose; it changes the swap, early-start and "
                         "sleep jobs only")
    args = ap.parse_args(argv)
    jobs = recon_jobs(PRIMARY if args.model_class == "primary" else FALLBACK)
    if args.only:
        wanted = args.only.split(",")
        unknown = sorted(set(wanted) - {j["label"] for j in jobs})
        if unknown:
            raise SystemExit(f"unknown labels {unknown}")
        jobs = [j for j in jobs if j["label"] in wanted]
    if args.list:
        for job in jobs:
            print(job["label"], job["probe"], json.dumps(job)[:200])
        return
    key, endpoint = os.environ["RUNPOD_API_KEY"], os.environ["RUNPOD_A4_ENDPOINT_ID"]
    assert_endpoint_matches(fetch_endpoint(endpoint, key), pins(args.template_id))
    print(f"[preflight] endpoint {endpoint} matches artifact 4's pin set", flush=True)
    if args.preflight_only:
        return
    capture(jobs, RunPodSubmitter(HttpTransport(endpoint, key)).submit_payload, Path(args.out))


if __name__ == "__main__":
    main()
