"""Official Swiss catalogue origins and explicitly selected acquisition evidence."""

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

# Name mappings require genuine-input validation and owner disclosure approval
# before generated metadata can be packaged. Native presence is insufficient.
STATION_METADATA_FIELDS: tuple[MetadataField, ...] = (
    MetadataField(
        "station_name",
        "data-name",
        source_scope="station_directory",
        source_facts=("source.station.foen_directory_identity_and_names",),
    ),
    MetadataField(
        "water_body_name",
        "data-hydro-body",
        source_scope="station_directory",
        source_facts=("source.station.foen_directory_identity_and_names",),
    ),
    MetadataField(
        "drainage_area",
        "Catchment size",
        "km2",
        source_scope="station_page",
        source_facts=("source.station.foen_reference_altitude_and_catchment",),
    ),
    MetadataField(
        "elevation",
        "Station altitude",
        "m",
        datum="LN02",
        source_scope="station_page",
        source_facts=("source.station.foen_reference_altitude_and_catchment",),
        support_facts=("source.station.foen_altitude_unit_datum_definition",),
        datum_support=("source.station.foen_altitude_unit_datum_definition",),
    ),
)

STATION_METADATA_NOTICE = (
    "Station metadata is from the Federal Office for the Environment (FOEN). "
    "Names and station-information text remain unchanged. "
    "This metadata projection is produced by RivRetrieve."
)

CRS_EVIDENCE_URL = "https://data.bafu.admin.ch/dataproduct-water-observations"
STATION_CATALOGUE_ORIGINS = {
    "provider_id": Authored(AuthoredValue("ch_foen")),
    "station_id": Field(NativeColumn("no")),
    "latitude": Field(NativeColumn("latitude")),
    "longitude": Field(NativeColumn("longitude")),
    "crs": Documented(DocumentedValue("EPSG:4326"), Evidence(CRS_EVIDENCE_URL)),
}

_CATALOGUE_SOURCE_FACTS = {
    "station": (
        "source.station.native_identity",
        "source.station.native_geometry",
        "source.station.documented_crs",
    ),
    "product": ("source.product.native_physics",),
    "station_product": (
        "source.station.native_identity",
        "source.station_product.source_associations",
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
    """Bind selected official source evidence to the Swiss catalogue.

    Parameters
    ----------
    native_identity
        Identity of the derived native table selected for this build.
    recordings
        Selected original responses and documentation, with their exact identities.
    acquisitions
        Acquisition records claiming the selected recordings, including any page campaigns.
    source_bindings
        Direct ``ch_foen`` bindings for station identity, geometry, CRS, physical facts,
        and source associations. Unresolved temporal fields remain an authored limitation.
        Approved station metadata uses its existing source fact names.
    statements
        An exact license statement is required. Citation wording is optional;
        an unestablished citation remains null, without claiming source silence.

    Returns
    -------
    AcquisitionProvenance
        Closed source and canonical fact bindings. This pure operation does not
        verify bytes, select archive members or approve metadata disclosure.

    Raises
    ------
    ValueError
        If required source facts are missing or supplied relations do not close.
    """
    if any(binding.source_id != "ch_foen" or binding.transformation is not None for binding in source_bindings):
        raise ValueError("Official source bindings must directly name ch_foen acquisitions")
    facts = tuple(fact for binding in source_bindings for fact in binding.facts)
    required = {fact for group in _CATALOGUE_SOURCE_FACTS.values() for fact in group}
    if missing := required - set(facts):
        raise ValueError(f"Missing official catalogue source facts: {sorted(missing)!r}")
    provenance = AcquisitionProvenance(
        schema_version=2,
        provider_id="ch_foen",
        native_table=native_identity,
        source_records=(
            SourceRecord(
                source_id="ch_foen",
                issuer="Federal Office for the Environment (FOEN)",
                acquisitions=acquisitions,
                evidence=tuple(
                    EvidenceReference(
                        evidence_id=recording.recording_id,
                        description="Selected official FOEN catalogue source",
                        recording=recording,
                    )
                    for recording in recordings
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
                name=(
                    f"Official FOEN source facts to canonical {carrier} fields; "
                    "selected evidence leaves temporal support and record bounds unresolved"
                ),
                external_inputs=tuple(ExternalFactReference(source_id="ch_foen", fact=fact) for fact in source_facts),
            ),
            fact_group=f"canonical_foen_{carrier}",
        )
    term_facts = tuple(statement.fact for statement in statements if statement.fact is not None)
    if not any(statement.kind == "license" and statement.fact is not None for statement in statements):
        raise ValueError("Official catalogue requires selected license evidence")
    provenance = complete_transformed_fact_universe(
        provenance,
        ("provider.license", "provider.citation"),
        transformation=Transformation(
            name="Selected FOEN terms statements; unestablished licence or citation remains null",
            external_inputs=tuple(ExternalFactReference(source_id="ch_foen", fact=fact) for fact in term_facts),
        ),
        fact_group="canonical_foen_terms",
    )
    return complete_transformed_fact_universe(
        provenance,
        tuple(fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith("provider.")),
        transformation=Transformation(
            name="RivRetrieve Swiss provider identity and catalogue capabilities",
            kind="authored_constant",
            external_inputs=(),
        ),
        fact_group="canonical_foen_provider",
    )
