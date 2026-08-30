from coldstart.analysis.metrics import derive
from coldstart.cache_config import resolve
from coldstart.checks import DiscardReason
from coldstart.driver import run_campaign
from coldstart.scheduler import build_schedule
from coldstart.store import JsonlStore
from coldstart.stubs.stub_endpoint import StubEndpoint, VirtualClock
from coldstart.submitter import StubSubmitter


def test_campaign_writes_one_record_per_scheduled_run(tmp_path):
    store = JsonlStore(tmp_path / "runs.jsonl")
    run_campaign(
        submitter=StubSubmitter(StubEndpoint(seed=3)),
        store=store,
        arms=["A", "B", "C"],
        triples=5,
        seed=11,
    )
    records = store.read_all()
    assert len(records) == 15
    assert sorted({r.arm for r in records}) == ["A", "B", "C"]


def test_failed_runs_are_recorded_and_never_retried(tmp_path):
    class SometimesBroken:
        def __init__(self):
            self.calls = 0
            self._inner = StubEndpoint(seed=4)

        def run(self, arm, run_id):
            self.calls += 1
            if self.calls % 3 == 0:
                raise RuntimeError("health check timed out")
            return self._inner.run(arm=arm, run_id=run_id)

    ep = SometimesBroken()
    store = JsonlStore(tmp_path / "runs.jsonl")
    run_campaign(
        submitter=StubSubmitter(ep), store=store, arms=["A", "B", "C"], triples=3, seed=1
    )
    records = store.read_all()
    assert len(records) == 9, "every scheduled run yields exactly one record"
    assert ep.calls == 9, "no run may be retried in place"
    failed = [r for r in records if r.status["outcome"] == "failed"]
    assert failed and failed[0].status["failure_class"] == "health_timeout"


# --- run_id identity: the record must name the paths the run actually used ---


def test_record_run_id_is_the_id_the_endpoint_ran_under(tmp_path):
    """CacheConfig namespaces cold paths by run_id and its docstring promises
    the config is reproducible from a stored RunRecord.run_id. Adopting the
    platform's job id here instead would break that."""
    seen = []

    class Recording:
        def __init__(self):
            self._inner = StubEndpoint(seed=7)

        def run(self, arm, run_id):
            seen.append(run_id)
            return self._inner.run(arm=arm, run_id=run_id)

    store = JsonlStore(tmp_path / "runs.jsonl")
    run_campaign(
        submitter=StubSubmitter(Recording()), store=store, arms=["A"], triples=3, seed=2
    )
    stored = [r.run_id for r in store.read_all()]
    assert stored == seen


def test_cold_cache_paths_are_reconstructible_from_the_stored_record(tmp_path):
    store = JsonlStore(tmp_path / "runs.jsonl")
    run_campaign(
        submitter=StubSubmitter(StubEndpoint(seed=9)),
        store=store,
        arms=["A"],
        triples=2,
        seed=3,
    )
    for record in store.read_all():
        expected = resolve(record.arm).env(record.run_id)
        assert record.config["env"] == expected


def test_run_ids_are_unique_across_the_campaign(tmp_path):
    """Two runs sharing an id would share a cold cache directory, and the
    second would find the first's compiled artifacts."""
    store = JsonlStore(tmp_path / "runs.jsonl")
    run_campaign(
        submitter=StubSubmitter(StubEndpoint(seed=6)),
        store=store,
        arms=["A", "B", "C"],
        triples=4,
        seed=5,
    )
    ids = [r.run_id for r in store.read_all()]
    assert len(set(ids)) == len(ids)


# --- provenance and schedule bookkeeping ------------------------------------


def test_records_carry_the_resolved_arm_configuration(tmp_path):
    store = JsonlStore(tmp_path / "runs.jsonl")
    run_campaign(
        submitter=StubSubmitter(StubEndpoint(seed=8)),
        store=store,
        arms=["C"],
        triples=1,
        seed=4,
    )
    record = store.read_all()[0]
    assert record.config["arm"] == "C"
    assert record.config["compile_cache_warm"] is True
    assert record.engine["compile_cache_observed"] is True


def test_triple_and_run_indices_are_preserved(tmp_path):
    store = JsonlStore(tmp_path / "runs.jsonl")
    run_campaign(
        submitter=StubSubmitter(StubEndpoint(seed=2)),
        store=store,
        arms=["A", "B", "C"],
        triples=3,
        seed=1,
    )
    records = store.read_all()
    assert [r.run_index for r in records] == list(range(9))
    assert [r.host["triple_index"] for r in records] == [0, 0, 0, 1, 1, 1, 2, 2, 2]


def test_failed_record_still_carries_clock_a_and_triple_index(tmp_path):
    class AlwaysBroken:
        def run(self, arm, run_id):
            raise RuntimeError("health check timed out")

    store = JsonlStore(tmp_path / "runs.jsonl")
    run_campaign(
        submitter=StubSubmitter(AlwaysBroken()),
        store=store,
        arms=["A"],
        triples=2,
        seed=1,
    )
    for record in store.read_all():
        assert record.status["outcome"] == "failed"
        assert "t_submit" in record.clock_A and "t_result" in record.clock_A
        assert record.host["triple_index"] is not None


# --- the whole loop: campaign -> store -> analysis, no GPU ------------------


def test_a_stub_campaign_derives_end_to_end(tmp_path):
    """Clock A and clock B must be consistent for this to work at all: the
    submitter and the endpoint share a virtual clock, so the clock-A span
    actually contains the clock-B timeline it is supposed to."""
    clock = VirtualClock()
    store = JsonlStore(tmp_path / "runs.jsonl")
    run_campaign(
        submitter=StubSubmitter(StubEndpoint(seed=12, clock=clock), clock=clock),
        store=store,
        arms=["A", "B", "C"],
        triples=4,
        seed=7,
    )
    rows = [derive(r) for r in store.read_all()]
    assert len(rows) == 12
    assert all(row["ok"] for row in rows)
    assert all(row["t_s4_bracket"] is not None for row in rows)
    assert all(row["t_fast_seconds"] is not None for row in rows)
    warm = [r for r in rows if r["arm"] == "C"]
    cold = [r for r in rows if r["arm"] == "B"]
    assert max(r["t_compile"] for r in warm) < min(r["t_compile"] for r in cold)


def test_clock_a_span_contains_the_clock_b_timeline(tmp_path):
    """A real wall clock around an instant stub gives a clock-A span far
    shorter than the clock-B marks inside it, and derive() then computes a
    negative T_total. The shared virtual clock is what prevents that."""
    clock = VirtualClock()
    store = JsonlStore(tmp_path / "runs.jsonl")
    run_campaign(
        submitter=StubSubmitter(StubEndpoint(seed=13, clock=clock), clock=clock),
        store=store,
        arms=["A"],
        triples=3,
        seed=2,
    )
    for record in store.read_all():
        span = record.clock_A["t_result"] - record.clock_A["t_submit"]
        marks = {m["stage"]: m["t_mono"] for m in record.clock_B["marks"]}
        assert span > marks["S7_warmup_done"]


def test_derived_t_total_is_positive_for_every_run(tmp_path):
    clock = VirtualClock()
    store = JsonlStore(tmp_path / "runs.jsonl")
    run_campaign(
        submitter=StubSubmitter(StubEndpoint(seed=14, clock=clock), clock=clock),
        store=store,
        arms=["A", "B", "C"],
        triples=3,
        seed=8,
    )
    for row in (derive(r) for r in store.read_all()):
        assert row["t_total"] > 0


# --- resumable campaigns -----------------------------------------------------


def test_resume_skips_completed_runs_and_keeps_the_schedule(tmp_path):
    """Resume must continue the same interleaved schedule. Rebuilding it would
    change which arm runs when, which is the confound interleaving exists to
    prevent."""

    class FailsAfter:
        def __init__(self, limit):
            self.limit = limit
            self.calls = 0
            self._inner = StubEndpoint(seed=21)

        def run(self, arm, run_id):
            self.calls += 1
            if self.calls > self.limit:
                raise KeyboardInterrupt("operator stopped the window")
            return self._inner.run(arm=arm, run_id=run_id)

    store = JsonlStore(tmp_path / "runs.jsonl")
    kw = {"store": store, "arms": ["A", "B", "C"], "triples": 4, "seed": 31}
    try:
        run_campaign(submitter=StubSubmitter(FailsAfter(5)), **kw)
    except KeyboardInterrupt:
        pass
    first = store.read_all()
    assert len(first) == 5

    ep = FailsAfter(999)
    run_campaign(submitter=StubSubmitter(ep), resume=True, **kw)
    all_records = store.read_all()

    assert len(all_records) == 12
    assert ep.calls == 7, "resume must not re-run completed runs"
    assert [r.run_index for r in all_records] == list(range(12))
    # The arm at each index is the one the original schedule assigned.
    expected = [s.arm for s in build_schedule(arms=["A", "B", "C"], triples=4, seed=31)]
    assert [r.arm for r in all_records] == expected


def test_resume_is_off_by_default(tmp_path):
    """Appending a second campaign to a populated store must not silently
    skip runs the operator meant to perform."""
    store = JsonlStore(tmp_path / "runs.jsonl")
    kw = {"store": store, "arms": ["A"], "triples": 2, "seed": 1}
    run_campaign(submitter=StubSubmitter(StubEndpoint(seed=22)), **kw)
    run_campaign(submitter=StubSubmitter(StubEndpoint(seed=23)), **kw)
    assert len(store.read_all()) == 4


def test_resume_rejects_a_drifted_seed(tmp_path):
    """A resumed window must use the exact seed of the original one. Silently
    accepting a different seed would splice two different interleavings
    together with nothing downstream able to tell -- the confound
    interleaving exists to prevent."""
    store = JsonlStore(tmp_path / "runs.jsonl")
    run_campaign(
        submitter=StubSubmitter(StubEndpoint(seed=21)),
        store=store,
        arms=["A", "B", "C"],
        triples=4,
        seed=31,
    )
    try:
        run_campaign(
            submitter=StubSubmitter(StubEndpoint(seed=21)),
            store=store,
            arms=["A", "B", "C"],
            triples=4,
            seed=99,
            resume=True,
        )
    except ValueError as e:
        msg = str(e)
        assert "run_index 0" in msg
        assert "C" in msg  # the arm actually stored at index 0
        assert "A" in msg  # the arm the drifted schedule expects at index 0
    else:
        raise AssertionError("expected ValueError")


# --- missing arm-state telemetry is a discard, not a failure ----------------
#
# The run completed and produced a full, otherwise-usable measurement -- a
# dropped telemetry field between engine and store is a plumbing bug, not an
# engine/infra failure (spec: failure vs. discard are two distinct, disjoint
# signals). So these records must stay `status["outcome"] == "ok"`, with
# `engine` populated exactly as the healthy path does, and get excluded only
# via `consistent=False` / `DiscardReason.ARM_STATE_UNVERIFIABLE` -- the same
# shape MISSING_WARMUP_END already uses for a structurally identical case.


def test_missing_compile_cache_observed_is_an_ok_record_discarded_by_arm_state(tmp_path):
    """worker/handler.py sets compile_cache_observed unconditionally on every
    real run. If it is absent from an otherwise-successful payload, something
    upstream dropped data -- and metrics.derive()'s arm-state gate treats a
    missing field as unknown, not a violation (on purpose, for historical
    rows), so it cannot catch this by itself. The driver must flag it
    explicitly, but the record stays `ok` with everything else intact."""

    class DropsObserved:
        def __init__(self, clock):
            self._inner = StubEndpoint(seed=15, clock=clock)

        def run(self, arm, run_id):
            payload = self._inner.run(arm=arm, run_id=run_id)
            del payload["compile_cache_observed"]
            return payload

    # A shared VirtualClock, not a real wall clock, so clock A's span
    # actually contains clock B's marks -- see
    # test_clock_a_span_contains_the_clock_b_timeline above for why a real
    # clock here would make derive() see a negative T_total unrelated to
    # what this test is checking.
    clock = VirtualClock()
    store = JsonlStore(tmp_path / "runs.jsonl")
    run_campaign(
        submitter=StubSubmitter(DropsObserved(clock), clock=clock),
        store=store,
        arms=["A"],
        triples=2,
        seed=1,
    )
    records = store.read_all()
    assert len(records) == 2
    for record in records:
        assert record.status["outcome"] == "ok"
        assert record.status["arm_state_unverifiable"] is True
        # engine populated exactly as the healthy path -- nothing lost.
        assert record.engine["s4_subphases"]
        assert record.engine["compile_cache_observed"] is None
    for record in records:
        row = derive(record)
        assert row["ok"] is True
        assert row["consistent"] is False
        assert row["discard_reason"] == DiscardReason.ARM_STATE_UNVERIFIABLE
        # Every other metric is still recoverable -- this is the whole point
        # of a discard rather than a failure.
        assert row["t_weights"] is not None
        assert row["warmup_penalty"] is not None


def test_missing_expected_compile_cache_warm_is_an_ok_record_discarded_by_arm_state(tmp_path):
    """The other half of the pair: cache_config.compile_cache_warm missing
    (e.g. the worker's cache_config block itself got truncated) is the same
    class of unverifiable run as a missing compile_cache_observed."""

    class DropsExpected:
        def __init__(self, clock):
            self._inner = StubEndpoint(seed=16, clock=clock)

        def run(self, arm, run_id):
            payload = self._inner.run(arm=arm, run_id=run_id)
            del payload["cache_config"]["compile_cache_warm"]
            return payload

    clock = VirtualClock()
    store = JsonlStore(tmp_path / "runs.jsonl")
    run_campaign(
        submitter=StubSubmitter(DropsExpected(clock), clock=clock),
        store=store,
        arms=["C"],
        triples=1,
        seed=2,
    )
    record = store.read_all()[0]
    assert record.status["outcome"] == "ok"
    assert record.status["arm_state_unverifiable"] is True
    row = derive(record)
    assert row["ok"] is True
    assert row["consistent"] is False
    assert row["discard_reason"] == DiscardReason.ARM_STATE_UNVERIFIABLE


def test_present_arm_state_telemetry_still_yields_a_consistent_ok_record(tmp_path):
    """Sanity check that the new guard doesn't fire on the ordinary path --
    every field present must still produce an ordinary, consistent ok
    record, with no `arm_state_unverifiable` key at all."""
    clock = VirtualClock()
    store = JsonlStore(tmp_path / "runs.jsonl")
    run_campaign(
        submitter=StubSubmitter(StubEndpoint(seed=17, clock=clock), clock=clock),
        store=store,
        arms=["A"],
        triples=2,
        seed=1,
    )
    for record in store.read_all():
        assert record.status["outcome"] == "ok"
        assert "arm_state_unverifiable" not in record.status
        assert derive(record)["consistent"] is True


def test_resume_rejects_a_shrunk_schedule(tmp_path):
    """Resuming with fewer triples than the original window leaves stored
    run_indices the rebuilt schedule doesn't cover -- the same class of drift
    as a wrong seed, and must not be silently ignored."""
    store = JsonlStore(tmp_path / "runs.jsonl")
    run_campaign(
        submitter=StubSubmitter(StubEndpoint(seed=21)),
        store=store,
        arms=["A", "B", "C"],
        triples=4,
        seed=31,
    )
    try:
        run_campaign(
            submitter=StubSubmitter(StubEndpoint(seed=21)),
            store=store,
            arms=["A", "B", "C"],
            triples=2,
            seed=31,
            resume=True,
        )
    except ValueError as e:
        assert "run_index" in str(e)
        assert "beyond" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_records_keep_the_raw_engine_log(tmp_path):
    """The published claim is that a reader re-derives every number from the
    committed records. Without the raw log, `s4_subphases` can only be
    trusted -- and a parser bug found after the campaign would make the
    dataset unrepeatable instead of re-parseable. Cannot be added
    retroactively: unrecorded logs are gone."""
    clock = VirtualClock()
    store = JsonlStore(tmp_path / "runs.jsonl")
    run_campaign(
        submitter=StubSubmitter(StubEndpoint(seed=5, clock=clock), clock=clock),
        store=store,
        arms=["A"],
        triples=1,
        seed=1,
    )
    record = store.read_all()[0]
    lines = record.engine["log_lines"]
    assert lines, "raw engine log missing from the stored record"

    # And it must be the log the parsed values actually came from.
    from coldstart.vllm_logs import parse_engine_log

    reparsed = parse_engine_log("\n".join(lines))
    assert reparsed.phases == record.engine["s4_subphases"]
    assert reparsed.merged == record.engine["s4_merged"]
