"""Guards shared by artifact 5's scripts that spend money."""

import os

PIN_KEYS = ("flashboot", "gpuTypeIds", "networkVolumeId", "templateId", "workersMin")


def require_credentials(environ=None) -> tuple[str, str]:
    environ = os.environ if environ is None else environ
    missing = [n for n in ("RUNPOD_API_KEY", "RUNPOD_ENDPOINT_ID") if not environ.get(n)]
    if missing:
        raise SystemExit(
            f"missing {', '.join(missing)}; load them with `set -a; . ./.env; set +a`"
        )
    return environ["RUNPOD_API_KEY"], environ["RUNPOD_ENDPOINT_ID"]


def guard_against_silent_restart(existing: int, path, *, resume: bool, force: bool) -> None:
    """Forgetting --resume would re-submit and re-pay for every stored run and
    append duplicate run indices. Require --resume, or --force-restart to say
    that is intended -- artifact 1's runner learned this the expensive way."""
    if resume or not existing or force:
        return
    raise SystemExit(
        f"refusing to start: {existing} record(s) already exist in {path} and --resume was "
        "not passed; pass --resume to continue, or --force-restart to re-run from index 0"
    )


STOP_EXIT_CODE = 3
RESUME_WAIT_S = 30


class ConsecutiveFailureGuard:
    """Counts consecutive non-ok outcomes; an ok outcome resets the count.
    `observe` returns True when the count reaches the threshold, meaning stop.

    The larger gate lost 52 instances in a row to one host whose driver could
    not run the image (docs/experiment-a5.md, Amendment 3): every job landed on
    the same bad worker and failed in about 21 s, and nothing stopped the run.
    Isolated failures are data and must not stop a run; a streak means the
    platform, not the experiment, is failing."""

    def __init__(self, threshold: int):
        if isinstance(threshold, bool) or not isinstance(threshold, int) or threshold < 1:
            raise ValueError(f"the failure threshold must be a positive int, got {threshold!r}")
        self.threshold = threshold
        self.streak = 0

    def observe(self, outcome: str) -> bool:
        if outcome == "ok":
            self.streak = 0
            return False
        self.streak += 1
        return self.streak >= self.threshold


def record_host(record) -> dict:
    """A failed record's `host` is empty: the worker's output, host included,
    is kept in `diagnostics` instead (multilora.records.build_record)."""
    return dict(record.host or (record.diagnostics or {}).get("host") or {})


def failure_streak_message(streak: list) -> str:
    first, last = streak[0], streak[-1]
    host = record_host(last)
    classes = ", ".join(sorted({r.failure_class or "unknown" for r in streak}))
    return (
        f"[stop] {len(streak)} consecutive failed instances, run_index "
        f"{first.run_index}..{last.run_index}, failure_class {classes}; the last ran on "
        f"host_id={host.get('host_id', '?')} driver_version={host.get('driver_version', '?')}. "
        "Every record so far, the failed ones included, is preserved in the store. Wait at "
        f"least {RESUME_WAIT_S} s so an idle bad worker exits, then run again with --resume "
        "to continue from the next run index."
    )


def stop_after_consecutive_failures(threshold: int):
    """An `on_run` callback for `multilora.campaign.run`. `harness.campaign.
    run_campaign` appends each record to the store before it calls `on_run`, so
    the stop leaves the failing records stored; it exits with STOP_EXIT_CODE."""
    guard = ConsecutiveFailureGuard(threshold)
    streak: list = []

    def on_run(record) -> None:
        if record.outcome == "ok":
            streak.clear()
        else:
            streak.append(record)
        if guard.observe(record.outcome):
            print(failure_streak_message(streak), flush=True)
            raise SystemExit(STOP_EXIT_CODE)

    return on_run


def pins_from_endpoint(endpoint: dict) -> dict:
    """The five fields artifact 1 pinned, read off a live endpoint. Refuses an
    endpoint whose configuration would measure the platform instead of the
    engine: FlashBoot on, or a warm worker kept around."""
    missing = [k for k in PIN_KEYS if k not in endpoint]
    if missing:
        raise ValueError(f"endpoint lacks {missing}")
    pins = {k: endpoint[k] for k in PIN_KEYS}
    if pins["flashboot"] is not False:
        raise ValueError("flashboot must be off")
    if pins["workersMin"] != 0:
        raise ValueError("workersMin must be 0")
    return pins


def submitter_for(*, stub: bool):
    """The live RunPod submitter after a passing preflight, or the stub for a
    GPU-free rehearsal of exactly the same path."""
    if stub:
        from harness.submit import PayloadStubSubmitter
        from multilora.stub import StubInstanceEndpoint

        return PayloadStubSubmitter(StubInstanceEndpoint(seed=0).run)
    from harness.runpod.preflight import assert_endpoint_matches, fetch_endpoint
    from harness.runpod.submitter import HttpTransport, RunPodSubmitter
    from multilora.pins import PINNED

    key, endpoint_id = require_credentials()
    assert_endpoint_matches(fetch_endpoint(endpoint_id, key), PINNED)
    print(f"[preflight] endpoint {endpoint_id} matches multilora/pins.py", flush=True)
    return RunPodSubmitter(HttpTransport(endpoint_id, key))
