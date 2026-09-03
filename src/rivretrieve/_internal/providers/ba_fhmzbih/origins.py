"""Bosnia catalogue authority : ∅ → OriginDeclarations × AcquisitionProvenance (pure)."""

from datetime import datetime

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
from rivretrieve._internal.catalogue_origins import Evidence, Field, NativeColumn, NotPublished
from rivretrieve._internal.catalogues.artifact import CATALOGUE_FACT_UNIVERSE

STATION_CATALOGUE_ORIGINS = {
    "provider_id": Field(NativeColumn("metadata_station_no")),
    "station_id": Field(NativeColumn("metadata_station_no")),
    "latitude": Field(NativeColumn("metadata_station_latitude")),
    "longitude": Field(NativeColumn("metadata_station_longitude")),
    "crs": NotPublished(Evidence("https://vodostaji.voda.ba/data/internet/stations/stations.json")),
}
NATIVE_TABLE_SHA256 = "abcbc2d2234ea1751d638307f89fba4cba4feca96c9cd1d77c728b87a0fea77a"
NATIVE_TABLE_BYTE_SIZE = 13430
NATIVE_TABLE_REVISION = "f805d2556a72617644f9bf90de2e3438e743b888"
NATIVE_TABLE_REPOSITORY_PATH = "src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/native.parquet"
DATA_STANDING_TEXT = "Svi podaci koji se prikazuju i koji se dobiju kao rezultat pretrage su informativnog karaktera i ne mogu služiti kao zvanični podaci."

_STATION_IDS = (
    "1010",
    "1020",
    "1114",
    "2010",
    "2020",
    "2030",
    "2035",
    "2050",
    "2060",
    "2101-B",
    "2103",
    "2110",
    "2120",
    "2210",
    "2310",
    "2320",
    "3010",
    "3020",
    "3030",
    "3040",
    "4010",
    "4020",
    "4024",
    "4030",
    "4042",
    "4050",
    "4055",
    "4060",
    "4061",
    "4062",
    "4070",
    "4110",
    "4111",
    "4121",
    "4130",
    "4142",
    "4150",
    "4170",
    "4220",
    "4240",
    "4310",
    "4340",
    "4410",
    "4411",
    "4412",
    "4420",
    "4430",
    "4450",
    "4510",
    "4610",
    "4620",
    "4630",
    "5010",
    "5101",
    "9017",
    "9018",
    "9019",
    "9030",
    "9044",
    "9045",
)
_PRODUCT_IDS = ("discharge_reported", "stage_reported", "water_temperature_reported")


def _build_provider_acquisition_provenance() -> AcquisitionProvenance:
    absence = RecordingReference(
        recording_id="ba_fhmzbih_terms_absence",
        repository_path="tests/test_data/ba_fhmzbih_terms_absence.html",
        source_url="https://vodostaji.voda.ba/data/html/impressum.html",
        retrieved_at=datetime.fromisoformat("2026-08-20T09:31:25Z"),
        media_type="text/html; charset=UTF-8",
        sha256="dd5daa83187fd11e1cd1321e4ffc78251f7f31f9e2cf528b742976f409d61709",
    )
    provider_facts = ("source.provider.service_operator", "source.provider.station_service_identity")
    product_facts = ("source.product.native_identifiers", "source.product.native_physics")
    bound_stations = ("source.station:4024.identity_location", "source.station:4110.identity_location")
    bound_observations = ("source.observation:4024.values_quality", "source.observation:4110.values_quality")
    established_availability = {
        ("4024", "discharge_reported"),
        ("4024", "stage_reported"),
        ("4110", "water_temperature_reported"),
    }
    withheld_stations = tuple(
        WithheldFact(
            fact_group=f"withheld_station:{station_id}",
            facts=(f"station:{station_id}.identity_location",),
            reason="no_acquisition_record_established",
            catalogue_rows=(CatalogueRowLocator(carrier="station", station_id=station_id),),
        )
        for station_id in _STATION_IDS
        if station_id not in {"4024", "4110"}
    )
    withheld_observations = tuple(
        WithheldFact(
            fact_group=f"withheld_observation:{station_id}",
            facts=(f"observation:{station_id}.values_quality",),
            reason="no_acquisition_record_established",
        )
        for station_id in _STATION_IDS
        if station_id not in {"4024", "4110"}
    )
    withheld_availability = tuple(
        WithheldFact(
            fact_group=f"withheld_availability:{station_id}:{product_id}",
            facts=(f"station_product:{station_id}:{product_id}.availability",),
            reason="no_acquisition_record_established",
            catalogue_rows=(
                CatalogueRowLocator(carrier="station_product", station_id=station_id, product_id=product_id),
            ),
        )
        for station_id in _STATION_IDS
        for product_id in _PRODUCT_IDS
        if (station_id, product_id) not in established_availability
    )
    withheld = withheld_stations + withheld_observations + withheld_availability
    universe = (
        provider_facts
        + product_facts
        + bound_stations
        + bound_observations
        + tuple(
            f"station_product:{station}:{product}.availability" for station, product in sorted(established_availability)
        )
        + tuple(fact for group in withheld for fact in group.facts)
    )
    return AcquisitionProvenance(
        schema_version=2,
        provider_id="ba_fhmzbih",
        native_table=NativeTableIdentity(
            repository_path=NATIVE_TABLE_REPOSITORY_PATH,
            revision=NATIVE_TABLE_REVISION,
            sha256=NATIVE_TABLE_SHA256,
            byte_size=NATIVE_TABLE_BYTE_SIZE,
            semantic_digest=SemanticDigest(
                name="ba_fhmzbih.stable_metadata_sha256",
                sha256="14ab47126fe40f16f23ddc66620fc8ae30910cd812c69806f867a851e659b23d",
            ),
        ),
        source_records=(
            SourceRecord(
                source_id="ba_avp_sava",
                issuer="Agencija za vodno područje rijeke Save",
                operator="vodostaji.voda.ba",
                acquisitions=(
                    AcquisitionRecord(
                        acquisition_id="catalogue_capture_2026_08_02",
                        method="http_request",
                        instant_type="retrieval",
                        description="60-row stable station metadata response with volatile L1 snapshot fields excluded",
                        requested_from=("https://vodostaji.voda.ba/data/internet/layers/20/index.json",),
                        retrieved_at_start=datetime.fromisoformat("2026-08-02T12:42:03Z"),
                    ),
                    AcquisitionRecord(
                        acquisition_id="terms_surface_capture_2026_08_20",
                        method="http_request",
                        instant_type="retrieval",
                        description="Exact-host Impressum response examined for published terms and citation words",
                        requested_from=(absence.source_url,),
                        retrieved_at_start=absence.retrieved_at,
                        recording_ids=(absence.recording_id,),
                    ),
                    AcquisitionRecord(
                        acquisition_id="observation_request",
                        method="runtime_http_request",
                        instant_type="runtime",
                        description="Exact station workbook request and response",
                        requested_from=(
                            "https://vodostaji.voda.ba/data/internet/stations/{group}/{station_id}/{code}/{file}",
                        ),
                    ),
                ),
                evidence=(
                    EvidenceReference(
                        evidence_id="terms_absence_surface",
                        description="Exact-host Impressum examined for terms and citation",
                        recording=absence,
                    ),
                ),
                statements=(
                    SourceStatement(
                        kind="terms",
                        exact_text=DATA_STANDING_TEXT,
                        recording_id=absence.recording_id,
                        fact="source.provider.terms_absence_statement",
                    ),
                ),
            ),
        ),
        fact_bindings=(
            FactBinding(
                fact_group="terms_surface_statement",
                facts=("source.provider.terms_absence_statement",),
                source_id="ba_avp_sava",
                acquisition_id="terms_surface_capture_2026_08_20",
            ),
            FactBinding(
                fact_group="canonical_provider",
                facts=provider_facts,
                source_id="ba_avp_sava",
                acquisition_id="catalogue_capture_2026_08_02",
            ),
            FactBinding(
                fact_group="canonical_products",
                facts=product_facts,
                source_id="ba_avp_sava",
                acquisition_id="catalogue_capture_2026_08_02",
            ),
            FactBinding(
                fact_group="stations_4024_4110",
                facts=bound_stations,
                source_id="ba_avp_sava",
                acquisition_id="catalogue_capture_2026_08_02",
            ),
            FactBinding(
                fact_group="observations_4024_4110",
                facts=bound_observations,
                source_id="ba_avp_sava",
                acquisition_id="observation_request",
            ),
            FactBinding(
                fact_group="recorded_availability",
                facts=tuple(
                    f"station_product:{station}:{product}.availability"
                    for station, product in sorted(established_availability)
                ),
                source_id=None,
                acquisition_id=None,
                transformation=Transformation(
                    name="non-empty recorded workbook to available catalogue edge",
                    external_inputs=tuple(
                        ExternalFactReference(
                            source_id="ba_avp_sava",
                            fact=f"source.observation:{station}.values_quality",
                        )
                        for station in ("4024", "4110")
                    ),
                ),
            ),
        ),
        withheld_facts=withheld,
        fact_universe=universe + ("source.provider.terms_absence_statement",),
    )


def _complete_catalogue_carrier(provenance: AcquisitionProvenance) -> AcquisitionProvenance:
    return complete_transformed_fact_universe(
        provenance,
        CATALOGUE_FACT_UNIVERSE,
        transformation=Transformation(
            name="ba_fhmzbih external facts to RivRetrieve canonical catalogue carriers",
            external_inputs=tuple(
                ExternalFactReference(source_id="ba_avp_sava", fact=fact)
                for fact in (
                    "source.provider.service_operator",
                    "source.provider.station_service_identity",
                    "source.product.native_identifiers",
                    "source.product.native_physics",
                    "source.station:4024.identity_location",
                    "source.station:4110.identity_location",
                )
            ),
        ),
    )


def build_acquisition_provenance() -> AcquisitionProvenance:
    """Build closed ba_fhmzbih acquisition provenance."""
    return _complete_catalogue_carrier(_build_provider_acquisition_provenance())
