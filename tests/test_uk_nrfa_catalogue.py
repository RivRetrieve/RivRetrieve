"""NRFA advertised associations and source metadata survive catalogue projection."""

from datetime import UTC, datetime

import polars as pl
import polars.testing as pt

from rivretrieve._internal.catalogues.native import RetrievedAt, stamp_native_table
from rivretrieve._internal.providers.uk_nrfa.generate_catalogue import build_station_products, build_stations


def test_station_projection_keeps_closed_stations_and_missing_coordinates():
    native = stamp_native_table(
        pl.DataFrame(
            {
                "station_id": ["12345", "201234"],
                "latitude": [51.25, None],
                "longitude": [-1.5, None],
                "closed": ["2000-01-01", None],
            }
        ),
        RetrievedAt(datetime(2026, 11, 6, tzinfo=UTC)),
    )
    expected = pl.DataFrame(
        {
            "provider_id": ["uk_nrfa", "uk_nrfa"],
            "station_id": ["12345", "201234"],
            "latitude": [51.25, None],
            "longitude": [-1.5, None],
            "crs": ["EPSG:4326", "EPSG:4326"],
        }
    )
    pt.assert_frame_equal(build_stations(native), expected)


def test_only_advertised_products_are_published_with_unknown_bounds():
    native = stamp_native_table(
        pl.DataFrame(
            {
                "station_id": ["12345", "201234"],
                "data-summary": [
                    {"data-types": entries}
                    for entries in [
                        [
                            {"data-type": "gdf", "first": "1970-01-01", "last": "2025-01-01"},
                            {"data-type": "gmf", "first": "1970-01", "last": "2025-01"},
                            {"data-type": "rainfall", "first": None, "last": None},
                        ],
                        [{"data-type": "gauging-stage", "first": "2020-01-01T12:30:00", "last": None}],
                    ]
                ],
            }
        ),
        RetrievedAt(datetime(2026, 11, 6, tzinfo=UTC)),
    )
    result = build_station_products(native)
    assert set(result.select("station_id", "product_id").iter_rows()) == {
        ("12345", "gdf"),
        ("12345", "gmf"),
        ("201234", "gauging-stage"),
    }
    assert result["availability"].to_list() == ["available"] * 3
    assert result["published_record_start_date"].null_count() == 3
    assert result["published_record_end_date"].null_count() == 3
    assert native.data["data-summary"][0]["data-types"][1]["first"] == "1970-01"


def test_ten_products_keep_distinct_identity_without_inferred_temporal_facts():
    from rivretrieve._internal.providers.uk_nrfa.catalogue_series import product_facts

    expected = {
        "gdf",
        "ndf",
        "gmf",
        "nmf",
        "gauging-flow",
        "gauging-stage",
        "amax-flow",
        "amax-stage",
        "pot-flow",
        "pot-stage",
    }
    facts = product_facts()
    assert set(facts) == expected
    for product, physical in facts.items():
        stage = product.endswith("stage")
        assert physical.quantity.value == ("stage" if stage else "discharge")
        assert physical.source_unit.value == ("m" if stage else "m3/s")
        assert physical.frequency.value is None
        assert physical.statistic.value is None
        assert physical.vertical_datum.value is None
        assert physical.vertical_reference.value is None


def test_native_preparation_preserves_source_fields_and_reconciles_inventory():
    import pytest

    from rivretrieve._internal.issues import FatalContractError
    from rivretrieve._internal.providers.uk_nrfa.generate_catalogue import prepare_native_table

    summary = {
        "data-type": "gmf",
        "parameter": "flow",
        "units": "m3/s",
        "period": "monthly",
        "first": "2000-01",
        "last": "2020-06",
    }
    rows = [
        {
            "id": identity,
            "name": "Example Gauge",
            "river": "Example River",
            "lat-long": {"string": "source spelling", "latitude": 51.25, "longitude": -1.5},
            "station-level": altitude,
            "catchment-area": 12.5,
            "opened": "2000-01-01",
            "closed": "2020-06-30",
            "data-summary": {"data-types": [summary]},
        }
        for identity, altitude in [(12345, 10.5), (101234, None), (201234, 2.0), (301234, 3.0)]
    ]
    ids = {"station-ids": [12345, 101234, 201234, 301234]}
    native = prepare_native_table({"data": rows}, ids, retrieved_at=RetrievedAt(datetime(2026, 11, 6, tzinfo=UTC)))
    assert native.data["station_id"].to_list() == ["101234", "12345", "201234", "301234"]
    assert native.data["id"].dtype == pl.Int64
    assert native.data["station-level"].dtype == pl.Float64
    assert native.data["station-level"].null_count() == 1
    assert native.data["station_altitude_datum"].to_list() == ["Ordnance Datum", "Ordnance Datum", "Malin Head", None]
    assert native.data["data-summary"][0]["data-types"][0] == summary
    assert native.data["lat-long"][0]["string"] == "source spelling"
    with pytest.raises(FatalContractError, match="inventory"):
        prepare_native_table(
            {"data": rows}, {"station-ids": [12345]}, retrieved_at=RetrievedAt(datetime(2026, 11, 6, tzinfo=UTC))
        )
