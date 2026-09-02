"""Swiss catalogue authority : ∅ → OriginDeclarations × AcquisitionProvenance (pure)."""

from datetime import datetime

from rivretrieve._internal.acquisition_provenance import (
    AcquisitionProvenance,
    AcquisitionRecord,
    EvidenceReference,
    ExternalFactReference,
    FactBinding,
    NativeTableIdentity,
    RecordingReference,
    SourceRecord,
    SourceStatement,
    Transformation,
    complete_transformed_fact_universe,
)
from rivretrieve._internal.catalogue_origins import Evidence, Field, NativeColumn, NotPublished
from rivretrieve._internal.catalogues.artifact import CATALOGUE_FACT_UNIVERSE

STATION_CATALOGUE_ORIGINS = {
    "provider_id": Field(NativeColumn("name")),
    "station_id": Field(NativeColumn("name")),
    "latitude": Field(NativeColumn("details.lat")),
    "longitude": Field(NativeColumn("details.lon")),
    "crs": NotPublished(Evidence("https://api.existenz.ch/#hydro")),
}
NATIVE_TABLE_SHA256 = "71b0a329568df9ad031339d3b77b4c692762c6feab6659c20751bebfbea18b48"
NATIVE_TABLE_BYTE_SIZE = 17765
NATIVE_TABLE_REVISION = "7fe7997d95b7ba2efc294ed4c4bf5910c9f93950"
NATIVE_TABLE_REPOSITORY_PATH = "src/rivretrieve/_internal/providers/ch_foen/catalogue/native.parquet"
BAFU_LICENCE = "Die Daten können frei genutzt werden. Die Angabe der Quelle wird empfohlen."
BAFU_CITATION = "Vorschlag für die Quellenangabe: Daten Oberflächengewässer: Abteilung Hydrologie, Bundesamt für Umwelt BAFU (Bezugsdatum)."
EXISTENZ_TERMS = "These APIs with weather and water data for Switzerland are free for public and non-commercial use, lovingly handcrafted by Christian Studer (Bureau für digitale Existenz)."
EXISTENZ_CREDIT = "BAFU data needs to be credited and linked to the BAFU."


def _build_provider_acquisition_provenance() -> AcquisitionProvenance:
    bafu = RecordingReference(
        recording_id="ch_foen_terms_bafu",
        repository_path="tests/test_data/ch_foen_terms_bafu.html",
        source_url="https://www.hydrodaten.admin.ch/de/fragen",
        retrieved_at=datetime.fromisoformat("2026-08-20T13:12:57Z"),
        media_type="text/html; charset=utf-8",
        sha256="d2ad98f7f12463cf9d67e0f72848185219557818814a5df02c86ed72138f7d66",
    )
    existenz = RecordingReference(
        recording_id="ch_foen_terms_existenz",
        repository_path="tests/test_data/ch_foen_terms_existenz.html",
        source_url="https://api.existenz.ch/",
        retrieved_at=datetime.fromisoformat("2026-08-20T13:12:58Z"),
        media_type="text/html; charset=UTF-8",
        sha256="488b25d24651aafb520d7cf69c1d36ac9f4384fa096b9cab77b44c6b669f82df",
    )
    bafu_facts = (
        "source.provider.canonical_identity",
        "source.station.native_identity",
        "source.station.native_geometry",
        "source.product.native_id",
        "source.product.native_physics",
        "source.observation.value",
        "source.observation.quality",
    )
    intermediary_facts = (
        "source.station.crs_not_published",
        "source.station_product.availability_not_published",
        "source.observation.transport",
    )
    canonical_observation_facts = ("observation.canonical_five_column_shape",)
    acq = AcquisitionRecord(
        acquisition_id="existenz_catalogue_capture_2026_08_02",
        method="http_request",
        instant_type="retrieval",
        description="Complete 246-station Existenz hydro locations response carrying BAFU data",
        requested_from=("https://api.existenz.ch/apiv1/hydro/locations",),
        retrieved_at_start=datetime.fromisoformat("2026-08-02T00:14:31Z"),
    )
    runtime = AcquisitionRecord(
        acquisition_id="existenz_observation_request",
        method="runtime_http_request",
        instant_type="runtime",
        description="Exact Existenz observation request and response",
        requested_from=("https://api.existenz.ch/apiv1/hydro/latest",),
    )
    return AcquisitionProvenance(
        schema_version=2,
        provider_id="ch_foen",
        native_table=NativeTableIdentity(
            repository_path=NATIVE_TABLE_REPOSITORY_PATH,
            revision=NATIVE_TABLE_REVISION,
            sha256=NATIVE_TABLE_SHA256,
            byte_size=NATIVE_TABLE_BYTE_SIZE,
        ),
        source_records=(
            SourceRecord(
                source_id="ch_bafu",
                issuer="Federal Office for the Environment (BAFU/FOEN)",
                acquisitions=(acq, runtime),
                evidence=(
                    EvidenceReference(
                        evidence_id="bafu_hydrology_terms",
                        description="BAFU hydrology terms and source wording",
                        recording=bafu,
                    ),
                ),
                statements=(
                    SourceStatement(kind="license", exact_text=BAFU_LICENCE, recording_id=bafu.recording_id),
                    SourceStatement(kind="citation", exact_text=BAFU_CITATION, recording_id=bafu.recording_id),
                ),
            ),
            SourceRecord(
                source_id="ch_existenz",
                issuer="Christian Studer, Bureau für digitale Existenz",
                operator="api.existenz.ch",
                acquisitions=(acq, runtime),
                evidence=(
                    EvidenceReference(
                        evidence_id="existenz_api_terms",
                        description="Intermediary API conditions and BAFU credit statement",
                        recording=existenz,
                    ),
                ),
                statements=(
                    SourceStatement(kind="terms", exact_text=EXISTENZ_TERMS, recording_id=existenz.recording_id),
                    SourceStatement(kind="citation", exact_text=EXISTENZ_CREDIT, recording_id=existenz.recording_id),
                ),
            ),
        ),
        fact_bindings=(
            FactBinding(
                fact_group="bafu_station_product_values",
                facts=bafu_facts,
                source_id="ch_bafu",
                acquisition_id="existenz_catalogue_capture_2026_08_02",
            ),
            FactBinding(
                fact_group="existenz_transport_and_absence",
                facts=intermediary_facts,
                source_id="ch_existenz",
                acquisition_id="existenz_catalogue_capture_2026_08_02",
            ),
            FactBinding(
                fact_group="canonical_observation_shape",
                facts=canonical_observation_facts,
                source_id=None,
                acquisition_id=None,
                transformation=Transformation(
                    name="BAFU observations to RivRetrieve five-column result shape",
                    external_inputs=(
                        ExternalFactReference(source_id="ch_bafu", fact="source.observation.value"),
                        ExternalFactReference(source_id="ch_bafu", fact="source.observation.quality"),
                    ),
                ),
            ),
        ),
        fact_universe=bafu_facts + intermediary_facts + canonical_observation_facts,
    )


def _complete_catalogue_carrier(provenance: AcquisitionProvenance) -> AcquisitionProvenance:
    bafu_facts = tuple(
        fact for fact in CATALOGUE_FACT_UNIVERSE if fact != "station.crs" and not fact.startswith("station_product.")
    )
    provenance = complete_transformed_fact_universe(
        provenance,
        bafu_facts,
        transformation=Transformation(
            name="BAFU source facts to canonical provider, product, and station carriers",
            external_inputs=(
                ExternalFactReference(source_id="ch_bafu", fact="source.provider.canonical_identity"),
                ExternalFactReference(source_id="ch_bafu", fact="source.station.native_identity"),
                ExternalFactReference(source_id="ch_bafu", fact="source.product.native_physics"),
            ),
        ),
        fact_group="canonical_bafu_catalogue_carrier",
    )
    existenz_facts = tuple(
        fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith(("station.", "station_product."))
    )
    return complete_transformed_fact_universe(
        provenance,
        existenz_facts,
        transformation=Transformation(
            name="Existenz documented absence facts to canonical CRS and availability carriers",
            external_inputs=(
                ExternalFactReference(source_id="ch_existenz", fact="source.station.crs_not_published"),
                ExternalFactReference(
                    source_id="ch_existenz", fact="source.station_product.availability_not_published"
                ),
            ),
        ),
        fact_group="canonical_existenz_catalogue_carrier",
    )


def build_acquisition_provenance() -> AcquisitionProvenance:
    """Build closed ch_foen acquisition provenance."""
    return _complete_catalogue_carrier(_build_provider_acquisition_provenance())
