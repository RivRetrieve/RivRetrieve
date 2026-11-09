"""SYKE Hydrologiarajapinta product identity.

Shared with generate_catalogue.py (maintainer-tier): this dataclass and tuple live
here, not there, matching au_bom's rationale -- a future declaration.py import graph
(series.py <- parse.py <- declaration.py) must never reach generate_catalogue.py, a
MAINTAINER_ROLES module (tests/test_provider_architecture_contracts.py).
"""

from dataclasses import dataclass
from typing import Literal

from rivretrieve._internal.source_series import (
    ClippingAxis,
    EvidenceFact,
    EvidenceState,
    PhysicalFacts,
    SourceIdentity,
    SourceSeries,
    known,
    stable_id,
)


@dataclass(frozen=True)
class ProductDefinition:
    product_id: str
    observed_property: str
    frequency: str
    statistic: str
    canonical_unit: str
    native_id: str
    # Dimension name admission() checks the normalized unit against
    # (source_series._UNIT_DIMENSIONS); distinct from observed_property,
    # which is this catalogue's own public display label. Only water
    # temperature differs ("temperature" vs "water_temperature") --
    # confirmed against no_nve/series.py's identical two-value convention
    # for the same quantity.
    quantity: str


# Step 1 (#753) confirmed each of the three admitted quantities has exactly one
# frequency and row shape (no sub-daily or monthly variant). Step 1 also found no
# table states whether Arvo is a daily mean, so statistic stays unknown rather than
# guessed; the "_reported" suffix follows ba_fhmzbih's convention for exactly this
# situation.
PRODUCT_DEFINITIONS: tuple[ProductDefinition, ...] = (
    ProductDefinition(
        product_id="discharge_reported",
        observed_property="discharge",
        frequency="daily",
        statistic="unknown",
        canonical_unit="m3/s",
        native_id="Virtaama",
        quantity="discharge",
    ),
    ProductDefinition(
        product_id="stage_reported",
        observed_property="stage",
        frequency="daily",
        statistic="unknown",
        canonical_unit="m",
        native_id="Vedenkorkeus",
        quantity="stage",
    ),
    ProductDefinition(
        product_id="water_temperature_reported",
        observed_property="water_temperature",
        frequency="daily",
        statistic="unknown",
        canonical_unit="degC",
        native_id="LampoPintavesi",
        quantity="temperature",
    ),
)

# Suure_Id -> product_id: Paikka's own quantity code, the one fact that both
# identifies a station and witnesses which product it has (no separate per-product
# association capture is needed, unlike au_bom's getTimeseriesList calls).
SUURE_ID_TO_PRODUCT: dict[int, str] = {
    1: "stage_reported",
    2: "discharge_reported",
    11: "water_temperature_reported",
}

_BY_PRODUCT_ID = {d.product_id: d for d in PRODUCT_DEFINITIONS}

# Native unit symbols -- confirmed live via the Suure entity set, step 1/#753.
_NATIVE_UNIT: dict[str, str] = {
    "discharge_reported": "m3/s",
    "stage_reported": "cm",
    "water_temperature_reported": "°C",
}

# normalized_unit is a recognised *spelling* of source_unit, same scale and
# zero -- never the canonical conversion target (stage's native "cm" stays
# "cm" here; admission() computes the cm->m factor separately via
# canonical_unit below). Only water temperature needs an actual respelling
# ("°C" -> "degC"); PhysicalFacts' own validator rejects a scale change.
_NORMALIZED_NATIVE_UNIT: dict[str, str] = {
    "discharge_reported": "m3/s",
    "stage_reported": "cm",
    "water_temperature_reported": "degC",
}

# Same retained-evidence pointers catalogue_series.py uses -- fi_syke is
# CatalogueOnly during #756; no fetch.py-origin recording exists yet to cite
# instead.
_TAULUKUVAUS_EVIDENCE = "maintenance/catalogue/fi_syke/official/web/taulukuvaus.body"
_PAIKKA_EVIDENCE = "maintenance/catalogue/fi_syke/official/web/paikka-page-01.body"
# Step 3 (#755): VedenkTasoTieto and a server-sorted Vedenkorkeus extremes
# sample jointly establish stage's vertical_reference; see
# research/fi-syke-series-identity.md (verification-evidence).
_VEDENKTASOTIETO_EVIDENCE = "maintenance/catalogue/fi_syke/official/web/vedenktasotieto-page-01.body"
_VEDENKORKEUS_EXTREMES_EVIDENCE = "maintenance/catalogue/fi_syke/official/web/vedenkorkeus-extremes-desc.body"


def describe_series(
    station_id: str, product_id: str, *, origin: Literal["catalogue", "response", "mapping"] = "response"
) -> SourceSeries:
    """Build the one concrete source identity for a station's series under one product.

    Each (station_id, product_id) pair has exactly one native table and no
    live lookup resolves it further (step 2, #754: one Suure_Id per Paikka_Id
    row) -- unlike au_bom's ts_id, there is no second identity to preserve
    separately here.
    """
    if product_id not in _BY_PRODUCT_ID:
        raise ValueError(f"fi_syke series description requires an admitted product_id: {product_id!r}")
    definition = _BY_PRODUCT_ID[product_id]
    series_id = stable_id("fi_syke", station_id, product_id)
    if product_id == "stage_reported":
        vertical_reference = EvidenceFact(
            value="above_sea_level",
            state=EvidenceState.KNOWN,
            evidence=(_VEDENKORKEUS_EXTREMES_EVIDENCE, _VEDENKTASOTIETO_EVIDENCE),
        )
    else:
        vertical_reference = EvidenceFact(state=EvidenceState.NOT_ESTABLISHED)
    facts = PhysicalFacts(
        facts_id=series_id,
        quantity=known(definition.quantity, _TAULUKUVAUS_EVIDENCE),
        source_unit=known(_NATIVE_UNIT[product_id], _TAULUKUVAUS_EVIDENCE),
        normalized_unit=_NORMALIZED_NATIVE_UNIT[product_id],
        frequency=known(definition.frequency, _PAIKKA_EVIDENCE),
        statistic=EvidenceFact(state=EvidenceState.SOURCE_SILENT),
        temporal_support=EvidenceFact(state=EvidenceState.SOURCE_SILENT),
        timestamp_anchor=EvidenceFact(state=EvidenceState.SOURCE_SILENT),
        time_zone=EvidenceFact(state=EvidenceState.SOURCE_SILENT),
        vertical_reference=vertical_reference,
        # Daily frequency is established (step 1), so calendar-date clipping is valid.
        clipping_axis=ClippingAxis.CALENDAR_DATE,
        label_time="00:00:00",
    )
    return SourceSeries(
        series_id=series_id,
        provider_id="fi_syke",
        station_id=station_id,
        product_id=product_id,
        identity=SourceIdentity(
            namespace=f"fi_syke/{product_id}",
            origin=origin,
            description="SYKE Hydrologiarajapinta entity set; station_id (Paikka_Id) witnesses exactly one product",
            evidence=(_TAULUKUVAUS_EVIDENCE, _PAIKKA_EVIDENCE),
        ),
        facts=(facts,),
    )
