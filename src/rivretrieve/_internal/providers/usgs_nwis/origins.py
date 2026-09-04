"""USGS provenance : ∅ → OriginDeclarations × AcquisitionProvenance (pure)."""

from datetime import datetime

from rivretrieve._internal import catalogue_origins
from rivretrieve._internal.acquisition_provenance import (
    AcquisitionProvenance,
    AcquisitionRecord,
    EvidenceReference,
    ExternalFactReference,
    FactBinding,
    NativeTableIdentity,
    RecordingReference,
    SemanticDigest,
    SourceRecord,
    SourceStatement,
    Transformation,
    complete_transformed_fact_universe,
)
from rivretrieve._internal.catalogues.artifact import CATALOGUE_FACT_UNIVERSE

STATION_CATALOGUE_ORIGINS: dict[str, catalogue_origins.CatalogueOrigin] = {
    "provider_id": catalogue_origins.Authored(catalogue_origins.AuthoredValue("usgs_nwis")),
    "station_id": catalogue_origins.Field(catalogue_origins.NativeColumn("site_no")),
    "latitude": catalogue_origins.Field(
        catalogue_origins.NativeColumn("dec_lat_va"), catalogue_origins.FieldTransform.FLOAT
    ),
    "longitude": catalogue_origins.Field(
        catalogue_origins.NativeColumn("dec_long_va"), catalogue_origins.FieldTransform.FLOAT
    ),
    "crs": catalogue_origins.Field(
        catalogue_origins.NativeColumn("dec_coord_datum_cd"), catalogue_origins.FieldTransform.USGS_DATUM_TO_CRS
    ),
}
NATIVE_TABLE_REPOSITORY_PATH = "src/rivretrieve/_internal/providers/usgs_nwis/catalogue/native.parquet"
NATIVE_TABLE_REVISION = "bfeb825a6f3b3aad4982649625d570c070b4ee32"
NATIVE_TABLE_SHA256 = "90fede218826b640963e98515a6e3c4c106bf310a2e5bcf1606f805b55d5e701"
NATIVE_TABLE_BYTE_SIZE = 14_093_302
NATIVE_TABLE_SEMANTIC_SHA256 = "e4384cea2ff00e5a120d244977d2dd75bc00ec4c8ba941e3e83f06239cd5777f"
_LICENSE_TEXT = "USGS-authored or produced data and information are considered to be in the U.S. Public Domain."
_CITATION_TEXT = "Example of how to cite USGS Water Data for the Nation in general: U.S. Geological Survey, [2024], USGS Water Data for the Nation: U.S. Geological Survey National Water Information System database, accessed [April 8, 2024], at https://doi.org/10.5066/F7P55KJN."


def _build_provider_acquisition_provenance() -> AcquisitionProvenance:
    """Build USGS acquisition provenance after exact source-word verification."""
    licence = RecordingReference(
        recording_id="usgs_nwis_terms_licence",
        repository_path="tests/test_data/usgs_nwis_terms_licence-1.html",
        source_url="https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits",
        retrieved_at=datetime.fromisoformat("2026-08-20T08:46:24Z"),
        media_type="text/html; charset=UTF-8",
        sha256="a6f640805e5783765fb350d4d60d06a5dbef8ffa3b219fa7713885e5dff9580c",
    )
    citation = RecordingReference(
        recording_id="usgs_nwis_terms_citation",
        repository_path="tests/test_data/usgs_nwis_terms_citation-1.html",
        source_url="https://waterdata.usgs.gov/citation/",
        retrieved_at=datetime.fromisoformat("2026-08-20T15:56:47Z"),
        media_type="text/html; charset=utf-8",
        sha256="11be7513f1f383b3db9856d55afd91324920c954ba9f00eb5032294b2cf81ce3",
    )
    catalogue = AcquisitionRecord(
        acquisition_id="national_site_campaign_2026_08_02",
        method="http_campaign",
        instant_type="retrieval",
        description="102 NWIS site-service requests for the fixed 50-state-plus-DC scope; 26,258 sites and 2,036,546 series rows",
        requested_from=(
            "https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=<51-code>&seriesCatalogOutput=true",
            "https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=<51-code>&siteOutput=expanded",
        ),
        retrieved_at_start=datetime.fromisoformat("2026-08-02T01:14:11Z"),
    )
    licence_terms = AcquisitionRecord(
        acquisition_id="public_domain_capture_2026_08_20",
        method="http_request",
        instant_type="retrieval",
        description="Agency-wide USGS copyright and credits HTML recording",
        requested_from=(licence.source_url,),
        retrieved_at_start=licence.retrieved_at,
        recording_ids=(licence.recording_id,),
    )
    citation_terms = AcquisitionRecord(
        acquisition_id="citation_capture_2026_08_20",
        method="http_request",
        instant_type="retrieval",
        description="Water Data for the Nation citation HTML recording",
        requested_from=(citation.source_url,),
        retrieved_at_start=citation.retrieved_at,
        recording_ids=(citation.recording_id,),
    )
    runtime = AcquisitionRecord(
        acquisition_id="observation_request",
        method="runtime_http_request",
        instant_type="runtime",
        description="Exact NWIS daily-value or instantaneous-value request and response retained at runtime",
        requested_from=("https://waterservices.usgs.gov/nwis/dv/", "https://waterservices.usgs.gov/nwis/iv/"),
    )
    source = SourceRecord(
        source_id="usgs_nwis",
        issuer="U.S. Geological Survey",
        operator="National Water Information System",
        acquisitions=(catalogue, runtime, licence_terms, citation_terms),
        evidence=(
            EvidenceReference(
                evidence_id="usgs_public_domain_statement",
                description="Agency-wide USGS copyright and credits recording",
                recording=licence,
            ),
            EvidenceReference(
                evidence_id="usgs_water_data_citation",
                description="Water Data for the Nation citation recording",
                recording=citation,
            ),
        ),
        statements=(
            SourceStatement(
                kind="license",
                exact_text=_LICENSE_TEXT,
                recording_id=licence.recording_id,
                fact="source.usgs.license_statement",
            ),
            SourceStatement(
                kind="citation",
                exact_text=_CITATION_TEXT,
                recording_id=citation.recording_id,
                fact="source.usgs.citation_statement",
            ),
        ),
    )
    bindings = (
        FactBinding(
            fact_group="license_statement",
            facts=("source.usgs.license_statement",),
            source_id="usgs_nwis",
            acquisition_id=licence_terms.acquisition_id,
        ),
        FactBinding(
            fact_group="citation_statement",
            facts=("source.usgs.citation_statement",),
            source_id="usgs_nwis",
            acquisition_id=citation_terms.acquisition_id,
        ),
        FactBinding(
            fact_group="provider_identity",
            facts=("source.provider.usgs_agency_identity",),
            source_id="usgs_nwis",
            acquisition_id=catalogue.acquisition_id,
        ),
        FactBinding(
            fact_group="station_identity_location_crs",
            facts=("source.station.nwis_identity_location_datum",),
            source_id="usgs_nwis",
            acquisition_id=catalogue.acquisition_id,
        ),
        FactBinding(
            fact_group="product_identity",
            facts=("source.product.nwis_parameter_statistic_data_type_codes",),
            source_id="usgs_nwis",
            acquisition_id=catalogue.acquisition_id,
        ),
        FactBinding(
            fact_group="station_product_availability",
            facts=("source.station_product.nwis_series_availability_and_coverage",),
            source_id="usgs_nwis",
            acquisition_id=catalogue.acquisition_id,
        ),
        FactBinding(
            fact_group="observation_values",
            facts=("source.observation.nwis_values_qualifiers_and_timestamps",),
            source_id="usgs_nwis",
            acquisition_id=runtime.acquisition_id,
        ),
    )
    facts = tuple(f for b in bindings for f in b.facts)
    return AcquisitionProvenance(
        schema_version=2,
        provider_id="usgs_nwis",
        native_table=NativeTableIdentity(
            repository_path=NATIVE_TABLE_REPOSITORY_PATH,
            revision=NATIVE_TABLE_REVISION,
            sha256=NATIVE_TABLE_SHA256,
            byte_size=NATIVE_TABLE_BYTE_SIZE,
            semantic_digest=SemanticDigest(
                name="usgs_nwis.native_table_content_sha256", sha256=NATIVE_TABLE_SEMANTIC_SHA256
            ),
        ),
        source_records=(source,),
        fact_universe=facts,
        fact_bindings=bindings,
    )


def _complete_catalogue_carrier(provenance: AcquisitionProvenance) -> AcquisitionProvenance:
    return complete_transformed_fact_universe(
        provenance,
        CATALOGUE_FACT_UNIVERSE,
        transformation=Transformation(
            name="usgs_nwis external facts to RivRetrieve canonical catalogue carriers",
            external_inputs=tuple(
                ExternalFactReference(source_id="usgs_nwis", fact=fact)
                for fact in (
                    "source.provider.usgs_agency_identity",
                    "source.station.nwis_identity_location_datum",
                    "source.product.nwis_parameter_statistic_data_type_codes",
                    "source.station_product.nwis_series_availability_and_coverage",
                )
            ),
        ),
    )


def build_acquisition_provenance() -> AcquisitionProvenance:
    """Build closed usgs_nwis acquisition provenance."""
    return _complete_catalogue_carrier(_build_provider_acquisition_provenance())
