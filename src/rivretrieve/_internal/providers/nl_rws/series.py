"""Rijkswaterstaat DDAPI 2.0 runtime series identity, physical facts, and missing-value rules.

Runtime-safe module shared with catalogue_series.py (never imports generate_catalogue.py).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProviderId
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

PROVIDER_ID = ProviderId("nl_rws")

CATALOGUS_EVIDENCE = "https://ddapi20-waterwebservices.rijkswaterstaat.nl/METADATASERVICES/OphalenCatalogus"
WAARNEMINGEN_EVIDENCE = (
    "https://ddapi20-waterwebservices.rijkswaterstaat.nl/ONLINEWAARNEMINGENSERVICES/OphalenWaarnemingen"
)
AQUO_GEM24H_EVIDENCE = "Aquo WaardeBewerkingsMethode GEM24H (Etmaalgemiddelde) in OphalenCatalogus"

MISSING_SENTINEL_THRESHOLD = 1e37
MISSING_ALPHANUMERIC_SENTINEL = ".999999E+38"
MISSING_QUALITY_CODE = "99"


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


def _nested_code(mapping: Mapping[str, object], key: str) -> str:
    raw = mapping.get(key)
    if isinstance(raw, dict):
        nested = cast("dict[str, object]", raw)
        code = nested.get("Code")
        if isinstance(code, str):
            return code
    return ""


def parse_tijdstip_offset(tijdstip: str) -> tuple[datetime, str]:
    """Parse an ISO-8601 DDAPI 2.0 ``Tijdstip`` into a naive wall-clock datetime and explicit offset string."""
    parsed = datetime.fromisoformat(tijdstip)
    offset = parsed.utcoffset()
    if offset is None:
        raise FatalContractError(f"nl_rws Tijdstip is missing an explicit UTC offset: {tijdstip!r}")
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    hours, minutes = divmod(abs(total_minutes), 60)
    offset_str = f"{sign}{hours:02d}:{minutes:02d}"
    return parsed.replace(tzinfo=None), offset_str


def is_missing_observation_value(
    numeric_value: float | int | None,
    alphanumeric_value: str | None,
    quality_code: str | None,
) -> bool:
    """Return True when a DDAPI 2.0 observation slot represents a published missing value.

    Empirical verification across 211,262 Lobith discharge rows established a 1-to-1 match
    between ``Kwaliteitswaardecode == "99"`` and ``Waarde_Numeriek == 9.99999e+37``
    (``".999999E+38"``). Valid ``0.0`` and negative readings return False.
    """
    if quality_code == MISSING_QUALITY_CODE:
        return True
    if numeric_value is None:
        return True
    if isinstance(numeric_value, bool):
        return True
    val = float(numeric_value)
    if not math.isfinite(val) or abs(val) >= MISSING_SENTINEL_THRESHOLD:
        return True
    return alphanumeric_value is not None and alphanumeric_value.strip().upper() == MISSING_ALPHANUMERIC_SENTINEL


def build_physical_facts(
    definition: ProductDefinition,
    *,
    time_zone_offset: str | None,
    facts_id: str | None = None,
) -> PhysicalFacts:
    """Construct ``PhysicalFacts`` for one admitted nl_rws product and optional explicit UTC offset."""
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
    time_zone = (
        known(time_zone_offset, WAARNEMINGEN_EVIDENCE)
        if time_zone_offset is not None
        else EvidenceFact(state=EvidenceState.NOT_ESTABLISHED)
    )
    resolved_facts_id = facts_id or (
        f"{definition.product_id}:{time_zone_offset}" if time_zone_offset is not None else definition.product_id
    )
    return PhysicalFacts(
        facts_id=resolved_facts_id,
        quantity=known(definition.quantity, CATALOGUS_EVIDENCE),
        source_unit=known(definition.native_unit, CATALOGUS_EVIDENCE),
        normalized_unit=definition.normalized_native_unit,
        frequency=frequency,
        statistic=statistic,
        temporal_support=EvidenceFact(state=EvidenceState.NOT_ESTABLISHED),
        day_definition=EvidenceFact(state=EvidenceState.NOT_ESTABLISHED),
        timestamp_anchor=EvidenceFact(state=EvidenceState.NOT_ESTABLISHED),
        time_zone=time_zone,
        vertical_reference=vertical_reference,
        vertical_datum=vertical_datum,
        clipping_axis=ClippingAxis.SOURCE_TIMESTAMP,
    )


def resolve_response_series(
    *,
    station_id: str,
    aquo_metadata: Mapping[str, object],
    offsets: Sequence[str],
) -> SourceSeries | None:
    """Resolve one ``WaarnemingenLijst`` item's ``AquoMetadata`` into a distinct ``SourceSeries``.

    Returns ``None`` for out-of-scope series (forecasts, astronomical tides, non-OW
    compartments, non-empty ``Groepering``, or unadmitted ``WaardeBewerkingsMethode``).
    Raises ``FatalContractError`` when an admitted series lacks ``WaardeBepalingsMethode.Code``.
    """
    if _nested_code(aquo_metadata, "Compartiment") != "OW":
        return None
    if aquo_metadata.get("ProcesType") != "meting":
        return None
    if _nested_code(aquo_metadata, "Groepering") != "":
        return None
    key = (
        _nested_code(aquo_metadata, "Grootheid"),
        _nested_code(aquo_metadata, "Eenheid"),
        _nested_code(aquo_metadata, "Hoedanigheid"),
        _nested_code(aquo_metadata, "WaardeBewerkingsMethode"),
    )
    product_id = ADMITTED_PRODUCT_KEY_TO_ID.get(key)
    if product_id is None:
        return None

    variant = _nested_code(aquo_metadata, "WaardeBepalingsMethode").strip()
    if not variant:
        raise FatalContractError(
            f"nl_rws admitted response series for {station_id!r}/{product_id!r} is missing WaardeBepalingsMethode.Code"
        )

    definition = PRODUCT_BY_ID[product_id]
    unique_offsets = tuple(dict.fromkeys(offsets))
    if unique_offsets:
        facts = tuple(
            build_physical_facts(
                definition,
                time_zone_offset=offset,
                facts_id=stable_id("nl_rws_facts", product_id, variant, offset),
            )
            for offset in unique_offsets
        )
    else:
        facts = (
            build_physical_facts(
                definition,
                time_zone_offset=None,
                facts_id=stable_id("nl_rws_facts", product_id, variant, "unknown_tz"),
            ),
        )

    identity = SourceIdentity(
        namespace=f"nl_rws/{product_id}",
        published_id=variant,
        origin="response",
        description=(
            f"Rijkswaterstaat DDAPI 2.0 measured series for {definition.native_id} "
            f"identified by WaardeBepalingsMethode={variant}"
        ),
        evidence=(WAARNEMINGEN_EVIDENCE,),
    )
    return SourceSeries(
        series_id=stable_id("nl_rws_series", station_id, product_id, variant),
        provider_id=PROVIDER_ID,
        station_id=station_id,
        product_id=product_id,
        identity=identity,
        facts=facts,
        variant=variant,
    )
