import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_the_rates_script_prints_the_numbers_the_amendment_quotes():
    out = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "a2_traffic_rates.py")],
        capture_output=True, text=True, check=True, cwd=REPO,
        env={"PYTHONDONTWRITEBYTECODE": "1", "PATH": "/usr/bin:/bin"},
    ).stdout
    for key in ("saturation_rps", "baseline_rps_one_replica", "peak_rps_one_replica",
                "validation_baseline_rps", "validation_peak_rps", "validation_requests",
                "validation_predicted_p50_s", "validation_last_arrival_s"):
        assert f"{key} " in out, key
    for line in out.splitlines():
        key, value = line.split(" ")
        float(value)  # every printed value parses as a number
