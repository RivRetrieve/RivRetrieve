from importlib.metadata import version

import rivretrieve
from rivretrieve import __version__


def test_version() -> None:
    assert __version__ == version("rivretrieve")


def test_init_public_surface_exports_m2_step_02_packaged_catalogue_surface() -> None:
    module_defined_names = {name for name in vars(rivretrieve) if not name.startswith("_")}

    assert "__version__" in vars(rivretrieve)
    assert module_defined_names == {"providers", "provider", "provider_info", "stations", "products", "product_info"}


def test_deferred_public_names_remain_absent_after_catalogue_surface() -> None:
    deferred_names = [
        "ProviderInfo",
        "ProviderModule",
        "ProviderHandle",
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
    ]
    for name in deferred_names:
        assert not hasattr(rivretrieve, name)
