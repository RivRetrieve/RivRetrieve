import json
from datetime import datetime
from pathlib import Path

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


def payload(retained_evidence_root: Path, path):
    r = read_recording((retained_evidence_root / DATA) / path)
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


def test_rest_parser_maps_all_three_products_utc_without_quality_inference(retained_evidence_root: Path):
    result = parse(payload(retained_evidence_root, "ch_foen_2135_rest_2026-09-01.recording.json"), config())
    assert result.rows.columns == [
        "station_id",
        "product_id",
        "time",
        "value",
        "time_zone",
        "series_id",
        "facts_id",
        "source_unit",
    ]
    counts = result.rows.group_by("product_id").len().sort("product_id")
    assert dict(counts.iter_rows()) == {
        "discharge_reported": 145,
        "stage_reported": 145,
        "water_temperature_reported": 145,
    }
    assert set(result.rows["time_zone"]) == {"+00:00"}
    assert all("quality" not in issue.code for issue in result.issues)


def test_flux_parser_maps_all_products_and_keeps_exclusive_stop_out(retained_evidence_root: Path):
    result = parse(payload(retained_evidence_root, "ch_foen_2135_flux_2020-01-01.recording.json"), config())
    assert dict(result.rows.group_by("product_id").len().iter_rows()) == {
        "discharge_reported": 6,
        "stage_reported": 6,
        "water_temperature_reported": 6,
    }
    assert result.rows["time"].max() == datetime(2020, 1, 1, 0, 50)


def test_parser_does_not_relabel_flow_ls_as_m3s(retained_evidence_root: Path):
    document = {"payload": {"timestamp": [0], "2135|flow_ls": [1000.0]}}
    p = payload(retained_evidence_root, "ch_foen_2135_rest_2026-09-01.recording.json")
    p = Payload(
        p.source_coordinates,
        (("2135", ProductId("discharge_reported")),),
        p.fetch_window,
        json.dumps(document).encode(),
        p.origin,
        (),
    )
    result = parse(p, config())
    assert result.rows["source_unit"].to_list() == ["l/s"]
    assert result.rows["value"].to_list() == [1000.0]


def test_stage_preserves_distinct_height_fields_without_fallback_or_coalescing(retained_evidence_root: Path):
    base = payload(retained_evidence_root, "ch_foen_2135_rest_2026-09-01.recording.json")
    fallback = {"payload": {"timestamp": [0], "2135|height": [501.0]}}
    value = Payload(
        base.source_coordinates,
        (("2135", ProductId("stage_reported")),),
        base.fetch_window,
        json.dumps(fallback).encode(),
        base.origin,
        (),
    )
    assert parse(value, config()).rows["value"].to_list() == [501.0]
    ambiguous = {"payload": {"timestamp": [0], "2135|height_abs": [1.0], "2135|height": [501.0]}}
    value = Payload(
        base.source_coordinates,
        (("2135", ProductId("stage_reported")),),
        base.fetch_window,
        json.dumps(ambiguous).encode(),
        base.origin,
        (),
    )
    result = parse(value, config())
    assert result.rows["value"].sort().to_list() == [1.0, 501.0]
    assert result.rows["series_id"].n_unique() == 2
