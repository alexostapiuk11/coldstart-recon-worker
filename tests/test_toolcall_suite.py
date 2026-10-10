"""The candidate suite is big enough and covers what the analysis needs
(amendment §4d, §4e, §6, §14 items 1 and 12). Added when authoring is complete; it fails before.

- About 45 candidates, so about 30 survive the band (§4d's target).
- Every target failure mode is represented, so the taxonomy has something to separate.
- At least 28 scenarios carry a recovery block, 22 of them persistent kinds, so H4 still has
  20 scenarios after the band (§14 item 1, signed off by the author 2026-10-09).
- A public seed with provenance, and at least six neutral domains.
- Every domain library has at least 12 tools, and a scenario's confusables come from its own
  domain (§14 item 12), so a high rendering is at least 12 tools from the scenario's domain.
"""

from collections import Counter
from pathlib import Path

from toolcall.formulation import Formulation, render
from toolcall.scenarios import PERSISTENT_KINDS, TARGETS, load_scenarios
from toolcall.tools import load_library

DATA = Path(__file__).resolve().parents[1] / "toolcall" / "data"
LIB = load_library(DATA / "tools")
SCENARIOS = load_scenarios(DATA / "scenarios", LIB)


def test_about_forty_five_candidates():
    assert len(SCENARIOS) >= 45, len(SCENARIOS)


def test_every_target_failure_mode_has_at_least_four_scenarios():
    counts = Counter(s.target_failure_mode for s in SCENARIOS)
    assert all(counts[t] >= 4 for t in TARGETS), counts


def test_enough_recovery_scenarios_for_h4_after_selection():
    rec = [s for s in SCENARIOS if s.recovery]
    persistent = [s for s in rec if s.recovery.error_kind in PERSISTENT_KINDS]
    assert len(rec) >= 28 and len(persistent) >= 22, (len(rec), len(persistent))


def test_a_public_seed_and_six_domains():
    sources = Counter(s.source["kind"] for s in SCENARIOS)
    assert sources["bfcl"] >= 8, sources
    assert len({s.domain for s in SCENARIOS}) >= 6


def test_every_domain_library_has_at_least_twelve_tools():
    for domain in {t.domain for t in LIB.tools.values()}:
        assert len(LIB.domain(domain)) >= 12, (domain, len(LIB.domain(domain)))


def test_a_high_rendering_is_mostly_the_scenarios_own_domain():
    for s in SCENARIOS:
        names = [t["name"] for t in render(s, LIB, Formulation("high", "rich", "strict"))]
        same = sum(LIB.get(n).domain == s.domain for n in names)
        assert same >= min(12, len(LIB.domain(s.domain))), (s.id, same)
