"""SENAMHI source declarations for offline station discovery."""

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


class CoordinateConversion(FloatConversion):
    """Preserve absent registry coordinates during numeric conversion."""

    def apply(self, canonical_column, native_column, native_row):
        if native_row[str(native_column)] is None:
            return None
        return super().apply(canonical_column, native_column, native_row)


STATION_CATALOGUE_ORIGINS = {
    "provider_id": Authored(AuthoredValue("pe_senamhi")),
    "station_id": Field(NativeColumn("stationId")),
    "latitude": Field(NativeColumn("latitude"), CoordinateConversion()),
    "longitude": Field(NativeColumn("longitude"), CoordinateConversion()),
    "crs": Withheld(),
}
STATION_METADATA_NOTICE = (
    "Información recopilada y trabajada por el Servicio Nacional de Meteorología e Hidrología del Perú. "
    "El uso que se le da a esta información es de mi (nuestra) entera responsabilidad."
)

STATION_METADATA_FIELDS = (
    MetadataField("station_name", "name", source_scope="station_registry", source_facts=("source.station.registry",)),
    MetadataField(
        "water_body_name", "waterBody", source_scope="phisis_detail", source_facts=("source.station.phisis_detail",)
    ),
    MetadataField(
        "elevation",
        "altitude",
        "m",
        source_scope="station_registry",
        source_facts=("source.station.registry",),
        support_facts=("source.station.altitude_unit",),
    ),
)


_CATALOGUE_SOURCE_FACTS = {
    "station": ("source.station.registry", "source.station.phisis_detail"),
    "product": ("source.station_product.associations",),
    "station_product": ("source.station_product.associations", "source.station_product.inventory_support"),
}


def build_acquisition_provenance(
    native_identity: NativeTableIdentity,
    recordings: tuple[RecordingReference, ...],
    *,
    acquisitions: tuple[AcquisitionRecord, ...],
    source_bindings: tuple[FactBinding, ...],
    statements: tuple[SourceStatement, ...] = (),
) -> AcquisitionProvenance:
    """Bind original source evidence and a retained derivative to catalogue facts.

    Acquisitions and exact statements come from the verified selection. Unknown
    CRS, temporal meanings and record bounds remain unknown in canonical output.
    """
    if any(binding.source_id != "pe_senamhi" or binding.transformation is not None for binding in source_bindings):
        raise ValueError("SENAMHI source bindings must directly identify selected acquisitions")
    facts = tuple(fact for binding in source_bindings for fact in binding.facts)
    required = {fact for group in _CATALOGUE_SOURCE_FACTS.values() for fact in group}
    required.update(("source.station.altitude_unit", "source.provider.terms", "source.provider.attribution"))
    if missing := required - set(facts):
        raise ValueError(f"Missing SENAMHI source facts: {sorted(missing)!r}")
    provenance = AcquisitionProvenance(
        schema_version=2,
        provider_id="pe_senamhi",
        native_table=native_identity,
        source_records=(
            SourceRecord(
                source_id="pe_senamhi",
                issuer="Servicio Nacional de Meteorología e Hidrología del Perú (SENAMHI)",
                acquisitions=acquisitions,
                evidence=tuple(
                    EvidenceReference(
                        evidence_id=item.recording_id, description="Selected SENAMHI catalogue source", recording=item
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
                source_id="pe_senamhi",
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
            external_inputs=(ExternalFactReference(source_id="pe_senamhi", fact="source.station.crs"),),
        ),
        fact_group="canonical_senamhi_crs",
    )
    for carrier, source_facts in _CATALOGUE_SOURCE_FACTS.items():
        provenance = complete_transformed_fact_universe(
            provenance,
            tuple(fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith(carrier + ".")),
            transformation=Transformation(
                name=f"SENAMHI source facts to canonical {carrier}; unsupported meanings remain unknown",
                external_inputs=tuple(
                    ExternalFactReference(source_id="pe_senamhi", fact=fact) for fact in source_facts
                ),
            ),
            fact_group=f"canonical_senamhi_{carrier}",
        )
    provenance = complete_transformed_fact_universe(
        provenance,
        ("provider.license", "provider.citation"),
        transformation=Transformation(
            name="Selected SENAMHI attribution; no inferred license",
            external_inputs=(
                ExternalFactReference(source_id="pe_senamhi", fact="source.provider.terms"),
                ExternalFactReference(source_id="pe_senamhi", fact="source.provider.attribution"),
            ),
        ),
        fact_group="canonical_senamhi_terms",
    )
    return complete_transformed_fact_universe(
        provenance,
        tuple(fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith("provider.")),
        transformation=Transformation(
            name="RivRetrieve SENAMHI identity and catalogue-only capabilities",
            kind="authored_constant",
            external_inputs=(),
        ),
        fact_group="canonical_senamhi_provider",
    )


CATALOGUE_SUPPORTING_INPUTS = {}
CATALOGUE_BUILD_DECLARATIONS = (
    ("maintenance/catalogue/pe_senamhi/official/selection.json", None),
    ("src/rivretrieve/_internal/providers/pe_senamhi/origins.py", "build_acquisition_provenance"),
    ("src/rivretrieve/_internal/providers/pe_senamhi/origins.py", "STATION_METADATA_FIELDS"),
    ("src/rivretrieve/_internal/providers/pe_senamhi/origins.py", "STATION_METADATA_NOTICE"),
    ("src/rivretrieve/_internal/providers/pe_senamhi/generate_catalogue.py", "build_catalogue"),
    ("src/rivretrieve/_internal/providers/pe_senamhi/series.py", "series_mappings"),
    ("src/rivretrieve/_internal/providers/pe_senamhi/generate_catalogue.py", "read_catalogue_sources"),
    ("src/rivretrieve/_internal/providers/pe_senamhi/station_metadata.py", "project_station_metadata"),
)
