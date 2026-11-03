"""Synthetic unit tests for au_bom's catalogue-building logic."""

from __future__ import annotations

from datetime import UTC, datetime

import polars as pl
import pytest

from rivretrieve._internal.catalogues.native import RetrievedAt
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.au_bom.generate_catalogue import (
    build_products,
    river_gauge_native_table,
    station_native_table,
    timeseries_list_associations,
)
from rivretrieve._internal.providers.au_bom.origins import GeorefsystemToEpsgConversion, NativeColumn


def _station_doc(rows: list[list[str]]) -> list[list[str]]:
    header = [
        "station_no",
        "station_name",
        "station_longname",
        "station_latitude",
        "station_longitude",
        "station_georefsystem",
    ]
    return [header, *rows]


def test_station_native_table_dedupes_within_and_across_lists() -> None:
    discharge = _station_doc(
        [
            ["410730", "Cotter R.", "Cotter River at Gingera", "-35.588", "148.822", "WGS84 (3D)"],
            # A duplicate row for the same station_no with slightly different text, as observed live.
            ["225213A", "ABERFELDY BEARDMORE", "Aberfeldy River at Beardmore", "-37.85387", "146.43303", "GDA94 2D"],
            [
                "225213A",
                "ABERFELDY BEARDMORES",
                "Aberfeldy River at Beardmores",
                "-37.853949",
                "146.433164",
                "GDA94 2D",
            ],
        ]
    )
    stage = _station_doc([["410730", "Cotter R.", "Cotter River at Gingera", "-35.588", "148.822", "WGS84 (3D)"]])
    temperature = _station_doc([])

    docs = {
        "station_list_discharge": discharge,
        "station_list_stage": stage,
        "station_list_temperature": temperature,
    }
    table, ambiguous = station_native_table(docs, retrieved_at=RetrievedAt(datetime(2026, 11, 2, tzinfo=UTC)))
    assert table.data.height == 2
    assert ambiguous == ("225213A",)
    row = table.data.filter(pl.col("station_no") == "225213A").row(0, named=True)
    # Keeps the first-seen record (discharge list, first occurrence).
    assert row["station_name"] == "ABERFELDY BEARDMORE"


def test_station_native_table_raises_when_truly_empty() -> None:
    empty = _station_doc([])
    docs = {"station_list_discharge": empty, "station_list_stage": empty, "station_list_temperature": empty}
    with pytest.raises(FatalContractError):
        station_native_table(docs, retrieved_at=RetrievedAt(datetime(2026, 11, 2, tzinfo=UTC)))


def test_river_gauge_native_table_scopes_to_witnessed_stations() -> None:
    discharge = _station_doc(
        [
            ["410730", "Cotter R.", "Cotter River at Gingera", "-35.588", "148.822", "WGS84 (3D)"],
            ["999999", "Unwitnessed", "Unwitnessed Station", "-10.0", "130.0", "GDA94 2D"],
        ]
    )
    docs = {"station_list_discharge": discharge, "station_list_stage": discharge, "station_list_temperature": discharge}
    all_stations, _ = station_native_table(docs, retrieved_at=RetrievedAt(datetime(2026, 11, 2, tzinfo=UTC)))
    scoped = river_gauge_native_table(all_stations, {"410730"})
    assert scoped.data["station_no"].to_list() == ["410730"]


def test_river_gauge_native_table_raises_if_witnessed_station_is_missing() -> None:
    discharge = _station_doc([["410730", "Cotter R.", "Cotter River at Gingera", "-35.588", "148.822", "WGS84 (3D)"]])
    docs = {"station_list_discharge": discharge, "station_list_stage": discharge, "station_list_temperature": discharge}
    all_stations, _ = station_native_table(docs, retrieved_at=RetrievedAt(datetime(2026, 11, 2, tzinfo=UTC)))
    with pytest.raises(FatalContractError):
        river_gauge_native_table(all_stations, {"410730", "does-not-exist"})


def test_timeseries_list_associations_rejects_unexpected_station() -> None:
    doc = [["ts_id", "station_no"], ["1573010", "410730"]]
    with pytest.raises(FatalContractError):
        timeseries_list_associations(doc, product_id="discharge_daily_mean_24hr", station_ids={"999999"})


def test_build_products_has_18_rows_matching_the_settled_scope() -> None:
    products = build_products()
    assert products.height == 18
    by_quantity = products.group_by("observed_property").len().sort("observed_property")
    assert by_quantity["len"].to_list() == [7, 6, 5]  # discharge, stage, water_temperature
    assert set(products["unit"].unique().to_list()) == {"m3/s", "m", "degC"}


def test_georefsystem_to_epsg_conversion_maps_known_and_unknown_values() -> None:
    conversion = GeorefsystemToEpsgConversion()
    native_column = NativeColumn("station_georefsystem")
    cases = {
        "WGS84": "EPSG:4326",
        "WGS84 (3D)": "EPSG:4326",
        "GDA94 2D": "EPSG:4283",
        "MGA Zone 54": "EPSG:4283",
        "AGD66": "EPSG:4202",
        "AMG Zone 58": "EPSG:4202",
        "---": "unknown",
        "something new": "unknown",
    }
    for value, expected in cases.items():
        assert conversion.apply("crs", native_column, {"station_georefsystem": value}) == expected


def test_georefsystem_conversion_rejects_other_canonical_columns() -> None:
    conversion = GeorefsystemToEpsgConversion()
    with pytest.raises(ValueError, match="only defined for crs"):
        conversion.apply("latitude", NativeColumn("station_georefsystem"), {"station_georefsystem": "WGS84"})
