"""Abstract tools: what a tool is, independent of how it is presented.

A tool here is plain data: a name, a terse and a rich description, and typed
parameters. The formulation layer (toolcall/formulation.py) decides how it is
shown to a model; the grader (toolcall/grader.py) checks every call against the
tool's one canonical schema, its strict form, whatever the model was shown
(amendment §4b).

Parameter types are a closed subset -- string, integer, number, boolean, and an
array of one of those -- with an optional `enum` or `pattern` on strings. The
subset is closed on purpose: it is what every provider's strict mode accepts
(amendment §4a), so a canonical schema can never depend on a feature one
provider rejects, and the grader's conformance check is small enough to read.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

PRIMITIVES = ("string", "integer", "number", "boolean")
_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


@dataclass(frozen=True)
class ParamSpec:
    name: str
    type: str  # one of PRIMITIVES, or "array"
    required: bool
    terse: str
    rich: str
    items: str | None = None  # element type when type == "array"
    enum: tuple[str, ...] = ()
    pattern: str | None = None

    def __post_init__(self) -> None:
        if not _NAME.match(self.name):
            raise ValueError(f"parameter name {self.name!r} is not snake_case")
        if self.type not in PRIMITIVES + ("array",):
            raise ValueError(f"{self.name}: type {self.type!r} is outside the closed subset")
        if (self.type == "array") != (self.items is not None):
            raise ValueError(f"{self.name}: `items` is required for arrays and only for arrays")
        if self.items is not None and self.items not in PRIMITIVES:
            raise ValueError(f"{self.name}: array items must be a primitive, got {self.items!r}")
        if (self.enum or self.pattern) and self.type != "string":
            raise ValueError(f"{self.name}: enum and pattern apply to strings only")
        if self.enum and self.pattern:
            raise ValueError(f"{self.name}: give an enum or a pattern, not both")
        if self.pattern is not None:
            re.compile(self.pattern)
        if not self.terse.strip() or not self.rich.strip():
            raise ValueError(f"{self.name}: both descriptions are required")


@dataclass(frozen=True)
class ToolSpec:
    name: str
    domain: str
    terse: str
    rich: str
    params: tuple[ParamSpec, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not _NAME.match(self.name):
            raise ValueError(f"tool name {self.name!r} is not snake_case")
        if not self.terse.strip() or not self.rich.strip():
            raise ValueError(f"{self.name}: both descriptions are required")
        names = [p.name for p in self.params]
        if len(names) != len(set(names)):
            raise ValueError(f"{self.name}: duplicate parameter names")
        if self.params and not any(p.required for p in self.params):
            raise ValueError(f"{self.name}: a tool with parameters needs one required parameter")

    def param(self, name: str) -> ParamSpec | None:
        return next((p for p in self.params if p.name == name), None)

    @property
    def primary_param(self) -> ParamSpec | None:
        """The tool's single most obvious argument: its first required one.
        The loose rendering keeps only this one in `required` (amendment §4a)."""
        return next((p for p in self.params if p.required), None)


def canonical_schema(tool: ToolSpec) -> dict:
    """The strict form, without descriptions. Every call in every cell is
    graded against this (amendment §4b)."""
    props = {}
    for p in tool.params:
        prop: dict = {"type": p.type}
        if p.items:
            prop["items"] = {"type": p.items}
        if p.enum:
            prop["enum"] = list(p.enum)
        if p.pattern:
            prop["pattern"] = p.pattern
        props[p.name] = prop
    return {
        "type": "object",
        "properties": props,
        "required": [p.name for p in tool.params if p.required],
        "additionalProperties": False,
    }


def _param_from_dict(d: dict) -> ParamSpec:
    return ParamSpec(
        name=d["name"],
        type=d["type"],
        required=d["required"],
        terse=d["terse"],
        rich=d["rich"],
        items=d.get("items"),
        enum=tuple(d.get("enum", ())),
        pattern=d.get("pattern"),
    )


def tool_from_dict(d: dict, domain: str) -> ToolSpec:
    if d.get("draft"):
        raise ValueError(f"{d['name']}: still a draft (scripts/a3_import_bfcl.py output)")
    return ToolSpec(
        name=d["name"],
        domain=domain,
        terse=d["terse"],
        rich=d["rich"],
        params=tuple(_param_from_dict(p) for p in d.get("params", ())),
    )


@dataclass(frozen=True)
class Library:
    """Every tool, from every domain file, by name. Tool names are unique
    across domains, so a scenario can borrow an unrelated tool by name."""

    tools: dict[str, ToolSpec]

    def get(self, name: str) -> ToolSpec:
        if name not in self.tools:
            raise KeyError(f"no tool named {name!r} in the library")
        return self.tools[name]

    def domain(self, domain: str) -> list[ToolSpec]:
        return sorted((t for t in self.tools.values() if t.domain == domain), key=lambda t: t.name)


def load_library(directory) -> Library:
    tools: dict[str, ToolSpec] = {}
    for path in sorted(Path(directory).glob("*.json")):
        data = json.loads(path.read_text())
        for d in data["tools"]:
            tool = tool_from_dict(d, data["domain"])
            if tool.name in tools:
                raise ValueError(f"{path.name}: tool {tool.name!r} is defined twice")
            tools[tool.name] = tool
    if not tools:
        raise ValueError(f"no tools under {directory}")
    return Library(tools)
