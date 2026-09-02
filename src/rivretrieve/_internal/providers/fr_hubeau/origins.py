"""France authority : ∅ → EndpointOrigins × AcquisitionProvenance (pure)."""

from datetime import datetime
from types import MappingProxyType

from rivretrieve._internal import catalogue_origins
from rivretrieve._internal.acquisition_provenance import (
    AcquisitionProvenance,
    AcquisitionRecord,
    CatalogueRowLocator,
    EvidenceReference,
    ExternalFactReference,
    FactBinding,
    NativeTableIdentity,
    RecordingReference,
    SemanticDigest,
    SourceRecord,
    SourceStatement,
    Transformation,
    WithheldFact,
    complete_transformed_fact_universe,
)
from rivretrieve._internal.catalogues.artifact import CATALOGUE_FACT_UNIVERSE

CRS_EVIDENCE_URL = (
    "https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/stations?code_station=1011000101&format=geojson"
)
TEMPERATURE_CRS_EVIDENCE_URL = "https://hubeau.eaufrance.fr/api/v1/temperature/station?size=2000&format=json"

HYDROMETRY_STATION_CATALOGUE_ORIGINS: dict[str, catalogue_origins.CatalogueOrigin] = {
    "provider_id": catalogue_origins.Field(catalogue_origins.NativeColumn("code_station")),
    "station_id": catalogue_origins.Field(catalogue_origins.NativeColumn("code_station")),
    "latitude": catalogue_origins.Field(catalogue_origins.NativeColumn("latitude_station")),
    "longitude": catalogue_origins.Field(catalogue_origins.NativeColumn("longitude_station")),
    "crs": catalogue_origins.Documented(
        catalogue_origins.DocumentedValue("EPSG:4326"),
        catalogue_origins.Evidence(CRS_EVIDENCE_URL),
    ),
}

TEMPERATURE_STATION_CATALOGUE_ORIGINS: dict[str, catalogue_origins.CatalogueOrigin] = {
    "provider_id": catalogue_origins.Field(catalogue_origins.NativeColumn("code_station")),
    "station_id": catalogue_origins.Field(catalogue_origins.NativeColumn("code_station")),
    "latitude": catalogue_origins.Field(catalogue_origins.NativeColumn("latitude")),
    "longitude": catalogue_origins.Field(catalogue_origins.NativeColumn("longitude")),
    "crs": catalogue_origins.Documented(
        catalogue_origins.DocumentedValue("EPSG:4326"),
        catalogue_origins.Evidence(TEMPERATURE_CRS_EVIDENCE_URL),
    ),
}

FRANCE_ORIGIN_DECLARATIONS = MappingProxyType(
    {
        "hydrometrie/referentiel/stations": HYDROMETRY_STATION_CATALOGUE_ORIGINS,
        "temperature/station": TEMPERATURE_STATION_CATALOGUE_ORIGINS,
    }
)

CODE_PROJECTION_31_AXIS_TRANSPOSITION = MappingProxyType(
    {"latitude": "longitude_station", "longitude": "latitude_station"}
)
CODE_PROJECTION_31_METROPOLITAN_BOUNDS = MappingProxyType(
    {"latitude": (42.4174, 49.989435), "longitude": (-0.616424, 5.593353)}
)


NATIVE_TABLE_SHA256 = "4ff9439d0abd7f479d17b2c608d923d7834ea3df084ed08a3af9cec1d35ab687"
NATIVE_TABLE_BYTE_SIZE = 1049930
NATIVE_TABLE_REVISION = "5dc8e480e426babe109c0467c5e0c374f92239c3"
NATIVE_TABLE_REPOSITORY_PATH = "src/rivretrieve/_internal/providers/fr_hubeau/catalogue/native.parquet"
NATIVE_TABLE_SEMANTIC_SHA256 = "f5c3d84a4e6674a1aa5e6b951576edf6bcbdf77867ab0e5c3ffe2f09adbf7322"
_TERMS_FILE = "fr_hubeau_terms_licence.html"
_TERMS_SHA256 = "82ff424acd31cdff38df4307bb8e8674d2cdc82659c99b4a117455cacd8d19cc"
_LICENSE = "La réutilisation des Jeux de données est régie par la licence ouverte Etalab, https://www.etalab.gouv.fr/licence-ouverte-open-licence. Les Jeux de données sont donc librement et gratuitement utilisables et réutilisables, y compris dans un but commercial."
_CITATION = "L'utilisateur de ces données doit néanmoins veiller à citer l'auteur des Jeux de données."


def _build_provider_acquisition_provenance(
    *,
    station_ids: tuple[str, ...],
    station_product_keys: tuple[tuple[str, str], ...],
) -> AcquisitionProvenance:
    """Build France provenance, withholding facts with no established SIE issuer."""
    if len(station_ids) != 7323 or len(set(station_ids)) != 7323:
        raise ValueError("France provenance requires exactly 7,323 unique station identifiers")
    if len(station_product_keys) != 33139 or len(set(station_product_keys)) != 33139:
        raise ValueError("France provenance requires exactly 33,139 unique station-product keys")
    recording = RecordingReference(
        recording_id="fr_hubeau_terms",
        repository_path=f"tests/test_data/{_TERMS_FILE}",
        source_url="https://hubeau.eaufrance.fr/page/conditions-generales",
        retrieved_at=datetime.fromisoformat("2026-08-20T15:39:10Z"),
        media_type="text/html; charset=UTF-8",
        sha256=_TERMS_SHA256,
    )
    external = (
        "source.provider.platform",
        "source.product.hydrometry_api_semantics",
        "source.product.temperature_api_semantics",
        "source.observation.transport",
    )
    canonical = (
        "canonical.provider_id",
        "canonical.product_identity",
        "canonical.product_unit",
        "canonical.product_period",
    )
    station_facts = tuple(f"source.station.{station_id}.identity_location_crs" for station_id in station_ids)
    observation_facts = tuple(f"source.observation.{station_id}.values_quality" for station_id in station_ids)
    availability_facts = tuple(
        f"station_product.{station_id}.{product_id}.availability" for station_id, product_id in station_product_keys
    )
    withheld_stations = tuple(
        WithheldFact(
            fact_group=f"withheld_station:{station_id}",
            facts=(fact,),
            reason="no_acquisition_record_established",
            catalogue_rows=(CatalogueRowLocator(carrier="station", station_id=station_id),),
        )
        for station_id, fact in zip(station_ids, station_facts, strict=True)
    )
    withheld_observations = tuple(
        WithheldFact(
            fact_group=f"withheld_observation:{station_id}",
            facts=(fact,),
            reason="no_acquisition_record_established",
        )
        for station_id, fact in zip(station_ids, observation_facts, strict=True)
    )
    withheld_availability = tuple(
        WithheldFact(
            fact_group=f"withheld_availability:{station_id}:{product_id}",
            facts=(fact,),
            reason="no_acquisition_record_established",
            catalogue_rows=(
                CatalogueRowLocator(carrier="station_product", station_id=station_id, product_id=product_id),
            ),
        )
        for (station_id, product_id), fact in zip(station_product_keys, availability_facts, strict=True)
    )
    withheld = withheld_stations + withheld_observations + withheld_availability
    return AcquisitionProvenance(
        schema_version=2,
        provider_id="fr_hubeau",
        native_table=NativeTableIdentity(
            repository_path=NATIVE_TABLE_REPOSITORY_PATH,
            revision=NATIVE_TABLE_REVISION,
            sha256=NATIVE_TABLE_SHA256,
            byte_size=NATIVE_TABLE_BYTE_SIZE,
            semantic_digest=SemanticDigest(
                name="fr_hubeau.native_table_content_sha256", sha256=NATIVE_TABLE_SEMANTIC_SHA256
            ),
        ),
        source_records=(
            SourceRecord(
                source_id="fr_hubeau",
                issuer="Hub’Eau / SCHAPI",
                operator="Hub’Eau platform",
                acquisitions=(
                    AcquisitionRecord(
                        acquisition_id="hydrometry_catalogue_capture_2026_08_02",
                        method="http_campaign",
                        instant_type="retrieval",
                        description="Seven complete Hub’Eau hydrometry referential pages, 6,454 rows",
                        requested_from=tuple(
                            f"https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/stations?size=1000&page={page}&format=json"
                            for page in range(1, 8)
                        ),
                        retrieved_at_start=datetime.fromisoformat("2026-08-02T17:32:58Z"),
                    ),
                    AcquisitionRecord(
                        acquisition_id="temperature_catalogue_capture_2026_08_02",
                        method="http_request",
                        instant_type="retrieval",
                        description="Complete Hub’Eau temperature station response, 869 rows",
                        requested_from=(
                            "https://hubeau.eaufrance.fr/api/v1/temperature/station?size=2000&format=json",
                        ),
                        retrieved_at_start=datetime.fromisoformat("2026-08-02T17:33:34Z"),
                    ),
                    AcquisitionRecord(
                        acquisition_id="general_conditions_capture_2026_08_20",
                        method="http_request",
                        instant_type="retrieval",
                        description="Hub’Eau general conditions section 5.1.3 HTML recording",
                        requested_from=(recording.source_url,),
                        retrieved_at_start=recording.retrieved_at,
                        recording_ids=(recording.recording_id,),
                    ),
                    AcquisitionRecord(
                        acquisition_id="observation_transport",
                        method="runtime_http_request",
                        instant_type="runtime",
                        description="Exact Hub'Eau API route response; dataset values remain withheld until the producing SIE actor is established",
                        requested_from=("https://hubeau.eaufrance.fr/api/",),
                    ),
                ),
                evidence=(
                    EvidenceReference(
                        evidence_id="fr_hubeau_terms",
                        description="Hub'Eau general conditions section 5.1.3",
                        recording=recording,
                    ),
                ),
                statements=(
                    SourceStatement(
                        kind="license",
                        exact_text=_LICENSE,
                        recording_id=recording.recording_id,
                        fact="source.hubeau.license_statement",
                    ),
                    SourceStatement(
                        kind="citation",
                        exact_text=_CITATION,
                        recording_id=recording.recording_id,
                        fact="source.hubeau.citation_statement",
                    ),
                ),
            ),
        ),
        fact_bindings=(
            FactBinding(
                fact_group="terms_statements",
                facts=("source.hubeau.license_statement", "source.hubeau.citation_statement"),
                source_id="fr_hubeau",
                acquisition_id="general_conditions_capture_2026_08_20",
            ),
            FactBinding(
                fact_group="hydrometry_platform_and_product_external",
                facts=external[:2],
                source_id="fr_hubeau",
                acquisition_id="hydrometry_catalogue_capture_2026_08_02",
            ),
            FactBinding(
                fact_group="temperature_product_external",
                facts=external[2:3],
                source_id="fr_hubeau",
                acquisition_id="temperature_catalogue_capture_2026_08_02",
            ),
            FactBinding(
                fact_group="observation_transport",
                facts=external[3:],
                source_id="fr_hubeau",
                acquisition_id="observation_transport",
            ),
            FactBinding(
                fact_group="canonical_platform_product",
                facts=canonical,
                source_id=None,
                acquisition_id=None,
                transformation=Transformation(
                    name="rivretrieve_france_platform_product_harmonisation",
                    external_inputs=tuple(
                        ExternalFactReference(source_id="fr_hubeau", fact=fact) for fact in external[:3]
                    ),
                ),
            ),
        ),
        fact_universe=external
        + canonical
        + station_facts
        + observation_facts
        + availability_facts
        + ("source.hubeau.license_statement", "source.hubeau.citation_statement"),
        withheld_facts=withheld,
    )


def _complete_catalogue_carrier(provenance: AcquisitionProvenance) -> AcquisitionProvenance:
    return complete_transformed_fact_universe(
        provenance,
        CATALOGUE_FACT_UNIVERSE,
        transformation=Transformation(
            name="fr_hubeau external facts to RivRetrieve canonical catalogue carriers",
            external_inputs=(
                ExternalFactReference(source_id="fr_hubeau", fact="source.provider.platform"),
                ExternalFactReference(source_id="fr_hubeau", fact="source.product.hydrometry_api_semantics"),
                ExternalFactReference(source_id="fr_hubeau", fact="source.product.temperature_api_semantics"),
            ),
        ),
    )


def build_acquisition_provenance(
    *,
    station_ids: tuple[str, ...],
    station_product_keys: tuple[tuple[str, str], ...],
) -> AcquisitionProvenance:
    """Build closed France provenance for the generated catalogue population."""
    return _complete_catalogue_carrier(
        _build_provider_acquisition_provenance(
            station_ids=station_ids,
            station_product_keys=station_product_keys,
        )
    )
