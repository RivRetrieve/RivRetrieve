"""Canada catalogue authority : ∅ → OriginDeclarations × AcquisitionProvenance (pure)."""

from datetime import datetime

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
from rivretrieve._internal.catalogue_origins import Documented, DocumentedValue, Evidence, Field, NativeColumn
from rivretrieve._internal.catalogues.artifact import CATALOGUE_FACT_UNIVERSE

CRS_EVIDENCE_URL = "https://api.weather.gc.ca/collections/hydrometric-stations?f=json"
STATION_CATALOGUE_ORIGINS = {
    "provider_id": Field(NativeColumn("STATION_NUMBER")),
    "station_id": Field(NativeColumn("STATION_NUMBER")),
    "latitude": Field(NativeColumn("geometry.coordinates[1]")),
    "longitude": Field(NativeColumn("geometry.coordinates[0]")),
    "crs": Documented(DocumentedValue("EPSG:4326"), Evidence(CRS_EVIDENCE_URL)),
}
NATIVE_TABLE_SHA256 = "2f451d5f088b147f5dc81d6b95d124d9fd7f9c5e3e671998b3213a708028f173"
NATIVE_TABLE_BYTE_SIZE = 244106
NATIVE_TABLE_REVISION = "a74ad90d2799546c16f049a2b437d9038294f2aa"
NATIVE_TABLE_REPOSITORY_PATH = "src/rivretrieve/_internal/providers/ca_eccc/catalogue/native.parquet"
NATIVE_TABLE_SEMANTIC_SHA256 = "46780a69f07e9ed8a7eae343929d81b4c78f2330d6268ee1fdc7de701cd6fe48"
LICENCE_TEXT = "Use of any Information indicates your acceptance of the terms below. The Information Provider grants you a worldwide, royalty-free, perpetual, non-exclusive licence to use the Information, including for commercial purposes, subject to the terms below."
CITATION_TEXT = "For real-time data retrieved from the Wateroffice web site:“Extracted from the Environment and Climate Change Canada Real-time Hydrometric Data web site (https://wateroffice.ec.gc.ca/mainmenu/real_time_data_index_e.html) on [DATE]” For historical data retrieved from the Wateroffice web site:“Extracted from the Environment and Climate Change Canada Historical Hydrometric Data web site (https://wateroffice.ec.gc.ca/mainmenu/historical_data_index_e.html) on [DATE]” For historical data retrieved from the MDB file:“Extracted from Environment and Climate Change Canada’s HYDAT.mdb, released on [DATE]”"


def _build_provider_acquisition_provenance() -> AcquisitionProvenance:
    licence = RecordingReference(
        recording_id="ca_eccc_terms_licence",
        repository_path="tests/test_data/ca_eccc_terms_licence.html",
        source_url="https://eccc-msc.github.io/open-data/licence/readme_en/",
        retrieved_at=datetime.fromisoformat("2026-08-20T12:31:14Z"),
        media_type="text/html; charset=utf-8",
        sha256="8dc38d32872a836ea93fb9771ba182dc14f41198fbcd17f83178e7b76e205b48",
    )
    citation = RecordingReference(
        recording_id="ca_eccc_terms_citation",
        repository_path="tests/test_data/ca_eccc_terms_citation.html",
        source_url="https://wateroffice.ec.gc.ca/contactus/faq_e.html",
        retrieved_at=datetime.fromisoformat("2026-08-20T12:31:16Z"),
        media_type="text/html; charset=UTF-8",
        sha256="0b64429355f7114725ddae6a77ceb53c19709f13a0e0b43d8dbb0f9a9958311d",
    )
    station_facts = (
        "source.provider.canonical_identity",
        "source.station.native_identity",
        "source.station.native_geometry",
        "source.station.horizontal_crs",
        "source.station_product.availability_not_published",
    )
    obs_facts = (
        "source.observation.value",
        "source.observation.quality",
    )
    canonical_observation_facts = ("observation.canonical_five_column_shape",)
    return AcquisitionProvenance(
        schema_version=2,
        provider_id="ca_eccc",
        native_table=NativeTableIdentity(
            repository_path=NATIVE_TABLE_REPOSITORY_PATH,
            revision=NATIVE_TABLE_REVISION,
            sha256=NATIVE_TABLE_SHA256,
            byte_size=NATIVE_TABLE_BYTE_SIZE,
            semantic_digest=SemanticDigest(
                name="ca_eccc.native_table_content_sha256", sha256=NATIVE_TABLE_SEMANTIC_SHA256
            ),
        ),
        source_records=(
            SourceRecord(
                source_id="ca_eccc_msc",
                issuer="Environment and Climate Change Canada, Meteorological Service of Canada",
                operator="MSC GeoMet",
                acquisitions=(
                    AcquisitionRecord(
                        acquisition_id="station_registry_capture_2026_08_02",
                        method="http_campaign",
                        instant_type="retrieval_interval",
                        description="Nine complete GeoMet pages assembled into 8,057 station features",
                        requested_from=(
                            "https://api.weather.gc.ca/collections/hydrometric-stations/items?f=json&limit=1000&offset={offset}",
                        ),
                        retrieved_at_start=datetime.fromisoformat("2026-08-02T01:09:10Z"),
                        retrieved_at_end=datetime.fromisoformat("2026-08-02T01:09:20Z"),
                    ),
                ),
                evidence=(
                    EvidenceReference(
                        evidence_id="eccc_data_server_licence",
                        description="ECCC Data Servers End-use Licence",
                        recording=licence,
                    ),
                ),
                statements=(
                    SourceStatement(kind="license", exact_text=LICENCE_TEXT, recording_id=licence.recording_id),
                ),
            ),
            SourceRecord(
                source_id="ca_eccc_wsc",
                issuer="Environment and Climate Change Canada, Water Survey of Canada",
                operator="HYDAT",
                acquisitions=(
                    AcquisitionRecord(
                        acquisition_id="hydat_observation_artifact",
                        method="runtime_http_request",
                        instant_type="runtime",
                        description="HYDAT SQLite ZIP artifact retained with exact URL, digest, and acquisition instant",
                        requested_from=(
                            "https://collaboration.cmc.ec.gc.ca/cmc/hydrometrics/www/Hydat_sqlite3_<vintage>.zip",
                        ),
                    ),
                ),
                evidence=(
                    EvidenceReference(
                        evidence_id="hydrometric_citation",
                        description="Wateroffice hydrometric citation instructions",
                        recording=citation,
                    ),
                ),
                statements=(
                    SourceStatement(kind="citation", exact_text=CITATION_TEXT, recording_id=citation.recording_id),
                ),
            ),
        ),
        fact_bindings=(
            FactBinding(
                fact_group="station_registry",
                facts=station_facts,
                source_id="ca_eccc_msc",
                acquisition_id="station_registry_capture_2026_08_02",
            ),
            FactBinding(
                fact_group="hydat_observations",
                facts=obs_facts,
                source_id="ca_eccc_wsc",
                acquisition_id="hydat_observation_artifact",
            ),
            FactBinding(
                fact_group="canonical_observation_shape",
                facts=canonical_observation_facts,
                source_id=None,
                acquisition_id=None,
                transformation=Transformation(
                    name="HYDAT observations to RivRetrieve five-column result shape",
                    external_inputs=(
                        ExternalFactReference(source_id="ca_eccc_wsc", fact="source.observation.value"),
                        ExternalFactReference(source_id="ca_eccc_wsc", fact="source.observation.quality"),
                    ),
                ),
            ),
        ),
        fact_universe=station_facts + obs_facts + canonical_observation_facts,
    )


def _complete_catalogue_carrier(provenance: AcquisitionProvenance) -> AcquisitionProvenance:
    msc_facts = tuple(fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith(("provider.", "station.")))
    provenance = complete_transformed_fact_universe(
        provenance,
        msc_facts,
        transformation=Transformation(
            name="Canada station registry facts to canonical provider and station carriers",
            external_inputs=(
                ExternalFactReference(source_id="ca_eccc_msc", fact="source.provider.canonical_identity"),
                ExternalFactReference(source_id="ca_eccc_msc", fact="source.station.native_identity"),
            ),
        ),
        fact_group="canonical_msc_catalogue_carrier",
    )
    product_facts = tuple(fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith("product."))
    provenance = complete_transformed_fact_universe(
        provenance,
        product_facts,
        transformation=Transformation(
            name="RivRetrieve code-defined HYDAT product definitions",
            kind="authored_constant",
            external_inputs=(),
        ),
        fact_group="canonical_wsc_product_carrier",
    )
    station_product_facts = tuple(fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith("station_product."))
    return complete_transformed_fact_universe(
        provenance,
        station_product_facts,
        transformation=Transformation(
            name="Canada station registry membership to canonical station-product carrier",
            external_inputs=(
                ExternalFactReference(
                    source_id="ca_eccc_msc", fact="source.station_product.availability_not_published"
                ),
            ),
        ),
        fact_group="canonical_wsc_station_product_carrier",
    )


def build_acquisition_provenance() -> AcquisitionProvenance:
    """Build closed ca_eccc acquisition provenance."""
    return _complete_catalogue_carrier(_build_provider_acquisition_provenance())
