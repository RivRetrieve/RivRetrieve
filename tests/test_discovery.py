from __future__ import annotations

from collections.abc import Callable

import polars as pl
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.catalogue_reader import CatalogueReader
from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.discovery import products
from rivretrieve._internal.issues import IssuePolicyError
from rivretrieve._internal.registry import UnknownProviderError, _registry
from rivretrieve._internal.results import CatalogProvenance, CatalogResult

EXPECTED_PRODUCT_IDS = [
    "discharge_daily",
    "discharge_daily_max",
    "discharge_daily_mean",
    "discharge_hourly",
    "discharge_hourly_mean",
    "discharge_instantaneous",
    "discharge_reported",
    "stage_daily",
    "stage_daily_max",
    "stage_daily_mean",
    "stage_daily_min",
    "stage_hourly",
    "stage_hourly_mean",
    "stage_instantaneous",
    "stage_reported",
    "water_temperature_daily_mean",
    "water_temperature_instantaneous",
    "water_temperature_reported",
]

EXPECTED_PRODUCTS_BY_PROVIDER = {
    "ba_fhmzbih": [
        "discharge_instantaneous",
        "stage_instantaneous",
        "water_temperature_instantaneous",
    ],
    "br_ana": [],
    "ca_eccc": [
        "discharge_daily_mean",
        "stage_daily_mean",
    ],
    "ch_foen": [
        "discharge_reported",
        "stage_reported",
        "water_temperature_reported",
    ],
    "cz_chmi": [
        "discharge_daily_mean",
        "discharge_hourly_mean",
        "stage_daily_mean",
        "stage_hourly_mean",
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
        "discharge_daily",
        "discharge_hourly",
        "stage_daily",
        "stage_hourly",
    ],
    "lt_lhmt": [
        "discharge_daily_mean",
        "stage_daily_mean",
    ],
    "no_nve": [],
    "pl_imgw": [
        "discharge_daily_mean",
        "stage_daily_mean",
        "water_temperature_daily_mean",
    ],
    "th_thaiwater": [
        "discharge_reported",
        "stage_reported",
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


def test_global_products_returns_sorted_deduplicated_vocabulary(
    monkeypatch: pytest.MonkeyPatch,
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    _disable_default_provider_registration(monkeypatch)
    _registry.register("z_provider", stub_packaged_catalogue_artifact("z_provider"))
    _registry.register("a_provider", stub_packaged_catalogue_artifact("a_provider"))

    assert products() == ["level"]


def test_global_discovery_disabled_defaults_empty_registry_distinguishes_result_kinds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_default_provider_registration(monkeypatch)
    product_result = products()

    assert product_result == []
    assert type(product_result) is list


def test_global_discovery_uses_reader_for_table_selection_and_validation(
    monkeypatch: pytest.MonkeyPatch,
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    _disable_default_provider_registration(monkeypatch)
    artifact = stub_packaged_catalogue_artifact("stub_provider")
    _registry.register("stub_provider", artifact)
    calls = {"products": 0}

    def read_products(self: CatalogueReader) -> CatalogResult[pl.DataFrame]:
        calls["products"] += 1
        return CatalogResult(
            data=self.artifact.products,
            provenance=CatalogProvenance(source="packaged", provider_id=self.provider_id),
            issues=(),
        )

    monkeypatch.setattr(CatalogueReader, "read_products", read_products)

    products_result = products()

    assert products_result == ["level"]
    assert calls == {"products": 1}


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
