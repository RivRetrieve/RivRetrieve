"""Austria eHYD source declarations for offline river station discovery."""

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

CRS_EVIDENCE_URL = "https://gis.lfrz.gv.at/api/geodata/i000501/ogc/features/v1/collections?f=application%2Fjson"

STATION_CATALOGUE_ORIGINS = {
    "provider_id": Authored(AuthoredValue("at_ehyd")),
    "station_id": Field(NativeColumn("hzbnr")),
    "latitude": Field(NativeColumn("latitude")),
    "longitude": Field(NativeColumn("longitude")),
    "crs": Documented(DocumentedValue("EPSG:4326"), Evidence(CRS_EVIDENCE_URL)),
}

STATION_METADATA_NOTICE = (
    "Datenquelle: ehyd.gv.at. Station metadata is published under CC BY 4.0 by the "
    "Federal Ministry of Agriculture and Forestry, Climate and Environmental Protection, "
    "Regions and Water Management (BMLUK). Source names and catchment areas remain unchanged; "
    "this metadata projection is produced by RivRetrieve."
)

OWF_METADATA_FIELDS: tuple[MetadataField, ...] = (
    MetadataField(
        "station_name",
        "name",
        source_scope="messstellen_owf",
        source_facts=("source.station.owf_registry",),
    ),
    MetadataField(
        "water_body_name",
        "gewaesser",
        source_scope="messstellen_owf",
        source_facts=("source.station.owf_registry",),
    ),
    MetadataField(
        "drainage_area",
        "orogr.Einzugsgebiet [km²]",
        "km²",
        source_scope="owf_stammdaten",
        source_facts=("source.station.owf_stammdaten",),
    ),
)

PEGEL_AKTUELL_METADATA_FIELDS: tuple[MetadataField, ...] = (
    MetadataField(
        "station_name",
        "messstelle",
        source_scope="pegel_aktuell",
        source_facts=("source.station.pegel_aktuell_registry",),
    ),
    MetadataField(
        "water_body_name",
        "gewasser",
        source_scope="pegel_aktuell",
        source_facts=("source.station.pegel_aktuell_registry",),
    ),
)

STATION_METADATA_FIELDS: tuple[MetadataField, ...] = (
    *OWF_METADATA_FIELDS,
    *PEGEL_AKTUELL_METADATA_FIELDS,
)

NATIVE_TABLE_ACQUISITION_IDS: tuple[str, ...] = (
    "at-ehyd-owf-registry",
    "at-ehyd-owf-archive",
    "at-ehyd-pegel-aktuell-registry",
)

_CATALOGUE_SOURCE_FACTS = {
    "station": (
        "source.station.owf_registry",
        "source.station.owf_stammdaten",
        "source.station.pegel_aktuell_registry",
        "source.station.documented_crs",
    ),
    "product": (
        "source.station_product.owf_associations",
        "source.station_product.pegel_aktuell_associations",
        "source.station.pegelnullpunkt_definition",
    ),
    "station_product": (
        "source.station.owf_registry",
        "source.station.pegel_aktuell_registry",
        "source.station_product.owf_associations",
        "source.station_product.pegel_aktuell_associations",
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
    """Bind selected official eHYD source evidence and derived native table to catalogue facts.

    Acquisitions and exact statements come from the verified selection. Temporal
    meanings and record bounds remain unknown in canonical catalogue products.
    """
    if any(binding.source_id != "at_ehyd" or binding.transformation is not None for binding in source_bindings):
        raise ValueError("eHYD source bindings must directly identify selected acquisitions")
    facts = tuple(fact for binding in source_bindings for fact in binding.facts)
    required = {fact for group in _CATALOGUE_SOURCE_FACTS.values() for fact in group}
    required.update(("source.provider.license", "source.provider.citation"))
    if missing := required - set(facts):
        raise ValueError(f"Missing eHYD source facts: {sorted(missing)!r}")
    if not any(statement.kind == "license" and statement.fact is not None for statement in statements):
        raise ValueError("eHYD catalogue requires selected license evidence")
    if not any(statement.kind == "citation" and statement.fact is not None for statement in statements):
        raise ValueError("eHYD catalogue requires selected citation evidence")
    provenance = AcquisitionProvenance(
        schema_version=2,
        provider_id="at_ehyd",
        native_table=native_identity,
        source_records=(
            SourceRecord(
                source_id="at_ehyd",
                issuer=(
                    "Bundesministerium für Land- und Forstwirtschaft, Klima- und Umweltschutz, "
                    "Regionen und Wasserwirtschaft (BMLUK)"
                ),
                acquisitions=acquisitions,
                evidence=tuple(
                    EvidenceReference(
                        evidence_id=item.recording_id,
                        description="Selected official eHYD catalogue source",
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
                name=f"eHYD source facts to canonical {carrier}; unestablished temporal meanings remain unknown",
                external_inputs=tuple(ExternalFactReference(source_id="at_ehyd", fact=fact) for fact in source_facts),
            ),
            fact_group=f"canonical_ehyd_{carrier}",
        )
    term_facts = tuple(statement.fact for statement in statements if statement.fact is not None)
    provenance = complete_transformed_fact_universe(
        provenance,
        ("provider.license", "provider.citation"),
        transformation=Transformation(
            name="Selected INSPIRE Austria CC BY 4.0 license and ehyd.gv.at attribution",
            external_inputs=tuple(ExternalFactReference(source_id="at_ehyd", fact=fact) for fact in term_facts),
        ),
        fact_group="canonical_ehyd_terms",
    )
    return complete_transformed_fact_universe(
        provenance,
        tuple(fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith("provider.")),
        transformation=Transformation(
            name="RivRetrieve Austria eHYD identity and catalogue-only capabilities",
            kind="authored_constant",
            external_inputs=(),
        ),
        fact_group="canonical_ehyd_provider",
    )


CATALOGUE_SUPPORTING_INPUTS: dict[str, tuple[str, ...]] = {}
CATALOGUE_BUILD_DECLARATIONS = (
    ("maintenance/catalogue/at_ehyd/official/selection.json", None),
    ("src/rivretrieve/_internal/providers/at_ehyd/origins.py", "build_acquisition_provenance"),
    ("src/rivretrieve/_internal/providers/at_ehyd/origins.py", "STATION_METADATA_FIELDS"),
    ("src/rivretrieve/_internal/providers/at_ehyd/origins.py", "STATION_METADATA_NOTICE"),
    ("src/rivretrieve/_internal/providers/at_ehyd/generate_catalogue.py", "build_catalogue"),
    ("src/rivretrieve/_internal/providers/at_ehyd/generate_catalogue.py", "read_catalogue_sources"),
    ("src/rivretrieve/_internal/providers/at_ehyd/station_metadata.py", "project_station_metadata"),
)
