"""Synthetic source-shape controls; genuine integration checks are separate."""

import json
from datetime import datetime

import polars as pl
from polars.testing import assert_frame_equal

from rivretrieve._internal.engine import (
    Payload,
    SourceCallOrigin,
    SourceCoordinates,
    UnknownOriginFact,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.providers.pe_senamhi.fetch import SenamhiSourceCoordinates
from rivretrieve._internal.providers.pe_senamhi.parse import parse


def payload(data, route, product="phisis_daily_flow"):
    def endpoint(value):
        return WindowEndpoint.from_datetime(datetime.fromisoformat(value))

    return Payload(
        source_coordinates=SourceCoordinates(route),
        station_products=(("A", product),),
        fetch_window=_make_fetch_window(endpoint("2024-01-01"), endpoint("2024-01-31T23:59:59")),
        content=json.dumps({"status": True, "data": data}).encode(),
        origin=SourceCallOrigin(
            **dict.fromkeys(
                ("url", "request_parameters", "status_code", "retrieved_at", "content_type", "source_path", "query"),
                UnknownOriginFact(),
            )
        ),
        prerequisite_calls=(),
    )


def test_daily_fields_keep_null_negative_and_distinct_identity():
    from rivretrieve._internal.providers.pe_senamhi.config import config

    source = payload(
        {
            "station": {"code": "A"},
            "type": "DAILY",
            "variable": "FLOW",
            "unit": "m3/s",
            "daily": [{"date": "2024-01-02", "current": -999, "minimum": None, "maximum": 7, "previous": 80}],
        },
        SenamhiSourceCoordinates("phisis", "DAILY", "FLOW", "m3/s"),
    )
    result = parse(source, config())
    identities = {s.series_id: s.identity.published_id for s in result.series}
    actual = (
        result.rows.select("series_id", "time", "value")
        .with_columns(pl.col("series_id").replace_strict(identities).alias("field"))
        .drop("series_id")
        .sort("field")
    )
    expected = pl.DataFrame(
        {"time": [datetime(2024, 1, 2)] * 3, "value": [-999.0, 7.0, None], "field": ["current", "maximum", "minimum"]}
    )
    assert_frame_equal(actual, expected)
    assert all(s.facts[0].time_zone.value is None for s in result.series)
    assert {o.status.value for o in result.outcomes} == {"success"}


def test_monthly_cells_preserve_null_absence_duplicates_and_future_dates():
    from rivretrieve._internal.providers.pe_senamhi.config import config

    source = payload(
        {
            "columns": [{"column": "N_NIVELAGUA", "unit": "m"}],
            "readings": [
                {"date": "02/01/2024", "time": "06:00", "values": [{"column": "N_NIVELAGUA", "value": None}]},
                {"date": "03/01/2024", "time": "06:00", "values": []},
                {
                    "date": "2027-01-01",
                    "time": "",
                    "values": [{"column": "N_NIVELAGUA", "value": -9}, {"column": "N_NIVELAGUA", "value": -8}],
                },
            ],
        },
        SenamhiSourceCoordinates("monthly_archive", None, "N_NIVELAGUA", "m"),
        "monthly_archive_n_nivelagua",
    )
    result = parse(source, config())
    assert_frame_equal(
        result.rows.select("time", "value"),
        pl.DataFrame(
            {"time": [datetime(2024, 1, 2, 6), datetime(2027, 1, 1), datetime(2027, 1, 1)], "value": [None, -9.0, -8.0]}
        ),
    )


def test_malformed_rows_are_not_successful_empty():
    from dataclasses import replace

    from rivretrieve._internal.providers.pe_senamhi.config import config

    source = payload(
        {"station": {"code": "A"}, "type": "DAILY", "variable": "FLOW", "unit": "m3/s", "daily": []},
        SenamhiSourceCoordinates("phisis", "DAILY", "FLOW", "m3/s"),
    )
    assert {o.status.value for o in parse(source, config()).outcomes} == {"empty"}
    for content in (source.content.replace(b'"daily": []', b'"daily": [{"date":"bad"}]'),):
        result = parse(replace(source, content=content), config())
        assert result.rows.is_empty()
        assert {o.status.value for o in result.outcomes} == {"unsupported"}
        assert all(o.reason for o in result.outcomes)
