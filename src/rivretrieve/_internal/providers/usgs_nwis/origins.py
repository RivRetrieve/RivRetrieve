"""USGS provenance : ∅ → OriginDeclarations × AcquisitionProvenance (pure)."""

from collections.abc import Mapping
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
from rivretrieve._internal.catalogues.station_metadata import MetadataField

# Name mappings require genuine-input validation and owner disclosure approval
# before generated metadata can be packaged. Native presence is insufficient.
STATION_METADATA_NOTICE = (
    "Station metadata from the U.S. Geological Survey (USGS), National Water Information System. "
    "USGS-authored or produced data and information are in the U.S. public domain "
    "(https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits); this statement "
    "does not extend to third-party content. RivRetrieve selected the declared source fields and encoded "
    "their values and absence states; source names remain unchanged. Processing and publication of this "
    "projection: RivRetrieve."
)

STATION_METADATA_FIELDS: tuple[MetadataField, ...] = (
    MetadataField("drainage_area", "drain_area_va", "sq mi"),
    MetadataField(
        "drainage_area",
        "contrib_drain_area_va",
        "sq mi",
        support_facts=("source.usgs.sitefile_drainage_area_definitions",),
    ),
    MetadataField(
        "elevation",
        "alt_va",
        "feet",
        datum_field="alt_datum_cd",
        support_facts=("source.usgs.sitefile_altitude_definition",),
        datum_support=("source.usgs.sitefile_altitude_datum_definition",),
    ),
    MetadataField("station_name", "station_nm"),
)

_DATUM_TO_CRS = {
    "NAD27": "EPSG:4267",
    "NAD83": "EPSG:4269",
    "OLDHI": "EPSG:4135",
    "WGS72": "EPSG:4322",
    "WGS84": "EPSG:4326",
}


def crs_from_datum(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("invalid USGS coordinate datum")
    return _DATUM_TO_CRS.get(value, "unknown")


class DatumToCrsConversion(catalogue_origins.FieldConversion):
    """Map a USGS datum code to the canonical CRS vocabulary."""

    __slots__ = ()

    @property
    def name(self) -> catalogue_origins.ConversionName:
        return catalogue_origins.ConversionName("usgs_nwis.datum_to_crs")

    def apply(
        self,
        canonical_column: str,
        native_column: catalogue_origins.NativeColumn,
        native_row: Mapping[str, object],
    ) -> object:
        if canonical_column != "crs":
            raise ValueError("USGS datum conversion is only defined for CRS")
        if native_column != "dec_coord_datum_cd":
            raise ValueError("USGS datum conversion requires native field 'dec_coord_datum_cd'")
        return crs_from_datum(native_row[str(native_column)])


STATION_CATALOGUE_ORIGINS: dict[str, catalogue_origins.CatalogueOrigin] = {
    "provider_id": catalogue_origins.Authored(catalogue_origins.AuthoredValue("usgs_nwis")),
    "station_id": catalogue_origins.Field(catalogue_origins.NativeColumn("site_no")),
    "latitude": catalogue_origins.Field(
        catalogue_origins.NativeColumn("dec_lat_va"), catalogue_origins.FloatConversion()
    ),
    "longitude": catalogue_origins.Field(
        catalogue_origins.NativeColumn("dec_long_va"), catalogue_origins.FloatConversion()
    ),
    "crs": catalogue_origins.Field(catalogue_origins.NativeColumn("dec_coord_datum_cd"), DatumToCrsConversion()),
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
    instantaneous_definition = RecordingReference(
        recording_id="usgs_nwis_instantaneous_values_definition",
        repository_path="tests/test_data/usgs_nwis_instantaneous_values_definition.html",
        source_url="https://waterservices.usgs.gov/docs/instantaneous-values/instantaneous-values-details/",
        retrieved_at=datetime.fromisoformat("2026-09-19T20:58:46.743636Z"),
        media_type="text/html; charset=UTF-8",
        sha256="1cec37f8cec8173f635d4afaba2d08814347d9cff672b25c29d427b004d0b3a2",
    )
    sitefile_definition = RecordingReference(
        recording_id="usgs_nwis-nwis-sitefile-manual-body",
        repository_path="maintenance/catalogue/station_metadata/sources/usgs_nwis/nwis-sitefile-manual/body",
        source_url="https://pubs.usgs.gov/of/2005/1251/pdf/gwcoding_Sect2-1.pdf",
        retrieved_at=datetime.fromisoformat("2026-10-04T10:38:02.574170+00:00"),
        media_type="application/pdf",
        sha256="e711a90861425227879decb13605e5fe7408c81ddb4dd40065692f52e35f86bf",
    )
    sitefile_definition_capture = AcquisitionRecord(
        acquisition_id="usgs_nwis-nwis-sitefile-manual",
        method="http_request",
        instant_type="retrieval",
        description="USGS site-file definitions for altitude, altitude datum and drainage areas",
        requested_from=(sitefile_definition.source_url,),
        retrieved_at_start=sitefile_definition.retrieved_at,
        recording_ids=(sitefile_definition.recording_id,),
    )
    instantaneous_definition_capture = AcquisitionRecord(
        acquisition_id="instantaneous_values_definition_capture_2026_09_19",
        method="http_request",
        instant_type="retrieval",
        description="Publisher Instantaneous Values Service Details documentation calls the returned measurement an instantaneous value; it does not establish a concrete series sampling frequency.",
        requested_from=(instantaneous_definition.source_url,),
        retrieved_at_start=instantaneous_definition.retrieved_at,
        recording_ids=(instantaneous_definition.recording_id,),
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
        acquisitions=(
            catalogue,
            runtime,
            licence_terms,
            citation_terms,
            instantaneous_definition_capture,
            sitefile_definition_capture,
        ),
        evidence=(
            EvidenceReference(
                evidence_id=sitefile_definition.recording_id,
                description="USGS site-file metadata definitions",
                recording=sitefile_definition,
            ),
            EvidenceReference(
                evidence_id="usgs_instantaneous_value_definition",
                description='Publisher service documentation: "most recent instantaneous value"; the service request URL is /nwis/iv/.',
                recording=instantaneous_definition,
            ),
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
            fact_group="sitefile_metadata_definitions",
            facts=(
                "source.usgs.sitefile_altitude_definition",
                "source.usgs.sitefile_altitude_datum_definition",
                "source.usgs.sitefile_drainage_area_definitions",
            ),
            source_id="usgs_nwis",
            acquisition_id=sitefile_definition_capture.acquisition_id,
        ),
        FactBinding(
            fact_group="instantaneous_value_definition",
            facts=("source.usgs.instantaneous_value_definition",),
            source_id="usgs_nwis",
            acquisition_id=instantaneous_definition_capture.acquisition_id,
        ),
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


def build_modern_acquisition_provenance(receipts, metadata_directory):
    """Supplement retained station provenance with independently acquired modern facts."""
    import hashlib

    legacy = _build_provider_acquisition_provenance()
    recordings = tuple(
        RecordingReference(
            recording_id=f"modern_metadata_{index}",
            repository_path=f"research/usgs-modern-coverage/{receipt['file']}",
            source_url=receipt["url"],
            retrieved_at=datetime.fromisoformat(receipt["retrieved_at"]),
            media_type="application/gzip",
            sha256=hashlib.sha256((metadata_directory / receipt["file"]).read_bytes()).hexdigest(),
        )
        for index, receipt in enumerate(receipts)
    )
    acquisition = AcquisitionRecord(
        acquisition_id="modern_time_series_metadata_2026_09_22",
        method="http_campaign",
        instant_type="retrieval_interval",
        description="Complete unsorted v1 metadata pagination for parameters 00060 and 00065, including discontinued records; exact decompressed response hashes and request receipts retained alongside gzip recordings. Station scope remains the independently acquired native station table. UTC metadata ranges do not establish physical daily support.",
        requested_from=tuple(item.source_url for item in recordings),
        retrieved_at_start=min(item.retrieved_at for item in recordings),
        retrieved_at_end=max(item.retrieved_at for item in recordings),
        recording_ids=tuple(item.recording_id for item in recordings),
    )
    observation_request = AcquisitionRecord(
        acquisition_id="modern_observation_request",
        method="runtime_http_request",
        instant_type="runtime",
        description="Exact modern Water Data v1 daily or continuous request and response retained at runtime; independent of historical WaterServices calls",
        requested_from=(
            "https://api.waterdata.usgs.gov/ogcapi/v1/collections/daily/items",
            "https://api.waterdata.usgs.gov/ogcapi/v1/collections/continuous/items",
        ),
    )
    observation_binding = FactBinding(
        fact_group="modern_observation_values",
        facts=("source.observation.modern_values_qualifiers_and_timestamps",),
        source_id="usgs_nwis",
        acquisition_id=observation_request.acquisition_id,
    )
    source = legacy.source_records[0]
    source = source.model_copy(
        update={
            "acquisitions": source.acquisitions + (acquisition, observation_request),
            "evidence": source.evidence
            + tuple(
                EvidenceReference(
                    evidence_id=item.recording_id,
                    description="Exact modern metadata response compressed losslessly",
                    recording=item,
                )
                for item in recordings
            ),
        }
    )
    modern_facts = (
        "source.product.modern_parameter_statistic_computation_codes",
        "source.station_product.modern_series_availability",
        "source.series.modern_identity_description_and_utc_ranges",
    )
    binding = FactBinding(
        fact_group="modern_series_metadata",
        facts=modern_facts,
        source_id="usgs_nwis",
        acquisition_id=acquisition.acquisition_id,
    )
    provenance = legacy.model_copy(
        update={
            "source_records": (source,),
            "fact_universe": legacy.fact_universe + modern_facts + observation_binding.facts,
            "fact_bindings": legacy.fact_bindings + (binding, observation_binding),
        }
    )
    return complete_transformed_fact_universe(
        provenance,
        CATALOGUE_FACT_UNIVERSE,
        transformation=Transformation(
            name="USGS native station facts and modern series metadata to canonical catalogue carriers",
            external_inputs=tuple(
                ExternalFactReference(source_id="usgs_nwis", fact=fact)
                for fact in (
                    "source.provider.usgs_agency_identity",
                    "source.station.nwis_identity_location_datum",
                    *modern_facts,
                )
            ),
        ),
    )


# Existing acquisition facts materialised in the retained native table.
# This declares derived-input support, not preservation of original responses.
NATIVE_TABLE_ACQUISITION_IDS = ("national_site_campaign_2026_08_02",)


# Authored catalogue, physical-fact and support declarations selected at build time.
CATALOGUE_BUILD_DECLARATIONS = (
    ("src/rivretrieve/_internal/providers/usgs_nwis/origins.py", "build_modern_acquisition_provenance"),
    ("src/rivretrieve/_internal/providers/usgs_nwis/origins.py", "NATIVE_TABLE_ACQUISITION_IDS"),
    ("src/rivretrieve/_internal/providers/usgs_nwis/origins.py", "CATALOGUE_SUPPORTING_INPUTS"),
    ("src/rivretrieve/_internal/providers/usgs_nwis/origins.py", "STATION_METADATA_FIELDS"),
    ("src/rivretrieve/_internal/providers/usgs_nwis/origins.py", "STATION_METADATA_NOTICE"),
    ("src/rivretrieve/_internal/providers/usgs_nwis/generate_catalogue.py", "build_modern_catalogue"),
    ("src/rivretrieve/_internal/providers/usgs_nwis/station_metadata.py", "project_station_metadata"),
    ("src/rivretrieve/_internal/assembly.py", "assemble"),
    ("src/rivretrieve/_internal/providers/usgs_nwis/config.py", "config"),
    ("src/rivretrieve/_internal/providers/usgs_nwis/catalogue_series.py", "modern_source_descriptions"),
)


# Retained source documents and acquisition receipts used by these source facts.
CATALOGUE_SUPPORTING_INPUTS = {
    "source.usgs.sitefile_altitude_definition": (
        "maintenance/catalogue/station_metadata/sources/usgs_nwis/nwis-sitefile-manual/body",
        "maintenance/catalogue/station_metadata/sources/usgs_nwis/nwis-sitefile-manual/receipt.json",
    ),
    "source.usgs.sitefile_altitude_datum_definition": (
        "maintenance/catalogue/station_metadata/sources/usgs_nwis/nwis-sitefile-manual/body",
        "maintenance/catalogue/station_metadata/sources/usgs_nwis/nwis-sitefile-manual/receipt.json",
    ),
    "source.usgs.sitefile_drainage_area_definitions": (
        "maintenance/catalogue/station_metadata/sources/usgs_nwis/nwis-sitefile-manual/body",
        "maintenance/catalogue/station_metadata/sources/usgs_nwis/nwis-sitefile-manual/receipt.json",
    ),
}
