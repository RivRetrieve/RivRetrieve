import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve
import rivretrieve._internal.catalogues.artifact as artifact_module
from rivretrieve._internal.catalogue_reader import CatalogueReader
from rivretrieve._internal.engine import (
    SourceCallOrigin,
    UnknownOriginFact,
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
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.recordings import read_recording
from rivretrieve._internal.source_series import PhysicalFacts, SourceIdentity, SourceSeries, known

RECORDING_PATH = Path("tests/test_data/usgs_nwis_07374000_iv_00060_2023-03-12.recording.json")


def _definition(provider_id, station_id, product_id):
    # Authored UTC-boundary context; this is not a provider physical mapping.
    quantity, unit = ("discharge", "m3/s") if product_id in ("flow", "q") else ("stage", "m")
    return SourceSeries(
        series_id=f"test/{station_id}/{product_id}",
        provider_id=str(provider_id),
        station_id=station_id,
        product_id=product_id,
        identity=SourceIdentity(
            namespace="test-utc", published_id=product_id, origin="mapping", evidence=("authored-UTC-contract",)
        ),
        facts=(
            PhysicalFacts(
                facts_id=f"test/{product_id}",
                quantity=known(quantity, "authored-UTC-contract"),
                source_unit=known(unit, "authored-UTC-contract"),
                normalized_unit=unit,
            ),
        ),
    )


def _frame(data):
    frame = pl.DataFrame(data)
    definitions = [
        _definition("provider-a", station, product)
        for station, product in frame.select("station_id", "product_id").iter_rows()
    ]
    return (
        frame.with_columns(
            pl.Series("series_id", [item.series_id for item in definitions]),
            pl.Series("facts_id", [item.facts[0].facts_id for item in definitions]),
            pl.Series("quantity", [item.facts[0].quantity.value for item in definitions]),
            pl.Series("source_unit", [item.facts[0].source_unit.value for item in definitions]),
            pl.Series("unit", [item.facts[0].normalized_unit for item in definitions]),
        )
        .select(ObservationDataSchema.polars_schema.names())
        .cast(ObservationDataSchema.polars_schema)
    )


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
    definitions = tuple(
        _definition(provider_id, station, product)
        for station, product in data.select("station_id", "product_id").unique().iter_rows()
    )
    return ObservationResult(
        data=data, provenance=provenance, issues=issues, receipts=receipts, source_series=definitions
    )


def test_to_utc_fixed_offsets_converts_row_by_row_and_preserves_result_members() -> None:
    input_data = _frame(
        {
            "time": [datetime(2026, 1, 1, 0, 15), datetime(2026, 1, 1, 0, 15)],
            "time_zone": ["+05:30", "-03:30"],
            "station_id": ["station-1", "station-1"],
            "product_id": ["flow", "flow"],
            "value": [1.25, None],
        }
    )
    untouched = input_data.clone()
    result = _result(input_data)
    expected = _frame(
        {
            "time": [datetime(2025, 12, 31, 18, 45), datetime(2026, 1, 1, 3, 45)],
            "time_zone": ["+00:00", "+00:00"],
            "station_id": ["station-1", "station-1"],
            "product_id": ["flow", "flow"],
            "value": [1.25, None],
        }
    )

    converted = rivretrieve.to_utc(result)

    pl_testing.assert_frame_equal(converted.data, expected, check_exact=True)
    pl_testing.assert_frame_equal(result.data, untouched, check_exact=True)
    assert converted is not result
    assert converted.data is not result.data
    assert converted.provenance is result.provenance
    assert converted.issues is result.issues
    assert converted.receipts is result.receipts
    assert converted.source_series == result.source_series
    assert converted.outcomes == result.outcomes
    assert converted.scope == result.scope
    assert converted.data.columns == ObservationDataSchema.polars_schema.names()
    assert converted.data.schema == ObservationDataSchema.polars_schema


def test_to_utc_iana_identifiers_use_zone_rules() -> None:
    result = _result(
        _frame(
            {
                "time": [datetime(2026, 1, 15, 12, 0), datetime(2026, 7, 15, 12, 0)],
                "time_zone": ["Europe/Zurich", "Europe/Zurich"],
                "station_id": ["station-iana", "station-iana"],
                "product_id": ["level", "level"],
                "value": [2.5, 3.5],
            }
        )
    )
    expected = _frame(
        {
            "time": [datetime(2026, 1, 15, 11, 0), datetime(2026, 7, 15, 10, 0)],
            "time_zone": ["+00:00", "+00:00"],
            "station_id": ["station-iana", "station-iana"],
            "product_id": ["level", "level"],
            "value": [2.5, 3.5],
        }
    )

    pl_testing.assert_frame_equal(rivretrieve.to_utc(result).data, expected, check_exact=True)


def test_to_utc_tz_aware_time_dtype_becomes_naive() -> None:
    data = _frame(
        {
            "time": [datetime(2026, 1, 15, 12, 0)],
            "time_zone": ["Europe/Zurich"],
            "station_id": ["s"],
            "product_id": ["q"],
            "value": [1.0],
        }
    ).with_columns(pl.col("time").dt.replace_time_zone("America/Chicago"))

    converted = rivretrieve.to_utc(_result(data))

    assert converted.data.schema["time"] == pl.Datetime("us")
    assert converted.data["time"].to_list() == [datetime(2026, 1, 15, 11, 0)]
    assert converted.data["time_zone"].to_list() == ["+00:00"]


def test_to_utc_unknown_zones_refuse_atomically_with_provider_and_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_data = _frame(
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
        }
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


@pytest.mark.recorded("tests/test_data/usgs_nwis_07374000_iv_00060_2023-03-12.recording.json")
def test_to_utc_usgs_dst_boundary_uses_each_payload_offset_without_catalogue(
    retained_evidence_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recording = read_recording(retained_evidence_root / RECORDING_PATH)
    fixture_bytes = recording.content
    origin = SourceCallOrigin(
        url=recording.request.url,
        request_parameters=recording.request.parameters,
        status_code=recording.status_code,
        retrieved_at=recording.retrieved_at,
        content_type=recording.content_type,
        source_path=UnknownOriginFact(),
        query=UnknownOriginFact(),
    )
    # Historical WaterServices evidence only. Decode this fixed recording into
    # the UTC test carrier; no retired provider implementation is retained.
    document = json.loads(fixture_bytes)
    recorded_series = document["value"]["timeSeries"][0]
    assert recorded_series["variable"]["unit"]["unitCode"] == "ft3/s"
    readings = recorded_series["values"][0]["value"]
    assert len(readings) == 92
    definition = SourceSeries(
        series_id="legacy-dst-recording",
        provider_id="usgs_nwis",
        station_id="07374000",
        product_id="discharge_instantaneous",
        identity=SourceIdentity(
            namespace="test-legacy-dst",
            published_id="recorded-discharge",
            origin="response",
            evidence=(str(RECORDING_PATH),),
        ),
        facts=(
            PhysicalFacts(
                facts_id="legacy-dst-facts",
                quantity=known("discharge", str(RECORDING_PATH)),
                source_unit=known("ft3/s", str(RECORDING_PATH)),
                normalized_unit="ft3/s",
            ),
        ),
    )
    data = pl.DataFrame(
        [
            {
                "time": datetime.fromisoformat(reading["dateTime"]).replace(tzinfo=None),
                "time_zone": reading["dateTime"][-6:],
                "station_id": "07374000",
                "product_id": "discharge_instantaneous",
                "series_id": definition.series_id,
                "facts_id": definition.facts[0].facts_id,
                "quantity": "discharge",
                "source_unit": "ft3/s",
                "unit": "m3/s",
                "value": float(reading["value"]) * 0.028316846592,
            }
            for reading in readings
        ],
        schema=ObservationDataSchema.polars_schema,
    )
    native = ObservationResult(
        data=data,
        source_series=(definition,),
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
            "time": [datetime(2023, 3, 12, 1, 30), datetime(2023, 3, 12, 3, 0)],
            "time_zone": ["-06:00", "-05:00"],
            "station_id": ["07374000", "07374000"],
            "product_id": ["discharge_instantaneous", "discharge_instantaneous"],
            "series_id": [definition.series_id] * 2,
            "facts_id": [definition.facts[0].facts_id] * 2,
            "quantity": ["discharge"] * 2,
            "source_unit": ["ft3/s"] * 2,
            "unit": ["m3/s"] * 2,
            "value": [809000.0 * 0.028316846592, 811000.0 * 0.028316846592],
        },
        schema=ObservationDataSchema.polars_schema,
    )
    expected_converted = pl.DataFrame(
        {
            "time": [datetime(2023, 3, 12, 7, 30), datetime(2023, 3, 12, 8, 0)],
            "time_zone": ["+00:00", "+00:00"],
            "station_id": ["07374000", "07374000"],
            "product_id": ["discharge_instantaneous", "discharge_instantaneous"],
            "series_id": [definition.series_id] * 2,
            "facts_id": [definition.facts[0].facts_id] * 2,
            "quantity": ["discharge"] * 2,
            "source_unit": ["ft3/s"] * 2,
            "unit": ["m3/s"] * 2,
            "value": [809000.0 * 0.028316846592, 811000.0 * 0.028316846592],
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

    pl_testing.assert_frame_equal(native.data[[6, 8]], expected_native, check_exact=True)
    pl_testing.assert_frame_equal(converted.data[[6, 8]], expected_converted, check_exact=True)
    assert converted.data["time"].to_list() == [
        datetime(2023, 3, 12, 6) + timedelta(minutes=15 * index) for index in range(92)
    ]
    pl_testing.assert_frame_equal(
        converted.data.drop("time", "time_zone"), native.data.drop("time", "time_zone"), check_exact=True
    )
    assert set(native.data["time_zone"].to_list()) == {"-06:00", "-05:00"}
    assert native.data["time_zone"].to_list() == ["-06:00"] * 8 + ["-05:00"] * 84
    assert "CST" not in native.data["time_zone"].to_list()
    assert "CDT" not in native.data["time_zone"].to_list()
    assert converted.data["time_zone"].to_list() == ["+00:00"] * 92
    assert converted.provenance is native.provenance
    assert converted.issues is native.issues
    assert converted.receipts is native.receipts


def test_to_utc_vectorizes_fixed_offsets_and_matches_zoneinfo_on_iana_dst_and_gaps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from zoneinfo import ZoneInfo

    import rivretrieve._internal.utc as utc_mod
    from rivretrieve._internal.source_annotations import (
        AnnotationBundle,
        AnnotationField,
        AnnotationSchema,
        AnnotationScope,
        ObservationAnnotationTable,
        with_annotations,
    )

    # 1. Fixed offsets across data + measured & unmeasured annotations avoid Python per-row wall-clock loop
    zones = ["-05:00", "+00:00", "+05:30", "-03:30", "+01:00"]
    times = [datetime(2026, 1, 1, 12, 30) + timedelta(minutes=15 * i) for i in range(100)]
    fixed_zones = [zones[i % len(zones)] for i in range(100)]
    fixed_data = _frame(
        {
            "time": times,
            "time_zone": fixed_zones,
            "station_id": ["s1"] * 100,
            "product_id": ["flow"] * 100,
            "value": [float(i) for i in range(100)],
        }
    )
    ann_schema = AnnotationSchema(
        schema_id="provider-a.qc",
        provider_id="provider-a",
        scope=AnnotationScope.OBSERVATION,
        fields=(AnnotationField(name="qc", dtype="String", description="Flag."),),
    )
    ann_table = ObservationAnnotationTable.from_rows(
        schema=ann_schema,
        rows=pl.DataFrame(
            {
                "series_id": [fixed_data["series_id"][0]] * 2,
                "facts_id": [fixed_data["facts_id"][0]] * 2,
                "station_id": ["s1", "s1"],
                "product_id": ["flow", "flow"],
                "time": [times[1], datetime(2026, 1, 2, 0, 0)],
                "time_zone": [fixed_zones[1], "+05:30"],
                "measured": [True, False],
                "qc": ["m1", "u1"],
            },
            schema={
                "series_id": pl.String,
                "facts_id": pl.String,
                "station_id": pl.String,
                "product_id": pl.String,
                "time": pl.Datetime("us"),
                "time_zone": pl.String,
                "measured": pl.Boolean,
                **ann_schema.polars_schema(),
            },
        ),
        measurement_indices=(1, None),
    )
    fixed_result = with_annotations(
        _result(fixed_data), AnnotationBundle(observation_tables={"provider-a.qc": ann_table})
    )
    expected_fixed_times = [utc_mod._convert_wall_clock(t, z) for t, z in zip(times, fixed_zones, strict=True)]
    expected_ann_times = [
        utc_mod._convert_wall_clock(times[1], fixed_zones[1]),
        utc_mod._convert_wall_clock(datetime(2026, 1, 2, 0, 0), "+05:30"),
    ]

    def _forbid_python_wall_clock(*args: object, **kwargs: object) -> None:
        raise AssertionError("_convert_wall_clock called for fixed offsets")

    with monkeypatch.context() as mp:
        mp.setattr(utc_mod, "_convert_wall_clock", _forbid_python_wall_clock)
        fixed_utc = rivretrieve.to_utc(fixed_result)

    assert fixed_utc.data["time"].to_list() == expected_fixed_times
    assert fixed_utc.data["time_zone"].to_list() == ["+00:00"] * 100
    utc_ann = fixed_utc._annotations.observation_tables["provider-a.qc"]
    assert utc_ann.rows["time"].to_list() == expected_ann_times
    assert utc_ann.rows["time_zone"].to_list() == ["+00:00", "+00:00"]
    assert utc_ann.measurement_indices == (1, None)

    # 2. Mixed fixed offsets + IANA zones including DST fall-back ambiguous fold=0 and spring-forward gap
    iana_times = [
        datetime(2026, 1, 15, 12, 0),  # winter America/New_York (-05:00)
        datetime(2026, 7, 15, 12, 0),  # summer America/New_York (-04:00)
        datetime(2026, 11, 1, 1, 30),  # ambiguous fall-back America/New_York (fold=0 -> -04:00)
        datetime(2026, 3, 8, 2, 30),  # non-existent spring-forward gap in America/New_York
        datetime(2026, 6, 1, 10, 0),  # Europe/Zurich
        datetime(2026, 6, 1, 10, 0),  # fixed offset +05:30
    ]
    iana_zones = [
        "America/New_York",
        "America/New_York",
        "America/New_York",
        "America/New_York",
        "Europe/Zurich",
        "+05:30",
    ]
    orig_wall_clock = utc_mod._convert_wall_clock
    expected_iana = [orig_wall_clock(t, z) for t, z in zip(iana_times, iana_zones, strict=True)]
    # Verify reference matches Python ZoneInfo directly
    assert expected_iana[2] == datetime(2026, 11, 1, 1, 30, tzinfo=ZoneInfo("America/New_York")).astimezone(
        UTC
    ).replace(tzinfo=None)

    iana_result = _result(
        _frame(
            {
                "time": iana_times,
                "time_zone": iana_zones,
                "station_id": ["s1"] * 6,
                "product_id": ["flow"] * 6,
                "value": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            }
        )
    )
    iana_utc = rivretrieve.to_utc(iana_result)
    assert iana_utc.data["time"].to_list() == expected_iana
    assert iana_utc.data["time_zone"].to_list() == ["+00:00"] * 6

    # Invalid IANA raises ValueError, and unknown in annotation refuses atomically
    bad_iana = iana_result.model_copy(
        update={
            "data": _frame(
                {
                    "time": [datetime(2026, 1, 1, 0, 0)],
                    "time_zone": ["Mars/Olympus_Mons"],
                    "station_id": ["s1"],
                    "product_id": ["flow"],
                    "value": [1.0],
                }
            )
        }
    )
    with pytest.raises(ValueError):
        rivretrieve.to_utc(bad_iana)

    unknown_ann = with_annotations(
        _result(
            _frame(
                {
                    "time": [datetime(2026, 1, 1, 0, 0)],
                    "time_zone": ["+00:00"],
                    "station_id": ["s1"],
                    "product_id": ["flow"],
                    "value": [1.0],
                }
            )
        ),
        AnnotationBundle(
            observation_tables={
                "provider-a.qc": ObservationAnnotationTable.from_rows(
                    schema=ann_schema,
                    rows=ann_table.rows.head(1).with_columns(
                        pl.lit("unknown").alias("time_zone"),
                        pl.lit(False).alias("measured"),
                    ),
                    measurement_indices=(None,),
                )
            }
        ),
    )
    with pytest.raises(FatalContractError, match="Cannot convert 1 annotation rows"):
        rivretrieve.to_utc(unknown_ann)
