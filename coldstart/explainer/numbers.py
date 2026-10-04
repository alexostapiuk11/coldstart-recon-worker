"""Resolve the explainer's key list against committed data.

A tutorial about measurement discipline that disagrees with its own dataset
refutes itself. Nothing numeric reaches the page except through here.
"""

import json
from pathlib import Path

from coldstart.analysis.metrics import derive, rows_for_arm
from coldstart.schema import RunRecord
from harness.stats import bootstrap_median_ci
from harness.store import JsonlStore

KEYS: dict = json.loads(
    (Path(__file__).resolve().parents[2] / "explainer" / "numbers.json").read_text()
)

_FIRST_TOUCH_THRESHOLD_S = 200.0


def _rows(repo: Path) -> list[dict]:
    return [derive(r) for r in JsonlStore(str(Path(repo) / "data" / "campaign.jsonl"), RunRecord).read_all()]


def _dig(obj, path: str):
    for part in path.split("."):
        obj = obj[part]
    return obj


def arm_a_ci_n99(repo: Path) -> dict:
    """Arm A's median interval on the gated, repeat-host sample.

    Explicitly not the raw n=100: that still contains the single first-touch
    run at 2266s. Using the gated sample is also a free demonstration of the
    gate the page teaches.
    """
    vals = [
        r["t_total"]
        for r in rows_for_arm(_rows(repo), "A")
        if r["t_total"] < _FIRST_TOUCH_THRESHOLD_S
    ]
    out = bootstrap_median_ci(vals)
    out["n"] = len(vals)
    return out


def first_touch_seconds(repo: Path) -> float:
    return max(r["t_total"] for r in _rows(repo))


def gpu_hours_a_n99(repo: Path) -> float:
    vals = [
        r["t_total"]
        for r in rows_for_arm(_rows(repo), "A")
        if r["t_total"] < _FIRST_TOUCH_THRESHOLD_S
    ]
    return sum(vals) / 3600.0


def hosts_observed(repo: Path) -> int:
    return len({r["host_id"] for r in _rows(repo)})


_COMPUTED = {
    "arm_a_ci_n99": arm_a_ci_n99,
    "first_touch_seconds": first_touch_seconds,
    "gpu_hours_a_n99": gpu_hours_a_n99,
    "hosts_observed": hosts_observed,
}


def resolve(key: str, repo: Path):
    if key not in KEYS:
        raise KeyError(
            f"{key!r} is not on the explainer key list; add it to explainer/numbers.json"
        )
    spec = KEYS[key]
    if spec["source"] == "analysis":
        analysis = json.loads((Path(repo) / "data" / "analysis.json").read_text())
        return _dig(analysis, spec["path"])
    if spec["source"] == "computed":
        return _COMPUTED[spec["fn"]](repo)
    rows = _rows(repo)
    if spec["kind"] == "count":
        return len(rows)
    return {a: len(rows_for_arm(rows, a)) for a in ("A", "B", "C")}
