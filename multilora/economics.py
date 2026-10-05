"""Tenants per GPU and cost per tenant per month (amendment §4).

Three bounds on tenants, the smallest wins:

- by slots: the last sweep point below the knee. A lower bound, because vLLM's
  intended multi-tenant mode holds more adapters on the CPU than in slots
  (amendment §3a).
- by throughput: measured request throughput divided by one tenant's peak
  request rate, valid only if TTFT p95 at concurrency C meets the SLO.
- by memory: Little's law on the measured operating point. C concurrent
  requests sustaining request rate r spend W = C / r in the system, so a
  tenant's peak rate p occupies p x W concurrent slots, and the KV ceiling K
  holds K / (p x W) tenants -- which equals by_throughput x K / C.
"""

import math

HOURS_PER_MONTH = 365.0 * 24.0 / 12.0
SECONDS_PER_MONTH = HOURS_PER_MONTH * 3600.0

A4_KEYS = ("gpu_hourly_rate", "reference", "rows")


def tenant_peak_rate(requests_per_tenant_month: float, peak_to_average: float) -> float:
    return requests_per_tenant_month / SECONDS_PER_MONTH * peak_to_average


def tenants_per_gpu(
    *,
    slots_below_knee: int,
    request_rate: float,
    ttft_p95: float,
    max_concurrency: int,
    prereg,
) -> dict:
    peak = tenant_peak_rate(prereg.requests_per_tenant_month, prereg.peak_to_average)
    slo_met = ttft_p95 <= prereg.slo_ttft_p95_s
    if not slo_met:
        return {
            "feasible": False,
            "reason": f"TTFT p95 {ttft_p95:.3f} s exceeds the SLO {prereg.slo_ttft_p95_s} s at C",
            "tenants": None,
        }
    by_throughput = math.floor(request_rate / peak)
    by_memory = math.floor(max_concurrency * request_rate / (prereg.concurrency * peak))
    bounds = {"slots": slots_below_knee, "throughput": by_throughput, "memory": by_memory}
    binding = min(bounds, key=bounds.get)
    return {
        "feasible": True,
        "bounds": bounds,
        "binding": binding,
        "tenants": bounds[binding],
        "tenant_peak_rate": peak,
        "memory_binds": by_memory < by_throughput,
    }


def cost_per_tenant_month(gpu_hourly_rate: float, tenants: int) -> float:
    if tenants <= 0:
        raise ValueError(f"tenants must be positive, got {tenants}")
    return gpu_hourly_rate * HOURS_PER_MONTH / tenants


def a4_reference_row(a4: dict) -> dict:
    """Artifact 4's costs depend on the skew and locality grid point, so its
    results file names a reference point, fixed in its second pre-registration
    step. This returns that point's row, and refuses a file where the reference
    matches no row, several rows, or a row with a strategy not evaluable."""
    missing = [k for k in A4_KEYS if k not in a4]
    if missing:
        raise ValueError(f"artifact 4 results lack {missing}")
    ref = a4["reference"]
    matches = [r for r in a4["rows"] if r["regime"] == ref["regime"] and r["s"] == ref["s"]]
    if len(matches) != 1:
        raise ValueError(f"artifact 4's reference {ref} matches {len(matches)} rows, not 1")
    row = matches[0]
    for key in ("dedicated_cost_per_tenant_month", "swapped_cost_per_tenant_month"):
        if row.get(key) is None:
            raise ValueError(f"artifact 4's reference row has no {key}")
    return row


def three_way_table(adapter_tenants: int, prereg, a4: dict) -> list[dict]:
    """Artifact 4's columns are consumed as committed data, never recomputed,
    and must share this artifact's GPU hourly rate. A sleep-mode column is
    included when artifact 4 measured one."""
    row = a4_reference_row(a4)
    if not math.isclose(a4["gpu_hourly_rate"], prereg.gpu_hourly_rate):
        raise ValueError(
            f"artifact 4 used ${a4['gpu_hourly_rate']}/h and this pre-registration "
            f"${prereg.gpu_hourly_rate}/h; the three columns must share one rate"
        )
    source = f"artifact 4, {row['regime']} regime, s = {row['s']}"
    table = [
        {"strategy": "dedicated", "cost": row["dedicated_cost_per_tenant_month"], "source": source},
        {"strategy": "swapped", "cost": row["swapped_cost_per_tenant_month"], "source": source},
    ]
    if row.get("sleep_mode_cost_per_tenant_month") is not None:
        table.append(
            {"strategy": "sleep mode", "cost": row["sleep_mode_cost_per_tenant_month"], "source": source}
        )
    table.append(
        {
            "strategy": "adapter",
            "cost": cost_per_tenant_month(prereg.gpu_hourly_rate, adapter_tenants),
            "source": "artifact 5",
            "upper_bound": True,
        }
    )
    return table
