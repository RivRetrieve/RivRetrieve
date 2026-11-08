"""Colombia IDEAM source declarations for offline river station discovery."""

from rivretrieve._internal.acquisition_provenance import (
    AbsenceMarkerValue,
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
    WithheldFact,
    complete_transformed_fact_universe,
)
from rivretrieve._internal.catalogue_origins import (
    Authored,
    AuthoredValue,
    Field,
    FloatConversion,
    NativeColumn,
    Withheld,
)
from rivretrieve._internal.catalogues.artifact import CATALOGUE_FACT_UNIVERSE
from rivretrieve._internal.catalogues.station_metadata import MetadataField

STATION_CATALOGUE_ORIGINS = {
    "provider_id": Authored(AuthoredValue("co_ideam")),
    "station_id": Field(NativeColumn("Codigo")),
    "latitude": Field(NativeColumn("Latitud"), FloatConversion()),
    "longitude": Field(NativeColumn("Longitud"), FloatConversion()),
    "crs": Withheld(),
}

STATION_METADATA_NOTICE = (
    "Station metadata from Colombia's Instituto de Hidrología, Meteorología y Estudios Ambientales (IDEAM), "
    "distributed through the IDEAM Open Data Cloud Object Store (https://datos.ideam.gov.co/s3-estacionesideam/) "
    "and Datos Abiertos Colombia (https://www.datos.gov.co/). This RivRetrieve projection is distributed under "
    "Creative Commons Attribution-ShareAlike 4.0 International (https://creativecommons.org/licenses/by-sa/4.0/). "
    "RivRetrieve selected the declared source fields and encoded their values and absence states; source names "
    "and elevations remain unchanged. Processing and publication of this projection: RivRetrieve."
)

STATION_METADATA_FIELDS: tuple[MetadataField, ...] = (
    MetadataField(
        "station_name",
        "Nombre",
        source_scope="catalogo_estaciones",
        source_facts=("source.station.catalogo_registry",),
    ),
    MetadataField(
        "water_body_name",
        "Corriente",
        source_scope="catalogo_estaciones",
        source_facts=("source.station.catalogo_registry",),
    ),
    MetadataField(
        "elevation",
        "Altitud",
        source_scope="catalogo_estaciones",
        source_facts=("source.station.catalogo_registry",),
        support_facts=("source.station.altitud_field_context",),
    ),
)

NATIVE_TABLE_ACQUISITION_IDS: tuple[str, ...] = (
    "co-ideam-s3-catalogo-estaciones",
    "co-ideam-s3-catalogo-variables",
    "co-ideam-s3-historicos-listings",
)

_CATALOGUE_SOURCE_FACTS = {
    "station": (
        "source.station.catalogo_registry",
        "source.station_product.s3_prefix_listings",
    ),
    "product": (
        "source.product.variables_catalogue",
        "source.station_product.s3_prefix_listings",
        "source.product.datosgov_series_definitions",
        "source.product.ideam_hydrological_manuals",
        "source.product.s3_observation_witnesses",
    ),
    "station_product": (
        "source.station.catalogo_registry",
        "source.station_product.s3_prefix_listings",
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
    """Bind selected official IDEAM source evidence and derived native table to catalogue facts.

    Acquisitions and exact statements come from the verified selection. Unestablished
    CRS, sub-daily cadence, temporal support, time zone, vertical datum, and record
    bounds remain unknown in canonical catalogue products.
    """
    if any(binding.source_id != "co_ideam" or binding.transformation is not None for binding in source_bindings):
        raise ValueError("IDEAM source bindings must directly identify selected acquisitions")
    facts = tuple(binding_fact for binding in source_bindings for binding_fact in binding.facts)
    required = {fact for group in _CATALOGUE_SOURCE_FACTS.values() for fact in group}
    required.update(
        (
            "source.station.altitud_field_context",
            "source.provider.license",
            "source.provider.citation",
            "source.provider.terms_series",
        )
    )
    if missing := required - set(facts):
        raise ValueError(f"Missing IDEAM source facts: {sorted(missing)!r}")
    provenance = AcquisitionProvenance(
        schema_version=2,
        provider_id="co_ideam",
        native_table=native_identity,
        source_records=(
            SourceRecord(
                source_id="co_ideam",
                issuer="Instituto de Hidrología, Meteorología y Estudios Ambientales (IDEAM)",
                operator="Datos Abiertos IDEAM",
                acquisitions=acquisitions,
                evidence=tuple(
                    EvidenceReference(
                        evidence_id=item.recording_id,
                        description="Selected official IDEAM catalogue source",
                        recording=item,
                    )
                    for item in recordings
                ),
                statements=statements,
            ),
        ),
        fact_bindings=source_bindings,
        fact_universe=(*facts, "source.station.crs"),
        withheld_facts=(
            WithheldFact(
                fact_group="unestablished_station_crs",
                source_id="co_ideam",
                facts=("source.station.crs",),
                reason="no_acquisition_record_established",
            ),
        ),
    )
    provenance = complete_transformed_fact_universe(
        provenance,
        ("station.crs",),
        transformation=Transformation(
            name="Unestablished source CRS remains unknown",
            kind="absence_marker",
            marker_value=AbsenceMarkerValue.UNKNOWN,
            external_inputs=(ExternalFactReference(source_id="co_ideam", fact="source.station.crs"),),
        ),
        fact_group="canonical_co_ideam_crs",
    )
    for carrier, source_facts in _CATALOGUE_SOURCE_FACTS.items():
        provenance = complete_transformed_fact_universe(
            provenance,
            tuple(fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith(carrier + ".")),
            transformation=Transformation(
                name=f"IDEAM source facts to canonical {carrier}; unestablished temporal meanings remain unknown",
                external_inputs=tuple(ExternalFactReference(source_id="co_ideam", fact=fact) for fact in source_facts),
            ),
            fact_group=f"canonical_co_ideam_{carrier}",
        )
    term_facts = tuple(statement.fact for statement in statements if statement.fact is not None)
    provenance = complete_transformed_fact_universe(
        provenance,
        ("provider.license", "provider.citation"),
        transformation=Transformation(
            name="Selected Datos Abiertos Colombia CC BY-SA 4.0 license and IDEAM attribution",
            external_inputs=tuple(ExternalFactReference(source_id="co_ideam", fact=fact) for fact in term_facts),
        ),
        fact_group="canonical_co_ideam_terms",
    )
    return complete_transformed_fact_universe(
        provenance,
        tuple(fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith("provider.")),
        transformation=Transformation(
            name="RivRetrieve Colombia IDEAM identity and catalogue-only capabilities",
            kind="authored_constant",
            external_inputs=(),
        ),
        fact_group="canonical_co_ideam_provider",
    )


CATALOGUE_SUPPORTING_INPUTS: dict[str, tuple[str, ...]] = {}
CATALOGUE_BUILD_DECLARATIONS = (
    ("maintenance/catalogue/co_ideam/official/selection.json", None),
    ("src/rivretrieve/_internal/providers/co_ideam/origins.py", "build_acquisition_provenance"),
    ("src/rivretrieve/_internal/providers/co_ideam/origins.py", "STATION_METADATA_FIELDS"),
    ("src/rivretrieve/_internal/providers/co_ideam/origins.py", "STATION_METADATA_NOTICE"),
    ("src/rivretrieve/_internal/providers/co_ideam/generate_catalogue.py", "build_catalogue"),
    ("src/rivretrieve/_internal/providers/co_ideam/generate_catalogue.py", "read_catalogue_sources"),
    ("src/rivretrieve/_internal/providers/co_ideam/station_metadata.py", "project_station_metadata"),
    ("src/rivretrieve/_internal/providers/co_ideam/series.py", "source_series"),
)
