"""data/a2/post-analysis.json is what the script computes from committed data, byte for byte."""

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
A = REPO / "data" / "a2" / "post-analysis.json"


def _analysis() -> dict:
    return json.loads(A.read_text())


def test_a_fresh_run_reproduces_the_committed_analysis(tmp_path):
    out = tmp_path / "a.json"
    subprocess.run([sys.executable, str(REPO / "scripts" / "a2_post_analysis.py"), "--out",
                    str(out)], check=True, cwd=REPO, env={"PYTHONDONTWRITEBYTECODE": "1",
                                                          "PATH": "/usr/bin:/bin"})
    assert out.read_bytes() == A.read_bytes()


def test_the_analysis_has_every_section_the_post_cites():
    a = _analysis()
    assert set(a) >= {"validation", "load_balancer", "host_speed", "simulator", "spend"}
    assert a["validation"]["engine"]["outcome"] == "failed"
    assert a["validation"]["calibrated"]["outcome"] == "failed"
    assert set(a["simulator"]["h3"]) == {"0.88", "1", "1.12"}
    assert a["spend"] is None
    assert "UNVALIDATED" in a["_provenance"]["label"]


def test_the_headline_gaps_are_the_committed_sweeps():
    g = _analysis()["simulator"]["gaps"]["1"]
    got = {tag: round(g[tag]["point"], 4) for tag in g}
    assert got == {"arm A": 0.0821, "arm C": 3.9550, "ramp arm A": 8.2488,
                   "ramp arm C": 10.8734}


def test_both_attempts_miss_as_their_verdicts_say():
    v = _analysis()["validation"]
    assert (v["engine"]["misses"], v["engine"]["compared"]) == (34, 37)
    assert (v["calibrated"]["misses"], v["calibrated"]["compared"]) == (37, 37)
    assert v["engine"]["void_repeats"] == 1 and v["calibrated"]["void_repeats"] == 0
    # The residual's sign is the finding: attempt 1 predicted too slow (real < predicted),
    # attempt 2 too fast (real > predicted).
    assert v["engine"]["typical_residual"]["median_ratio_real_over_predicted"] < 1
    assert v["calibrated"]["typical_residual"]["median_ratio_real_over_predicted"] > 1


def test_probe_1_delivered_about_17_per_second_whatever_was_offered():
    steps = _analysis()["load_balancer"]["probes"]["1"]["steps"]
    for rate in ("25", "50"):
        assert 16 < steps[rate]["delivered_rate_rps"] < 18, rate


def test_no_raw_runpod_worker_id_is_published_for_the_probes():
    a = _analysis()
    for probe in a["load_balancer"]["probes"].values():
        for step in probe["steps"].values():
            labels = set(step["worker_share"]) | set(step.get("per_worker_concurrency") or {})
            assert all(w.startswith("worker ") for w in labels), labels
    text = A.read_text()
    for raw in ("38yfp2e8fbuocu", "6kr7ewoci6yumy", "kywbic97n9yt0l", "vlbc8ozita5pbh"):
        assert raw not in text


def test_the_signed_hypotheses_come_out_as_computed():
    s = _analysis()["simulator"]
    assert s["h1"]["overall"] is False
    assert s["h2"]["per_sweep"] == {"arm A": True, "arm C": False, "ramp arm A": False,
                                    "ramp arm C": False}
    assert s["h2"]["overall"] is False
    assert s["h4"] == {"arm A": False, "arm C": False, "overall": False}
    assert all(s["h3"][f]["holds"] is False for f in ("0.88", "1", "1.12"))
