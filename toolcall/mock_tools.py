"""The mock tool layer: what a tool "returns" in a recovery scenario.

Mock tools exist because recovery needs something to fail (August §4). They
produce state, and the state is recorded, but grading never depends on it.

How each error kind behaves, decided by the scenario's acceptable recovery
calls (the calls the service would accept):

- invalid_parameter: the service rejects any call that matches no acceptable
  recovery call, naming the parameter. A first call that already matches is
  accepted, and that conversation records that no error was injected.
- contradicting_result: a call that matches no acceptable recovery call gets a
  success-shaped result that contradicts the request, at any attempt. A call
  that matches one gets the real result, the first call included: a first call
  that already meets the recovery requirement is accepted and that
  conversation records that no contradiction was injected, as for
  invalid_parameter.
- timeout, malformed_payload: the first call fails whatever it was. Later calls
  that match get the real result. These are transient: an identical retry is
  the right move, which is why H4 excludes them (scenarios.PERSISTENT_KINDS).

Two message formats per kind, the nested factor: `actionable` says what went
wrong and what to do; `opaque` says only that something did.
"""

import json
from dataclasses import dataclass

from toolcall.normalize import call_matches
from toolcall.scenarios import Recovery
from toolcall.tools import Library

FORMATS = ("actionable", "opaque")


@dataclass(frozen=True)
class ToolReply:
    content: str
    is_error: bool
    success: bool


def error_text(recovery: Recovery, fmt: str) -> str:
    if fmt not in FORMATS:
        raise ValueError(f"format {fmt!r}")
    p, hint = recovery.param, recovery.expected
    if recovery.error_kind == "invalid_parameter":
        if fmt == "actionable":
            return (f"Error: invalid request. Parameter '{p}': {hint}. The request was not "
                    f"processed; correct '{p}' and call again.")
        return "Error: invalid request."
    if recovery.error_kind == "timeout":
        if fmt == "actionable":
            return ("Error: the service timed out before processing the request. Nothing was "
                    "changed; the same request can be sent again.")
        return "Error: timeout."
    if recovery.error_kind == "malformed_payload":
        if fmt == "actionable":
            return ("Error: the service returned an unreadable response. Nothing was changed; "
                    "the same request can be sent again.")
        return "Error: bad response."
    raise ValueError(f"{recovery.error_kind} has no error text; it returns a result")


def _contradiction(recovery: Recovery, fmt: str) -> str:
    body = json.dumps(recovery.contradicting_result, sort_keys=True)
    if fmt == "actionable":
        return (f"{body}\nNote: these results do not match the requested '{recovery.param}'. "
                f"{recovery.expected}.")
    return body


def _accepted(name: str, args, recovery: Recovery, library: Library) -> bool:
    if not isinstance(args, dict):
        return False
    tool = library.tools.get(name)
    return tool is not None and any(
        c["tool"] == name and call_matches(args, c, tool)
        for c in recovery.acceptable_recovery_calls
    )


def reply(recovery: Recovery, fmt: str, attempt: int, name: str, args,
          library: Library) -> ToolReply:
    """The tool's answer to call number `attempt` (0 is the first call)."""
    ok = _accepted(name, args, recovery, library)
    success = ToolReply(json.dumps(recovery.success_result, sort_keys=True), False, True)
    kind = recovery.error_kind
    if kind == "invalid_parameter":
        return success if ok else ToolReply(error_text(recovery, fmt), True, False)
    if kind == "contradicting_result":
        return success if ok else ToolReply(_contradiction(recovery, fmt), False, False)
    if attempt == 0 or not ok:
        return ToolReply(error_text(recovery, fmt), True, False)
    return success
