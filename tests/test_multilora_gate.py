from multilora.gate import verdict


def _row(real: float, synth: float, real2: float) -> dict:
    return {
        "real": {"ttft_p50": real, "throughput_tps": 1000.0 / real},
        "synthetic": {"ttft_p50": synth, "throughput_tps": 1000.0 / synth},
        "real_phases": [
            {"ttft_p50": real, "throughput_tps": 1000.0 / real},
            {"ttft_p50": real2, "throughput_tps": 1000.0 / real2},
        ],
    }


def _rows(bias: float, jitter: float) -> list[dict]:
    rows = []
    for i in range(24):
        wobble = jitter * ((i % 5) - 2) / 2
        real = 0.10 * (1 + wobble)
        rows.append(_row(real, real * (1 + bias), real * (1 + wobble / 4)))
    return rows


def test_indistinguishable_adapters_pass():
    assert verdict(_rows(bias=0.0, jitter=0.01), delta=0.05, iterations=500)["verdict"] == "pass"


def test_a_bias_beyond_the_margin_fails():
    res = verdict(_rows(bias=0.2, jitter=0.01), delta=0.05, iterations=500)
    assert res["verdict"] == "fail"
    assert not res["metrics"]["ttft_p50"]["inside"]


def test_real_against_real_noise_wider_than_the_margin_is_inconclusive_not_a_pass():
    rows = []
    for i in range(24):
        real2 = 0.10 * (1.3 if i % 2 else 0.7)
        rows.append(_row(0.10, 0.10, real2))
    res = verdict(rows, delta=0.05, iterations=500)
    assert res["verdict"] == "inconclusive"
    assert res["alpha"] == 0.10
