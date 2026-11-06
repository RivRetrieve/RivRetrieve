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


def test_metadata_projection_preserves_source_values_nulls_units_and_datum():
    from rivretrieve._internal.catalogues.station_metadata import build_station_metadata
    from rivretrieve._internal.providers.uk_nrfa.origins import STATION_CATALOGUE_ORIGINS, STATION_METADATA_FIELDS

    native = stamp_native_table(
        pl.DataFrame(
            {
                "station_id": ["12345", "201234"],
                "latitude": [51.25, 54.5],
                "longitude": [-1.5, -6.0],
                "name": ["Example Gauge", "Closed Gauge"],
                "river": ["River Example", None],
                "catchment-area": [12.5, 8.0],
                "station-level": [None, 2.0],
                "station_altitude_datum": ["Ordnance Datum", "Malin Head"],
            }
        ),
        RetrievedAt(datetime(2026, 11, 6, tzinfo=UTC)),
    )
    metadata = build_station_metadata(
        "uk_nrfa", native, build_stations(native), STATION_CATALOGUE_ORIGINS["station_id"], STATION_METADATA_FIELDS
    )
    altitude = metadata.filter(pl.col("attribute_role") == "elevation").sort("station_id")
    assert altitude["source_value"].to_list() == [None, "2.0"]
    assert altitude["source_dtype"].to_list() == ["Float64", "Float64"]
    assert altitude["source_unit"].to_list() == ["m", "m"]
    assert altitude["state"].to_list() == ["source_null", "value"]
    assert altitude["source_datum"].to_list() == ["Ordnance Datum", "Malin Head"]
    area = metadata.filter(pl.col("attribute_role") == "drainage_area").sort("station_id")
    assert area["source_value"].to_list() == ["12.5", "8.0"]
    assert area["source_unit"].to_list() == ["km²", "km²"]
    names = metadata.filter(pl.col("attribute_role") == "station_name").sort("station_id")
    assert names["source_value"].to_list() == ['"Example Gauge"', '"Closed Gauge"']


def test_native_preparation_refuses_lossy_scalar_inference():
    import pytest

    from rivretrieve._internal.issues import FatalContractError
    from rivretrieve._internal.providers.uk_nrfa.generate_catalogue import prepare_native_table

    rows = [
        {
            "id": identity,
            "station-level": altitude,
            "catchment-area": 12,
            "lat-long": {"latitude": 51.25, "longitude": -1.5},
            "data-summary": {"data-types": []},
        }
        for identity, altitude in [(12345, 10), (12346, 10.5), (12347, None)]
    ]
    instant = RetrievedAt(datetime(2026, 11, 6, tzinfo=UTC))
    with pytest.raises(FatalContractError, match="scalar"):
        prepare_native_table({"data": rows}, {"station-ids": [12345, 12346, 12347]}, retrieved_at=instant)
    rows[1]["station-level"] = 11
    native = prepare_native_table({"data": rows}, {"station-ids": [12345, 12346, 12347]}, retrieved_at=instant)
    assert native.data["station-level"].dtype == pl.Int64
    assert native.data["station-level"].to_list() == [10, 11, None]


def test_catalogue_composition_enforces_declared_station_origins():
    import pytest

    from rivretrieve._internal.catalogue_origins import Authored, AuthoredValue
    from rivretrieve._internal.issues import FatalContractError
    from rivretrieve._internal.providers.uk_nrfa.generate_catalogue import build_catalogue
    from rivretrieve._internal.providers.uk_nrfa.origins import STATION_CATALOGUE_ORIGINS

    native = stamp_native_table(
        pl.DataFrame(
            {
                "station_id": ["12345"],
                "latitude": [51.25],
                "longitude": [-1.5],
                "data-summary": [{"data-types": [{"data-type": "gdf", "first": "2000-01-01", "last": "2020-01-01"}]}],
            }
        ),
        RetrievedAt(datetime(2026, 11, 6, tzinfo=UTC)),
    )
    with pytest.raises(FatalContractError):
        build_catalogue(native, {**STATION_CATALOGUE_ORIGINS, "provider_id": Authored(AuthoredValue("wrong_provider"))})
    result = build_catalogue(native, STATION_CATALOGUE_ORIGINS)
    assert result.products.height == 10
    assert result.station_products.height == 1
    assert result.provider_info["citation"] == "Data from the UK National River Flow Archive"


def test_publication_encodes_catalogue_only_descriptions_and_crs_support(tmp_path):
    from rivretrieve._internal.acquisition_provenance import (
        ArchiveMemberReference,
        CatalogueBuildInputs,
        CodeReference,
        RetainedInputUse,
    )
    from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
    from rivretrieve._internal.providers.uk_nrfa import origins
    from rivretrieve._internal.providers.uk_nrfa.generate_catalogue import build_catalogue, write_catalogue

    native = stamp_native_table(
        pl.DataFrame(
            {
                "station_id": ["12345"],
                "latitude": [51.25],
                "longitude": [-1.5],
                "name": ["Example"],
                "river": ["River"],
                "catchment-area": [12.0],
                "station-level": [3.0],
                "station_altitude_datum": ["Ordnance Datum"],
                "data-summary": [{"data-types": [{"data-type": "gdf", "first": "2000-01-01", "last": "2020-01-01"}]}],
            }
        ),
        RetrievedAt(datetime(2026, 11, 6, tzinfo=UTC)),
    )
    generated = build_catalogue(native, origins.STATION_CATALOGUE_ORIGINS)

    def code(path, symbol):
        return CodeReference(
            repository="https://github.com/RivRetrieve/RivRetrieve",
            revision="a" * 40,
            repository_path=path,
            symbol=symbol,
        )

    uses = tuple(
        RetainedInputUse(
            reference=ArchiveMemberReference(
                archive_repository="https://github.com/RivRetrieve/verification-evidence",
                archive_revision="b" * 40,
                collection_id="synthetic",
                manifest_sha256="c" * 64,
                artifact_id=str(index),
                sha256=origins.NATIVE_TABLE_SHA256 if index == 0 else "d" * 64,
                byte_size=origins.NATIVE_TABLE_BYTE_SIZE if index == 0 else 1,
                role="derived_input" if index == 0 else "publisher_original",
            ),
            usage="native_table" if index == 0 else "recording",
            facts=binding.facts,
        )
        for index, binding in enumerate(generated.acquisition_provenance.fact_bindings)
        if binding.transformation is None
    )
    build = CatalogueBuildInputs(
        build=code("src/rivretrieve/_internal/providers/uk_nrfa/generate_catalogue.py", "main"),
        declarations=tuple(code(path, symbol) for path, symbol in origins.CATALOGUE_BUILD_DECLARATIONS),
        inputs=uses,
    )
    write_catalogue(generated, tmp_path, build_inputs=build, native_table=native)
    loaded = load_packaged_catalogue_artifact(tmp_path, on_issue="raise")
    assert loaded.products.height == 10
    assert loaded.station_products.height == 1
    assert loaded.source_descriptions.provider_id == "uk_nrfa"
    assert {item.identity.published_id for item in loaded.source_descriptions.descriptions} == {
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
    from rivretrieve._internal.catalogues.source_series import materialize_series
    from rivretrieve._internal.selection import _Selection
    from rivretrieve._internal.source_series import SeriesScope

    # Exercise the shared selection contract with several products at one gauge.
    from dataclasses import replace

    all_products = pl.concat(
        [
            loaded.station_products.with_columns(pl.lit(product).alias("product_id"))
            for product in loaded.products["product_id"]
        ]
    )
    series, inventories = materialize_series(replace(loaded, station_products=all_products))
    selection = _Selection(scope=SeriesScope(provider_ids=("uk_nrfa",)), known_series=series, inventories=inventories)
    assert len(selection.known_series) == 10
    assert "source.station.documented_crs" in generated.acquisition_provenance.fact_universe
    metadata = pl.read_parquet(tmp_path / "station_metadata.parquet")
    assert metadata.filter(pl.col("attribute_role") == "elevation")["source_datum"].item() == "Ordnance Datum"
