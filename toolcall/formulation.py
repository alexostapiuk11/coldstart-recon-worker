"""One scenario, eight renderings, and nothing else differs between them.

The three factors (August §5, amendment §4a and §4c):

- count: `low` is the scenario's own 2-4 tools; `high` is exactly 20 tools,
  the low set plus its confusables plus filler, drawn per scenario (seeded)
  from the scenario's own domain first, then from the other domains.
- richness: `terse` or `rich` descriptions, for the tool and every parameter.
- strictness: `strict` renders enums, patterns, every required parameter and
  `additionalProperties: false`; `loose` renders bare types and keeps only
  the tool's primary parameter in `required`.

Tool order is a function of the scenario and the count level only, so the
richness and strictness cells of one count level show the model the same
tools in the same order. The system prompt is one fixed text in every cell.
"""

import random
from dataclasses import dataclass

from toolcall.scenarios import Scenario
from toolcall.tools import Library, ToolSpec

HIGH_COUNT = 20
SYSTEM_PROMPT = (
    "You are an assistant that can call tools. Call a tool when the request needs one; "
    "otherwise answer directly. Make at most one tool call per turn."
)


@dataclass(frozen=True)
class Formulation:
    count: str  # "low" | "high"
    richness: str  # "terse" | "rich"
    strictness: str  # "loose" | "strict"

    def __post_init__(self) -> None:
        if self.count not in ("low", "high"):
            raise ValueError(f"count {self.count!r}")
        if self.richness not in ("terse", "rich"):
            raise ValueError(f"richness {self.richness!r}")
        if self.strictness not in ("loose", "strict"):
            raise ValueError(f"strictness {self.strictness!r}")

    @property
    def name(self) -> str:
        return f"{self.count}-{self.richness}-{self.strictness}"

    @property
    def signs(self) -> dict[str, int]:
        """The +1/-1 coding the 2^3 contrasts use (toolcall/effects.py)."""
        return {
            "count": 1 if self.count == "high" else -1,
            "richness": 1 if self.richness == "rich" else -1,
            "strictness": 1 if self.strictness == "strict" else -1,
        }


CELLS = tuple(
    Formulation(c, r, s)
    for c in ("low", "high")
    for r in ("terse", "rich")
    for s in ("loose", "strict")
)
BASELINE = Formulation("low", "terse", "loose")  # amendment §5, proposed for step 1


def parse_cell(name: str) -> Formulation:
    parts = name.split("-")
    if len(parts) != 3:
        raise ValueError(f"cell name {name!r} is not count-richness-strictness")
    return Formulation(*parts)


def tool_names(scenario: Scenario, library: Library, count: str) -> list[str]:
    """The tools in context, in the order the model sees them."""
    names = list(scenario.tools)
    if count == "high":
        names += list(scenario.confusables)
        same = [t.name for t in library.domain(scenario.domain)]
        other = sorted(t.name for t in library.tools.values() if t.domain != scenario.domain)
        rng = random.Random(f"{scenario.id}:filler")
        rng.shuffle(same)
        rng.shuffle(other)
        for name in same + other:
            if len(names) == HIGH_COUNT:
                break
            if name not in names:
                names.append(name)
        if len(names) < HIGH_COUNT:
            raise ValueError(
                f"{scenario.id}: the library has only {len(names)} tools to offer; "
                f"the high level needs {HIGH_COUNT}"
            )
    random.Random(f"{scenario.id}:{count}").shuffle(names)
    return names


def render_tool(tool: ToolSpec, richness: str, strictness: str) -> dict:
    """Provider-neutral: name, description, JSON-schema parameters."""
    rich = richness == "rich"
    strict = strictness == "strict"
    props = {}
    for p in tool.params:
        prop: dict = {"type": p.type, "description": p.rich if rich else p.terse}
        if p.items:
            prop["items"] = {"type": p.items}
        if strict and p.enum:
            prop["enum"] = list(p.enum)
        if strict and p.pattern:
            prop["pattern"] = p.pattern
        props[p.name] = prop
    if strict:
        required = [p.name for p in tool.params if p.required]
    else:
        required = [tool.primary_param.name] if tool.primary_param else []
    schema: dict = {"type": "object", "properties": props, "required": required}
    if strict:
        schema["additionalProperties"] = False
    return {"name": tool.name, "description": tool.rich if rich else tool.terse,
            "parameters": schema}


def render(scenario: Scenario, library: Library, formulation: Formulation) -> list[dict]:
    return [
        render_tool(library.get(n), formulation.richness, formulation.strictness)
        for n in tool_names(scenario, library, formulation.count)
    ]
