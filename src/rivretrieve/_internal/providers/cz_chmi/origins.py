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

STATION_CATALOGUE_ORIGINS: dict[str, catalogue_origins.CatalogueOrigin] = {
    "provider_id": catalogue_origins.Field(catalogue_origins.NativeColumn("objID")),
    "station_id": catalogue_origins.Field(catalogue_origins.NativeColumn("objID")),
    "latitude": catalogue_origins.Field(catalogue_origins.NativeColumn("GEOGR1")),
    "longitude": catalogue_origins.Field(catalogue_origins.NativeColumn("GEOGR2")),
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
    external = (
        "source.provider.service",
        "source.product.native_identity",
        "source.station.native_identity",
        "source.station.native_location",
        "source.station.crs_not_published",
        "source.station_product.availability_not_published",
        "source.observation.native_value",
        "source.observation.native_quality",
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
                        acquisition_id="observation_request",
                        method="runtime_http_request",
                        instant_type="runtime",
                        description="Exact annual CHMI station-product response",
                        requested_from=("https://opendata.chmi.cz/hydrology/historical/",),
                    ),
                ),
                evidence=(
                    EvidenceReference(
                        evidence_id="cz_chmi_terms",
                        description="CHMI licensing and attribution page",
                        recording=recording,
                    ),
                ),
                statements=(
                    SourceStatement(kind="license", exact_text=_LICENSE, recording_id=recording.recording_id),
                    SourceStatement(kind="citation", exact_text=_CITATION, recording_id=recording.recording_id),
                ),
            ),
        ),
        fact_bindings=(
            FactBinding(
                fact_group="catalogue_external",
                facts=external[:-2],
                source_id="cz_chmi",
                acquisition_id="catalogue_capture_2026_08_02",
            ),
            FactBinding(
                fact_group="observation_external",
                facts=external[-2:],
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
                        ExternalFactReference(source_id="cz_chmi", fact=fact) for fact in external[:-2]
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
                    external_inputs=tuple(
                        ExternalFactReference(source_id="cz_chmi", fact=fact) for fact in external[-2:]
                    ),
                ),
            ),
        ),
        fact_universe=external + canonical,
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
            ),
        ),
    )


def build_acquisition_provenance() -> AcquisitionProvenance:
    """Build closed cz_chmi acquisition provenance."""
    return _complete_catalogue_carrier(_build_provider_acquisition_provenance())
