"""Tabulate artifact 2's reconnaissance captures -- evidence, not verdicts.

One row per job: which worker ran it, how long the platform delayed it, how
long it executed, whether the engine reported itself healthy, what the engine
log says about compilation and weights, and the KV capacity it reported. The
Q1/Q2 verdicts are written into docs/recon-a2.md by a person reading this
table beside capture.jsonl. The rules for calling a start "warm-host" are
exactly what the capture is meant to inform, so encoding them here in advance
would decide the answer before seeing the data.

Unlike capture_a2.py this is not a frozen reproduction tool, so it imports
artifact 1's log parser and payload accessors instead of re-deriving them: a
second parser for the same log format is a second answer waiting to diverge.

A burst that ran out of its polling deadline before every job finished leaves
one `<label>.timeout.json` per unfinished job -- its last non-terminal status,
verbatim -- and `load()`'s glob matches it too, because `*` matches `.`. Such a
row is kept, not dropped: dropping it would make an aborted capture look like
a smaller clean one, the same reasoning already applied to a FAILED row.
`render_table` says how many rows timed out, so no reader mistakes a table
from an aborted burst for one from a completed run. A timeout row whose last
status was IN_PROGRESS may carry a running `executionTime` already -- whether
RunPod reports that field before a job ends is not verified here, so it is
read the same as any other row's and left for a person to judge against the
status next to it.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.runpod.api import extract_lifecycle, extract_worker_id
from harness.vllm_logs import parse_engine_log

# Present only when weights were NOT already on disk (fixtures/README.md,
# parser hazard 1), so its presence distinguishes a host that had to fetch.
#
# Lives here rather than in harness.vllm_logs: that module is artifact 1's
# frozen parser for the S4 sub-phases (fixtures/vllm_logs/, per its own
# docstring), and this line is outside what it was written to parse -- it is
# not a duration, and artifact 1 never needed to know whether weights came
# from disk or the network. Adding it there would mean touching a module
# whose whole point is being pinned to one committed log format.
WEIGHTS_DOWNLOAD = re.compile(r"Time spent downloading weights", re.IGNORECASE)

# Weight loading's completion line (fixtures/README.md, Q1, S4a). Its absence
# means the log ended before weight loading finished -- OOM, a truncated
# drain, a health-poll timeout mid-load -- and WEIGHTS_DOWNLOAD's absence in
# that case says nothing about where the weights came from.
WEIGHTS_LOADED = re.compile(r"Loading weights took", re.IGNORECASE)

COLUMNS = ("label", "status", "healthy", "worker_id", "delay_ms", "execution_ms",
           "compile_s", "weights_downloaded", "kv_tokens")

# Anchored to the repository, like capture_a2.OUT: this script is meant to be
# run from anywhere, and a relative default would silently read (or print) an
# empty table from the current directory instead of the fixtures the capture
# actually wrote.
DEFAULT_CAPTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "a2_recon"


def _weights_downloaded(text: str) -> bool | None:
    """Whether the engine found weights already on disk, or had to fetch them.

    Three states, not two, because a bool cannot say "the log never got far
    enough to know" without lying in one direction or the other: reporting
    False for a log that died mid-load would claim "found on disk" about a
    run that never reached that point, and reporting True would claim the
    opposite with just as little basis. None is the honest answer to a
    question the log itself never answered.
    """
    if not WEIGHTS_LOADED.search(text):
        return None
    return bool(WEIGHTS_DOWNLOAD.search(text))


def job_row(label: str, status: dict) -> dict:
    """One table row from one job's `/status` payload (or timeout snapshot).

    `output` is the only field besides `status`/`id` this trusts to be
    anything but a plain scalar -- log_lines and healthy both come out of it
    -- so a payload where it is present but not an object (or null) is
    refused outright rather than read partway and silently turned into a row
    of absences that looks like a job which ran and reported nothing.
    """
    output = status.get("output")
    if output is not None and not isinstance(output, dict):
        raise ValueError(
            f"'output' is a {type(output).__name__}, not an object or null; "
            "every field this row reads beyond status/id comes out of it, and "
            "reading past this point would either crash on an unrelated line "
            "or silently report a row of absences indistinguishable from a "
            "job that ran and said nothing"
        )
    output = output or {}
    lifecycle = extract_lifecycle(status)
    lines = output.get("log_lines") or []
    text = "\n".join(lines)
    parsed = parse_engine_log(text) if lines else None
    return {
        "label": label,
        "status": status.get("status"),
        "healthy": output.get("healthy"),
        "worker_id": extract_worker_id(status),
        "delay_ms": lifecycle.get("delay_ms"),
        "execution_ms": lifecycle.get("execution_ms"),
        "compile_s": parsed.phases.get("S4b") if parsed else None,
        "weights_downloaded": _weights_downloaded(text) if lines else None,
        "kv_tokens": parsed.engine_info.get("kv_capacity_tokens") if parsed else None,
    }


def _sort_key(path: Path):
    """Order job files by (prefix, numeric index), not by path string.

    `sorted()` on the paths themselves compares "10" against "2" character by
    character -- '1' < '2' -- so `burst1_10.json` would land between
    `burst1_1.json` and `burst1_2.json` instead of after both, reordering a
    burst's own jobs as soon as it grows past ten. A stem this shape does not
    match sorts after every one that does, in its own lexicographic order,
    rather than crashing on a name this capture format was not built to
    produce.
    """
    m = re.match(r"^(?P<prefix>.+)_(?P<index>\d+)(?P<suffix>\.timeout)?$", path.stem)
    if not m:
        return (1, path.stem, 0, "")
    return (0, m.group("prefix"), int(m.group("index")), m.group("suffix") or "")


def load(directory: Path, pattern: str) -> list[dict]:
    """Read every job payload matching `pattern` in `directory` into a row.

    Raises rather than returning an empty table for an empty match: an empty
    table reads as a capture in which nothing happened, not as a wrong
    pattern or directory. A `job_row` failure is re-raised with the actual
    file path attached -- the operator reading the error has the directory on
    disk, not the label a row would otherwise carry alone.
    """
    paths = sorted(Path(directory).glob(pattern), key=_sort_key)
    if not paths:
        raise ValueError(
            f"no job payloads match {pattern!r} in {directory}; an empty table "
            "would read as a capture in which nothing happened"
        )
    rows = []
    for p in paths:
        try:
            rows.append(job_row(p.stem, json.loads(p.read_text())))
        except ValueError as e:
            raise ValueError(f"{p}: {e}") from e
    return rows


def distinct_workers(rows: list[dict]) -> int:
    """Q2's headline count: how many distinct `worker_id` values were seen.

    A timed-out row's worker_id counts too: a worker that picked up the job
    before the deadline is real evidence of a worker, even though the job
    itself never finished. `None` (no worker reported at all, e.g. a FAILED
    row that never started) is filtered out -- it is an absence, not a worker.
    """
    return len({r["worker_id"] for r in rows if r["worker_id"]})


def render_table(rows: list[dict]) -> str:
    """Render `rows` as a Markdown table, one line per row plus two summaries.

    A missing value prints as "—", never the string "None": a reader scanning
    the table for gaps should not have to distinguish the two. The timeout
    line appears only when at least one row timed out (see the module
    docstring), so a table from a clean, complete capture says nothing extra.
    """
    def cell(v):
        return "—" if v is None else str(v)

    head = "| " + " | ".join(COLUMNS) + " |"
    rule = "|" + "---|" * len(COLUMNS)
    body = ["| " + " | ".join(cell(r[c]) for c in COLUMNS) + " |" for r in rows]
    lines = [head, rule, *body, "", f"distinct workers: {distinct_workers(rows)}"]
    timed_out = sum(1 for r in rows if r["label"].endswith(".timeout"))
    if timed_out:
        lines.append(f"timed out (capture aborted after this burst): {timed_out}")
    return "\n".join(lines)


def main(argv: list[str]) -> None:
    directory = Path(argv[0]) if argv else DEFAULT_CAPTURE_DIR
    print(render_table(load(directory, "burst*.json")))


if __name__ == "__main__":
    main(sys.argv[1:])
