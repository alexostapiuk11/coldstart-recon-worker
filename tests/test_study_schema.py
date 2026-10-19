import pytest

from study.schema import ContentError, validate
from tests.study_examples import artifact_unit, prereq_unit


def test_valid_units_pass():
    validate(artifact_unit())
    validate(prereq_unit())


def _fails(unit, match):
    with pytest.raises(ContentError, match=match):
        validate(unit)


def test_missing_field_is_named():
    u = artifact_unit()
    del u["question"]
    _fails(u, "question")


def test_artifact_needs_all_four_levels_once():
    u = artifact_unit()
    u["views"] = u["views"][:3]
    _fails(u, "levels")
    u = artifact_unit()
    u["views"][3]["level"] = "context"
    _fails(u, "levels")


def test_decision_count_is_four_to_six():
    u = artifact_unit()
    u["decisions"] = u["decisions"][:3]
    _fails(u, "decisions")
    u = artifact_unit()
    u["decisions"] = u["decisions"] * 2
    _fails(u, "decisions")


def test_duplicate_decision_ids_fail():
    u = artifact_unit()
    u["decisions"][1]["id"] = "d0"
    _fails(u, "duplicate")


def test_result_must_point_at_a_real_decision():
    u = artifact_unit()
    u["results"][0]["so"] = "nope"
    _fails(u, "so")


def test_edge_to_unknown_node_fails():
    u = artifact_unit()
    u["views"][0]["edges"][0]["to"] = "zzz"
    _fails(u, "edge")


def test_node_label_and_sub_length_are_bounded():
    u = artifact_unit()
    u["views"][0]["nodes"][0]["label"] = "x" * 23
    _fails(u, "label")
    u = artifact_unit()
    u["views"][0]["nodes"][0]["sub"] = "x" * 61
    _fails(u, "sub")


def test_node_sub_must_fit_two_lines():
    u = artifact_unit()
    u["views"][0]["nodes"][0]["sub"] = "aaaaaaaaaaaaaaaaaa bbbbbbbbbbbbbbbbbb cccccccccccccccccc"
    _fails(u, "Author.*two lines|two lines.*Author")
    u["views"][0]["nodes"][0]["sub"] = "aaaaaaaaaaaaaaaaaa bbbbbbbbbbbbbbbbbb"
    validate(u)


def test_chart_show_totals_must_be_a_bool_when_present():
    u = artifact_unit()
    u["results"][0]["chart"]["show_totals"] = True
    validate(u)
    u["results"][0]["chart"]["show_totals"] = "yes"
    _fails(u, "show_totals")


def test_two_nodes_cannot_share_a_cell():
    u = artifact_unit()
    u["views"][0]["nodes"][1].update(col=0, row=0)
    _fails(u, "cell")


def test_short_title_is_two_to_four_words():
    u = artifact_unit()
    u["short_title"] = "Solo"
    _fails(u, "short_title")


def test_chart_type_and_numbers_are_checked():
    u = artifact_unit()
    u["results"][0]["chart"]["type"] = "pie"
    _fails(u, "chart")
    u = artifact_unit()
    u["results"][0]["chart"]["bars"][0]["segments"][0]["value"] = "forty"
    _fails(u, "value")


def test_prereq_needs_three_concepts_with_analogy():
    u = prereq_unit()
    u["concepts"] = u["concepts"][:2]
    _fails(u, "concepts")
    u = prereq_unit()
    del u["concepts"][0]["analogy"]
    _fails(u, "analogy")


def test_sources_and_recall_are_required():
    u = artifact_unit()
    u["sources"] = []
    _fails(u, "sources")
    u = artifact_unit()
    u["recall"] = []
    _fails(u, "recall")


def test_derived_number_needs_a_how():
    u = artifact_unit()
    u["derived_numbers"] = [{"value": "1.5"}]
    _fails(u, "how")


def test_decision_needs_one_line_reason_and_cost():
    for key in ("why_short", "cost_short"):
        u = artifact_unit()
        del u["decisions"][0][key]
        _fails(u, key)
        u = artifact_unit()
        u["decisions"][0][key] = "x" * 161
        _fails(u, key)
