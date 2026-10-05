"""The co-located pair's KV memory is pinned (docs/experiment-a4.md, "Amendment,
2026-10-05"), so two engines fit together whether or not they hit the compile cache."""

from pathlib import Path

from placement_measure import prereg
from placement_measure.campaigns import CellDesign
from placement_measure.prereg import FALLBACK

DOC = (Path(__file__).resolve().parents[1] / "docs" / "experiment-a4.md").read_text()

# Qwen3-1.7B's KV per token: 2 (K and V) x 28 layers x 8 KV heads x 128 head dim x 2 bytes.
BYTES_PER_TOKEN = 2 * 28 * 8 * 128 * 2
BLOCK_TOKENS = 16
FLAG = f"--kv-cache-memory-bytes={prereg.SPLIT_KV_BYTES}"


def _design(**kw):
    return CellDesign(measured_model=FALLBACK, neighbour_model=FALLBACK, own_levels=(2,),
                      neighbour_levels=(16,), solo=False, input_len=1792, output_len=256,
                      repeats=1, seed=1, **kw)


def _payloads(design):
    return {s.condition: design.payload(s, f"r{s.run_index}") for s in design.schedule()}


def test_the_pin_is_the_registered_split_kv_in_whole_blocks():
    tokens = prereg.SPLIT_KV_BYTES // BYTES_PER_TOKEN
    assert prereg.SPLIT_KV_BYTES == tokens * BYTES_PER_TOKEN
    assert tokens % BLOCK_TOKENS == 0
    assert tokens == 55104  # step 2's registered split KV, `placement/registered.py`


def test_both_engines_of_a_pair_carry_the_same_pin():
    payload = _payloads(_design())["pair:o2:n16"]
    for side in ("a", "b"):
        assert FLAG in payload[side]["extra_args"], side
        assert payload[side]["gpu_memory_utilization"] == prereg.SPLIT_GMU, side


def test_a_solo_engine_is_not_pinned():
    payload = _payloads(_design(extra_cells=("solo:o8",)))["solo:o8"]
    assert payload["b"] is None
    assert not [a for a in payload["a"]["extra_args"] if a.startswith("--kv-cache-memory-bytes")]
    assert payload["a"]["gpu_memory_utilization"] == prereg.SOLO_GMU


def test_the_document_states_the_pin():
    assert f"`{prereg.SPLIT_KV_BYTES:,}`" in DOC
    assert "Amendment, 2026-10-05" in DOC
