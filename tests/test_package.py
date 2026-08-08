import json
from importlib import import_module
from importlib.metadata import version
from pathlib import Path

import rivretrieve
from rivretrieve import RawMode, __version__, to_utc
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
        "to_utc",
    }
    assert rivretrieve.RawMode is RawMode
    assert rivretrieve.to_utc is to_utc


def test_deferred_public_names_remain_absent_after_provider_handle_promotion() -> None:
    deferred_names = [
        "ProviderInfo",
        "ProviderModule",
        "_ProviderHandle",
        "ObservationResult",
        "ObservationRequest",
        "ObservationProvenance",
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
        "InvalidObservationRequestError",
        "ObservationsUnavailableError",
        "ObservationDataSchemaError",
        "MissingOptionalDependencyError",
        "StationMap",
    ]
    for name in deferred_names:
        assert not hasattr(rivretrieve, name)

    removed_contract_names = (
        "Row" + "Annotation" + "TableSchema",
        "Series" + "Annotation" + "TableSchema",
        "Annotation" + "Table",
        "Annotation" + "Schema",
        "Annotation" + "SchemaDeclaration",
        "validate_" + "annotation_names",
        "Annotation" + "SchemaViolationError",
        "row_" + "annotation_schema",
        "series_" + "annotation_schema",
        "row_" + "annotations",
        "series_" + "annotations",
    )
    affected_modules = (
        rivretrieve,
        import_module("rivretrieve._internal"),
        import_module("rivretrieve._internal.observations"),
        import_module("rivretrieve._internal.issues"),
        import_module("rivretrieve._internal.handle"),
        import_module("rivretrieve._internal.provider_module"),
        import_module("rivretrieve._internal.registry"),
        import_module("rivretrieve._internal.providers.ca_eccc.module"),
        import_module("rivretrieve._internal.providers.usgs_nwis.module"),
    )
    for module in affected_modules:
        for name in removed_contract_names:
            assert name not in vars(module)


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
        catalogue_path = providers_root / provider_id / "catalogue"
        raw_provider_info = json.loads((catalogue_path / "provider.json").read_text())
        assert set(raw_provider_info) == set(PROVIDER_INFO_CATALOG_SCHEMA.polars_schema)
        assert raw_provider_info["license"] is None
        assert raw_provider_info["citation"] is None

        artifact = load_packaged_catalogue_artifact(catalogue_path, on_issue="raise")
        assert artifact.products.schema == PRODUCT_CATALOG_SCHEMA.polars_schema
        assert artifact.stations.schema == STATION_CATALOG_SCHEMA.polars_schema
        assert artifact.station_products.schema == STATION_PRODUCT_CATALOG_SCHEMA.polars_schema
        assert tuple(artifact.provider_info) == tuple(PROVIDER_INFO_CATALOG_SCHEMA.polars_schema)
        assert artifact.provider_info["license"] is None
        assert artifact.provider_info["citation"] is None
        assert "metadata" not in artifact.provider_info
