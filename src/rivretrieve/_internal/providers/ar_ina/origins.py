"""Argentina INA Alerta5 source declarations for offline hydrometric station discovery."""

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
    NativeColumn,
)
from rivretrieve._internal.catalogues.artifact import CATALOGUE_FACT_UNIVERSE
from rivretrieve._internal.catalogues.station_metadata import MetadataField

CRS_EVIDENCE_URL = "https://alerta.ina.gob.ar/a5/secciones/mapa/puntual"

STATION_CATALOGUE_ORIGINS = {
    "provider_id": Authored(AuthoredValue("ar_ina")),
    "station_id": Field(NativeColumn("id")),
    "latitude": Field(NativeColumn("latitude")),
    "longitude": Field(NativeColumn("longitude")),
    "crs": Documented(DocumentedValue("EPSG:4326"), Evidence(CRS_EVIDENCE_URL)),
}

STATION_METADATA_NOTICE = (
    "Station metadata is published under Creative Commons Atribución 4.0 Internacional by the "
    "Instituto Nacional del Agua (INA) via Argentina.gob.ar. Source station and water-body names "
    "remain unchanged; this metadata projection is produced by RivRetrieve."
)

STATION_METADATA_FIELDS: tuple[MetadataField, ...] = (
    MetadataField("station_name", "nombre"),
    MetadataField("water_body_name", "rio"),
)

NATIVE_TABLE_ACQUISITION_IDS: tuple[str, ...] = (
    "ar-ina-estaciones-snapshot",
    "ar-ina-series-catalogue",
)

_CATALOGUE_SOURCE_FACTS = {
    "station": (
        "source.station.estaciones_registry",
        "source.station.series_embedded_estacion",
        "source.station.openapi_estacion_schema",
        "source.station.documented_crs",
    ),
    "product": (
        "source.product.variables_unidades_procedimientos",
        "source.product.observation_temporal_semantics",
        "source.product.series_meaning_witnesses",
        "source.station_product.series_associations",
        "source.station.cero_ign_definition",
    ),
    "station_product": (
        "source.station.estaciones_registry",
        "source.station.series_embedded_estacion",
        "source.station_product.series_associations",
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
    """Bind selected official INA Alerta5 source evidence and derived native table to catalogue facts.

    Acquisitions and exact statements come from the verified selection. Unestablished
    temporal meanings (such as Continuous slotted stage statistics and pre-2009 DST
    fixed day offsets) and record bounds remain unknown in canonical catalogue tables;
    unestablished citation wording remains null.
    """
    if any(binding.source_id != "ar_ina" or binding.transformation is not None for binding in source_bindings):
        raise ValueError("INA source bindings must directly identify selected acquisitions")
    facts = tuple(fact for binding in source_bindings for fact in binding.facts)
    required = {fact for group in _CATALOGUE_SOURCE_FACTS.values() for fact in group}
    required.add("source.provider.license")
    if missing := required - set(facts):
        raise ValueError(f"Missing INA source facts: {sorted(missing)!r}")
    if not any(statement.kind == "license" and statement.fact is not None for statement in statements):
        raise ValueError("ar_ina catalogue requires selected license evidence")
    provenance = AcquisitionProvenance(
        schema_version=2,
        provider_id="ar_ina",
        native_table=native_identity,
        source_records=(
            SourceRecord(
                source_id="ar_ina",
                issuer="Instituto Nacional del Agua (INA)",
                operator="Sistema de Información Hidrológica (Alerta5)",
                acquisitions=acquisitions,
                evidence=tuple(
                    EvidenceReference(
                        evidence_id=item.recording_id,
                        description="Selected official INA Alerta5 catalogue source",
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
                name=f"INA Alerta5 source facts to canonical {carrier}; unestablished temporal meanings remain unknown",
                external_inputs=tuple(ExternalFactReference(source_id="ar_ina", fact=fact) for fact in source_facts),
            ),
            fact_group=f"canonical_ar_ina_{carrier}",
        )
    term_facts = tuple(statement.fact for statement in statements if statement.fact is not None)
    provenance = complete_transformed_fact_universe(
        provenance,
        ("provider.license", "provider.citation"),
        transformation=Transformation(
            name="Selected Argentina.gob.ar CC BY 4.0 license statement; unestablished citation remains null",
            external_inputs=tuple(ExternalFactReference(source_id="ar_ina", fact=fact) for fact in term_facts),
        ),
        fact_group="canonical_ar_ina_terms",
    )
    return complete_transformed_fact_universe(
        provenance,
        tuple(fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith("provider.")),
        transformation=Transformation(
            name="RivRetrieve Argentina INA Alerta5 identity and catalogue-only capabilities",
            kind="authored_constant",
            external_inputs=(),
        ),
        fact_group="canonical_ar_ina_provider",
    )


CATALOGUE_SUPPORTING_INPUTS: dict[str, tuple[str, ...]] = {}
CATALOGUE_BUILD_DECLARATIONS = (
    ("maintenance/catalogue/ar_ina/official/selection.json", None),
    ("maintenance/catalogue/station_metadata/review.json", None),
    ("src/rivretrieve/_internal/providers/ar_ina/origins.py", "build_acquisition_provenance"),
    ("src/rivretrieve/_internal/providers/ar_ina/origins.py", "STATION_METADATA_FIELDS"),
    ("src/rivretrieve/_internal/providers/ar_ina/origins.py", "STATION_METADATA_NOTICE"),
    ("src/rivretrieve/_internal/providers/ar_ina/generate_catalogue.py", "build_catalogue"),
    ("src/rivretrieve/_internal/providers/ar_ina/generate_catalogue.py", "read_catalogue_sources"),
    ("src/rivretrieve/_internal/providers/ar_ina/series.py", "source_series"),
)
