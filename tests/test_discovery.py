from __future__ import annotations

from collections.abc import Callable

import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.catalogue_reader import CatalogueReader
from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.catalogues.schemas import (
    PRODUCT_CATALOG_SCHEMA,
    PROVIDER_INFO_CATALOG_SCHEMA,
    STATION_CATALOG_SCHEMA,
)
from rivretrieve._internal.discovery import product_info, products, stations
from rivretrieve._internal.issues import IssuePolicyError
from rivretrieve._internal.registry import UnknownProviderError, _ProviderHandle, _registry
from rivretrieve._internal.results import CatalogProvenance, CatalogResult

EXPECTED_PRODUCT_IDS = [
    "discharge_daily_max",
    "discharge_daily_mean",
    "discharge_hourly_mean",
    "discharge_instantaneous",
    "stage_daily_max",
    "stage_daily_mean",
    "stage_daily_min",
    "stage_hourly_mean",
    "stage_instantaneous",
    "water_temperature_daily_mean",
    "water_temperature_hourly_mean",
    "water_temperature_instantaneous",
]

EXPECTED_PRODUCTS_BY_PROVIDER = {
    "ba_fhmzbih": [
        "discharge_instantaneous",
        "stage_instantaneous",
        "water_temperature_instantaneous",
    ],
    "br_ana": [
        "discharge_daily_mean",
        "discharge_instantaneous",
        "stage_daily_mean",
        "stage_instantaneous",
        "water_temperature_instantaneous",
    ],
    "ca_eccc": [
        "discharge_daily_mean",
        "stage_daily_mean",
    ],
    "ch_foen": [
        "discharge_instantaneous",
        "stage_instantaneous",
        "water_temperature_instantaneous",
    ],
    "cz_chmi": [
        "discharge_daily_mean",
        "discharge_instantaneous",
        "stage_daily_mean",
        "stage_instantaneous",
        "water_temperature_daily_mean",
    ],
    "fr_hubeau": [
        "discharge_daily_max",
        "discharge_daily_mean",
        "discharge_instantaneous",
        "stage_daily_max",
        "stage_instantaneous",
        "water_temperature_instantaneous",
    ],
    "jp_mlit": [
        "discharge_daily_mean",
        "discharge_hourly_mean",
        "stage_daily_mean",
        "stage_hourly_mean",
    ],
    "lt_lhmt": [
        "discharge_daily_mean",
        "stage_daily_mean",
    ],
    "no_nve": [
        "discharge_daily_mean",
        "discharge_hourly_mean",
        "discharge_instantaneous",
        "stage_daily_mean",
        "stage_hourly_mean",
        "stage_instantaneous",
        "water_temperature_daily_mean",
        "water_temperature_hourly_mean",
        "water_temperature_instantaneous",
    ],
    "pl_imgw": [
        "discharge_daily_mean",
        "stage_daily_mean",
        "water_temperature_daily_mean",
    ],
    "th_thaiwater": [
        "discharge_instantaneous",
        "stage_instantaneous",
    ],
    "usgs_nwis": [
        "discharge_daily_mean",
        "discharge_instantaneous",
        "stage_daily_max",
        "stage_daily_mean",
        "stage_daily_min",
        "stage_instantaneous",
    ],
    "za_dws": [
        "discharge_daily_mean",
        "discharge_instantaneous",
        "stage_instantaneous",
    ],
}


def _issue_policy_error_chain(exc: BaseException) -> list[IssuePolicyError]:
    found = []
    seen: set[int] = set()
    stack: list[BaseException] = [exc]
    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, IssuePolicyError):
            found.append(current)
        if current.__cause__ is not None:
            stack.append(current.__cause__)
        if current.__context__ is not None:
            stack.append(current.__context__)
    return found


def _disable_default_provider_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(discovery, "_DEFAULT_PROVIDER_REGISTRATION_ENABLED", False)
    _registry.clear()


def test_providers_empty_registry_returns_default_providers() -> None:
    assert rr.providers() == [
        "ba_fhmzbih",
        "br_ana",
        "ca_eccc",
        "ch_foen",
        "cz_chmi",
        "fr_hubeau",
        "jp_mlit",
        "lt_lhmt",
        "no_nve",
        "pl_imgw",
        "th_thaiwater",
        "usgs_nwis",
        "za_dws",
    ]


def test_providers_sorted_independent_of_registration_order(
    monkeypatch: pytest.MonkeyPatch,
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    _disable_default_provider_registration(monkeypatch)
    _registry.register("z_provider", stub_packaged_catalogue_artifact("z_provider"))
    _registry.register("a_provider", stub_packaged_catalogue_artifact("a_provider"))

    assert rr.providers() == ["a_provider", "z_provider"]


def test_provider_returns_registered_placeholder_object(
    monkeypatch: pytest.MonkeyPatch,
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    _disable_default_provider_registration(monkeypatch)
    expected = _registry.register("stub_provider", stub_packaged_catalogue_artifact("stub_provider"))

    handle = rr.provider("stub_provider")

    assert isinstance(handle, object)
    assert isinstance(handle, _ProviderHandle)
    assert handle is expected


def test_provider_unknown_raises_unknown_provider_error() -> None:
    with pytest.raises(UnknownProviderError) as exc_info:
        rr.provider("missing")

    assert not isinstance(exc_info.value, IssuePolicyError)
    assert _issue_policy_error_chain(exc_info.value) == []


def test_provider_info_disabled_defaults_empty_registry_returns_schema_conformant_catalog_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_default_provider_registration(monkeypatch)
    expected_provenance = CatalogProvenance(
        source="packaged",
        provider_id=None,
        rivretrieve_version=rr.__version__,
        catalogue_version=None,
        artifact_id=None,
        artifact_path=None,
        artifact_hash=None,
        generated_at=None,
        retrieved_at=None,
        endpoints=(),
        query=None,
        response_version=None,
    )

    result = rr.provider_info()

    assert isinstance(result, CatalogResult)
    assert result.issues == ()
    assert result.provenance == expected_provenance
    assert result.data.schema == PROVIDER_INFO_CATALOG_SCHEMA.polars_schema
    assert result.data.height == 0


def test_provider_info_aggregates_registered_provider_rows(
    monkeypatch: pytest.MonkeyPatch,
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    _disable_default_provider_registration(monkeypatch)
    _registry.register("z_provider", stub_packaged_catalogue_artifact("z_provider", catalogue_version=None))
    _registry.register("a_provider", stub_packaged_catalogue_artifact("a_provider", catalogue_version="2026.02"))
    expected = pl.DataFrame(
        [
            {
                "provider_id": "a_provider",
                "name": "a_provider Provider",
                "live_stations": False,
                "live_products": False,
                "live_station_products": False,
                "bulk_observations": "none",
                "catalogue_version": "2026.02",
                "license": None,
                "citation": None,
            },
            {
                "provider_id": "z_provider",
                "name": "z_provider Provider",
                "live_stations": False,
                "live_products": False,
                "live_station_products": False,
                "bulk_observations": "none",
                "catalogue_version": None,
                "license": None,
                "citation": None,
            },
        ],
        schema=PROVIDER_INFO_CATALOG_SCHEMA.polars_schema,
    )

    result = rr.provider_info()

    pl_testing.assert_frame_equal(result.data, expected, check_exact=True)
    assert result.issues == ()
    assert result.provenance.source == "packaged"


def test_provider_lookup_malformed_id_is_membership_miss() -> None:
    with pytest.raises(UnknownProviderError):
        rr.provider("BAD-Provider")


def test_global_stations_aggregates_registered_packaged_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    _disable_default_provider_registration(monkeypatch)
    _registry.register("z_provider", stub_packaged_catalogue_artifact("z_provider"))
    _registry.register("a_provider", stub_packaged_catalogue_artifact("a_provider"))

    result = stations()

    assert result.data.select("provider_id", "station_id").rows() == [
        ("a_provider", "station-1"),
        ("z_provider", "station-1"),
    ]
    assert result.data.schema == STATION_CATALOG_SCHEMA.polars_schema
    assert result.issues == ()


def test_default_provider_stations_share_canonical_schema_and_non_null_crs() -> None:
    result = rr.stations()

    assert result.data.schema == STATION_CATALOG_SCHEMA.polars_schema
    assert set(result.data["provider_id"].unique()) == set(rr.providers())
    assert result.data["crs"].null_count() == 0
    documented_wgs84 = result.data.filter(pl.col("provider_id").is_in(["lt_lhmt", "ca_eccc", "fr_hubeau"]))
    usgs = result.data.filter(pl.col("provider_id") == "usgs_nwis")
    other_providers = result.data.filter(~pl.col("provider_id").is_in(["lt_lhmt", "ca_eccc", "fr_hubeau", "usgs_nwis"]))
    poland = result.data.filter(pl.col("provider_id") == "pl_imgw")
    assert set(documented_wgs84["crs"].to_list()) == {"EPSG:4326"}
    assert set(usgs["crs"].to_list()) == {"EPSG:4269"}
    assert set(other_providers["crs"].to_list()) == {"unknown"}
    assert set(poland["crs"].to_list()) == {"unknown"}
    assert set(other_providers["provider_id"].unique()) == set(rr.providers()) - {
        "lt_lhmt",
        "ca_eccc",
        "fr_hubeau",
        "usgs_nwis",
    }


def test_global_products_returns_sorted_deduplicated_vocabulary(
    monkeypatch: pytest.MonkeyPatch,
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    _disable_default_provider_registration(monkeypatch)
    _registry.register("z_provider", stub_packaged_catalogue_artifact("z_provider"))
    _registry.register("a_provider", stub_packaged_catalogue_artifact("a_provider"))

    assert products() == ["level"]


def test_global_product_info_retains_independent_table_contract(
    monkeypatch: pytest.MonkeyPatch,
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    _disable_default_provider_registration(monkeypatch)
    artifact = stub_packaged_catalogue_artifact("stub_provider")
    _registry.register("stub_provider", artifact)

    product_info_result = product_info()

    assert products() == ["level"]
    assert isinstance(product_info_result, CatalogResult)
    pl_testing.assert_frame_equal(product_info_result.data, artifact.products, check_exact=True)
    assert product_info_result.issues == ()
    assert product_info_result.provenance.source == "packaged"


def test_global_discovery_disabled_defaults_empty_registry_distinguishes_result_kinds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_default_provider_registration(monkeypatch)
    station_result = stations()
    product_result = products()
    product_info_result = product_info()

    assert station_result.data.schema == STATION_CATALOG_SCHEMA.polars_schema
    assert station_result.data.height == 0
    assert product_result == []
    assert type(product_result) is list
    assert product_info_result.data.schema == PRODUCT_CATALOG_SCHEMA.polars_schema
    assert product_info_result.data.height == 0
    assert station_result.provenance.source == "packaged"
    assert product_info_result.provenance.source == "packaged"


def test_global_discovery_provenance_is_global_packaged(
    monkeypatch: pytest.MonkeyPatch,
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    _disable_default_provider_registration(monkeypatch)
    _registry.register("stub_provider", stub_packaged_catalogue_artifact("stub_provider"))
    expected = CatalogProvenance(
        source="packaged",
        provider_id=None,
        rivretrieve_version=rr.__version__,
        catalogue_version=None,
        artifact_id=None,
        artifact_path=None,
        artifact_hash=None,
        generated_at=None,
        retrieved_at=None,
        endpoints=(),
        query=None,
        response_version=None,
    )

    assert stations().provenance == expected
    assert product_info().provenance == expected


def test_global_discovery_uses_reader_for_table_selection_and_validation(
    monkeypatch: pytest.MonkeyPatch,
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    _disable_default_provider_registration(monkeypatch)
    artifact = stub_packaged_catalogue_artifact("stub_provider")
    _registry.register("stub_provider", artifact)
    calls = {"stations": 0, "products": 0}

    def read_stations(self: CatalogueReader) -> CatalogResult[pl.DataFrame]:
        calls["stations"] += 1
        return CatalogResult(
            data=self.artifact.stations,
            provenance=CatalogProvenance(source="packaged", provider_id=self.provider_id),
            issues=(),
        )

    def read_products(self: CatalogueReader) -> CatalogResult[pl.DataFrame]:
        calls["products"] += 1
        return CatalogResult(
            data=self.artifact.products,
            provenance=CatalogProvenance(source="packaged", provider_id=self.provider_id),
            issues=(),
        )

    monkeypatch.setattr(CatalogueReader, "read_stations", read_stations)
    monkeypatch.setattr(CatalogueReader, "read_products", read_products)

    stations_result = stations()
    products_result = products()
    product_info_result = product_info()

    assert stations_result.data.height == 1
    assert products_result == ["level"]
    pl_testing.assert_frame_equal(product_info_result.data, artifact.products)
    assert calls == {"stations": 1, "products": 2}


def test_products_returns_exact_global_vocabulary_and_every_provider_subset() -> None:
    assert list(EXPECTED_PRODUCTS_BY_PROVIDER) == rr.providers()
    assert rr.products() == EXPECTED_PRODUCT_IDS
    for provider_id, expected in EXPECTED_PRODUCTS_BY_PROVIDER.items():
        actual = rr.products(provider=provider_id)
        assert actual == expected
        assert type(actual) is list
        assert actual == sorted(actual)
        assert set(actual) <= set(EXPECTED_PRODUCT_IDS)


def test_products_result_is_not_a_catalogue_or_dataframe() -> None:
    result = rr.products()
    assert type(result) is list
    assert not isinstance(result, CatalogResult)
    assert not isinstance(result, pl.DataFrame)


def test_products_unknown_provider_raises_loudly() -> None:
    with pytest.raises(UnknownProviderError) as exc_info:
        rr.products(provider="missing_provider")

    assert str(exc_info.value) == "Provider is not registered: missing_provider"
    assert exc_info.value.provider_id == "missing_provider"
    assert _issue_policy_error_chain(exc_info.value) == []
