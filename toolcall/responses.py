"""Provider responses, hand-built in each provider's documented JSON shape.

For dry runs and tests: the scripted client returns these, so the whole
harness -- parsing, grading, analysis, figures -- runs with no API call
(August §6, "dry-run mode is a build requirement"). Field names follow the
OpenAI Responses API and Anthropic Messages API references; the parser tests
in tests/test_toolcall_providers.py pin the shapes against
tests/fixtures/a3/*.json.
"""

import itertools
import json

_ids = itertools.count(1)


def _usage_openai(input_tokens: int, output_tokens: int, cached: int = 0) -> dict:
    return {
        "input_tokens": input_tokens,
        "input_tokens_details": {"cached_tokens": cached},
        "output_tokens": output_tokens,
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": input_tokens + output_tokens,
    }


def openai_call(name: str, args, *, model="gpt-5.4-mini-2026-03-17", input_tokens=1000,
                output_tokens=40, raw_arguments: str | None = None) -> dict:
    n = next(_ids)
    arguments = raw_arguments if raw_arguments is not None else json.dumps(args)
    return {
        "id": f"resp_{n}", "object": "response", "model": model, "status": "completed",
        "output": [{"type": "function_call", "id": f"fc_{n}", "call_id": f"call_{n}",
                    "name": name, "arguments": arguments, "status": "completed"}],
        "usage": _usage_openai(input_tokens, output_tokens),
    }


def openai_text(text: str, *, model="gpt-5.4-mini-2026-03-17", input_tokens=1000,
                output_tokens=40) -> dict:
    n = next(_ids)
    return {
        "id": f"resp_{n}", "object": "response", "model": model, "status": "completed",
        "output": [{"type": "message", "id": f"msg_{n}", "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": text, "annotations": []}]}],
        "usage": _usage_openai(input_tokens, output_tokens),
    }


def openai_refusal(*, model="gpt-5.4-mini-2026-03-17") -> dict:
    n = next(_ids)
    return {
        "id": f"resp_{n}", "object": "response", "model": model, "status": "completed",
        "output": [{"type": "message", "id": f"msg_{n}", "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "refusal", "refusal": "I can't help with that."}]}],
        "usage": _usage_openai(1000, 10),
    }


def openai_truncated(*, model="gpt-5.4-mini-2026-03-17") -> dict:
    n = next(_ids)
    return {
        "id": f"resp_{n}", "object": "response", "model": model, "status": "incomplete",
        "incomplete_details": {"reason": "max_output_tokens"},
        "output": [{"type": "function_call", "id": f"fc_{n}", "call_id": f"call_{n}",
                    "name": "search_flights", "arguments": '{"origin": "JF',
                    "status": "incomplete"}],
        "usage": _usage_openai(1000, 1024),
    }


def anthropic_call(name: str, args: dict, *, model="claude-sonnet-5-5", input_tokens=1000,
                   output_tokens=40) -> dict:
    n = next(_ids)
    return {
        "id": f"msg_{n}", "type": "message", "role": "assistant", "model": model,
        "content": [{"type": "tool_use", "id": f"toolu_{n}", "name": name, "input": args}],
        "stop_reason": "tool_use", "stop_sequence": None,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens,
                  "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
    }


def anthropic_text(text: str, *, model="claude-sonnet-5-5", stop_reason="end_turn") -> dict:
    n = next(_ids)
    return {
        "id": f"msg_{n}", "type": "message", "role": "assistant", "model": model,
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop_reason, "stop_sequence": None,
        "usage": {"input_tokens": 1000, "output_tokens": 40,
                  "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
    }
