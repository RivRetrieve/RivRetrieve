"""Tests for jp_mlit provider registration and module contract."""

from __future__ import annotations

import rivretrieve as rr


def test_jp_mlit_in_providers_list() -> None:
    assert "jp_mlit" in rr.providers()


def test_jp_mlit_provider_handle_returns() -> None:
    handle = rr.provider("jp_mlit")
    assert handle is not None


def test_jp_mlit_info_name() -> None:
    info = rr.provider("jp_mlit").info()
    assert "Japan" in info.name or "MLIT" in info.name


def test_jp_mlit_catalogue_version() -> None:
    info = rr.provider("jp_mlit").info()
    assert info.catalogue_version is not None


def test_jp_mlit_stations_returns_catalog_result() -> None:
    result = rr.provider("jp_mlit").stations()
    assert hasattr(result, "data")
    assert hasattr(result, "provenance")
    assert hasattr(result, "issues")


def test_jp_mlit_stations_count() -> None:
    result = rr.provider("jp_mlit").stations()
    assert len(result.data) == 1024


def test_jp_mlit_products_count() -> None:
    result = rr.provider("jp_mlit").products()
    assert len(result.data) == 4


def test_jp_mlit_station_products_count() -> None:
    result = rr.provider("jp_mlit").station_products()
    assert len(result.data) == 4096


def test_jp_mlit_global_stations_includes_provider() -> None:
    result = rr.stations()
    provider_ids = result.data["provider_id"].unique().to_list()
    assert "jp_mlit" in provider_ids


def test_jp_mlit_annotation_schemas_non_empty() -> None:
    from rivretrieve._internal.providers.jp_mlit import module as jp_mlit_module

    assert len(jp_mlit_module.row_annotation_schema()) > 0
    assert len(jp_mlit_module.series_annotation_schema()) > 0


def test_jp_mlit_annotation_schema_ids_are_strings() -> None:
    from rivretrieve._internal.providers.jp_mlit import module as jp_mlit_module

    for schema in jp_mlit_module.row_annotation_schema() + jp_mlit_module.series_annotation_schema():
        assert isinstance(schema.annotation_id, str)
        assert schema.annotation_id


def test_jp_mlit_live_catalogue_unsupported() -> None:
    result = rr.provider("jp_mlit").stations(source="live")
    assert len(result.issues) > 0
