from importlib.metadata import version

import rivretrieve
from rivretrieve import __version__


def test_version() -> None:
    assert __version__ == version("rivretrieve")


def test_init_public_surface_exports_m2_provider_handle_surface() -> None:
    module_defined_names = {name for name in vars(rivretrieve) if not name.startswith("_")}

    assert "__version__" in vars(rivretrieve)
    assert module_defined_names == {
        "ProviderHandle",
        "product_info",
        "products",
        "provider",
        "provider_info",
        "providers",
        "stations",
    }


def test_deferred_public_names_remain_absent_after_provider_handle_promotion() -> None:
    deferred_names = [
        "ProviderInfo",
        "ProviderModule",
        "_ProviderHandle",
        "observations",
        "map_stations",
        "ObservationResult",
        "ObservationRequest",
        "ObservationProvenance",
        "AnnotationSchema",
        "AnnotationTable",
        "RawPayload",
        "Issue",
        "CatalogResult",
        "StationCatalog",
        "ProductCatalog",
        "StationProductCatalog",
        "ProviderInfoCatalog",
        "PackagedCatalogArtifact",
        "CorruptCatalogArtifactError",
        "LiveCatalogueUnsupportedIssue",
        "LiveCatalogueRoutingNotImplementedError",
        "ObservationDataSchema",
        "RowAnnotationTableSchema",
        "SeriesAnnotationTableSchema",
        "AnnotationSchemaDeclaration",
        "InvalidObservationRequestError",
        "ObservationsUnavailableError",
        "ObservationDataSchemaError",
        "AnnotationSchemaViolationError",
    ]
    for name in deferred_names:
        assert not hasattr(rivretrieve, name)
