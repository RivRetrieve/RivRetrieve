"""ThaiWater provenance : NativeTable × GraphAvailabilityEvidence → AcquisitionProvenance (pure)."""

from __future__ import annotations

from datetime import datetime
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
    Transformation,
    complete_transformed_fact_universe,
)
from rivretrieve._internal.catalogues.artifact import CATALOGUE_FACT_UNIVERSE
from rivretrieve._internal.catalogues.native import NativeTable
from rivretrieve._internal.issues import FatalContractError

if TYPE_CHECKING:
    from rivretrieve._internal.providers.th_thaiwater.generate_catalogue import GraphAvailabilityEvidence

CRS_EVIDENCE_URL = "https://standard.thaiwater.net/docs/การจัดทำมาตรฐานน้ำ-ระยะ/ข้อมูลอ้างอิง-ข้อมูลอ้า/การระบุพิกัดตำแหน่ง/"
STATION_CATALOGUE_ORIGINS: dict[str, catalogue_origins.CatalogueOrigin] = {
    "provider_id": catalogue_origins.Authored(catalogue_origins.AuthoredValue("th_thaiwater")),
    "station_id": catalogue_origins.Field(catalogue_origins.NativeColumn("station.id")),
    "latitude": catalogue_origins.Field(
        catalogue_origins.NativeColumn("station.tele_station_lat"), catalogue_origins.FloatConversion()
    ),
    "longitude": catalogue_origins.Field(
        catalogue_origins.NativeColumn("station.tele_station_long"), catalogue_origins.FloatConversion()
    ),
    "crs": catalogue_origins.NotPublished(catalogue_origins.Evidence(CRS_EVIDENCE_URL)),
}

NATIVE_TABLE_REPOSITORY_PATH = "src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet"
NATIVE_TABLE_REVISION = "bfeb825a6f3b3aad4982649625d570c070b4ee32"
NATIVE_TABLE_SHA256 = "7a39c2c4e1144cb9b761a3f94153c06d72927224cd82318efe1f957d90d27d03"
NATIVE_TABLE_BYTE_SIZE = 126_616
NATIVE_TABLE_SEMANTIC_SHA256 = "3e2085ce51e3714d35feb053973c5074a0994278943b51c620c862be1f281cfd"
_AGENCY_NAMES = {
    8: "Electricity Generating Authority of Thailand",
    9: "Hydro – Informatics Institute (Public Organization)",
    12: "Royal Irrigation Department",
    91: "Friend in Need (of “Pa”) Volunteers Foundation",
}


def _build_provider_acquisition_provenance(
    native_table: NativeTable, availability_evidence: GraphAvailabilityEvidence
) -> AcquisitionProvenance:
    """Build exact row-level ThaiWater issuing-body bindings."""
    required = {"station.id", "agency.id", "station.agency_id"}
    if not required <= set(native_table.data.columns):
        raise FatalContractError("ThaiWater provenance requires station and agency identity columns")
    rows = native_table.data.select("station.id", "agency.id", "station.agency_id").sort("station.id").iter_rows()
    station_agencies: list[tuple[str, int]] = []
    for station_id, agency_id, station_agency_id in rows:
        if not isinstance(station_id, str) or agency_id not in _AGENCY_NAMES or agency_id != station_agency_id:
            raise FatalContractError(f"ThaiWater station {station_id!r} has an unverified agency mapping")
        station_agencies.append((station_id, agency_id))
    terms = RecordingReference(
        recording_id="th_thaiwater_terms_absence",
        repository_path="tests/test_data/th_thaiwater_terms_licence-1.html",
        source_url="https://standard.thaiwater.net/",
        retrieved_at=datetime.fromisoformat("2026-08-20T16:12:19Z"),
        media_type="text/html; charset=UTF-8",
        sha256="5e3ac2e7ad1d125e8810c1004ef7fc4d4f85fef35233e0dca96378dc0c32a9c5",
    )
    graph_page = RecordingReference(
        recording_id="th_thaiwater_graph_page_2026_09_02",
        repository_path="tests/test_data/th_thaiwater_official_water_wl-2026-09-02.html",
        source_url="https://www.thaiwater.net/water/wl",
        retrieved_at=datetime.fromisoformat("2026-09-02T16:24:04.418069Z"),
        media_type="text/html; charset=UTF-8",
        sha256="40d29be76b21fceca0045fc88450e8f0d037b068714956b2722ddfc6953d07c6",
    )
    graph_bundle = RecordingReference(
        recording_id="th_thaiwater_graph_bundle_2026_09_02",
        repository_path="tests/test_data/th_thaiwater_official_app.chunk-2026-09-02.js",
        source_url="https://www.thaiwater.net/dist/js/app.chunk.js",
        retrieved_at=datetime.fromisoformat("2026-09-02T16:24:05.191409Z"),
        media_type="application/javascript",
        sha256="c5aeb29ff02c604ec186a1eea56bbfa770091dee6953e3d497722e1fe8632ec8",
    )
    product_semantics_acquisition = AcquisitionRecord(
        acquisition_id="product_semantics_capture_2026_09_02",
        method="http_request",
        instant_type="retrieval_interval",
        description=(
            "Official ThaiWater graph page and complete application bundle mapping graph_data.value to "
            "water level in m MSL and graph_data.discharge to discharge in m3/s; no temporal support declared"
        ),
        requested_from=(graph_page.source_url, graph_bundle.source_url),
        retrieved_at_start=graph_page.retrieved_at,
        retrieved_at_end=graph_bundle.retrieved_at,
        recording_ids=(graph_page.recording_id, graph_bundle.recording_id),
    )
    catalogue_acquisition = AcquisitionRecord(
        acquisition_id="waterlevel_load_2026_08_02",
        method="http_request",
        instant_type="retrieval",
        description="Complete 825-row ThaiWater waterlevel_load response acquired from the HII-operated API",
        requested_from=("https://api-v3.thaiwater.net/api/v1/thaiwater30/public/waterlevel_load",),
        retrieved_at_start=datetime.fromisoformat("2026-08-02T12:42:03Z"),
    )
    runtime = AcquisitionRecord(
        acquisition_id="observation_request",
        method="runtime_http_request",
        instant_type="runtime",
        description="Exact ThaiWater API observation request and response retained at runtime through the HII-operated route",
        requested_from=("https://api-v3.thaiwater.net/api/v1/thaiwater30/public/<observation-route>",),
    )
    agency_by_station = dict(station_agencies)
    if {pair.station_id for pair in availability_evidence.pairs} != set(agency_by_station):
        raise FatalContractError("ThaiWater availability evidence station population differs from native table")
    acquisitions_by_source: dict[str, dict[str, AcquisitionRecord]] = {}
    for pair in availability_evidence.pairs:
        if pair.source_id != f"th_agency_{agency_by_station[pair.station_id]}":
            raise FatalContractError(f"ThaiWater station {pair.station_id} has an unverified evidence agency mapping")
        acquisitions_by_source.setdefault(pair.source_id, {})[pair.acquisition.acquisition_id] = pair.acquisition
    records = []
    for agency_id, issuer in _AGENCY_NAMES.items():
        records.append(
            SourceRecord(
                source_id=f"th_agency_{agency_id}",
                issuer=issuer,
                operator="Hydro-Informatics Institute ThaiWater API" if agency_id != 9 else None,
                acquisitions=(
                    catalogue_acquisition,
                    runtime,
                    *((product_semantics_acquisition,) if agency_id == 9 else ()),
                    *acquisitions_by_source[f"th_agency_{agency_id}"].values(),
                ),
                evidence=(
                    EvidenceReference(
                        evidence_id="th_thaiwater_terms_surface",
                        description="HII terms surface recorded as evidence that no applicable licence or citation statement was found",
                        recording=terms,
                    ),
                    EvidenceReference(
                        evidence_id="th_thaiwater_graph_page",
                        description="Official ThaiWater graph page loading the recorded application bundle",
                        recording=graph_page,
                    ),
                    EvidenceReference(
                        evidence_id="th_thaiwater_graph_field_mapping",
                        description=(
                            "Complete official bundle binding value to Water Level (m MSL) and discharge to "
                            "Discharge (m3/second), without declaring represented temporal support"
                        ),
                        recording=graph_bundle,
                    ),
                )
                if agency_id == 9
                else (),
            )
        )
    bindings = []
    for station_id, agency_id in station_agencies:
        source_id = f"th_agency_{agency_id}"
        bindings.append(
            FactBinding(
                fact_group=f"station:{station_id}",
                facts=(f"source.station:{station_id}.identity_and_location",),
                source_id=source_id,
                acquisition_id="waterlevel_load_2026_08_02",
            )
        )
        bindings.append(
            FactBinding(
                fact_group=f"observation:{station_id}",
                facts=(f"source.station:{station_id}.observation.values_and_quality",),
                source_id=source_id,
                acquisition_id="observation_request",
            )
        )
    bindings.extend(
        (
            FactBinding(
                fact_group="provider_identity",
                facts=("source.provider.thaiwater_platform_identity",),
                source_id="th_agency_9",
                acquisition_id="waterlevel_load_2026_08_02",
            ),
            FactBinding(
                fact_group="source_product_semantics",
                facts=("source.product.thaiwater_graph_field_meanings_and_units",),
                source_id="th_agency_9",
                acquisition_id="product_semantics_capture_2026_09_02",
            ),
            *(
                FactBinding(
                    fact_group=f"station_product:{pair.station_id}:{pair.product_id}:availability",
                    facts=(f"source.station_product:{pair.station_id}:{pair.product_id}.availability",),
                    source_id=pair.source_id,
                    acquisition_id=pair.acquisition.acquisition_id,
                )
                for pair in availability_evidence.pairs
            ),
        )
    )
    facts = tuple(fact for binding in bindings for fact in binding.facts)
    return AcquisitionProvenance(
        schema_version=2,
        provider_id="th_thaiwater",
        native_table=NativeTableIdentity(
            repository_path=NATIVE_TABLE_REPOSITORY_PATH,
            revision=NATIVE_TABLE_REVISION,
            sha256=NATIVE_TABLE_SHA256,
            byte_size=NATIVE_TABLE_BYTE_SIZE,
            semantic_digest=SemanticDigest(
                name="th_thaiwater.native_table_content_sha256", sha256=NATIVE_TABLE_SEMANTIC_SHA256
            ),
        ),
        source_records=tuple(records),
        fact_universe=facts,
        fact_bindings=tuple(bindings),
    )


def _complete_catalogue_carrier(provenance: AcquisitionProvenance) -> AcquisitionProvenance:
    product_facts = tuple(fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith("product."))
    provenance = complete_transformed_fact_universe(
        provenance,
        product_facts,
        transformation=Transformation(
            name="ThaiWater graph fields to conservative canonical product definitions",
            external_inputs=(
                ExternalFactReference(
                    source_id="th_agency_9",
                    fact="source.product.thaiwater_graph_field_meanings_and_units",
                ),
            ),
        ),
        fact_group="canonical_product_carrier",
    )
    platform_facts = tuple(fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith("provider."))
    provenance = complete_transformed_fact_universe(
        provenance,
        platform_facts,
        transformation=Transformation(
            name="ThaiWater platform identity to canonical provider carrier",
            external_inputs=(
                ExternalFactReference(source_id="th_agency_9", fact="source.provider.thaiwater_platform_identity"),
            ),
        ),
        fact_group="canonical_platform_carrier",
    )
    relation_facts = tuple(fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith("station_product."))
    provenance = complete_transformed_fact_universe(
        provenance,
        relation_facts,
        transformation=Transformation(
            name="Agency-bound graph acquisitions to canonical station-product carrier",
            external_inputs=tuple(
                ExternalFactReference(source_id=binding.source_id, fact=binding.facts[0])
                for binding in provenance.fact_bindings
                if binding.fact_group.startswith("station_product:")
            ),
        ),
        fact_group="canonical_station_product_carrier",
    )
    station_facts = tuple(fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith("station."))
    station_inputs = tuple(
        ExternalFactReference(source_id=binding.source_id, fact=binding.facts[0])
        for binding in provenance.fact_bindings
        if binding.fact_group.startswith("station:") and binding.source_id is not None
    )
    payload = provenance.model_dump(mode="python")
    payload["fact_universe"] = (*provenance.fact_universe, *station_facts)
    payload["fact_bindings"] = (
        *provenance.fact_bindings,
        FactBinding(
            fact_group="canonical_station_carrier",
            facts=station_facts,
            source_id=None,
            acquisition_id=None,
            transformation=Transformation(
                name="Agency-bound station rows to canonical station carriers",
                external_inputs=station_inputs,
            ),
        ),
    )
    return AcquisitionProvenance.model_validate(payload)


def build_acquisition_provenance(
    native_table: NativeTable, availability_evidence: GraphAvailabilityEvidence
) -> AcquisitionProvenance:
    """Build closed ThaiWater provenance for the exact native station population."""
    return _complete_catalogue_carrier(_build_provider_acquisition_provenance(native_table, availability_evidence))
