from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve
import rivretrieve._internal.catalogues.artifact as artifact_module
from rivretrieve._internal.catalogue_reader import CatalogueReader
from rivretrieve._internal.engine import (
    Payload,
    SourceCallOrigin,
    SourceCoordinates,
    UnknownOriginFact,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.observations import (
    ObservationDataSchema,
    ObservationProvenance,
    ObservationResult,
    ReceiptAuthorship,
    ReceiptEntry,
    Receipts,
)
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.usgs_nwis.config import config as usgs_nwis_config
from rivretrieve._internal.providers.usgs_nwis.parse import parse

FIXTURE_PATH = Path("tests/test_data/usgs_nwis_07374000_iv_00060_2023-03-12-dst.json")


def _result(data: pl.DataFrame, provider_id: ProviderId | None = None) -> ObservationResult:
    if provider_id is None:
        provider_id = ProviderId("provider-a")
    provenance = ObservationProvenance(
        source="live",
        provider_id=provider_id,
        metadata='{"trace":"kept"}',
    )
    issues = (
        Issue(
            severity="warning",
            code="source.note",
            message="Source note preserved",
            details={"row": 1},
            provider_id=provider_id,
        ),
    )
    origin = SourceCallOrigin(
        url="https://example.invalid/observations",
        request_parameters={"station": "station-1"},
        status_code=200,
        retrieved_at=datetime(2026, 8, 8, 10, 30, tzinfo=UTC),
        content_type="application/json",
        source_path=UnknownOriginFact(),
        query=UnknownOriginFact(),
    )
    receipts = Receipts(
        provider_id=provider_id,
        entries=(
            ReceiptEntry(
                content=b'{"source":"fixture"}', origin=origin, authorship=ReceiptAuthorship.PUBLISHER_PAYLOAD
            ),
        ),
    )
    return ObservationResult(data=data, provenance=provenance, issues=issues, receipts=receipts)


def test_to_utc_fixed_offsets_converts_row_by_row_and_preserves_result_members() -> None:
    input_data = pl.DataFrame(
        {
            "time": [datetime(2026, 1, 1, 0, 15), datetime(2026, 1, 1, 0, 15)],
            "time_zone": ["+05:30", "-03:30"],
            "station_id": ["station-1", "station-1"],
            "product_id": ["flow", "flow"],
            "value": [1.25, None],
        },
        schema=ObservationDataSchema.polars_schema,
    )
    untouched = input_data.clone()
    result = _result(input_data)
    expected = pl.DataFrame(
        {
            "time": [datetime(2025, 12, 31, 18, 45), datetime(2026, 1, 1, 3, 45)],
            "time_zone": ["+00:00", "+00:00"],
            "station_id": ["station-1", "station-1"],
            "product_id": ["flow", "flow"],
            "value": [1.25, None],
        },
        schema=ObservationDataSchema.polars_schema,
    )

    converted = rivretrieve.to_utc(result)

    pl_testing.assert_frame_equal(converted.data, expected, check_exact=True)
    pl_testing.assert_frame_equal(result.data, untouched, check_exact=True)
    assert converted is not result
    assert converted.data is not result.data
    assert converted.provenance is result.provenance
    assert converted.issues is result.issues
    assert converted.receipts is result.receipts
    assert tuple(type(converted).model_fields) == ("data", "provenance", "issues", "receipts")
    assert converted.data.columns == ["time", "time_zone", "station_id", "product_id", "value"]
    assert converted.data.schema == ObservationDataSchema.polars_schema


def test_to_utc_iana_identifiers_use_zone_rules() -> None:
    result = _result(
        pl.DataFrame(
            {
                "time": [datetime(2026, 1, 15, 12, 0), datetime(2026, 7, 15, 12, 0)],
                "time_zone": ["Europe/Zurich", "Europe/Zurich"],
                "station_id": ["station-iana", "station-iana"],
                "product_id": ["level", "level"],
                "value": [2.5, 3.5],
            },
            schema=ObservationDataSchema.polars_schema,
        )
    )
    expected = pl.DataFrame(
        {
            "time": [datetime(2026, 1, 15, 11, 0), datetime(2026, 7, 15, 10, 0)],
            "time_zone": ["+00:00", "+00:00"],
            "station_id": ["station-iana", "station-iana"],
            "product_id": ["level", "level"],
            "value": [2.5, 3.5],
        },
        schema=ObservationDataSchema.polars_schema,
    )

    pl_testing.assert_frame_equal(rivretrieve.to_utc(result).data, expected, check_exact=True)


def test_to_utc_tz_aware_time_dtype_becomes_naive() -> None:
    data = pl.DataFrame(
        {
            "time": [datetime(2026, 1, 15, 12, 0)],
            "time_zone": ["Europe/Zurich"],
            "station_id": ["s"],
            "product_id": ["q"],
            "value": [1.0],
        },
        schema=ObservationDataSchema.polars_schema,
    ).with_columns(pl.col("time").dt.replace_time_zone("America/Chicago"))

    converted = rivretrieve.to_utc(_result(data))

    assert converted.data.schema["time"] == pl.Datetime("us")
    assert converted.data["time"].to_list() == [datetime(2026, 1, 15, 11, 0)]
    assert converted.data["time_zone"].to_list() == ["+00:00"]


def test_to_utc_unknown_zones_refuse_atomically_with_provider_and_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_data = pl.DataFrame(
        {
            "time": [
                datetime(2026, 1, 1, 0, 0),
                datetime(2026, 1, 1, 1, 0),
                datetime(2026, 1, 1, 2, 0),
            ],
            "time_zone": ["+02:00", "unknown", "unknown"],
            "station_id": ["station-known", "station-unknown-1", "station-unknown-2"],
            "product_id": ["flow", "flow", "level"],
            "value": [10.0, 11.0, 12.0],
        },
        schema=ObservationDataSchema.polars_schema,
    )
    untouched = input_data.clone()
    result = _result(input_data, ProviderId("ca_eccc"))
    calls: list[object] = []

    def probe(*args: object) -> None:
        calls.append(args)
        raise AssertionError("per-row conversion ran before unknown-zone refusal")

    monkeypatch.setattr("rivretrieve._internal.utc._convert_wall_clock", probe)

    with pytest.raises(FatalContractError) as raised:
        rivretrieve.to_utc(result)

    assert str(raised.value) == (
        "Cannot convert 2 observation rows for provider 'ca_eccc' to UTC because time_zone is 'unknown'"
    )
    assert calls == []
    pl_testing.assert_frame_equal(result.data, untouched, check_exact=True)


def test_to_utc_usgs_dst_boundary_uses_each_payload_offset_without_catalogue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture_bytes = FIXTURE_PATH.read_bytes()
    origin = SourceCallOrigin(
        UnknownOriginFact(),
        UnknownOriginFact(),
        UnknownOriginFact(),
        UnknownOriginFact(),
        UnknownOriginFact(),
        UnknownOriginFact(),
        UnknownOriginFact(),
    )
    payload = Payload(
        SourceCoordinates(object()),
        (("07374000", ProductId("discharge_instantaneous")),),
        _make_fetch_window(
            WindowEndpoint.from_datetime(datetime(2023, 3, 12, 0, 0)),
            WindowEndpoint.from_datetime(datetime(2023, 3, 12, 23, 59, 59, 999999)),
        ),
        fixture_bytes,
        origin,
    )
    parsed = parse(payload, usgs_nwis_config())
    native = ObservationResult(
        data=parsed.value.select(ObservationDataSchema.polars_schema.names()),
        provenance=ObservationProvenance(source="live", provider_id=ProviderId("usgs_nwis")),
        issues=(),
        receipts=Receipts(
            provider_id=ProviderId("usgs_nwis"),
            entries=(
                ReceiptEntry(content=fixture_bytes, origin=origin, authorship=ReceiptAuthorship.PUBLISHER_PAYLOAD),
            ),
        ),
    )
    expected_native = pl.DataFrame(
        {
            "time": [datetime(2023, 3, 12, 1, 30), datetime(2023, 3, 12, 3, 30)],
            "time_zone": ["-06:00", "-05:00"],
            "station_id": ["07374000", "07374000"],
            "product_id": ["discharge_instantaneous", "discharge_instantaneous"],
            "value": [100.0, 101.0],
        },
        schema=ObservationDataSchema.polars_schema,
    )
    expected_converted = pl.DataFrame(
        {
            "time": [datetime(2023, 3, 12, 7, 30), datetime(2023, 3, 12, 8, 30)],
            "time_zone": ["+00:00", "+00:00"],
            "station_id": ["07374000", "07374000"],
            "product_id": ["discharge_instantaneous", "discharge_instantaneous"],
            "value": [100.0, 101.0],
        },
        schema=ObservationDataSchema.polars_schema,
    )

    def catalogue_probe(*args: object, **kwargs: object) -> None:
        raise AssertionError("to_utc consulted the catalogue")

    monkeypatch.setattr(CatalogueReader, "read_stations", catalogue_probe)
    monkeypatch.setattr(artifact_module, "load_packaged_catalogue_artifact", catalogue_probe)
    monkeypatch.setattr(pl, "read_parquet", catalogue_probe)
    monkeypatch.setattr(pl, "scan_parquet", catalogue_probe)

    converted = rivretrieve.to_utc(native)

    pl_testing.assert_frame_equal(native.data, expected_native, check_exact=True)
    pl_testing.assert_frame_equal(converted.data, expected_converted, check_exact=True)
    assert set(native.data["time_zone"].to_list()) == {"-06:00", "-05:00"}
    assert native.data["time_zone"].to_list() == ["-06:00", "-05:00"]
    assert "CST" not in native.data["time_zone"].to_list()
    assert "CDT" not in native.data["time_zone"].to_list()
    assert converted.data["time_zone"].to_list() == ["+00:00", "+00:00"]
    assert converted.provenance is native.provenance
    assert converted.issues is native.issues
    assert converted.receipts is native.receipts
