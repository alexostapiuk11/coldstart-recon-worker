"""Tabulate artifact 2's reconnaissance captures -- evidence, not verdicts.

One row per job: which worker ran it, how long the platform delayed it, how
long it executed, what the engine log says about compilation and weights, and
the KV capacity it reported. The Q1/Q2 verdicts are written into
docs/recon-a2.md by a person reading this table beside capture.jsonl. The rules
for calling a start "warm-host" are exactly what the capture is meant to inform,
so encoding them here in advance would decide the answer before seeing the data.

Unlike capture_a2.py this is not a frozen reproduction tool, so it imports
artifact 1's log parser and payload accessors instead of re-deriving them: a
second parser for the same log format is a second answer waiting to diverge.

A burst that ran out of its polling deadline before every job finished leaves
one `<label>.timeout.json` per unfinished job -- its last non-terminal status,
verbatim -- and `load()`'s glob matches it too, because `*` matches `.`. Such a
row is kept, not dropped: dropping it would make an aborted capture look like
a smaller clean one, the same reasoning already applied to a FAILED row.
`render_table` says how many rows timed out, so no reader mistakes a table
from an aborted burst for one from a completed run.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coldstart.runpod_api import extract_lifecycle, extract_worker_id
from coldstart.vllm_logs import parse_engine_log

# Present only when weights were NOT already on disk (fixtures/README.md,
# parser hazard 1), so its presence distinguishes a host that had to fetch.
WEIGHTS_DOWNLOAD = re.compile(r"Time spent downloading weights", re.IGNORECASE)

COLUMNS = ("label", "status", "worker_id", "delay_ms", "execution_ms",
           "compile_s", "weights_downloaded", "kv_tokens")


def job_row(label: str, status: dict) -> dict:
    lifecycle = extract_lifecycle(status)
    lines = (status.get("output") or {}).get("log_lines") or []
    text = "\n".join(lines)
    parsed = parse_engine_log(text) if lines else None
    return {
        "label": label,
        "status": status.get("status"),
        "worker_id": extract_worker_id(status),
        "delay_ms": lifecycle.get("delay_ms"),
        "execution_ms": lifecycle.get("execution_ms"),
        "compile_s": parsed.phases.get("S4b") if parsed else None,
        "weights_downloaded": bool(WEIGHTS_DOWNLOAD.search(text)) if lines else None,
        "kv_tokens": parsed.engine_info.get("kv_capacity_tokens") if parsed else None,
    }


def load(directory: Path, pattern: str) -> list[dict]:
    paths = sorted(Path(directory).glob(pattern))
    if not paths:
        raise ValueError(
            f"no job payloads match {pattern!r} in {directory}; an empty table "
            "would read as a capture in which nothing happened"
        )
    # A timeout file's payload has no "output" and a non-terminal "status", so
    # job_row already reports it as a row of absences with that status --
    # nothing here special-cases the name beyond the label, which is exactly
    # `p.stem` (e.g. "burst1_0.timeout") for both kinds of file.
    return [job_row(p.stem, json.loads(p.read_text())) for p in paths]


def _timed_out(row: dict) -> bool:
    # The one place a row's provenance (not its status field) matters: RunPod's
    # non-terminal statuses (IN_QUEUE, IN_PROGRESS, ...) are not a fixed set
    # this module should have to enumerate, but capture_a2.py's own naming is
    # -- it never writes "<label>.timeout.json" for a terminal result.
    return row["label"].endswith(".timeout")


def distinct_workers(rows: list[dict]) -> int:
    # A timed-out row's worker_id counts too: a worker that picked up the job
    # before the deadline is real evidence of a worker, even though the job
    # itself never finished.
    return len({r["worker_id"] for r in rows if r["worker_id"]})


def render_table(rows: list[dict]) -> str:
    def cell(v):
        return "—" if v is None else str(v)

    head = "| " + " | ".join(COLUMNS) + " |"
    rule = "|" + "---|" * len(COLUMNS)
    body = ["| " + " | ".join(cell(r[c]) for c in COLUMNS) + " |" for r in rows]
    lines = [head, rule, *body, "", f"distinct workers: {distinct_workers(rows)}"]
    timed_out = sum(1 for r in rows if _timed_out(r))
    if timed_out:
        lines.append(f"timed out (capture aborted after this burst): {timed_out}")
    return "\n".join(lines)


def main(argv: list[str]) -> None:
    directory = Path(argv[0]) if argv else Path("fixtures") / "a2_recon"
    print(render_table(load(directory, "burst*.json")))


if __name__ == "__main__":
    main(sys.argv[1:])
