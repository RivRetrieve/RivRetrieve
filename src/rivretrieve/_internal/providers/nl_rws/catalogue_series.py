"""Publisher product definitions and catalogue-only series descriptions for nl_rws."""

from __future__ import annotations

from dataclasses import dataclass

from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.catalogues.source_series import SourceDescription, SourceDescriptions
from rivretrieve._internal.source_series import (
    ClippingAxis,
    EvidenceFact,
    EvidenceState,
    PhysicalFacts,
    SourceIdentity,
    known,
)

CATALOGUS_EVIDENCE = "https://ddapi20-waterwebservices.rijkswaterstaat.nl/METADATASERVICES/OphalenCatalogus"
AQUO_GEM24H_EVIDENCE = "Aquo WaardeBewerkingsMethode GEM24H (Etmaalgemiddelde) in OphalenCatalogus"


@dataclass(frozen=True)
class ProductDefinition:
    product_id: str
    observed_property: str
    frequency: str
    statistic: str
    canonical_unit: str
    native_unit: str
    normalized_native_unit: str
    native_id: str
    quantity: str
    grootheid: str
    eenheid: str
    hoedanigheid: str
    waarde_bewerkings_methode: str
    vertical_reference: str | None = None
    vertical_datum: str | None = None


PRODUCT_DEFINITIONS: tuple[ProductDefinition, ...] = (
    ProductDefinition(
        product_id="discharge_m3s_nvt",
        observed_property="discharge",
        frequency="unknown",
        statistic="unknown",
        canonical_unit="m3/s",
        native_unit="m3/s",
        normalized_native_unit="m3/s",
        native_id="OW:Q:m3/s:NVT:NVT",
        quantity="discharge",
        grootheid="Q",
        eenheid="m3/s",
        hoedanigheid="NVT",
        waarde_bewerkings_methode="NVT",
    ),
    ProductDefinition(
        product_id="discharge_m3s_gem24h",
        observed_property="discharge",
        frequency="P1D",
        statistic="mean",
        canonical_unit="m3/s",
        native_unit="m3/s",
        normalized_native_unit="m3/s",
        native_id="OW:Q:m3/s:NVT:GEM24H",
        quantity="discharge",
        grootheid="Q",
        eenheid="m3/s",
        hoedanigheid="NVT",
        waarde_bewerkings_methode="GEM24H",
    ),
    ProductDefinition(
        product_id="discharge_m3d_nvt",
        observed_property="discharge",
        frequency="unknown",
        statistic="unknown",
        canonical_unit="m3/s",
        native_unit="m3/d",
        normalized_native_unit="m3/d",
        native_id="OW:Q:m3/d:NVT:NVT",
        quantity="discharge",
        grootheid="Q",
        eenheid="m3/d",
        hoedanigheid="NVT",
        waarde_bewerkings_methode="NVT",
    ),
    ProductDefinition(
        product_id="stage_nap_nvt",
        observed_property="stage",
        frequency="unknown",
        statistic="unknown",
        canonical_unit="m",
        native_unit="cm",
        normalized_native_unit="cm",
        native_id="OW:WATHTE:cm:NAP:NVT",
        quantity="stage",
        grootheid="WATHTE",
        eenheid="cm",
        hoedanigheid="NAP",
        waarde_bewerkings_methode="NVT",
        vertical_reference="above_sea_level",
        vertical_datum="NAP",
    ),
    ProductDefinition(
        product_id="stage_nap_gem24h",
        observed_property="stage",
        frequency="P1D",
        statistic="mean",
        canonical_unit="m",
        native_unit="cm",
        normalized_native_unit="cm",
        native_id="OW:WATHTE:cm:NAP:GEM24H",
        quantity="stage",
        grootheid="WATHTE",
        eenheid="cm",
        hoedanigheid="NAP",
        waarde_bewerkings_methode="GEM24H",
        vertical_reference="above_sea_level",
        vertical_datum="NAP",
    ),
    ProductDefinition(
        product_id="stage_plaatslr_nvt",
        observed_property="stage",
        frequency="unknown",
        statistic="unknown",
        canonical_unit="m",
        native_unit="cm",
        normalized_native_unit="cm",
        native_id="OW:WATHTE:cm:PLAATSLR:NVT",
        quantity="stage",
        grootheid="WATHTE",
        eenheid="cm",
        hoedanigheid="PLAATSLR",
        waarde_bewerkings_methode="NVT",
        vertical_reference=None,
        vertical_datum="PLAATSLR",
    ),
    ProductDefinition(
        product_id="stage_msl_nvt",
        observed_property="stage",
        frequency="unknown",
        statistic="unknown",
        canonical_unit="m",
        native_unit="cm",
        normalized_native_unit="cm",
        native_id="OW:WATHTE:cm:MSL:NVT",
        quantity="stage",
        grootheid="WATHTE",
        eenheid="cm",
        hoedanigheid="MSL",
        waarde_bewerkings_methode="NVT",
        vertical_reference="above_sea_level",
        vertical_datum="MSL",
    ),
    ProductDefinition(
        product_id="stage_taw_nvt",
        observed_property="stage",
        frequency="unknown",
        statistic="unknown",
        canonical_unit="m",
        native_unit="cm",
        normalized_native_unit="cm",
        native_id="OW:WATHTE:cm:TAW:NVT",
        quantity="stage",
        grootheid="WATHTE",
        eenheid="cm",
        hoedanigheid="TAW",
        waarde_bewerkings_methode="NVT",
        vertical_reference="above_sea_level",
        vertical_datum="TAW",
    ),
    ProductDefinition(
        product_id="water_temperature_nvt",
        observed_property="water_temperature",
        frequency="unknown",
        statistic="unknown",
        canonical_unit="degC",
        native_unit="oC",
        normalized_native_unit="degC",
        native_id="OW:T:oC:NVT:NVT",
        quantity="temperature",
        grootheid="T",
        eenheid="oC",
        hoedanigheid="NVT",
        waarde_bewerkings_methode="NVT",
    ),
    ProductDefinition(
        product_id="water_temperature_gem24h",
        observed_property="water_temperature",
        frequency="P1D",
        statistic="mean",
        canonical_unit="degC",
        native_unit="oC",
        normalized_native_unit="degC",
        native_id="OW:T:oC:NVT:GEM24H",
        quantity="temperature",
        grootheid="T",
        eenheid="oC",
        hoedanigheid="NVT",
        waarde_bewerkings_methode="GEM24H",
    ),
)

PRODUCT_BY_ID: dict[str, ProductDefinition] = {d.product_id: d for d in PRODUCT_DEFINITIONS}

ADMITTED_PRODUCT_KEY_TO_ID: dict[tuple[str, str, str, str], str] = {
    (d.grootheid, d.eenheid, d.hoedanigheid, d.waarde_bewerkings_methode): d.product_id for d in PRODUCT_DEFINITIONS
}


def describe_catalogue(artifact: PackagedCatalogArtifact) -> SourceDescriptions:
    """Build catalogue-tier source descriptions for nl_rws offline discovery.

    Unestablished temporal facts (NVT cadence/statistic, GEM24H day anchor, and
    PLAATSLR reference semantics) stay ``not_established`` until Step 3 (#1050).
    """
    descriptions: list[SourceDescription] = []
    for row in artifact.products.iter_rows(named=True):
        product_id = str(row["product_id"])
        definition = PRODUCT_BY_ID[product_id]
        frequency = (
            known(definition.frequency, AQUO_GEM24H_EVIDENCE)
            if definition.frequency != "unknown"
            else EvidenceFact(state=EvidenceState.NOT_ESTABLISHED)
        )
        statistic = (
            known(definition.statistic, AQUO_GEM24H_EVIDENCE)
            if definition.statistic != "unknown"
            else EvidenceFact(state=EvidenceState.NOT_ESTABLISHED)
        )
        vertical_reference = (
            known(definition.vertical_reference, CATALOGUS_EVIDENCE)
            if definition.vertical_reference is not None
            else EvidenceFact(state=EvidenceState.NOT_ESTABLISHED)
        )
        vertical_datum = (
            known(definition.vertical_datum, CATALOGUS_EVIDENCE)
            if definition.vertical_datum is not None
            else EvidenceFact(state=EvidenceState.NOT_ESTABLISHED)
        )
        facts = PhysicalFacts(
            facts_id=product_id,
            quantity=known(definition.quantity, CATALOGUS_EVIDENCE),
            source_unit=known(definition.native_unit, CATALOGUS_EVIDENCE),
            normalized_unit=definition.normalized_native_unit,
            frequency=frequency,
            statistic=statistic,
            temporal_support=EvidenceFact(state=EvidenceState.NOT_ESTABLISHED),
            day_definition=EvidenceFact(state=EvidenceState.NOT_ESTABLISHED),
            timestamp_anchor=EvidenceFact(state=EvidenceState.NOT_ESTABLISHED),
            time_zone=EvidenceFact(state=EvidenceState.NOT_ESTABLISHED),
            vertical_reference=vertical_reference,
            vertical_datum=vertical_datum,
            clipping_axis=ClippingAxis.SOURCE_TIMESTAMP,
        )
        descriptions.append(
            SourceDescription(
                product_id=product_id,
                native_coordinate=row["native_id"],
                identity=SourceIdentity(
                    namespace=f"nl_rws/{product_id}",
                    origin="catalogue",
                    description=(
                        "Rijkswaterstaat DDAPI 2.0 AquoMetadata physical/aggregation product "
                        "(Compartiment=OW, ProcesType=meting, Groepering=''); distinct "
                        "WaardeBepalingsMethode series are separated at retrieval/parse time"
                    ),
                    evidence=(CATALOGUS_EVIDENCE,),
                ),
                facts=(facts,),
            )
        )
    return SourceDescriptions(provider_id="nl_rws", descriptions=tuple(descriptions))
