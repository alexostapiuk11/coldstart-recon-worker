"""The provider interface: build a request, send it, parse the response.

Two providers, OpenAI's Responses API and Anthropic's Messages API (amendment
§3, §7). Everything provider-specific is in this file. The request builders and
response parsers are pure functions over plain dicts in each provider's
documented JSON shape, so they are tested against hand-authored responses with
no SDK installed and no network. The SDKs are imported only inside `send`.

A response whose terminal state is not one of the documented clean ones (a
failed or cancelled OpenAI response, an Anthropic `pause_turn`, a response with
no usage) parses to finish "error", never to a silent "stop".

Every call keeps the exact request body it sent. That body is the evidence the
rendering was the only thing that differed between cells (August §4).

A conversation is a provider-neutral transcript, a list of:
    {"role": "user", "text": str}
    {"role": "assistant", "raw": <the provider's output, echoed back unchanged>}
    {"role": "tool", "call_id": str, "content": str, "is_error": bool}
Echoing the assistant's raw output keeps any reasoning or thinking items the
provider requires on the next turn.
"""

import json
from dataclasses import dataclass, field

from toolcall.formulation import SYSTEM_PROMPT

OPENAI = "openai"
ANTHROPIC = "anthropic"


@dataclass(frozen=True)
class ModelSettings:
    provider: str
    model: str
    temperature: float | None  # None: the provider default (amendment §3)
    max_output_tokens: int = 1024
    reasoning_effort: str | None = None  # OpenAI: "none"
    thinking: str | None = None  # Anthropic: "between_tools"
    constrained: bool = False  # provider strict mode; on only in the exploratory slice

    def __post_init__(self) -> None:
        if self.provider not in (OPENAI, ANTHROPIC):
            raise ValueError(f"provider {self.provider!r}")
        if self.provider == ANTHROPIC and self.reasoning_effort is not None:
            raise ValueError("reasoning_effort is an OpenAI setting")
        if self.provider == OPENAI and self.thinking is not None:
            raise ValueError("thinking is an Anthropic setting")
        if self.provider == OPENAI and self.reasoning_effort is None:
            raise ValueError("amendment §3: an OpenAI setting must set reasoning_effort")
        if self.provider == ANTHROPIC and self.thinking is None:
            raise ValueError("amendment §3: an Anthropic setting must set thinking")
        if self.provider == ANTHROPIC and self.temperature is not None:
            raise ValueError("amendment §3: Sonnet 5.5 refuses a temperature; use None")

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: str  # the raw JSON text the model produced; parsed by the grader


@dataclass(frozen=True)
class Parsed:
    calls: tuple[ToolCall, ...]
    text: str
    # "tool_call" | "stop" | "refused" | "truncated" | "error"; "error" is any
    # terminal state not listed above, or a response with no usage
    finish: str
    usage: dict  # {"input", "cached", "cache_write", "output", "reasoning"}
    model: str
    raw_output: list = field(default_factory=list)


# --- OpenAI Responses API -------------------------------------------------


def openai_strict_parameters(schema: dict) -> dict:
    """OpenAI's strict mode requires every property in `required` and
    `additionalProperties: false`; an optional property is written as a
    union with null instead. Used only when constrained decoding is on (the
    exploratory slice, amendment §4a), so the factorial's schemas are never
    touched by it."""
    props = {}
    required = set(schema.get("required", []))
    for name, prop in schema["properties"].items():
        prop = dict(prop)
        if name not in required:
            prop["type"] = [prop["type"], "null"]
            if "enum" in prop:  # strict mode wants null among the values too
                prop["enum"] = [*prop["enum"], None]
        props[name] = prop
    return {"type": "object", "properties": props, "required": list(props),
            "additionalProperties": False}



def openai_request(settings: ModelSettings, tools: list[dict], transcript: list[dict]) -> dict:
    items: list = []
    for turn in transcript:
        if turn["role"] == "user":
            items.append({"role": "user", "content": turn["text"]})
        elif turn["role"] == "assistant":
            items.extend(turn["raw"])
        elif turn["role"] == "tool":
            items.append(
                {"type": "function_call_output", "call_id": turn["call_id"],
                 "output": turn["content"]}
            )
        else:
            raise ValueError(f"unknown transcript role {turn['role']!r}")
    body = {
        "model": settings.model,
        "instructions": SYSTEM_PROMPT,
        "input": items,
        "tools": [
            {"type": "function", "name": t["name"], "description": t["description"],
             "parameters": (openai_strict_parameters(t["parameters"]) if settings.constrained
                            else t["parameters"]),
             "strict": settings.constrained}
            for t in tools
        ],
        "tool_choice": "auto",
        "parallel_tool_calls": False,
        "max_output_tokens": settings.max_output_tokens,
        "store": False,
    }
    if settings.reasoning_effort is not None:
        body["reasoning"] = {"effort": settings.reasoning_effort}
    if settings.temperature is not None:
        body["temperature"] = settings.temperature
    return body


def openai_parse(response: dict) -> Parsed:
    calls, texts, refused = [], [], False
    for item in response.get("output", []):
        if item.get("type") == "function_call":
            calls.append(ToolCall(item["call_id"], item["name"], item["arguments"]))
        elif item.get("type") == "message":
            for part in item.get("content", []):
                if part.get("type") == "output_text":
                    texts.append(part["text"])
                elif part.get("type") == "refusal":
                    refused = True
    reason = (response.get("incomplete_details") or {}).get("reason")
    status = response.get("status")
    if refused or reason == "content_filter":
        finish = "refused"
    elif status == "incomplete" and reason == "max_output_tokens":
        finish = "truncated"
    elif status in ("failed", "cancelled") or status == "incomplete":
        finish = "error"
    elif calls:
        finish = "tool_call"
    else:
        finish = "stop"
    if not response.get("usage"):
        finish = "error"
    u = response.get("usage") or {}
    usage = {
        "input": u.get("input_tokens", 0),
        "cached": (u.get("input_tokens_details") or {}).get("cached_tokens", 0),
        "cache_write": 0,
        "output": u.get("output_tokens", 0),
        "reasoning": (u.get("output_tokens_details") or {}).get("reasoning_tokens", 0),
    }
    return Parsed(tuple(calls), "\n".join(texts), finish, usage, response.get("model", ""),
                  list(response.get("output", [])))


# --- Anthropic Messages API -----------------------------------------------


def anthropic_request(settings: ModelSettings, tools: list[dict], transcript: list[dict]) -> dict:
    messages: list = []
    open_results: list | None = None  # tool_results of the message being filled
    for turn in transcript:
        if turn["role"] != "tool":
            open_results = None
        if turn["role"] == "user":
            messages.append({"role": "user", "content": turn["text"]})
        elif turn["role"] == "assistant":
            messages.append({"role": "assistant", "content": turn["raw"]})
        elif turn["role"] == "tool":
            result = {"type": "tool_result", "tool_use_id": turn["call_id"],
                      "content": turn["content"], "is_error": turn["is_error"]}
            if open_results is not None:  # one message answers every call
                open_results.append(result)
            else:
                open_results = [result]
                messages.append({"role": "user", "content": open_results})
        else:
            raise ValueError(f"unknown transcript role {turn['role']!r}")
    rendered = []
    for t in tools:
        tool = {"name": t["name"], "description": t["description"],
                "input_schema": t["parameters"]}
        if settings.constrained:
            tool["strict"] = True
        rendered.append(tool)
    body = {
        "model": settings.model,
        "max_tokens": settings.max_output_tokens,
        "system": SYSTEM_PROMPT,
        "messages": messages,
        "tools": rendered,
        "tool_choice": {"type": "auto", "disable_parallel_tool_use": True},
    }
    if settings.thinking is not None:
        body["thinking"] = {"type": settings.thinking}
    if settings.temperature is not None:
        body["temperature"] = settings.temperature
    return body


def anthropic_parse(response: dict) -> Parsed:
    calls, texts = [], []
    for block in response.get("content", []):
        if block.get("type") == "tool_use":
            calls.append(ToolCall(block["id"], block["name"], json.dumps(block["input"])))
        elif block.get("type") == "text":
            texts.append(block["text"])
    stop = response.get("stop_reason")
    if stop == "refusal":
        finish = "refused"
    elif stop == "max_tokens":
        finish = "truncated"
    elif stop not in ("end_turn", "tool_use", "stop_sequence"):
        finish = "error"
    elif calls:
        finish = "tool_call"
    else:
        finish = "stop"
    if not response.get("usage"):
        finish = "error"
    u = response.get("usage") or {}
    read = u.get("cache_read_input_tokens") or 0
    write = u.get("cache_creation_input_tokens") or 0
    usage = {
        "input": (u.get("input_tokens") or 0) + read + write,
        "cached": read,
        "cache_write": write,
        "output": u.get("output_tokens") or 0,
        "reasoning": 0,
    }
    return Parsed(tuple(calls), "\n".join(texts), finish, usage, response.get("model", ""),
                  list(response.get("content", [])))


BUILD = {OPENAI: openai_request, ANTHROPIC: anthropic_request}
PARSE = {OPENAI: openai_parse, ANTHROPIC: anthropic_parse}


# --- Clients --------------------------------------------------------------


class Client:
    """Builds and sends one request. `send` returns (request body, response
    dict); `request` and `post` are its two halves, so a caller can keep the
    body even when the post raises."""

    def __init__(self, settings: ModelSettings, sdk=None):
        self.settings = settings
        self._sdk = sdk

    def request(self, tools: list[dict], transcript: list[dict]) -> dict:
        return BUILD[self.settings.provider](self.settings, tools, transcript)

    def post(self, body: dict) -> dict:
        if self._sdk is None:
            if self.settings.provider == OPENAI:
                from openai import OpenAI

                self._sdk = OpenAI()
            else:
                from anthropic import Anthropic

                self._sdk = Anthropic()
        if self.settings.provider == OPENAI:
            return self._sdk.responses.create(**body).model_dump(exclude_none=True)
        return self._sdk.messages.create(**body).model_dump(exclude_none=True)

    def send(self, tools: list[dict], transcript: list[dict]) -> tuple[dict, dict]:
        body = self.request(tools, transcript)
        return body, self.post(body)


class ScriptedClient(Client):
    """No network. `policy(body)` returns a response dict in the provider's
    documented shape (toolcall/responses.py builds them). The request body is
    still built by the real builder, so dry runs exercise it."""

    def __init__(self, settings: ModelSettings, policy):
        super().__init__(settings, sdk=None)
        self.policy = policy
        self.sent: list[dict] = []

    def post(self, body: dict) -> dict:
        self.sent.append(body)
        return self.policy(body)
