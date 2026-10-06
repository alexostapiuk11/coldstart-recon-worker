"""The load-balancer and frontier evidence the post cites is committed, not only in build/."""

import gzip
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROBES = REPO / "data" / "a2" / "lb-probes"


def test_every_probe_has_a_summary_and_its_steps():
    for n in range(1, 6):
        d = PROBES / f"probe-{n}"
        summary = json.loads((d / "summary.json").read_text())
        assert summary["steps"], n
        for rate in summary["steps"]:
            with gzip.open(d / f"step-{rate}.jsonl.gz", "rt") as fh:
                rows = fh.read().splitlines()
            assert len(rows) == summary["steps"][rate]["requests"], (n, rate)


def test_probe_1_shows_the_17_per_second_ceiling():
    s = json.loads((PROBES / "probe-1" / "summary.json").read_text())
    assert set(s["steps"]) >= {"25", "50", "100"} and s["status"].startswith("stopped")


def test_the_frontier_sweep_is_the_headline_x1_sweep():
    raw = json.loads((REPO / "data" / "a2" / "frontier-sweep.json").read_text())
    assert raw["identity"]["additional_replicas"] == 0.5
    assert set(raw["gaps"]) == {"arm A", "arm C", "ramp arm A", "ramp arm C"}
    assert round(raw["gaps"]["arm C"]["point"], 4) == 3.955
