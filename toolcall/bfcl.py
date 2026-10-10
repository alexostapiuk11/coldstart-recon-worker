"""Drafts from the Berkeley Function Calling Leaderboard's public data (amendment §6).

BFCL's single-turn entries already carry what a scenario needs: a user
message, function documents and, for the categories with answers, the
acceptable values of every argument. This converts one entry and its answer
into a *draft*: a scenario and tool definitions in this repository's format,
marked `"draft": true`. The loader refuses drafts. An author finishes each
one: writes the terse and rich descriptions, chooses the low set, writes 4-6
confusables, and removes the draft flag. That is why the seed is "public
seed plus authored extension", and why the post can attribute every seed
scenario to its BFCL id and commit.

BFCL types: `dict` (the parameters object), `integer`, `float`, `string`,
`boolean`, `array`. `tuple` and `any` have no equivalent in the closed subset
and raise, so such an entry is skipped rather than approximated. In an answer,
the empty string `""` among an argument's values means the argument may be
omitted.

One entry is one expected call. BFCL's parallel and multiple categories have
several calls in `ground_truth`; there is no single expectation to draft from
them, so they raise like an out-of-subset type does. The caller says whether an
entry is an irrelevance one (no call expected); it is never inferred from a
missing answer, so a lost answer file cannot turn every entry into a no-call
scenario.
"""

import re

TYPES = {"integer": "integer", "float": "number", "number": "number", "string": "string",
         "boolean": "boolean", "array": "array"}


def tool_name(bfcl_name: str) -> str:
    name = re.sub(r"[^a-z0-9_]", "_", bfcl_name.lower())
    return re.sub(r"_+", "_", name).strip("_")


def _first_sentence(text: str) -> str:
    m = re.match(r"(.+?[.!?])(\s|$)", text.strip())
    return (m.group(1) if m else text.strip())[:120]


def draft_tool(fn: dict) -> dict:
    params = []
    props = fn["parameters"].get("properties", {})
    required = set(fn["parameters"].get("required", []))
    for name, spec in props.items():
        t = spec.get("type")
        if t not in TYPES:
            raise ValueError(f"{fn['name']}.{name}: BFCL type {t!r} is outside the closed subset")
        p = {"name": tool_name(name), "type": TYPES[t], "required": name in required,
             "terse": _first_sentence(spec.get("description", name)),
             "rich": spec.get("description", name)}
        if t == "array":
            item = spec.get("items", {}).get("type")
            if item not in TYPES or TYPES[item] == "array":
                raise ValueError(f"{fn['name']}.{name}: array items {item!r} unsupported")
            p["items"] = TYPES[item]
        if spec.get("enum"):
            p["enum"] = list(spec["enum"])
        params.append(p)
    return {"name": tool_name(fn["name"]), "terse": _first_sentence(fn["description"]),
            "rich": fn["description"], "params": params, "draft": True}


def _acceptable(answer_entry: dict) -> dict:
    (fn_name, args), = answer_entry.items()
    call = {"tool": tool_name(fn_name), "args": {}, "may_include": {}}
    for name, values in args.items():
        omit = "" in values
        values = [v for v in values if v != ""]
        if not values:
            continue
        spec = values[0] if len(values) == 1 else {"one_of": values}
        call["may_include" if omit else "args"][tool_name(name)] = spec
    return call


def draft_scenario(entry: dict, answer: dict | None, *, commit: str, domain: str,
                   irrelevance: bool) -> dict:
    users = [m["content"] for turn in entry["question"] for m in turn if m["role"] == "user"]
    if not users:
        raise ValueError(f"{entry['id']}: the entry has no user message")
    if irrelevance and answer is not None:
        raise ValueError(f"{entry['id']}: an irrelevance entry has no answer, but one was given")
    if not irrelevance and answer is None:
        raise ValueError(f"{entry['id']}: no answer was given and the entry is not marked "
                         "irrelevance")
    d = {
        "id": f"bfcl-{tool_name(entry['id'])}",
        "draft": True,
        "source": {"kind": "bfcl", "id": entry["id"], "commit": commit},
        "domain": domain,
        "target_failure_mode": "SPURIOUS" if irrelevance else "WRONG_PARAMS",
        "tools": [tool_name(f["name"]) for f in entry["function"]],
        "confusables": [],
        "user_message": users[-1],
    }
    if irrelevance:
        d["expectation"] = {"no_call_expected": True}
    else:
        truth = answer["ground_truth"]
        if len(truth) != 1:
            raise ValueError(f"{entry['id']}: {len(truth)} calls in ground_truth; a draft "
                             "scenario is exactly one expected call")
        d["expectation"] = {"acceptable_calls": [_acceptable(truth[0])]}
    return d
