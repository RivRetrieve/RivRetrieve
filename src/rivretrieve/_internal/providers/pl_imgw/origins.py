"""Poland catalogue authority : ∅ → OriginDeclarations × AcquisitionProvenance (pure)."""

from datetime import datetime

from rivretrieve._internal.acquisition_provenance import (
    AbsenceMarkerValue,
    AcquisitionProvenance,
    AcquisitionRecord,
    EvidenceReference,
    ExternalFactReference,
    FactBinding,
    MaterialIdentity,
    NativeTableIdentity,
    PrivateStatementVerification,
    RecordingReference,
    SemanticDigest,
    SourceRecord,
    SourceStatement,
    Transformation,
    WithheldFact,
)
from rivretrieve._internal.catalogue_origins import (
    Authored,
    AuthoredValue,
    Field,
    FloatConversion,
    NativeColumn,
    Withheld,
)
from rivretrieve._internal.catalogues.station_metadata import MetadataField
from rivretrieve._internal.issues import FatalContractError

# Name mappings require genuine-input validation and owner disclosure approval
# before generated metadata can be packaged. Native presence is insufficient.
STATION_METADATA_FIELDS: tuple[MetadataField, ...] = (
    MetadataField(
        "drainage_area",
        "area",
        "square kilometre",
        support_facts=("source.grdc.catchment_area_unit",),
    ),
)

CRS_EVIDENCE_URL = "https://danepubliczne.imgw.pl/pl/apiinfo"
"""Retained IMGW evidence URL; it is not authority for GRDC-issued geometry."""

TERMS_URL = "https://danepubliczne.imgw.pl/regulations"
STATION_CSV_URL = (
    "https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/lista_stacji_hydro.csv"
)

STATION_CATALOGUE_ORIGINS = {
    "provider_id": Authored(AuthoredValue("pl_imgw")),
    "station_id": Field(NativeColumn("gauge_id")),
    "latitude": Field(NativeColumn("latitude"), FloatConversion()),
    "longitude": Field(NativeColumn("longitude"), FloatConversion()),
    "crs": Withheld(),
}

NATIVE_TABLE_SHA256 = "46b162f8f28e31db1a5e3caec1e5ead7f23cd07cfbc5c3975ca5e9af783b76fe"
NATIVE_TABLE_BYTE_SIZE = 49670
NATIVE_TABLE_REVISION = "c9c81934bb1773b0286c968f4fd7323f724c71ac"
NATIVE_TABLE_REPOSITORY_PATH = "src/rivretrieve/_internal/providers/pl_imgw/catalogue/native.parquet"
NATIVE_TABLE_SEMANTIC_SHA256 = "c7fb3582edcc4b66a154d5dac52acd22d2847cd04ed54f5ee94fbf7c8bc6d9ec"

# Public, redacted output of the completed local verification. The private message,
# its headers, and the checked excerpt are deliberately not committed.
FORWARDED_COPY_VERIFICATION = PrivateStatementVerification(
    schema_version=2,
    statement_id="pl_imgw.grdc.inclusion",
    evidence_kind="forwarded_copy",
    limitation="original_byte_identity_not_established",
    evidence_sha256="6ffc840e3a371cc7731fdd587e3d3a3918e47aa73c0e7e1c1251e54494054742",
    evidence_byte_count=228_628,
    workbook_sha256="dfab6ea7de80fb1570f4a8dded8743ed7c7dcb4eb67fe75e2c0e02e9b964b7bf",
    workbook_byte_count=116_301,
    statement_sha256="a95a0e6b9f0f26c87b2d04e02098b3c0dbc24525bdd75b17dfddfa0cd0c443c2",
    decoded_text_plain_occurrence_count=1,
    decoded_text_html_occurrence_count=1,
    verified=True,
)

PROVIDER_FACTS = (
    "provider.provider_id",
    "provider.name",
    "provider.live_stations",
    "provider.live_products",
    "provider.live_station_products",
    "provider.bulk_observations",
    "provider.catalogue_version",
)
PROVIDER_COMPATIBILITY_FACTS = ("provider.license", "provider.citation")
IMGW_STATEMENT_FACTS = ("source.imgw.license_statement", "source.imgw.citation_statement")
PRODUCT_FACTS = (
    "product.provider_id",
    "product.product_id",
    "product.observed_property",
    "product.frequency",
    "product.statistic",
    "product.period_type",
    "product.period_anchor",
    "product.unit",
    "product.native_id",
)
STATION_PRODUCT_FACTS = (
    "station_product.provider_id",
    "station_product.station_id",
    "station_product.product_id",
    "station_product.availability",
    "station_product.availability_reason",
    "station_product.published_record_start_date",
    "station_product.published_record_end_date",
    "station_product.last_catalogue_check",
)
OBSERVATION_FACTS = (
    "source.observation.request",
    "source.observation.response",
    "source.observation.value",
    "source.observation.quality",
)
IMGW_SOURCE_FACTS = (
    "source.imgw.provider_service_identity",
    "source.imgw.observation_archive_product_semantics",
    "source.imgw.station_roster_membership",
    "source.imgw.station_product.availability_not_published",
)
GRDC_NATIVE_FACTS = (
    "native.gauge_id",
    "native.gauge_name",
    "native.river",
    "native.area",
    "native.gauge_altitude",
    "native.latitude",
    "native.longitude",
)
POLAND_FACT_UNIVERSE = (
    *PROVIDER_FACTS,
    *PROVIDER_COMPATIBILITY_FACTS,
    *IMGW_STATEMENT_FACTS,
    *IMGW_SOURCE_FACTS,
    *PRODUCT_FACTS,
    "station.provider_id",
    "station.station_id",
    "station.latitude",
    "station.longitude",
    "station.crs",
    *STATION_PRODUCT_FACTS,
    *OBSERVATION_FACTS,
    *GRDC_NATIVE_FACTS,
    "source.grdc.catchment_area_unit",
    "source.grdc.horizontal_crs",
)


def build_acquisition_provenance(
    private_verification: PrivateStatementVerification | None = None,
) -> AcquisitionProvenance:
    """Build Poland's mixed-source acquisition provenance.

    Parameters
    ----------
    private_verification
        Optional local re-verification result. When supplied, it must equal the
        committed redacted forwarded-copy declaration exactly.

    Returns
    -------
    AcquisitionProvenance
        Closed IMGW and GRDC source records with field-level bindings.

    Raises
    ------
    FatalContractError
        If a supplied re-verification record differs from the committed declaration.
    """
    if private_verification is not None:
        from rivretrieve._internal.private_source_verification import validate_private_email_verification_pin

        private_verification = validate_private_email_verification_pin(private_verification)
        if private_verification != FORWARDED_COPY_VERIFICATION:
            raise FatalContractError("pl_imgw redacted private verification record differs from committed origin")
    private_verification = FORWARDED_COPY_VERIFICATION

    terms = RecordingReference(
        recording_id="pl_imgw_terms_regulations",
        repository_path="tests/test_data/pl_imgw_terms_regulations.html",
        source_url=TERMS_URL,
        retrieved_at=datetime.fromisoformat("2026-08-20T08:47:07Z"),
        media_type="text/html; charset=UTF-8",
        sha256="998edce594f80302054adc06e45f8118a4346ddcc392a5648c7dc9e7347177bf",
    )
    codz = RecordingReference(
        recording_id="pl_imgw_codz_format",
        repository_path="tests/test_data/pl_imgw_annual/CODZ_publiczne_format.txt",
        source_url="https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/dobowe/CODZ_publiczne_format.txt",
        retrieved_at=datetime.fromisoformat("2026-09-20T09:52:00.066902+00:00"),
        media_type="text/plain; charset=windows-1250",
        sha256="d8e7cbbc7680663d99813dd5f9abd793384b2f560600229625bb808ea71ef362",
    )
    yearbook = RecordingReference(
        recording_id="pl_imgw_yearbook_2025",
        repository_path="tests/test_data/pl_imgw_annual/yearbook-2025.pdf",
        source_url="https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/Roczniki/Rocznik%20hydrologiczny/Rocznik%20Hydrologiczny%202025.pdf",
        retrieved_at=datetime.fromisoformat("2026-09-20T09:59:57.031773+00:00"),
        media_type="application/pdf",
        sha256="c2ad75c472ab46363fb149ac5cf982230e2506d7e0b73b8e4eecb6623fa2a916",
    )
    return AcquisitionProvenance(
        schema_version=2,
        provider_id="pl_imgw",
        native_table=NativeTableIdentity(
            repository_path=NATIVE_TABLE_REPOSITORY_PATH,
            revision=NATIVE_TABLE_REVISION,
            sha256=NATIVE_TABLE_SHA256,
            byte_size=NATIVE_TABLE_BYTE_SIZE,
            semantic_digest=SemanticDigest(
                name="pl_imgw.native_table_content_sha256",
                sha256=NATIVE_TABLE_SEMANTIC_SHA256,
            ),
        ),
        fact_universe=POLAND_FACT_UNIVERSE,
        source_records=(
            SourceRecord(
                source_id="sr.pl.imgw",
                issuer="Institute of Meteorology and Water Management – National Research Institute",
                operator="IMGW public-data portal",
                acquisitions=(
                    AcquisitionRecord(
                        acquisition_id="imgw_archive_definitions_2026_09_20",
                        method="http_campaign",
                        instant_type="retrieval_interval",
                        description="CODZ units/daily fields and yearbook station-dependent methods; archive-wide statistics remain unestablished",
                        requested_from=(codz.source_url, yearbook.source_url),
                        retrieved_at_start=codz.retrieved_at,
                        retrieved_at_end=yearbook.retrieved_at,
                        recording_ids=(codz.recording_id, yearbook.recording_id),
                    ),
                    AcquisitionRecord(
                        acquisition_id="imgw_catalogue_routes_2026_08_02",
                        method="http_campaign",
                        instant_type="retrieval_interval",
                        description=(
                            "IMGW public station roster and API documentation establish provider membership and "
                            "the station-product availability statement; the roster contains no geometry"
                        ),
                        requested_from=(STATION_CSV_URL, "https://danepubliczne.imgw.pl/pl/apiinfo"),
                        retrieved_at_start=datetime.fromisoformat("2026-08-02T18:45:32Z"),
                        retrieved_at_end=datetime.fromisoformat("2026-08-02T19:54:27Z"),
                    ),
                    AcquisitionRecord(
                        acquisition_id="imgw_regulations_capture_2026_08_20",
                        method="http_request",
                        instant_type="retrieval",
                        description="IMGW public-data regulations HTML recording",
                        requested_from=(terms.source_url,),
                        retrieved_at_start=terms.retrieved_at,
                        recording_ids=(terms.recording_id,),
                    ),
                    AcquisitionRecord(
                        acquisition_id="imgw_observation_request",
                        method="runtime_http_request",
                        instant_type="runtime",
                        description="Observation archive requests are acquired from IMGW at runtime",
                        requested_from=(
                            "https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/",
                        ),
                    ),
                ),
                evidence=(
                    EvidenceReference(
                        evidence_id="pl_imgw_codz_definition",
                        description="Exact publisher CODZ physical columns and missing-cell definitions",
                        recording=codz,
                    ),
                    EvidenceReference(
                        evidence_id="pl_imgw_yearbook_methods",
                        description="Exact publisher yearbook methods, selected stations only, pp. 7-9",
                        recording=yearbook,
                    ),
                    EvidenceReference(
                        evidence_id="pl_imgw_terms",
                        description="IMGW public-data regulations recording",
                        recording=terms,
                    ),
                ),
                statements=(
                    SourceStatement(
                        kind="license",
                        exact_text=(
                            "Korzystający może używać nieodpłatnie udostępnionych danych do celów prywatnych, "
                            "a w przypadku danych o wysokiej wartości w każdym celu. Jakikolwiek użycie danych "
                            "w celach określonych w § 3 ust. 2 regulaminu wymaga podpisania umowy, która określi "
                            "wysokość kosztów utrzymywania, odbudowy, rozbudowy i przebudowy sieci, systemów i "
                            "biur lub koszty wykonania badań, pomiarów i ocen, jakie ma ponieść odbiorca."
                        ),
                        recording_id=terms.recording_id,
                        fact="source.imgw.license_statement",
                    ),
                    SourceStatement(
                        kind="citation",
                        exact_text=(
                            "Udostępnienie i korzystanie z danych następuje pod warunkiem wskazania źródła "
                            "pochodzenia danych, poprzez umieszczenie przez korzystającego na wszelkiego rodzaju "
                            "pracach lub produktach, opracowanych z użyciem danych IMGW-PIB informacji: „Źródłem "
                            "pochodzenia danych jest Instytut Meteorologii i Gospodarki Wodnej – Państwowy "
                            "Instytut Badawczy”."
                        ),
                        recording_id=terms.recording_id,
                        fact="source.imgw.citation_statement",
                    ),
                ),
            ),
            SourceRecord(
                source_id="sr.pl.grdc",
                issuer="Global Runoff Data Centre",
                operator="Bundesanstalt für Gewässerkunde",
                acquisitions=(
                    AcquisitionRecord(
                        acquisition_id="recovered_upstream_import_f67f6d8",
                        method="repository_recovery",
                        instant_type="provenance_lower_bound",
                        description=(
                            "Recovered station table is raw-byte identical to the upstream materialization; "
                            "the commit instant is a provenance lower bound, not an original receipt instant"
                        ),
                        requested_from=(
                            "https://github.com/kratzert/RivRetrieve-Python/blob/"
                            "f67f6d8507a55144bf235feb3f27f65648b90f83/rivretrieve/cached_site_data/poland_sites.csv",
                        ),
                        retrieved_at_start=datetime.fromisoformat("2025-10-10T18:46:34Z"),
                        material=MaterialIdentity(
                            filename="poland_sites.csv",
                            byte_count=111941,
                            sha256="8c4cdd675c2811cd3b91a5889cbcd4273830c2fa4ee90ad6142c69ba7a198f49",
                        ),
                    ),
                    AcquisitionRecord(
                        acquisition_id="grdc_workbook_corroboration_private_receipt",
                        method="corroborating_receipt",
                        instant_type="private_redacted_corroborating_receipt",
                        description=(
                            "Later GRDC workbook receipt corroborates every recovered field but is not "
                            "established as the historical acquisition that produced the recovered import. "
                            "Its header Catchment area (square kilometre) establishes the existing area field unit"
                        ),
                        requested_from=("private://grdc-bfg/correspondence",),
                        material=MaterialIdentity(
                            filename="Metadata_GRDC_30.10.2025.xlsx",
                            byte_count=116301,
                            sha256="dfab6ea7de80fb1570f4a8dded8743ed7c7dcb4eb67fe75e2c0e02e9b964b7bf",
                        ),
                    ),
                ),
                statements=(
                    SourceStatement(
                        kind="access",
                        verification_status="verified_private_forwarded_copy",
                        private_verification=private_verification,
                    ),
                ),
            ),
        ),
        fact_bindings=(
            FactBinding(
                fact_group="imgw_archive_physics",
                facts=(IMGW_SOURCE_FACTS[1],),
                source_id="sr.pl.imgw",
                acquisition_id="imgw_archive_definitions_2026_09_20",
            ),
            FactBinding(
                fact_group="imgw_catalogue_inputs",
                facts=tuple(fact for fact in IMGW_SOURCE_FACTS if fact != IMGW_SOURCE_FACTS[1]),
                source_id="sr.pl.imgw",
                acquisition_id="imgw_catalogue_routes_2026_08_02",
            ),
            FactBinding(
                fact_group="imgw_source_statements",
                facts=IMGW_STATEMENT_FACTS,
                source_id="sr.pl.imgw",
                acquisition_id="imgw_regulations_capture_2026_08_20",
            ),
            FactBinding(
                fact_group="grdc_catchment_area_unit",
                facts=("source.grdc.catchment_area_unit",),
                source_id="sr.pl.grdc",
                acquisition_id="grdc_workbook_corroboration_private_receipt",
            ),
            FactBinding(
                fact_group="grdc_native_station_fields",
                facts=GRDC_NATIVE_FACTS,
                source_id="sr.pl.grdc",
                acquisition_id="recovered_upstream_import_f67f6d8",
            ),
            FactBinding(
                fact_group="rivretrieve_provider_catalogue",
                facts=PROVIDER_FACTS,
                source_id=None,
                acquisition_id=None,
                transformation=Transformation(
                    name="IMGW service identity to RivRetrieve provider carrier",
                    external_inputs=(
                        ExternalFactReference(source_id="sr.pl.imgw", fact=IMGW_SOURCE_FACTS[0]),
                        ExternalFactReference(source_id="sr.pl.imgw", fact=IMGW_SOURCE_FACTS[1]),
                    ),
                ),
            ),
            FactBinding(
                fact_group="rivretrieve_provider_terms_compatibility",
                facts=PROVIDER_COMPATIBILITY_FACTS,
                source_id=None,
                acquisition_id=None,
                transformation=Transformation(
                    name="RivRetrieve null marker for unsafe singular mixed-source terms fields",
                    kind="absence_marker",
                    marker_value=AbsenceMarkerValue.NULL,
                    external_inputs=(
                        ExternalFactReference(source_id="sr.pl.imgw", fact="source.imgw.license_statement"),
                        ExternalFactReference(source_id="sr.pl.imgw", fact="source.imgw.citation_statement"),
                        ExternalFactReference(source_id="sr.pl.grdc", fact="native.gauge_id"),
                    ),
                ),
            ),
            FactBinding(
                fact_group="rivretrieve_product_catalogue",
                facts=PRODUCT_FACTS,
                source_id=None,
                acquisition_id=None,
                transformation=Transformation(
                    name="IMGW archive semantics to RivRetrieve product carrier",
                    external_inputs=(ExternalFactReference(source_id="sr.pl.imgw", fact=IMGW_SOURCE_FACTS[1]),),
                ),
            ),
            FactBinding(
                fact_group="rivretrieve_station_catalogue",
                facts=("station.provider_id", "station.station_id", "station.latitude", "station.longitude"),
                source_id=None,
                acquisition_id=None,
                transformation=Transformation(
                    name="IMGW roster and GRDC native fields to RivRetrieve station carrier",
                    external_inputs=(
                        ExternalFactReference(source_id="sr.pl.imgw", fact=IMGW_SOURCE_FACTS[2]),
                        ExternalFactReference(source_id="sr.pl.grdc", fact="native.gauge_id"),
                        ExternalFactReference(source_id="sr.pl.grdc", fact="native.latitude"),
                        ExternalFactReference(source_id="sr.pl.grdc", fact="native.longitude"),
                    ),
                ),
            ),
            FactBinding(
                fact_group="rivretrieve_crs_knowledge_state",
                facts=("station.crs",),
                source_id=None,
                acquisition_id=None,
                transformation=Transformation(
                    name="RivRetrieve unknown marker for an unestablished source horizontal CRS",
                    kind="absence_marker",
                    marker_value=AbsenceMarkerValue.UNKNOWN,
                    external_inputs=(ExternalFactReference(source_id="sr.pl.grdc", fact="source.grdc.horizontal_crs"),),
                ),
            ),
            FactBinding(
                fact_group="rivretrieve_station_product_catalogue",
                facts=STATION_PRODUCT_FACTS,
                source_id=None,
                acquisition_id=None,
                transformation=Transformation(
                    name="IMGW and GRDC inputs to RivRetrieve station-product carrier",
                    external_inputs=(
                        ExternalFactReference(source_id="sr.pl.imgw", fact=IMGW_SOURCE_FACTS[1]),
                        ExternalFactReference(source_id="sr.pl.imgw", fact=IMGW_SOURCE_FACTS[2]),
                        ExternalFactReference(source_id="sr.pl.imgw", fact=IMGW_SOURCE_FACTS[3]),
                        ExternalFactReference(source_id="sr.pl.grdc", fact="native.gauge_id"),
                    ),
                ),
            ),
            FactBinding(
                fact_group="imgw_observation_acquisition",
                facts=OBSERVATION_FACTS,
                source_id="sr.pl.imgw",
                acquisition_id="imgw_observation_request",
            ),
        ),
        withheld_facts=(
            WithheldFact(
                fact_group="grdc_horizontal_crs",
                facts=("source.grdc.horizontal_crs",),
                reason="no_acquisition_record_established",
                source_id="sr.pl.grdc",
            ),
        ),
    )


# Existing acquisition facts materialised in the retained native table.
# This declares derived-input support, not preservation of original responses.
NATIVE_TABLE_ACQUISITION_IDS = ("recovered_upstream_import_f67f6d8",)


# Authored catalogue, physical-fact and support declarations selected at build time.
CATALOGUE_BUILD_DECLARATIONS = (
    ("maintenance/catalogue/station_metadata/review.json", None),
    ("src/rivretrieve/_internal/providers/pl_imgw/origins.py", "build_acquisition_provenance"),
    ("src/rivretrieve/_internal/providers/pl_imgw/origins.py", "NATIVE_TABLE_ACQUISITION_IDS"),
    ("src/rivretrieve/_internal/providers/pl_imgw/origins.py", "CATALOGUE_SUPPORTING_INPUTS"),
    ("src/rivretrieve/_internal/providers/pl_imgw/origins.py", "STATION_METADATA_FIELDS"),
    ("src/rivretrieve/_internal/providers/pl_imgw/generate_catalogue.py", "build_catalogue"),
    ("src/rivretrieve/_internal/assembly.py", "assemble"),
    ("src/rivretrieve/_internal/providers/pl_imgw/config.py", "config"),
    ("src/rivretrieve/_internal/providers/pl_imgw/catalogue_series.py", "describe_catalogue"),
)


# Additional retained declarations used by these source facts; not original-body claims.
CATALOGUE_SUPPORTING_INPUTS = {
    "source.grdc.catchment_area_unit": (
        "maintenance/catalogue/station_metadata/sources/pl_imgw/grdc-workbook/Metadata_GRDC_30.10.2025.xlsx",
    ),
}
