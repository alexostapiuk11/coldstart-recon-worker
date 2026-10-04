"""Artifact 1's publishability presets: what each of its analyses requires.

Each is a `required` tuple `harness.publish.partition()` already knows how to
interpret. They live here rather than in the harness because they name artifact
1's fields -- `t_weights`, `t_compile`, `t_fast_seconds` -- and because the
rulings recorded in their docstrings are about artifact 1's clock checks
specifically. A second artifact writes its own presets against the same
`partition()`.

Read the block comment below before adding a preset: consistency is the floor
every one of them stands on, and that was settled twice already.
"""

# Presets for the analyses this plan actually builds. Each is just a `required`
# tuple `partition()` already knows how to interpret — these exist so a call site
# reads "what this analysis needs" rather than a bare tuple literal, and so the four
# figures / the T_weights contrast can't quietly drift from each other on what they
# require.
#
# CONSISTENCY IS THE SHARED FLOOR EVERY PRESET STANDS ON, NOT ONE AXIS AMONG
# SEVERAL. Spec 6.5 rule 3 is unconditional: "Every run gets a consistency
# check ... Violations are discarded ... never silently" (and spec 6, line
# 484: "discard inconsistent runs for a stated, recorded reason"). A failed
# consistency check does not say "this one field looks wrong" — it says this
# run's clocks or platform behavior are not trustworthy, full stop. That is a
# statement about the run, not about any single field of it. It is tempting
# to reason that a given field was measured on a clock domain the check
# didn't touch and so must still be trustworthy — that reasoning was tried
# twice while this module was built (once for `t_weights`, once for the
# warmup list) and overruled both times: "clock A misbehaved and everything
# else is fine" and "this run is anomalous in a way nobody understands"
# produce identical evidence, and choosing the first reading after the fact
# is exactly the post-hoc selective inclusion pre-registration exists to
# prevent. So EVERY preset below includes `"consistent"` — there is no
# exception, deliberate or otherwise. What the tuples express instead is what
# each metric needs *in addition to* that floor: `t_weights` and
# `t_fast_seconds` have their own, genuinely different nullity conditions
# (a merged phase; a missing dispatch offset) that have nothing to do with
# consistency, and `T_TOTAL`'s consumers need nothing beyond the floor
# itself. That per-metric layer is the reason `required` is a tuple a caller
# states rather than one hardcoded predicate — consistency being universal
# doesn't collapse that design, it just means every tuple below starts with
# `"consistent"`. Do not re-litigate this by adding a fifth preset that
# omits it.
REQUIRED_FOR_WARMUP: tuple[str, ...] = ("consistent",)
"""`warmup_curve` needs a clock-consistent, successful run. The warmup list is
ten raw clock-B, intra-process latency measurements with no cross-clock
reconciliation step of their own, which argues a consistency violation
elsewhere shouldn't taint them — but that argument was tried and overruled
(see the block comment above): whether the rest of an inconsistent run's data
is untouched is exactly what cannot be established after the fact, so it is
discarded with everything else from that run rather than selectively kept."""

REQUIRED_FOR_T_TOTAL: tuple[str, ...] = ("consistent",)
"""`waterfall`, `ecdf_plot`, and `per_host_medians` all read `t_total` and/or
`t_platform` — both `None` on a row that failed the clock-consistency check (spec
6.5 rule 3), so both need the row's `consistent` flag to be `True`, not merely
present."""

REQUIRED_FOR_T_WEIGHTS: tuple[str, ...] = ("consistent", "t_weights")
"""The primary A→B / B→C contrast (spec 7, Task 19). Also requires
`"consistent"` — ruling on B4's original design note, which argued `t_weights`
(S2+S3) is computed and validated independently of the T_total/T_process
reconciliation and so a clock-skewed run's `t_weights` could still be trusted.
That is technically true and still the wrong conclusion: a failed consistency
check means this run's clocks or platform behavior are not trustworthy, not
that only the T_total/T_platform fields are suspect. Publishing `t_weights`
from a run already declared broken is exactly the selective inclusion spec
6.5 rule 3 ("discarded ... never silently") exists to prevent. The fixture row
that exposed this (host `h4`: inconsistent, but with a perfectly plausible
`t_weights`) is pinned in tests/test_pipeline.py landing in `discarded` here,
specifically because of this ruling."""

REQUIRED_FOR_T_COMPILE: tuple[str, ...] = ("consistent", "t_compile")
"""The B→C compile-cache contrast (spec 7, spec stage taxonomy: "S4b, cold
minus warm"). Also requires `"consistent"`, same reasoning as
REQUIRED_FOR_T_WEIGHTS above — `t_compile` (`subphase_values["S4b"]` in
`metrics.derive()`) is computed independently of the T_total/T_process
consistency check and must not be published from a run that check already
rejected. `t_compile` is `None` under the exact same "merged phase" policy
that makes `t_weights` `None` when S2/S3 aren't delineated -- here, when a
given run's parsed engine log has no `S4b` entry in its phases. The pinned
engine version normally DOES delineate S4b (unlike S4a/S4d, which it merges
-- see harness/vllm_logs.py's PATTERNS and the fixture captures), so on a
healthy run this is populated, not the common case; the preset still needs
its own gate because that nullity condition is independent of clock
consistency, not because it is expected to fire often. Analogous to `by_w`'s
use of REQUIRED_FOR_T_WEIGHTS in `scripts/analyse.py`: pooling `t_compile`
from `REQUIRED_FOR_T_TOTAL`'s publishable set (gated on `consistent` alone)
would let a run without an S4b entry's `None` reach a bootstrap
unfiltered."""

REQUIRED_FOR_T_FAST: tuple[str, ...] = ("consistent", "t_fast_seconds")
"""The T_fast / business-framing figures (economics.py). Also requires
`"consistent"`, same reasoning as REQUIRED_FOR_T_WEIGHTS above —
`t_fast_seconds` is likewise computed independent of the T_total/T_process
check and must not be published from a run that check rejected.
`t_fast_seconds` is `None` on every run recorded before the Task 11 probe
emits `t_dispatch_mono` on its warmup records (see metrics.t_fast_seconds's
docstring, B5) — today that is every real run, so THIS preset is expected to
discard nearly an entire pre-Task-11 campaign on that basis alone, before
`"consistent"` ever enters into it. A reader who sees this preset's discard
count dwarf every other preset's should read that as the known, honest
pre-B5 state of the harness, not as a bug in this gate."""
