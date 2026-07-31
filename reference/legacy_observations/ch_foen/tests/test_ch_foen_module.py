from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from rivretrieve._internal.observations import AnnotationSchema, ObservationRequest
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.provider_module import ProviderModule
from rivretrieve._internal.providers.ch_foen import module as ch_foen_module
from rivretrieve._internal.providers.ch_foen.observation_client import (
    ChFoenObservationClient,
    ChFoenTransportRequest,
    ChFoenTransportResponse,
)

TEST_DATA = Path(__file__).parent / "test_data"


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


def test_ch_foen_observations_delegates_to_real_retrieval(monkeypatch) -> None:
    def transport(_request: ChFoenTransportRequest) -> ChFoenTransportResponse:
        return ChFoenTransportResponse(
            content=(TEST_DATA / "switzerland_2206_discharge_20250101.csv").read_bytes(),
            status_code=200,
            retrieved_at=datetime(2026, 5, 28, tzinfo=UTC),
        )

    monkeypatch.setattr(
        ch_foen_module,
        "_observation_client_factory",
        lambda: ChFoenObservationClient(token="fake-token", transport=transport),
    )
    request = ObservationRequest.from_inputs(
        provider_id=ProviderId("ch_foen"),
        stations="2206",
        products="discharge_instantaneous",
        start="2025-01-01",
        end="2025-01-01",
    )

    result = ch_foen_module.observations(request, on_issue="ignore")

    assert result.data.height == 144
    assert set(result.data["station_id"].to_list()) == {"2206"}
    assert set(result.data["product_id"].to_list()) == {"discharge_instantaneous"}
    assert result.provenance.source == "live"
    assert result.provenance.provider_id == "ch_foen"
    assert result.provenance.catalogue_version == "2026-05-28"


def test_ch_foen_observations_not_yet_implemented_code_removed() -> None:
    from rivretrieve._internal.providers.ch_foen.issue_codes import ChFoenObservationIssueCodes

    assert "observations_not_yet_implemented" not in {code.value for code in ChFoenObservationIssueCodes}
