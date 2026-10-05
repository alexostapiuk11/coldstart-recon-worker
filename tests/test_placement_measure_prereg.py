"""The pre-registration document and the values jobs run on must agree."""

from pathlib import Path

from placement_measure import prereg

DOC = (Path(__file__).resolve().parents[1] / "docs" / "experiment-a4.md").read_text()


def test_every_revision_is_stated():
    for model, revision in prereg.CANDIDATES.items():
        assert f"`{model}` | `{revision}`" in DOC, model


def test_the_primary_and_fallback_are_stated_with_their_revisions():
    for model in (prereg.PRIMARY, prereg.FALLBACK):
        assert f"`{model}` at revision `{prereg.CANDIDATES[model]}`" in DOC


def test_the_engine_flags_and_memory_split_are_stated():
    for text in (f"T_max = `{prereg.T_MAX}`", f"--max-model-len {prereg.MAX_MODEL_LEN}",
                 f"--max-num-seqs {prereg.MAX_NUM_SEQS}", f"`{prereg.SPLIT_GMU}`",
                 f"`{prereg.SOLO_GMU}`", f"`{prereg.SLEEP_GMU:.2f}`"):
        assert text in DOC, text


def test_the_go_no_go_threshold_is_stated():
    assert f"`{prereg.GO_NO_GO_TOKENS:,}`" in DOC
    assert prereg.GO_NO_GO_TOKENS == prereg.GO_NO_GO_MIN_REQUESTS * prereg.T_MAX


def test_the_platform_and_image_are_stated():
    for text in (prereg.GPU_TYPE, prereg.NETWORK_VOLUME, prereg.VLLM_VERSION,
                 prereg.VLLM_BASE_DIGEST, prereg.HF_HOME):
        assert text in DOC, text


def test_the_base_digest_is_the_one_the_image_builds_from():
    dockerfile = (Path(__file__).resolve().parents[1] / "worker" / "Dockerfile").read_text()
    assert f"ARG VLLM_DIGEST={prereg.VLLM_BASE_DIGEST}" in dockerfile


def test_the_release_rule_is_stated():
    assert f"`{prereg.RELEASE_TOLERANCE_MIB}` MiB" in DOC
    assert f"`{prereg.RELEASE_TIMEOUT_S}` s" in DOC
