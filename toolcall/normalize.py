"""The normalization rules, version 1.

These rules silently set every number the artifact publishes: a lenient
normalizer inflates the correct rate and a strict one deflates it, and neither
shows in the output (August §4). So they are written down here, in order,
published in the post, and versioned by `toolcall.NORMALIZER_VERSION`. Changing
one is a breaking change: bump the version, and never compare numbers graded
under two versions.

The split that matters most (amendment §4b): a call that is structurally
wrong is MALFORMED; a call that is well-formed but carries a wrong value is
WRONG_PARAMS. `conformance` decides the first, `call_matches` the second.
`call_matches` is true only for a call that conforms, breaks none of the
canonical schema's value constraints (R9), and matches an acceptable call.
"""

import json
import math
import re

from toolcall.tools import ParamSpec, ToolSpec

RULES = (
    ("R1", (
        "Enum values compare case-insensitively. Anthropic's strict mode does not "
        "guarantee enum capitalisation (amendment §4b), so no arm may be penalised for "
        "it."
    )),
    ("R2", (
        "Strings are trimmed and internal whitespace runs collapse to one space before "
        "any comparison. Free-text values compare case-sensitively; enum values and "
        "pattern specifications compare case-insensitively, but never override R9."
    )),
    ("R3", (
        "Numbers compare numerically within an absolute tolerance of 1e-9, so 3 equals "
        "3.0. An integer parameter accepts a float with no fractional part."
    )),
    ("R4", (
        'A number sent as a string is a type error, not a coercion: "3" for an integer '
        "parameter is MALFORMED."
    )),
    ("R5", (
        "An explicit null for an optional parameter is the same as omitting it. A null "
        "for a required parameter is a missing required parameter."
    )),
    ("R6", "Key order is irrelevant."),
    ("R7", (
        "A key the canonical schema does not define is a wrong parameter (WRONG_PARAMS), "
        "not a structural failure and not ignored as harmless."
    )),
    ("R8", "Arrays compare element by element, in order."),
    ("R9", (
        "A value counts as correct only if it also satisfies the canonical schema's enum "
        "and pattern; a scenario's acceptable values are checked against them when it "
        "loads."
    )),
)

TOLERANCE = 1e-9


def collapse(s: str) -> str:
    return " ".join(s.split())


def strip_nulls(args: dict, tool: ToolSpec) -> dict:
    """R5: drop explicit nulls on known parameters. A null on a required
    parameter is dropped too, so it then reads as missing. A null on a key the
    schema does not define stays, so R7 makes it a wrong parameter."""
    return {k: v for k, v in args.items() if v is not None or tool.param(k) is None}


def _type_ok(value, type_: str) -> bool:
    if type_ == "string":
        return isinstance(value, str)
    if type_ == "boolean":
        return isinstance(value, bool)
    if isinstance(value, bool):
        return False  # bool is an int subclass in Python, never a number here
    if type_ == "integer":
        return isinstance(value, int) or (isinstance(value, float) and value.is_integer())
    if type_ == "number":
        if isinstance(value, int):
            return True  # an arbitrarily large int is a valid number; isfinite would overflow
        return isinstance(value, float) and math.isfinite(value)
    raise ValueError(f"unknown type {type_!r}")


def _param_type_ok(value, p: ParamSpec) -> bool:
    if p.type == "array":
        return isinstance(value, list) and all(_type_ok(v, p.items) for v in value)
    return _type_ok(value, p.type)


def conformance(args, tool: ToolSpec) -> str | None:
    """Why `args` is structurally invalid for `tool`'s canonical schema, or
    None if it is valid. Structural means: not an object, a required key
    missing (after R5), or a known key with a value of the wrong JSON type
    (R3, R4). Value-level problems are not structural (R7, and amendment §4b)."""
    if not isinstance(args, dict):
        return f"arguments are a {type(args).__name__}, not an object"
    present = strip_nulls(args, tool)
    missing = [p.name for p in tool.params if p.required and p.name not in present]
    if missing:
        return f"missing required {missing}"
    for key, value in present.items():
        p = tool.param(key)
        if p is not None and not _param_type_ok(value, p):
            return f"{key!r} has type {type(value).__name__}, schema says {p.type}"
    return None


def _scalar_equal(a, b, p_type: str, enum: bool) -> bool:
    if p_type == "string":
        if not (isinstance(a, str) and isinstance(b, str)):
            return False
        a, b = collapse(a), collapse(b)
        return a.casefold() == b.casefold() if enum else a == b
    if p_type == "boolean":
        return a is b
    if isinstance(a, int) and isinstance(b, int):
        return a == b  # exact, so integers beyond float range compare without overflow
    try:
        return abs(float(a) - float(b)) <= TOLERANCE
    except OverflowError:
        return False


def _literal_equal(spec, value, p: ParamSpec) -> bool:
    if p.type == "array":
        return (
            isinstance(value, list)
            and isinstance(spec, list)
            and len(value) == len(spec)
            and all(_scalar_equal(s, v, p.items, False) for s, v in zip(spec, value))
        )
    return _scalar_equal(spec, value, p.type, bool(p.enum))


def value_matches(spec, value, p: ParamSpec) -> bool:
    """A value specification is a literal, `{"one_of": [literal, ...]}`, or
    `{"pattern": regex, "example": literal}` (a full, case-insensitive match on
    a string after R2; the example is one value that matches, for the stub)."""
    if isinstance(spec, dict) and set(spec) == {"one_of"}:
        return any(_literal_equal(s, value, p) for s in spec["one_of"])
    if isinstance(spec, dict) and set(spec) == {"pattern", "example"}:
        return isinstance(value, str) and re.fullmatch(
            spec["pattern"], collapse(value), re.IGNORECASE
        ) is not None
    return _literal_equal(spec, value, p)


def call_matches(args: dict, acceptable: dict, tool: ToolSpec) -> bool:
    """Whether `args` match one acceptable call. They must conform and break no
    canonical value constraint (R9); then every key in `acceptable["args"]` must
    be present and matching, and any other key may be present only if
    `acceptable["may_include"]` allows it with a matching value (R7)."""
    if conformance(args, tool) is not None or value_violations(args, tool):
        return False  # R9: one definition of a valid value
    present = strip_nulls(args, tool)
    required = acceptable.get("args", {})
    optional = acceptable.get("may_include", {})
    if set(present) - set(required) - set(optional):
        return False
    for key, spec in required.items():
        if key not in present or not value_matches(spec, present[key], tool.param(key)):
            return False
    for key, spec in optional.items():
        if key in present and not value_matches(spec, present[key], tool.param(key)):
            return False
    return True


def value_violations(args: dict, tool: ToolSpec) -> list[str]:
    """The canonical schema's value-level constraints a well-formed call
    breaks: unknown keys (R7), enum values outside the set (R1), strings
    failing a pattern. Recorded as detail on a WRONG_PARAMS grade."""
    out = []
    for key, value in strip_nulls(args, tool).items():
        p = tool.param(key)
        if p is None:
            out.append(f"unknown key {key!r}")
        elif p.enum and collapse(value).casefold() not in {e.casefold() for e in p.enum}:
            out.append(f"{key!r}={value!r} is not one of {list(p.enum)}")
        elif p.pattern and re.fullmatch(p.pattern, collapse(value)) is None:
            out.append(f"{key!r}={value!r} does not match {p.pattern!r}")
    return out


def call_key(name: str, args: dict, tool: ToolSpec | None) -> str:
    """One string per distinct call after normalization, for comparing two
    calls: identical retries (August §4) are calls with equal keys."""
    if not isinstance(args, dict):
        return json.dumps([name, repr(args)])
    norm = {}
    for key, value in (strip_nulls(args, tool) if tool else args).items():
        p = tool.param(key) if tool else None
        norm[key] = _normalized(value, p is not None and bool(p.enum))
    return json.dumps([name, norm], sort_keys=True)


def _normalized(value, enum: bool):
    """One value in its comparison form, recursively, so array elements get the
    same treatment as scalars: whitespace collapsed, an integral float as an int,
    an enum string case-folded."""
    if isinstance(value, str):
        value = collapse(value)
        return value.casefold() if enum else value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, list):
        return [_normalized(v, False) for v in value]
    return value
