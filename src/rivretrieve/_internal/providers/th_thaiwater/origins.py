"""ThaiWater provenance : NativeTable → AcquisitionProvenance (pure)."""

from datetime import datetime
from pathlib import Path

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
    Transformation,
    WithheldFact,
    complete_transformed_fact_universe,
)
from rivretrieve._internal.catalogues.artifact import CATALOGUE_FACT_UNIVERSE
from rivretrieve._internal.catalogues.native import NativeTable
from rivretrieve._internal.issues import FatalContractError

CRS_EVIDENCE_URL = "https://standard.thaiwater.net/docs/การจัดทำมาตรฐานน้ำ-ระยะ/ข้อมูลอ้างอิง-ข้อมูลอ้า/การระบุพิกัดตำแหน่ง/"
STATION_CATALOGUE_ORIGINS: dict[str, catalogue_origins.CatalogueOrigin] = {
    "provider_id": catalogue_origins.Field(catalogue_origins.NativeColumn("station.id")),
    "station_id": catalogue_origins.Field(catalogue_origins.NativeColumn("station.id")),
    "latitude": catalogue_origins.Field(catalogue_origins.NativeColumn("station.tele_station_lat")),
    "longitude": catalogue_origins.Field(catalogue_origins.NativeColumn("station.tele_station_long")),
    "crs": catalogue_origins.NotPublished(catalogue_origins.Evidence(CRS_EVIDENCE_URL)),
}

NATIVE_TABLE_REPOSITORY_PATH = "src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet"
NATIVE_TABLE_REVISION = "bfeb825a6f3b3aad4982649625d570c070b4ee32"
NATIVE_TABLE_SHA256 = "7a39c2c4e1144cb9b761a3f94153c06d72927224cd82318efe1f957d90d27d03"
NATIVE_TABLE_BYTE_SIZE = 126_616
NATIVE_TABLE_SEMANTIC_SHA256 = "3e2085ce51e3714d35feb053973c5074a0994278943b51c620c862be1f281cfd"
TERMS_RECORDING_PATH = Path(__file__).resolve().parents[5] / "tests/test_data/th_thaiwater_terms_licence-1.html"
_AGENCY_NAMES = {
    8: "Electricity Generating Authority of Thailand",
    9: "Hydro – Informatics Institute (Public Organization)",
    12: "Royal Irrigation Department",
    91: "Friend in Need (of “Pa”) Volunteers Foundation",
}
_PRODUCTS = ("discharge_instantaneous", "stage_instantaneous")


def _build_provider_acquisition_provenance(native_table: NativeTable) -> AcquisitionProvenance:
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
    records = []
    for agency_id, issuer in _AGENCY_NAMES.items():
        records.append(
            SourceRecord(
                source_id=f"th_agency_{agency_id}",
                issuer=issuer,
                operator="Hydro-Informatics Institute ThaiWater API" if agency_id != 9 else None,
                acquisitions=(catalogue_acquisition, runtime),
                evidence=(
                    EvidenceReference(
                        evidence_id="th_thaiwater_terms_surface",
                        description="HII terms surface recorded as evidence that no applicable licence or citation statement was found",
                        recording=terms,
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
        )
    )
    withheld = tuple(
        WithheldFact(
            fact_group=f"station_product:{station_id}:{product}:availability",
            facts=(f"station_product:{station_id}:{product}:availability",),
            reason="no_acquisition_record_established",
            catalogue_rows=(CatalogueRowLocator(carrier="station_product", station_id=station_id, product_id=product),),
        )
        for station_id, _ in station_agencies
        for product in _PRODUCTS
    )
    facts = tuple(fact for binding in bindings for fact in binding.facts) + tuple(
        fact for item in withheld for fact in item.facts
    )
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
        withheld_facts=withheld,
    )


def _complete_catalogue_carrier(provenance: AcquisitionProvenance) -> AcquisitionProvenance:
    product_facts = tuple(fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith("product."))
    provenance = complete_transformed_fact_universe(
        provenance,
        product_facts,
        transformation=Transformation(
            name="RivRetrieve canonical ThaiWater product definitions",
            kind="authored_constant",
            external_inputs=(),
        ),
        fact_group="canonical_product_carrier",
    )
    platform_facts = tuple(
        fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith(("provider.", "station_product."))
    )
    provenance = complete_transformed_fact_universe(
        provenance,
        platform_facts,
        transformation=Transformation(
            name="ThaiWater platform facts to canonical provider and relation carriers",
            external_inputs=(
                ExternalFactReference(source_id="th_agency_9", fact="source.provider.thaiwater_platform_identity"),
            ),
        ),
        fact_group="canonical_platform_carrier",
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


def build_acquisition_provenance(native_table: NativeTable) -> AcquisitionProvenance:
    """Build closed ThaiWater provenance for the exact native station population."""
    return _complete_catalogue_carrier(_build_provider_acquisition_provenance(native_table))
