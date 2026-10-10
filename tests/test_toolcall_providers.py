"""Request builders and response parsers against hand-authored responses in
each provider's documented shape (tests/fixtures/a3/). No SDK, no network."""

import json
from pathlib import Path

import pytest

from tests.a3_examples import library, scenario
from toolcall.formulation import SYSTEM_PROMPT, Formulation, render
from toolcall.providers import (
    Client,
    ModelSettings,
    ScriptedClient,
    anthropic_parse,
    anthropic_request,
    openai_parse,
    openai_request,
)
from toolcall.responses import (
    anthropic_text,
    openai_refusal,
    openai_text,
    openai_truncated,
)

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


# --- review fixes -----------------------------------------------------------

USAGE_OA = {"input_tokens": 10, "output_tokens": 2}
USAGE_AN = {"input_tokens": 10, "output_tokens": 2}


class _Dumpable:
    def __init__(self, payload):
        self.payload = payload
        self.dump_kwargs = None

    def model_dump(self, **kwargs):
        self.dump_kwargs = kwargs
        return self.payload


class _Endpoint:
    def __init__(self, payload):
        self.result = _Dumpable(payload)
        self.received = None

    def create(self, **body):
        self.received = body
        return self.result


class _FakeSdk:
    def __init__(self, payload):
        self.responses = _Endpoint(payload)
        self.messages = _Endpoint(payload)


def test_post_passes_the_body_through_and_asks_for_no_null_fields():
    for settings, endpoint in ((MINI, "responses"), (SONNET, "messages")):
        payload = {"id": "x", "output": [], "content": []}
        sdk = _FakeSdk(payload)
        client = Client(settings, sdk=sdk)
        body = client.request(_tools(), [{"role": "user", "text": "x"}])
        before = json.dumps(body, sort_keys=True)
        assert client.post(body) is payload
        ep = getattr(sdk, endpoint)
        assert json.dumps(ep.received, sort_keys=True) == before
        assert ep.result.dump_kwargs == {"exclude_none": True}


def test_each_setting_the_amendment_fixes_is_required():
    with pytest.raises(ValueError, match="§3"):
        ModelSettings("openai", "gpt-5.4-mini-2026-03-17", 0.0)
    with pytest.raises(ValueError, match="§3"):
        ModelSettings("anthropic", "claude-sonnet-5-5", None)
    with pytest.raises(ValueError, match="§3"):
        ModelSettings("anthropic", "claude-sonnet-5-5", 0.0, thinking="between_tools")


def _two_results():
    return [
        {"role": "user", "text": "go"},
        {"role": "assistant", "raw": [
            {"type": "function_call", "call_id": "c1", "name": "a", "arguments": "{}"},
            {"type": "function_call", "call_id": "c2", "name": "b", "arguments": "{}"}]},
        {"role": "tool", "call_id": "c1", "content": "one", "is_error": False},
        {"role": "tool", "call_id": "c2", "content": "two", "is_error": True},
    ]


def test_every_call_is_answered_in_one_anthropic_message():
    transcript = _two_results()
    transcript[1] = {"role": "assistant", "raw": [
        {"type": "tool_use", "id": "c1", "name": "a", "input": {}},
        {"type": "tool_use", "id": "c2", "name": "b", "input": {}}]}
    messages = anthropic_request(SONNET, _tools(), transcript)["messages"]
    assert len(messages) == 3
    assert messages[-1] == {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "c1", "content": "one", "is_error": False},
        {"type": "tool_result", "tool_use_id": "c2", "content": "two", "is_error": True}]}


def test_every_call_gets_its_own_openai_output_in_order():
    items = openai_request(MINI, _tools(), _two_results())["input"]
    assert items[-2:] == [
        {"type": "function_call_output", "call_id": "c1", "output": "one"},
        {"type": "function_call_output", "call_id": "c2", "output": "two"}]


def test_the_assistants_raw_output_is_echoed_unchanged():
    oa_raw = [{"type": "reasoning", "id": "rs_1", "summary": []},
              {"type": "function_call", "call_id": "c1", "name": "a", "arguments": "{}"}]
    an_raw = [{"type": "thinking", "thinking": "", "signature": "sig"},
              {"type": "tool_use", "id": "c1", "name": "a", "input": {}}]
    t = [{"role": "user", "text": "go"}]
    oa = openai_request(MINI, _tools(), t + [{"role": "assistant", "raw": oa_raw}])["input"]
    assert oa[1:] == oa_raw
    an = anthropic_request(SONNET, _tools(), t + [{"role": "assistant", "raw": an_raw}])
    assert an["messages"][1] == {"role": "assistant", "content": an_raw}


def test_the_output_cap_is_1024_for_both_providers():
    t = [{"role": "user", "text": "x"}]
    assert openai_request(MINI, _tools(), t)["max_output_tokens"] == 1024
    assert anthropic_request(SONNET, _tools(), t)["max_tokens"] == 1024


def test_two_formulations_of_one_scenario_differ_only_in_the_tools():
    t = [{"role": "user", "text": "x"}]
    for settings, build in ((MINI, openai_request), (SONNET, anthropic_request)):
        a = build(settings, render(scenario(), library(), Formulation("low", "terse", "loose")), t)
        b = build(settings, render(scenario(), library(), Formulation("high", "rich", "strict")), t)
        assert a["tools"] != b["tools"]
        a.pop("tools")
        b.pop("tools")
        assert a == b


def test_openai_refusals_truncation_and_failures():
    assert openai_parse(openai_refusal()).finish == "refused"
    filtered = {"status": "incomplete", "incomplete_details": {"reason": "content_filter"},
                "output": [], "usage": USAGE_OA}
    assert openai_parse(filtered).finish == "refused"
    assert openai_parse(openai_truncated()).finish == "truncated"
    other = {"status": "incomplete", "incomplete_details": {"reason": "something_new"},
             "output": [], "usage": USAGE_OA}
    assert openai_parse(other).finish == "error"
    for status in ("failed", "cancelled"):
        assert openai_parse({"status": status, "output": [], "usage": USAGE_OA}
                            ).finish == "error"


def test_anthropic_max_tokens_and_unknown_stops():
    assert anthropic_parse(anthropic_text("cut", stop_reason="max_tokens")).finish == "truncated"
    for stop in ("pause_turn", "model_context_window_exceeded", None):
        assert anthropic_parse(anthropic_text("x", stop_reason=stop)).finish == "error"
    assert anthropic_parse(anthropic_text("x", stop_reason="stop_sequence")).finish == "stop"


def test_a_response_without_usage_is_an_error_with_zero_usage():
    zero = {"input": 0, "cached": 0, "cache_write": 0, "output": 0, "reasoning": 0}
    for usage in (None, {}):
        oa = {"status": "completed", "output": [], "model": "m"}
        an = {"stop_reason": "end_turn", "content": [], "model": "m"}
        if usage is not None:
            oa["usage"] = usage
            an["usage"] = usage
        assert openai_parse(oa).finish == "error" and openai_parse(oa).usage == zero
        assert anthropic_parse(an).finish == "error" and anthropic_parse(an).usage == zero
    oa_null = {"status": "completed", "output": [], "usage": None}
    assert openai_parse(oa_null).finish == "error"


def test_text_and_a_call_together_and_two_calls_keep_everything_in_order():
    oa = {"status": "completed", "usage": USAGE_OA, "output": [
        {"type": "reasoning", "id": "rs_1", "summary": []},
        {"type": "message", "role": "assistant", "content": [
            {"type": "output_text", "text": "Looking.", "annotations": []}]},
        {"type": "function_call", "call_id": "c1", "name": "a", "arguments": "{}"},
        {"type": "function_call", "call_id": "c2", "name": "b", "arguments": "{}"}]}
    p = openai_parse(oa)
    assert p.finish == "tool_call" and p.text == "Looking."
    assert [c.call_id for c in p.calls] == ["c1", "c2"]
    assert p.raw_output == oa["output"] and p.raw_output[0]["type"] == "reasoning"
    an = {"stop_reason": "tool_use", "usage": USAGE_AN, "content": [
        {"type": "text", "text": "Looking."},
        {"type": "tool_use", "id": "t1", "name": "a", "input": {}},
        {"type": "tool_use", "id": "t2", "name": "b", "input": {"x": 1}}]}
    p = anthropic_parse(an)
    assert p.finish == "tool_call" and p.text == "Looking."
    assert [c.call_id for c in p.calls] == ["t1", "t2"]
    assert p.raw_output == an["content"]


def test_anthropic_cache_writes_count_as_input_and_as_cache_write():
    r = anthropic_text("x")
    r["usage"] = {"input_tokens": 100, "cache_creation_input_tokens": 300,
                  "cache_read_input_tokens": 50, "output_tokens": 7}
    u = anthropic_parse(r).usage
    assert u["input"] == 450 and u["cache_write"] == 300 and u["cached"] == 50
