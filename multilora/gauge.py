"""The manipulation check: which adapters the scheduler was running, sampled
from vLLM's `vllm:lora_requests_info` gauge (amendment §3a).

The gauge encodes its state in label values and stamps each update with the
current time as its value. The Prometheus client keeps every label combination
it has ever seen, so a scrape returns many series; the current state is the
one with the newest timestamp. This is a sample of scheduler state at each
scrape, not a count per batch, and is published under that name.
"""

import re

_SERIES = re.compile(r"^vllm:lora_requests_info\{(?P<labels>[^}]*)\}\s+(?P<value>\S+)", re.MULTILINE)
_LABEL = re.compile(r'(\w+)="((?:[^"\\]|\\.)*)"')


def running_adapters(metrics_text: str) -> list[str] | None:
    """Adapters in the newest `running_lora_adapters` label, sorted. None when
    the gauge is absent, as it is with `--disable-log-stats`."""
    newest: tuple[float, str] | None = None
    for m in _SERIES.finditer(metrics_text):
        labels = dict(_LABEL.findall(m.group("labels")))
        value = float(m.group("value"))
        if newest is None or value > newest[0]:
            newest = (value, labels.get("running_lora_adapters", ""))
    if newest is None:
        return None
    return sorted(a for a in newest[1].split(",") if a)


def distinct_running(record, regime: str) -> list[int]:
    """Distinct running adapters at each scrape during `regime`'s phases."""
    phases = {p["phase_index"] for p in record.phases if p["regime"] == regime}
    return [
        len(s["running"])
        for s in record.gauge_samples
        if s["phase_index"] in phases and s["running"] is not None
    ]
