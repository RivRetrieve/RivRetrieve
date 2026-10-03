"""France authority : NativeStationPartitions × FranceAvailability → AcquisitionProvenance (pure)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from types import MappingProxyType
from typing import TYPE_CHECKING

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
    "Station metadata distributed by Hub’Eau through its hydrometry and river-temperature services "
    "(https://hubeau.eaufrance.fr/), used under the Etalab Open Licence "
    "(https://www.etalab.gouv.fr/licence-ouverte-open-licence). Hub’Eau distributes data from several "
    "producers; its role does not establish the original producer of every record. Source acquisition "
    "identities and dates remain in the catalogue provenance; acquisition dates are not asserted to be "
    "publisher last-update dates. RivRetrieve selected the declared source fields and encoded their "
    "values and absence states; source names remain unchanged. Processing and publication of this "
    "projection: RivRetrieve."
)

STATION_METADATA_FIELDS: tuple[MetadataField, ...] = (
    MetadataField("drainage_area", "superficie_topo"),
    MetadataField("drainage_area", "superficie_reelle"),
    MetadataField("station_name", "libelle_station"),
    MetadataField("river_name", "libelle_cours_eau"),
)

if TYPE_CHECKING:
    from rivretrieve._internal.providers.fr_hubeau.generate_catalogue import FranceAvailability, NativeInventoryCapture

CODE_PROJECTION_31_AXIS_TRANSPOSITION = MappingProxyType(
    {"latitude": "longitude_station", "longitude": "latitude_station"}
)
CODE_PROJECTION_31_METROPOLITAN_BOUNDS = MappingProxyType(
    {"latitude": (42.4174, 49.989435), "longitude": (-0.616424, 5.593353)}
)


class Projection31PreconditionError(ValueError):
    """Projection-31 source columns do not have the evidenced transposition signature."""


class Projection31BoundsError(ValueError):
    """Corrected projection-31 coordinates remain outside evidenced bounds."""


def hydrometry_coordinates(native_row: Mapping[str, object]) -> tuple[object, object]:
    latitude = native_row["latitude_station"]
    longitude = native_row["longitude_station"]
    if native_row["code_projection"] != 31:
        return latitude, longitude
    if native_row["coordonnee_x_station"] != latitude or native_row["coordonnee_y_station"] != longitude:
        raise Projection31PreconditionError
    corrected_latitude = longitude
    corrected_longitude = latitude
    latitude_bounds = CODE_PROJECTION_31_METROPOLITAN_BOUNDS["latitude"]
    longitude_bounds = CODE_PROJECTION_31_METROPOLITAN_BOUNDS["longitude"]
    if not (
        isinstance(corrected_latitude, int | float)
        and isinstance(corrected_longitude, int | float)
        and latitude_bounds[0] <= corrected_latitude <= latitude_bounds[1]
        and longitude_bounds[0] <= corrected_longitude <= longitude_bounds[1]
    ):
        raise Projection31BoundsError
    return corrected_latitude, corrected_longitude


class HydrometryCoordinateConversion(catalogue_origins.FieldConversion):
    """Apply France's evidenced projection-31 axis correction to one coordinate."""

    __slots__ = ()

    @property
    def name(self) -> catalogue_origins.ConversionName:
        return catalogue_origins.ConversionName("fr_hubeau.projection_31_axis_correction")

    def apply(
        self,
        canonical_column: str,
        native_column: catalogue_origins.NativeColumn,
        native_row: Mapping[str, object],
    ) -> object:
        expected_native_column = {
            "latitude": "latitude_station",
            "longitude": "longitude_station",
        }.get(canonical_column)
        if expected_native_column is None:
            raise ValueError("Hubeau coordinate conversion is only defined for coordinates")
        if native_column != expected_native_column:
            raise ValueError(f"Hubeau {canonical_column} conversion requires native field {expected_native_column!r}")
        latitude, longitude = hydrometry_coordinates(native_row)
        return latitude if canonical_column == "latitude" else longitude


CRS_EVIDENCE_URL = (
    "https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/stations?code_station=1011000101&format=geojson"
)
TEMPERATURE_CRS_EVIDENCE_URL = "https://hubeau.eaufrance.fr/api/v1/temperature/station?size=2000&format=json"

HYDROMETRY_STATION_CATALOGUE_ORIGINS: dict[str, catalogue_origins.CatalogueOrigin] = {
    "provider_id": catalogue_origins.Authored(catalogue_origins.AuthoredValue("fr_hubeau")),
    "station_id": catalogue_origins.Field(catalogue_origins.NativeColumn("code_station")),
    "latitude": catalogue_origins.Field(
        catalogue_origins.NativeColumn("latitude_station"), HydrometryCoordinateConversion()
    ),
    "longitude": catalogue_origins.Field(
        catalogue_origins.NativeColumn("longitude_station"), HydrometryCoordinateConversion()
    ),
    "crs": catalogue_origins.Documented(
        catalogue_origins.DocumentedValue("EPSG:4326"),
        catalogue_origins.Evidence(CRS_EVIDENCE_URL),
    ),
}

TEMPERATURE_STATION_CATALOGUE_ORIGINS: dict[str, catalogue_origins.CatalogueOrigin] = {
    "provider_id": catalogue_origins.Authored(catalogue_origins.AuthoredValue("fr_hubeau")),
    "station_id": catalogue_origins.Field(catalogue_origins.NativeColumn("code_station")),
    "latitude": catalogue_origins.Field(
        catalogue_origins.NativeColumn("latitude"), catalogue_origins.FloatConversion()
    ),
    "longitude": catalogue_origins.Field(
        catalogue_origins.NativeColumn("longitude"), catalogue_origins.FloatConversion()
    ),
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

NATIVE_TABLE_SHA256 = "4ff9439d0abd7f479d17b2c608d923d7834ea3df084ed08a3af9cec1d35ab687"
NATIVE_TABLE_BYTE_SIZE = 1049930
NATIVE_TABLE_REVISION = "5dc8e480e426babe109c0467c5e0c374f92239c3"
NATIVE_TABLE_REPOSITORY_PATH = "src/rivretrieve/_internal/providers/fr_hubeau/catalogue/native.parquet"
NATIVE_TABLE_SEMANTIC_SHA256 = "f5c3d84a4e6674a1aa5e6b951576edf6bcbdf77867ab0e5c3ffe2f09adbf7322"
_TERMS_FILE = "fr_hubeau_terms_licence.html"
_TERMS_SHA256 = "82ff424acd31cdff38df4307bb8e8674d2cdc82659c99b4a117455cacd8d19cc"
_LICENSE = "La réutilisation des Jeux de données est régie par la licence ouverte Etalab, https://www.etalab.gouv.fr/licence-ouverte-open-licence. Les Jeux de données sont donc librement et gratuitement utilisables et réutilisables, y compris dans un but commercial."
_CITATION = "L'utilisateur de ces données doit néanmoins veiller à citer l'auteur des Jeux de données."


_PUBLICATION_DOCUMENTS = (
    (
        "fr_hubeau_hydrometrie",
        "Hydrometry distribution and network roles",
        "tests/test_data/fr_hubeau_hydrometrie.html",
        "https://hubeau.eaufrance.fr/page/api-hydrometrie",
        "2026-09-13T17:56:22.140907+00:00",
        "text/html; charset=UTF-8",
        "0fac4526c51ea72921747e23726024359991c25fb5781b32bc368c9cc9ded509",
    ),
)


def build_acquisition_provenance(
    *,
    hydrometry_station_ids: tuple[str, ...],
    temperature_station_ids: tuple[str, ...],
    availability: FranceAvailability,
    native_capture: NativeInventoryCapture | None = None,
) -> AcquisitionProvenance:
    """Bind official publication separately from original measurement authorship."""
    station_ids = hydrometry_station_ids + temperature_station_ids
    if not station_ids or len(set(station_ids)) != len(station_ids):
        raise ValueError("Hub’Eau provenance requires unique station identifiers")
    terms = RecordingReference(
        recording_id="fr_hubeau_terms",
        repository_path=f"tests/test_data/{_TERMS_FILE}",
        source_url="https://hubeau.eaufrance.fr/page/conditions-generales",
        retrieved_at=datetime.fromisoformat("2026-08-20T15:39:10Z"),
        media_type="text/html; charset=UTF-8",
        sha256=_TERMS_SHA256,
    )
    temperature = RecordingReference(
        recording_id="fr_hubeau_temperature_openapi",
        repository_path="tests/test_data/fr_hubeau_temperature_openapi.json",
        source_url="https://hubeau.eaufrance.fr/api/v1/temperature/api-docs",
        retrieved_at=datetime.fromisoformat("2026-09-02T14:50:55.466790Z"),
        media_type="application/json",
        sha256="797506a9cf78fbba29fb82eca71ac278d7fe84bd90aa4552ac79a71752c059ef",
    )
    evidence: dict[str, list[EvidenceReference]] = {
        "fr_hubeau": [
            EvidenceReference(
                evidence_id="fr_hubeau_terms", description="Hub'Eau general conditions section 5.1.3", recording=terms
            ),
            EvidenceReference(
                evidence_id="fr_hubeau_temperature_openapi",
                description="Official temperature API contract for chronique result fields",
                recording=temperature,
            ),
        ],
    }
    acquisitions: dict[str, list[AcquisitionRecord]] = {
        "fr_hubeau": [
            AcquisitionRecord(
                acquisition_id="hydrometry_catalogue_capture_2026_08_02",
                method="http_campaign",
                instant_type="retrieval",
                description="Seven complete Hub’Eau hydrometry referential pages, 6,454 rows; station identity and location, not historical measurement authorship",
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
                description="Complete Hub’Eau temperature station response, 869 rows; station identity and location, not historical measurement authorship",
                requested_from=("https://hubeau.eaufrance.fr/api/v1/temperature/station?size=2000&format=json",),
                retrieved_at_start=datetime.fromisoformat("2026-08-02T17:33:34Z"),
            ),
            AcquisitionRecord(
                acquisition_id="temperature_semantics_openapi_2026_09_02",
                method="http_request",
                instant_type="retrieval",
                description="Official temperature API contract without stated temporal support",
                requested_from=(temperature.source_url,),
                retrieved_at_start=temperature.retrieved_at,
                recording_ids=(temperature.recording_id,),
            ),
            AcquisitionRecord(
                acquisition_id="general_conditions_capture_2026_08_20",
                method="http_request",
                instant_type="retrieval",
                description="Hub’Eau general conditions; naming a publisher does not resolve requested dataset-author credit",
                requested_from=(terms.source_url,),
                retrieved_at_start=terms.retrieved_at,
                recording_ids=(terms.recording_id,),
            ),
            AcquisitionRecord(
                acquisition_id="observation_transport",
                method="runtime_http_request",
                instant_type="runtime",
                description="Official Hub’Eau publication of station daily hydrometry and reported temperature; original measurement authorship remains unestablished",
                requested_from=(
                    "https://hubeau.eaufrance.fr/api/v2/hydrometrie/obs_elab?code_entite={station}&grandeur_hydro_elab={metric}",
                    "https://hubeau.eaufrance.fr/api/v1/temperature/chronique?code_station={station}",
                ),
            ),
        ],
    }
    if native_capture is not None:
        acquisitions["fr_hubeau"][:2] = [native_capture.hydrometry, native_capture.temperature]
        evidence["fr_hubeau"].extend(native_capture.evidence)
    bindings: list[FactBinding] = []

    def bind(group: str, facts: tuple[str, ...], source: str, acquisition: str) -> None:
        bindings.append(FactBinding(fact_group=group, facts=facts, source_id=source, acquisition_id=acquisition))

    for identifier, scope, path, url, instant, media_type, digest in _PUBLICATION_DOCUMENTS:
        source = "fr_hubeau"
        recording = RecordingReference(
            recording_id=identifier,
            repository_path=path,
            source_url=url,
            retrieved_at=datetime.fromisoformat(instant),
            media_type=media_type,
            sha256=digest,
        )
        evidence[source].append(EvidenceReference(evidence_id=identifier, description=scope, recording=recording))
        acquisitions[source].append(
            AcquisitionRecord(
                acquisition_id=identifier,
                method="http_request",
                instant_type="retrieval",
                description=scope + "; official publication does not establish all historical measurement authorship",
                requested_from=(url,),
                retrieved_at_start=recording.retrieved_at,
                recording_ids=(identifier,),
            )
        )
        bind(identifier, (f"source.publication.{identifier}",), source, identifier)
    bind(
        "terms_statements",
        ("source.hubeau.license_statement", "source.hubeau.citation_statement"),
        "fr_hubeau",
        "general_conditions_capture_2026_08_20",
    )
    bind(
        "hydrometry_platform_and_product_external",
        ("source.provider.platform", "source.product.hydrometry_api_semantics"),
        "fr_hubeau",
        "fr_hubeau_hydrometrie",
    )
    bind(
        "temperature_product_external",
        ("source.product.temperature_api_semantics",),
        "fr_hubeau",
        "temperature_semantics_openapi_2026_09_02",
    )
    bind("observation_transport", ("source.observation.transport",), "fr_hubeau", "observation_transport")
    for partition, ids, acquisition in (
        (
            "hydrometry",
            hydrometry_station_ids,
            native_capture.hydrometry.acquisition_id if native_capture else "hydrometry_catalogue_capture_2026_08_02",
        ),
        (
            "temperature",
            temperature_station_ids,
            native_capture.temperature.acquisition_id if native_capture else "temperature_catalogue_capture_2026_08_02",
        ),
    ):
        bind(
            acquisition,
            (f"source.station_inventory.{partition}.identity_location_crs",)
            + tuple(f"source.station.{station}.identity_location_crs" for station in ids),
            "fr_hubeau",
            acquisition,
        )
    bindings.append(
        FactBinding(
            fact_group="canonical_station_identity_geometry",
            facts=("station.station_id", "station.latitude", "station.longitude", "station.crs"),
            source_id=None,
            acquisition_id=None,
            transformation=Transformation(
                name="Hub’Eau native station fields with independently evidenced coordinate correction",
                external_inputs=tuple(
                    ExternalFactReference(
                        source_id="fr_hubeau", fact=f"source.station_inventory.{partition}.identity_location_crs"
                    )
                    for partition in ("hydrometry", "temperature")
                ),
            ),
        )
    )
    for pair in availability.pairs:
        external = []
        for index, acquisition in enumerate(pair.acquisitions):
            source = "fr_hubeau"
            if acquisition.role != "publisher_count":
                raise ValueError("Hub’Eau availability cannot use another publication service")
            identifier = f"availability_{pair.code_station}_{pair.product_id}_{index}"
            fact = f"source.availability.{pair.code_station}.{pair.product_id}.{index}"
            acquisitions[source].append(
                AcquisitionRecord(
                    acquisition_id=identifier,
                    method=acquisition.method,
                    instant_type="retrieval",
                    description=f"{acquisition.role}; HTTP {acquisition.http_status}; {pair.status}; {pair.basis}. Availability only, not numerical values or continuous history.",
                    requested_from=acquisition.requested_from,
                    retrieved_at_start=acquisition.retrieved_at_start,
                    material=acquisition.material,
                )
            )
            bind(identifier, (fact,), source, identifier)
            external.append(ExternalFactReference(source_id=source, fact=fact))
        if not external:
            external.append(
                ExternalFactReference(
                    source_id="fr_hubeau", fact=f"source.station.{pair.code_station}.identity_location_crs"
                )
            )
        bindings.append(
            FactBinding(
                fact_group=f"availability:{pair.code_station}:{pair.product_id}",
                facts=(f"station_product:{pair.code_station}:{pair.product_id}.availability",),
                source_id=None,
                acquisition_id=None,
                transformation=Transformation(
                    name="dated station-product availability conclusion", external_inputs=tuple(external)
                ),
            )
        )
    for source, acquisition_id, products in (
        (
            "fr_hubeau",
            "observation_transport",
            {"discharge_daily_mean", "discharge_daily_max", "stage_daily_max", "water_temperature_reported"},
        ),
    ):
        bind(
            f"observation_publication:{source}",
            tuple(
                f"source.observation.{pair.code_station}.{pair.product_id}.values_quality"
                for pair in availability.pairs
                if pair.product_id in products
            ),
            source,
            acquisition_id,
        )
    sources = (
        SourceRecord(
            source_id="fr_hubeau",
            issuer="Hub’Eau",
            operator="OFB / Service Central Vigicrues / BRGM, éditeurs Hub’Eau",
            acquisitions=tuple(acquisitions["fr_hubeau"]),
            evidence=tuple(evidence["fr_hubeau"]),
            statements=(
                SourceStatement(
                    kind="license",
                    exact_text=_LICENSE,
                    recording_id=terms.recording_id,
                    fact="source.hubeau.license_statement",
                ),
                SourceStatement(
                    kind="citation",
                    exact_text=_CITATION,
                    recording_id=terms.recording_id,
                    fact="source.hubeau.citation_statement",
                ),
            ),
        ),
    )
    provenance = AcquisitionProvenance(
        schema_version=2,
        provider_id="fr_hubeau",
        native_table=native_capture.native_table
        if native_capture
        else NativeTableIdentity(
            repository_path=NATIVE_TABLE_REPOSITORY_PATH,
            revision=NATIVE_TABLE_REVISION,
            sha256=NATIVE_TABLE_SHA256,
            byte_size=NATIVE_TABLE_BYTE_SIZE,
            semantic_digest=SemanticDigest(
                name="fr_hubeau.native_table_content_sha256", sha256=NATIVE_TABLE_SEMANTIC_SHA256
            ),
        ),
        source_records=sources,
        fact_bindings=tuple(bindings),
        fact_universe=tuple(fact for binding in bindings for fact in binding.facts),
    )
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


# Existing acquisition facts materialised in the retained native table.
# This declares derived-input support, not preservation of original responses.
NATIVE_TABLE_ACQUISITION_IDS = ("hydrometry_catalogue_capture_2026_09_21", "temperature_catalogue_capture_2026_09_21")


# Authored catalogue, physical-fact and support declarations selected at build time.
# Non-source paths identify explicit authored inputs in the restricted handoff.
# Their code references resolve to the reviewed private declaration owner.
CATALOGUE_BUILD_DECLARATIONS = (
    ("src/rivretrieve/_internal/providers/fr_hubeau/origins.py", "build_acquisition_provenance"),
    ("src/rivretrieve/_internal/providers/fr_hubeau/origins.py", "NATIVE_TABLE_ACQUISITION_IDS"),
    ("src/rivretrieve/_internal/providers/fr_hubeau/origins.py", "CATALOGUE_SUPPORTING_INPUTS"),
    ("src/rivretrieve/_internal/providers/fr_hubeau/origins.py", "STATION_METADATA_FIELDS"),
    ("src/rivretrieve/_internal/providers/fr_hubeau/origins.py", "STATION_METADATA_NOTICE"),
    ("src/rivretrieve/_internal/providers/fr_hubeau/generate_catalogue.py", "build_catalogue"),
    ("src/rivretrieve/_internal/assembly.py", "assemble"),
    ("src/rivretrieve/_internal/providers/fr_hubeau/config.py", "config"),
    ("src/rivretrieve/_internal/providers/fr_hubeau/config.py", "SERIES_MAPPINGS"),
    ("maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz", None),
    ("maintenance/catalogue/fr_hubeau/inventory/native_capture.json", None),
)


# Additional retained declarations used by these source facts; not original-body claims.
CATALOGUE_SUPPORTING_INPUTS = {}
