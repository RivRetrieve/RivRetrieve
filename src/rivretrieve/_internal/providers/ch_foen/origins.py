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
from rivretrieve._internal.catalogue_origins import (
    Authored,
    AuthoredValue,
    Evidence,
    Field,
    FloatConversion,
    NativeColumn,
    NotPublished,
)
from rivretrieve._internal.catalogues.artifact import CATALOGUE_FACT_UNIVERSE

STATION_CATALOGUE_ORIGINS = {
    "provider_id": Authored(AuthoredValue("ch_foen")),
    "station_id": Field(NativeColumn("name")),
    "latitude": Field(NativeColumn("details.lat"), FloatConversion()),
    "longitude": Field(NativeColumn("details.lon"), FloatConversion()),
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
    bafu_current_data = RecordingReference(
        recording_id="ch_foen_bafu_current_data_2026_09_02",
        repository_path="tests/test_data/ch_foen_bafu_current_hydrological_data.html",
        source_url="https://www.bafu.admin.ch/de/aktuelle-hydrologische-daten-beziehen",
        retrieved_at=datetime.fromisoformat("2026-09-02T17:04:52.348247Z"),
        media_type="text/html;charset=utf-8",
        sha256="5aa90c7c311a155c1c3b9df7f5d403497fdb4552039ea24b6b787bdac601d94c",
    )
    bafu_data_service = RecordingReference(
        recording_id="ch_foen_bafu_data_service_2026_09_02",
        repository_path="tests/test_data/ch_foen_bafu_hydrology_data_service.html",
        source_url="https://www.bafu.admin.ch/de/datenservice-hydrologie-fuer-fliessgewaesser-und-seen",
        retrieved_at=datetime.fromisoformat("2026-09-02T17:04:52.675158Z"),
        media_type="text/html;charset=utf-8",
        sha256="425dbcf44abca31b65061b0652f46d02b6750aefb16ade4da9471c9f0326f082",
    )
    existenz = RecordingReference(
        recording_id="ch_foen_terms_existenz",
        repository_path="tests/test_data/ch_foen_terms_existenz.html",
        source_url="https://api.existenz.ch/",
        retrieved_at=datetime.fromisoformat("2026-08-20T13:12:58Z"),
        media_type="text/html; charset=UTF-8",
        sha256="b353852a474516acf404c1d8b775cc77c5cf3c97bd3055380fc4534bcba9111c",
    )
    parameters = RecordingReference(
        recording_id="ch_foen_parameters_2026_09_02",
        repository_path="tests/test_data/ch_foen_parameters_2026-09-02.recording.json",
        source_url="https://api.existenz.ch/apiv1/hydro/parameters",
        retrieved_at=datetime.fromisoformat("2026-09-02T15:41:56.950701Z"),
        media_type="application/vnd.rivretrieve.recording+json",
        sha256="592c9fdee1992551d0a3eec01ed5150ccf3668ce1e9162c45e0b2c2bebeba0e4",
    )
    rest_observations = RecordingReference(
        recording_id="ch_foen_rest_observations_2026_09_02",
        repository_path="tests/test_data/ch_foen_2135_rest_2026-09-01.recording.json",
        source_url="https://api.existenz.ch/apiv1/hydro/daterange",
        retrieved_at=datetime.fromisoformat("2026-09-02T16:47:23.700173Z"),
        media_type="application/vnd.rivretrieve.recording+json",
        sha256="68823a7be35d9cf435515522e2275b761d2a15a7ea28ec40b0b7eaa9bb9569bd",
    )
    flux_observations = RecordingReference(
        recording_id="ch_foen_flux_observations_2026_09_02",
        repository_path="tests/test_data/ch_foen_2135_flux_2020-01-01.recording.json",
        source_url="https://influx.konzept.space/api/v2/query",
        retrieved_at=datetime.fromisoformat("2026-09-02T15:42:05.306549Z"),
        media_type="application/vnd.rivretrieve.recording+json",
        sha256="9b9007164e9e58e4c1d144d6db22dce6e6cab7984c91ab504022eea9c746e62c",
    )
    bafu_catalogue_facts = (
        "source.provider.canonical_identity",
        "source.station.native_identity",
        "source.station.native_geometry",
    )
    bafu_parameter_facts = ("source.product.native_id", "source.product.native_physics")
    bafu_observation_facts = ("source.observation.value", "source.observation.quality")
    bafu_temporal_facts = ("source.product.temporal_support_not_identified",)
    bafu_facts = bafu_catalogue_facts + bafu_parameter_facts + bafu_observation_facts + bafu_temporal_facts
    intermediary_facts = (
        "source.station.crs_not_published",
        "source.station_product.availability_not_published",
        "source.observation.transport",
    )
    canonical_observation_facts = ("observation.source_series_shape",)
    acq = AcquisitionRecord(
        acquisition_id="existenz_catalogue_capture_2026_08_02",
        method="http_request",
        instant_type="retrieval",
        description="Complete 246-station Existenz hydro locations response carrying BAFU data",
        requested_from=("https://api.existenz.ch/apiv1/hydro/locations",),
        retrieved_at_start=datetime.fromisoformat("2026-08-02T00:14:31Z"),
    )
    parameter_capture = AcquisitionRecord(
        acquisition_id="existenz_parameters_capture_2026_09_02",
        method="http_request",
        instant_type="retrieval",
        description="Exact Existenz parameter dictionary response",
        requested_from=(parameters.source_url,),
        retrieved_at_start=parameters.retrieved_at,
        recording_ids=(parameters.recording_id,),
    )
    observation_capture = AcquisitionRecord(
        acquisition_id="existenz_observations_capture_2026_09_02",
        method="http_request",
        instant_type="retrieval_interval",
        description="Exact recent REST and older Flux observation requests and responses",
        requested_from=(rest_observations.source_url, flux_observations.source_url),
        retrieved_at_start=flux_observations.retrieved_at,
        retrieved_at_end=rest_observations.retrieved_at,
        recording_ids=(rest_observations.recording_id, flux_observations.recording_id),
    )
    intermediary_observation = AcquisitionRecord(
        acquisition_id="existenz_runtime_observation_surfaces",
        method="runtime_http_request",
        instant_type="runtime",
        description="Recent REST and older Flux intermediary observation surfaces",
        requested_from=(rest_observations.source_url, flux_observations.source_url),
    )
    bafu_terms = AcquisitionRecord(
        acquisition_id="bafu_terms_capture_2026_08_20",
        method="http_request",
        instant_type="retrieval",
        description="BAFU hydrology terms and source-wording response",
        requested_from=(bafu.source_url,),
        retrieved_at_start=bafu.retrieved_at,
        recording_ids=(bafu.recording_id,),
    )
    bafu_temporal_audit = AcquisitionRecord(
        acquisition_id="bafu_temporal_audit_2026_09_02",
        method="http_request",
        instant_type="retrieval_interval",
        description="Official update-cadence and distinct temporal-product evidence",
        requested_from=(bafu_current_data.source_url, bafu_data_service.source_url),
        retrieved_at_start=bafu_current_data.retrieved_at,
        retrieved_at_end=bafu_data_service.retrieved_at,
        recording_ids=(bafu_current_data.recording_id, bafu_data_service.recording_id),
    )
    existenz_terms = AcquisitionRecord(
        acquisition_id="existenz_terms_capture_2026_08_20",
        method="http_request",
        instant_type="retrieval",
        description="Existenz API conditions and BAFU credit response; published archive credential redacted in retained fixture",
        requested_from=(existenz.source_url,),
        retrieved_at_start=existenz.retrieved_at,
        recording_ids=(existenz.recording_id,),
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
                acquisitions=(acq, parameter_capture, observation_capture, bafu_terms, bafu_temporal_audit),
                evidence=(
                    EvidenceReference(
                        evidence_id="bafu_hydrology_terms",
                        description="BAFU hydrology terms and source wording",
                        recording=bafu,
                    ),
                    EvidenceReference(
                        evidence_id="bafu_current_data_update_cadence",
                        description="Official current-data update cadence without exact Existenz temporal binding",
                        recording=bafu_current_data,
                    ),
                    EvidenceReference(
                        evidence_id="bafu_continuous_data_product_variants",
                        description="Official distinct support-point and mean products",
                        recording=bafu_data_service,
                    ),
                    EvidenceReference(
                        evidence_id="existenz_parameter_dictionary",
                        description="Exact native fields and units carried for BAFU data",
                        recording=parameters,
                    ),
                    EvidenceReference(
                        evidence_id="existenz_recent_observations",
                        description="Exact recent REST observation interaction",
                        recording=rest_observations,
                    ),
                    EvidenceReference(
                        evidence_id="existenz_flux_observations",
                        description="Exact older Flux observation interaction",
                        recording=flux_observations,
                    ),
                ),
                statements=(
                    SourceStatement(
                        kind="license",
                        exact_text=BAFU_LICENCE,
                        recording_id=bafu.recording_id,
                        fact="source.provider.bafu_license_statement",
                    ),
                    SourceStatement(
                        kind="citation",
                        exact_text=BAFU_CITATION,
                        recording_id=bafu.recording_id,
                        fact="source.provider.bafu_citation_statement",
                    ),
                ),
            ),
            SourceRecord(
                source_id="ch_existenz",
                issuer="Christian Studer, Bureau für digitale Existenz",
                operator="api.existenz.ch",
                acquisitions=(acq, intermediary_observation, existenz_terms),
                evidence=(
                    EvidenceReference(
                        evidence_id="existenz_api_terms",
                        description="Intermediary API conditions and BAFU credit statement; retained fixture has published archive credential redacted",
                        recording=existenz,
                    ),
                ),
                statements=(
                    SourceStatement(
                        kind="terms",
                        exact_text=EXISTENZ_TERMS,
                        recording_id=existenz.recording_id,
                        fact="source.provider.existenz_terms_statement",
                    ),
                    SourceStatement(
                        kind="citation",
                        exact_text=EXISTENZ_CREDIT,
                        recording_id=existenz.recording_id,
                        fact="source.provider.existenz_citation_statement",
                    ),
                ),
            ),
        ),
        fact_bindings=(
            FactBinding(
                fact_group="bafu_terms_statements",
                facts=("source.provider.bafu_license_statement", "source.provider.bafu_citation_statement"),
                source_id="ch_bafu",
                acquisition_id=bafu_terms.acquisition_id,
            ),
            FactBinding(
                fact_group="bafu_temporal_support_not_identified",
                facts=bafu_temporal_facts,
                source_id="ch_bafu",
                acquisition_id=bafu_temporal_audit.acquisition_id,
            ),
            FactBinding(
                fact_group="existenz_terms_statements",
                facts=("source.provider.existenz_terms_statement", "source.provider.existenz_citation_statement"),
                source_id="ch_existenz",
                acquisition_id=existenz_terms.acquisition_id,
            ),
            FactBinding(
                fact_group="bafu_station_values",
                facts=bafu_catalogue_facts,
                source_id="ch_bafu",
                acquisition_id="existenz_catalogue_capture_2026_08_02",
            ),
            FactBinding(
                fact_group="bafu_product_values",
                facts=bafu_parameter_facts,
                source_id="ch_bafu",
                acquisition_id=parameter_capture.acquisition_id,
            ),
            FactBinding(
                fact_group="bafu_observation_values",
                facts=bafu_observation_facts,
                source_id="ch_bafu",
                acquisition_id=observation_capture.acquisition_id,
            ),
            FactBinding(
                fact_group="existenz_absence",
                facts=intermediary_facts[:2],
                source_id="ch_existenz",
                acquisition_id="existenz_catalogue_capture_2026_08_02",
            ),
            FactBinding(
                fact_group="existenz_transport",
                facts=intermediary_facts[2:],
                source_id="ch_existenz",
                acquisition_id=intermediary_observation.acquisition_id,
            ),
            FactBinding(
                fact_group="canonical_observation_shape",
                facts=canonical_observation_facts,
                source_id=None,
                acquisition_id=None,
                transformation=Transformation(
                    name="BAFU observations to identified RivRetrieve observations",
                    external_inputs=(
                        ExternalFactReference(source_id="ch_bafu", fact="source.observation.value"),
                        ExternalFactReference(source_id="ch_bafu", fact="source.observation.quality"),
                    ),
                ),
            ),
        ),
        fact_universe=bafu_facts
        + intermediary_facts
        + canonical_observation_facts
        + (
            "source.provider.bafu_license_statement",
            "source.provider.bafu_citation_statement",
            "source.provider.existenz_terms_statement",
            "source.provider.existenz_citation_statement",
        ),
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
                ExternalFactReference(source_id="ch_bafu", fact="source.product.temporal_support_not_identified"),
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
