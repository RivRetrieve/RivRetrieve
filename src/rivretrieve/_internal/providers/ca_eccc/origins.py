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
from rivretrieve._internal.catalogue_origins import (
    Authored,
    AuthoredValue,
    Documented,
    DocumentedValue,
    Evidence,
    Field,
    FloatConversion,
    NativeColumn,
)
from rivretrieve._internal.catalogues.artifact import CATALOGUE_FACT_UNIVERSE
from rivretrieve._internal.catalogues.station_metadata import MetadataField

# Name mappings require genuine-input validation and owner disclosure approval
# before generated metadata can be packaged. Native presence is insufficient.
STATION_METADATA_NOTICE = (
    "Station metadata from Environment and Climate Change Canada, Meteorological Service of Canada. "
    "Contains information licensed under the Open Government Licence – Canada "
    "(https://open.canada.ca/en/open-government-licence-canada). RivRetrieve selected the declared source "
    "fields and encoded their values and absence states; source names remain unchanged. Processing and "
    "publication of this projection: RivRetrieve."
)

STATION_METADATA_FIELDS: tuple[MetadataField, ...] = (
    MetadataField("drainage_area", "DRAINAGE_AREA_GROSS"),
    MetadataField("drainage_area", "DRAINAGE_AREA_EFFECT"),
    MetadataField("station_name", "STATION_NAME"),
)

CRS_EVIDENCE_URL = "https://api.weather.gc.ca/collections/hydrometric-stations?f=json"
STATION_CATALOGUE_ORIGINS = {
    "provider_id": Authored(AuthoredValue("ca_eccc")),
    "station_id": Field(NativeColumn("STATION_NUMBER")),
    "latitude": Field(NativeColumn("geometry.coordinates[1]"), FloatConversion()),
    "longitude": Field(NativeColumn("geometry.coordinates[0]"), FloatConversion()),
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
    canonical_observation_facts = ("observation.identity_bearing_shape",)
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
                    AcquisitionRecord(
                        acquisition_id="msc_licence_capture_2026_08_20",
                        method="http_request",
                        instant_type="retrieval",
                        description="ECCC Data Servers End-use Licence response",
                        requested_from=(licence.source_url,),
                        retrieved_at_start=licence.retrieved_at,
                        recording_ids=(licence.recording_id,),
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
                    SourceStatement(
                        kind="license",
                        exact_text=LICENCE_TEXT,
                        recording_id=licence.recording_id,
                        fact="source.provider.license_statement",
                    ),
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
                    AcquisitionRecord(
                        acquisition_id="wsc_citation_capture_2026_08_20",
                        method="http_request",
                        instant_type="retrieval",
                        description="Wateroffice hydrometric citation instructions response",
                        requested_from=(citation.source_url,),
                        retrieved_at_start=citation.retrieved_at,
                        recording_ids=(citation.recording_id,),
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
                    SourceStatement(
                        kind="citation",
                        exact_text=CITATION_TEXT,
                        recording_id=citation.recording_id,
                        fact="source.provider.citation_statement",
                    ),
                ),
            ),
        ),
        fact_bindings=(
            FactBinding(
                fact_group="msc_licence_statement",
                facts=("source.provider.license_statement",),
                source_id="ca_eccc_msc",
                acquisition_id="msc_licence_capture_2026_08_20",
            ),
            FactBinding(
                fact_group="wsc_citation_statement",
                facts=("source.provider.citation_statement",),
                source_id="ca_eccc_wsc",
                acquisition_id="wsc_citation_capture_2026_08_20",
            ),
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
                    name="HYDAT observations to identity-bearing RivRetrieve observation rows",
                    external_inputs=(
                        ExternalFactReference(source_id="ca_eccc_wsc", fact="source.observation.value"),
                        ExternalFactReference(source_id="ca_eccc_wsc", fact="source.observation.quality"),
                    ),
                ),
            ),
        ),
        fact_universe=station_facts
        + obs_facts
        + canonical_observation_facts
        + ("source.provider.license_statement", "source.provider.citation_statement"),
    )


def _complete_catalogue_carrier(provenance: AcquisitionProvenance) -> AcquisitionProvenance:
    term_bindings = tuple(
        FactBinding(
            fact_group=f"canonical_provider_{statement.kind}",
            facts=(f"provider.{statement.kind}",),
            source_id=None,
            acquisition_id=None,
            transformation=Transformation(
                name=f"Canada verified source {statement.kind} statement to canonical provider carrier",
                external_inputs=(ExternalFactReference(source_id=source.source_id, fact=statement.fact),),
            ),
        )
        for source in provenance.source_records
        for statement in source.statements
        if statement.kind in ("license", "citation") and statement.fact is not None
    )
    payload = provenance.model_dump(mode="python")
    payload["fact_bindings"] = (*provenance.fact_bindings, *term_bindings)
    payload["fact_universe"] = (
        *provenance.fact_universe,
        *(fact for binding in term_bindings for fact in binding.facts),
    )
    provenance = AcquisitionProvenance.model_validate(payload)
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


# Existing acquisition facts materialised in the retained native table.
# This declares derived-input support, not preservation of original responses.
NATIVE_TABLE_ACQUISITION_IDS = ("station_registry_capture_2026_08_02",)


# Authored catalogue, physical-fact and support declarations selected at build time.
CATALOGUE_BUILD_DECLARATIONS = (
    ("src/rivretrieve/_internal/providers/ca_eccc/origins.py", "build_acquisition_provenance"),
    ("src/rivretrieve/_internal/providers/ca_eccc/origins.py", "NATIVE_TABLE_ACQUISITION_IDS"),
    ("src/rivretrieve/_internal/providers/ca_eccc/origins.py", "CATALOGUE_SUPPORTING_INPUTS"),
    ("src/rivretrieve/_internal/providers/ca_eccc/origins.py", "STATION_METADATA_FIELDS"),
    ("src/rivretrieve/_internal/providers/ca_eccc/origins.py", "STATION_METADATA_NOTICE"),
    ("src/rivretrieve/_internal/providers/ca_eccc/generate_catalogue.py", "build_catalogue"),
    ("src/rivretrieve/_internal/providers/ca_eccc/bulk.py", "_unpivot_month"),
    ("src/rivretrieve/_internal/providers/ca_eccc/origins.py", "TRANSFORMATION_IMPLEMENTATIONS"),
    ("src/rivretrieve/_internal/providers/ca_eccc/config.py", "config"),
    ("src/rivretrieve/_internal/providers/ca_eccc/catalogue_series.py", "describe_catalogue"),
)


# Additional retained declarations used by these source facts; not original-body claims.
CATALOGUE_SUPPORTING_INPUTS = {}


# Exact observation operation responsibility; catalogue publication does not run it.
TRANSFORMATION_IMPLEMENTATIONS = {
    "canonical_observation_shape": ("src/rivretrieve/_internal/providers/ca_eccc/bulk.py", "_unpivot_month"),
}
