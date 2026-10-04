"""The guards are the portfolio's shared figure contract, so they get their own
tests rather than being exercised only through artifact 1's four charts."""

import pytest

from harness.figure_guards import (
    MIN_PHONE_TEXT_PX,
    PHONE_WIDTH_PX,
    group_required,
    phone_pt,
    required_field,
    validate_rows,
)
from harness.publish import NotPublishableError


def test_validate_rows_refuses_empty_input():
    with pytest.raises(ValueError, match="rows must not be empty"):
        validate_rows([])


def test_validate_rows_materializes_a_generator():
    rows = validate_rows(r for r in [{"arm": "A"}])
    assert rows == [{"arm": "A"}]


def test_required_field_names_the_row_and_the_field_when_absent():
    with pytest.raises(NotPublishableError, match="t_total"):
        required_field({"arm": "A", "host_id": "h1"}, "t_total")


def test_required_field_rejects_none_as_firmly_as_absent():
    with pytest.raises(NotPublishableError, match="= None"):
        required_field({"arm": "A", "host_id": "h1", "t_total": None}, "t_total")


def test_group_required_refuses_to_silently_drop_a_group():
    rows = [{"regime": "spread"}, {"regime": "spread"}]
    with pytest.raises(ValueError, match="concentrated"):
        group_required(rows, "regime", ("spread", "concentrated"))


def test_group_required_splits_when_every_group_is_present():
    rows = [{"regime": "spread"}, {"regime": "concentrated"}]
    by = group_required(rows, "regime", ("spread", "concentrated"))
    assert list(by) == ["spread", "concentrated"]
    assert by["spread"] == [{"regime": "spread"}]


def test_phone_pt_inverts_the_downscale_relation():
    # A 12pt callout on an 8-inch canvas renders at 7.8px at phone width.
    assert phone_pt(7.8, 8.0) == pytest.approx(12.0, abs=0.1)
    assert MIN_PHONE_TEXT_PX < 7.8
    assert PHONE_WIDTH_PX == 375
