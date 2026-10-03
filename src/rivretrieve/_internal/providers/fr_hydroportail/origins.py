"""HydroPortail-native field origins and acquisition lineage."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from rivretrieve._internal import catalogue_origins as origins
from rivretrieve._internal.acquisition_provenance import (
    AcquisitionProvenance,
    AcquisitionRecord,
    EvidenceReference,
    ExternalFactReference,
    FactBinding,
    MaterialIdentity,
    NativeTableIdentity,
    SourceRecord,
    Transformation,
    complete_transformed_fact_universe,
)
from rivretrieve._internal.catalogues.artifact import CATALOGUE_FACT_UNIVERSE
from rivretrieve._internal.catalogues.station_metadata import MetadataField

# Name mappings require genuine-input validation and owner disclosure approval
# before generated metadata can be packaged. Native presence is insufficient.
STATION_METADATA_FIELDS: tuple[MetadataField, ...] = ()

if TYPE_CHECKING:
    from rivretrieve._internal.catalogues.native import NativeTable
    from rivretrieve._internal.providers.fr_hydroportail.generate_catalogue import StationProductAvailability

SEARCH_URL = "https://hydro.eaufrance.fr/rechercher/ajax/entites-hydrometriques"
COORDINATE_EVIDENCE = "https://hydro.eaufrance.fr/build/8529.fdb00780.js"
STATION_CATALOGUE_ORIGINS = {
    "provider_id": origins.Authored(origins.AuthoredValue("fr_hydroportail")),
    "station_id": origins.Field(origins.NativeColumn("bookmarkCode")),
    "latitude": origins.Field(origins.NativeColumn("y")),
    "longitude": origins.Field(origins.NativeColumn("x")),
    "crs": origins.Documented(origins.DocumentedValue("EPSG:4326"), origins.Evidence(COORDINATE_EVIDENCE)),
}


def build_acquisition_provenance(
    native: NativeTable,
    pairs: tuple[StationProductAvailability, ...],
    receipt: dict,
    documents: tuple[EvidenceReference, ...],
    native_identity: NativeTableIdentity,
    requested_from: str,
) -> AcquisitionProvenance:
    source = "fr_hydroportail"
    acquisitions = [
        AcquisitionRecord(
            acquisition_id="public_station_search",
            method="http_request",
            instant_type="retrieval",
            description="Anonymous public native station search: explicit active, closed, all published site types and test entities. Not an unrestricted PHyC census or observation availability assertion.",
            requested_from=(requested_from,),
            retrieved_at_start=datetime.fromisoformat(receipt["retrieved_at"]),
            material=MaterialIdentity(
                filename="maintenance/catalogue/fr_hydroportail/evidence/national-tests.body",
                byte_count=receipt["bytes"],
                sha256=receipt["sha256"],
            ),
        )
    ]
    bindings = [
        FactBinding(
            fact_group="native_station_inventory",
            facts=("source.station_inventory.identity_location_crs",)
            + tuple(f"source.station.{s}.identity_location_crs" for s in native.data["bookmarkCode"]),
            source_id=source,
            acquisition_id="public_station_search",
        )
    ]
    for document in documents:
        recording = document.recording
        acquisitions.append(
            AcquisitionRecord(
                acquisition_id=document.evidence_id,
                method="http_request",
                instant_type="retrieval",
                description=document.description,
                requested_from=(recording.source_url,),
                retrieved_at_start=recording.retrieved_at,
                recording_ids=(recording.recording_id,),
            )
        )
        bindings.append(
            FactBinding(
                fact_group=document.evidence_id,
                facts=(f"source.documentation.{document.evidence_id}",),
                source_id=source,
                acquisition_id=document.evidence_id,
            )
        )
    bindings.append(
        FactBinding(
            fact_group="native_publication",
            facts=("source.provider.platform",),
            source_id=source,
            acquisition_id="about",
        )
    )
    acquisitions.append(
        AcquisitionRecord(
            acquisition_id="raw_station_series",
            method="runtime_http_request",
            instant_type="runtime",
            description="HydroPortail station-own raw Q/H publication; original measurement authorship unknown",
            requested_from=("https://hydro.eaufrance.fr/stationhydro/ajax/{station}/series",),
        )
    )
    bindings.append(
        FactBinding(
            fact_group="raw_station_series",
            facts=("source.observation.raw_station_series",),
            source_id=source,
            acquisition_id="raw_station_series",
        )
    )
    for pair in pairs:
        external = []
        for index, acquisition in enumerate(pair.acquisitions):
            identifier = f"history_{pair.station_id}_{pair.product_id}_{index}"
            fact = f"source.availability.{pair.station_id}.{pair.product_id}.{index}"
            acquisitions.append(
                AcquisitionRecord(
                    acquisition_id=identifier,
                    method="http_request",
                    instant_type="retrieval",
                    description=f"HydroPortail raw station history; HTTP {acquisition.http_status}; {pair.status}. Exact bounded request, not continuous availability.",
                    requested_from=acquisition.requested_from,
                    retrieved_at_start=acquisition.retrieved_at_start,
                    material=acquisition.material,
                )
            )
            bindings.append(
                FactBinding(fact_group=identifier, facts=(fact,), source_id=source, acquisition_id=identifier)
            )
            external.append(ExternalFactReference(source_id=source, fact=fact))
        if not external:
            external.append(
                ExternalFactReference(source_id=source, fact=f"source.station.{pair.station_id}.identity_location_crs")
            )
        bindings.append(
            FactBinding(
                fact_group=f"availability:{pair.station_id}:{pair.product_id}",
                facts=(f"station_product:{pair.station_id}:{pair.product_id}.availability",),
                source_id=None,
                acquisition_id=None,
                transformation=Transformation(name=pair.reason, external_inputs=tuple(external)),
            )
        )
    inventory_fact = ExternalFactReference(source_id=source, fact="source.station_inventory.identity_location_crs")
    bindings.extend(
        (
            FactBinding(
                fact_group="canonical_station_identity",
                facts=("station.station_id",),
                source_id=None,
                acquisition_id=None,
                transformation=Transformation(
                    name="Full station bookmarkCode from native public search",
                    external_inputs=(inventory_fact,),
                ),
            ),
            FactBinding(
                fact_group="canonical_station_geometry",
                facts=("station.latitude", "station.longitude", "station.crs"),
                source_id=None,
                acquisition_id=None,
                transformation=Transformation(
                    name="Native station x/y with published GeoJSON coordinate semantics",
                    external_inputs=(
                        inventory_fact,
                        ExternalFactReference(source_id=source, fact="source.documentation.chunk-8529.fdb00780.js"),
                    ),
                ),
            ),
        )
    )
    provenance = AcquisitionProvenance(
        native_table=native_identity,
        schema_version=2,
        provider_id=source,
        source_records=(
            SourceRecord(
                source_id=source,
                issuer="Service Central Vigicrues",
                operator="HydroPortail / PHyC",
                acquisitions=tuple(acquisitions),
                evidence=documents,
            ),
        ),
        fact_bindings=tuple(bindings),
        fact_universe=tuple(f for b in bindings for f in b.facts),
    )
    return complete_transformed_fact_universe(
        provenance,
        CATALOGUE_FACT_UNIVERSE,
        transformation=Transformation(
            name="HydroPortail native publication to canonical catalogue; reuse licence and historical measurement authors unknown",
            external_inputs=(
                ExternalFactReference(source_id=source, fact="source.provider.platform"),
                ExternalFactReference(source_id=source, fact="source.documentation.chunk-8529.fdb00780.js"),
            ),
        ),
    )


# Existing acquisition facts materialised in the retained native table.
# This declares derived-input support, not preservation of original responses.
NATIVE_TABLE_ACQUISITION_IDS = ("public_station_search",)


# Authored catalogue, physical-fact and support declarations selected at build time.
# Non-source paths identify explicit authored inputs in the restricted handoff.
# Their code references resolve to the reviewed private declaration owner.
CATALOGUE_BUILD_DECLARATIONS = (
    ("src/rivretrieve/_internal/providers/fr_hydroportail/origins.py", "build_acquisition_provenance"),
    ("src/rivretrieve/_internal/providers/fr_hydroportail/origins.py", "NATIVE_TABLE_ACQUISITION_IDS"),
    ("src/rivretrieve/_internal/providers/fr_hydroportail/origins.py", "CATALOGUE_SUPPORTING_INPUTS"),
    ("src/rivretrieve/_internal/providers/fr_hydroportail/origins.py", "STATION_METADATA_FIELDS"),
    ("src/rivretrieve/_internal/providers/fr_hydroportail/generate_catalogue.py", "build_catalogue"),
    ("src/rivretrieve/_internal/assembly.py", "assemble"),
    ("src/rivretrieve/_internal/providers/fr_hydroportail/config.py", "config"),
    ("src/rivretrieve/_internal/providers/fr_hydroportail/config.py", "SERIES_MAPPINGS"),
    ("maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz", None),
)


# Additional retained declarations used by these source facts; not original-body claims.
CATALOGUE_SUPPORTING_INPUTS = {}
