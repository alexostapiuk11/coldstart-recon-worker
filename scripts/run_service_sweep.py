"""Run the single-engine service-curve sweep on a RunPod endpoint.

    set -a; . ./.env; set +a
    .venv/bin/python scripts/run_service_sweep.py --preflight-only --template-id <id>
    .venv/bin/python scripts/run_service_sweep.py --template-id <id> \\
        --levels 1,2,4,8,16,32,64 --seed 20261004 --serve-args "--max-num-seqs 256" \\
        --store data/a2/service-sweep.jsonl --out data/a2/service-sweep-curve.json
    .venv/bin/python scripts/run_service_sweep.py --reduce-only --levels 1,2,4,8,16,32,64 \\
        --min-repeats 2 --store data/a2/service-sweep.jsonl --out data/a2/service-sweep-curve.json

Reads RUNPOD_API_KEY and RUNPOD_SWEEP_ENDPOINT_ID from the environment. The
endpoint's template must run `python3 -u /opt/sweep_handler.py`.

Refuses to spend unless the endpoint matches the sweep pin set below. Every
(level, repeat) is one job, stored as it lands; `--resume` continues an
interrupted campaign with the same --levels/--repeats/--seed. The curve is
written as plain tuples plus per-level intervals; artifact 2 turns it into a
`ServiceCurve` with scripts/a2_service_curve.py.

`--preflight-only` makes one GET (the endpoint's configuration) and nothing
else: no job is submitted and no store is opened.

`--diagnostics` is for the first paid run only. Each job then also returns
the in-container checks (the bench tool's help text, nvidia-smi's raw output,
whether pandas imports, whether the prompt reached the engine log) and the
tool's raw saved JSON, which is tens of kilobytes a job. It is off by
default so an ordinary sweep stores none of it.

`--store` and `--out` have no defaults. Artifacts 2 and 4 both run this
script, and a shared default path would let one artifact's campaign resume
into the other's store, which the resume guard would accept whenever the
level lists happened to agree.

This script prints no cost estimate. RunPod's per-second price on the day is
UNVERIFIED (plan item 13) and a hard-coded rate would be a number that looks
measured and is not; the estimate belongs to the owner's paid-run checklist
(Task 15), where the price is read off the console.
"""

import argparse
import json
import os
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.campaign import run_campaign
from harness.runpod.preflight import assert_endpoint_matches, fetch_endpoint
from harness.runpod.submitter import HttpTransport, RunPodSubmitter
from harness.service_sweep import (
    DEFAULT_MIN_PROMPTS,
    DEFAULT_REPEATS,
    DEFAULT_WAVES,
    SweepRun,
    build_sweep_record,
    job_payload,
    reduce_curve,
    sweep_schedule,
)
from harness.store import JsonlStore

# The endpoint's executionTimeout, in seconds. The worker budgets each job
# against it (worker/sweep_handler.py), so it is pinned below as well: a
# larger platform limit would be harmless, a smaller one would kill jobs the
# worker believes it has time for, and they would return nothing.
EXECUTION_TIMEOUT_S = 1800
OUTPUT_LEN = 16  # artifact 1's max_tokens (worker/probe.py MAX_TOKENS)

# The sweep's boundary. Same GPU class and network volume as artifact 1
# (coldstart/pins.py), because artifact 2 inherits artifact 1's engine; the
# template is the sweep's own (dockerStartCmd overridden) and is passed in,
# since it is provisioned when the paid run is prepared. FlashBoot and
# workersMin are deliberately NOT pinned: they change startup, and the sweep
# measures nothing about startup. It lives here and not in `harness/` because
# a pin set is one experiment's boundary; the harness checks pins, it does not
# own any.
SWEEP_PINNED_BASE = {
    "gpuTypeIds": ["NVIDIA GeForce RTX 4090"],
    "networkVolumeId": "9c7ut2slrd",
    "executionTimeoutMs": EXECUTION_TIMEOUT_S * 1000,
}


def sweep_pins(template_id: str) -> dict:
    """The pin set for one sweep, with the template the caller provisioned.

    The template id is required, not defaulted: left out, the pin set would
    simply not mention the image or its start command, and the preflight would
    pass an endpoint running artifact 1's handler (or anything else), which
    answers every job with the wrong output and spends the money doing it.
    """
    if not template_id:
        raise ValueError(
            "a template id is required; without it the preflight would accept an "
            "endpoint running any image and any start command"
        )
    return {**SWEEP_PINNED_BASE, "templateId": template_id}


def run_sweep(
    *,
    submit_payload,
    store_path,
    out_path,
    levels,
    seed: int,
    source: str,
    repeats: int = DEFAULT_REPEATS,
    serve_args=(),
    waves: int = DEFAULT_WAVES,
    min_prompts: int = DEFAULT_MIN_PROMPTS,
    output_len: int = OUTPUT_LEN,
    min_repeats: int = DEFAULT_REPEATS,
    resume: bool = False,
    diagnostics: bool = False,
    on_run=None,
) -> dict:
    """Schedule -> one job per (level, repeat) -> JSONL -> curve JSON.

    `submit_payload` is `RunPodSubmitter.submit_payload` for a paid run and
    `PayloadStubSubmitter.submit_payload` in tests. `source` ("runpod" or
    "stub") is written into the curve so a stub curve can never be mistaken
    for a measured one downstream.
    """
    schedule = sweep_schedule(levels, repeats=repeats, seed=seed)
    store = JsonlStore(store_path, SweepRun)

    def submit(scheduled, run_id):
        return submit_payload(
            job_payload(
                scheduled,
                run_id,
                serve_args=serve_args,
                output_len=output_len,
                job_budget_s=EXECUTION_TIMEOUT_S,
                seed=seed,
                waves=waves,
                min_prompts=min_prompts,
                diagnostics=diagnostics,
            )
        )

    run_campaign(
        schedule,
        submit,
        build_sweep_record,
        store,
        index_of=lambda r: r.run_index,
        condition_of=lambda r: r.condition,
        on_run=on_run,
        resume=resume,
    )
    meta = {
        "source": source,
        "levels_requested": list(levels),
        "repeats": repeats,
        "seed": seed,
        "serve_args": list(serve_args),
        "output_len": output_len,
        "waves": waves,
        "min_prompts": min_prompts,
    }
    return reduce_store(store_path, out_path, min_repeats=min_repeats, meta=meta)


def reduce_store(store_path, out_path, *, min_repeats: int, meta: dict) -> dict:
    records = JsonlStore(store_path, SweepRun).read_all()
    reduction = reduce_curve(
        records, min_repeats=min_repeats, expected_levels=meta.get("levels_requested")
    )
    doc = {**reduction.to_dict(), **meta, "min_repeats": min_repeats, "store": str(store_path)}
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    return doc


def _levels(text: str) -> list[int]:
    return [int(part) for part in text.split(",") if part.strip()]


def _require(name: str) -> str:
    # The value is never echoed: only the name goes in the message.
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is not set; refusing to start (see this script's docstring)")
    return value


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--template-id")
    ap.add_argument("--levels", type=_levels)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    ap.add_argument("--serve-args", default="", help="extra `vllm serve` flags, one string")
    ap.add_argument("--waves", type=int, default=DEFAULT_WAVES)
    ap.add_argument("--min-prompts", type=int, default=DEFAULT_MIN_PROMPTS)
    ap.add_argument("--min-repeats", type=int, default=DEFAULT_REPEATS)
    ap.add_argument("--store")
    ap.add_argument("--out")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--diagnostics", action="store_true",
                    help="first paid run only: in-container checks and the raw bench JSON")
    ap.add_argument("--preflight-only", action="store_true")
    ap.add_argument("--reduce-only", action="store_true")
    args = ap.parse_args(argv)

    if args.reduce_only:
        if not (args.store and args.out):
            ap.error("--reduce-only needs --store and --out")
        meta = {"source": "runpod"}
        if args.levels:
            meta["levels_requested"] = args.levels
        reduce_store(args.store, args.out, min_repeats=args.min_repeats, meta=meta)
        print(f"[reduce] wrote {args.out}", flush=True)
        return

    key, endpoint_id = _require("RUNPOD_API_KEY"), _require("RUNPOD_SWEEP_ENDPOINT_ID")
    # Built before the GET, so a missing template id is refused without a request.
    pins = sweep_pins(args.template_id)
    assert_endpoint_matches(fetch_endpoint(endpoint_id, key), pins)
    print(f"[preflight] endpoint {endpoint_id} matches the sweep pin set", flush=True)
    if args.preflight_only:
        return
    missing = [f for f in ("levels", "seed", "store", "out") if getattr(args, f) is None]
    if missing:
        ap.error(f"a paid run needs --{', --'.join(missing)}")

    def progress(record):
        detail = record.status.get("failure_class") or ""
        print(
            f"[run {record.run_index:>3}] c={record.level:<4} repeat={record.repeat} "
            f"{record.outcome:<6} {detail}",
            flush=True,
        )

    doc = run_sweep(
        submit_payload=RunPodSubmitter(HttpTransport(endpoint_id, key)).submit_payload,
        store_path=args.store,
        out_path=args.out,
        levels=args.levels,
        seed=args.seed,
        source="runpod",
        repeats=args.repeats,
        serve_args=shlex.split(args.serve_args),
        waves=args.waves,
        min_prompts=args.min_prompts,
        min_repeats=args.min_repeats,
        resume=args.resume,
        diagnostics=args.diagnostics,
        on_run=progress,
    )
    print(f"[done] {len(doc['points'])} levels; curve={args.out}", flush=True)


if __name__ == "__main__":
    main()
