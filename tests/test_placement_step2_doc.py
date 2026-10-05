"""The pre-registration's step 2 rules and the code that applies them must agree."""

from pathlib import Path

from placement import step2

DOC = (Path(__file__).resolve().parents[1] / "docs" / "experiment-a4.md").read_text()
PART = DOC[DOC.index("## Step 2, part 1"):]


def _fmt(x) -> str:
    return f"`{x}`"


def test_the_section_exists_after_step_1():
    assert DOC.index("## Step 1") < DOC.index("## Step 2, part 1")


def test_the_request_shape_rule_is_stated():
    assert _fmt(step2.OUTPUT_LEN) in PART and _fmt(step2.SPLIT_CEILING_TARGET) in PART
    assert ", ".join(_fmt(n) for n in step2.TOTAL_LEN_CANDIDATES) in PART
    assert _fmt(step2.LEVEL_HEADROOM) in PART


def test_the_campaign_rules_are_stated():
    for value in (step2.CELL_REPEATS, step2.CELL_MIN_VALID, step2.SWAPS_PER_STATE,
                  step2.SLEEP_REPEATS, step2.EVICTION_MIN_FRACTION):
        assert _fmt(value) in PART, value
    for model in (step2.BASE, step2.INSTRUCT):
        assert _fmt(model) in PART


def test_the_simulated_design_is_stated():
    for value in (step2.N_MODELS, step2.HOT_FRACTION, int(step2.WARMUP_S), int(step2.MEAN_BURST_S),
                  step2.DUTY, step2.REPETITIONS, step2.PILOT_TRACES, step2.SWEEP_SEED,
                  step2.SCREEN_REPETITIONS, step2.SCREEN_SEED):
        assert _fmt(value) in PART, value
    assert ", ".join(str(s) for s in step2.SKEWS) in PART
    for value in step2.SCREEN_OFFERED_GPUS + step2.SCREEN_SLO_SWAP_MULTIPLES:
        assert _fmt(value) in PART, value
    assert f"s = {_fmt(step2.REFERENCE['s'])}" in PART and step2.REFERENCE["regime"] in PART


def test_the_validation_gate_is_stated():
    seeds = step2.VALIDATION_SEEDS
    assert seeds == tuple(range(seeds[0], seeds[-1] + 1))
    assert f"seeds {_fmt(seeds[0])} to {_fmt(seeds[-1])}" in PART
    for value in (step2.VALIDATION_S, step2.VALIDATION_LOAD, step2.VALIDATION_DUTY,
                  int(step2.VALIDATION_DRAIN_LIMIT_S), int(step2.VALIDATION_WINDOW_S),
                  step2.VALIDATION_MIN_SWAPS,
                  int(step2.VALIDATION_MEAN_BURST_S), step2.VALIDATION_REPEATS,
                  int(step2.VALIDATION_BIN_S), step2.MAX_SEND_JITTER_S, step2.MIN_COMPARED_BINS,
                  step2.MAX_MISS_FRACTION, step2.EDGE_TOLERANCE_S, step2.SWAP_COUNT_SLACK,
                  step2.HELD_OUT_TOLERANCE):
        assert _fmt(value) in PART, value


def test_the_section_14_decision_is_recorded():
    assert "Decided 2026-10-04" in PART and "ON-period load" in PART
