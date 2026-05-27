from importlib.metadata import version

import rivretrieve
from rivretrieve import __version__


def test_version() -> None:
    assert __version__ == version("rivretrieve")


def test_init_public_surface_still_only_version() -> None:
    module_defined_names = {name for name in vars(rivretrieve) if not name.startswith("_")}

    assert "__version__" in vars(rivretrieve)
    assert module_defined_names == set()
    for name in [
        "providers",
        "provider",
        "provider_info",
        "StationCatalog",
        "ProductCatalog",
        "StationProductCatalog",
        "ProviderInfoCatalog",
        "PackagedCatalogArtifact",
        "CorruptCatalogArtifactError",
        "CatalogResult",
        "Issue",
    ]:
        assert not hasattr(rivretrieve, name)
