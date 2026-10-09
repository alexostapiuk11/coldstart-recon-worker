"""A GPU-free, network-free stand-in for a model, with planted effects. NOT DATA.

`StubModel` is a `ScriptedClient` policy. It reads the request body the real
builder produced, works out which scenario and which cell it is looking at
from the rendered tools alone, and draws a category from probabilities with
known effects planted in them. The end-to-end tests check that the analysis
recovers those effects, the way artifact 5's stub let its tests check that its
analysis recovered the costs put in.

Planted (as rates of each category, before scenario difficulty):

- WRONG_TOOL rises with tool count, and rich descriptions cut it only at high
  count: the H1 interaction and H3.
- MALFORMED and WRONG_PARAMS fall under the strict schema: H2. Strictness does
  not touch WRONG_TOOL.
- Repetitions are sticky: with probability `stickiness` a call repeats its
  (scenario, cell) unit's first draw, so the intra-scenario correlation is high,
  as the Noise Floor Audit found for real endpoints.
- Recovery: opaque errors are followed by an identical retry more often than
  actionable ones: H4.
"""

import json
import random

from toolcall import responses
from toolcall.formulation import Formulation

PLANTED = {
    "WRONG_TOOL": {"base": 0.03, "high": 0.18, "high_rich": -0.12},
    "MALFORMED": {"base": 0.05, "strict": -0.04},
    "WRONG_PARAMS": {"base": 0.08, "strict": -0.05},
    "MISSING": {"base": 0.03},
    "SPURIOUS": {"base": 0.10, "high": 0.10},
}
IDENTICAL_RETRY = {"opaque": 0.45, "actionable": 0.10}


def _stable(*parts) -> random.Random:
    return random.Random(":".join(str(p) for p in parts))


class StubModel:
    def __init__(self, library, scenarios, *, seed: int = 0, stickiness: float = 0.8,
                 model: str = "gpt-5.4-mini-2026-03-17", difficulty: float = 0.10):
        self.library = library
        self.by_message = {s.user_message: s for s in scenarios}
        if len(self.by_message) != len(scenarios):
            raise ValueError("the stub identifies scenarios by user message; make them unique")
        self.seed = seed
        self.stickiness = stickiness
        self.model = model
        self.difficulty = {s.id: _stable(seed, "difficulty", s.id).random() * difficulty
                           for s in scenarios}
        self.calls_seen: dict = {}

    # -- reading the request -------------------------------------------------

    @staticmethod
    def _strict(tools: list[dict]) -> bool:
        """Read strictness from what the rendering put in the schemas.

        `additionalProperties` is not a safe signal: constrained decoding adds
        it to every tool, and makes every property required, so a loose cell
        sent with `strict: true` looks strict by those two marks. Enums and
        patterns are only rendered in the strict cell and the constrained
        rewrite leaves them alone. A body that is not constrained also shows
        the strict cell through `additionalProperties` and a longer `required`,
        for a scenario whose tools carry no enum or pattern.
        """
        # Under constrained decoding a strict cell whose tools carry no enum or
        # pattern reads as loose here. The synthetic suite always has one, so
        # the stub stays correct for it.
        for t in tools:
            if any("enum" in p or "pattern" in p for p in t["parameters"]["properties"].values()):
                return True
        if any(t.get("strict") is True for t in tools):
            return False
        return any("additionalProperties" in t["parameters"] or len(t["parameters"]["required"]) > 1
                   for t in tools)

    def _cell(self, tools: list[dict]) -> Formulation:
        count = "high" if len(tools) == 20 else "low"
        first = tools[0]
        rich = first["description"] == self.library.get(first["name"]).rich
        return Formulation(count, "rich" if rich else "terse",
                           "strict" if self._strict(tools) else "loose")

    def _scenario_and_turns(self, body: dict):
        items = body["input"]
        user = next(i["content"] for i in items if i.get("role") == "user")
        tool_outputs = [i for i in items if i.get("type") == "function_call_output"]
        return self.by_message[user], tool_outputs

    # -- choosing an outcome -------------------------------------------------

    def _probabilities(self, scenario, cell: Formulation) -> dict[str, float]:
        high, rich, strict = cell.count == "high", cell.richness == "rich", \
            cell.strictness == "strict"
        d = self.difficulty[scenario.id]

        def rate(cat):
            p = PLANTED[cat]
            return max(0.0, p["base"] + p.get("high", 0) * high
                       + p.get("high_rich", 0) * (high and rich) + p.get("strict", 0) * strict)

        if scenario.no_call_expected:
            return {"SPURIOUS": min(0.9, rate("SPURIOUS") + d)}
        return {"WRONG_TOOL": rate("WRONG_TOOL") + d, "MALFORMED": rate("MALFORMED"),
                "WRONG_PARAMS": rate("WRONG_PARAMS") + d, "MISSING": rate("MISSING")}

    @staticmethod
    def _draw(rng, probs) -> str:
        x = rng.random()
        for cat, p in probs.items():
            if x < p:
                return cat
            x -= p
        return "CORRECT"

    # -- writing the response --------------------------------------------------

    def _stub_args(self, tool_name: str) -> dict:
        filler = {"string": "x", "integer": 1, "number": 1.0, "boolean": True}
        tool = self.library.get(tool_name)
        args = {}
        for p in tool.params:
            if not p.required:
                continue
            if p.enum:
                args[p.name] = p.enum[0]
            elif p.pattern == "^[A-Z]{3}$":
                args[p.name] = "AAA"
            elif p.pattern:
                args[p.name] = "2026-01-01"
            else:
                args[p.name] = [filler[p.items]] if p.type == "array" else filler[p.type]
        return args

    @staticmethod
    def _literal(spec):
        if isinstance(spec, dict) and "one_of" in spec:
            return spec["one_of"][0]
        if isinstance(spec, dict):
            return spec["example"]
        return spec

    def _respond(self, scenario, category: str, tools: list[dict], tokens: int) -> dict:
        names = [t["name"] for t in tools]
        kw = {"model": self.model, "input_tokens": tokens}
        if category == "CORRECT" and scenario.no_call_expected:
            return responses.openai_text("You're welcome.", **kw)
        if category == "MISSING":
            return responses.openai_text("I think there are flights in the morning.", **kw)
        if category == "SPURIOUS":
            return responses.openai_call(names[0], self._stub_args(names[0]), **kw)
        call = scenario.acceptable_calls[0]
        args = {k: self._literal(v) for k, v in call["args"].items()}
        if category == "CORRECT":
            return responses.openai_call(call["tool"], args, **kw)
        if category == "MALFORMED":
            return responses.openai_call(call["tool"], None, raw_arguments='{"origin": ', **kw)
        if category == "WRONG_TOOL":
            wrong = [n for n in names if n not in scenario.acceptable_tools]
            if wrong:
                return responses.openai_call(wrong[0], self._stub_args(wrong[0]), **kw)
            category = "WRONG_PARAMS"
        key = next(iter(args))
        args[key] = "ZZZ" if isinstance(args[key], str) else args[key] + 7
        return responses.openai_call(call["tool"], args, **kw)

    def _recovery_turn(self, scenario, tool_outputs, body) -> dict:
        last = tool_outputs[-1]["output"]
        fmt = "opaque" if len(last) < 40 else "actionable"
        rng = _stable(self.seed, "recovery", scenario.id, len(tool_outputs),
                      self.calls_seen.setdefault(("rec", scenario.id), 0))
        self.calls_seen[("rec", scenario.id)] += 1
        first = next(i for i in body["input"] if i.get("type") == "function_call")
        x = rng.random()
        if x < IDENTICAL_RETRY[fmt]:
            return responses.openai_call(first["name"], None,
                                         raw_arguments=first["arguments"], model=self.model)
        if x < IDENTICAL_RETRY[fmt] + 0.4:
            fix = scenario.recovery.acceptable_recovery_calls[0]
            return responses.openai_call(
                fix["tool"], {k: self._literal(v) for k, v in fix["args"].items()},
                model=self.model)
        return responses.openai_text("Sorry, I could not complete the search.",
                                     model=self.model)

    def __call__(self, body: dict) -> dict:
        """Usage reports input tokens from the size of the request, as a real
        API would, so per-cell costs differ the way they will when paid."""
        tokens = max(1, len(json.dumps(body)) // 4)
        scenario, tool_outputs = self._scenario_and_turns(body)
        if tool_outputs:
            return self._recovery_turn(scenario, tool_outputs, body)
        cell = self._cell(body["tools"])
        unit = (scenario.id, cell.name)
        n = self.calls_seen.get(unit, 0)
        self.calls_seen[unit] = n + 1
        probs = self._probabilities(scenario, cell)
        rng = _stable(self.seed, "call", *unit, n)
        if rng.random() < self.stickiness:
            category = self._draw(_stable(self.seed, "unit", *unit), probs)
        else:
            category = self._draw(rng, probs)
        if scenario.recovery is not None and category == "CORRECT":
            # recovery scenarios open with the natural call, which the
            # service then rejects for want of the parameter it requires
            call = scenario.acceptable_calls[0]
            return responses.openai_call(
                call["tool"], {k: self._literal(v) for k, v in call["args"].items()},
                model=self.model, input_tokens=tokens)
        return self._respond(scenario, category, body["tools"], tokens)
