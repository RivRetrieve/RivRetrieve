from __future__ import annotations

import pytest

from rivretrieve._internal.observations import AnnotationSchema, ObservationRequest
from rivretrieve._internal.primitives import OnIssue, ProviderId
from rivretrieve._internal.provider_module import ProviderModule
from rivretrieve._internal.providers.ch_foen import module as ch_foen_module


def test_ch_foen_module_matches_provider_module_protocol() -> None:
    assert isinstance(ch_foen_module, ProviderModule)


def test_ch_foen_info_returns_provider_info() -> None:
    provider_info = ch_foen_module.info()

    assert provider_info.provider_id == "ch_foen"
    assert provider_info.name == "Swiss Federal Office for the Environment FOEN / BAFU"


def test_ch_foen_products_returns_packaged_products() -> None:
    result = ch_foen_module.products()

    assert result.data.height == 6
    assert set(result.data["provider_id"].to_list()) == {"ch_foen"}


def test_ch_foen_stations_returns_packaged_stations() -> None:
    result = ch_foen_module.stations()

    assert result.data.height == 246
    assert result.data.filter(result.data["station_id"] == "2016").select("name").item() == "Brugg"


def test_ch_foen_station_products_returns_packaged_availability() -> None:
    result = ch_foen_module.station_products()

    assert result.data.height == 1476
    assert set(result.data["availability"].cast(str).to_list()) == {"unknown"}


def test_ch_foen_row_annotation_schema_declares_m4_observation_names() -> None:
    schemas = ch_foen_module.row_annotation_schema()

    assert [schema.annotation_id for schema in schemas] == [
        "native_field",
        "native_unit",
        "converted_unit",
        "source_endpoint_or_query",
        "raw_value",
        "alternative_native_field",
        "alternative_raw_value",
        "alternative_native_unit",
    ]
    assert [schema.value_type for schema in schemas] == [
        "string",
        "string",
        "string",
        "string",
        "float",
        "string",
        "float",
        "string",
    ]
    for schema in schemas:
        assert AnnotationSchema.from_row(schema.to_row()) == schema


def test_ch_foen_series_annotation_schema_declares_m4_observation_names() -> None:
    schemas = ch_foen_module.series_annotation_schema()

    assert [schema.annotation_id for schema in schemas] == [
        "preferred_source",
        "fallback_source_used",
        "native_unit_returned",
        "converted_unit",
        "returned_time_range_start",
        "returned_time_range_end",
        "resolved_timezone",
        "timezone_mismatch_flag",
        "provider_endpoint",
        "provider_query_fields",
    ]
    assert [schema.value_type for schema in schemas] == [
        "string",
        "boolean",
        "string",
        "string",
        "datetime",
        "datetime",
        "string",
        "boolean",
        "string",
        "json",
    ]
    for schema in schemas:
        assert AnnotationSchema.from_row(schema.to_row()) == schema


@pytest.mark.parametrize("on_issue", ["warn", "raise", "ignore"])
def test_ch_foen_observations_placeholder_returns_issue_result(on_issue: OnIssue) -> None:
    request = ObservationRequest.from_inputs(
        provider_id=ProviderId("ch_foen"),
        stations="2016",
        products="discharge_daily_mean",
        start="2026-01-01",
        end="2026-01-02",
    )

    result = ch_foen_module.observations(request, on_issue=on_issue)

    assert result.data.is_empty()
    assert result.row_annotations.data.is_empty()
    assert result.series_annotations.data.is_empty()
    assert result.provenance.source == "placeholder"
    assert result.provenance.provider_id == "ch_foen"
    assert result.provenance.catalogue_version == "2026-05-28"
    assert result.raw is None
    assert len(result.issues) == 1
    assert result.issues[0].severity == "error"
    assert result.issues[0].code == "observations_not_yet_implemented"
