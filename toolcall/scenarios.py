"""Scenarios: plain data files, validated against the tool library.

A scenario names the tools it needs (its low set), the plausible confusables
written for it (amendment §4c), one user message, and exactly one expectation:
an enumerated list of acceptable calls, or "no call expected" (August §4).
Recovery scenarios add an injected error and the calls that count as recovering.

Validation runs at load time, so a scenario that could never be graded -- an
acceptable call that is itself malformed, a confusable that does not exist --
fails before any money is spent on it.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from toolcall.normalize import call_matches, conformance, value_matches, value_violations
from toolcall.tools import Library

TARGETS = ("MALFORMED", "SPURIOUS", "MISSING", "WRONG_TOOL", "WRONG_PARAMS")
ERROR_KINDS = ("invalid_parameter", "contradicting_result", "timeout", "malformed_payload")
# Kinds where repeating the failing call unchanged cannot succeed. H4 is
# computed on these only: after a timeout, an identical retry is correct.
PERSISTENT_KINDS = ("invalid_parameter", "contradicting_result")
LOW_SET = (2, 4)
CONFUSABLES = (4, 6)


@dataclass(frozen=True)
class Recovery:
    error_kind: str
    param: str  # the parameter the error is about
    expected: str  # the actionable message's hint, e.g. "YYYY-MM-DD, for example 2026-11-03"
    acceptable_recovery_calls: tuple[dict, ...]
    success_result: dict
    success_claim_pattern: str  # deterministic proxy for "hallucinated success"
    contradicting_result: dict | None = None


@dataclass(frozen=True)
class Scenario:
    id: str
    source: dict
    domain: str
    target_failure_mode: str
    tools: tuple[str, ...]
    confusables: tuple[str, ...]
    user_message: str
    acceptable_calls: tuple[dict, ...]
    no_call_expected: bool
    recovery: Recovery | None = None

    @property
    def acceptable_tools(self) -> set[str]:
        return {c["tool"] for c in self.acceptable_calls}


def _check_call(call: dict, library: Library, where: str) -> None:
    tool = library.get(call["tool"])
    unknown = set(call) - {"tool", "args", "may_include"}
    if unknown:
        raise ValueError(f"{where}: unknown fields {sorted(unknown)}")
    both = set(call.get("args", {})) & set(call.get("may_include", {}))
    if both:
        raise ValueError(f"{where}: {sorted(both)} appear in both args and may_include")
    for group in ("args", "may_include"):
        for key, spec in call.get(group, {}).items():
            p = tool.param(key)
            if p is None:
                raise ValueError(f"{where}: {call['tool']} has no parameter {key!r}")
            if isinstance(spec, dict) and "pattern" in spec:
                if set(spec) != {"pattern", "example"}:
                    raise ValueError(f"{where}: a pattern needs exactly an `example` beside it")
                try:
                    example_ok = value_matches(spec, spec["example"], p)
                except re.error as e:
                    raise ValueError(f"{where}: pattern {spec['pattern']!r} is invalid: {e}") from e
                if not example_ok:
                    raise ValueError(f"{where}: example {spec['example']!r} fails its pattern")
                literals = [spec["example"]]
            elif isinstance(spec, dict) and set(spec) == {"one_of"}:
                literals = spec["one_of"]
                if not isinstance(literals, list) or not literals:
                    raise ValueError(f"{where}: one_of must be a non-empty list")
            elif isinstance(spec, dict):
                raise ValueError(f"{where}: unknown value specification {sorted(spec)}")
            else:
                literals = [spec]
            for lit in literals:
                if conformance({**_required_stub(tool), key: lit}, tool) is not None:
                    raise ValueError(f"{where}: {key}={lit!r} does not fit the canonical type")
                if not value_matches(lit, lit, p):
                    raise ValueError(f"{where}: {key}={lit!r} does not match itself")
                # R9: an acceptable value must also satisfy the canonical enum and
                # pattern, or no call could ever be both correct and valid.
                violations = value_violations({key: lit}, tool)
                if violations:
                    raise ValueError(f"{where}: {key}={lit!r} breaks the canonical schema: "
                                     f"{violations[0]}")
    missing = [p.name for p in tool.params if p.required and p.name not in call.get("args", {})]
    if missing:
        raise ValueError(f"{where}: acceptable call omits required {missing}")


def _required_stub(tool) -> dict:
    """A placeholder value of the right type for every required parameter, so
    one literal can be type-checked on its own through `conformance`."""
    filler = {"string": "x", "integer": 1, "number": 1.0, "boolean": True}
    return {
        p.name: ([filler[p.items]] if p.type == "array" else filler[p.type])
        for p in tool.params
        if p.required
    }


def _literal_args(call: dict) -> dict:
    """The one concrete argument set a call specification stands for: the first
    `one_of` member and each pattern's example, and no `may_include` keys."""
    out = {}
    for key, spec in call.get("args", {}).items():
        if isinstance(spec, dict) and "one_of" in spec:
            spec = spec["one_of"][0]
        elif isinstance(spec, dict) and "pattern" in spec:
            spec = spec["example"]
        out[key] = spec
    return out


def _recovery_from_dict(
    d: dict | None, library: Library, sid: str, low_set: tuple[str, ...], first_call: dict | None
) -> Recovery | None:
    if d is None:
        return None
    if d["error_kind"] not in ERROR_KINDS:
        raise ValueError(f"{sid}: error_kind {d['error_kind']!r} not in {ERROR_KINDS}")
    calls = tuple(d["acceptable_recovery_calls"])
    if not calls:
        raise ValueError(f"{sid}: a recovery scenario needs acceptable recovery calls")
    for i, c in enumerate(calls):
        _check_call(c, library, f"{sid} recovery call {i}")
        if c["tool"] not in low_set:
            raise ValueError(f"{sid} recovery call {i}: {c['tool']} is not in the low set")
    if not any(library.get(c["tool"]).param(d["param"]) for c in calls):
        raise ValueError(f"{sid}: recovery param {d['param']!r} is not a parameter of any "
                         "recovery call's tool")
    try:
        re.compile(d["success_claim_pattern"])
    except (re.error, TypeError) as e:
        raise ValueError(f"{sid}: success_claim_pattern does not compile: {e}") from e
    if not isinstance(d["success_result"], dict):
        raise ValueError(f"{sid}: success_result must be an object")  # noqa: TRY004
    contradicting = d.get("contradicting_result")
    if contradicting is not None and not isinstance(contradicting, dict):
        raise ValueError(f"{sid}: contradicting_result must be an object")
    if d["error_kind"] == "contradicting_result" and not contradicting:
        raise ValueError(f"{sid}: contradicting_result kind needs a contradicting_result")
    if d["error_kind"] == "invalid_parameter" and first_call is not None:
        # The error is injected when the model's first call matches the first
        # acceptable call. If that call also counted as a recovery, the error
        # could never be injected (amendment §14 item 4).
        literal = _literal_args(first_call)
        for c in calls:
            if c["tool"] == first_call["tool"] and call_matches(
                literal, c, library.get(c["tool"])
            ):
                raise ValueError(f"{sid}: the first acceptable call already matches a recovery "
                                 "call, so the injected error could never occur")
    return Recovery(
        error_kind=d["error_kind"],
        param=d["param"],
        expected=d["expected"],
        acceptable_recovery_calls=calls,
        success_result=d["success_result"],
        success_claim_pattern=d["success_claim_pattern"],
        contradicting_result=d.get("contradicting_result"),
    )


def scenario_from_dict(d: dict, library: Library, *, factorial: bool = True) -> Scenario:
    """`factorial=False` is the bring-your-own-tools path (August §7): your own
    tools and scenarios, the baseline formulation only, so the low-set and
    confusable counts the factorial needs are not required."""
    sid = d["id"]
    if d.get("draft"):
        raise ValueError(f"{sid}: still a draft (scripts/a3_import_bfcl.py output); author it")
    exp = d["expectation"]
    no_call = exp.get("no_call_expected", False)
    calls = tuple(exp.get("acceptable_calls", ()))
    if no_call == bool(calls):
        raise ValueError(f"{sid}: give acceptable_calls or no_call_expected, exactly one")
    if d["target_failure_mode"] not in TARGETS:
        raise ValueError(f"{sid}: target_failure_mode must be one of {TARGETS}")
    if no_call and d["target_failure_mode"] != "SPURIOUS":
        raise ValueError(f"{sid}: a no-call scenario targets SPURIOUS")
    tools = tuple(d["tools"])
    confusables = tuple(d["confusables"])
    if len(set(tools)) != len(tools):
        raise ValueError(f"{sid}: duplicate names in tools")
    if len(set(confusables)) != len(confusables):
        raise ValueError(f"{sid}: duplicate names in confusables")
    if factorial and not LOW_SET[0] <= len(tools) <= LOW_SET[1]:
        raise ValueError(f"{sid}: the low set has {len(tools)} tools; amendment §4c says 2-4")
    if factorial and not CONFUSABLES[0] <= len(confusables) <= CONFUSABLES[1]:
        raise ValueError(f"{sid}: {len(confusables)} confusables; amendment §4c says 4-6")
    if not tools:
        raise ValueError(f"{sid}: no tools")
    if set(tools) & set(confusables):
        raise ValueError(f"{sid}: a tool cannot be both in the low set and a confusable")
    for name in tools + confusables:
        library.get(name)
    for i, c in enumerate(calls):
        if c["tool"] not in tools:
            raise ValueError(f"{sid}: acceptable call {i} uses {c['tool']}, not in the low set")
        _check_call(c, library, f"{sid} call {i}")
    recovery = _recovery_from_dict(d.get("recovery"), library, sid, tools,
                                   calls[0] if calls else None)
    if recovery is not None and no_call:
        raise ValueError(f"{sid}: a recovery scenario must expect a call")
    return Scenario(
        id=sid,
        source=d["source"],
        domain=d["domain"],
        target_failure_mode=d["target_failure_mode"],
        tools=tools,
        confusables=confusables,
        user_message=d["user_message"],
        acceptable_calls=calls,
        no_call_expected=no_call,
        recovery=recovery,
    )


def load_scenarios(directory, library: Library, *, factorial: bool = True) -> list[Scenario]:
    out = []
    for path in sorted(Path(directory).glob("*.json")):
        s = scenario_from_dict(json.loads(path.read_text()), library, factorial=factorial)
        if s.id != path.stem:
            raise ValueError(f"{path.name}: id {s.id!r} must equal the file name")
        out.append(s)
    if len({s.id for s in out}) != len(out):
        raise ValueError("duplicate scenario ids")
    return out
