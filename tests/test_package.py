import json
from importlib import import_module
from importlib.metadata import version
from pathlib import Path

import polars as pl

import rivretrieve
from rivretrieve import __version__, to_utc
from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
from rivretrieve._internal.catalogues.schemas import (
    PRODUCT_CATALOG_SCHEMA,
    PROVIDER_INFO_CATALOG_SCHEMA,
    STATION_CATALOG_SCHEMA,
    STATION_PRODUCT_CATALOG_SCHEMA,
)
from rivretrieve._internal.observations import ReceiptMode


def test_version() -> None:
    assert __version__ == version("rivretrieve")


def test_init_public_surface_exports_catalogue_and_retrieval_functions() -> None:
    module_defined_names = [name for name in dir(rivretrieve) if not name.startswith("_")]

    assert "__version__" in vars(rivretrieve)
    assert module_defined_names == [
        "as_frame",
        "cache_status",
        "clear_cache",
        "describe",
        "download",
        "fetch",
        "fetch_by_provider",
        "find",
        "from_frame",
        "map",
        "pick",
        "products",
        "providers",
        "to_utc",
    ]
    removed = (
        "ProviderHandle",
        "CatalogSource",
        "map_stations",
        "observations",
        "product_info",
        "provider",
        "provider_info",
        "stations",
    )
    assert all(not hasattr(rivretrieve, name) for name in removed)
    assert not hasattr(rivretrieve, "source_metadata")
    assert not hasattr(rivretrieve, "ReceiptMode")
    assert ReceiptMode.OMIT.value == "omit"
    assert ReceiptMode.INCLUDE.value == "include"
    assert rivretrieve.to_utc is to_utc


def test_clear_cache_public_help_describes_all_destructive_recovery_effects() -> None:
    documentation = rivretrieve.clear_cache.__doc__

    assert documentation is not None
    assert "compiled observation store" in documentation
    assert "preserved pending publisher downloads" in documentation
    assert "destructive" in documentation
    assert "retry" in documentation


def test_deferred_public_names_remain_absent_after_provider_handle_promotion() -> None:
    deferred_names = [
        "ProviderInfo",
        "ProviderModule",
        "_ProviderHandle",
        "ObservationResult",
        "ObservationRequest",
        "ObservationProvenance",
        "Receipts",
        "ReceiptEntry",
        "ReceiptAuthorship",
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
        import_module("rivretrieve._internal.provider_module"),
        import_module("rivretrieve._internal.registry"),
        import_module("rivretrieve._internal.providers.ca_eccc.declaration"),
        import_module("rivretrieve._internal.providers.usgs_nwis.declaration"),
    )
    for module in affected_modules:
        for name in removed_contract_names:
            assert name not in vars(module)


def test_all_packaged_catalogues_expose_exact_reduced_carriers() -> None:
    providers_root = Path(__file__).parents[1] / "src/rivretrieve/_internal/providers"
    expected_station_products = {
        "ba_fhmzbih": (180, 0, 0),
        "br_ana": (35_828, 0, 0),
        "ca_eccc": (16_114, 0, 0),
        "ch_foen": (738, 0, 0),
        "cz_chmi": (4_155, 0, 0),
        "fr_hubeau": (33_139, 0, 0),
        "jp_mlit": (4_092, 0, 0),
        "lt_lhmt": (194, 0, 0),
        "no_nve": (44_118, 0, 0),
        "pl_imgw": (3_903, 0, 0),
        "th_thaiwater": (1_650, 0, 0),
        "usgs_nwis": (157_548, 57_450, 57_450),
        "za_dws": (8_715, 0, 0),
    }
    expected_station_product_columns = (
        "provider_id",
        "station_id",
        "product_id",
        "availability",
        "availability_reason",
        "published_record_start_date",
        "published_record_end_date",
        "last_catalogue_check",
    )
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
    expected_provider_terms: dict[str, tuple[str | None, str | None]] = dict.fromkeys(provider_ids, (None, None))
    expected_provider_terms["no_nve"] = (
        "The data provided by the API is licensed under the Norwegian License for Open Government Data (NLOD) "
        "which is compatible with CC Navngivelse 3.0 Norge (CC BY 3.0).",
        "When using data from this service, if possible, please refer to this service as origin of data.",
    )
    expected_provider_terms["br_ana"] = (
        "Os dados abertos são disponibilizados livremente para a utilização de toda a sociedade, sem restrição de licenças, patentes ou mecanismos de controle.",
        None,
    )
    for provider_id in provider_ids:
        catalogue_path = providers_root / provider_id / "catalogue"
        raw_provider_info = json.loads((catalogue_path / "provider.json").read_text())
        assert set(raw_provider_info) == set(PROVIDER_INFO_CATALOG_SCHEMA.polars_schema)
        assert (raw_provider_info["license"], raw_provider_info["citation"]) == expected_provider_terms[provider_id]

        artifact = load_packaged_catalogue_artifact(catalogue_path, on_issue="raise")
        assert artifact.products.schema == PRODUCT_CATALOG_SCHEMA.polars_schema
        assert artifact.stations.schema == STATION_CATALOG_SCHEMA.polars_schema
        assert artifact.station_products.schema == STATION_PRODUCT_CATALOG_SCHEMA.polars_schema
        row_count, start_count, end_count = expected_station_products[provider_id]
        assert artifact.station_products.height == row_count
        assert tuple(artifact.station_products.columns) == expected_station_product_columns
        assert artifact.station_products.schema["published_record_start_date"] == pl.Date
        assert artifact.station_products.schema["published_record_end_date"] == pl.Date
        assert "start_date" not in artifact.station_products.columns
        assert "end_date" not in artifact.station_products.columns
        assert artifact.station_products["published_record_start_date"].count() == start_count
        assert artifact.station_products["published_record_end_date"].count() == end_count
        assert tuple(artifact.provider_info) == tuple(PROVIDER_INFO_CATALOG_SCHEMA.polars_schema)
        assert (artifact.provider_info["license"], artifact.provider_info["citation"]) == expected_provider_terms[
            provider_id
        ]
        assert "metadata" not in artifact.provider_info
