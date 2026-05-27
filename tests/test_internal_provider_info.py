from __future__ import annotations

import pytest

from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.provider_info import ProviderInfo, ProviderInfoValidationError


def valid_provider_info_row() -> dict[str, object]:
    return {
        "provider_id": "stub_provider",
        "name": "Stub Provider",
        "live_stations": False,
        "live_products": True,
        "live_station_products": False,
        "bulk_observations": "none",
        "catalogue_version": "2026.01",
        "metadata": '{"homepage":"https://stub.example.invalid"}',
    }


def test_provider_info_from_row_matches_provider_info_catalog_contract() -> None:
    info = ProviderInfo.from_row(valid_provider_info_row())

    assert info == ProviderInfo(
        provider_id=ProviderId("stub_provider"),
        name="Stub Provider",
        live_stations=False,
        live_products=True,
        live_station_products=False,
        bulk_observations="none",
        catalogue_version="2026.01",
        metadata='{"homepage":"https://stub.example.invalid"}',
    )


def test_provider_info_to_row_round_trips_catalogue_row() -> None:
    row = valid_provider_info_row()

    assert ProviderInfo.from_row(row).to_row() == row


def test_provider_info_metadata_is_raw_json_string() -> None:
    info = ProviderInfo.from_row(valid_provider_info_row())

    assert isinstance(info.metadata, str)


@pytest.mark.parametrize("field_name", list(valid_provider_info_row()))
def test_provider_info_rejects_missing_required_field(field_name: str) -> None:
    row = valid_provider_info_row()
    del row[field_name]

    with pytest.raises(ProviderInfoValidationError):
        ProviderInfo.from_row(row)


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    [
        ("provider_id", 123),
        ("name", 123),
        ("live_stations", "false"),
        ("live_products", 1),
        ("live_station_products", None),
        ("bulk_observations", False),
        ("catalogue_version", 123),
        ("metadata", {"homepage": "https://stub.example.invalid"}),
    ],
)
def test_provider_info_rejects_wrong_field_type(field_name: str, bad_value: object) -> None:
    row = valid_provider_info_row()
    row[field_name] = bad_value

    with pytest.raises(ProviderInfoValidationError):
        ProviderInfo.from_row(row)


def test_provider_info_rejects_invalid_metadata_json() -> None:
    row = valid_provider_info_row()
    row["metadata"] = "{"

    with pytest.raises(ProviderInfoValidationError):
        ProviderInfo.from_row(row)


@pytest.mark.parametrize("metadata", ["[]", "null"])
def test_provider_info_rejects_non_object_metadata_json(metadata: str) -> None:
    row = valid_provider_info_row()
    row["metadata"] = metadata

    with pytest.raises(ProviderInfoValidationError):
        ProviderInfo.from_row(row)
