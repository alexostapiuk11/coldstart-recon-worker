"""Artifact 2's open-loop validation gate against RunPod (spec §10).

`--repeat K` SPENDS MONEY: VALIDATION_REPLICAS pinned RTX 4090 workers for
about ten minutes. The owner runs it (docs/runbook-a2-validation.md), only
after the LB probe passed the amendment's acceptance rule. Reads
RUNPOD_API_KEY and RUNPOD_A2_LB_ENDPOINT_ID; never prints the key or writes it
into a record.

One repeat: preflight (GPU, volume, template; workersMin 0, workersMax == N),
check the slot (and that the out dir is writable and the open-files limit holds
the replay's sockets) and build the schedule, all before any pin; then pin, warm up until
all N workers answer cleanly (their ids are the run's host_ids), replay the ONE
pre-registered schedule open-loop, release on any exit, and write every request
to data/a2/validation-engine/repeat-K.json.gz. `--judge` builds EngineRuns from
the engine's own arrival stamps and latencies and calls
autoscale.validation.validate_engine_arrivals (amendment 2026-10-05, third).
The three one-replica repeats run before that amendment carry no arrival
stamps; they stay in data/a2/validation/ as its evidence and are not judged.

Void rules (amendments 2026-10-04 and 2026-10-05, third): a request that reached
the engine and did not end in 200; more than 1% of requests never reaching the
engine (a final non-200 without the worker header, which are otherwise counted
and left out of both sides); a response from a worker outside the pinned set;
a 200 without a usable server-latency or received-time header. Send jitter is
recorded, not judged. A void repeat is kept, moved aside, and may be run once more;
a valid repeat is never overwritten, because re-running until the band fits
is the failure the fixed repeat count exists to prevent.

What a record means when something fails mid-run:
- The record is written as soon as the replay has returned, in a `finally`
  that runs after the pin's release. A release that fails afterwards
  (ReleaseFailed) leaves the data valid and the record says `release:
  "FAILED"`: the run was paid for and its evidence is sound, and the failure is
  a billing problem the exception already shouts about. Dropping the record
  because a later step failed was rejected: it throws away ~$0.30 of evidence.
- If the record cannot be built or written after the replay, the raw outcomes go
  to a temp file (path on stderr) and `RecordLost` is raised, chained to the pin's
  own error so a ReleaseFailed stays visible.
- A failure BEFORE the replay completes (warm-up gave up, the replay raised or
  was interrupted) writes nothing. Such a run has no complete replay, so a
  record of it, void or not, would be a partial run that looks like data. The
  slot stays as it was (a void repeat is moved aside only just before the
  replay starts), so the attempt costs the owner no "rerun" allowance.
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
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from a2_lb_common import (
    POOL_THREADS,
    RETRY_MARK,
    SERVER_RECEIVED,
    WORKER,
    calibrate,
    ensure_fd_limit,
    ensure_thread_headroom,
    sender,
    server_latency_s,
    warm_up,
)

from autoscale.figures import validation_residuals
from autoscale.measured_curve import DEFAULT_PATH, load_measured_curve
from autoscale.validation import (
    MAX_SEND_JITTER_SECONDS,
    REPEATS,
    EngineRun,
    engine_trajectories,
    validate_engine_arrivals,
)
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

OUT = Path("data/a2/validation-calibrated")
# 2: records carry the engine's arrival stamps (amendment 2026-10-05, third).
# 3: and the repeat's host calibration (amendment 2026-10-05, fourth).
SCHEMA_VERSION = 3
# More than this share of requests never reaching the engine voids a repeat.
MAX_NEVER_REACHED_FRACTION = 0.01
# The peak is ~201 req/s on 1 worker, and client latency adds the WAN and the
# load balancer to the engine's ~0.6 s. The shared pool (3500 threads; see
# a2_lb_common.POOL_THREADS for why not 4096) holds about 17 s of latency at 201
# req/s before the driver's own pool, not the endpoint, causes send jitter. A
# pool that is too small does not fail: the requests queue and leave late. The
# gate predicts from the engine's own arrivals, so lateness is not judged, but a
# pool that holds the load keeps the engine seeing the schedule's traffic.
REPLAY_MAX_IN_FLIGHT = POOL_THREADS


class RecordLost(RuntimeError):
    """The replay completed but its record could not be built or written.

    `fallback` is the raw-outcomes file (or None if even that failed): the paid
    data is in it, not in the slot.
    """

    def __init__(self, message: str, fallback: Path | None):
        super().__init__(message)
        self.fallback = fallback


def lb_pins(template_id: str) -> dict:
    return {"gpuTypeIds": ["NVIDIA GeForce RTX 4090"], "networkVolumeId": "9c7ut2slrd",
            "templateId": template_id}


def _server_seconds(outcome) -> float | None:
    """The server-latency header as seconds, or None if absent OR unusable.

    `server_latency_s` raises on a header that is not a number, and "nan" parses
    to NaN. Either would crash the record after the replay was paid for, or
    write a NaN that EngineRun refuses at judge time. An unusable header is the
    same fault as a missing one, so both become the void reason.
    """
    try:
        s = server_latency_s(outcome)
    except ValueError:
        return None
    return s if s is not None and math.isfinite(s) and s >= 0 else None


def _received_seconds(outcome) -> float | None:
    """The engine's arrival stamp as a float, or None if absent or unusable."""
    raw = outcome.headers.get(SERVER_RECEIVED)
    try:
        t = float(raw) if raw is not None else None
    except ValueError:
        return None
    return t if t is not None and math.isfinite(t) else None


def record_from(outcomes, *, repeat, schedule, host_ids, endpoint_id, template_id, started_at,
                replicas, until, seed=VALIDATION_SEED, drain=VALIDATION_DRAIN_SECONDS,
                warmup=None, calibration=None) -> dict:
    if len(outcomes) != len(schedule):
        # Not a void reason: the amendment's list is fixed, and `harness.open_loop.replay`
        # returns one outcome per scheduled request. Raising here, inside run_repeat's
        # record-build guard, keeps the raw outcomes in the fallback dump.
        raise RuntimeError(
            f"the replay returned {len(outcomes)} outcomes for {len(schedule)} scheduled "
            "requests; harness.open_loop.replay guarantees this cannot happen, so the data "
            "cannot be trusted and no record is written from it")
    workers = [o.headers.get(WORKER) for o in outcomes]
    server = [_server_seconds(o) for o in outcomes]
    received = [_received_seconds(o) for o in outcomes]
    void = []
    # A final non-200 without the worker header never produced an engine
    # response: counted and left out of both sides (amendment 2026-10-05, third).
    never = [i for i, (o, w) in enumerate(zip(outcomes, workers, strict=True))
             if o.status != 200 and not w]
    reached_failed = [o for o, w in zip(outcomes, workers, strict=True) if o.status != 200 and w]
    if reached_failed:
        void.append(f"{len(reached_failed)} requests reached the engine without a 200")
    if len(never) > MAX_NEVER_REACHED_FRACTION * len(outcomes):
        errors = sum(1 for i in never if outcomes[i].error)
        void.append(f"{len(never)} requests without a 200 never reached the engine "
                    f"({len(never) / len(outcomes):.2%}, over {MAX_NEVER_REACHED_FRACTION:.0%}; "
                    f"{errors} of them transport errors)")
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
    no_received = sum(1 for o, r in zip(outcomes, received, strict=True)
                      if o.status == 200 and r is None)
    if no_received:
        void.append(f"{no_received} 200 responses without a usable received-time header "
                    "(absent or unparseable)")
    return {
        "schema_version": SCHEMA_VERSION, "repeat": repeat, "started_at": started_at,
        "endpoint_id": endpoint_id, "template_id": template_id, "replicas": replicas,
        "until": until, "drain": drain, "seed": seed, "latency_source": LATENCY_SOURCE,
        "host_ids": list(host_ids), "novel_workers": novel, "void": void,
        "headerless_worker_200": no_worker,
        "never_reached": never,
        # Which requests the driver retried after a load-balancer 502 (amendment
        # 2026-10-05). Disclosed, not a void reason. A retry that failed again without
        # reaching the engine is in `never_reached` (amendment 2026-10-05, third).
        "lb_502_retried": [i for i, o in enumerate(outcomes) if RETRY_MARK in o.headers],
        "release": "ok", "post_run_error": None, "warmup": dict(warmup or {}),
        "calibration": calibration,
        "max_jitter_s": max_jitter(outcomes),
        "schedule": list(schedule),
        "sent": [o.sent for o in outcomes],
        "server_latency_s": server,
        "server_received_s": received,
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
    try:
        with gzip.open(tmp, "wt") as fh:
            json.dump(record, fh)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)  # a failed write leaves the slot as it was
        raise


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
    """Refuse a slot that may not be run, or an out dir that cannot take the record.

    Creates `out` and writes then deletes a probe file, BEFORE any pin. Finding
    out after the replay that the record cannot be written would waste the
    whole paid run (the data would survive only in the fallback dump).
    """
    try:
        out.mkdir(parents=True, exist_ok=True)
        probe = out / f".write-probe-{os.getpid()}"
        probe.write_text("")
        probe.unlink()
    except OSError as e:
        raise SystemExit(
            f"cannot write to {out} ({type(e).__name__}: {e}); a repeat started now would "
            "pay for ten minutes of pinned GPUs and then have nowhere to put its record. "
            "Fix the path or its permissions and start again") from e
    _slot(out, k)


def _dump_fallback(k, outcomes, context) -> Path | None:
    """Raw outcomes and context to the system temp dir, for when the record cannot be written."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    try:
        fd, name = tempfile.mkstemp(prefix=f"a2-repeat-{k}-{stamp}-", suffix=".json",
                                    dir=tempfile.gettempdir())
        with os.fdopen(fd, "w") as fh:
            json.dump({"context": context,
                       "outcomes": [dataclasses.asdict(o) for o in outcomes]},
                      fh, default=str)
        return Path(name)
    except Exception:  # noqa: BLE001 -- the dump is the last resort; its failure is reported
        return None


def prepare_slot(out: Path, k: int) -> Path:
    path, void_path, void_present = _slot(out, k)
    if void_present:
        path.rename(void_path)
    return path


def _calibration_void_record(*, k, host_ids, endpoint_id, template_id, started_at, replicas,
                             until, seed, drain, warmup, calibration) -> dict:
    """A void repeat whose calibration failed: no replay was run (amendment 2026-10-05,
    fourth). Written, not skipped, because the signed rule makes it a void repeat
    with its one re-run; replaying anyway was rejected as paying for a trace that
    could only be void."""
    return {"schema_version": SCHEMA_VERSION, "repeat": k, "started_at": started_at,
            "endpoint_id": endpoint_id, "template_id": template_id, "replicas": replicas,
            "until": until, "drain": drain, "seed": seed, "latency_source": LATENCY_SOURCE,
            "host_ids": list(host_ids or []), "void": list(calibration["void"]),
            "release": "ok", "post_run_error": None, "warmup": dict(warmup or {}),
            "calibration": calibration}


def run_repeat(*, k, schedule, pin, send, warm_fn, replay_fn, endpoint_id, template_id,
               replicas, until, now, path, seed=VALIDATION_SEED,
               drain=VALIDATION_DRAIN_SECONDS, prepare=None, calibrate_fn=None) -> dict:
    """Pin, warm up, replay, release; write the record to `path` once the replay is complete.

    The record is written in a `finally` that runs after the pin's release, so a
    release failure cannot cost the evidence (see the module docstring). No
    replay, no record. Returns the record; an exception from the pin's exit is
    re-raised after the write.

    `prepare`, if given, runs once the pin is held and warm-up has succeeded,
    immediately before the replay: the slot is touched (a void repeat moved
    aside) only when the run is really starting, so a failed pin or warm-up
    leaves it exactly as it was.

    If building or writing the record fails after the replay, the raw outcomes
    go to a temp file and `RecordLost` is raised, chained to the pin's own
    error when there was one (a ReleaseFailed must stay visible: a worker may
    be billing). A signal-driven SystemExit or KeyboardInterrupt keeps
    propagating as itself, with the fallback path printed.
    """
    warmup: dict = {}
    host_ids = started_at = outcomes = calibration = None
    escaped: BaseException | None = None
    try:
        with pin:
            host_ids = warm_fn(send, warmup)
            if calibrate_fn is not None:
                calibration = calibrate_fn(send)
            if prepare is not None:
                prepare()
            started_at = now()
            if calibration is None or not calibration["void"]:
                outcomes = replay_fn(schedule, send)
    except BaseException as e:
        escaped = e
        raise
    finally:
        if outcomes is None and calibration is not None and calibration["void"] and started_at:
            record = _calibration_void_record(
                k=k, host_ids=host_ids, endpoint_id=endpoint_id, template_id=template_id,
                started_at=started_at, replicas=replicas, until=until, seed=seed, drain=drain,
                warmup=warmup, calibration=calibration)
            if escaped is not None:
                record["post_run_error"] = f"{type(escaped).__name__}: {escaped}"[:300]
                if isinstance(escaped, ReleaseFailed):
                    record["release"] = "FAILED"
            write_record(path, record)
        if outcomes is not None:
            try:
                record = record_from(outcomes, repeat=k, schedule=schedule, host_ids=host_ids,
                                     endpoint_id=endpoint_id, template_id=template_id,
                                     started_at=started_at, replicas=replicas, until=until,
                                     seed=seed, drain=drain, warmup=warmup,
                                     calibration=calibration)
                if escaped is not None:
                    record["post_run_error"] = f"{type(escaped).__name__}: {escaped}"[:300]
                    if isinstance(escaped, ReleaseFailed):
                        record["release"] = "FAILED"
                write_record(path, record)
            except Exception as lost:  # noqa: BLE001 -- whatever failed, the paid data must survive
                fallback = _dump_fallback(k, outcomes, {
                    "repeat": k, "endpoint_id": endpoint_id, "template_id": template_id,
                    "host_ids": host_ids, "started_at": started_at, "replicas": replicas,
                    "until": until, "seed": seed, "drain": drain, "schedule": list(schedule),
                    "pin_exit_error": None if escaped is None else
                    f"{type(escaped).__name__}: {escaped}"})
                where = (f"the raw outcomes are in {fallback}" if fallback else
                         "the fallback dump failed too, so the replay's data is lost")
                print(f"[repeat {k}] the replay completed but its record could not be written "
                      f"({type(lost).__name__}: {lost}); {where}", file=sys.stderr)
                if escaped is None or isinstance(escaped, Exception):
                    raise RecordLost(
                        f"the replay completed but its record could not be built or written "
                        f"({type(lost).__name__}: {lost}); {where}"
                        + (f". The pin's exit also failed: {escaped}" if escaped else ""),
                        fallback) from (escaped or lost)
    return record


def _valid_records(out: Path) -> list[dict]:
    """The three repeats' records, or a refusal naming the missing or void one.

    Shared by `judge` and `figure_inputs`, so the figure is drawn from exactly
    the records the verdict was judged on. A second copy of the refusals was
    rejected: a figure drawn from a repeat the gate would refuse is a picture
    of a run that was never judged.
    """
    records = []
    for k in range(1, REPEATS + 1):
        path = out / f"repeat-{k}.json.gz"
        if not path.exists():
            void_path = out / f"repeat-{k}.void.json.gz"
            aside = (f"; an earlier void attempt is kept at {void_path}"
                     if void_path.exists() else "")
            raise SystemExit(
                f"repeat {k} is missing ({path}){aside}; the gate needs all {REPEATS}")
        rec = read_record(path)
        if rec.get("schema_version", 1) < 2 or "server_received_s" not in rec:
            raise SystemExit(
                f"repeat {k} ({path}) predates the engine-arrival amendment (2026-10-05, "
                "third): it has no engine arrival stamps, so it cannot be judged by it")
        if rec["void"]:
            raise SystemExit(f"repeat {k} is void ({rec['void']}); run it once more or stop")
        if not (rec.get("calibration") or {}).get("ratios"):
            raise SystemExit(
                f"repeat {k} ({path}) has no host calibration (amendment 2026-10-05, fourth); "
                "judging it on the uncalibrated curve would repeat the first attempt")
        if rec["void"]:
            raise SystemExit(f"repeat {k} is void ({rec['void']}); run it once more or stop")
        records.append(rec)
    return records


def _engine_runs(records: list[dict]) -> list[EngineRun]:
    """EngineRuns from the records: the engine's arrival stamps and latencies,
    with requests that never reached the engine as None on both."""
    runs = []
    for r in records:
        received = [t if st == 200 else None
                    for t, st in zip(r["server_received_s"], r["status"], strict=True)]
        latencies = [lat if st == 200 else None
                     for lat, st in zip(r["server_latency_s"], r["status"], strict=True)]
        runs.append(EngineRun(sent=r["sent"], received=received, latencies=latencies,
                              replicas=r["replicas"], until=r["until"],
                              host_ids=tuple(r["host_ids"]),
                              host_ratios=tuple(r["calibration"]["ratios"])))
    return runs


def figure_inputs(out: Path, curve):
    """The figure-3 inputs for the three valid repeats, from the same records the gate judged.

    Returns (per-repeat (real, predicted) trajectories, validation, requests per run).
    """
    records = _valid_records(out)
    try:
        runs = _engine_runs(records)
        pairs = [engine_trajectories(r, curve) for r in runs]
        result = validate_engine_arrivals(runs, curve)
    except ValueError as e:
        raise SystemExit(
            f"the gate refused the repeats: {e}. No figure is drawn from runs the gate "
            "rejects, because it would show a trace that was never judged") from e
    return pairs, result, len(records[0]["schedule"])


def judge(out: Path, curve) -> dict:
    records = _valid_records(out)
    try:
        result = validate_engine_arrivals(_engine_runs(records), curve)
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
                           "max_jitter_s": r["max_jitter_s"], "release": r.get("release"),
                           "never_reached": len(r["never_reached"]),
                           "host_ratios": r["calibration"]["ratios"],
                           "lb_502_retried": len(r["lb_502_retried"]),
                           "post_run_error": r.get("post_run_error")})
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
        "gate": "engine_arrivals (amendment 2026-10-05, third)",
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
        for r in verdict["per_repeat"]:
            if r["post_run_error"]:
                print(f"[judge] WARNING: repeat {r['repeat']} recorded an error after its "
                      f"replay ({r['post_run_error']}); the verdict stands, the owner decides "
                      "what it means", file=sys.stderr)
        pairs, result, n = figure_inputs(out, curve)
        print(validation_residuals(pairs, result, out / "validation_residuals.png",
                                   replicas=VALIDATION_REPLICAS, requests_per_run=n,
                                   latency_source=LATENCY_SOURCE))
        return
    if not args.template_id:
        ap.error("--preflight-only and --repeat need --template-id")
    if args.repeat is not None:
        check_slot(out, args.repeat)  # before the network, never after a pin
        ensure_fd_limit()
        ensure_thread_headroom()
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
    path = out / f"repeat-{args.repeat}.json.gz"
    void_path = out / f"repeat-{args.repeat}.void.json.gz"
    had_void = path.exists()  # check_slot proved it is a void repeat, not a valid one
    moved = {"void": False}

    def prepare():
        moved["void"] = had_void
        prepare_slot(out, args.repeat)

    send = sender(endpoint, key)
    unwind_on_hangup_and_term()
    try:
        record = run_repeat(
            k=args.repeat, schedule=schedule, pin=pin, send=send,
            warm_fn=lambda s, summary: warm_up(
                s, workers=VALIDATION_REPLICAS, rps=WARMUP_RPS, min_clean=WARMUP_MIN_SECONDS,
                max_seconds=WARMUP_MAX_SECONDS, summary_out=summary),
            replay_fn=lambda sch, s: replay(sch, s, max_in_flight=REPLAY_MAX_IN_FLIGHT),
            calibrate_fn=lambda s: calibrate(s, curve),
            endpoint_id=endpoint, template_id=args.template_id, replicas=VALIDATION_REPLICAS,
            until=VALIDATION_UNTIL, now=lambda: datetime.now(UTC).isoformat(timespec="seconds"),
            path=path, prepare=prepare)
    except BaseException as e:
        # A void still sitting in the slot is not this run's record.
        wrote = (path.exists() and not isinstance(e, RecordLost)
                 and (not had_void or moved["void"]))
        if isinstance(e, RecordLost):
            tail = "see the line above for where the raw outcomes were saved"
        elif wrote:
            tail = (f"the record was still written to {path} with this error in post_run_error "
                    "(not voided; the owner decides what it means)")
        elif moved["void"]:
            tail = (f"no complete replay, so NO new record was written; the earlier void "
                    f"repeat was moved aside to {void_path} when the replay was about to start")
        else:
            tail = "no complete replay, so NO record was written and the slot is unchanged"
        print(f"[repeat {args.repeat}] {'WARNING after the replay: ' if wrote else ''}"
              f"{type(e).__name__}: {str(e)[:300]}; {tail}", file=sys.stderr)
        raise
    jitter = record["max_jitter_s"]
    print(f"[repeat {args.repeat}] {len(schedule)} requests, host_ids {record['host_ids']}, "
          f"max jitter {jitter:.3f} s, {len(record['never_reached'])} never reached the "
          f"engine, {len(record['lb_502_retried'])} load-balancer 502s retried, "
          f"{record['headerless_worker_200']} 200s without the worker header, "
          + ("VOID: " + "; ".join(record["void"]) if record["void"] else "valid"))
    if jitter > MAX_SEND_JITTER_SECONDS:
        print(f"[repeat {args.repeat}] note: send jitter {jitter:.3f} s is over the "
              f"{MAX_SEND_JITTER_SECONDS} s the first gate judged. Recorded, not judged: the "
              "gate predicts from the engine's own arrivals (amendment 2026-10-05, third)",
              file=sys.stderr)


if __name__ == "__main__":
    main()
