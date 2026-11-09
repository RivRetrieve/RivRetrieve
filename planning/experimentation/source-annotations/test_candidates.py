"""Handwritten synthetic controls; no publisher observations or meanings."""

import polars as pl
import polars.testing as pt
import pytest
from candidates import build


@pytest.fixture
def records():
    # Same time across series, duplicate values, exact duplicate source records,
    # null measurement, absent/null/blank/list and integer annotation shapes.
    return [
        {"series_id": "a", "time": 1, "value": 4.0, "status": "accepted", "tag": "estimate", "code": 2},
        {"series_id": "a", "time": 1, "value": 4.0, "status": "pending", "tag": ["estimate"], "code": 0},
        {"series_id": "a", "time": 1, "value": 4.0, "status": "pending", "tag": ["estimate"], "code": 0},
        {"series_id": "b", "time": 1, "value": None, "status": None, "tag": []},
        {"series_id": "a", "time": 2, "value": 5.0, "tag": ""},
    ]


@pytest.mark.parametrize("candidate", ["columns", "linked", "long", "json"])
def test_candidates_keep_occurrences_and_source_shapes(records, candidate):
    view = build(records, candidate).view()
    pt.assert_frame_equal(
        view.select("occurrence", "series_id", "time", "value"),
        pl.DataFrame(
            {
                "occurrence": ["synthetic:0", "synthetic:1", "synthetic:2", "synthetic:3", "synthetic:4"],
                "series_id": ["a", "a", "a", "b", "a"],
                "time": [1, 1, 1, 1, 2],
                "value": [4.0, 4.0, 4.0, None, 5.0],
            }
        ),
    )
    assert view["status__present"].to_list() == [True, True, True, True, False]
    assert view["status"].to_list() == ["accepted", "pending", "pending", None, None]
    assert view["tag"].to_list() == [
        {"kind": "string", "string": "estimate", "strings": None},
        {"kind": "list", "string": None, "strings": ["estimate"]},
        {"kind": "list", "string": None, "strings": ["estimate"]},
        {"kind": "list", "string": None, "strings": []},
        {"kind": "string", "string": "", "strings": None},
    ]
    assert view["code"].dtype == pl.Int64


@pytest.mark.parametrize("candidate", ["columns", "linked", "long", "json"])
def test_discovery_and_personal_rule_preserve_association(records, candidate):
    result = build(records, candidate)
    assert result.fields().select("source_name", "meaning").rows() == [
        ("status", None),
        ("tag", None),
        ("code", None),
    ]
    view = result.view().filter(pl.col("time") == 1).with_columns(pl.col("value") * 2)
    chosen = view.filter(pl.col("status") == "pending")
    assert chosen.select("occurrence", "series_id", "value", "code").rows() == [
        ("synthetic:1", "a", 8.0, 0),
        ("synthetic:2", "a", 8.0, 0),
    ]


def test_linked_refuses_dangling_annotation(records):
    result = build(records, "linked")
    result.annotations = result.annotations.with_columns(
        pl.when(pl.col("occurrence") == "synthetic:0")
        .then(pl.lit("missing"))
        .otherwise(pl.col("occurrence"))
        .alias("occurrence")
    )
    with pytest.raises(ValueError, match="occurrence"):
        result.view()


@pytest.mark.parametrize("candidate", ["columns", "linked", "long", "json"])
def test_null_tag_differs_from_absent_and_empty_result(candidate):
    result = build(
        [
            {"series_id": "a", "time": 1, "value": None, "tag": None},
            {"series_id": "a", "time": 1, "value": None},
        ],
        candidate,
    )
    assert result.view().select("occurrence", "tag", "tag__present").rows() == [
        ("synthetic:0", None, True),
        ("synthetic:1", None, False),
    ]
    empty = build([], candidate)
    assert empty.view().height == 0
    assert empty.fields()["source_name"].to_list() == ["status", "tag", "code"]
