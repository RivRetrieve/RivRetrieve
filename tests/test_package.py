from importlib.metadata import version

import rivretrieve
from rivretrieve import __version__


def test_version() -> None:
    assert __version__ == version("rivretrieve")


def test_init_public_surface_exports_m1_discovery_only() -> None:
    module_defined_names = {name for name in vars(rivretrieve) if not name.startswith("_")}

    assert "__version__" in vars(rivretrieve)
    assert module_defined_names == {"providers", "provider", "provider_info"}
    deferred_names = [
        "ProviderInfo",
        "ProviderModule",
        "ProviderHandle",
        "observations",
        "stations",
        "products",
        "product_info",
        "map_stations",
        "ObservationResult",
        "AnnotationSchema",
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
