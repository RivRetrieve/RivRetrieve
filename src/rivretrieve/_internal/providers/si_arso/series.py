"""Official Slovenia ARSO (``si_arso``) series identities and physical facts contract.

Kept free of network, filesystem, and runtime configuration I/O so offline
catalogue generation, source certification, and response parsing share one
deterministic contract across the three distinct ARSO streams:

1. ``pov_arhiv_tab.php`` ``b_oddo_CSV``: verified daily historical series
   (``P1D``; ``statistic="not_established"`` because pre-limnigraph/manual
   ``tip=O`` epochs store once-daily instantaneous observations alongside modern
   daily means);
2. ``pov_arhiv_tab.php`` ``b_eks_CSV``: verified monthly instantaneous minima
   and maxima (``P1M``) with exact ``DD.MM.YYYY HH:MM`` occurrence timestamps;
3. ``www.arso.gov.si/vode/podatki/amp/H{sifra}_t_{1,7,30}.html``: provisional
   operational rolling telemetry tables (``t_1`` station-scoped ``PT5M`` /
   ``PT10M`` / ``PT30M``, uniform ``t_7`` ``PT30M``, and uniform ``t_30``
   ``PT1H`` in fixed ``CET``, ``UTC+01:00`` / ``+01:00``).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from rivretrieve._internal.frequency import canonicalize_frequency
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.source_series import (
    ClippingAxis,
    EvidenceFact,
    EvidenceState,
    PhysicalFacts,
    SourceIdentity,
    SourceSeries,
    admission,
    stable_id,
)

if TYPE_CHECKING:
    from rivretrieve._internal.catalogues.source_series import SourceDescription

NAMESPACE_ARCHIVE_DAILY = "arso.hidarhiv.oddo"
NAMESPACE_ARCHIVE_MONTHLY_EXTREMES = "arso.hidarhiv.eks"
NAMESPACE_AMP_PREFIX = "arso.amp"

ARCHIVE_MISSING_DATUM_MARKERS: frozenset[str] = frozenset({"", "-"})

# Deferred archive / telemetry columns outside the 3 core quantities; kept explicit
# so catalogue/observation parsers skip them deterministically without guessing meanings.
DEFERRED_ODDO_COLUMNS: frozenset[str] = frozenset(
    {
        "transport suspend. materiala (kg/s)",
        "transport suspendiranega materiala (kg/s)",
        "vsebnost suspend. materiala (g/m3)",
        "vsebnost suspendiranega materiala (g/m3)",
        "motnost vode (NTU)",
        "spec. elekt. prevod. vode (µS/cm)",
        "specifična električna prevodnost vode (µS/cm)",
        "koeficienti zaraščenosti",
    }
)
DEFERRED_EKS_PREFIXES: frozenset[str] = frozenset(
    {
        "Tr.S.M",
        "Tr.S.M.",
        "Vs.S.M",
        "Vs.S.M.",
        "Mv",
        "SEP",
        "S.El.P",
        "S.El.P.",
        "kZ",
    }
)
DEFERRED_AMP_COLUMNS: frozenset[str] = frozenset({"Elektroprevodnost vode [uS]"})

UNITS: dict[str, str] = {
    "m3/s": "m3/s",
    "m³/s": "m3/s",
    "cm": "cm",
    "°C": "degC",
}

TARGET_UNITS: dict[str, str] = {
    "discharge": "m3/s",
    "stage": "m",
    "temperature": "degC",
}

_ARCHIVE_DAILY_EVIDENCE = (
    "catalogue:si_arso:source.station_product.archive_daily_witnesses",
    "catalogue:si_arso:source.product.archive_methodology",
)
_ARCHIVE_MONTHLY_EXTREMES_EVIDENCE = (
    "catalogue:si_arso:source.station_product.archive_monthly_extremes_witnesses",
    "catalogue:si_arso:source.product.monthly_extremes_units_and_definitions",
    "catalogue:si_arso:source.product.archive_methodology",
)
_AMP_EVIDENCE = (
    "catalogue:si_arso:source.station_product.amp_telemetry_witnesses",
    "catalogue:si_arso:source.product.amp_operational_semantics",
)
_GAUGE_ZERO_EVIDENCE = ("catalogue:si_arso:source.station.gauge_zero_definition",)


def _known_many(value: str, *evidence: str) -> EvidenceFact:
    return EvidenceFact(value=value, state=EvidenceState.KNOWN, evidence=evidence)


AMP_T1_5MIN_STATIONS: frozenset[str] = frozenset({"1260", "2005", "2110", "2830", "3530", "4050", "4270", "8180"})
AMP_T1_30MIN_STATIONS: frozenset[str] = frozenset({"3900", "6120"})


def station_amp_t1_frequency(station: str) -> Literal["PT5M", "PT10M", "PT30M"]:
    """Return documented & empirically verified ``t_1`` cadence for an in-scope station."""
    clean = validate_station_id(station)
    if clean in AMP_T1_5MIN_STATIONS:
        return "PT5M"
    if clean in AMP_T1_30MIN_STATIONS:
        return "PT30M"
    return "PT10M"


@dataclass(frozen=True, slots=True)
class SiArsoProductSpec:
    """Verified ARSO stream product coordinates, physical facts, and clipping rule."""

    product_id: str
    stream: Literal["archive_daily", "archive_monthly_extremes", "amp"]
    quantity: Literal["discharge", "stage", "temperature"]
    source_unit: str
    normalized_unit: str
    target_unit: str
    frequency: str | None
    statistic: str | None
    temporal_support: str | None
    time_zone: str | None
    clipping_axis: ClippingAxis
    variant: str | None
    data_status: Literal["Verificirani podatki", "Začasni podatki"]
    archive_column: str | None = None
    eks_prefix: str | None = None
    amp_cadence: Literal["t_1", "t_7", "t_30"] | None = None
    amp_column: str | None = None


PRODUCT_SPECS: tuple[SiArsoProductSpec, ...] = (
    # 1. Verified daily archive (pov_arhiv_tab.php b_oddo_CSV)
    SiArsoProductSpec(
        product_id="archive_discharge_daily",
        stream="archive_daily",
        quantity="discharge",
        source_unit="m3/s",
        normalized_unit="m3/s",
        target_unit="m3/s",
        frequency="P1D",
        statistic=None,
        temporal_support=None,
        time_zone=None,
        clipping_axis=ClippingAxis.CALENDAR_DATE,
        variant=None,
        data_status="Verificirani podatki",
        archive_column="pretok (m3/s)",
    ),
    SiArsoProductSpec(
        product_id="archive_stage_daily",
        stream="archive_daily",
        quantity="stage",
        source_unit="cm",
        normalized_unit="cm",
        target_unit="m",
        frequency="P1D",
        statistic=None,
        temporal_support=None,
        time_zone=None,
        clipping_axis=ClippingAxis.CALENDAR_DATE,
        variant=None,
        data_status="Verificirani podatki",
        archive_column="vodostaj (cm)",
    ),
    SiArsoProductSpec(
        product_id="archive_temperature_daily",
        stream="archive_daily",
        quantity="temperature",
        source_unit="°C",
        normalized_unit="degC",
        target_unit="degC",
        frequency="P1D",
        statistic=None,
        temporal_support=None,
        time_zone=None,
        clipping_axis=ClippingAxis.CALENDAR_DATE,
        variant=None,
        data_status="Verificirani podatki",
        archive_column="temp. vode (°C)",
    ),
    # 2. Verified monthly instantaneous extremes (pov_arhiv_tab.php b_eks_CSV)
    SiArsoProductSpec(
        product_id="archive_discharge_monthly_min",
        stream="archive_monthly_extremes",
        quantity="discharge",
        source_unit="m3/s",
        normalized_unit="m3/s",
        target_unit="m3/s",
        frequency="P1M",
        statistic="min",
        temporal_support="calendar_month",
        time_zone=None,
        clipping_axis=ClippingAxis.SOURCE_TIMESTAMP,
        variant=None,
        data_status="Verificirani podatki",
        eks_prefix="Q_MIN",
    ),
    SiArsoProductSpec(
        product_id="archive_discharge_monthly_max",
        stream="archive_monthly_extremes",
        quantity="discharge",
        source_unit="m3/s",
        normalized_unit="m3/s",
        target_unit="m3/s",
        frequency="P1M",
        statistic="max",
        temporal_support="calendar_month",
        time_zone=None,
        clipping_axis=ClippingAxis.SOURCE_TIMESTAMP,
        variant=None,
        data_status="Verificirani podatki",
        eks_prefix="Q_MAX",
    ),
    SiArsoProductSpec(
        product_id="archive_stage_monthly_min",
        stream="archive_monthly_extremes",
        quantity="stage",
        source_unit="cm",
        normalized_unit="cm",
        target_unit="m",
        frequency="P1M",
        statistic="min",
        temporal_support="calendar_month",
        time_zone=None,
        clipping_axis=ClippingAxis.SOURCE_TIMESTAMP,
        variant=None,
        data_status="Verificirani podatki",
        eks_prefix="H_MIN",
    ),
    SiArsoProductSpec(
        product_id="archive_stage_monthly_max",
        stream="archive_monthly_extremes",
        quantity="stage",
        source_unit="cm",
        normalized_unit="cm",
        target_unit="m",
        frequency="P1M",
        statistic="max",
        temporal_support="calendar_month",
        time_zone=None,
        clipping_axis=ClippingAxis.SOURCE_TIMESTAMP,
        variant=None,
        data_status="Verificirani podatki",
        eks_prefix="H_MAX",
    ),
    SiArsoProductSpec(
        product_id="archive_temperature_monthly_min",
        stream="archive_monthly_extremes",
        quantity="temperature",
        source_unit="°C",
        normalized_unit="degC",
        target_unit="degC",
        frequency="P1M",
        statistic="min",
        temporal_support="calendar_month",
        time_zone=None,
        clipping_axis=ClippingAxis.SOURCE_TIMESTAMP,
        variant=None,
        data_status="Verificirani podatki",
        eks_prefix="Tv_MIN",
    ),
    SiArsoProductSpec(
        product_id="archive_temperature_monthly_max",
        stream="archive_monthly_extremes",
        quantity="temperature",
        source_unit="°C",
        normalized_unit="degC",
        target_unit="degC",
        frequency="P1M",
        statistic="max",
        temporal_support="calendar_month",
        time_zone=None,
        clipping_axis=ClippingAxis.SOURCE_TIMESTAMP,
        variant=None,
        data_status="Verificirani podatki",
        eks_prefix="Tv_MAX",
    ),
    # 3. Provisional operational rolling telemetry (amp/H{sifra}_t_{1,7,30}.html)
    *(
        SiArsoProductSpec(
            product_id=f"operational_{quantity}_{variant_suffix}",
            stream="amp",
            quantity=quantity,
            source_unit=source_unit,
            normalized_unit=UNITS[source_unit],
            target_unit=TARGET_UNITS[quantity],
            frequency=frequency,
            statistic=None,
            temporal_support=None,
            time_zone="UTC+01:00",
            clipping_axis=ClippingAxis.SOURCE_TIMESTAMP,
            variant=f"operational_{variant_suffix}",
            data_status="Začasni podatki",
            amp_cadence=amp_cadence,
            amp_column=amp_column,
        )
        for amp_cadence, variant_suffix, frequency in (
            ("t_1", "10min", None),
            ("t_7", "30min", "PT30M"),
            ("t_30", "hourly", "PT1H"),
        )
        for quantity, source_unit, amp_column in (
            ("discharge", "m³/s", "Pretok [m³/s]"),
            ("stage", "cm", "Vodostaj [cm]"),
            ("temperature", "°C", "Temperatura vode [°C]"),
        )
    ),
)

SPECS_BY_PRODUCT_ID: dict[str, SiArsoProductSpec] = {spec.product_id: spec for spec in PRODUCT_SPECS}
SPECS_BY_ARCHIVE_COLUMN: dict[str, SiArsoProductSpec] = {
    spec.archive_column: spec for spec in PRODUCT_SPECS if spec.archive_column is not None
}
SPECS_BY_EKS_PREFIX: dict[str, SiArsoProductSpec] = {
    spec.eks_prefix: spec for spec in PRODUCT_SPECS if spec.eks_prefix is not None
}
SPECS_BY_AMP_ROUTE: dict[tuple[str, str], SiArsoProductSpec] = {
    (spec.amp_cadence, spec.amp_column): spec
    for spec in PRODUCT_SPECS
    if spec.amp_cadence is not None and spec.amp_column is not None
}


def validate_station_id(station: str) -> str:
    """Validate canonical 4-digit ASCII ARSO gauging station identifier."""
    if len(station) != 4 or not station.isascii() or not station.isdigit():
        raise FatalContractError(f"si_arso station_id must be a 4-digit ASCII code: {station!r}")
    return station


def product_native_coordinate(spec: SiArsoProductSpec) -> str:
    """Return canonical native coordinate identifier for ``products.parquet`` and descriptors."""
    if spec.stream == "archive_daily":
        assert spec.archive_column is not None
        return f"oddo:{spec.archive_column}"
    if spec.stream == "archive_monthly_extremes":
        assert spec.eks_prefix is not None
        return f"eks:{spec.eks_prefix}"
    assert spec.amp_cadence is not None and spec.amp_column is not None
    return f"amp:{spec.amp_cadence}:{spec.amp_column}"


def product_identity(
    spec: SiArsoProductSpec,
    *,
    origin: Literal["catalogue", "response"] = "catalogue",
    evidence: tuple[str, ...] | None = None,
) -> SourceIdentity:
    """Construct the ``SourceIdentity`` distinguishing archive daily, extremes, and amp streams."""
    if spec.stream == "archive_daily":
        assert spec.archive_column is not None
        evs = evidence if evidence is not None else _ARCHIVE_DAILY_EVIDENCE
        return SourceIdentity(
            namespace=NAMESPACE_ARCHIVE_DAILY,
            published_id=spec.archive_column,
            origin=origin,
            evidence=evs,
        )
    if spec.stream == "archive_monthly_extremes":
        assert spec.eks_prefix is not None
        evs = evidence if evidence is not None else _ARCHIVE_MONTHLY_EXTREMES_EVIDENCE
        return SourceIdentity(
            namespace=NAMESPACE_ARCHIVE_MONTHLY_EXTREMES,
            published_id=spec.eks_prefix,
            origin=origin,
            evidence=evs,
        )
    assert spec.amp_cadence is not None and spec.amp_column is not None
    evs = evidence if evidence is not None else _AMP_EVIDENCE
    return SourceIdentity(
        namespace=f"{NAMESPACE_AMP_PREFIX}.{spec.amp_cadence}",
        published_id=spec.amp_column,
        origin=origin,
        evidence=evs,
    )


def product_physical_facts(
    product_id: str,
    *,
    station: str | None = None,
    source_unit: str | None = None,
    evidence: tuple[str, ...] | None = None,
    stage_reference_evidence: tuple[str, ...] = _GAUGE_ZERO_EVIDENCE,
) -> PhysicalFacts:
    """Construct admission-validated ``PhysicalFacts`` for one ``si_arso`` product."""
    spec = SPECS_BY_PRODUCT_ID.get(product_id)
    if spec is None:
        raise FatalContractError(f"Unsupported si_arso product_id: {product_id!r}")

    resolved_unit = spec.source_unit if source_unit is None else source_unit.strip()
    if resolved_unit != spec.source_unit:
        raise FatalContractError(
            f"si_arso product {product_id!r} requires source unit {spec.source_unit!r}, got {resolved_unit!r}"
        )

    resolved_frequency = (
        station_amp_t1_frequency(station) if spec.amp_cadence == "t_1" and station is not None else spec.frequency
    )
    canonical_frequency = canonicalize_frequency(resolved_frequency) if resolved_frequency is not None else None

    if spec.stream == "archive_daily":
        evs = evidence if evidence is not None else _ARCHIVE_DAILY_EVIDENCE
    elif spec.stream == "archive_monthly_extremes":
        evs = evidence if evidence is not None else _ARCHIVE_MONTHLY_EXTREMES_EVIDENCE
    else:
        evs = evidence if evidence is not None else _AMP_EVIDENCE

    facts = PhysicalFacts(
        facts_id="unidentified",
        quantity=_known_many(spec.quantity, *evs),
        source_unit=_known_many(resolved_unit, *evs),
        normalized_unit=spec.normalized_unit,
        frequency=_known_many(canonical_frequency, *evs) if canonical_frequency is not None else EvidenceFact(),
        statistic=_known_many(spec.statistic, *evs) if spec.statistic is not None else EvidenceFact(),
        temporal_support=_known_many(spec.temporal_support, *evs)
        if spec.temporal_support is not None
        else EvidenceFact(),
        day_definition=EvidenceFact(),
        timestamp_anchor=EvidenceFact(),
        time_zone=_known_many(spec.time_zone, *evs) if spec.time_zone is not None else EvidenceFact(),
        vertical_reference=(
            _known_many("gauge_zero", *stage_reference_evidence) if spec.quantity == "stage" else EvidenceFact()
        ),
        vertical_datum=EvidenceFact(),
        clipping_axis=spec.clipping_axis,
    )
    facts = facts.model_copy(update={"facts_id": stable_id(facts.model_dump_json(exclude={"facts_id"}))})
    decision = admission(facts)
    if decision.status != "supported" or decision.target_unit != spec.target_unit:
        raise FatalContractError(f"si_arso product {product_id!r} failed admission: {decision.reason}")
    return facts


def route_product_facts(product_id: str) -> PhysicalFacts:
    """Return canonical route-level physical facts for ``products.parquet``."""
    return product_physical_facts(product_id)


def source_series(
    station: str,
    product_id: str,
    *,
    source_unit: str | None = None,
    origin: Literal["catalogue", "response"] = "catalogue",
    identity_evidence: tuple[str, ...] | None = None,
    fact_evidence: tuple[str, ...] | None = None,
    stage_reference_evidence: tuple[str, ...] = _GAUGE_ZERO_EVIDENCE,
) -> SourceSeries:
    """Resolve one witnessed ARSO ``SourceSeries`` with separated identity and physical facts."""
    clean_station = validate_station_id(station)
    spec = SPECS_BY_PRODUCT_ID.get(product_id)
    if spec is None:
        raise FatalContractError(f"Unsupported si_arso product_id: {product_id!r}")
    identity = product_identity(spec, origin=origin, evidence=identity_evidence)
    facts = product_physical_facts(
        product_id,
        station=clean_station,
        source_unit=source_unit,
        evidence=fact_evidence if fact_evidence is not None else identity_evidence,
        stage_reference_evidence=stage_reference_evidence,
    )
    return SourceSeries(
        series_id=stable_id("si_arso", clean_station, identity.namespace, identity.published_id),
        provider_id="si_arso",
        station_id=clean_station,
        product_id=spec.product_id,
        identity=identity,
        variant=spec.variant,
        facts=(facts,),
    )


def build_source_descriptions(
    grouped_stations: Sequence[tuple[str, Sequence[str]]],
) -> tuple[SourceDescription, ...]:
    """Construct compact station-grouped ``SourceDescription`` records for ``si_arso``."""
    from rivretrieve._internal.catalogues.source_series import SourceDescription

    descriptions = []
    for product_id, station_ids in grouped_stations:
        spec = SPECS_BY_PRODUCT_ID.get(product_id)
        if spec is None:
            raise FatalContractError(f"Unsupported si_arso product_id in associations: {product_id!r}")
        if not station_ids:
            raise FatalContractError(f"Empty station group for si_arso product {product_id!r}")
        if spec.amp_cadence == "t_1":
            frequencies = {station_amp_t1_frequency(station_id) for station_id in station_ids}
            if len(frequencies) != 1:
                raise FatalContractError(
                    f"si_arso {product_id!r} station group mixes AMP t_1 frequencies: {sorted(frequencies)}"
                )
        identity = product_identity(spec, origin="catalogue")
        facts = product_physical_facts(product_id, station=station_ids[0])
        descriptions.append(
            SourceDescription(
                product_id=spec.product_id,
                station_ids=tuple(sorted(station_ids)),
                identity_key=(identity.namespace, identity.published_id),
                native_coordinate=product_native_coordinate(spec),
                identity=identity,
                variant=spec.variant,
                facts=(facts,),
            )
        )
    return tuple(descriptions)
