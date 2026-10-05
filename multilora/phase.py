"""Amendment §3f's rules for reading one phase of `vllm bench serve` output,
and the per-instance summaries every estimand is built from.

A request is a failure if its error string is non-empty, OR its TTFT is 0.0,
OR its output length is 0. vLLM 0.27.1 records some failures with an empty
error string and saves no per-request success flag, so the error field alone
undercounts. The tool's own completed/failed counts are the cross-check: a
phase whose counts disagree with this rule is not trusted at all.
"""

from harness.stats import percentiles


class PhaseCountMismatch(ValueError):
    """The failure rule and the tool's own counts disagree for a phase."""


def is_failure(ttft: float, output_len: int, error: str) -> bool:
    return bool(error) or ttft == 0.0 or output_len == 0


def successful(phase: dict) -> tuple[list[float], list[int]]:
    ttfts, lens, errors = phase["ttfts"], phase["output_lens"], phase["errors"]
    if not (len(ttfts) == len(lens) == len(errors)):
        raise ValueError(
            f"phase {phase.get('phase_index')}: per-request arrays differ in length "
            f"({len(ttfts)}, {len(lens)}, {len(errors)})"
        )
    ok = [i for i in range(len(ttfts)) if not is_failure(ttfts[i], lens[i], errors[i])]
    return [ttfts[i] for i in ok], [lens[i] for i in ok]


def check_counts(phase: dict) -> None:
    ok_ttfts, _ = successful(phase)
    n_ok = len(ok_ttfts)
    n_failed = len(phase["ttfts"]) - n_ok
    if (n_ok, n_failed) != (phase["completed"], phase["failed"]):
        raise PhaseCountMismatch(
            f"phase {phase.get('phase_index')}: the failure rule finds {n_ok} ok and "
            f"{n_failed} failed, the tool reports {phase['completed']} completed and "
            f"{phase['failed']} failed"
        )


def summarize(phases: list[dict]) -> dict:
    """TTFT percentiles over the successful requests of `phases`, and
    throughput as total successful output tokens over total phase duration."""
    if not phases:
        raise ValueError("no phases to summarize")
    ttfts: list[float] = []
    tokens = 0
    n_ok = 0
    n_total = 0
    duration = 0.0
    for phase in phases:
        ok_ttfts, ok_lens = successful(phase)
        ttfts += ok_ttfts
        tokens += sum(ok_lens)
        n_ok += len(ok_ttfts)
        n_total += len(phase["ttfts"])
        duration += phase["duration_s"]
    if duration <= 0:
        raise ValueError("phase duration must be positive")
    pct = percentiles(ttfts, want=("p50", "p95"))
    return {
        "ttft_p50": pct["p50"],
        "ttft_p95": pct["p95"],
        "throughput_tps": tokens / duration,
        "request_rate": n_ok / duration,
        "n_ok": n_ok,
        "n_failed": n_total - n_ok,
    }


def regime_summary(record, regime: str) -> dict:
    return summarize([p for p in record.phases if p["regime"] == regime])


def phase_summaries(record, regime: str) -> list[dict]:
    """One summary per phase of `regime`, in phase order. The gate's resolution
    check compares a regime's first phase with its second (amendment §4)."""
    phases = sorted(
        (p for p in record.phases if p["regime"] == regime), key=lambda p: p["phase_index"]
    )
    return [summarize([p]) for p in phases]
