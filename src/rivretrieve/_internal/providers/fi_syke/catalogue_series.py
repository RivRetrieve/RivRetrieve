"""Publisher field definitions for SYKE catalogue-only discovery."""

from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.catalogues.source_series import SourceDescription, SourceDescriptions
from rivretrieve._internal.source_series import EvidenceFact, EvidenceState, PhysicalFacts, SourceIdentity, known

# Evidence pointers name the retained capture, not a replay fixture (fi_syke is
# CatalogueOnly; no fetch.py/parse.py or recordings exist yet).
_TAULUKUVAUS_EVIDENCE = "maintenance/catalogue/fi_syke/official/web/taulukuvaus.body"
_PAIKKA_EVIDENCE = "maintenance/catalogue/fi_syke/official/web/paikka-page-01.body"
# Step 3 (#755): VedenkTasoTieto (per-site datum corrections) and a server-sorted
# min/max Vedenkorkeus sample together establish that stage is an absolute
# water-surface elevation, not a small gauge-relative reading -- see
# research/fi-syke-series-identity.md (verification-evidence).
_VEDENKTASOTIETO_EVIDENCE = "maintenance/catalogue/fi_syke/official/web/vedenktasotieto-page-01.body"
_VEDENKORKEUS_EXTREMES_EVIDENCE = "maintenance/catalogue/fi_syke/official/web/vedenkorkeus-extremes-desc.body"

_NATIVE_UNIT = {
    "discharge_reported": "m3/s",
    "stage_reported": "cm",
    "water_temperature_reported": "°C",
}


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
        quantity = row["observed_property"]
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
            quantity=known(quantity, _TAULUKUVAUS_EVIDENCE),
            source_unit=known(_NATIVE_UNIT[product], _TAULUKUVAUS_EVIDENCE),
            frequency=known("daily", _PAIKKA_EVIDENCE),
            statistic=EvidenceFact(state=EvidenceState.SOURCE_SILENT),
            temporal_support=EvidenceFact(state=EvidenceState.SOURCE_SILENT),
            timestamp_anchor=EvidenceFact(state=EvidenceState.SOURCE_SILENT),
            time_zone=EvidenceFact(state=EvidenceState.SOURCE_SILENT),
            vertical_reference=vertical_reference,
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
