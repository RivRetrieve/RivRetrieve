"""Australia BoM source declarations for offline river station discovery."""

from collections.abc import Mapping

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
    ConversionName,
    Field,
    FieldConversion,
    NativeColumn,
)
from rivretrieve._internal.catalogues.artifact import CATALOGUE_FACT_UNIVERSE
from rivretrieve._internal.catalogues.station_metadata import MetadataField

# BoM's station_georefsystem names each station's own survey datum. Geographic
# datums (WGS84, GDA94, AGD66) are copied straight into station_latitude/
# station_longitude with no reprojection -- confirmed live on 2026-11-02 by
# comparing station_latitude/longitude against the separate station_local_x/y
# fields across stations on different georefsystem values. Projected datums
# (MGA/AMG zone) are inverse-projected into geographic coordinates on the same
# underlying datum (MGA -> GDA94, AMG -> AGD66), a standard, documented
# Australian geodetic convention, not a source-stated fact about any one
# station. Unrecognised or absent labels ("---") stay "unknown", never guessed.
_GEOREFSYSTEM_TO_EPSG = {
    "WGS84": "EPSG:4326",
    "WGS84 (3D)": "EPSG:4326",
    "GDA94 2D": "EPSG:4283",
    "GDA94 3D": "EPSG:4283",
    "AGD66": "EPSG:4202",
}


def _epsg_for_georefsystem(value: str) -> str:
    if value in _GEOREFSYSTEM_TO_EPSG:
        return _GEOREFSYSTEM_TO_EPSG[value]
    if value.startswith("MGA Zone"):
        return "EPSG:4283"
    if value.startswith("AMG Zone"):
        return "EPSG:4202"
    return "unknown"


class GeorefsystemToEpsgConversion(FieldConversion):
    """Map each station's own station_georefsystem label to its EPSG code."""

    __slots__ = ()

    @property
    def name(self) -> ConversionName:
        return ConversionName("au_bom.georefsystem_to_epsg")

    def apply(
        self,
        canonical_column: str,
        native_column: NativeColumn,
        native_row: Mapping[str, object],
    ) -> object:
        if canonical_column != "crs":
            raise ValueError("au_bom georefsystem conversion is only defined for crs")
        value = native_row[str(native_column)]
        if not isinstance(value, str):
            raise ValueError("station_georefsystem must be a string")
        return _epsg_for_georefsystem(value)


STATION_CATALOGUE_ORIGINS = {
    "provider_id": Authored(AuthoredValue("au_bom")),
    "station_id": Field(NativeColumn("station_no")),
    "latitude": Field(NativeColumn("station_latitude")),
    "longitude": Field(NativeColumn("station_longitude")),
    "crs": Field(NativeColumn("station_georefsystem"), GeorefsystemToEpsgConversion()),
}

STATION_METADATA_NOTICE = (
    "Station metadata from the Bureau of Meteorology's Water Data Online KiWIS service "
    "(waterdata.bom.gov.au). BoM's Water Data Online portal states its material is licensed "
    "under the Creative Commons Attribution Australia Licence unless otherwise noted; BoM's "
    "general copyright page separately prefers the attribution: 'Bureau of Meteorology, "
    "© Commonwealth of Australia. Licensed from the Commonwealth of Australia under a "
    "Creative Commons Attribution 4.0 International licence.' Source names remain unchanged; "
    "this metadata projection is produced by RivRetrieve."
)

STATION_METADATA_FIELDS: tuple[MetadataField, ...] = (MetadataField("station_name", "station_name"),)

NATIVE_TABLE_ACQUISITION_IDS: tuple[str, ...] = ("station_lists",)

# Canonical catalogue facts this provider must bind, grouped by the catalogue
# schema prefix they close (CATALOGUE_FACT_UNIVERSE = provider.* | product.* |
# station.* | station_product.*).
_CATALOGUE_SOURCE_FACTS = {
    "station": (
        "source.station.station_list",
        "source.station.georefsystem_documented",
    ),
    "product": (
        "source.product.timeseries_list_units",
        "source.product.parameter_type_list",
    ),
    "station_product": ("source.station_product.timeseries_list_witnessed",),
}


def build_acquisition_provenance(
    native_identity: NativeTableIdentity,
    recordings: tuple[RecordingReference, ...],
    *,
    acquisitions: tuple[AcquisitionRecord, ...],
    source_bindings: tuple[FactBinding, ...],
    statements: tuple[SourceStatement, ...] = (),
) -> AcquisitionProvenance:
    """Bind selected official BoM source evidence and derived native table to catalogue facts.

    Acquisitions and exact statements come from the verified selection. BoM does
    not document a time zone name, a stage vertical datum, or whether quality
    codes carry a redistribution implication; these remain unknown in canonical
    catalogue products rather than being inferred here.
    """
    if any(binding.source_id != "au_bom" or binding.transformation is not None for binding in source_bindings):
        raise ValueError("BoM source bindings must directly identify selected acquisitions")
    facts = tuple(fact for binding in source_bindings for fact in binding.facts)
    required = {fact for group in _CATALOGUE_SOURCE_FACTS.values() for fact in group}
    required.update(("source.provider.license", "source.provider.citation"))
    if missing := required - set(facts):
        raise ValueError(f"Missing BoM source facts: {sorted(missing)!r}")
    if not any(statement.kind == "license" and statement.fact is not None for statement in statements):
        raise ValueError("au_bom catalogue requires selected license evidence")
    if not any(statement.kind == "citation" and statement.fact is not None for statement in statements):
        raise ValueError("au_bom catalogue requires selected citation evidence")
    provenance = AcquisitionProvenance(
        schema_version=2,
        provider_id="au_bom",
        native_table=native_identity,
        source_records=(
            SourceRecord(
                source_id="au_bom",
                issuer="Bureau of Meteorology (Commonwealth of Australia)",
                operator="Water Data Online, KiWIS web service",
                acquisitions=acquisitions,
                evidence=tuple(
                    EvidenceReference(
                        evidence_id=item.recording_id,
                        description="Selected official BoM Water Data Online catalogue source",
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
                name=f"BoM source facts to canonical {carrier}; unestablished facts remain unknown",
                external_inputs=tuple(ExternalFactReference(source_id="au_bom", fact=fact) for fact in source_facts),
            ),
            fact_group=f"canonical_au_bom_{carrier}",
        )
    term_facts = tuple(statement.fact for statement in statements if statement.fact is not None)
    provenance = complete_transformed_fact_universe(
        provenance,
        ("provider.license", "provider.citation"),
        transformation=Transformation(
            name="Selected BoM Water Data Online licence and attribution statements",
            external_inputs=tuple(ExternalFactReference(source_id="au_bom", fact=fact) for fact in term_facts),
        ),
        fact_group="canonical_au_bom_terms",
    )
    return complete_transformed_fact_universe(
        provenance,
        tuple(fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith("provider.")),
        transformation=Transformation(
            name="RivRetrieve Australia BoM identity and catalogue-only capabilities",
            kind="authored_constant",
            external_inputs=(),
        ),
        fact_group="canonical_au_bom_provider",
    )


CATALOGUE_SUPPORTING_INPUTS: dict[str, tuple[str, ...]] = {}
CATALOGUE_BUILD_DECLARATIONS = (
    ("maintenance/catalogue/au_bom/official/catalogue.json", None),
    ("maintenance/catalogue/station_metadata/review.json", None),
    ("src/rivretrieve/_internal/providers/au_bom/origins.py", "build_acquisition_provenance"),
    ("src/rivretrieve/_internal/providers/au_bom/origins.py", "STATION_METADATA_FIELDS"),
    ("src/rivretrieve/_internal/providers/au_bom/origins.py", "STATION_METADATA_NOTICE"),
    ("src/rivretrieve/_internal/providers/au_bom/generate_catalogue.py", "build_catalogue"),
    ("src/rivretrieve/_internal/providers/au_bom/generate_catalogue.py", "read_catalogue_sources"),
    ("src/rivretrieve/_internal/providers/au_bom/catalogue_series.py", "describe_catalogue"),
)
