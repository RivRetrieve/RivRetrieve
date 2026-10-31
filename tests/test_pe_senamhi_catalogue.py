"""Synthetic SENAMHI catalogue identity and source-fidelity checks."""

from datetime import UTC, datetime

import polars as pl
from polars.testing import assert_frame_equal

from rivretrieve._internal.catalogues.native import RetrievedAt
from rivretrieve._internal.providers.pe_senamhi.generate_catalogue import station_native_table


def station(code, **values):
    return {"stationId": code, "typeId": "H", "categoryId": "05", "name": "Synthetic station", **values}


def envelope(rows):
    return {"status": True, "data": rows}


def test_registry_keeps_primary_identity_hydrological_exceptions_and_closed_stations():
    native = station_native_table(
        envelope([station("A", legacyStationId="B", conditionId="C", latitude="-12.5", longitude="-74.25")]),
        envelope(
            [station("B", typeId="M", categoryId="22", conditionId="P"), station("MET", typeId="M", categoryId="01")]
        ),
        envelope([station("A", legacyStationId="B", conditionId="C", latitude="-12.5", longitude="-74.25")]),
        retrieved_at=RetrievedAt(datetime(2026, 10, 31, tzinfo=UTC)),
    )
    assert_frame_equal(
        native.data.select("stationId", "legacyStationId", "conditionId", "latitude", "longitude"),
        pl.DataFrame(
            {
                "stationId": ["A", "B"],
                "legacyStationId": ["B", None],
                "conditionId": ["C", "P"],
                "latitude": ["-12.5", None],
                "longitude": ["-74.25", None],
            }
        ),
    )


def test_recognized_empty_hourly_association_uses_response_units():
    from rivretrieve._internal.providers.pe_senamhi.generate_catalogue import phisis_associations

    result = phisis_associations(
        envelope({"station": {"code": "A"}, "type": "HOURLY", "variable": "LEVEL", "unit": "m.s.n.m", "hourly": []}),
        station="A",
        resolution="HOURLY",
        variable="LEVEL",
        station_ids={"A"},
    )
    assert result.select("station_id", "subsystem", "resolution", "variable", "unit").rows() == [
        ("A", "phisis", "HOURLY", "LEVEL", "m.s.n.m")
    ]


def test_monthly_preserves_distinct_water_level_fields_without_using_dates():
    from rivretrieve._internal.providers.pe_senamhi.generate_catalogue import monthly_associations

    result = monthly_associations(
        envelope(
            {
                "columns": [
                    {"column": "N_NIVELMEDIO", "unit": "m"},
                    {"column": "N_NIV_INST_00", "unit": "m"},
                    {"column": "RAIN", "unit": "mm"},
                ],
                "readings": [{"date": "2099-12-01"}],
            }
        ),
        station="A",
        station_ids={"A"},
    )
    assert result.select("station_id", "subsystem", "variable", "unit").rows() == [
        ("A", "monthly_archive", "N_NIVELMEDIO", "m"),
        ("A", "monthly_archive", "N_NIV_INST_00", "m"),
    ]
    empty = monthly_associations(
        envelope({"columns": [{"column": "RAIN", "unit": "mm"}], "readings": []}), station="A", station_ids={"A"}
    )
    assert empty.is_empty()


def test_metadata_joins_only_exact_primary_code_and_preserves_unknowns():
    from rivretrieve._internal.providers.pe_senamhi.station_metadata import (
        enrich_station_metadata,
        project_station_metadata,
    )

    native = station_native_table(
        envelope([station("A", legacyStationId="B", altitude=123.5), station("B")]),
        envelope([]),
        envelope([]),
        retrieved_at=RetrievedAt(datetime(2026, 10, 31, tzinfo=UTC)),
    )
    enriched = enrich_station_metadata(
        native, [envelope({"code": "B", "waterBody": "Synthetic river", "waterBodyType": "RÍO", "automaticCode": "A"})]
    )
    assert enriched.data.select("stationId", "waterBody").rows() == [("A", None), ("B", "Synthetic river")]
    stations = pl.DataFrame({"provider_id": ["pe_senamhi"] * 2, "station_id": ["A", "B"]})
    metadata = project_station_metadata(enriched, stations)
    elevation = metadata.filter((pl.col("station_id") == "A") & (pl.col("attribute_role") == "elevation"))
    assert elevation.select("source_value", "source_unit", "source_datum").row(0) == ("123.5", "m", None)
    missing = metadata.filter((pl.col("station_id") == "A") & (pl.col("attribute_role") == "water_body_name"))
    assert missing["state"].item() == "source_null"


def test_catalogue_keeps_unknown_pairs_and_distinguishes_unit_based_level_products():
    from datetime import date

    from rivretrieve._internal.providers.pe_senamhi.generate_catalogue import catalogue_tables, phisis_associations

    native = station_native_table(
        envelope([station("A", latitude="-12", longitude="-75"), station("B")]),
        envelope([]),
        envelope([]),
        retrieved_at=RetrievedAt(datetime(2026, 10, 31, tzinfo=UTC)),
    )
    associations = phisis_associations(
        envelope({"station": {"code": "A"}, "type": "DAILY", "variable": "LEVEL", "unit": "m.s.n.m"}),
        station="A",
        resolution="DAILY",
        variable="LEVEL",
        station_ids={"A", "B"},
    )
    products, stations, pairs = catalogue_tables(native, associations, checked_on=date(2026, 10, 31))
    assert stations["crs"].to_list() == ["unknown", "unknown"]
    assert stations.select("latitude", "longitude").row(0) == (-12.0, -75.0)
    assert products.select("product_id", "frequency", "statistic").rows() == [
        ("phisis_daily_level_above_sea_level", "unknown", "unknown")
    ]
    assert pairs.select("station_id", "availability").rows() == [("A", "available"), ("B", "unknown")]
    assert pairs["published_record_start_date"].null_count() == 2
    assert pairs["published_record_end_date"].null_count() == 2


def test_source_descriptions_preserve_unknown_time_and_datum():
    from rivretrieve._internal.providers.pe_senamhi.generate_catalogue import describe_associations, phisis_associations

    associations = phisis_associations(
        envelope({"station": {"code": "A"}, "type": "DAILY", "variable": "LEVEL", "unit": "m.s.n.m"}),
        station="A",
        resolution="DAILY",
        variable="LEVEL",
        station_ids={"A"},
    )
    description = describe_associations(associations).descriptions[0]
    facts = description.facts[0]
    assert facts.source_unit.value == "m.s.n.m"
    assert facts.vertical_reference.value == "above_sea_level"
    assert facts.frequency.value is None
    assert facts.time_zone.value is None
    assert facts.vertical_datum.value is None


def test_conflicting_registry_identity_and_mismatched_response_are_fatal():
    import pytest

    from rivretrieve._internal.issues import FatalContractError
    from rivretrieve._internal.providers.pe_senamhi.generate_catalogue import phisis_associations

    with pytest.raises(FatalContractError, match="disagree"):
        station_native_table(
            envelope([station("A")]),
            envelope([]),
            envelope([station("A", name="Changed")]),
            retrieved_at=RetrievedAt(datetime(2026, 10, 31, tzinfo=UTC)),
        )
    with pytest.raises(FatalContractError, match="differs"):
        phisis_associations(
            envelope({"station": {"code": "B"}, "type": "HOURLY", "variable": "LEVEL", "unit": "m"}),
            station="A",
            resolution="HOURLY",
            variable="LEVEL",
            station_ids={"A", "B"},
        )
