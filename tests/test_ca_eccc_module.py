"""Tests for ca_eccc provider registration and module contract."""

from __future__ import annotations

import rivretrieve as rr


def test_ca_eccc_in_providers_list() -> None:
    assert "ca_eccc" in rr.providers()


def test_ca_eccc_provider_handle_returns() -> None:
    handle = rr.provider("ca_eccc")
    assert handle is not None


def test_ca_eccc_info_name() -> None:
    info = rr.provider("ca_eccc").info()
    assert "Canada" in info.name or "ECCC" in info.name


def test_ca_eccc_catalogue_version() -> None:
    info = rr.provider("ca_eccc").info()
    assert info.catalogue_version is not None


def test_ca_eccc_live_stations_capability() -> None:
    info = rr.provider("ca_eccc").info()
    assert info.live_stations is False


def test_ca_eccc_stations_returns_catalog_result() -> None:
    result = rr.provider("ca_eccc").stations()
    assert hasattr(result, "data")
    assert hasattr(result, "provenance")
    assert hasattr(result, "issues")


def test_ca_eccc_stations_count() -> None:
    result = rr.provider("ca_eccc").stations()
    # Live catalogue (2026-06-04): 8055 stations.
    assert len(result.data) == 8055


def test_ca_eccc_products_count() -> None:
    result = rr.provider("ca_eccc").products()
    assert len(result.data) == 2


def test_ca_eccc_products_include_canonical() -> None:
    result = rr.provider("ca_eccc").products()
    product_ids = set(result.data["product_id"].to_list())
    assert "discharge_daily_mean" in product_ids
    assert "stage_daily_mean" in product_ids


def test_ca_eccc_station_products_count() -> None:
    result = rr.provider("ca_eccc").station_products()
    # 8055 stations × 2 products = 16110
    assert len(result.data) == 16110


def test_ca_eccc_station_products_availability_unknown() -> None:
    """OGC endpoint does not expose per-variable availability → all unknown."""
    result = rr.provider("ca_eccc").station_products()
    availabilities = set(result.data["availability"].cast(str).to_list())
    assert availabilities == {"unknown"}


def test_ca_eccc_global_stations_includes_provider() -> None:
    result = rr.stations()
    provider_ids = result.data["provider_id"].unique().to_list()
    assert "ca_eccc" in provider_ids


def test_ca_eccc_annotation_schemas_non_empty() -> None:
    from rivretrieve._internal.providers.ca_eccc import module as ca_eccc_module

    assert len(ca_eccc_module.row_annotation_schema()) > 0
    assert len(ca_eccc_module.series_annotation_schema()) > 0


def test_ca_eccc_annotation_schema_ids_are_strings() -> None:
    from rivretrieve._internal.providers.ca_eccc import module as ca_eccc_module

    for schema in ca_eccc_module.row_annotation_schema() + ca_eccc_module.series_annotation_schema():
        assert isinstance(schema.annotation_id, str)
        assert schema.annotation_id


def test_ca_eccc_live_catalogue_returns_warning_issue() -> None:
    result = rr.provider("ca_eccc").stations(source="live", on_issue="ignore")
    assert len(result.issues) > 0


def test_ca_eccc_stations_schema_has_expected_columns() -> None:
    result = rr.provider("ca_eccc").stations()
    expected = {"provider_id", "station_id", "name", "latitude", "longitude", "country"}
    assert expected.issubset(set(result.data.columns))


def test_ca_eccc_station_grand_river_present() -> None:
    result = rr.provider("ca_eccc").stations()
    ids = result.data["station_id"].to_list()
    assert "02GA010" in ids


def test_ca_eccc_station_no_elevation() -> None:
    """ECCC OGC stations endpoint does not provide elevation — always null."""
    result = rr.provider("ca_eccc").stations()
    assert result.data["elevation_m"].is_null().all()
