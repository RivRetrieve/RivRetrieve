"""Lithuania authority : ∅ → OriginDeclarations × AcquisitionProvenance (pure)."""

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
    SourceRecord,
    SourceStatement,
    Transformation,
    complete_transformed_fact_universe,
)
from rivretrieve._internal.catalogues.artifact import CATALOGUE_FACT_UNIVERSE

STATION_CATALOGUE_ORIGINS: dict[str, catalogue_origins.CatalogueOrigin] = {
    "provider_id": catalogue_origins.Authored(catalogue_origins.AuthoredValue("lt_lhmt")),
    "station_id": catalogue_origins.Field(catalogue_origins.NativeColumn("code")),
    "latitude": catalogue_origins.Field(
        catalogue_origins.NativeColumn("coordinates"), catalogue_origins.StructMemberConversion()
    ),
    "longitude": catalogue_origins.Field(
        catalogue_origins.NativeColumn("coordinates"), catalogue_origins.StructMemberConversion()
    ),
    "crs": catalogue_origins.Documented(
        catalogue_origins.DocumentedValue("EPSG:4326"),
        catalogue_origins.Evidence("https://api.meteo.lt/"),
    ),
}


NATIVE_TABLE_SHA256 = "f1ddebed42b911d1417f22e22abebc5904652db4d5fc6da0bd0bed666d321b8d"
NATIVE_TABLE_BYTE_SIZE = 6156
NATIVE_TABLE_REVISION = "7b71c51715f92085ea5d83c9e862c2b67d0b742e"
NATIVE_TABLE_REPOSITORY_PATH = "src/rivretrieve/_internal/providers/lt_lhmt/catalogue/native.parquet"
_TERMS_FILE = "lt_lhmt_terms_licence.html"
_TERMS_SHA256 = "bf8f893026a8c744136818d47da37e8c7b231b891c74c85e0f6192ac4a8d8645"
_LICENSE = "Per Meteo LT API teikiami duomenys (toliau – duomenys) yra viešai prieinami ir nemokami visuomeniniam naudojimui, platinimui ir tolimesniam apdorojimui, laikantis šių duomenų naudojimo sąlygų: 1) duomenys, jeigu nenustatyta kitaip, teikiami pagal Creative Commons Attribution-ShareAlike 4.0 (CC BY-SA 4.0) tarptautinę duomenų naudojimo licenciją, būtina susipažinti su licencijos sąlygomis;"
_CITATION = "5) publikuojant, pakartotinai atkartojant ar kitaip naudojant duomenis, būtina nurodyti, kad duomenų šaltinis yra Tarnyba. Nenurodant duomenų šaltinio, gali būti nutraukta prieiga prie duomenų."


def _build_provider_acquisition_provenance() -> AcquisitionProvenance:
    """Build Lithuania's acquisition provenance without performing IO."""
    recording = RecordingReference(
        recording_id="lt_lhmt_terms",
        repository_path=f"tests/test_data/{_TERMS_FILE}",
        source_url="https://api.meteo.lt/",
        retrieved_at=datetime.fromisoformat("2026-08-21T08:27:13Z"),
        media_type="text/html; charset=UTF-8",
        sha256=_TERMS_SHA256,
    )
    external = (
        "source.provider.service",
        "source.product.native_fields",
        "source.station.native_identity",
        "source.station.native_location",
        "source.station.crs_documentation",
        "source.station_product.availability_not_published",
        "source.product.historical_daily_mean_semantics",
        "source.product.historical_time_zone",
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
        provider_id="lt_lhmt",
        native_table=NativeTableIdentity(
            repository_path=NATIVE_TABLE_REPOSITORY_PATH,
            revision=NATIVE_TABLE_REVISION,
            sha256=NATIVE_TABLE_SHA256,
            byte_size=NATIVE_TABLE_BYTE_SIZE,
        ),
        source_records=(
            SourceRecord(
                source_id="lt_lhmt",
                issuer="Lithuanian Hydrometeorological Service",
                operator="Meteo LT API",
                acquisitions=(
                    AcquisitionRecord(
                        acquisition_id="catalogue_capture_2026_08_01",
                        method="http_request",
                        instant_type="retrieval",
                        description="Complete 97-station Meteo LT hydro-stations response",
                        requested_from=("https://api.meteo.lt/v1/hydro-stations",),
                        retrieved_at_start=datetime.fromisoformat("2026-08-01T18:31:08Z"),
                    ),
                    AcquisitionRecord(
                        acquisition_id="terms_capture_2026_08_21",
                        method="http_request",
                        instant_type="retrieval",
                        description="Meteo LT API documentation and data-use conditions HTML recording",
                        requested_from=(recording.source_url,),
                        retrieved_at_start=recording.retrieved_at,
                        recording_ids=(recording.recording_id,),
                    ),
                    AcquisitionRecord(
                        acquisition_id="observation_request",
                        method="runtime_http_request",
                        instant_type="runtime",
                        description="Exact monthly Meteo LT station observation response",
                        requested_from=(
                            "https://api.meteo.lt/v1/hydro-stations/{station}/observations/historical/{YYYY-MM}",
                        ),
                    ),
                ),
                evidence=(
                    EvidenceReference(
                        evidence_id="lt_lhmt_terms",
                        description=(
                            "Meteo LT API documentation and data-use conditions: historical observations "
                            "waterLevel (cm) and waterDischarge (m3/s), Vidurkis per parą; "
                            "observationDateUtc (UTC laiko juosta); coordinates (WGS 84)"
                        ),
                        recording=recording,
                    ),
                ),
                statements=(
                    SourceStatement(
                        kind="license",
                        exact_text=_LICENSE,
                        recording_id=recording.recording_id,
                        fact="source.meteo_lt.license_statement",
                    ),
                    SourceStatement(
                        kind="citation",
                        exact_text=_CITATION,
                        recording_id=recording.recording_id,
                        fact="source.meteo_lt.citation_statement",
                    ),
                ),
            ),
        ),
        fact_bindings=(
            FactBinding(
                fact_group="terms_statements",
                facts=("source.meteo_lt.license_statement", "source.meteo_lt.citation_statement"),
                source_id="lt_lhmt",
                acquisition_id="terms_capture_2026_08_21",
            ),
            FactBinding(
                fact_group="catalogue_external",
                facts=(external[0], external[2], external[3], external[5]),
                source_id="lt_lhmt",
                acquisition_id="catalogue_capture_2026_08_01",
            ),
            FactBinding(
                fact_group="api_documented_semantics",
                facts=(external[1], external[4], external[6], external[7]),
                source_id="lt_lhmt",
                acquisition_id="terms_capture_2026_08_21",
            ),
            FactBinding(
                fact_group="observation_external",
                facts=external[-2:],
                source_id="lt_lhmt",
                acquisition_id="observation_request",
            ),
            FactBinding(
                fact_group="canonical_catalogue",
                facts=canonical[:-1],
                source_id=None,
                acquisition_id=None,
                transformation=Transformation(
                    name="rivretrieve_lithuania_catalogue_harmonisation",
                    external_inputs=tuple(
                        ExternalFactReference(source_id="lt_lhmt", fact=fact) for fact in external[:-2]
                    ),
                ),
            ),
            FactBinding(
                fact_group="canonical_observation",
                facts=canonical[-1:],
                source_id=None,
                acquisition_id=None,
                transformation=Transformation(
                    name="rivretrieve_lithuania_observation_harmonisation",
                    external_inputs=tuple(
                        ExternalFactReference(source_id="lt_lhmt", fact=fact) for fact in external[-2:]
                    ),
                ),
            ),
        ),
        fact_universe=external
        + canonical
        + ("source.meteo_lt.license_statement", "source.meteo_lt.citation_statement"),
    )


def _complete_catalogue_carrier(provenance: AcquisitionProvenance) -> AcquisitionProvenance:
    return complete_transformed_fact_universe(
        provenance,
        CATALOGUE_FACT_UNIVERSE,
        transformation=Transformation(
            name="lt_lhmt external facts to RivRetrieve canonical catalogue carriers",
            external_inputs=(
                ExternalFactReference(source_id="lt_lhmt", fact="source.provider.service"),
                ExternalFactReference(source_id="lt_lhmt", fact="source.product.native_fields"),
                ExternalFactReference(source_id="lt_lhmt", fact="source.product.historical_daily_mean_semantics"),
                ExternalFactReference(source_id="lt_lhmt", fact="source.product.historical_time_zone"),
                ExternalFactReference(source_id="lt_lhmt", fact="source.station.native_identity"),
                ExternalFactReference(source_id="lt_lhmt", fact="source.station.native_location"),
                ExternalFactReference(source_id="lt_lhmt", fact="source.station.crs_documentation"),
                ExternalFactReference(source_id="lt_lhmt", fact="source.station_product.availability_not_published"),
            ),
        ),
    )


def build_acquisition_provenance() -> AcquisitionProvenance:
    """Build closed lt_lhmt acquisition provenance."""
    return _complete_catalogue_carrier(_build_provider_acquisition_provenance())
