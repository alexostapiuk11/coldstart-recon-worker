"""The knee (amendment §4).

m(N) = 1 - T(N) / T(N/2), with T the spread regime's throughput. The knee is
the smallest N whose POINT estimate of m(N) exceeds tau, reported as the
interval (N/2, N] because the sweep resolves only doublings.

Point estimate, not significance: requiring the interval to clear tau would
miss a real but noisy drop and push the knee -- and tenants per GPU -- upward.
Whether each crossing is also resolved (its interval's lower bound above tau)
is reported beside it, descriptively, without a multiplicity correction.
"""

from harness.stats import bootstrap_function_of_medians


def knee(throughput_by_n: dict[int, list[float]], tau: float, iterations=10000, seed=0) -> dict:
    ns = sorted(throughput_by_n)
    for n in ns[1:]:
        if n // 2 not in throughput_by_n or n % 2:
            raise ValueError(f"sweep point {n} has no half-point; the knee needs doublings")
    doublings = []
    knee_upper = None
    for n in ns[1:]:
        res = bootstrap_function_of_medians(
            [throughput_by_n[n], throughput_by_n[n // 2]],
            lambda m: 1 - m[0] / m[1],
            iterations=iterations,
            seed=seed,
        )
        crosses = res["point"] > tau
        doublings.append(
            {"n": n, **res, "crosses": crosses, "resolved": crosses and res["lo"] > tau}
        )
        if crosses and knee_upper is None:
            knee_upper = n
    return {
        "tau": tau,
        "doublings": doublings,
        "knee": None if knee_upper is None else {"lower": knee_upper // 2, "upper": knee_upper},
        "slots_below_knee": ns[-1] if knee_upper is None else knee_upper // 2,
        "above_top": knee_upper is None,
    }
