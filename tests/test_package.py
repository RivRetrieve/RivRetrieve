from importlib.metadata import version
from pathlib import Path

import rivretrieve
from rivretrieve import RawMode, __version__
from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
from rivretrieve._internal.catalogues.schemas import (
    PRODUCT_CATALOG_SCHEMA,
    PROVIDER_INFO_CATALOG_SCHEMA,
    STATION_CATALOG_SCHEMA,
    STATION_PRODUCT_CATALOG_SCHEMA,
)


def test_version() -> None:
    assert __version__ == version("rivretrieve")


def test_init_public_surface_exports_m2_provider_handle_surface() -> None:
    module_defined_names = {name for name in vars(rivretrieve) if not name.startswith("_")}

    assert "__version__" in vars(rivretrieve)
    assert module_defined_names == {
        "ProviderHandle",
        "RawMode",
        "map_stations",
        "observations",
        "product_info",
        "products",
        "provider",
        "provider_info",
        "providers",
        "stations",
    }
    assert rivretrieve.RawMode is RawMode


def test_deferred_public_names_remain_absent_after_provider_handle_promotion() -> None:
    deferred_names = [
        "ProviderInfo",
        "ProviderModule",
        "_ProviderHandle",
        "ObservationResult",
        "ObservationRequest",
        "ObservationProvenance",
        "AnnotationSchema",
        "AnnotationTable",
        "RawPayload",
        "RawSourceCall",
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
        "MissingOptionalDependencyError",
        "StationMap",
    ]
    for name in deferred_names:
        assert not hasattr(rivretrieve, name)


def test_all_packaged_catalogues_expose_exact_reduced_carriers() -> None:
    providers_root = Path(__file__).parents[1] / "src/rivretrieve/_internal/providers"
    provider_ids = (
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
    )
    for provider_id in provider_ids:
        artifact = load_packaged_catalogue_artifact(providers_root / provider_id / "catalogue", on_issue="raise")
        assert artifact.products.schema == PRODUCT_CATALOG_SCHEMA.polars_schema
        assert artifact.stations.schema == STATION_CATALOG_SCHEMA.polars_schema
        assert artifact.station_products.schema == STATION_PRODUCT_CATALOG_SCHEMA.polars_schema
        assert tuple(artifact.provider_info) == tuple(PROVIDER_INFO_CATALOG_SCHEMA.polars_schema)
        assert "metadata" not in artifact.provider_info
