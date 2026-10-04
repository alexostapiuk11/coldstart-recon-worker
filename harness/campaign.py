"""The campaign loop every measurement artifact shares: schedule -> submit ->
record -> store, with a resume guard.

Lifted from artifact 1's `coldstart/driver.run_campaign`. What an artifact
submits and what record it builds are its own business, so both arrive as
callables; what is worth sharing is the discipline around them:

- One record per scheduled run, appended as it lands. Never retried in place:
  a retry would hide a failure the failure-rate table has to count.
- `resume=True` skips runs already in the store, keyed by `run_index`, and
  first checks that every stored record agrees with the rebuilt schedule. A
  resumed window called with a drifted seed or block count would otherwise
  splice two interleavings into one store -- the confound interleaving exists
  to prevent -- and nothing downstream could tell.

The drift guard assumes the store holds only this campaign's records. Give
each campaign its own store file.
"""

import uuid
from collections.abc import Callable, Iterable


def new_run_id() -> str:
    """Generated before the job is submitted: artifacts namespace per-run
    paths by it, so it must exist before the worker runs. A uuid4 hex string
    contains no "/"."""
    return uuid.uuid4().hex


def check_resume(
    schedule: list,
    stored: Iterable,
    index_of: Callable[[object], int],
    condition_of: Callable[[object], str],
) -> set[int]:
    """Return the run indices already done, refusing a store that disagrees
    with `schedule`."""
    expected = {s.run_index: s.condition for s in schedule}
    done: set[int] = set()
    for record in stored:
        index = index_of(record)
        want = expected.get(index)
        if want is None:
            raise ValueError(
                f"resume: stored run_index {index} falls beyond the rebuilt "
                f"schedule, which only covers 0..{len(schedule) - 1}. Resume "
                "was called with different schedule parameters than produced "
                "the stored data -- it must use the exact ones of the original "
                "window."
            )
        have = condition_of(record)
        if have != want:
            raise ValueError(
                f"resume: stored run_index {index} has condition {have!r} on "
                f"disk, but the rebuilt schedule assigns it {want!r}. Resume "
                "was called with different schedule parameters than produced "
                "the stored data, which would splice two interleavings together "
                "-- it must use the exact ones of the original window."
            )
        done.add(index)
    return done


def run_campaign(
    schedule: list,
    submit: Callable,
    build_record: Callable,
    store,
    *,
    index_of: Callable[[object], int],
    condition_of: Callable[[object], str],
    make_run_id: Callable[[], str] = new_run_id,
    on_run: Callable | None = None,
    resume: bool = False,
):
    """Run every scheduled item not already stored.

    `submit(scheduled, run_id)` returns a `harness.submit.SubmitOutcome`.
    `build_record(scheduled, run_id, outcome)` returns the artifact's record,
    which `store.append` persists. `index_of` and `condition_of` read a stored
    record's run index and condition for the resume guard.

    `resume` is off by default: silently skipping runs an operator asked for is
    a worse failure than repeating them.
    """
    done = check_resume(schedule, store.read_all(), index_of, condition_of) if resume else set()
    for scheduled in schedule:
        if scheduled.run_index in done:
            continue
        run_id = make_run_id()
        outcome = submit(scheduled, run_id)
        record = build_record(scheduled, run_id, outcome)
        store.append(record)
        if on_run:
            on_run(record)
    return store
