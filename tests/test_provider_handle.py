from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, get_type_hints

import pytest

import rivretrieve as rr
from rivretrieve import ProviderHandle
from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.handle import ProviderHandle as InternalProviderHandle
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.registry import UnknownProviderError, _ProviderHandle, _registry
from tests._stubs import stub_provider


def _typed_provider_reference() -> rr.ProviderHandle:
    return rr.provider("stub_provider")


def test_provider_handle_imported_from_package_root() -> None:
    from rivretrieve import ProviderHandle as RootProviderHandle

    assert rr.ProviderHandle is RootProviderHandle
    assert RootProviderHandle is InternalProviderHandle


def test_provider_handle_is_runtime_checkable_protocol() -> None:
    protocol_type: Any = ProviderHandle

    assert protocol_type._is_protocol is True
    assert protocol_type._is_runtime_protocol is True


def test_private_provider_handle_structurally_conforms_to_public_protocol(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    artifact = stub_packaged_catalogue_artifact("stub_provider")
    handle = _ProviderHandle(provider_id=ProviderId("stub_provider"), _artifact=artifact)

    assert isinstance(handle, ProviderHandle)


def test_public_provider_returns_provider_handle_protocol_instance(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    _registry.register(
        "stub_provider",
        stub_packaged_catalogue_artifact("stub_provider"),
        provider_module=stub_provider,
    )

    handle = rr.provider("stub_provider")

    assert isinstance(handle, ProviderHandle)


def test_public_provider_return_annotation_is_provider_handle() -> None:
    type_hints = get_type_hints(rr.provider)

    handle = rr.provider

    assert type_hints["return"] is ProviderHandle
    assert handle is rr.provider


def test_public_provider_unknown_still_raises_unknown_provider_error() -> None:
    with pytest.raises(UnknownProviderError):
        rr.provider("missing")


def test_provider_handle_protocol_declares_exactly_five_public_methods() -> None:
    expected = {
        "info",
        "products",
        "stations",
        "station_products",
        "observations",
    }
    protocol_attrs = getattr(ProviderHandle, "__protocol_attrs__", None)
    if protocol_attrs is None:
        protocol_attrs = {
            name for name, value in vars(ProviderHandle).items() if not name.startswith("_") and callable(value)
        }

    assert set(protocol_attrs) == expected


def test_provider_handle_protocol_method_signatures_match_tracker() -> None:
    _assert_signature(
        "info",
        [],
        {},
        "ProviderInfo",
    )
    _assert_signature(
        "products",
        [
            ("source", inspect.Parameter.KEYWORD_ONLY, "packaged"),
            ("observed_property", inspect.Parameter.KEYWORD_ONLY, None),
            ("frequency", inspect.Parameter.KEYWORD_ONLY, None),
            ("statistic", inspect.Parameter.KEYWORD_ONLY, None),
            ("on_issue", inspect.Parameter.KEYWORD_ONLY, "warn"),
        ],
        {
            "source": "CatalogSource",
            "observed_property": "str | None",
            "frequency": "str | None",
            "statistic": "str | None",
            "on_issue": "OnIssue",
        },
        "CatalogResult[ProductCatalog]",
    )
    _assert_signature(
        "stations",
        [
            ("source", inspect.Parameter.KEYWORD_ONLY, "packaged"),
            ("on_issue", inspect.Parameter.KEYWORD_ONLY, "warn"),
        ],
        {"source": "CatalogSource", "on_issue": "OnIssue"},
        "CatalogResult[StationCatalog]",
    )
    _assert_signature(
        "station_products",
        [
            ("stations", inspect.Parameter.POSITIONAL_OR_KEYWORD, None),
            ("source", inspect.Parameter.KEYWORD_ONLY, "packaged"),
            ("on_issue", inspect.Parameter.KEYWORD_ONLY, "warn"),
        ],
        {"stations": "Sequence[str] | None", "source": "CatalogSource", "on_issue": "OnIssue"},
        "CatalogResult[StationProductCatalog]",
    )
    _assert_signature(
        "observations",
        [
            ("stations", inspect.Parameter.KEYWORD_ONLY, inspect.Parameter.empty),
            ("products", inspect.Parameter.KEYWORD_ONLY, inspect.Parameter.empty),
            ("start", inspect.Parameter.KEYWORD_ONLY, inspect.Parameter.empty),
            ("end", inspect.Parameter.KEYWORD_ONLY, inspect.Parameter.empty),
            ("on_issue", inspect.Parameter.KEYWORD_ONLY, "warn"),
        ],
        {
            "stations": "str | Sequence[str]",
            "products": "str | Sequence[str]",
            "start": "object",
            "end": "object",
            "on_issue": "OnIssue",
        },
        "ObservationResult",
    )


def test_private_provider_handle_has_no_removed_declaration_methods(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    handle = _ProviderHandle(
        provider_id=ProviderId("stub_provider"),
        _artifact=stub_packaged_catalogue_artifact("stub_provider"),
    )

    assert not hasattr(handle, "row_" + "annotation_schema")
    assert not hasattr(handle, "series_" + "annotation_schema")


def _assert_signature(
    method_name: str,
    expected_parameters: list[tuple[str, inspect._ParameterKind, Any]],
    expected_annotations: dict[str, str],
    expected_return: str,
) -> None:
    method = getattr(ProviderHandle, method_name)
    signature = inspect.signature(method)
    actual_parameters = list(signature.parameters.values())[1:]

    assert [
        (parameter.name, parameter.kind, parameter.default) for parameter in actual_parameters
    ] == expected_parameters
    annotations = inspect.get_annotations(method, eval_str=False)
    assert {name: annotations[name] for name in expected_annotations} == expected_annotations
    assert annotations["return"] == expected_return
