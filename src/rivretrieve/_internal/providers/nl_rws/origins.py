"""Netherlands Rijkswaterstaat (nl_rws) source declarations for offline discovery."""

from __future__ import annotations

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


class Etrs89CrsConversion(FieldConversion):
    """Map DDAPI 2.0 ``Coordinatenstelsel = 'ETRS89'`` to ``EPSG:4258``."""

    __slots__ = ()

    @property
    def name(self) -> ConversionName:
        return ConversionName("nl_rws.etrs89_to_epsg4258")

    def apply(
        self,
        canonical_column: str,
        native_column: NativeColumn,
        native_row: Mapping[str, object],
    ) -> object:
        if canonical_column != "crs":
            raise ValueError("nl_rws CRS conversion is only defined for crs")
        value = native_row[str(native_column)]
        if value != "ETRS89":
            raise ValueError(f"nl_rws station has unexpected Coordinatenstelsel: {value!r}")
        return "EPSG:4258"


STATION_CATALOGUE_ORIGINS = {
    "provider_id": Authored(AuthoredValue("nl_rws")),
    "station_id": Field(NativeColumn("Code")),
    "latitude": Field(NativeColumn("Lat")),
    "longitude": Field(NativeColumn("Lon")),
    "crs": Field(NativeColumn("Coordinatenstelsel"), Etrs89CrsConversion()),
}

STATION_METADATA_NOTICE = (
    "Station metadata from Rijkswaterstaat Waterwebservices DDAPI 2.0 "
    "(https://ddapi20-waterwebservices.rijkswaterstaat.nl). Published under "
    "Public Domain Mark 1.0 / CC0 1.0 (https://www.rijkswaterstaat.nl/copyright, "
    "https://data.overheid.nl/dataset/9442-waterinfo-rijkswateren); recommended "
    "attribution is 'Bron: Rijkswaterstaat – Waterwebservices'. Source station "
    "names remain unchanged; this metadata projection is produced by RivRetrieve."
)

STATION_METADATA_FIELDS: tuple[MetadataField, ...] = (MetadataField("station_name", "Naam"),)

CATALOGUE_BUILD_DECLARATIONS = (
    ("maintenance/catalogue/station_metadata/review.json", None),
    ("src/rivretrieve/_internal/providers/nl_rws/origins.py", "build_acquisition_provenance"),
    ("src/rivretrieve/_internal/providers/nl_rws/origins.py", "STATION_METADATA_FIELDS"),
    ("src/rivretrieve/_internal/providers/nl_rws/origins.py", "STATION_METADATA_NOTICE"),
    ("src/rivretrieve/_internal/providers/nl_rws/generate_catalogue.py", "build_catalogue"),
    ("src/rivretrieve/_internal/providers/nl_rws/catalogue_series.py", "describe_catalogue"),
)

NATIVE_TABLE_ACQUISITION_IDS: tuple[str, ...] = ("nl_rws_catalogus_2026_11_25",)

CATALOGUE_SUPPORTING_INPUTS: dict[str, tuple[str, ...]] = {}

_CATALOGUE_SOURCE_FACTS = {
    "station": (
        "source.station.ophalen_catalogus_locations",
        "source.station.etrs89_coordinates",
    ),
    "product": ("source.product.aquo_metadata_catalogue",),
    "station_product": ("source.station_product.aquo_metadata_location_links",),
}


def build_acquisition_provenance(
    native_identity: NativeTableIdentity,
    recordings: tuple[RecordingReference, ...],
    *,
    acquisitions: tuple[AcquisitionRecord, ...],
    source_bindings: tuple[FactBinding, ...],
    statements: tuple[SourceStatement, ...] = (),
) -> AcquisitionProvenance:
    """Bind selected official Rijkswaterstaat DDAPI 2.0 evidence to catalogue facts."""
    if any(binding.source_id != "nl_rws" or binding.transformation is not None for binding in source_bindings):
        raise ValueError("nl_rws source bindings must directly identify selected acquisitions")
    facts = tuple(fact for binding in source_bindings for fact in binding.facts)
    required = {fact for group in _CATALOGUE_SOURCE_FACTS.values() for fact in group}
    required.update(("source.provider.license", "source.provider.citation"))
    if missing := required - set(facts):
        raise ValueError(f"Missing nl_rws source facts: {sorted(missing)!r}")
    if not any(statement.kind == "license" and statement.fact is not None for statement in statements):
        raise ValueError("nl_rws catalogue requires selected license evidence")
    if not any(statement.kind == "citation" and statement.fact is not None for statement in statements):
        raise ValueError("nl_rws catalogue requires selected citation evidence")

    provenance = AcquisitionProvenance(
        schema_version=2,
        provider_id="nl_rws",
        native_table=native_identity,
        source_records=(
            SourceRecord(
                source_id="nl_rws",
                issuer="Rijkswaterstaat (Ministerie van Infrastructuur en Waterstaat)",
                operator="Rijkswaterstaat Waterwebservices DDAPI 2.0",
                acquisitions=acquisitions,
                evidence=tuple(
                    EvidenceReference(
                        evidence_id=item.recording_id,
                        description="Selected official Rijkswaterstaat catalogue source",
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
                name=f"nl_rws DDAPI 2.0 source facts to canonical {carrier}; unestablished facts remain unknown",
                external_inputs=tuple(ExternalFactReference(source_id="nl_rws", fact=fact) for fact in source_facts),
            ),
            fact_group=f"canonical_nl_rws_{carrier}",
        )
    term_facts = tuple(statement.fact for statement in statements if statement.fact is not None)
    provenance = complete_transformed_fact_universe(
        provenance,
        ("provider.license", "provider.citation"),
        transformation=Transformation(
            name="Selected Rijkswaterstaat Public Domain Mark 1.0 / CC0 1.0 terms and attribution",
            external_inputs=tuple(ExternalFactReference(source_id="nl_rws", fact=fact) for fact in term_facts),
        ),
        fact_group="canonical_nl_rws_terms",
    )
    return complete_transformed_fact_universe(
        provenance,
        tuple(fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith("provider.")),
        transformation=Transformation(
            name="RivRetrieve Netherlands Rijkswaterstaat identity and offline catalogue capabilities",
            kind="authored_constant",
            external_inputs=(),
        ),
        fact_group="canonical_nl_rws_provider",
    )
