"""South Africa provenance : ∅ → OriginDeclarations × AcquisitionProvenance (pure)."""

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
    Transformation,
    complete_transformed_fact_universe,
)
from rivretrieve._internal.catalogues.artifact import CATALOGUE_FACT_UNIVERSE

CRS_EVIDENCE_URL = "https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA1_Limpopo-Olifants_River.pdf"
CRS_EVIDENCE_EXPLANATION = "The cited River PDF's own two-line coordinate header reads Latitude / dd:mm:ss and Longitude / dd:mm:ss; this names a representation format but never a datum. A case-insensitive review of all eight River PDFs found zero datum, WGS, ellipsoid, geodetic, projection, or EPSG occurrences. HyCatalogue.aspx is only a link index with no prose or coordinate header and is not CRS evidence."
DMS_SIGN_CONVENTION = "DWS publishes unsigned DMS magnitudes with no leading sign, hemisphere marker, or hemisphere note; the build applies a southern negative latitude sign and an eastern positive longitude sign that the source does not carry."
STATION_CATALOGUE_ORIGINS: dict[str, catalogue_origins.CatalogueOrigin] = {
    "provider_id": catalogue_origins.Field(catalogue_origins.NativeColumn("Station")),
    "station_id": catalogue_origins.Field(catalogue_origins.NativeColumn("Station")),
    "latitude": catalogue_origins.Field(catalogue_origins.NativeColumn("Latitude (dd:mm:ss)")),
    "longitude": catalogue_origins.Field(catalogue_origins.NativeColumn("Longitude (dd:mm:ss)")),
    "crs": catalogue_origins.NotPublished(catalogue_origins.Evidence(CRS_EVIDENCE_URL)),
}
NATIVE_TABLE_REPOSITORY_PATH = "src/rivretrieve/_internal/providers/za_dws/catalogue/native.parquet"
NATIVE_TABLE_REVISION = "bfeb825a6f3b3aad4982649625d570c070b4ee32"
NATIVE_TABLE_SHA256 = "6d122a3ae50e9bdb61599bce488bcf1045649cec2ec4b848177eccc328f56efd"
NATIVE_TABLE_BYTE_SIZE = 67_655
NATIVE_TABLE_SEMANTIC_SHA256 = "7949369cf573d675cf8cb2374fa172038e10e492299572df442834d6a08e40fc"


def _build_provider_acquisition_provenance() -> AcquisitionProvenance:
    """Build DWS provenance with the archive represented only as intermediary."""
    landing = RecordingReference(
        recording_id="za_dws_terms_landing_absence",
        repository_path="tests/test_data/za_dws_terms_licence-1.html",
        source_url="http://web.archive.org/web/20241129011721id_/https://www.dws.gov.za/hydrology/Verified/",
        retrieved_at=datetime.fromisoformat("2026-08-21T08:01:44Z"),
        media_type="text/html; charset=utf-8",
        sha256="6a6e2dcae1effa27bd4122c48403d6eefd3bbe8080c06e547f8863ec2e785d86",
    )
    catalogue_terms = RecordingReference(
        recording_id="za_dws_terms_catalogue_absence",
        repository_path="tests/test_data/za_dws_terms_licence-4.html",
        source_url="http://web.archive.org/web/20260311133455id_/https://www.dws.gov.za/hydrology/Verified/HyCatalogue.aspx",
        retrieved_at=datetime.fromisoformat("2026-08-21T11:33:32Z"),
        media_type="text/html; charset=utf-8",
        sha256="673c679ca5005e6831aa94f1c9cd9f72467982646c375c6b7d2ca3d25de801d8",
    )
    observation_terms = RecordingReference(
        recording_id="za_dws_terms_observation_absence",
        repository_path="tests/test_data/za_dws_terms_licence-5.html",
        source_url="http://web.archive.org/web/20230525074558id_/https://www.dws.gov.za/hydrology/Verified/HyData.aspx?Station=A2H023100.00&DataType=Monthly&StartDT=1965-10-23&EndDT=2022-02-09&SiteType=RIV&Format=Old",
        retrieved_at=datetime.fromisoformat("2026-08-21T11:33:37Z"),
        media_type="text/html; charset=utf-8",
        sha256="5d10dfdb5c487c4884983cf71149a0533f35b9af0f7ad45f81a8f2e9540baf36",
    )
    catalogue = AcquisitionRecord(
        acquisition_id="verified_hydrology_archive_campaign_2026_08_02",
        method="http_campaign",
        instant_type="retrieval_interval",
        description="Internet Archive intermediary capture of DWS Verified Hydrology HyCatalogue.aspx and all eight linked WMA River PDFs; 2,905 stations",
        requested_from=(
            "http://web.archive.org/web/20260311133455id_/https://www.dws.gov.za/hydrology/Verified/HyCatalogue.aspx",
            "http://web.archive.org/web/20251122081546id_/https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA1_Limpopo-Olifants_River.pdf",
            "http://web.archive.org/web/20251127140120id_/https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA2_Inkomati-Usuthu_River.pdf",
            "http://web.archive.org/web/20251127181748id_/https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA3_Pongola-Mtamvuna_River.pdf",
            "http://web.archive.org/web/20251126040946id_/https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA4_Vaal-Orange_River.pdf",
            "http://web.archive.org/web/20251127142153id_/https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA5_Mzimvubu-Tsitsikamma_River.pdf",
            "http://web.archive.org/web/20251121090856id_/https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA6_Breede-Olifants_River.pdf",
            "http://web.archive.org/web/20251121161554id_/https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA7_Eswatini_River.pdf",
            "http://web.archive.org/web/20251121113702id_/https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA8_Lesotho_River.pdf",
        ),
        retrieved_at_start=datetime.fromisoformat("2026-08-02T18:47:00Z"),
        retrieved_at_end=datetime.fromisoformat("2026-08-02T18:47:09Z"),
    )
    runtime = AcquisitionRecord(
        acquisition_id="observation_request",
        method="runtime_http_request",
        instant_type="runtime",
        description="Exact DWS Verified Hydrology HyData.aspx request and response retained at runtime",
        requested_from=("https://www.dws.gov.za/hydrology/Verified/HyData.aspx",),
    )
    source = SourceRecord(
        source_id="za_dws",
        issuer="South African Department of Water and Sanitation",
        operator="DWS Verified Hydrology",
        acquisitions=(catalogue, runtime),
        evidence=(
            EvidenceReference(
                evidence_id="za_dws_verified_landing_terms_absence",
                description="Archived Verified Hydrology landing page examined without an applicable terms or citation statement",
                recording=landing,
            ),
            EvidenceReference(
                evidence_id="za_dws_catalogue_terms_absence",
                description="Archived exact catalogue surface examined without an applicable terms or citation statement",
                recording=catalogue_terms,
            ),
            EvidenceReference(
                evidence_id="za_dws_observation_terms_absence",
                description="Archived observation-shaped response examined without an applicable terms or citation statement",
                recording=observation_terms,
            ),
        ),
    )
    bindings = (
        FactBinding(
            fact_group="provider_identity",
            facts=("source.provider.dws_service_identity",),
            source_id="za_dws",
            acquisition_id=catalogue.acquisition_id,
        ),
        FactBinding(
            fact_group="station_identity",
            facts=("source.station.dws_station_code",),
            source_id="za_dws",
            acquisition_id=catalogue.acquisition_id,
        ),
        FactBinding(
            fact_group="station_location",
            facts=(
                "source.station.dws_unsigned_dms",
                "source.station.horizontal_crs_not_published",
            ),
            source_id="za_dws",
            acquisition_id=catalogue.acquisition_id,
        ),
        FactBinding(
            fact_group="product_identity",
            facts=("source.product.dws_datatype_and_file_semantics",),
            source_id="za_dws",
            acquisition_id=catalogue.acquisition_id,
        ),
        FactBinding(
            fact_group="station_product_availability",
            facts=("source.station_product.availability_not_published",),
            source_id="za_dws",
            acquisition_id=catalogue.acquisition_id,
        ),
        FactBinding(
            fact_group="observation_values",
            facts=("source.observation.dws_fixed_format_values_quality_and_time",),
            source_id="za_dws",
            acquisition_id=runtime.acquisition_id,
        ),
    )
    facts = tuple(f for b in bindings for f in b.facts)
    return AcquisitionProvenance(
        schema_version=2,
        provider_id="za_dws",
        native_table=NativeTableIdentity(
            repository_path=NATIVE_TABLE_REPOSITORY_PATH,
            revision=NATIVE_TABLE_REVISION,
            sha256=NATIVE_TABLE_SHA256,
            byte_size=NATIVE_TABLE_BYTE_SIZE,
            semantic_digest=SemanticDigest(
                name="za_dws.native_table_content_sha256", sha256=NATIVE_TABLE_SEMANTIC_SHA256
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
            name="za_dws external facts to RivRetrieve canonical catalogue carriers",
            external_inputs=tuple(
                ExternalFactReference(source_id="za_dws", fact=fact)
                for fact in (
                    "source.provider.dws_service_identity",
                    "source.station.dws_station_code",
                    "source.station.dws_unsigned_dms",
                    "source.station.horizontal_crs_not_published",
                    "source.product.dws_datatype_and_file_semantics",
                    "source.station_product.availability_not_published",
                )
            ),
        ),
    )


def build_acquisition_provenance() -> AcquisitionProvenance:
    """Build closed za_dws acquisition provenance."""
    return _complete_catalogue_carrier(_build_provider_acquisition_provenance())
