"""Synthetic, source-independent coverage for the de_pegelonline catalogue builder.

These tests construct small PEGELONLINE-shaped payloads by hand (not read from any
retained fixture) so every expectation is independently worked out from the
published REST API v2 shape, rather than from the implementation under test.
Figures pinned to a fresh live fetch (station totals, per-timeseries counts, the
NEUSTADT collision) live in a separate, evidence-marked test module.
"""

from __future__ import annotations

from datetime import UTC, datetime

import polars as pl
import pytest

from rivretrieve._internal.catalogues.native import NativeTable, RetrievedAt
from rivretrieve._internal.catalogues.schemas import (
    PRODUCT_CATALOG_SCHEMA,
    PROVIDER_INFO_CATALOG_SCHEMA,
    STATION_CATALOG_SCHEMA,
    STATION_PRODUCT_CATALOG_SCHEMA,
    validate_catalogue,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.de_pegelonline import generate_catalogue
from rivretrieve._internal.providers.de_pegelonline.origins import STATION_CATALOGUE_ORIGINS

RETRIEVED_AT = RetrievedAt(datetime(2026, 11, 24, 17, 20, 15, tzinfo=UTC))


def _station(
    uuid: str,
    shortname: str,
    *,
    longname: str | None = None,
    agency: str = "VERDEN",
    km: float | None = 1.74,
    remark: str | None = None,
    longitude: float | None = 10.0,
    latitude: float | None = 52.0,
    water_shortname: str = "ALLER",
    water_longname: str = "ALLER",
    timeseries: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    station: dict[str, object] = {
        "uuid": uuid,
        "number": "48300105",
        "shortname": shortname,
        "longname": longname if longname is not None else shortname,
        "km": km,
        "agency": agency,
        "longitude": longitude,
        "latitude": latitude,
        "water": {"shortname": water_shortname, "longname": water_longname},
        "timeseries": timeseries if timeseries is not None else [],
    }
    if remark is not None:
        station["remark"] = remark
    return station


def _w_series(unit: str, *, gauge_zero_value: float | None = None) -> dict[str, object]:
    series: dict[str, object] = {"shortname": "W", "longname": "WASSERSTAND ROHDATEN", "unit": unit, "equidistance": 15}
    series["gaugeZero"] = (
        None if gauge_zero_value is None else {"unit": "m. ü. NN", "value": gauge_zero_value, "validFrom": "1936-11-01"}
    )
    return series


SAMPLE_PAYLOAD = [
    _station(
        "b475386c-30cc-453a-b3b7-1d17ace13595",
        "CELLE",
        timeseries=[
            _w_series("cm", gauge_zero_value=31.82),
            {"shortname": "WT", "longname": "WASSERTEMPERATUR ROHDATEN", "unit": "°C", "equidistance": 15},
        ],
    ),
    _station(
        "2813f196-3404-4ac2-92be-e288fe1607af",
        "AHSEN SCHLEUSE OW",
        agency="DUISBURG-MEIDERICH",
        remark="",
        timeseries=[_w_series("m+NN")],
    ),
    _station(
        "5cdc6555-87d7-4fcd-834d-cbbe24c9d08b",
        "DIEMELTALSPERRE",
        agency="HANN. MUENDEN",
        remark="Example remark",
        timeseries=[_w_series("m+PNP", gauge_zero_value=0.041)],
    ),
    _station(
        "c389c9e2-a5d8-4104-a4cf-510ade44f143",
        "ACHLEITEN",
        agency="VIA DONAU",
        longitude=None,
        latitude=None,
        timeseries=[_w_series("cm", gauge_zero_value=287.7)],
    ),
    _station(
        "0a111111-0000-0000-0000-000000000001",
        "GIMBSHEIM",
        agency="MAINZ",
        timeseries=[{"shortname": "Q", "longname": "DURCHFLUSS", "unit": "m³/s", "equidistance": 15}],
    ),
    # The real NEUSTADT shortname collision: two distinct uuids, different rivers.
    _station(
        "dda39817-d01d-467f-a6a3-7487011a45d1",
        "NEUSTADT",
        water_shortname="LEINE",
        water_longname="LEINE",
        timeseries=[_w_series("cm", gauge_zero_value=50.0)],
    ),
    _station(
        "3f0b6b74-80a9-4576-a3cb-ea967dfc349f",
        "NEUSTADT",
        water_shortname="OSTSEE",
        water_longname="OSTSEE",
        timeseries=[],
    ),
]


def _native_table() -> NativeTable:
    return generate_catalogue.station_native_table(SAMPLE_PAYLOAD, retrieved_at=RETRIEVED_AT)


# --- station_native_table ---------------------------------------------------


def test_station_native_table_parses_core_fields_and_flattens_water():
    table = _native_table()
    row = table.data.filter(pl.col("uuid") == "b475386c-30cc-453a-b3b7-1d17ace13595").row(0, named=True)

    assert row["number"] == "48300105"
    assert row["shortname"] == "CELLE"
    assert row["longname"] == "CELLE"
    assert row["km"] == pytest.approx(1.74)
    assert row["agency"] == "VERDEN"
    assert row["remark"] is None
    assert row["water_shortname"] == "ALLER"
    assert row["water_longname"] == "ALLER"
    assert row["w_unit"] == "cm"
    assert row["w_gauge_zero_value"] == pytest.approx(31.82)
    assert {entry["shortname"] for entry in row["timeseries"]} == {"W", "WT"}


def test_station_native_table_keeps_blank_remark_distinct_from_absent_remark():
    table = _native_table()
    blank = table.data.filter(pl.col("uuid") == "2813f196-3404-4ac2-92be-e288fe1607af").row(0, named=True)
    present = table.data.filter(pl.col("uuid") == "5cdc6555-87d7-4fcd-834d-cbbe24c9d08b").row(0, named=True)
    absent = table.data.filter(pl.col("uuid") == "b475386c-30cc-453a-b3b7-1d17ace13595").row(0, named=True)

    assert blank["remark"] == ""
    assert present["remark"] == "Example remark"
    assert absent["remark"] is None


def test_station_native_table_records_m_nn_series_without_gauge_zero():
    table = _native_table()
    row = table.data.filter(pl.col("uuid") == "2813f196-3404-4ac2-92be-e288fe1607af").row(0, named=True)

    assert row["w_unit"] == "m+NN"
    assert row["w_gauge_zero_value"] is None


def test_station_native_table_keeps_m_pnp_gauge_zero_distinct_from_m_nn():
    table = _native_table()
    row = table.data.filter(pl.col("uuid") == "5cdc6555-87d7-4fcd-834d-cbbe24c9d08b").row(0, named=True)

    assert row["w_unit"] == "m+PNP"
    assert row["w_gauge_zero_value"] == pytest.approx(0.041)


def test_station_native_table_preserves_null_coordinates_together():
    table = _native_table()
    row = table.data.filter(pl.col("uuid") == "c389c9e2-a5d8-4104-a4cf-510ade44f143").row(0, named=True)

    assert row["latitude"] is None
    assert row["longitude"] is None


def test_station_native_table_rejects_duplicate_uuid():
    duplicated = [*SAMPLE_PAYLOAD, _station(SAMPLE_PAYLOAD[0]["uuid"], "DUPLICATE")]

    with pytest.raises(FatalContractError, match="uuid"):
        generate_catalogue.station_native_table(duplicated, retrieved_at=RETRIEVED_AT)


def test_station_native_table_rejects_mismatched_coordinate_nullability():
    malformed = [_station("x", "X", longitude=None, latitude=1.0)]

    with pytest.raises(FatalContractError, match="coordinate"):
        generate_catalogue.station_native_table(malformed, retrieved_at=RETRIEVED_AT)


def test_station_native_table_keeps_neustadt_shortname_collision_as_two_uuids():
    table = _native_table()
    neustadt = table.data.filter(pl.col("shortname") == "NEUSTADT")

    assert neustadt.height == 2
    assert set(neustadt["uuid"]) == {
        "dda39817-d01d-467f-a6a3-7487011a45d1",
        "3f0b6b74-80a9-4576-a3cb-ea967dfc349f",
    }
    assert set(neustadt["water_shortname"]) == {"LEINE", "OSTSEE"}


# --- build_catalogue ---------------------------------------------------------


def _catalogue():
    return generate_catalogue.build_catalogue(_native_table(), STATION_CATALOGUE_ORIGINS)


def test_build_products_returns_exactly_w_q_wt_with_distinct_observed_properties():
    catalogue = _catalogue()
    products = catalogue.products.sort("product_id")

    assert products["product_id"].to_list() == ["Q", "W", "WT"]
    assert products["observed_property"].to_list() == ["discharge", "stage", "water_temperature"]
    assert products.filter(pl.col("product_id") == "W")["unit"].item() == "unknown"
    assert products.filter(pl.col("product_id") == "Q")["unit"].item() == "m3/s"
    assert products.filter(pl.col("product_id") == "WT")["unit"].item() == "degC"
    assert set(products["statistic"]) == {"unknown"}
    assert set(products["frequency"]) == {"unknown"}


def test_build_stations_maps_missing_coordinates_to_unknown_crs_sentinel():
    catalogue = _catalogue()
    stations = catalogue.stations

    no_coords = stations.filter(pl.col("station_id") == "c389c9e2-a5d8-4104-a4cf-510ade44f143").row(0, named=True)
    with_coords = stations.filter(pl.col("station_id") == "b475386c-30cc-453a-b3b7-1d17ace13595").row(0, named=True)

    assert no_coords["crs"] == "unknown"
    assert no_coords["latitude"] is None
    assert no_coords["longitude"] is None
    assert with_coords["crs"] == "EPSG:4326"


def test_build_station_products_availability_matches_listed_timeseries():
    catalogue = _catalogue()
    pairs = catalogue.station_products

    celle = pairs.filter(pl.col("station_id") == "b475386c-30cc-453a-b3b7-1d17ace13595")
    assert celle.filter(pl.col("product_id") == "W")["availability"].item() == "available"
    assert celle.filter(pl.col("product_id") == "WT")["availability"].item() == "available"
    assert celle.filter(pl.col("product_id") == "Q")["availability"].item() == "unknown"

    gimbsheim = pairs.filter(pl.col("station_id") == "0a111111-0000-0000-0000-000000000001")
    assert gimbsheim.filter(pl.col("product_id") == "Q")["availability"].item() == "available"
    assert gimbsheim.filter(pl.col("product_id") == "W")["availability"].item() == "unknown"

    assert set(pairs["published_record_start_date"]) == {None}
    assert set(pairs["published_record_end_date"]) == {None}


def test_build_provider_info_uses_the_settled_licence_and_live_flags():
    catalogue = _catalogue()
    info = catalogue.provider_info

    assert info["license"] == "DL-DE->Zero-2.0"
    assert info["live_stations"] is True
    assert info["live_products"] is True
    assert info["live_station_products"] is True
    assert info["bulk_observations"] == "none"
    assert info["catalogue_version"] == "2026-11-24"


def test_build_catalogue_validates_against_all_four_schemas():
    catalogue = _catalogue()
    provider_info_df = pl.DataFrame([catalogue.provider_info], schema=PROVIDER_INFO_CATALOG_SCHEMA.polars_schema)

    validate_catalogue(provider_info_df, PROVIDER_INFO_CATALOG_SCHEMA, on_issue="raise")
    validate_catalogue(catalogue.products, PRODUCT_CATALOG_SCHEMA, on_issue="raise")
    validate_catalogue(catalogue.stations, STATION_CATALOG_SCHEMA, on_issue="raise")
    validate_catalogue(catalogue.station_products, STATION_PRODUCT_CATALOG_SCHEMA, on_issue="raise")


def test_build_catalogue_is_gated_on_origins():
    broken = dict(STATION_CATALOGUE_ORIGINS)
    del broken["longitude"]

    with pytest.raises(
        FatalContractError, match=r"de_pegelonline\.longitude: canonical column has no origin declaration"
    ):
        generate_catalogue.build_catalogue(_native_table(), broken)


# --- station metadata ---------------------------------------------------------


def test_station_metadata_projects_names_and_the_w_vertical_datum_regime():
    from rivretrieve._internal.catalogues.station_metadata import build_station_metadata
    from rivretrieve._internal.providers.de_pegelonline.origins import STATION_METADATA_FIELDS

    table = _native_table()
    stations = generate_catalogue.build_stations(table)
    metadata = build_station_metadata(
        "de_pegelonline", table, stations, STATION_CATALOGUE_ORIGINS["station_id"], STATION_METADATA_FIELDS
    )

    celle = metadata.filter(
        (pl.col("station_id") == "b475386c-30cc-453a-b3b7-1d17ace13595") & (pl.col("attribute_role") == "elevation")
    ).row(0, named=True)
    assert celle["source_field"] == "w_gauge_zero_value"
    assert celle["source_value"] == "31.82"
    assert celle["source_datum"] == "cm"
    assert celle["source_datum_field"] == "w_unit"
    assert celle["datum_support_fact"] is not None

    m_nn = metadata.filter(
        (pl.col("station_id") == "2813f196-3404-4ac2-92be-e288fe1607af") & (pl.col("attribute_role") == "elevation")
    ).row(0, named=True)
    assert m_nn["state"] == "source_null"
    assert m_nn["source_datum"] == "m+NN"

    names = metadata.filter(
        (pl.col("station_id") == "b475386c-30cc-453a-b3b7-1d17ace13595") & (pl.col("attribute_role") == "station_name")
    )
    assert set(names["source_field"]) == {"longname", "shortname"}

    water = metadata.filter(
        (pl.col("station_id") == "dda39817-d01d-467f-a6a3-7487011a45d1")
        & (pl.col("attribute_role") == "water_body_name")
    )
    assert set(water["source_value"]) == {'"LEINE"'}


# --- acquisition provenance ---------------------------------------------------


def test_build_acquisition_provenance_is_internally_closed():
    from rivretrieve._internal.acquisition_provenance import NativeTableIdentity, RecordingReference
    from rivretrieve._internal.providers.de_pegelonline.origins import build_acquisition_provenance

    terms_recording = RecordingReference(
        recording_id="de_pegelonline-terms",
        repository_path="tests/test_data/de_pegelonline_terms.html",
        source_url="https://pegelonline.wsv.de/gast/nutzungsbedingungen",
        retrieved_at=datetime(2026, 11, 24, 17, 27, 46, tzinfo=UTC),
        media_type="text/html; charset=utf-8",
        sha256="d5e9194b6fb981df5eba1032c3d76d068a04123d05242a9549cb7b09e0013981",
    )
    provenance = build_acquisition_provenance(
        stations_retrieved_at=RETRIEVED_AT.value,
        native_identity=NativeTableIdentity(
            repository_path="src/rivretrieve/_internal/providers/de_pegelonline/catalogue/native.parquet",
            revision="0" * 40,
            sha256="1" * 64,
            byte_size=123,
        ),
        terms_recording=terms_recording,
        license_exact_text=(
            "Informationen, Produkte oder Dienste, die Sie von dieser Website erhalten, dürfen übernommen "
            "werden. Dies geschieht auf der Grundlage der Lizenz DL-DE->Zero-2.0"
        ),
    )

    assert provenance.provider_id == "de_pegelonline"
    assert {statement.kind for source in provenance.source_records for statement in source.statements} == {"license"}
