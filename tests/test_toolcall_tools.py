import json

import pytest

from tests.a3_examples import MISC, TRAVEL, library
from toolcall.tools import ParamSpec, ToolSpec, canonical_schema, load_library, tool_from_dict


def _p(**kw):
    base = {"name": "x", "type": "string", "required": True, "terse": "X.", "rich": "The x."}
    return ParamSpec(**{**base, **kw})


def test_the_canonical_schema_is_the_strict_form_without_descriptions():
    schema = canonical_schema(library().get("search_flights"))
    assert schema["required"] == ["origin", "destination", "date"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["cabin"] == {
        "type": "string", "enum": ["economy", "premium", "business"]}
    assert "description" not in schema["properties"]["origin"]


@pytest.mark.parametrize("kw, match", [
    ({"type": "object"}, "closed subset"),
    ({"type": "array"}, "items"),
    ({"type": "integer", "enum": ("a",)}, "strings only"),
    ({"enum": ("a",), "pattern": "^a$"}, "not both"),
    ({"rich": " "}, "both descriptions"),
    ({"name": "Bad-Name"}, "snake_case"),
])
def test_parameters_outside_the_closed_subset_are_refused(kw, match):
    with pytest.raises(ValueError, match=match):
        _p(**kw)


def test_a_tool_needs_a_required_parameter_and_unique_names():
    with pytest.raises(ValueError, match="required parameter"):
        ToolSpec("t", "d", "T.", "The t.", (_p(required=False),))
    with pytest.raises(ValueError, match="duplicate"):
        ToolSpec("t", "d", "T.", "The t.", (_p(), _p()))


def test_primary_param_is_the_first_required_one():
    assert library().get("search_flights").primary_param.name == "origin"


def test_load_library_reads_every_domain_and_refuses_duplicates(tmp_path):
    for data in (TRAVEL, MISC):
        (tmp_path / f"{data['domain']}.json").write_text(json.dumps(data))
    lib = load_library(tmp_path)
    assert len(lib.tools) == len(TRAVEL["tools"]) + len(MISC["tools"])
    assert next(t.name for t in lib.domain("travel")) == "airport_info"
    (tmp_path / "dupe.json").write_text(json.dumps({"domain": "x", "tools": [TRAVEL["tools"][0]]}))
    with pytest.raises(ValueError, match="defined twice"):
        load_library(tmp_path)


def test_a_draft_tool_is_refused():
    with pytest.raises(ValueError, match="draft"):
        tool_from_dict({**TRAVEL["tools"][0], "draft": True}, "travel")
