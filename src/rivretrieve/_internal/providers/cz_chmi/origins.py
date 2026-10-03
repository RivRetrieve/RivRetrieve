"""Czech authority : ∅ → OriginDeclarations × AcquisitionProvenance (pure)."""

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
    "Station metadata from Český hydrometeorologický ústav (ČHMÚ), used under Creative Commons "
    "Attribution 4.0 (https://creativecommons.org/licenses/by/4.0/). RivRetrieve selected the declared "
    "source fields and encoded their values and absence states; source names remain unchanged. Processing "
    "and publication of this projection: RivRetrieve."
)

STATION_METADATA_FIELDS: tuple[MetadataField, ...] = (
    MetadataField("drainage_area", "PLO_STA", "km²"),
    MetadataField("station_name", "STATION_NAME"),
    MetadataField("river_name", "STREAM_NAME"),
)

STATION_CATALOGUE_ORIGINS: dict[str, catalogue_origins.CatalogueOrigin] = {
    "provider_id": catalogue_origins.Authored(catalogue_origins.AuthoredValue("cz_chmi")),
    "station_id": catalogue_origins.Field(catalogue_origins.NativeColumn("objID")),
    "latitude": catalogue_origins.Field(catalogue_origins.NativeColumn("GEOGR1"), catalogue_origins.FloatConversion()),
    "longitude": catalogue_origins.Field(catalogue_origins.NativeColumn("GEOGR2"), catalogue_origins.FloatConversion()),
    "crs": catalogue_origins.NotPublished(
        catalogue_origins.Evidence("https://opendata.chmi.cz/hydrology/read_me/Popis_kodu_historical.pdf")
    ),
}


NATIVE_TABLE_SHA256 = "03c2ce0b1bc686e696fd57a4ff82dfb3bb60c176edeafe2c24b62168d4e60408"
NATIVE_TABLE_BYTE_SIZE = 51445
NATIVE_TABLE_REVISION = "2f97c3a841b3403618126ea7587bffe1908ec6c0"
NATIVE_TABLE_REPOSITORY_PATH = "src/rivretrieve/_internal/providers/cz_chmi/catalogue/native.parquet"
NATIVE_TABLE_SEMANTIC_SHA256 = "b13d49902967e6f2fe182348999d24af711868f0c38032c425485aa41a66dd2b"
_TERMS_FILE = "cz_chmi_terms_licence.html"
_TERMS_SHA256 = "cec8e0a56984c0a59c439077ac5e58956f6199cbe82c39657ce86d262f6ae291"
_LICENSE = "Produkty Českého hydrometeorologického ústavu dostupné na těchto webových stránkách podléhají licenci Creative Commons 4.0 CC-BY."
_CITATION = "Dílo smíte sdílet a upravovat za podmínky uvedení původu (zdroje ČHMÚ)."
_META2_FILE = "cz_meta2.json"
_META2_SHA256 = "b72883dbaa8407b4a514ae4aeec807350222b67298da16a089ed6299d553fafc"


def _build_provider_acquisition_provenance() -> AcquisitionProvenance:
    """Build Czechia's acquisition provenance without performing IO."""
    recording = RecordingReference(
        recording_id="cz_chmi_terms",
        repository_path=f"tests/test_data/{_TERMS_FILE}",
        source_url="https://www.chmi.cz/vylou%C4%8Den%C3%AD-odpov%C4%9Bdnosti",
        retrieved_at=datetime.fromisoformat("2026-08-20T15:24:48Z"),
        media_type="text/html; charset=UTF-8",
        sha256=_TERMS_SHA256,
    )
    semantics_recording = RecordingReference(
        recording_id="cz_chmi_product_semantics",
        repository_path=f"tests/test_data/{_META2_FILE}",
        source_url="https://opendata.chmi.cz/hydrology/historical/metadata/meta2.json",
        retrieved_at=datetime.fromisoformat("2026-09-02T14:47:26.717737Z"),
        media_type="application/json",
        sha256=_META2_SHA256,
    )
    external = (
        "source.provider.service",
        "source.product.native_identity",
        "source.station.native_identity",
        "source.station.native_location",
        "source.station.crs_not_published",
        "source.station_product.availability_not_published",
        "source.observation.native_value",
        "source.product.hourly_mean_semantics",
        "source.product.hourly_interval_anchor_not_established",
        "source.product.daily_mean_semantics",
    )
    canonical = (
        "canonical.provider_id",
        "canonical.product_identity",
        "canonical.product_unit",
        "canonical.product_period",
        "canonical.station_identity",
        "canonical.station_location",
        "canonical.station.crs",
        "canonical.observation.value",
    )
    return AcquisitionProvenance(
        schema_version=2,
        provider_id="cz_chmi",
        native_table=NativeTableIdentity(
            repository_path=NATIVE_TABLE_REPOSITORY_PATH,
            revision=NATIVE_TABLE_REVISION,
            sha256=NATIVE_TABLE_SHA256,
            byte_size=NATIVE_TABLE_BYTE_SIZE,
            semantic_digest=SemanticDigest(
                name="cz_chmi.native_table_content_sha256", sha256=NATIVE_TABLE_SEMANTIC_SHA256
            ),
        ),
        source_records=(
            SourceRecord(
                source_id="cz_chmi",
                issuer="Czech Hydrometeorological Institute",
                operator="CHMI Open Data",
                acquisitions=(
                    AcquisitionRecord(
                        acquisition_id="catalogue_capture_2026_08_02",
                        method="http_request",
                        instant_type="retrieval",
                        description="Complete 831-row CHMI historical hydrology metadata response",
                        requested_from=("https://opendata.chmi.cz/hydrology/historical/metadata/meta1.json",),
                        retrieved_at_start=datetime.fromisoformat("2026-08-02T00:14:31Z"),
                    ),
                    AcquisitionRecord(
                        acquisition_id="terms_capture_2026_08_20",
                        method="http_request",
                        instant_type="retrieval",
                        description="CHMI licensing and attribution HTML recording",
                        requested_from=(recording.source_url,),
                        retrieved_at_start=recording.retrieved_at,
                        recording_ids=(recording.recording_id,),
                    ),
                    AcquisitionRecord(
                        acquisition_id="product_semantics_capture_2026_09_02",
                        method="http_request",
                        instant_type="retrieval",
                        description=(
                            "CHMI TSCON_ID/TSCON_DS and UNIT_ID/UNIT_DS dictionary: "
                            "HD/QD/TD daily means and HH/QH hourly means, quantities and coded units"
                        ),
                        requested_from=(semantics_recording.source_url,),
                        retrieved_at_start=semantics_recording.retrieved_at,
                        recording_ids=(semantics_recording.recording_id,),
                    ),
                    AcquisitionRecord(
                        acquisition_id="observation_request",
                        method="runtime_http_request",
                        instant_type="runtime",
                        description="Exact annual CHMI station-cadence response",
                        requested_from=("https://opendata.chmi.cz/hydrology/historical/",),
                    ),
                ),
                evidence=(
                    EvidenceReference(
                        evidence_id="cz_chmi_terms",
                        description="CHMI licensing and attribution page",
                        recording=recording,
                    ),
                    EvidenceReference(
                        evidence_id="cz_chmi_product_semantics",
                        description="CHMI native product dictionary",
                        recording=semantics_recording,
                    ),
                ),
                statements=(
                    SourceStatement(
                        kind="license",
                        exact_text=_LICENSE,
                        recording_id=recording.recording_id,
                        fact="source.chmi.license_statement",
                    ),
                    SourceStatement(
                        kind="citation",
                        exact_text=_CITATION,
                        recording_id=recording.recording_id,
                        fact="source.chmi.citation_statement",
                    ),
                ),
            ),
        ),
        fact_bindings=(
            FactBinding(
                fact_group="terms_statements",
                facts=("source.chmi.license_statement", "source.chmi.citation_statement"),
                source_id="cz_chmi",
                acquisition_id="terms_capture_2026_08_20",
            ),
            FactBinding(
                fact_group="catalogue_external",
                facts=(external[0], *external[2:6]),
                source_id="cz_chmi",
                acquisition_id="catalogue_capture_2026_08_02",
            ),
            FactBinding(
                fact_group="product_semantics",
                facts=(external[1], *external[7:]),
                source_id="cz_chmi",
                acquisition_id="product_semantics_capture_2026_09_02",
            ),
            FactBinding(
                fact_group="observation_external",
                facts=external[6:7],
                source_id="cz_chmi",
                acquisition_id="observation_request",
            ),
            FactBinding(
                fact_group="canonical_catalogue",
                facts=canonical[:-1],
                source_id=None,
                acquisition_id=None,
                transformation=Transformation(
                    name="rivretrieve_czech_catalogue_harmonisation",
                    external_inputs=tuple(
                        ExternalFactReference(source_id="cz_chmi", fact=fact) for fact in (*external[:6], *external[7:])
                    ),
                ),
            ),
            FactBinding(
                fact_group="canonical_observation",
                facts=canonical[-1:],
                source_id=None,
                acquisition_id=None,
                transformation=Transformation(
                    name="rivretrieve_czech_observation_harmonisation",
                    external_inputs=(ExternalFactReference(source_id="cz_chmi", fact=external[6]),),
                ),
            ),
        ),
        fact_universe=external + canonical + ("source.chmi.license_statement", "source.chmi.citation_statement"),
    )


def _complete_catalogue_carrier(provenance: AcquisitionProvenance) -> AcquisitionProvenance:
    return complete_transformed_fact_universe(
        provenance,
        CATALOGUE_FACT_UNIVERSE,
        transformation=Transformation(
            name="cz_chmi external facts to RivRetrieve canonical catalogue carriers",
            external_inputs=(
                ExternalFactReference(source_id="cz_chmi", fact="source.provider.service"),
                ExternalFactReference(source_id="cz_chmi", fact="source.product.native_identity"),
                ExternalFactReference(source_id="cz_chmi", fact="source.station.native_identity"),
                ExternalFactReference(source_id="cz_chmi", fact="source.station.native_location"),
                ExternalFactReference(source_id="cz_chmi", fact="source.station.crs_not_published"),
                ExternalFactReference(source_id="cz_chmi", fact="source.station_product.availability_not_published"),
                ExternalFactReference(source_id="cz_chmi", fact="source.product.hourly_mean_semantics"),
                ExternalFactReference(source_id="cz_chmi", fact="source.product.daily_mean_semantics"),
                ExternalFactReference(
                    source_id="cz_chmi", fact="source.product.hourly_interval_anchor_not_established"
                ),
            ),
        ),
    )


def build_acquisition_provenance() -> AcquisitionProvenance:
    """Build closed cz_chmi acquisition provenance."""
    return _complete_catalogue_carrier(_build_provider_acquisition_provenance())


# Existing acquisition facts materialised in the retained native table.
# This declares derived-input support, not preservation of original responses.
NATIVE_TABLE_ACQUISITION_IDS = ("catalogue_capture_2026_08_02",)


# Authored catalogue, physical-fact and support declarations selected at build time.
CATALOGUE_BUILD_DECLARATIONS = (
    ("src/rivretrieve/_internal/providers/cz_chmi/origins.py", "build_acquisition_provenance"),
    ("src/rivretrieve/_internal/providers/cz_chmi/origins.py", "NATIVE_TABLE_ACQUISITION_IDS"),
    ("src/rivretrieve/_internal/providers/cz_chmi/origins.py", "CATALOGUE_SUPPORTING_INPUTS"),
    ("src/rivretrieve/_internal/providers/cz_chmi/origins.py", "STATION_METADATA_FIELDS"),
    ("src/rivretrieve/_internal/providers/cz_chmi/origins.py", "STATION_METADATA_NOTICE"),
    ("src/rivretrieve/_internal/providers/cz_chmi/generate_catalogue.py", "build_catalogue"),
    ("src/rivretrieve/_internal/conversion.py", "convert"),
    ("src/rivretrieve/_internal/providers/cz_chmi/origins.py", "TRANSFORMATION_IMPLEMENTATIONS"),
    ("src/rivretrieve/_internal/providers/cz_chmi/config.py", "config"),
    ("src/rivretrieve/_internal/providers/cz_chmi/config.py", "SERIES_MAPPINGS"),
)


# Additional retained declarations used by these source facts; not original-body claims.
CATALOGUE_SUPPORTING_INPUTS = {}


# Exact observation operation responsibility; catalogue publication does not run it.
TRANSFORMATION_IMPLEMENTATIONS = {
    "canonical_observation": ("src/rivretrieve/_internal/conversion.py", "convert"),
}
