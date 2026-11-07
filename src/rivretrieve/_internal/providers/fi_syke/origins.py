"""Finland SYKE source declarations for offline river station discovery."""

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

# SYKE's own TauluKuvaus/SarakeKuvaus description fields are null for every one of
# Paikka's coordinate columns (confirmed live 2026-11-07) -- the source never labels
# which coordinate pair is "the" datum. Cross-checking the actual published numbers
# with pyproj (not the field names) showed KoordYk/KoordPk/KoordLat/KoordLong are the
# same legacy KKJ/Hayford-1924 point in three encodings, while KoordErTm (ETRS-TM35FIN,
# EPSG:3067) is a genuinely different modern datum (ETRS89), offset ~200m -- matching
# Finland's documented official KKJ->ETRS89 shift, not source noise. ETRS89 is
# Finland's current national standard (KKJ superseded circa 2005); this choice is a
# standard, documented Finnish geodetic convention, not a source-stated fact about any
# one station -- the same epistemic shape as au_bom's MGA/AMG zone handling.


class ConstantCrsConversion(FieldConversion):
    """Every fi_syke station publishes ETRS-TM35FIN coordinates; the inverse-projected
    datum (ETRS89, EPSG:4258) is therefore constant, grounded in KoordErTmIta's
    presence rather than its numeric value."""

    __slots__ = ()

    @property
    def name(self) -> ConversionName:
        return ConversionName("fi_syke.ertm_to_etrs89_crs")

    def apply(
        self,
        canonical_column: str,
        native_column: NativeColumn,
        native_row: Mapping[str, object],
    ) -> object:
        if canonical_column != "crs":
            raise ValueError("fi_syke CRS conversion is only defined for crs")
        if native_row[str(native_column)] is None:
            raise ValueError("fi_syke station is missing its ETRS-TM35FIN coordinate")
        return "EPSG:4258"


STATION_CATALOGUE_ORIGINS = {
    "provider_id": Authored(AuthoredValue("fi_syke")),
    "station_id": Field(NativeColumn("Paikka_Id")),
    "latitude": Field(NativeColumn("latitude_etrs89")),
    "longitude": Field(NativeColumn("longitude_etrs89")),
    "crs": Field(NativeColumn("KoordErTmIta"), ConstantCrsConversion()),
}

STATION_METADATA_NOTICE = (
    "Station metadata from the Finnish Environment Institute's (Syke) hydrology OData service, "
    "Hydrologiarajapinta (rajapinnat.ymparisto.fi). Syke's open data, including this API, is "
    "licensed under Creative Commons Attribution 4.0 International; Syke's own worked example "
    "is 'Source: Finnish Environment Institute (Syke)'. Source names remain unchanged; this "
    "metadata projection is produced by RivRetrieve."
)

STATION_METADATA_FIELDS: tuple[MetadataField, ...] = (
    MetadataField("station_name", "Nimi"),
    MetadataField("water_body_name", "VesalNimi"),
    MetadataField("water_body_name", "PaaVesalNimi"),
)

NATIVE_TABLE_ACQUISITION_IDS: tuple[str, ...] = ("paikka_site_list",)

# Canonical catalogue facts this provider must bind, grouped by the catalogue
# schema prefix they close (CATALOGUE_FACT_UNIVERSE = provider.* | product.* |
# station.* | station_product.*).
_CATALOGUE_SOURCE_FACTS = {
    "station": (
        "source.station.paikka_site_list",
        "source.station.ertm_coordinates",
    ),
    "product": (
        "source.product.suure_catalogue",
        "source.product.taulukuvaus_description",
    ),
    "station_product": ("source.station_product.paikka_suure_witnessed",),
}


def build_acquisition_provenance(
    native_identity: NativeTableIdentity,
    recordings: tuple[RecordingReference, ...],
    *,
    acquisitions: tuple[AcquisitionRecord, ...],
    source_bindings: tuple[FactBinding, ...],
    statements: tuple[SourceStatement, ...] = (),
) -> AcquisitionProvenance:
    """Bind selected official SYKE source evidence and derived native table to catalogue facts.

    Acquisitions and exact statements come from the verified selection. SYKE does not
    document a time zone name, whether a daily value is a mean, or the applicability
    of each site's own stage-datum correction; these remain unknown in canonical
    catalogue products rather than being inferred here.
    """
    if any(binding.source_id != "fi_syke" or binding.transformation is not None for binding in source_bindings):
        raise ValueError("SYKE source bindings must directly identify selected acquisitions")
    facts = tuple(fact for binding in source_bindings for fact in binding.facts)
    required = {fact for group in _CATALOGUE_SOURCE_FACTS.values() for fact in group}
    required.update(("source.provider.license", "source.provider.citation"))
    if missing := required - set(facts):
        raise ValueError(f"Missing SYKE source facts: {sorted(missing)!r}")
    if not any(statement.kind == "license" and statement.fact is not None for statement in statements):
        raise ValueError("fi_syke catalogue requires selected license evidence")
    if not any(statement.kind == "citation" and statement.fact is not None for statement in statements):
        raise ValueError("fi_syke catalogue requires selected citation evidence")
    provenance = AcquisitionProvenance(
        schema_version=2,
        provider_id="fi_syke",
        native_table=native_identity,
        source_records=(
            SourceRecord(
                source_id="fi_syke",
                issuer="Finnish Environment Institute (Suomen ympäristökeskus, Syke)",
                operator="Hydrologiarajapinta OData service",
                acquisitions=acquisitions,
                evidence=tuple(
                    EvidenceReference(
                        evidence_id=item.recording_id,
                        description="Selected official SYKE Hydrologiarajapinta catalogue source",
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
                name=f"SYKE source facts to canonical {carrier}; unestablished facts remain unknown",
                external_inputs=tuple(ExternalFactReference(source_id="fi_syke", fact=fact) for fact in source_facts),
            ),
            fact_group=f"canonical_fi_syke_{carrier}",
        )
    term_facts = tuple(statement.fact for statement in statements if statement.fact is not None)
    provenance = complete_transformed_fact_universe(
        provenance,
        ("provider.license", "provider.citation"),
        transformation=Transformation(
            name="Selected SYKE license and attribution statements",
            external_inputs=tuple(ExternalFactReference(source_id="fi_syke", fact=fact) for fact in term_facts),
        ),
        fact_group="canonical_fi_syke_terms",
    )
    return complete_transformed_fact_universe(
        provenance,
        tuple(fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith("provider.")),
        transformation=Transformation(
            name="RivRetrieve Finland SYKE identity and catalogue-only capabilities",
            kind="authored_constant",
            external_inputs=(),
        ),
        fact_group="canonical_fi_syke_provider",
    )


CATALOGUE_SUPPORTING_INPUTS: dict[str, tuple[str, ...]] = {}
CATALOGUE_BUILD_DECLARATIONS = (
    ("maintenance/catalogue/fi_syke/official/catalogue.json", None),
    ("maintenance/catalogue/station_metadata/review.json", None),
    ("src/rivretrieve/_internal/providers/fi_syke/origins.py", "build_acquisition_provenance"),
    ("src/rivretrieve/_internal/providers/fi_syke/origins.py", "STATION_METADATA_FIELDS"),
    ("src/rivretrieve/_internal/providers/fi_syke/origins.py", "STATION_METADATA_NOTICE"),
    ("src/rivretrieve/_internal/providers/fi_syke/generate_catalogue.py", "build_catalogue"),
    ("src/rivretrieve/_internal/providers/fi_syke/generate_catalogue.py", "read_catalogue_sources"),
    ("src/rivretrieve/_internal/providers/fi_syke/catalogue_series.py", "describe_catalogue"),
)
