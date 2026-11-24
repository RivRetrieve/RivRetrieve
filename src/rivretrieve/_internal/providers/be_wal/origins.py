"""Belgium - Wallonia (SPW Hydrométrie) source declarations for offline station discovery."""

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
    Documented,
    DocumentedValue,
    Evidence,
    Field,
    FloatConversion,
    NativeColumn,
)
from rivretrieve._internal.catalogues.artifact import CATALOGUE_FACT_UNIVERSE
from rivretrieve._internal.catalogues.station_metadata import MetadataField

CRS_EVIDENCE_URL = (
    "https://hydrometrie.wallonie.be/services/KiWIS/KiWIS"
    "?service=kisters&type=queryServices&datasource=0&format=json"
    "&request=getStationList&returnfields=all&ca_sta=all"
)

STATION_CATALOGUE_ORIGINS = {
    "provider_id": Authored(AuthoredValue("be_wal")),
    "station_id": Field(NativeColumn("station_no")),
    "latitude": Field(NativeColumn("station_latitude"), FloatConversion()),
    "longitude": Field(NativeColumn("station_longitude"), FloatConversion()),
    "crs": Documented(DocumentedValue("EPSG:4326"), Evidence(CRS_EVIDENCE_URL)),
}

STATION_METADATA_NOTICE = (
    "Station metadata from Service public de Wallonie (SPW) — Hydrométrie "
    "(https://hydrometrie.wallonie.be/mentions-legales.html; DataSPW-CGU.pdf v1.1). "
    "This metadata projection is excluded from RivRetrieve's MIT software licence. "
    "Source names, water-body names, and catchment areas remain unchanged; third-party "
    "redistribution or commercial diffusion requires SPW authorization. "
    "Attribution: Sources des données : Service public de Wallonie."
)

STATION_METADATA_FIELDS: tuple[MetadataField, ...] = (
    MetadataField(
        "station_name",
        "station_name",
        source_scope="kiwis_station_list",
        source_facts=("source.station.kiwis_station_list",),
    ),
    MetadataField(
        "water_body_name",
        "river_name",
        source_scope="kiwis_station_list",
        source_facts=("source.station.kiwis_station_list",),
    ),
    MetadataField(
        "drainage_area",
        "CATCHMENT_SIZE",
        "km2",
        source_scope="kiwis_station_list",
        source_facts=("source.station.kiwis_station_list",),
        support_facts=("source.station.catchment_size_unit",),
    ),
)

NATIVE_TABLE_ACQUISITION_IDS: tuple[str, ...] = ("kiwis-getStationList-allfields",)

_CATALOGUE_SOURCE_FACTS = {
    "station": (
        "source.station.kiwis_station_list",
        "source.station.documented_crs",
    ),
    "product": (
        "source.station_product.kiwis_tslist",
        "source.series.fields",
        "source.series.temporal_semantics",
        "source.series.stage_vertical_reference",
    ),
    "station_product": (
        "source.station.kiwis_station_list",
        "source.station_product.kiwis_tslist",
        "source.station_product.empty_coverage_checks",
    ),
}


def build_acquisition_provenance(
    native_identity: NativeTableIdentity,
    recordings: tuple[RecordingReference, ...],
    *,
    acquisitions: tuple[AcquisitionRecord, ...],
    source_bindings: tuple[FactBinding, ...],
    statements: tuple[SourceStatement, ...] = (),
) -> AcquisitionProvenance:
    """Bind selected SPW Hydrométrie KiWIS evidence and native table to catalogue facts.

    Acquisitions and verbatim statements come from the verified archive selection.
    Step 3 establishes temporal semantics, stage vertical references, and the
    ``be_wal.quality`` observation annotation schema; published record bounds remain
    unknown until Step 4 establishes retrieval window witnesses. SPW's non-redistribution
    terms leave provider license unset (``None``).
    """
    if any(binding.source_id != "be_wal" or binding.transformation is not None for binding in source_bindings):
        raise ValueError("be_wal source bindings must directly identify selected acquisitions")
    facts = tuple(fact for binding in source_bindings for fact in binding.facts)
    required = {fact for group in _CATALOGUE_SOURCE_FACTS.values() for fact in group}
    required.update(
        (
            "source.station.catchment_size_unit",
            "source.provider.terms",
            "source.provider.attribution",
            "source.series.annotations",
        )
    )
    if missing := required - set(facts):
        raise ValueError(f"Missing be_wal source facts: {sorted(missing)!r}")
    if not any(statement.kind == "terms" for statement in statements):
        raise ValueError("be_wal catalogue requires selected SPW terms statement")
    if not any(statement.kind == "citation" for statement in statements):
        raise ValueError("be_wal catalogue requires selected SPW citation statement")

    provenance = AcquisitionProvenance(
        schema_version=2,
        provider_id="be_wal",
        native_table=native_identity,
        source_records=(
            SourceRecord(
                source_id="be_wal",
                issuer="Service public de Wallonie (SPW) — Hydrométrie",
                acquisitions=acquisitions,
                evidence=tuple(
                    EvidenceReference(
                        evidence_id=item.recording_id,
                        description="Selected SPW Hydrométrie KiWIS or legal recording",
                        recording=item,
                    )
                    for item in recordings
                ),
                statements=statements,
            ),
        ),
        fact_bindings=source_bindings,
        fact_universe=facts,
    )
    for carrier, source_facts in _CATALOGUE_SOURCE_FACTS.items():
        provenance = complete_transformed_fact_universe(
            provenance,
            tuple(fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith(carrier + ".")),
            transformation=Transformation(
                name=f"SPW Hydrométrie source facts to canonical {carrier}; unverified meanings remain unknown",
                external_inputs=tuple(ExternalFactReference(source_id="be_wal", fact=fact) for fact in source_facts),
            ),
            fact_group=f"canonical_be_wal_{carrier}",
        )
    provenance = complete_transformed_fact_universe(
        provenance,
        ("provider.license", "provider.citation"),
        transformation=Transformation(
            name="Selected SPW attribution; non-redistribution terms leave software license null",
            external_inputs=(
                ExternalFactReference(source_id="be_wal", fact="source.provider.terms"),
                ExternalFactReference(source_id="be_wal", fact="source.provider.attribution"),
            ),
        ),
        fact_group="canonical_be_wal_terms",
    )
    return complete_transformed_fact_universe(
        provenance,
        tuple(fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith("provider.")),
        transformation=Transformation(
            name="RivRetrieve be_wal provider identity and CatalogueOnly capabilities",
            kind="authored_constant",
            external_inputs=(),
        ),
        fact_group="canonical_be_wal_provider",
    )


CATALOGUE_SUPPORTING_INPUTS = {}
CATALOGUE_BUILD_DECLARATIONS = (
    ("maintenance/catalogue/be_wal/official/selection.json", None),
    ("src/rivretrieve/_internal/providers/be_wal/origins.py", "build_acquisition_provenance"),
    ("src/rivretrieve/_internal/providers/be_wal/origins.py", "STATION_METADATA_FIELDS"),
    ("src/rivretrieve/_internal/providers/be_wal/origins.py", "STATION_METADATA_NOTICE"),
    ("src/rivretrieve/_internal/providers/be_wal/generate_catalogue.py", "build_catalogue"),
    ("src/rivretrieve/_internal/providers/be_wal/annotations.py", "BE_WAL_QUALITY_SCHEMA"),
    ("src/rivretrieve/_internal/providers/be_wal/generate_catalogue.py", "read_catalogue_sources"),
    ("src/rivretrieve/_internal/providers/be_wal/station_metadata.py", "project_station_metadata"),
    ("src/rivretrieve/_internal/providers/be_wal/series.py", "PRODUCT_SPECS"),
    ("src/rivretrieve/_internal/providers/be_wal/series.py", "catalogue_product_rows"),
    ("src/rivretrieve/_internal/providers/be_wal/series.py", "describe_associations"),
)
