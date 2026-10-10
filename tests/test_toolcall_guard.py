import errno
import json
import math
import os
import stat
from pathlib import Path

import pytest

from toolcall.guard import (
    INPUT_OVERHEAD_TOKENS,
    SDK_MAX_RETRIES,
    GuardedClient,
    LedgerWriteError,
    SpendCapReached,
    SpendGuard,
    SpendGuardError,
    SpendLedger,
    call_bound_usd,
    check_estimate,
    input_tokens_bound,
)
from toolcall.prices import PRICES
from toolcall.providers import PARSE, ModelSettings, ScriptedClient
from toolcall.responses import anthropic_text, openai_text

MINI = ModelSettings("openai", "gpt-5.4-mini-2026-03-17", 0.0, reasoning_effort="none")
SONNET = ModelSettings("anthropic", "claude-sonnet-5-5", None, thinking="between_tools")
BODY = {"input": "x" * 400}


def _guarded(settings, policy, approved=1.0):
    client = ScriptedClient(settings, policy)
    guard = SpendGuard(approved)
    return GuardedClient(client, guard, PARSE[settings.provider]), guard, client


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, 0.0, -1.0])
def test_a_non_finite_or_non_positive_approval_is_refused(bad):
    with pytest.raises(SpendCapReached):
        SpendGuard(bad)
    with pytest.raises(SpendCapReached):
        check_estimate(1.0, bad)


def test_a_non_finite_estimate_is_refused():
    with pytest.raises(SpendCapReached):
        check_estimate(math.nan, 5.0)
    with pytest.raises(SpendCapReached):
        check_estimate(math.inf, 5.0)
    check_estimate(4.0, 5.0)
    with pytest.raises(SpendCapReached):
        check_estimate(6.0, 5.0)


def test_the_bound_includes_the_overhead_and_the_dearer_input_price():
    chars = len(json.dumps(BODY))
    assert input_tokens_bound(MINI, BODY) == chars / 2.0 + INPUT_OVERHEAD_TOKENS
    assert input_tokens_bound(SONNET, BODY) == chars / 2.0 * 1.3 + INPUT_OVERHEAD_TOKENS
    # OpenAI has no cache-write price, so its input price is the larger one.
    p = PRICES[MINI.model]
    assert call_bound_usd(MINI, BODY) == pytest.approx(
        ((chars / 2.0 + 500) * p.input + MINI.max_output_tokens * p.output) / 1e6)
    # Anthropic's cache write (2.50) costs more than its input (2.00).
    p = PRICES[SONNET.model]
    assert p.cache_write > p.input
    assert call_bound_usd(SONNET, BODY) == pytest.approx(
        ((chars / 2.0 * 1.3 + 500) * p.cache_write + SONNET.max_output_tokens * p.output) / 1e6)


def test_a_raising_post_is_charged_the_worst_case_and_reraised():
    def boom(body):
        raise TimeoutError("read timeout")

    gc, guard, _ = _guarded(MINI, boom)
    bound = call_bound_usd(MINI, BODY)
    with pytest.raises(TimeoutError):
        gc.post(BODY)
    assert guard.spent == pytest.approx(bound * (1 + SDK_MAX_RETRIES))
    assert guard.unmetered == 1 and guard.calls == 1
    with pytest.raises(TimeoutError):
        gc.post(BODY)
    assert guard.spent == pytest.approx(2 * bound * (1 + SDK_MAX_RETRIES))  # later calls see it


def test_the_cap_check_covers_the_retry_worst_case():
    bound = call_bound_usd(MINI, BODY)
    gc, _, client = _guarded(MINI, lambda b: openai_text("ok"),
                                 approved=bound * (1 + SDK_MAX_RETRIES) * 0.99)
    with pytest.raises(SpendCapReached):
        gc.post(BODY)
    assert client.sent == []  # refused before anything was sent


def test_a_response_without_usage_is_charged_the_bound_not_zero():
    gc, guard, _ = _guarded(MINI, lambda b: {**openai_text("ok"), "usage": {}})
    gc.post(BODY)
    assert guard.spent == pytest.approx(call_bound_usd(MINI, BODY))
    assert guard.unmetered == 1


def test_a_metered_response_is_charged_its_own_usage():
    gc, guard, _ = _guarded(MINI, lambda b: openai_text("ok"))
    gc.post(BODY)
    assert guard.unmetered == 0 and guard.calls == 1
    assert guard.spent == pytest.approx((1000 * 0.75 + 40 * 4.50) / 1e6)


def test_an_unreadable_response_is_charged_the_bound():
    gc, guard, _ = _guarded(MINI, lambda b: {"output": [{"type": "function_call"}], "usage": {}})
    gc.post(BODY)
    assert guard.spent == pytest.approx(call_bound_usd(MINI, BODY))


def test_an_unpriced_model_stops_the_run_before_any_call():
    odd = ModelSettings("openai", "gpt-unpriced", 0.0, reasoning_effort="none")
    gc, guard, client = _guarded(odd, lambda b: openai_text("ok"))
    with pytest.raises(SpendGuardError, match="no pinned price"):
        gc.post(BODY)
    assert client.sent == [] and guard.spent == 0.0
    assert issubclass(SpendGuardError, SpendCapReached)


def test_usage_the_price_table_cannot_cost_stops_the_run():
    bad = openai_text("ok")
    bad["usage"]["input_tokens"] = 10
    bad["usage"]["input_tokens_details"]["cached_tokens"] = 50
    gc, guard, _ = _guarded(MINI, lambda b: bad)
    with pytest.raises(SpendGuardError, match="cannot meter"):
        gc.post(BODY)
    assert guard.spent == pytest.approx(call_bound_usd(MINI, BODY))  # the call happened


def test_spend_never_exceeds_the_approval_when_some_posts_raise():
    state = {"n": 0}

    def alternate(body):
        state["n"] += 1
        if state["n"] % 2 == 0:
            raise ConnectionError("reset")
        return openai_text("ok")

    bound = call_bound_usd(MINI, BODY)
    approved = bound * 10
    gc, guard, _ = _guarded(MINI, alternate, approved=approved)
    stopped = False
    for _ in range(100):
        try:
            gc.post(BODY)
        except ConnectionError:
            pass
        except SpendCapReached:
            stopped = True
            break
        assert guard.spent <= approved
    assert stopped and guard.unmetered > 0 and guard.spent <= approved


def test_the_anthropic_response_is_metered_with_cache_writes():
    gc, guard, _ = _guarded(SONNET, lambda b: anthropic_text("ok"))
    gc.post(BODY)
    assert guard.spent == pytest.approx((1000 * 2.00 + 40 * 10.00) / 1e6)


def test_a_seeded_guard_counts_prior_spend_against_the_approval():
    bound = call_bound_usd(MINI, BODY)
    guard = SpendGuard(bound * 10, spent=bound * 8)
    assert guard.spent == pytest.approx(bound * 8)
    with pytest.raises(SpendCapReached, match="stopping"):
        guard.before(bound * 3)
    guard.before(bound)  # still fits


@pytest.mark.parametrize("bad", [math.nan, math.inf, -0.01, True])
def test_a_bad_seed_is_refused(bad):
    with pytest.raises(SpendCapReached, match="seed"):
        SpendGuard(1.0, spent=bad)


# --- the durable spend ledger -------------------------------------------------------


def _ledger_lines(path):
    return path.read_text().splitlines()


def test_a_ledger_totals_settled_amounts_and_counts_an_unsettled_reservation_at_worst(tmp_path):
    led = SpendLedger(tmp_path / "l.jsonl")
    a, b = led.reserve(0.5), led.reserve(0.3)
    assert a != b and led.total() == pytest.approx(0.8)  # a crash now costs the worst case
    led.settle(a, 0.1)
    assert led.total() == pytest.approx(0.4)
    led.settle(b, 0.05)
    assert led.total() == pytest.approx(0.15)


def test_a_reopened_ledger_keeps_its_total_and_never_reuses_an_id(tmp_path):
    path = tmp_path / "l.jsonl"
    led = SpendLedger(path)
    first = led.reserve(0.5)
    led.close()
    reopened = SpendLedger(path)
    assert reopened.total() == pytest.approx(0.5)
    second = reopened.reserve(0.2)
    assert second != first
    reopened.settle(first, 0.01)  # a reservation of an earlier session can be settled
    assert reopened.total() == pytest.approx(0.21)


def _record_fsyncs(monkeypatch):
    """(file fsyncs, directory fsyncs), told apart by what the descriptor is."""
    files, dirs = [], []
    real = os.fsync

    def spy(fd):
        (dirs if stat.S_ISDIR(os.fstat(fd).st_mode) else files).append(fd)
        real(fd)

    monkeypatch.setattr(os, "fsync", spy)
    return files, dirs


def test_every_ledger_line_is_flushed_and_fsynced(tmp_path, monkeypatch):
    files, _ = _record_fsyncs(monkeypatch)
    led = SpendLedger(tmp_path / "l.jsonl")
    led.settle(led.reserve(0.5), 0.1)
    assert len(files) == 2 == len(_ledger_lines(tmp_path / "l.jsonl"))


def test_the_ledgers_directory_is_fsynced_once_when_the_file_is_created(tmp_path, monkeypatch):
    files, dirs = _record_fsyncs(monkeypatch)
    led = SpendLedger(tmp_path / "sub" / "l.jsonl")
    assert dirs == []  # opening a ledger writes nothing
    rid = led.reserve(0.5)
    assert len(dirs) == 1  # the first reserve created the file
    led.settle(rid, 0.1)
    led.settle(led.reserve(0.2), 0.0)
    assert len(dirs) == 1 and len(files) == 4
    led.close()
    SpendLedger(tmp_path / "sub" / "l.jsonl").reserve(0.1)  # an existing file: no new entry
    assert len(dirs) == 1


@pytest.mark.parametrize("bad", [math.nan, math.inf, -0.1])
def test_a_ledger_refuses_a_non_finite_or_negative_amount(tmp_path, bad):
    led = SpendLedger(tmp_path / "l.jsonl")
    with pytest.raises(ValueError, match="amount"):
        led.reserve(bad)
    rid = led.reserve(0.5)
    with pytest.raises(ValueError, match="amount"):
        led.settle(rid, bad)


def test_a_ledger_refuses_to_settle_an_unknown_or_settled_reservation(tmp_path):
    led = SpendLedger(tmp_path / "l.jsonl")
    with pytest.raises(ValueError, match="no open reservation"):
        led.settle(7, 0.1)
    rid = led.reserve(0.5)
    led.settle(rid, 0.1)
    with pytest.raises(ValueError, match="no open reservation"):
        led.settle(rid, 0.1)
    assert led.total() == pytest.approx(0.1)


def test_a_torn_last_line_is_tolerated(tmp_path):
    path = tmp_path / "l.jsonl"
    path.write_text('{"id": 0, "reserve": 0.5}\n{"id": 0, "settle": 0.1}\n'
                    '{"id": 1, "reserve": 0.4}\n{"id": 1, "set')
    led = SpendLedger(path)  # the half-written settle is lost; reservation 1 stays at worst
    assert led.total() == pytest.approx(0.1 + 0.4)
    rid = led.reserve(0.2)  # appending after the torn tail leaves a readable file
    led.settle(rid, 0.05)
    led.close()
    assert SpendLedger(path).total() == pytest.approx(0.1 + 0.4 + 0.05)


def test_a_torn_reservation_that_still_parses_counts_at_worst(tmp_path):
    path = tmp_path / "l.jsonl"
    path.write_text('{"id": 0, "reserve": 0.5}\n{"id": 1, "reserve": 0.4}')  # no newline
    led = SpendLedger(path)
    assert led.total() == pytest.approx(0.9)
    led.settle(led.reserve(0.1), 0.0)
    led.close()
    assert SpendLedger(path).total() == pytest.approx(0.9)


def test_a_malformed_line_anywhere_but_the_last_raises(tmp_path):
    path = tmp_path / "l.jsonl"
    path.write_text('{"id": 0, "reserve": 0.5}\n{"id": 0, "se\n{"id": 1, "reserve": 0.4}\n')
    with pytest.raises(ValueError, match="line 2"):
        SpendLedger(path)
    path.write_text('{"id": 0, "reserve": 0.5}\n{"id": 5, "settle": 0.1}\n')
    with pytest.raises(ValueError, match="line 2"):  # a settle for a reservation never made
        SpendLedger(path)
    path.write_text('{"id": 0, "reserve": -1}\n{"id": 1, "reserve": 0.4}\n')
    with pytest.raises(ValueError, match="line 1"):
        SpendLedger(path)


def _ledgered(settings, policy, tmp_path, approved=1.0, seen=None):
    client = ScriptedClient(settings, policy)
    led = SpendLedger(tmp_path / "l.jsonl")
    guard = SpendGuard(approved, ledger=led)
    return GuardedClient(client, guard, PARSE[settings.provider]), guard, led


def test_the_ledger_holds_the_worst_case_while_the_post_is_in_flight(tmp_path):
    bound = call_bound_usd(MINI, BODY)
    seen = []

    def policy(body):
        seen.append(led.total())
        return openai_text("ok")

    gc, guard, led = _ledgered(MINI, policy, tmp_path)
    gc.post(BODY)
    assert seen == [pytest.approx(bound * (1 + SDK_MAX_RETRIES))]
    assert led.total() == pytest.approx(guard.spent) == pytest.approx(
        (1000 * 0.75 + 40 * 4.50) / 1e6)


def test_a_refused_call_reserves_nothing(tmp_path):
    bound = call_bound_usd(MINI, BODY)
    gc, _, led = _ledgered(MINI, lambda b: openai_text("ok"), tmp_path,
                           approved=bound * (1 + SDK_MAX_RETRIES) * 0.99)
    with pytest.raises(SpendCapReached):
        gc.post(BODY)
    assert not (tmp_path / "l.jsonl").exists() and led.total() == 0.0


def _boom(exc):
    def policy(body):
        raise exc

    return policy


@pytest.mark.parametrize("policy, charge", [
    (_boom(TimeoutError("read timeout")), "worst"),
    (_boom(KeyboardInterrupt()), "worst"),  # a crash is the worst case, not a skipped settle
    (_boom(SpendCapReached("inner guard")), "nothing"),  # the inner guard charged it
    (lambda b: {**openai_text("ok"), "usage": {}}, "bound"),  # unmetered
    (lambda b: {"output": [{"type": "function_call"}], "usage": {}}, "bound"),  # unreadable
])
def test_every_branch_settles_the_reservation_with_what_the_guard_charged(tmp_path, policy, charge):
    bound = call_bound_usd(MINI, BODY)
    gc, guard, led = _ledgered(MINI, policy, tmp_path)
    try:
        gc.post(BODY)
    except BaseException:  # noqa: BLE001, S110 -- the branch under test re-raises
        pass
    expected = {"worst": bound * (1 + SDK_MAX_RETRIES), "bound": bound, "nothing": 0.0}[charge]
    assert guard.spent == pytest.approx(expected)
    assert led.total() == pytest.approx(expected)  # settled, and counted exactly once
    assert len(_ledger_lines(tmp_path / "l.jsonl")) == 2


def test_usage_the_price_table_cannot_cost_is_settled_at_the_bound(tmp_path):
    bad = openai_text("ok")
    bad["usage"]["input_tokens"] = 10
    bad["usage"]["input_tokens_details"]["cached_tokens"] = 50
    gc, guard, led = _ledgered(MINI, lambda b: bad, tmp_path)
    with pytest.raises(SpendGuardError, match="cannot meter"):
        gc.post(BODY)
    assert led.total() == pytest.approx(guard.spent) == pytest.approx(call_bound_usd(MINI, BODY))


def test_the_ledger_total_equals_the_guard_after_a_mixed_run(tmp_path):
    state = {"n": 0}

    def mixed(body):
        state["n"] += 1
        if state["n"] % 4 == 0:
            raise ConnectionError("reset")
        if state["n"] % 3 == 0:
            return {**openai_text("ok"), "usage": {}}
        return openai_text("ok")

    gc, guard, led = _ledgered(MINI, mixed, tmp_path, approved=10.0)
    for _ in range(30):
        try:
            gc.post(BODY)
        except ConnectionError:
            pass
    assert guard.unmetered > 0
    assert led.total() == pytest.approx(guard.spent)


def test_a_guard_seeded_from_a_ledger_resumes_from_its_total(tmp_path):
    bound = call_bound_usd(MINI, BODY)
    led = SpendLedger(tmp_path / "l.jsonl")
    led.reserve(bound * 9)  # a session that died mid-call
    guard = SpendGuard(bound * 10, spent=led.total(), ledger=led)
    with pytest.raises(SpendCapReached, match="stopping"):
        guard.before(bound * 3)


# --- one writer at a time ------------------------------------------------------------


def test_a_second_open_of_the_same_ledger_is_refused_until_the_first_closes(tmp_path):
    path = tmp_path / "x.spend.jsonl"
    first = SpendLedger(path, label="pilot-baseline")
    with pytest.raises(SpendGuardError, match="another run of pilot-baseline holds .*x.spend.lock"):
        SpendLedger(path, label="pilot-baseline")
    other = SpendLedger(tmp_path / "y.spend.jsonl")  # a different ledger is not in the way
    other.close()
    first.close()
    first.close()  # closing twice is harmless
    SpendLedger(path).close()


def test_a_ledger_that_fails_to_open_releases_its_lock(tmp_path):
    path = tmp_path / "x.spend.jsonl"
    path.write_text('{"id": 0, "reserve": 0.5}\nnot json\n{"id": 1, "reserve": 0.4}\n')
    with pytest.raises(ValueError, match="line 2"):
        SpendLedger(path)
    path.write_text('{"id": 0, "reserve": 0.5}\n')
    with SpendLedger(path) as led:  # not "locked by the failed attempt"
        assert led.total() == pytest.approx(0.5)


def test_a_process_holding_the_lock_file_blocks_the_ledger(tmp_path):
    import fcntl

    path = tmp_path / "x.spend.jsonl"
    with (tmp_path / "x.spend.lock").open("a") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(SpendGuardError, match="holds"):
            SpendLedger(path)
    SpendLedger(path).close()


# --- a failed write stops the run and leaves no partial line ---------------------------


def test_a_failed_fsync_stops_the_run_and_the_file_is_as_it_was(tmp_path, monkeypatch):
    path = tmp_path / "l.jsonl"
    led = SpendLedger(path)
    rid = led.reserve(0.5)
    before = path.read_bytes()
    real = os.fsync
    state = {"fail": True}

    def flaky(fd):
        if state["fail"]:
            raise OSError(errno.ENOSPC, "No space left on device")
        real(fd)

    monkeypatch.setattr(os, "fsync", flaky)
    with pytest.raises(LedgerWriteError, match="No space left"):
        led.settle(rid, 0.1)
    assert issubclass(LedgerWriteError, SpendGuardError)
    assert path.read_bytes() == before
    state["fail"] = False
    led.settle(rid, 0.1)  # the reservation was still open, and the ledger still works
    assert led.total() == pytest.approx(0.1)


def test_a_half_written_line_is_rolled_back_before_the_error_is_raised(tmp_path, monkeypatch):
    path = tmp_path / "l.jsonl"
    led = SpendLedger(path)
    led.reserve(0.5)
    before = path.read_bytes()
    real_open = Path.open

    class HalfWriter:
        def __init__(self, f):
            self.f = f

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.f.close()

        def write(self, data):
            self.f.write(data[: len(data) // 2])
            self.f.flush()
            raise OSError(errno.ENOSPC, "No space left on device")

    def open_(self, mode="r", *a, **k):
        f = real_open(self, mode, *a, **k)
        return HalfWriter(f) if self == path and mode == "ab" else f

    monkeypatch.setattr(Path, "open", open_)
    with pytest.raises(LedgerWriteError):
        led.reserve(0.3)
    assert path.read_bytes() == before  # nothing left for the next append to land after
    monkeypatch.undo()
    led.reserve(0.2)
    assert led.total() == pytest.approx(0.7)
    led.close()
    assert SpendLedger(path).total() == pytest.approx(0.7)


def test_a_failed_first_write_leaves_an_empty_file_and_a_working_ledger(tmp_path, monkeypatch):
    path = tmp_path / "l.jsonl"
    led = SpendLedger(path)
    real = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (_ for _ in ()).throw(OSError(errno.EIO, "io")))
    with pytest.raises(LedgerWriteError):
        led.reserve(0.3)
    monkeypatch.setattr(os, "fsync", real)
    assert path.stat().st_size == 0
    led.reserve(0.3)
    assert led.total() == pytest.approx(0.3)


def test_a_settle_that_cannot_be_written_stops_the_run_without_charging_twice(tmp_path):
    led = SpendLedger(tmp_path / "l.jsonl")
    guard = SpendGuard(1.0, ledger=led)
    gc = GuardedClient(ScriptedClient(MINI, lambda b: openai_text("ok")), guard,
                       PARSE["openai"])
    real_append = led._append

    def fail_settles(entry):
        if "settle" in entry:
            raise OSError(errno.ENOSPC, "No space left on device")
        real_append(entry)

    led._append = fail_settles
    with pytest.raises(LedgerWriteError):
        gc.post(BODY)
    metered = (1000 * 0.75 + 40 * 4.50) / 1e6
    assert guard.spent == pytest.approx(metered) and guard.unmetered == 0  # not metered twice
    assert led.total() == pytest.approx(call_bound_usd(MINI, BODY) * (1 + SDK_MAX_RETRIES))


# --- repairing a torn tail never rewrites the file ------------------------------------------


def _watch_file_modes(monkeypatch):
    modes, flags, truncated = [], [], []
    real_open, real_os_open, real_truncate = Path.open, os.open, os.truncate

    def open_(self, mode="r", *a, **k):
        modes.append(mode)
        return real_open(self, mode, *a, **k)

    def os_open(path, flag, *a, **k):
        flags.append(flag)
        return real_os_open(path, flag, *a, **k)

    def truncate(path, length):
        truncated.append(length)
        return real_truncate(path, length)

    monkeypatch.setattr(Path, "open", open_)
    monkeypatch.setattr(os, "open", os_open)
    monkeypatch.setattr(os, "truncate", truncate)
    return modes, flags, truncated


def test_an_unparseable_tail_is_cut_with_truncate_never_a_rewrite(tmp_path, monkeypatch):
    path = tmp_path / "l.jsonl"
    good = b'{"id": 0, "reserve": 0.5}\n{"id": 0, "settle": 0.1}\n'
    path.write_bytes(good + b'{"id": 1, "res')
    modes, flags, truncated = _watch_file_modes(monkeypatch)
    led = SpendLedger(path)
    assert path.read_bytes() == good and truncated == [len(good)]
    assert not any("w" in m for m in modes)  # never opened to truncate-and-rewrite
    assert not any(f & os.O_TRUNC for f in flags)
    assert led.total() == pytest.approx(0.1)


def test_a_missing_newline_is_appended_not_rewritten(tmp_path, monkeypatch):
    path = tmp_path / "l.jsonl"
    line = b'{"id": 0, "reserve": 0.5}'
    path.write_bytes(line)
    modes, flags, truncated = _watch_file_modes(monkeypatch)
    led = SpendLedger(path)
    assert path.read_bytes() == line + b"\n" and truncated == []
    assert not any("w" in m for m in modes) and not any(f & os.O_TRUNC for f in flags)
    assert led.total() == pytest.approx(0.5)


def test_a_file_that_is_only_a_torn_line_is_emptied_by_truncate(tmp_path, monkeypatch):
    path = tmp_path / "l.jsonl"
    path.write_bytes(b'{"id": 0, "res')
    _, _, truncated = _watch_file_modes(monkeypatch)
    assert SpendLedger(path).total() == 0.0 and truncated == [0] and path.read_bytes() == b""
