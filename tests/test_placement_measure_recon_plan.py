import json

import pytest

from placement_measure.pins import pins
from placement_measure.prereg import CANDIDATES, FALLBACK, SLEEP_GMU, SOLO_GMU, SPLIT_GMU
from placement_measure.recon_plan import recon_jobs


def test_every_recon_job_is_labelled_once_and_pins_every_revision():
    jobs = recon_jobs()
    labels = [j["label"] for j in jobs]
    assert len(labels) == len(set(labels))
    specs = [s for j in jobs for k in ("a", "b") if k in j for s in [j[k]]]
    specs += [s[k] for j in jobs for s in j.get("swaps", []) for k in ("a", "b")]
    assert specs and all(s["revision"] == CANDIDATES[s["model"]] for s in specs)
    json.dumps(jobs)  # a job that does not serialise fails here, not on a paid run


def test_the_coresidency_jobs_use_the_split():
    jobs = {j["label"]: j for j in recon_jobs()}
    for label in ("coresidency-primary", "coresidency-fallback"):
        assert jobs[label]["a"]["gpu_memory_utilization"] == SPLIT_GMU
        assert jobs[label]["b"]["gpu_memory_utilization"] == SPLIT_GMU


def test_the_stage_job_stages_every_candidate():
    stage = next(j for j in recon_jobs() if j["probe"] == "stage")
    assert {m["model"] for m in stage["models"]} == set(CANDIDATES)


def test_pins_require_the_template():
    assert pins("tpl")["templateId"] == "tpl"
    with pytest.raises(ValueError):
        pins("")


def test_the_primary_plan_is_the_default():
    assert recon_jobs("Qwen/Qwen3-4B") == recon_jobs()


def test_the_fallback_plan_keeps_the_labels_and_the_first_four_jobs():
    primary, fallback = recon_jobs(), recon_jobs(FALLBACK)
    assert [j["label"] for j in fallback] == [j["label"] for j in primary]
    assert fallback[:4] == primary[:4]  # help, stage and both co-residency pairs are class-free


def test_the_fallback_plan_measures_only_the_fallback_checkpoint():
    jobs = recon_jobs(FALLBACK)
    specs = [s for j in jobs[4:] for k in ("a", "b") if k in j for s in [j[k]]]
    specs += [s[k] for j in jobs[4:] for s in j.get("swaps", []) for k in ("a", "b")]
    assert specs and {s["model"] for s in specs} == {FALLBACK}
    assert all(s["revision"] == CANDIDATES[FALLBACK] for s in specs)
    json.dumps(jobs)


def test_the_fallback_swaps_keep_the_primary_plans_cache_states():
    primary = {j["label"]: j for j in recon_jobs()}
    fallback = {j["label"]: j for j in recon_jobs(FALLBACK)}
    for label in ("swaps-compile", "swaps-cache"):
        assert [s["cold"] for s in fallback[label]["swaps"]] == [s["cold"] for s in primary[label]["swaps"]]
        assert all(s["a"]["gpu_memory_utilization"] == SOLO_GMU for s in fallback[label]["swaps"])


def test_the_fallback_sleep_probe_keeps_its_flags_and_memory_split():
    sleep = next(j for j in recon_jobs(FALLBACK) if j["label"] == "sleep")
    for side in ("a", "b"):
        assert sleep[side]["gpu_memory_utilization"] == SLEEP_GMU
        assert "--enable-sleep-mode" in sleep[side]["extra_args"]


def test_a_model_class_that_is_neither_is_refused():
    with pytest.raises(ValueError, match="model class"):
        recon_jobs("Qwen/Qwen3-4B-Base")
