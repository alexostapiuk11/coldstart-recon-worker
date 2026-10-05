import json

import pytest

from placement_measure.pins import pins
from placement_measure.prereg import CANDIDATES, SPLIT_GMU
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
