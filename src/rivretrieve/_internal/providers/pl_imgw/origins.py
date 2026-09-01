"""Poland catalogue authority : ∅ → OriginDeclarations × AcquisitionProvenance (pure)."""

from datetime import datetime

from rivretrieve._internal.acquisition_provenance import (
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
from rivretrieve._internal.catalogue_origins import Field, NativeColumn, Withheld

CRS_EVIDENCE_URL = "https://danepubliczne.imgw.pl/pl/apiinfo"
"""Retained IMGW evidence URL; it is not authority for GRDC-issued geometry."""

TERMS_URL = "https://danepubliczne.imgw.pl/regulations"
STATION_CSV_URL = (
    "https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/lista_stacji_hydro.csv"
)

STATION_CATALOGUE_ORIGINS = {
    "provider_id": Field(NativeColumn("gauge_id")),
    "station_id": Field(NativeColumn("gauge_id")),
    "latitude": Field(NativeColumn("latitude")),
    "longitude": Field(NativeColumn("longitude")),
    "crs": Withheld(),
}

NATIVE_TABLE_SHA256 = "46b162f8f28e31db1a5e3caec1e5ead7f23cd07cfbc5c3975ca5e9af783b76fe"
NATIVE_TABLE_REVISION = "c9c81934bb1773b0286c968f4fd7323f724c71ac"
NATIVE_TABLE_REPOSITORY_PATH = "src/rivretrieve/_internal/providers/pl_imgw/catalogue/native.parquet"
NATIVE_TABLE_SEMANTIC_SHA256 = "c7fb3582edcc4b66a154d5dac52acd22d2847cd04ed54f5ee94fbf7c8bc6d9ec"

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
    "observation.request",
    "observation.response",
    "observation.value",
    "observation.quality",
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
    *PRODUCT_FACTS,
    "station.provider_id",
    "station.station_id",
    "station.latitude",
    "station.longitude",
    "station.crs",
    *STATION_PRODUCT_FACTS,
    *OBSERVATION_FACTS,
    *GRDC_NATIVE_FACTS,
    "source.grdc.horizontal_crs",
)


def build_acquisition_provenance(
    private_verification: PrivateStatementVerification | None = None,
) -> AcquisitionProvenance:
    """Build Poland's mixed-source acquisition provenance.

    Returns
    -------
    AcquisitionProvenance
        Closed IMGW and GRDC source records with field-level bindings.
    """
    terms = RecordingReference(
        recording_id="pl_imgw_terms_regulations",
        repository_path="tests/test_data/pl_imgw_terms_regulations.html",
        source_url=TERMS_URL,
        retrieved_at=datetime.fromisoformat("2026-08-20T08:47:07Z"),
        media_type="text/html; charset=UTF-8",
        sha256="998edce594f80302054adc06e45f8118a4346ddcc392a5648c7dc9e7347177bf",
    )
    return AcquisitionProvenance(
        schema_version=2,
        provider_id="pl_imgw",
        native_table=NativeTableIdentity(
            repository_path=NATIVE_TABLE_REPOSITORY_PATH,
            revision=NATIVE_TABLE_REVISION,
            sha256=NATIVE_TABLE_SHA256,
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
                        acquisition_id="grdc_workbook_corroboration_2025_11_07",
                        method="corroborating_receipt",
                        instant_type="corroborating_receipt",
                        description=(
                            "Later GRDC workbook receipt corroborates every recovered field but is not "
                            "established as the historical acquisition that produced the recovered import"
                        ),
                        requested_from=("private correspondence from GRDC/BfG",),
                        retrieved_at_start=datetime.fromisoformat("2025-11-07T12:40:38Z"),
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
                        exact_text=(
                            "I just wanted to send you the metadata for all stations of Poland.\n\n"
                            "Feel free to include them!"
                        ),
                        verification_status=(
                            "verified_private_original"
                            if private_verification is not None
                            else "unverified_private_original_required"
                        ),
                        private_verification=private_verification,
                    ),
                ),
            ),
        ),
        fact_bindings=(
            FactBinding(
                fact_group="imgw_provider_catalogue",
                facts=PROVIDER_FACTS,
                source_id="sr.pl.imgw",
                acquisition_id="imgw_catalogue_routes_2026_08_02",
            ),
            FactBinding(
                fact_group="imgw_source_statements",
                facts=IMGW_STATEMENT_FACTS,
                source_id="sr.pl.imgw",
                acquisition_id="imgw_catalogue_routes_2026_08_02",
            ),
            FactBinding(
                fact_group="rivretrieve_provider_terms_compatibility",
                facts=PROVIDER_COMPATIBILITY_FACTS,
                source_id=None,
                acquisition_id=None,
                transformation=Transformation(
                    name="RivRetrieve null marker for unsafe singular mixed-source terms fields",
                    external_inputs=(
                        ExternalFactReference(
                            source_id="sr.pl.imgw",
                            fact="source.imgw.license_statement",
                        ),
                        ExternalFactReference(
                            source_id="sr.pl.imgw",
                            fact="source.imgw.citation_statement",
                        ),
                        ExternalFactReference(
                            source_id="sr.pl.grdc",
                            fact="native.gauge_id",
                        ),
                    ),
                ),
            ),
            FactBinding(
                fact_group="imgw_product_catalogue",
                facts=PRODUCT_FACTS,
                source_id="sr.pl.imgw",
                acquisition_id="imgw_catalogue_routes_2026_08_02",
            ),
            FactBinding(
                fact_group="imgw_station_membership",
                facts=("station.provider_id",),
                source_id="sr.pl.imgw",
                acquisition_id="imgw_catalogue_routes_2026_08_02",
            ),
            FactBinding(
                fact_group="grdc_station_catalogue",
                facts=("station.station_id", "station.latitude", "station.longitude", *GRDC_NATIVE_FACTS),
                source_id="sr.pl.grdc",
                acquisition_id="recovered_upstream_import_f67f6d8",
            ),
            FactBinding(
                fact_group="rivretrieve_crs_knowledge_state",
                facts=("station.crs",),
                source_id=None,
                acquisition_id=None,
                transformation=Transformation(
                    name="RivRetrieve unknown marker for an unestablished source horizontal CRS",
                    external_inputs=(
                        ExternalFactReference(
                            source_id="sr.pl.grdc",
                            fact="source.grdc.horizontal_crs",
                        ),
                    ),
                ),
            ),
            FactBinding(
                fact_group="imgw_station_product_catalogue",
                facts=STATION_PRODUCT_FACTS,
                source_id="sr.pl.imgw",
                acquisition_id="imgw_catalogue_routes_2026_08_02",
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
