"""South Africa provenance : ∅ → OriginDeclarations × AcquisitionProvenance (pure)."""

import re
from collections.abc import Mapping
from datetime import datetime

from rivretrieve._internal import catalogue_origins
from rivretrieve._internal.acquisition_provenance import (
    AcquisitionProvenance,
    AcquisitionRecord,
    EvidenceReference,
    ExternalFactReference,
    FactBinding,
    MaterialIdentity,
    NativeTableIdentity,
    RecordingReference,
    SemanticDigest,
    SourceRecord,
    Transformation,
    complete_transformed_fact_universe,
)
from rivretrieve._internal.catalogues.artifact import CATALOGUE_FACT_UNIVERSE
from rivretrieve._internal.catalogues.station_metadata import MetadataField

# Name mappings require genuine-input validation and owner disclosure approval
# before generated metadata can be packaged. Native presence is insufficient.
STATION_METADATA_FIELDS: tuple[MetadataField, ...] = (MetadataField("drainage_area", "Catchment Area km**2", "km**2"),)

_UNSIGNED_DMS = re.compile(r"\d{2}:\d{2}:\d{2}")


def unsigned_dms_coordinate(value: object, canonical_column: str) -> float:
    if not isinstance(value, str) or _UNSIGNED_DMS.fullmatch(value) is None:
        raise ValueError("invalid unsigned DMS coordinate")
    degrees, minutes, seconds = map(float, value.split(":"))
    magnitude = degrees + minutes / 60.0 + seconds / 3600.0
    if canonical_column == "latitude":
        return -magnitude
    if canonical_column == "longitude":
        return magnitude
    raise ValueError("DWS DMS conversion is only defined for coordinates")


def unsigned_dms_coordinates(latitude_dms: object, longitude_dms: object) -> tuple[float, float]:
    return (
        unsigned_dms_coordinate(latitude_dms, "latitude"),
        unsigned_dms_coordinate(longitude_dms, "longitude"),
    )


class UnsignedDmsConversion(catalogue_origins.FieldConversion):
    """Apply DWS's provider-owned southern/eastern sign policy to unsigned DMS."""

    __slots__ = ()

    @property
    def name(self) -> catalogue_origins.ConversionName:
        return catalogue_origins.ConversionName("za_dws.unsigned_dms")

    def apply(
        self,
        canonical_column: str,
        native_column: catalogue_origins.NativeColumn,
        native_row: Mapping[str, object],
    ) -> object:
        expected_native_column = {
            "latitude": "Latitude (dd:mm:ss)",
            "longitude": "Longitude (dd:mm:ss)",
        }.get(canonical_column)
        if expected_native_column is None:
            raise ValueError("DWS DMS conversion is only defined for coordinates")
        if native_column != expected_native_column:
            raise ValueError(f"DWS {canonical_column} conversion requires native field {expected_native_column!r}")
        return unsigned_dms_coordinate(native_row[str(native_column)], canonical_column)


CRS_EVIDENCE_URL = "https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA1_Limpopo-Olifants_River.pdf"
CRS_EVIDENCE_EXPLANATION = "The cited River PDF's own two-line coordinate header reads Latitude / dd:mm:ss and Longitude / dd:mm:ss; this names a representation format but never a datum. A case-insensitive review of all eight River PDFs found zero datum, WGS, ellipsoid, geodetic, projection, or EPSG occurrences. HyCatalogue.aspx is only a link index with no prose or coordinate header and is not CRS evidence."
DMS_SIGN_CONVENTION = "DWS publishes unsigned DMS magnitudes with no leading sign, hemisphere marker, or hemisphere note; the build applies a southern negative latitude sign and an eastern positive longitude sign that the source does not carry."
STATION_CATALOGUE_ORIGINS: dict[str, catalogue_origins.CatalogueOrigin] = {
    "provider_id": catalogue_origins.Authored(catalogue_origins.AuthoredValue("za_dws")),
    "station_id": catalogue_origins.Field(catalogue_origins.NativeColumn("Station")),
    "latitude": catalogue_origins.Field(catalogue_origins.NativeColumn("Latitude (dd:mm:ss)"), UnsignedDmsConversion()),
    "longitude": catalogue_origins.Field(
        catalogue_origins.NativeColumn("Longitude (dd:mm:ss)"), UnsignedDmsConversion()
    ),
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
    definitions = tuple(
        AcquisitionRecord(
            acquisition_id=f"{kind}_field_definitions_repository_recovery",
            method="repository_recovery",
            instant_type="provenance_lower_bound",
            description=(
                f"Historical {kind} response fixture recovered unchanged from commit df1b17778fb1f5d8db8eb3a803822571dc1dde85; "
                "commit attests live capture; instant is repository provenance lower bound, not HTTP capture. "
                "Point response completeness is unestablished. Used for field definitions only."
            ),
            requested_from=(
                f"https://github.com/RivRetrieve/RivRetrieve/blob/df1b17778fb1f5d8db8eb3a803822571dc1dde85/tests/test_data/za_dws_X3H001_{kind}_2020-01.txt",
            ),
            retrieved_at_start=datetime.fromisoformat("2026-06-11T09:28:43Z"),
            material=MaterialIdentity(filename=filename, byte_count=size, sha256=digest),
        )
        for kind, filename, size, digest in (
            (
                "daily",
                "X3H001_daily_2020-01.html",
                2188,
                "d7edcd596883840c36800535c9ad7eaa52fc3d920c837ad134b902c96fa31d20",
            ),
            (
                "point",
                "X3H001_point_2020-01.html",
                5134,
                "7b266fa724354709d1c3cb5602e0bf1b5bfa80e09bc5b272d4145d6153d88ae4",
            ),
        )
    )
    source = SourceRecord(
        source_id="za_dws",
        issuer="South African Department of Water and Sanitation",
        operator="DWS Verified Hydrology",
        acquisitions=(catalogue, *definitions),
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
                description=(
                    "Archived A2H023 Monthly response publishes Variable 100.00 Surface Water Level "
                    "and monthly volumes in million cubic metres; no equivalence with D_AVG_FR, "
                    "COR_FLOW or COR_LEVEL is established. No applicable terms or citation statement."
                ),
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
            fact_group="daily_product_identity",
            facts=("source.product.daily_field_definition",),
            source_id="za_dws",
            acquisition_id=definitions[0].acquisition_id,
        ),
        FactBinding(
            fact_group="point_product_identity",
            facts=("source.product.point_field_definitions",),
            source_id="za_dws",
            acquisition_id=definitions[1].acquisition_id,
        ),
        FactBinding(
            fact_group="station_product_availability",
            facts=("source.station_product.availability_not_published",),
            source_id="za_dws",
            acquisition_id=catalogue.acquisition_id,
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
                    "source.product.daily_field_definition",
                    "source.product.point_field_definitions",
                    "source.station_product.availability_not_published",
                )
            ),
        ),
    )


def build_acquisition_provenance() -> AcquisitionProvenance:
    """Build closed za_dws acquisition provenance."""
    return _complete_catalogue_carrier(_build_provider_acquisition_provenance())


# Existing acquisition facts materialised in the retained native table.
# This declares derived-input support, not preservation of original responses.
NATIVE_TABLE_ACQUISITION_IDS = ("verified_hydrology_archive_campaign_2026_08_02",)


# Authored catalogue, physical-fact and support declarations selected at build time.
CATALOGUE_BUILD_DECLARATIONS = (
    ("maintenance/catalogue/station_metadata/review.json", None),
    ("src/rivretrieve/_internal/providers/za_dws/origins.py", "build_acquisition_provenance"),
    ("src/rivretrieve/_internal/providers/za_dws/origins.py", "NATIVE_TABLE_ACQUISITION_IDS"),
    ("src/rivretrieve/_internal/providers/za_dws/origins.py", "CATALOGUE_SUPPORTING_INPUTS"),
    ("src/rivretrieve/_internal/providers/za_dws/origins.py", "STATION_METADATA_FIELDS"),
    ("src/rivretrieve/_internal/providers/za_dws/generate_catalogue.py", "build_catalogue"),
    ("src/rivretrieve/_internal/assembly.py", "assemble"),
    ("src/rivretrieve/_internal/providers/za_dws/catalogue_series.py", "describe_catalogue"),
)


# Additional retained declarations used by these source facts; not original-body claims.
CATALOGUE_SUPPORTING_INPUTS = {}
