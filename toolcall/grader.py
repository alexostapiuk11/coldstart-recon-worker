"""The deterministic grader: one response, one category.

The ordered procedure (August §4, with amendment §4b's canonical schema and
§4g's provider-side outcomes ahead of it):

    0. Provider-side: the request failed, the provider reported an unrecognised
       terminal state or no usage, the model refused, or the output hit the cap
                                                  -> API_ERROR / REFUSED / TRUNCATED
       (excluded before any rate is computed, counted per cell)
    1. A call was made but is not a parseable call to a rendered tool that
       conforms structurally to the canonical schema    -> MALFORMED
    2. No call was expected, and a call was made         -> SPURIOUS
    3. A call was expected, and none was made            -> MISSING
    4. The tool is not one an acceptable call names      -> WRONG_TOOL
    5. The arguments match no acceptable call            -> WRONG_PARAMS
    6. otherwise                                         -> CORRECT

No call at all is never MALFORMED: a direct answer is MISSING or, where no call
was expected, CORRECT. A tool call written into the text instead of a call
block is flagged (`text_looks_like_call`) but graded by the same rules, so the
flag is descriptive only.

A response with more than one call is graded on its first and flagged.
"""

import json
from dataclasses import dataclass

from toolcall import NORMALIZER_VERSION
from toolcall.normalize import call_matches, conformance, value_violations
from toolcall.providers import Parsed
from toolcall.scenarios import Scenario
from toolcall.tools import Library

CATEGORIES = ("MALFORMED", "SPURIOUS", "MISSING", "WRONG_TOOL", "WRONG_PARAMS", "CORRECT")
FAILURES = CATEGORIES[:-1]
EXCLUDED = ("API_ERROR", "REFUSED", "TRUNCATED")


@dataclass(frozen=True)
class Grade:
    category: str
    detail: str
    multiple_calls: bool = False
    text_looks_like_call: bool = False
    wrong_tool_kind: str | None = None  # "confusable" | "filler" | "low_set"
    normalizer_version: int = NORMALIZER_VERSION

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d: dict) -> "Grade":
        return cls(**d)


def parse_arguments(raw: str):
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _looks_like_call(text: str, rendered: list[str]) -> bool:
    return any(f"{name}(" in text or f'"{name}"' in text for name in rendered)


def grade(parsed: Parsed | None, scenario: Scenario, library: Library, rendered: list[str],
          error: str | None = None) -> Grade:
    if error is not None or parsed is None:
        return Grade("API_ERROR", error or "no response")
    if parsed.finish == "error":
        return Grade("API_ERROR", "provider reported an unrecognised terminal state or no usage")
    if parsed.finish == "refused":
        return Grade("REFUSED", "provider reported a refusal")
    if parsed.finish == "truncated":
        return Grade("TRUNCATED", "output cap reached")
    flags = {
        "multiple_calls": len(parsed.calls) > 1,
        "text_looks_like_call": not parsed.calls and _looks_like_call(parsed.text, rendered),
    }
    if parsed.calls:
        call = parsed.calls[0]
        args = parse_arguments(call.arguments)
        if call.name not in rendered:
            return Grade("MALFORMED", f"tool {call.name!r} is not in context", **flags)
        tool = library.get(call.name)
        why = conformance(args, tool)
        if why is not None:
            return Grade("MALFORMED", why, **flags)
        if scenario.no_call_expected:
            return Grade("SPURIOUS", f"called {call.name} when no call was expected", **flags)
        if call.name not in scenario.acceptable_tools:
            if call.name in scenario.confusables:
                kind = "confusable"
            elif call.name in scenario.tools:
                kind = "low_set"
            else:
                kind = "filler"
            return Grade("WRONG_TOOL", f"called {call.name}", wrong_tool_kind=kind, **flags)
        acceptable = [c for c in scenario.acceptable_calls if c["tool"] == call.name]
        if not any(call_matches(args, c, tool) for c in acceptable):
            detail = "; ".join(value_violations(args, tool)) or "values match no acceptable call"
            return Grade("WRONG_PARAMS", detail, **flags)
        return Grade("CORRECT", "", **flags)
    if scenario.no_call_expected:
        return Grade("CORRECT", "answered directly, as expected", **flags)
    return Grade("MISSING", "answered without a call", **flags)
