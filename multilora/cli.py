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
