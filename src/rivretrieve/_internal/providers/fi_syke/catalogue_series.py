"""Publisher field definitions for SYKE catalogue-only discovery."""

from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.catalogues.source_series import SourceDescription, SourceDescriptions
from rivretrieve._internal.providers.fi_syke.series import (
    _BY_PRODUCT_ID,
    _NATIVE_UNIT,
    _NORMALIZED_NATIVE_UNIT,
    _PAIKKA_EVIDENCE,
    _TAULUKUVAUS_EVIDENCE,
    _VEDENKORKEUS_EXTREMES_EVIDENCE,
    _VEDENKTASOTIETO_EVIDENCE,
)
from rivretrieve._internal.source_series import (
    ClippingAxis,
    EvidenceFact,
    EvidenceState,
    PhysicalFacts,
    SourceIdentity,
    known,
)


def describe_catalogue(artifact: PackagedCatalogArtifact) -> SourceDescriptions:
    """Step 1/2 established frequency and native units; step 3 (#755) still owes
    statistic, temporal support, day definition, timestamp anchor and time zone --
    TauluKuvaus states none of them (confirmed live), so they stay source_silent
    rather than guessed. Step 3 does establish stage's vertical_reference: SYKE
    publishes Vedenkorkeus as an absolute water-surface elevation (observed range
    -223 to 24,469 cm across active stations, matching Finland's coast-to-Lapland
    relief, independently corroborated by VedenkTasoTieto's per-site datum
    corrections), not a small gauge-relative reading."""
    descriptions = []
    for row in artifact.products.iter_rows(named=True):
        product = row["product_id"]
        definition = _BY_PRODUCT_ID[product]
        if product == "stage_reported":
            vertical_reference = EvidenceFact(
                value="above_sea_level",
                state=EvidenceState.KNOWN,
                evidence=(_VEDENKORKEUS_EXTREMES_EVIDENCE, _VEDENKTASOTIETO_EVIDENCE),
            )
        else:
            vertical_reference = EvidenceFact(state=EvidenceState.NOT_ESTABLISHED)
        facts = PhysicalFacts(
            facts_id=product,
            quantity=known(definition.quantity, _TAULUKUVAUS_EVIDENCE),
            source_unit=known(_NATIVE_UNIT[product], _TAULUKUVAUS_EVIDENCE),
            normalized_unit=_NORMALIZED_NATIVE_UNIT[product],
            frequency=known(definition.frequency, _PAIKKA_EVIDENCE),
            statistic=EvidenceFact(state=EvidenceState.SOURCE_SILENT),
            temporal_support=EvidenceFact(state=EvidenceState.SOURCE_SILENT),
            timestamp_anchor=EvidenceFact(state=EvidenceState.SOURCE_SILENT),
            time_zone=EvidenceFact(state=EvidenceState.SOURCE_SILENT),
            vertical_reference=vertical_reference,
            clipping_axis=ClippingAxis.CALENDAR_DATE,
            label_time="00:00:00",
        )
        descriptions.append(
            SourceDescription(
                product_id=product,
                native_coordinate=row["native_id"],
                identity=SourceIdentity(
                    namespace=f"fi_syke/{product}",
                    origin="catalogue",
                    description=(
                        "SYKE Hydrologiarajapinta entity set; per-station series identity is resolved by "
                        "station_id (Paikka_Id), which witnesses exactly one product per row"
                    ),
                    evidence=(_TAULUKUVAUS_EVIDENCE, _PAIKKA_EVIDENCE),
                ),
                facts=(facts,),
            )
        )
    return SourceDescriptions(provider_id="fi_syke", descriptions=tuple(descriptions))
