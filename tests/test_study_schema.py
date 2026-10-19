import pytest

from study.schema import ContentError, validate
from tests.study_examples import artifact_unit, artifact_unit_with_links, prereq_unit


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


# ---- relationships (traceability) ----


def test_linked_unit_passes():
    validate(artifact_unit_with_links())


def test_units_without_requirement_ids_need_no_links():
    u = artifact_unit()
    assert "serves" not in u["decisions"][0]
    validate(u)


def test_requirement_ids_are_unique():
    u = artifact_unit_with_links()
    u["requirements"][1]["id"] = "R1"
    _fails(u, r"requirements\[1\].*duplicate id 'R1'")


def test_once_one_requirement_has_an_id_all_need_one():
    u = artifact_unit_with_links()
    del u["requirements"][2]["id"]
    _fails(u, r"requirements\[2\].*'id'")


def test_short_labels_are_bounded():
    for path in (("requirements", 0), ("decisions", 0), ("results", 0), ("concepts", 0)):
        u = artifact_unit_with_links()
        u[path[0]][path[1]]["short"] = "x" * 41
        _fails(u, rf"{path[0]}\[0\]\.short longer than 40")


def test_result_takeaway_is_one_bounded_sentence():
    u = artifact_unit_with_links()
    u["results"][0]["takeaway"] = "x" * 201
    _fails(u, r"results\[0\]\.takeaway longer than 200")
    u["results"][0]["takeaway"] = 5
    _fails(u, r"results\[0\]\.takeaway: expected str")


def test_every_decision_serves_a_requirement():
    u = artifact_unit_with_links()
    u["decisions"][2]["serves"] = []
    _fails(u, r"decisions\[2\]\.serves: needs at least 1")
    del u["decisions"][2]["serves"]
    _fails(u, r"decisions\[2\].*'serves'")


def test_every_requirement_is_served_or_says_why_not():
    u = artifact_unit_with_links()
    del u["requirements"][2]["unlinked_reason"]
    _fails(u, r"requirements\[2\] 'R3'.*no decision serves it.*unlinked_reason")


def test_unlinked_reason_contradicts_a_serving_decision():
    u = artifact_unit_with_links()
    u["requirements"][0]["unlinked_reason"] = "None."
    _fails(u, r"requirements\[0\] 'R1'.*unlinked_reason.*served by")


def test_every_result_supports_a_decision_or_says_why_not():
    u = artifact_unit_with_links()
    del u["results"][1]["so_none_reason"]
    _fails(u, r"results\[1\].*so.*so_none_reason")
    u = artifact_unit_with_links()
    u["results"][0]["so"] = []
    _fails(u, r"results\[0\].*so.*so_none_reason")


def test_result_so_and_so_none_reason_are_exclusive():
    u = artifact_unit_with_links()
    u["results"][0]["so_none_reason"] = "None."
    _fails(u, r"results\[0\].*both")


def test_result_so_may_be_a_list_of_real_decisions():
    u = artifact_unit_with_links()
    u["results"][0]["so"] = ["d0", "nope"]
    _fails(u, r"results\[0\]\.so 'nope' is not a decision id")
    u["results"][0]["so"] = ["d0", 3]
    _fails(u, r"results\[0\]\.so")
    u = artifact_unit()
    u["results"][0]["so"] = ["d0", "d1"]
    validate(u)


def test_references_must_exist():
    u = artifact_unit_with_links()
    u["decisions"][0]["serves"][0]["req"] = "R9"
    _fails(u, r"decisions\[0\]\.serves\[0\]\.req 'R9' is not a requirement id")
    u = artifact_unit_with_links()
    u["decisions"][0]["uses"][0]["concept"] = "nope"
    _fails(u, r"decisions\[0\]\.uses\[0\]\.concept 'nope' is not a concept id")
    u = artifact_unit_with_links()
    u["flow"][0]["decision"] = "nope"
    _fails(u, r"flow\[0\]\.decision 'nope' is not a decision id")


def test_every_because_is_non_empty():
    u = artifact_unit_with_links()
    u["decisions"][1]["serves"][1]["because"] = "  "
    _fails(u, r"decisions\[1\]\.serves\[1\]\.because is empty")
    u = artifact_unit_with_links()
    u["decisions"][0]["uses"][0]["because"] = ""
    _fails(u, r"decisions\[0\]\.uses\[0\]\.because is empty")
    u = artifact_unit_with_links()
    del u["decisions"][0]["uses"][0]["because"]
    _fails(u, r"decisions\[0\]\.uses\[0\].*'because'")


def test_concept_ids_are_unique():
    u = artifact_unit_with_links()
    u["concepts"][1]["id"] = "arms"
    _fails(u, r"concepts\[1\].*duplicate id 'arms'")


def test_optional_reason_fields_must_be_non_empty_strings():
    u = artifact_unit_with_links()
    u["requirements"][2]["unlinked_reason"] = ""
    _fails(u, r"requirements\[2\]\.unlinked_reason is empty")
    u = artifact_unit_with_links()
    u["results"][1]["so_none_reason"] = 1
    _fails(u, r"results\[1\]\.so_none_reason: expected str")


def test_link_fields_are_checked_even_without_requirement_ids():
    u = artifact_unit()
    u["decisions"][0]["uses"] = [{"concept": "nope", "because": "x"}]
    _fails(u, r"uses\[0\]\.concept 'nope' is not a concept id")


def _interval():
    return {"type": "interval", "unit": "s", "zero_label": "no difference",
            "left_label": "B faster", "right_label": "A faster",
            "rows": [{"label": "A minus B", "estimate": -10.39, "low": -12.5, "high": -8.25},
                     {"label": "B minus C", "estimate": 1.5, "low": -0.5, "high": 3.25}]}


def test_interval_chart_validates():
    u = artifact_unit()
    u["results"][0]["chart"] = _interval()
    validate(u)


def test_interval_rows_need_numbers_in_order():
    u = artifact_unit()
    u["results"][0]["chart"] = _interval()
    u["results"][0]["chart"]["rows"][0]["low"] = "low"
    _fails(u, r"rows\[0\]\.low: expected float")
    u["results"][0]["chart"] = _interval()
    u["results"][0]["chart"]["rows"][1]["low"] = 2.0
    _fails(u, r"rows\[1\].*low <= estimate <= high")
    u["results"][0]["chart"] = _interval()
    u["results"][0]["chart"]["rows"] = []
    _fails(u, "rows")
    u["results"][0]["chart"] = _interval()
    del u["results"][0]["chart"]["rows"][0]["label"]
    _fails(u, r"rows\[0\].*'label'")
    u["results"][0]["chart"] = _interval()
    u["results"][0]["chart"]["zero_label"] = 0
    _fails(u, "zero_label: expected str")
    u["results"][0]["chart"] = dict(_interval(), shade="up")
    _fails(u, "shade")
    u["results"][0]["chart"] = dict(_interval(), shade="left")
    validate(u)


def test_stacked_chart_deltas_and_highlight_are_checked():
    u = artifact_unit()
    ch = u["results"][0]["chart"]
    ch["deltas"] = [{"between": "A → C", "text": "Compile time nearly vanishes."}]
    ch["highlight"] = ["compile"]
    validate(u)
    ch["deltas"] = [{"between": "A → C", "text": ""}]
    _fails(u, r"deltas\[0\]\.text is empty")
    ch["deltas"] = [{"between": "A → C"}]
    _fails(u, r"deltas\[0\].*'text'")
    ch["deltas"] = "A to C"
    _fails(u, r"deltas: expected list")
    del ch["deltas"]
    ch["highlight"] = ["warmup"]
    _fails(u, r"highlight 'warmup' is not a segment name")
    ch["highlight"] = "compile"
    _fails(u, r"highlight: expected list")


def test_deltas_and_highlight_belong_to_stacked_bars_only():
    u = artifact_unit()
    u["results"][0]["chart"] = {"type": "bars", "unit": "s", "highlight": ["a"],
                                "items": [{"label": "a", "value": 1.5}]}
    _fails(u, r"highlight.*stacked_bars")


def _percentiles():
    return {"type": "percentiles", "unit": "s", "note": "One run of 300 was far slower.",
            "rows": [{"label": "A", "values": [{"name": "p50", "value": 81.1},
                                               {"name": "p90", "value": 96.3},
                                               {"name": "p95", "value": 96.4}],
                      "max_label": {"text": "largest run", "value": 148.2}},
                     {"label": "B", "values": [{"name": "p50", "value": 70.0},
                                               {"name": "p90", "value": 80.5}]}]}


def test_percentiles_chart_validates():
    u = artifact_unit()
    u["results"][0]["chart"] = _percentiles()
    validate(u)


def test_percentiles_chart_fields_are_checked():
    def bad(change, match):
        u = artifact_unit()
        ch = _percentiles()
        change(ch)
        u["results"][0]["chart"] = ch
        _fails(u, match)

    bad(lambda ch: ch["rows"][0].pop("values"), r"rows\[0\].*'values'")
    bad(lambda ch: ch["rows"][0].update(values=[]), r"rows\[0\]\.values: needs at least 1")
    bad(lambda ch: ch["rows"][0]["values"][0].update(value="81"), r"values\[0\]\.value: expected float")
    bad(lambda ch: ch["rows"][0]["values"][0].update(value=-1.0), r"values\[0\]\.value.*negative")
    bad(lambda ch: ch["rows"][0]["values"][1].update(name="p50"), r"duplicate percentile 'p50'")
    bad(lambda ch: ch["rows"][0]["max_label"].update(value=90.0), r"max_label.*below")
    bad(lambda ch: ch["rows"][0]["max_label"].update(text=" "), r"max_label\.text is empty")
    bad(lambda ch: ch.update(note=3), r"note: expected str")
    bad(lambda ch: ch.update(rows=[]), "rows")
    bad(lambda ch: ch.update(highlight=["p50"]), r"highlight.*stacked_bars")


def _three_phase():
    return {"type": "stacked_bars", "unit": "s", "bars": [
        {"label": "B", "segments": [{"name": "load", "value": 30.35},
                                    {"name": "compile", "value": 18.79},
                                    {"name": "rest", "value": 8.0}]},
        {"label": "C", "segments": [{"name": "load", "value": 21.34},
                                    {"name": "compile", "value": 0.33},
                                    {"name": "rest", "value": 8.0}]}]}


def test_merge_and_ghost_validate():
    u = artifact_unit()
    u["results"][0]["chart"] = dict(_three_phase(),
                                    merge=[{"names": ["load", "rest"], "label": "Other"}],
                                    ghost={"segment": "compile", "from_bar": "B", "on_bar": "C"})
    validate(u)
    # a ghost may name a merged segment by its label
    u["results"][0]["chart"]["ghost"]["segment"] = "Other"
    validate(u)


def test_merge_fields_are_checked():
    def bad(merge, match):
        u = artifact_unit()
        u["results"][0]["chart"] = dict(_three_phase(), merge=merge)
        _fails(u, match)

    bad([{"names": ["load", "nope"], "label": "x"}], r"merge\[0\].*'nope' is not a segment name")
    bad([{"names": ["load"], "label": "x"}], r"merge\[0\]\.names: needs at least 2")
    bad([{"names": ["load", "rest"], "label": " "}], r"merge\[0\]\.label is empty")
    bad([{"names": ["load", "rest"], "label": "a"}, {"names": ["rest", "compile"], "label": "b"}],
        r"merge\[1\].*'rest' is already merged")
    bad({"names": ["load", "rest"], "label": "x"}, r"merge: expected list")
    u = artifact_unit()
    u["results"][0]["chart"] = {"type": "bars", "unit": "s", "items": [{"label": "a", "value": 1.0}],
                                "merge": [{"names": ["a", "b"], "label": "x"}]}
    _fails(u, r"merge.*stacked_bars")


def test_ghost_fields_are_checked():
    def bad(ghost, match):
        u = artifact_unit()
        u["results"][0]["chart"] = dict(_three_phase(), ghost=ghost)
        _fails(u, match)

    bad({"segment": "nope", "from_bar": "B", "on_bar": "C"}, r"ghost\.segment 'nope'.*bar 'B'")
    bad({"segment": "compile", "from_bar": "X", "on_bar": "C"}, r"ghost\.from_bar 'X' is not a bar")
    bad({"segment": "compile", "from_bar": "B", "on_bar": "Y"}, r"ghost\.on_bar 'Y' is not a bar")
    bad({"segment": "compile", "from_bar": "B", "on_bar": "B"}, r"ghost.*two different bars")
    bad({"segment": "compile", "from_bar": "B"}, r"ghost.*'on_bar'")


def test_links_and_prereqs_validate():
    u = artifact_unit()
    u["links"] = {"p1": "https://claude.ai/artifact/abc"}
    u["prereqs"] = [{"unit": "p1", "label": "LLM serving on a GPU"}]
    u["decisions"][0]["why"] = "See [the KV cache](p1:kvcache) and [arms](x1:arms)."
    validate(u)


def test_links_and_prereqs_are_checked():
    u = artifact_unit()
    u["links"] = {"p1": "http://example.com"}
    _fails(u, r"links\.p1 must begin with https://")
    u["links"] = ["p1"]
    _fails(u, r"links: expected dict")
    u = artifact_unit()
    u["prereqs"] = [{"unit": "p1", "label": " "}]
    _fails(u, r"prereqs\[0\]\.label is empty")
    u["prereqs"] = [{"label": "x"}]
    _fails(u, r"prereqs\[0\].*'unit'")


def test_an_inline_link_must_name_a_known_unit():
    u = artifact_unit()
    u["decisions"][1]["why"] = "See [the KV cache](p9:kvcache)."
    _fails(u, r"decisions\[1\]\.why: link to unknown unit 'p9'")
    u["prereqs"] = [{"unit": "p9", "label": "Nine"}]
    validate(u)
