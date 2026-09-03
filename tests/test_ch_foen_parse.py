import json
from datetime import datetime
from pathlib import Path

import pytest

from rivretrieve._internal.engine import (
    Payload,
    SourceCallOrigin,
    SourceCoordinates,
    UnknownOriginFact,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.ch_foen.config import config
from rivretrieve._internal.providers.ch_foen.parse import parse
from rivretrieve._internal.recordings import read_recording

DATA = Path("tests/test_data")
PRODUCTS = tuple(config().products)


def payload(path):
    r = read_recording(DATA / path)
    return Payload(
        SourceCoordinates("combined"),
        tuple(("2135", p) for p in PRODUCTS),
        _make_fetch_window(
            WindowEndpoint.from_datetime(datetime(2020, 1, 1)), WindowEndpoint.from_datetime(datetime(2026, 9, 2))
        ),
        r.content,
        SourceCallOrigin(
            r.request.url,
            {},
            200,
            r.retrieved_at,
            r.content_type or UnknownOriginFact(),
            UnknownOriginFact(),
            UnknownOriginFact(),
        ),
        (),
    )


def test_rest_parser_maps_all_three_products_utc_and_drops_null_without_quality_inference():
    result = parse(payload("ch_foen_2135_rest_2026-09-01.recording.json"), config())
    assert result.value.columns == ["station_id", "product_id", "time", "value", "time_zone"]
    counts = result.value.group_by("product_id").len().sort("product_id")
    assert dict(counts.iter_rows()) == {
        "discharge_reported": 145,
        "stage_reported": 145,
        "water_temperature_reported": 145,
    }
    assert set(result.value["time_zone"]) == {"+00:00"}
    assert all("quality" not in issue.code for issue in result.issues)


def test_flux_parser_maps_all_products_and_keeps_exclusive_stop_out():
    result = parse(payload("ch_foen_2135_flux_2020-01-01.recording.json"), config())
    assert dict(result.value.group_by("product_id").len().iter_rows()) == {
        "discharge_reported": 6,
        "stage_reported": 6,
        "water_temperature_reported": 6,
    }
    assert result.value["time"].max() == datetime(2020, 1, 1, 0, 50)


def test_parser_does_not_relabel_flow_ls_as_m3s():
    document = {"payload": {"timestamp": [0], "2135|flow_ls": [1000.0]}}
    p = payload("ch_foen_2135_rest_2026-09-01.recording.json")
    p = Payload(
        p.source_coordinates,
        (("2135", ProductId("discharge_reported")),),
        p.fetch_window,
        json.dumps(document).encode(),
        p.origin,
        (),
    )
    with pytest.raises(Exception, match="no declared field"):
        parse(p, config())


def test_stage_uses_same_unit_height_fallback_but_refuses_two_returned_alternatives():
    base = payload("ch_foen_2135_rest_2026-09-01.recording.json")
    fallback = {"payload": {"timestamp": [0], "2135|height": [501.0]}}
    value = Payload(
        base.source_coordinates,
        (("2135", ProductId("stage_reported")),),
        base.fetch_window,
        json.dumps(fallback).encode(),
        base.origin,
        (),
    )
    assert parse(value, config()).value["value"].to_list() == [501.0]
    ambiguous = {"payload": {"timestamp": [0], "2135|height_abs": [1.0], "2135|height": [501.0]}}
    value = Payload(
        base.source_coordinates,
        (("2135", ProductId("stage_reported")),),
        base.fetch_window,
        json.dumps(ambiguous).encode(),
        base.origin,
        (),
    )
    with pytest.raises(Exception, match="multiple alternatives"):
        parse(value, config())
