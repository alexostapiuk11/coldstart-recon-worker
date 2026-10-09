"""Request builders and response parsers against hand-authored responses in
each provider's documented shape (tests/fixtures/a3/). No SDK, no network."""

import json
from pathlib import Path

import pytest

from tests.a3_examples import library, scenario
from toolcall.formulation import SYSTEM_PROMPT, Formulation, render
from toolcall.providers import (
    ModelSettings,
    ScriptedClient,
    anthropic_parse,
    anthropic_request,
    openai_parse,
    openai_request,
)
from toolcall.responses import openai_text

FIX = Path(__file__).parent / "fixtures" / "a3"
MINI = ModelSettings("openai", "gpt-5.4-mini-2026-03-17", 0.0, reasoning_effort="none")
SONNET = ModelSettings("anthropic", "claude-sonnet-5-5", None, thinking="between_tools")


def _fixture(name):
    return json.loads((FIX / name).read_text())


def _tools():
    return render(scenario(), library(), Formulation("low", "rich", "strict"))


def test_openai_request_pins_every_setting_the_amendment_fixes():
    body = openai_request(MINI, _tools(), [{"role": "user", "text": "hi"}])
    assert body["model"] == "gpt-5.4-mini-2026-03-17"
    assert body["instructions"] == SYSTEM_PROMPT
    assert body["tool_choice"] == "auto"
    assert body["parallel_tool_calls"] is False
    assert body["reasoning"] == {"effort": "none"}
    assert body["temperature"] == 0.0
    assert body["store"] is False
    assert all(t["strict"] is False and t["type"] == "function" for t in body["tools"])


def test_openai_temperature_is_omitted_when_the_default_is_registered():
    s = ModelSettings("openai", "gpt-5.4-mini-2026-03-17", None, reasoning_effort="none")
    assert "temperature" not in openai_request(s, _tools(), [{"role": "user", "text": "x"}])


def test_anthropic_request_disables_parallel_calls_and_sends_no_temperature():
    body = anthropic_request(SONNET, _tools(), [{"role": "user", "text": "hi"}])
    assert body["tool_choice"] == {"type": "auto", "disable_parallel_tool_use": True}
    assert body["thinking"] == {"type": "between_tools"}
    assert "temperature" not in body
    assert all("strict" not in t and "input_schema" in t for t in body["tools"])


def test_constrained_decoding_is_a_setting_not_a_rendering():
    on = ModelSettings("openai", "gpt-5.4-mini-2026-03-17", 0.0, reasoning_effort="none",
                       constrained=True)
    body = openai_request(on, _tools(), [{"role": "user", "text": "x"}])
    assert all(t["strict"] is True for t in body["tools"])
    flights = next(t for t in body["tools"] if t["name"] == "search_flights")["parameters"]
    assert flights["required"] == list(flights["properties"])
    assert flights["properties"]["cabin"]["type"] == ["string", "null"]
    assert flights["properties"]["origin"]["type"] == "string"
    off = openai_request(MINI, _tools(), [{"role": "user", "text": "x"}])
    assert next(t for t in off["tools"] if t["name"] == "search_flights")["parameters"] == next(
        t for t in _tools() if t["name"] == "search_flights")["parameters"]


def test_strict_mode_nullable_enums_carry_null_and_the_input_is_untouched():
    tools = _tools()
    before = json.dumps(tools, sort_keys=True)
    on = ModelSettings("openai", "gpt-5.4-mini-2026-03-17", 0.0, reasoning_effort="none",
                       constrained=True)
    body = openai_request(on, tools, [{"role": "user", "text": "x"}])
    cabin = next(t for t in body["tools"] if t["name"] == "search_flights")[
        "parameters"]["properties"]["cabin"]
    assert cabin["type"] == ["string", "null"]
    assert cabin["enum"] == ["economy", "premium", "business", None]
    assert json.dumps(tools, sort_keys=True) == before


def test_a_transcript_round_trips_tool_results_in_each_shape():
    transcript = [
        {"role": "user", "text": "go"},
        {"role": "assistant", "raw": [{"type": "function_call", "call_id": "c1",
                                       "name": "search_flights", "arguments": "{}"}]},
        {"role": "tool", "call_id": "c1", "content": "Error: timeout.", "is_error": True},
    ]
    oa = openai_request(MINI, _tools(), transcript)["input"]
    assert oa[-1] == {"type": "function_call_output", "call_id": "c1",
                      "output": "Error: timeout."}
    an = anthropic_request(SONNET, _tools(), transcript)["messages"]
    assert an[-1]["content"][0]["type"] == "tool_result"
    assert an[-1]["content"][0]["is_error"] is True


def test_openai_function_call_parses_with_cached_usage():
    p = openai_parse(_fixture("openai_function_call.json"))
    assert p.finish == "tool_call"
    assert p.calls[0].name == "search_flights"
    assert json.loads(p.calls[0].arguments)["passengers"] == 2
    assert p.usage == {"input": 1312, "cached": 1024, "cache_write": 0, "output": 41,
                       "reasoning": 0}
    assert p.model == "gpt-5.4-mini-2026-03-17"


def test_openai_text_and_truncation():
    assert openai_parse(_fixture("openai_message.json")).finish == "stop"
    assert openai_parse(_fixture("openai_incomplete.json")).finish == "truncated"


def test_anthropic_tool_use_parses_and_counts_cache_reads_as_input():
    p = anthropic_parse(_fixture("anthropic_tool_use.json"))
    assert p.finish == "tool_call"
    assert json.loads(p.calls[0].arguments) == {"origin": "JFK", "destination": "SFO",
                                                "date": "2026-11-03"}
    assert p.usage["input"] == 1700 and p.usage["cached"] == 200
    assert p.raw_output[0]["type"] == "thinking"


def test_anthropic_refusal():
    assert anthropic_parse(_fixture("anthropic_refusal.json")).finish == "refused"


def test_settings_refuse_the_other_providers_knobs():
    with pytest.raises(ValueError):
        ModelSettings("anthropic", "claude-sonnet-5-5", None, reasoning_effort="none")
    with pytest.raises(ValueError):
        ModelSettings("openai", "gpt-5.4-mini-2026-03-17", 0.0, thinking="between_tools")


def test_the_scripted_client_builds_the_real_body_and_records_it():
    client = ScriptedClient(MINI, lambda body: openai_text("ok"))
    body, response = client.send(_tools(), [{"role": "user", "text": "x"}])
    assert client.sent == [body]
    assert openai_parse(response).text == "ok"
