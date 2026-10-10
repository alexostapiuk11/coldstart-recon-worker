"""The spend guard (amendment §7).

The portfolio rule: no paid call without the author's explicit yes, stating the
number of calls and the estimated cost. A paid script therefore takes an
`--approved-usd` amount and does three things with it:

1. Before anything runs, it refuses if its own estimate exceeds the amount
   (`check_estimate`).
2. Before every call, it refuses if that call's upper bound could take total
   spend past the amount (`SpendGuard.before`).
3. After every call, it adds that call's metered cost from the response.

The per-call bound (`call_bound_usd`) is an upper bound, not an estimate: the
output can never exceed `max_output_tokens`, and the input is counted at two
characters of request JSON per token, where the providers' tokenizers average
three to four on this text. Plan 2 checks that assumption against the pilot's
recorded usage (`bound_held`). A bound rather than the largest call seen so far,
because a call larger than any before it would otherwise cross the cap.

Metering is only as good as the response in hand, so the guard charges what it
cannot meter rather than assuming it was free:

- A post that raises may or may not have been billed, and the SDKs retry
  transport failures internally (`SDK_MAX_RETRIES`, each retry a separate
  provider call). The guard therefore checks the cap against the call's bound
  times `1 + SDK_MAX_RETRIES`, and charges that worst case when the post raises.
- A response with no usable usage, or one the parser cannot read, is charged the
  bound for one attempt.
- A call that succeeds after internal retries is metered at its own usage only.
  Billed retries that left no response are invisible to the guard. The spend
  record's billed-versus-metered comparison (amendment §8) is what catches them,
  which is why that comparison is a gate and not a courtesy.

The spend ledger (`SpendLedger`) makes that guarantee durable. Paid turns that
never reach a store (a conversation cut off by the cap, a crash between the post
and the store write, a metering failure) are invisible to anything rebuilt from
the stores, so a resume would redo and re-pay them without bound. The ledger is
written ahead of the call: `reserve` records the worst case and is fsynced
BEFORE the post, `settle` records what the guard charged. A reservation with no
settle, which is what a crash leaves, counts at its worst case.

`SpendCapReached` deliberately is not caught by the campaign's error handling:
it stops the run, and the records already stored stay stored. `SpendGuardError`
subclasses it, so a guard-internal failure (a model with no pinned price, usage
the price table cannot cost) stops the run the same way instead of being
recorded as a provider error and quietly skipping the meter.
"""

import fcntl
import json
import math
import os
from pathlib import Path

from toolcall.prices import PRICES, cost_usd

CHARS_PER_TOKEN_BOUND = 2.0
TOKENIZER_FACTOR = {"openai": 1.0, "anthropic": 1.3}  # amendment §8
# Providers add hidden tool-use prompt tokens and render the schemas internally,
# so the request JSON alone undercounts the input; this fixed allowance covers it.
INPUT_OVERHEAD_TOKENS = 500
# The SDKs' default internal transport retries; each one is a separate provider
# call. Client.post sets it explicitly so the bound below does not depend on a
# default the SDKs may change.
SDK_MAX_RETRIES = 2


class SpendCapReached(RuntimeError):
    pass


class SpendGuardError(SpendCapReached):
    """The guard itself failed (unpriced model, usage it cannot cost)."""


class LedgerWriteError(SpendGuardError):
    """The spend ledger could not be written or locked. It stops the run: an
    OSError is not SpendCapReached, so left alone the campaign would record it
    as an API_ERROR row and carry on spending with nothing written ahead."""


def _require_finite_positive(amount: float, what: str) -> None:
    # NaN compares false with everything, so `spent + bound > NaN` would never
    # trip and a NaN or infinite amount would silently disable the cap.
    if not math.isfinite(amount) or amount <= 0:
        raise SpendCapReached(f"{what} must be a finite positive amount, got {amount!r}")


def input_tokens_bound(settings, body: dict) -> float:
    return (len(json.dumps(body)) / CHARS_PER_TOKEN_BOUND * TOKENIZER_FACTOR[settings.provider]
            + INPUT_OVERHEAD_TOKENS)


def call_bound_usd(settings, body: dict) -> float:
    try:
        p = PRICES[settings.model]
    except KeyError:
        raise SpendGuardError(
            f"no pinned price for {settings.model!r}; add it with its source first") from None
    # A cache write costs more than a plain input token, and the bound cannot
    # know which tokens a provider will cache, so the dearer price is used.
    return (input_tokens_bound(settings, body) * max(p.input, p.cache_write)
            + settings.max_output_tokens * p.output) / 1e6


def bound_held(settings, body: dict, usage: dict) -> bool:
    return usage["input"] <= input_tokens_bound(settings, body)


def check_estimate(estimate_usd: float, approved_usd: float) -> None:
    _require_finite_positive(approved_usd, "the approved amount (--approved-usd)")
    if not math.isfinite(estimate_usd):
        raise SpendCapReached(f"the estimate is not finite ({estimate_usd!r}); fix it first")
    if estimate_usd > approved_usd:
        raise SpendCapReached(
            f"estimated ${estimate_usd:.2f} exceeds the approved ${approved_usd:.2f}; "
            "ask the author for a new approval rather than raising the number"
        )


class SpendLedger:
    """An append-only JSONL file of reservations and settlements, one fsynced
    line per event, so a resumed phase can see every paid call ever started.

    `reserve(usd)` writes `{"id", "reserve"}` before a post; `settle(id, usd)`
    writes `{"id", "settle"}` once the guard knows what the call was charged.
    `total()` is the settled amounts plus the reserved amount of every
    reservation never settled: a crash is counted at its worst case.

    A line torn by a crash mid-write can only be the last one. If it still
    parses it is read as written; if not it is cut off when the ledger is
    opened (`os.truncate`, never a rewrite of the file). That is safe both ways:
    a reserve is fsynced before its post starts, so a torn reserve means no post
    was made, and a torn settle leaves its reserve unsettled, which counts at
    worst. A malformed line anywhere else is a damaged ledger and raises.

    One writer at a time: opening a ledger takes an exclusive, non-blocking
    `flock` on `<ledger>.lock` (`x.spend.jsonl` -> `x.spend.lock`) and holds it
    until `close()`. Two runs seeding from the same total could together spend
    twice the approval, and would collide on reservation ids. The flock is per
    open file description, so a second open in the same process is refused the
    same way as one from another process, and the lock dies with its process.
    The runner holds the ledger, so the lock covers a paid phase from before it
    reads the seed until it ends.

    A write that fails (disk full, I/O error) is rolled back to the file's size
    before the write and raised as `LedgerWriteError`, so no partial line is ever
    left for the next append to land after."""

    def __init__(self, path, label: str | None = None):
        self.path = Path(path)
        self.lock_path = self.path.with_suffix(".lock")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = self.lock_path.open("a")
        try:
            try:
                fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as e:
                raise LedgerWriteError(
                    f"another run of {label or self.path.name} holds {self.lock_path}; two "
                    "runs on one spend ledger could each spend the whole approval") from e
            except OSError as e:
                raise LedgerWriteError(f"cannot lock {self.lock_path}: {e}") from e
            self._drop_torn_tail()
            reserved, settled = self._scan()
        except BaseException:
            self.close()
            raise
        self._next_id = max(reserved, default=-1) + 1
        self._open = {i for i in reserved if i not in settled}

    def close(self) -> None:
        """Release the lock. Safe to call twice."""
        if not self._lock.closed:
            self._lock.close()  # closing the descriptor releases the flock

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _drop_torn_tail(self) -> None:
        if not self.path.exists():
            return
        data = self.path.read_bytes()
        if not data or data.endswith(b"\n"):
            return
        head, _, tail = data.rpartition(b"\n")
        try:
            json.loads(tail)
        except ValueError:
            # Cut the torn bytes off in place: a crash here loses at most them.
            os.truncate(self.path, len(head) + 1 if head else 0)
            self._fsync_path(os.O_WRONLY)
            return
        with self.path.open("ab") as f:  # a whole line that lost only its newline
            f.write(b"\n")
            f.flush()
            os.fsync(f.fileno())

    def _fsync_path(self, flags: int) -> None:
        fd = os.open(self.path, flags)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    @staticmethod
    def _amount(value, where: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)) \
                or not math.isfinite(value) or value < 0:
            raise ValueError(f"{where}: amount must be a finite number >= 0, got {value!r}")
        return float(value)

    def _scan(self) -> tuple[dict, dict]:
        reserved: dict[int, float] = {}
        settled: dict[int, float] = {}
        if not self.path.exists():
            return reserved, settled
        for lineno, line in enumerate(self.path.read_text().splitlines(), start=1):
            where = f"{self.path}: line {lineno}"
            try:
                entry = json.loads(line)
                rid = entry["id"]
                if isinstance(rid, bool) or not isinstance(rid, int):
                    raise ValueError("id must be an int")  # noqa: TRY004 -- caught below
                if set(entry) == {"id", "reserve"}:
                    if rid in reserved:
                        raise ValueError(f"reservation {rid} is written twice")
                    reserved[rid] = self._amount(entry["reserve"], where)
                elif set(entry) == {"id", "settle"}:
                    if rid not in reserved or rid in settled:
                        raise ValueError(f"settle for reservation {rid} with no open reservation")
                    settled[rid] = self._amount(entry["settle"], where)
                else:
                    raise ValueError(f"unexpected fields {sorted(entry)}")
            except (ValueError, KeyError, TypeError) as e:
                raise ValueError(f"{where} is not a ledger entry ({e}); the spend ledger is "
                                 "damaged and the phase's spend cannot be trusted") from e
        return reserved, settled

    def _append(self, entry: dict) -> None:
        created = not self.path.exists()
        size = 0 if created else self.path.stat().st_size
        try:
            with self.path.open("ab") as f:
                f.write((json.dumps(entry, sort_keys=True) + "\n").encode())
                f.flush()
                os.fsync(f.fileno())
            if created:
                # The new file's directory entry is durable only once its directory
                # is fsynced; otherwise a power loss right after the first reserve
                # could drop the whole file, and the spend with it.
                fd = os.open(self.path.parent, os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
        except OSError:
            try:  # leave no partial line behind for the next append to land after
                os.truncate(self.path, size)
            except OSError:
                pass  # the next open cuts an unparseable tail; this error is the one to raise
            raise

    def _write(self, entry: dict) -> None:
        try:
            self._append(entry)
        except OSError as e:
            raise LedgerWriteError(
                f"cannot write the spend ledger {self.path}: {e}; stopping, because a call "
                "made now would be paid for with nothing recorded") from e

    def reserve(self, usd: float) -> int:
        self._amount(usd, "reserve")
        rid = self._next_id
        self._write({"id": rid, "reserve": usd})
        self._next_id += 1
        self._open.add(rid)
        return rid

    def settle(self, rid: int, usd: float) -> None:
        self._amount(usd, "settle")
        if rid not in self._open:
            raise ValueError(f"no open reservation {rid} to settle")
        self._write({"id": rid, "settle": usd})
        self._open.discard(rid)

    def total(self) -> float:
        reserved, settled = self._scan()
        return sum(settled.values()) + sum(v for i, v in reserved.items() if i not in settled)


class SpendGuard:
    def __init__(self, approved_usd: float, spent: float = 0.0,
                 ledger: "SpendLedger | None" = None):
        """`spent` seeds a resumed phase with what it already cost, so the approved
        amount caps the whole phase across resumes. With a `ledger`, every call
        the guard lets through is reserved at its worst case before the post and
        settled with what the guard charged."""
        _require_finite_positive(approved_usd, "the approved amount")
        if isinstance(spent, bool) or not math.isfinite(spent) or spent < 0:
            raise SpendCapReached(f"the seed spend must be a finite amount >= 0, got {spent!r}")
        self.approved = approved_usd
        self.spent = spent
        self.calls = 0
        self.unmetered = 0  # calls charged at a bound because usage was unavailable
        self.ledger = ledger
        self._reservation: int | None = None
        self._in_flight = False

    def before(self, bound_usd: float) -> None:
        if self.spent + bound_usd > self.approved:
            raise SpendCapReached(
                f"stopping: ${self.spent:.4f} spent over {self.calls} calls, and the next "
                f"(up to ${bound_usd:.4f}) could exceed the approved ${self.approved:.2f}"
            )

    def reserve(self, worst_usd: float) -> None:
        """Open the in-flight call: write its worst case to the ledger first."""
        if self.ledger is not None:
            self._reservation = self.ledger.reserve(worst_usd)
        self._in_flight = True

    def _settle(self, usd: float) -> None:
        self._in_flight = False
        rid, self._reservation = self._reservation, None
        if rid is not None:
            self.ledger.settle(rid, usd)

    def release(self) -> None:
        """Close the in-flight call with no charge (an inner guard already charged it)."""
        self._settle(0.0)

    def add(self, model: str, usage: dict) -> float:
        try:
            cost = cost_usd(model, usage)
        except (KeyError, ValueError) as e:
            raise SpendGuardError(f"cannot meter this call: {e}") from e
        self.spent += cost
        self.calls += 1
        self._settle(cost)
        return cost

    def charge_unmetered(self, usd: float) -> None:
        """Charge a call whose cost is unknown at the amount it could have cost."""
        self.spent += usd
        self.calls += 1
        self.unmetered += 1
        self._settle(usd)

    def charge_if_in_flight(self, usd: float) -> None:
        """Whatever left the call open (a crash, an interrupt) is charged `usd`."""
        if self._in_flight:
            self.charge_unmetered(usd)


class GuardedClient:
    """Wraps a client so every post passes through the guard. Same interface."""

    def __init__(self, client, guard: SpendGuard, parse):
        self.client = client
        self.settings = client.settings
        self.guard = guard
        self._parse = parse

    def request(self, tools, transcript):
        return self.client.request(tools, transcript)

    def post(self, body):
        bound = call_bound_usd(self.settings, body)
        worst = bound * (1 + SDK_MAX_RETRIES)
        self.guard.before(worst)
        self.guard.reserve(worst)
        try:
            return self._post_reserved(body, bound, worst)
        finally:
            # Every branch settles; this is for what none of them caught (a
            # KeyboardInterrupt, an error in metering): the worst case, once.
            self.guard.charge_if_in_flight(worst)

    def _post_reserved(self, body, bound, worst):
        try:
            response = self.client.post(body)
        except SpendCapReached:
            self.guard.release()
            raise
        except Exception:
            # Unknown whether it was billed, and the SDK may have retried:
            # assume the worst rather than $0.
            self.guard.charge_unmetered(worst)
            raise
        try:
            usage = self._parse(response).usage
        except Exception:  # noqa: BLE001 -- an unreadable response was still billed
            self.guard.charge_unmetered(bound)
            return response
        if usage["input"] == 0 and usage["output"] == 0:
            self.guard.charge_unmetered(bound)
            return response
        try:
            self.guard.add(self.settings.model, usage)
        except LedgerWriteError:
            raise  # metered and counted; only the ledger line failed, and the run stops
        except SpendGuardError:
            self.guard.charge_unmetered(bound)
            raise
        return response

    def send(self, tools, transcript):
        body = self.request(tools, transcript)
        return body, self.post(body)
