"""Artifact 2's open-loop validation gate against RunPod (spec §10).

`--repeat K` SPENDS MONEY: VALIDATION_REPLICAS pinned RTX 4090 workers for
about ten minutes. The owner runs it (docs/runbook-a2-validation.md), only
after the LB probe passed the amendment's acceptance rule. Reads
RUNPOD_API_KEY and RUNPOD_A2_LB_ENDPOINT_ID; never prints the key or writes it
into a record.

One repeat: preflight (GPU, volume, template; workersMin 0, workersMax == N),
check the slot and build the schedule (both before any pin), pin, warm up until
all N workers answer cleanly (their ids are the run's host_ids), replay the ONE
pre-registered schedule open-loop, release on any exit, and write every request
to data/a2/validation/repeat-K.json.gz. `--judge` builds RealRuns from the
pre-registered latency source and calls autoscale.validation.validate.

Void rules (amendment 2026-10-04): any non-200, a response from a worker
outside the pinned set, a 200 without the server-latency header, or a short
outcome list. A void repeat is kept, moved aside, and may be run once more;
a valid repeat is never overwritten, because re-running until the band fits
is the failure the fixed repeat count exists to prevent.

What a record means when something fails mid-run:
- The record is written as soon as the replay has returned, in a `finally`
  that runs after the pin's release. A release that fails afterwards
  (ReleaseFailed) leaves the data valid and the record says `release:
  "FAILED"`: the run was paid for and its evidence is sound, and the failure is
  a billing problem the exception already shouts about. Dropping the record
  because a later step failed was rejected: it throws away ~$0.30 of evidence.
- A failure BEFORE the replay completes (warm-up gave up, the replay raised or
  was interrupted) writes nothing. Such a run has no complete replay, so a
  record of it, void or not, would be a partial run that looks like data. The
  slot stays as it was, so the attempt costs the owner no "rerun" allowance.
- Any other error that escapes the pin AFTER the replay (for instance workersMax
  changed during the run) is recorded in `post_run_error` and printed, but does
  not void the record: the void list is the signed amendment's, and a new void
  category would burn the one allowed rerun. The owner reads the error and
  decides what the evidence is worth.
"""

import argparse
import dataclasses
import gzip
import json
import math
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from a2_lb_common import WORKER, sender, server_latency_s, warm_up

from autoscale.measured_curve import DEFAULT_PATH, load_measured_curve
from autoscale.validation import MAX_SEND_JITTER_SECONDS, REPEATS, RealRun, validate
from autoscale.validation_schedule import (
    LATENCY_SOURCE,
    VALIDATION_DRAIN_SECONDS,
    VALIDATION_KIND,
    VALIDATION_REPLICAS,
    VALIDATION_SEED,
    VALIDATION_UNTIL,
    WARMUP_MAX_SECONDS,
    WARMUP_MIN_SECONDS,
    WARMUP_RPS,
    build_schedule,
)
from harness.open_loop import max_jitter, replay
from harness.runpod.pinning import ReleaseFailed, WorkerPin, unwind_on_hangup_and_term
from harness.runpod.preflight import assert_endpoint_matches, fetch_endpoint

OUT = Path("data/a2/validation")
SCHEMA_VERSION = 1
# The peak is ~401 req/s over 2 workers, and client latency adds the WAN and the
# load balancer to the engine's ~0.6 s. 4096 threads hold about 10 s of latency
# (4096 / 401) before the driver's own pool, not the endpoint, causes send
# jitter. The replay default of 1024 holds only ~2.5 s, and a pool that is too
# small does not fail: the requests queue and leave late, which RealRun refuses
# above 0.5 s of jitter, so the paid run would be spent on a refusal.
REPLAY_MAX_IN_FLIGHT = 4096


def lb_pins(template_id: str) -> dict:
    return {"gpuTypeIds": ["NVIDIA GeForce RTX 4090"], "networkVolumeId": "9c7ut2slrd",
            "templateId": template_id}


def _server_seconds(outcome) -> float | None:
    """The server-latency header as seconds, or None if absent OR unusable.

    `server_latency_s` raises on a header that is not a number, and "nan" parses
    to NaN. Either would crash the record after the replay was paid for, or
    write a NaN that RealRun refuses at judge time. An unusable header is the
    same fault as a missing one, so both become the void reason.
    """
    try:
        s = server_latency_s(outcome)
    except ValueError:
        return None
    return s if s is not None and math.isfinite(s) and s >= 0 else None


def record_from(outcomes, *, repeat, schedule, host_ids, endpoint_id, template_id, started_at,
                replicas, until, seed=VALIDATION_SEED, drain=VALIDATION_DRAIN_SECONDS,
                warmup=None) -> dict:
    workers = [o.headers.get(WORKER) for o in outcomes]
    server = [_server_seconds(o) for o in outcomes]
    void = []
    if len(outcomes) != len(schedule):
        void.append(f"{len(outcomes)} outcomes for {len(schedule)} scheduled requests")
    failed = [o for o in outcomes if o.status != 200]
    if failed:
        errors = sum(1 for o in failed if o.error)
        void.append(f"{len(failed)} requests without a 200 ({errors} of them transport errors)")
    novel = sorted({w for w in workers if w} - set(host_ids))
    if novel:
        void.append(f"responses from workers outside the pinned set: {novel}")
    # Disclosure only, not a void rule: the amendment's void list is fixed, and the
    # latency-header rule below already voids the practical case (the middleware emits
    # both headers together).
    no_worker = sum(1 for o, w in zip(outcomes, workers, strict=True) if o.status == 200 and not w)
    no_latency = sum(1 for o, s in zip(outcomes, server, strict=True)
                     if o.status == 200 and s is None)
    if no_latency:
        void.append(f"{no_latency} 200 responses without a usable server-latency header "
                    "(absent or unparseable)")
    return {
        "schema_version": SCHEMA_VERSION, "repeat": repeat, "started_at": started_at,
        "endpoint_id": endpoint_id, "template_id": template_id, "replicas": replicas,
        "until": until, "drain": drain, "seed": seed, "latency_source": LATENCY_SOURCE,
        "host_ids": list(host_ids), "novel_workers": novel, "void": void,
        "headerless_worker_200": no_worker,
        "release": "ok", "post_run_error": None, "warmup": dict(warmup or {}),
        "max_jitter_s": max_jitter(outcomes),
        "schedule": list(schedule),
        "sent": [o.sent for o in outcomes],
        "server_latency_s": server,
        "client_latency_s": [o.latency for o in outcomes],
        "status": [o.status for o in outcomes],
        "worker": workers,
        "error": [o.error for o in outcomes],
    }


def read_record(path: Path) -> dict:
    with gzip.open(path, "rt") as fh:
        return json.load(fh)


def write_record(path: Path, record: dict) -> None:
    """Atomic: a half-written .gz in the slot would crash the next slot check."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with gzip.open(tmp, "wt") as fh:
        json.dump(record, fh)
    os.replace(tmp, path)


def _slot(out: Path, k: int) -> tuple[Path, Path, bool]:
    path, void_path = out / f"repeat-{k}.json.gz", out / f"repeat-{k}.void.json.gz"
    if not path.exists():
        return path, void_path, False
    if not read_record(path)["void"]:
        raise SystemExit(f"{path} holds a valid repeat {k}; a valid repeat is never re-run")
    if void_path.exists():
        raise SystemExit(
            f"repeat {k} is void twice ({void_path}, {path}); by the amendment the gate is "
            "not evaluable. Publish the causes; do not run it a third time")
    return path, void_path, True


def check_slot(out: Path, k: int) -> None:
    """Refuse a slot that may not be run, touching nothing."""
    _slot(out, k)


def prepare_slot(out: Path, k: int) -> Path:
    path, void_path, void_present = _slot(out, k)
    if void_present:
        path.rename(void_path)
    return path


def run_repeat(*, k, schedule, pin, send, warm_fn, replay_fn, endpoint_id, template_id,
               replicas, until, now, path, seed=VALIDATION_SEED,
               drain=VALIDATION_DRAIN_SECONDS) -> dict:
    """Pin, warm up, replay, release; write the record to `path` once the replay is complete.

    The record is written in a `finally` that runs after the pin's release, so a
    release failure cannot cost the evidence (see the module docstring). No
    replay, no record. Returns the record; an exception from the pin's exit is
    re-raised after the write.
    """
    warmup: dict = {}
    host_ids = started_at = outcomes = None
    escaped: BaseException | None = None
    try:
        with pin:
            host_ids = warm_fn(send, warmup)
            started_at = now()
            outcomes = replay_fn(schedule, send)
    except BaseException as e:
        escaped = e
        raise
    finally:
        if outcomes is not None:
            record = record_from(outcomes, repeat=k, schedule=schedule, host_ids=host_ids,
                                 endpoint_id=endpoint_id, template_id=template_id,
                                 started_at=started_at, replicas=replicas, until=until,
                                 seed=seed, drain=drain, warmup=warmup)
            if escaped is not None:
                record["post_run_error"] = f"{type(escaped).__name__}: {escaped}"[:300]
                if isinstance(escaped, ReleaseFailed):
                    record["release"] = "FAILED"
            write_record(path, record)
    return record


def judge(out: Path, curve) -> dict:
    records = []
    for k in range(1, REPEATS + 1):
        path = out / f"repeat-{k}.json.gz"
        if not path.exists():
            raise SystemExit(f"repeat {k} is missing ({path}); the gate needs all {REPEATS}")
        rec = read_record(path)
        if rec["void"]:
            raise SystemExit(f"repeat {k} is void ({rec['void']}); run it once more or stop")
        records.append(rec)
    key = "server_latency_s" if LATENCY_SOURCE == "server" else "client_latency_s"
    try:
        runs = [RealRun(schedule=r["schedule"], sent=r["sent"], latencies=r[key],
                        replicas=r["replicas"], until=r["until"], host_ids=tuple(r["host_ids"]))
                for r in records]
        result = validate(runs, curve)
    except ValueError as e:
        raise SystemExit(
            f"the gate refused the repeats: {e}. They are not judged, because judging a run "
            "the gate's own checks reject would give a verdict on a different trace") from e
    novelty, seen = {}, set(records[0]["host_ids"])
    for r in records[1:]:
        new = sorted(set(r["host_ids"]) - seen)
        if new:
            novelty[str(r["repeat"])] = new
        seen |= set(r["host_ids"])
    per_repeat = []
    for r in records:
        server = [x for x in r["server_latency_s"] if x is not None]
        client = [x for x in r["client_latency_s"] if x is not None]
        per_repeat.append({"repeat": r["repeat"], "host_ids": r["host_ids"],
                           "server_p50_s": median(server), "client_p50_s": median(client),
                           "max_jitter_s": r["max_jitter_s"], "release": r.get("release")})
    bins = []
    for b in result.bins:
        d = dataclasses.asdict(b)
        d["censoring_disagreement"] = math.isinf(b.miss_seconds)
        if d["censoring_disagreement"]:
            d["miss_seconds"] = None  # strict JSON has no Infinity
        bins.append(d)
    return {
        "outcome": result.outcome, "detail": result.detail, "compared": result.compared,
        "agreeing": result.agreeing, "misses": result.misses,
        "max_miss_seconds": None if math.isinf(result.max_miss_seconds)
        else result.max_miss_seconds,
        "max_miss_is_censoring": math.isinf(result.max_miss_seconds),
        "bins": bins, "host_novelty": novelty, "latency_source": LATENCY_SOURCE,
        "per_repeat": per_repeat,
    }


def _preflight(endpoint: str, key: str, template_id: str) -> WorkerPin:
    assert_endpoint_matches(fetch_endpoint(endpoint, key), lb_pins(template_id))
    pin = WorkerPin(endpoint, key, workers=VALIDATION_REPLICAS)
    pin.preflight()
    return pin


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight-only", action="store_true")
    mode.add_argument("--repeat", type=int, choices=range(1, REPEATS + 1))
    mode.add_argument("--judge", action="store_true")
    ap.add_argument("--template-id")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--curve", default=str(DEFAULT_PATH))
    args = ap.parse_args(argv)
    out = Path(args.out)
    curve = load_measured_curve(args.curve).curve
    if args.judge:
        verdict = judge(out, curve)
        out.mkdir(parents=True, exist_ok=True)
        tmp = out / "verdict.json.tmp"
        tmp.write_text(json.dumps(verdict, indent=1))
        os.replace(tmp, out / "verdict.json")
        print(f"[judge] {verdict['outcome']}: {verdict['detail']} (judged {verdict['compared']}, "
              f"outside {verdict['misses']}); host novelty {verdict['host_novelty'] or 'none'}")
        return
    if not args.template_id:
        ap.error("--preflight-only and --repeat need --template-id")
    if args.repeat is not None:
        check_slot(out, args.repeat)  # before the network, never after a pin
    key = os.environ["RUNPOD_API_KEY"]
    endpoint = os.environ["RUNPOD_A2_LB_ENDPOINT_ID"]
    pin = _preflight(endpoint, key, args.template_id)
    print(f"[preflight] {endpoint} matches the LB pin set and holds workersMax "
          f"{VALIDATION_REPLICAS}; nothing written")
    if args.preflight_only:
        return
    schedule = build_schedule(curve, replicas=VALIDATION_REPLICAS, kind=VALIDATION_KIND,
                              until=VALIDATION_UNTIL, drain=VALIDATION_DRAIN_SECONDS,
                              seed=VALIDATION_SEED)
    path = prepare_slot(out, args.repeat)
    send = sender(endpoint, key)
    unwind_on_hangup_and_term()
    try:
        record = run_repeat(
            k=args.repeat, schedule=schedule, pin=pin, send=send,
            warm_fn=lambda s, summary: warm_up(
                s, workers=VALIDATION_REPLICAS, rps=WARMUP_RPS, min_clean=WARMUP_MIN_SECONDS,
                max_seconds=WARMUP_MAX_SECONDS, summary_out=summary),
            replay_fn=lambda sch, s: replay(sch, s, max_in_flight=REPLAY_MAX_IN_FLIGHT),
            endpoint_id=endpoint, template_id=args.template_id, replicas=VALIDATION_REPLICAS,
            until=VALIDATION_UNTIL, now=lambda: datetime.now(UTC).isoformat(timespec="seconds"),
            path=path)
    except BaseException as e:
        wrote = path.exists()
        print(f"[repeat {args.repeat}] {'WARNING after the replay: ' if wrote else ''}"
              f"{type(e).__name__}: {str(e)[:300]}; "
              + (f"the record was still written to {path} with this error in post_run_error "
                 "(not voided; the owner decides what it means)" if wrote else
                 "no complete replay, so NO record was written and the slot is unchanged"),
              file=sys.stderr)
        raise
    jitter = record["max_jitter_s"]
    print(f"[repeat {args.repeat}] {len(schedule)} requests, host_ids {record['host_ids']}, "
          f"max jitter {jitter:.3f} s, {record['headerless_worker_200']} 200s without the "
          "worker header, "
          + ("VOID: " + "; ".join(record["void"]) if record["void"] else "valid"))
    if jitter > MAX_SEND_JITTER_SECONDS:
        print(f"[repeat {args.repeat}] WARNING: send jitter {jitter:.3f} s exceeds "
              f"{MAX_SEND_JITTER_SECONDS} s; --judge will refuse this repeat. Not a void rule "
              "in the amendment: the owner decides what to do", file=sys.stderr)


if __name__ == "__main__":
    main()
