"""Official Austria eHYD publication identities and established physical facts.

Validated ``Geprüfte Daten`` (``owf`` CSV series) and unvalidated ``Pegel Aktuell``
telemetry (``pegelBgis`` rolling sub-daily JSON and ``pegelLongterm`` current-year
daily JSON) remain distinct ``SourceIdentity`` namespaces even at overlapping gauges.
Temporal support on monthly instantaneous extrema describes the calendar-month
aggregate window rather than an underlying sensor averaging duration. Unresolved
source facts (including ``owf`` time zone, ``owf`` interval temporal support across
historical anchor shifts, per-series ``Pegelnullpunkt`` datum epochs, ``207340``'s
daily ``W-Monatsminima`` export, and ``Pegel Aktuell`` statistics) remain
``not_established`` so incompatible ``PhysicalPredicate`` filters reject rather than guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from rivretrieve._internal.issues import FatalContractError
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

IN_SCOPE_OWF_FTYPES: dict[str, tuple[str, str]] = {
    "owf_abfl_tagesmittel": ("Q-Tagesmittel", "m³/s"),
    "owf_abfl_monatsminima": ("Q-Monatsminima", "m³/s"),
    "owf_abfl_monatsmaxima": ("Q-Monatsmaxima", "m³/s"),
    "owf_wasserst_tagesmittel": ("W-Tagesmittel", "cm"),
    "owf_wasserst_monatsminima": ("W-Monatsminima", "cm"),
    "owf_wasserst_monatsmaxima": ("W-Monatsmaxima", "cm"),
    "owf_wassertemp_monatsmittel": ("WT-Monatsmittel", "°C"),
}

OWF_MISSING_VALUE_TOKEN = "Lücke"
OWF_INTERVAL_RULE_TEXT = "Der Intervallwert gilt bis zum nächsten Zeitpunkt mit einem Wert oder Lücke"

PEGEL_AKTUELL_OBSERVATION_FIELDS: dict[str, str] = {
    "pegel_bgis": "data",
    "pegel_longterm": "current_value",
}

PEGEL_LONGTERM_EXCLUDED_FIELDS: frozenset[str] = frozenset(
    {
        "last_year_value",
        "min_data",
        "min_year",
        "max_data",
        "max_year",
        "mit_data",
        "p5_data",
        "p95_data",
    }
)

PEGEL_BGIS_NON_SERIES_FIELDS: frozenset[str] = frozenset(
    {
        "wert",
        "zp",
        "niedrigwasser",
        "mittelwasser",
        "erhmittelwasser",
        "hochwasser1",
        "hochwasser2",
        "hochwasser3",
    }
)

# Publisher source classifications only, never a cross-route RivRetrieve quality score.
QUALITY_VOCABULARY: dict[str, str] = {
    "owf": "Geprüfte Daten",
    "pegel_aktuell": "ungeprüfte Rohdaten!",
}

UNITS: dict[str, str] = {
    "m³/s": "m3/s",
    "m3/s": "m3/s",
    "cm": "cm",
    "m": "m",
    "°C": "degC",
}

# (parameter_name, canonical_quantity, kind_code, canonical_statistic, expected_period_code, canonical_frequency)
_OWF_ROUTE_SPECS: dict[str, tuple[str, str, str, str, str, str]] = {
    "owf_abfl_tagesmittel": ("Abfluss", "discharge", "I", "mean", "T", "daily"),
    "owf_abfl_monatsminima": ("Abfluss", "discharge", "M", "min", "M", "monthly"),
    "owf_abfl_monatsmaxima": ("Abfluss", "discharge", "M", "max", "M", "monthly"),
    "owf_wasserst_tagesmittel": ("Wasserstand", "stage", "I", "mean", "T", "daily"),
    "owf_wasserst_monatsminima": ("Wasserstand", "stage", "M", "min", "M", "monthly"),
    "owf_wasserst_monatsmaxima": ("Wasserstand", "stage", "M", "max", "M", "monthly"),
    "owf_wassertemp_monatsmittel": ("WTemperatur", "temperature", "I", "mean", "M", "monthly"),
}

_PEGEL_AKTUELL_PARAMETERS: dict[str, str] = {
    "Abfluss": "discharge",
    "Wasserstand": "stage",
}

_STATISTIC_CODES: dict[str, str] = {
    "mit": "mean",
    "min": "min",
    "max": "max",
}

_OWF_ASSOCIATIONS_EVIDENCE = "catalogue:at_ehyd:source.station_product.owf_associations"
_OWF_DESCRIPTOR_EVIDENCE = "catalogue:at_ehyd:source.product.owf_export_descriptors"
_PEGELORDNUNG_STAGE_EVIDENCE = "catalogue:at_ehyd:source.station.pegelnullpunkt_definition"
_PEGELORDNUNG_TEMPORAL_EVIDENCE = "catalogue:at_ehyd:source.product.pegelordnung_temporal_rules"
_PA_ASSOCIATIONS_EVIDENCE = "catalogue:at_ehyd:source.station_product.pegel_aktuell_associations"
_PA_FIELDS_EVIDENCE = "catalogue:at_ehyd:source.series.pegel_aktuell_fields"
_PA_TEMPORAL_EVIDENCE = "catalogue:at_ehyd:source.product.pegel_aktuell_temporal_meaning"


@dataclass(frozen=True, slots=True)
class ExportzeitreiheDescriptor:
    """Parsed ``Exportzeitreihe:`` tuple from an ``owf`` CSV preamble."""

    raw: str
    series_code: str | None
    parameter: str
    kind_code: str
    statistic_code: str
    period_code: str
    period_step: str

    @property
    def canonical_statistic(self) -> str:
        mapped = _STATISTIC_CODES.get(self.statistic_code.casefold())
        if mapped is None:
            raise FatalContractError(f"Unsupported eHYD Exportzeitreihe statistic {self.statistic_code!r}")
        return mapped


@dataclass(frozen=True, slots=True)
class OwfHeaderFacts:
    """Verified preamble facts from a Windows-1252 ``owf`` CSV before ``Werte:``."""

    unit: str | None
    descriptor: ExportzeitreiheDescriptor | None
    has_interval_rule: bool
    pegelnullpunkt_epochs: tuple[tuple[str, str], ...] = ()


def association_product(subsystem: str, variable: str) -> str:
    """Map an eHYD subsystem and native variable identifier to its canonical product_id."""
    if subsystem == "owf":
        if variable not in _OWF_ROUTE_SPECS:
            raise FatalContractError(f"Unsupported eHYD owf variable: {variable!r}")
        return variable
    if subsystem in PEGEL_AKTUELL_OBSERVATION_FIELDS and variable in _PEGEL_AKTUELL_PARAMETERS:
        return f"{subsystem}_{variable.lower()}"
    raise FatalContractError(f"Unsupported eHYD association route: {subsystem!r}/{variable!r}")


def parse_exportzeitreihe(raw_value: str) -> ExportzeitreiheDescriptor:
    """Parse parenthesized or unparenthesized ``Exportzeitreihe:`` metadata tuples."""
    cleaned = raw_value.strip()
    if not cleaned:
        raise FatalContractError("eHYD Exportzeitreihe header is empty")
    unwrapped = cleaned[1:-1].strip() if cleaned.startswith("(") and cleaned.endswith(")") else cleaned
    fields = [part.strip() for part in unwrapped.split(",")]
    if len(fields) < 5:
        raise FatalContractError(f"Malformed eHYD Exportzeitreihe tuple: {raw_value!r}")
    if fields[0].isdigit():
        series_code: str | None = fields[0]
        if len(fields) < 6:
            raise FatalContractError(f"Malformed coded eHYD Exportzeitreihe tuple: {raw_value!r}")
        parameter, kind_code, statistic_code, period_code, period_step = fields[1:6]
    else:
        series_code = None
        parameter, kind_code, statistic_code, period_code, period_step = fields[0:5]
    if parameter not in {"Abfluss", "Wasserstand", "WTemperatur"}:
        raise FatalContractError(f"Unsupported eHYD Exportzeitreihe parameter {parameter!r}")
    if kind_code not in {"I", "M"}:
        raise FatalContractError(f"Unsupported eHYD Exportzeitreihe series kind {kind_code!r}")
    if statistic_code.casefold() not in _STATISTIC_CODES:
        raise FatalContractError(f"Unsupported eHYD Exportzeitreihe statistic {statistic_code!r}")
    if period_code not in {"T", "M"} or not period_step:
        raise FatalContractError(f"Unsupported eHYD Exportzeitreihe period {period_code!r},{period_step!r}")
    return ExportzeitreiheDescriptor(
        raw=cleaned,
        series_code=series_code,
        parameter=parameter,
        kind_code=kind_code,
        statistic_code=statistic_code,
        period_code=period_code,
        period_step=period_step,
    )


def parse_owf_header_facts(raw: bytes, *, expected_ftyp: str | None = None) -> OwfHeaderFacts:
    """Decode and validate an ``owf`` CSV preamble before ``Werte:`` without reading values."""
    header_bytes, sep, _ = raw.partition(b"Werte:")
    if not sep:
        raise FatalContractError("eHYD owf series CSV lacks Werte: sentinel")
    try:
        header_text = header_bytes.decode("cp1252")
    except UnicodeDecodeError as error:
        raise FatalContractError("eHYD owf series CSV preamble is not valid Windows-1252 text") from error

    lines = [line.rstrip("\r\n") for line in header_text.splitlines()]
    found_unit = False
    unit: str | None = None
    raw_ezr: str | None = None
    has_interval_rule = False
    pnp_epochs: list[tuple[str, str]] = []
    in_pnp = False

    for line in lines:
        if line.startswith("Einheit:"):
            found_unit = True
            value = line.split(";", 1)[1].strip() if ";" in line else line.split(":", 1)[1].strip()
            while value.startswith("[") and value.endswith("]"):
                value = value[1:-1].strip()
            unit = value or None
        elif line.startswith("Exportzeitreihe:"):
            raw_ezr = line.split(";", 1)[1].strip() if ";" in line else line.split(":", 1)[1].strip()
        if OWF_INTERVAL_RULE_TEXT in line:
            has_interval_rule = True

        parts = [part.strip() for part in line.split(";")]
        if line.startswith("Pegelnullpunkt:"):
            in_pnp = True
            continue
        if in_pnp:
            if not line.strip() or not line[0].isspace():
                in_pnp = False
                continue
            if parts[0].startswith("gültig"):
                continue
            if len(parts) >= 2 and parts[0] and parts[1]:
                pnp_epochs.append((parts[0], parts[1]))

    if not found_unit:
        raise FatalContractError("eHYD owf series CSV lacks an Einheit header line")
    if not raw_ezr:
        raise FatalContractError("eHYD owf series CSV lacks an Exportzeitreihe header line")
    if unit is None:
        return OwfHeaderFacts(
            unit=None,
            descriptor=None,
            has_interval_rule=has_interval_rule,
            pegelnullpunkt_epochs=tuple(pnp_epochs),
        )

    descriptor = parse_exportzeitreihe(raw_ezr)
    if expected_ftyp is not None:
        if expected_ftyp not in _OWF_ROUTE_SPECS:
            raise FatalContractError(f"Unsupported eHYD owf ftyp: {expected_ftyp!r}")
        exp_param, _, exp_kind, exp_stat, exp_period, _ = _OWF_ROUTE_SPECS[expected_ftyp]
        _, exp_unit = IN_SCOPE_OWF_FTYPES[expected_ftyp]
        if unit != exp_unit:
            raise FatalContractError(f"Unsupported eHYD owf unit {unit!r} for {expected_ftyp}")
        if (
            descriptor.parameter != exp_param
            or descriptor.kind_code != exp_kind
            or descriptor.canonical_statistic != exp_stat
        ):
            raise FatalContractError(
                f"eHYD Exportzeitreihe {descriptor.raw!r} contradicts requested series {expected_ftyp!r}"
            )
        if exp_kind == "I":
            if not has_interval_rule:
                raise FatalContractError(f"eHYD interval series {expected_ftyp!r} lacks interval validity header")
            if (descriptor.period_code, descriptor.period_step) != (exp_period, "1"):
                raise FatalContractError(
                    f"eHYD interval series {expected_ftyp!r} has unexpected period {descriptor.period_code},{descriptor.period_step}"
                )
        else:
            if has_interval_rule:
                raise FatalContractError(f"eHYD instantaneous extrema {expected_ftyp!r} carries interval rule header")
            if descriptor.period_code == "M" and descriptor.period_step not in {"1", "0"}:
                raise FatalContractError(
                    f"eHYD monthly extrema {expected_ftyp!r} has unexpected step {descriptor.period_step!r}"
                )

    return OwfHeaderFacts(
        unit=unit,
        descriptor=descriptor,
        has_interval_rule=has_interval_rule,
        pegelnullpunkt_epochs=tuple(pnp_epochs),
    )


_NOT_ESTABLISHED = EvidenceFact()


def _known_many(value: str, *evidence: str) -> EvidenceFact:
    return EvidenceFact(value=value, state=EvidenceState.KNOWN, evidence=evidence)


def _build_facts(
    *,
    quantity: str,
    units: tuple[str | None, ...],
    unit_evidence: str,
    stage_reference_evidence: str,
    frequency: EvidenceFact = _NOT_ESTABLISHED,
    statistic: EvidenceFact = _NOT_ESTABLISHED,
    temporal_support: EvidenceFact = _NOT_ESTABLISHED,
    timestamp_anchor: EvidenceFact = _NOT_ESTABLISHED,
    time_zone: EvidenceFact = _NOT_ESTABLISHED,
    day_definition: EvidenceFact = _NOT_ESTABLISHED,
    clipping_axis: ClippingAxis = ClippingAxis.SOURCE_TIMESTAMP,
) -> tuple[PhysicalFacts, ...]:
    if not units:
        raise FatalContractError("eHYD source series requires at least one unit state")
    segments: list[PhysicalFacts] = []
    for unit in sorted(set(units), key=lambda item: item or ""):
        vertical_reference = (
            known("gauge_zero", stage_reference_evidence) if quantity == "stage" and unit == "cm" else EvidenceFact()
        )
        fact = PhysicalFacts(
            facts_id="unidentified",
            quantity=known(quantity, unit_evidence),
            source_unit=known(unit, unit_evidence) if unit else EvidenceFact(),
            normalized_unit=UNITS.get(unit) if unit is not None else None,
            frequency=frequency,
            statistic=statistic,
            temporal_support=temporal_support,
            day_definition=day_definition,
            timestamp_anchor=timestamp_anchor,
            time_zone=time_zone,
            vertical_reference=vertical_reference,
            vertical_datum=EvidenceFact(),
            clipping_axis=clipping_axis,
        )
        segments.append(fact.model_copy(update={"facts_id": stable_id(fact.model_dump_json(exclude={"facts_id"}))}))
    return tuple(segments)


def source_series(
    station: str,
    subsystem: str,
    variable: str,
    *,
    units: tuple[str | None, ...],
    origin: Literal["catalogue", "response"] = "catalogue",
    descriptor: ExportzeitreiheDescriptor | None = None,
    evidence: str | None = None,
    temporal_evidence: str | None = None,
    stage_reference_evidence: str = _PEGELORDNUNG_STAGE_EVIDENCE,
) -> SourceSeries:
    """Resolve witnessed eHYD source identities and established physical facts without I/O."""
    if not station.strip():
        raise FatalContractError("eHYD source series requires a nonblank station identifier")
    product = association_product(subsystem, variable)

    if subsystem == "owf":
        exp_param, quantity, exp_kind, exp_stat, exp_period, exp_freq = _OWF_ROUTE_SPECS[variable]
        unit_ev = evidence or _OWF_ASSOCIATIONS_EVIDENCE
        temp_evs = (
            (temporal_evidence,)
            if temporal_evidence is not None
            else (_OWF_DESCRIPTOR_EVIDENCE, _PEGELORDNUNG_TEMPORAL_EVIDENCE)
        )
        if descriptor is not None and (
            descriptor.parameter != exp_param
            or descriptor.kind_code != exp_kind
            or descriptor.canonical_statistic != exp_stat
        ):
            raise FatalContractError(f"eHYD Exportzeitreihe {descriptor.raw!r} contradicts {variable!r}")

        unresolved_period = (descriptor is not None and descriptor.period_code != exp_period) or (
            descriptor is None and station == "207340" and variable == "owf_wasserst_monatsminima"
        )

        statistic = _known_many(exp_stat, *temp_evs)
        frequency = EvidenceFact() if unresolved_period else _known_many(exp_freq, *temp_evs)
        if exp_kind == "I":
            timestamp_anchor = _known_many("start", *temp_evs)
            temporal_support = EvidenceFact()
        else:
            timestamp_anchor = EvidenceFact()
            temporal_support = EvidenceFact() if unresolved_period else _known_many("calendar_month", *temp_evs)

        identity = SourceIdentity(
            namespace="ehyd.owf",
            published_id=variable,
            origin=origin,
            evidence=(unit_ev,),
        )
        facts = _build_facts(
            quantity=quantity,
            units=units,
            unit_evidence=unit_ev,
            stage_reference_evidence=stage_reference_evidence,
            frequency=frequency,
            statistic=statistic,
            temporal_support=temporal_support,
            timestamp_anchor=timestamp_anchor,
            clipping_axis=ClippingAxis.SOURCE_TIMESTAMP,
        )
    else:
        quantity = _PEGEL_AKTUELL_PARAMETERS[variable]
        unit_ev = evidence or _PA_ASSOCIATIONS_EVIDENCE
        identity_evs = (evidence,) if evidence is not None else (_PA_ASSOCIATIONS_EVIDENCE, _PA_FIELDS_EVIDENCE)
        temp_ev = temporal_evidence or _PA_TEMPORAL_EVIDENCE
        published_field = PEGEL_AKTUELL_OBSERVATION_FIELDS[subsystem]
        identity = SourceIdentity(
            namespace=f"ehyd.{subsystem}.{variable}",
            published_id=published_field,
            origin=origin,
            evidence=identity_evs,
        )
        if subsystem == "pegel_bgis":
            facts = _build_facts(
                quantity=quantity,
                units=units,
                unit_evidence=unit_ev,
                stage_reference_evidence=stage_reference_evidence,
                time_zone=known("UTC+01:00", temp_ev),
                clipping_axis=ClippingAxis.SOURCE_TIMESTAMP,
            )
        else:
            facts = _build_facts(
                quantity=quantity,
                units=units,
                unit_evidence=unit_ev,
                stage_reference_evidence=stage_reference_evidence,
                frequency=known("daily", temp_ev),
                clipping_axis=ClippingAxis.CALENDAR_DATE,
            )

    return SourceSeries(
        series_id=stable_id("at_ehyd", station, identity.namespace, identity.published_id),
        provider_id="at_ehyd",
        station_id=station,
        product_id=product,
        identity=identity,
        facts=facts,
    )


def route_product_facts(subsystem: str, variable: str, unit: str) -> PhysicalFacts:
    """Return route-wide established physical facts for canonical ``products.parquet``.

    Station ``207340`` publishes daily minima (``T,1``) inside ``owf_wasserst_monatsminima``,
    preventing a route-wide monthly frequency or calendar-month period claim while
    preserving established stage dimension and minimum statistic across the route.
    """
    representative_station = "207340" if (subsystem == "owf" and variable == "owf_wasserst_monatsminima") else "route"
    return source_series(representative_station, subsystem, variable, units=(unit,)).facts[0]
