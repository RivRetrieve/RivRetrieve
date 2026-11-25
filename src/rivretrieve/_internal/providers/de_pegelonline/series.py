"""Germany PEGELONLINE source-series identity and established physical facts.

PEGELONLINE publishes each of the five already-catalogued products (`W`, `Q`,
`WT`, `TRM`, `TRM_WT`) as one `timeseries` entry on a station: `source_series`
turns one such entry (its native `shortname`, `unit`, optional `equidistance`
minute count and optional `gaugeZero.unit`) into a `SourceSeries` with its own
`SourceIdentity`/`PhysicalFacts`. Facts genuinely vary per station even for
the same product (vertical-datum regime on `W`/`TRM`, reporting interval on
every regular product), so this follows `at_ehyd`'s bespoke-builder pattern
(one call per station/product pair) rather than `provider_series.SeriesMapping`'s
one-frequency-per-product shortcut, which cannot express that variation.

`TRM` and `WT`'s scheduled counterpart `TRM_WT` each keep their own identity:
`TRM` is never folded into `W`, and `TRM_WT` is never folded into `WT`, even
though `TRM` shares `W`'s vertical-datum regime. Their *Terminwerte* readings
are fixed-local-clock-time schedules, not a regular elapsed interval, so their
`frequency` stays `not_established` regardless of any `equidistance` passed in
(PEGELONLINE never actually publishes one for these two anyway).

`WT`/`TRM_WT` map to the dimensional-admission quantity `"temperature"`, never
the catalogue's separate `"water_temperature"` observed-property label: using
that label here would make `admission()` reject every fact as dimensionally
incompatible, reproducing the exact incident recorded in
`providers/dk_vanda/series.py`.
"""

from __future__ import annotations

from typing import Literal

from rivretrieve._internal.frequency import canonicalize_frequency
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.source_series import (
    EvidenceFact,
    EvidenceState,
    PhysicalFacts,
    SourceIdentity,
    SourceSeries,
    known,
    stable_id,
)

PROVIDER_ID = "de_pegelonline"

# Shared by every product: PEGELONLINE identifies a series by (station uuid,
# timeseries shortname) within one uniform `timeseries` list structure, not by
# distinct per-product access routes the way at_ehyd's owf/pegel_bgis/pegel_longterm
# subsystems do.
NAMESPACE = "de_pegelonline.timeseries"

# Native PEGELONLINE `timeseries.shortname` -> source_series.py's dimensional
# admission vocabulary ("stage"/"discharge"/"temperature"). This is distinct
# from generate_catalogue.py's PRODUCTS mapping, which records the catalogue's
# "observed_property" label ("water_temperature") for a different purpose;
# the two vocabularies are not interchangeable here (see module docstring).
QUANTITIES: dict[str, str] = {
    "W": "stage",
    "Q": "discharge",
    "WT": "temperature",
    "TRM": "stage",
    "TRM_WT": "temperature",
}

# W and TRM share one vertical-datum regime (both are stage readings off the
# same gauge); Q, WT and TRM_WT never carry a vertical reference.
_STAGE_PRODUCTS = frozenset({"W", "TRM"})

# Terminwerte: 1-3 scheduled fixed-local-clock-time readings per day, not a
# regular elapsed or calendar interval. PEGELONLINE never publishes an
# `equidistance` for these two; frequency stays not_established regardless.
_SCHEDULED_PRODUCTS = frozenset({"TRM", "TRM_WT"})

_NN_VERTICAL_DATUM = "NN"

# Q and WT/TRM_WT each publish exactly one fixed native unit across every
# witnessed station (step 2's catalogue confirmed this; only W's three
# vertical-datum regimes vary). Unrecognized units are rejected rather than
# silently admitted.
_SIMPLE_NORMALIZED_UNITS: dict[str, dict[str, str]] = {
    "Q": {"m³/s": "m3/s"},
    "WT": {"°C": "degC"},
    "TRM_WT": {"°C": "degC"},
}

TIMESERIES_EVIDENCE = "catalogue:de_pegelonline:source.station.timeseries_entry"
GAUGE_ZERO_EVIDENCE = "catalogue:de_pegelonline:source.station.gauge_zero"
EQUIDISTANCE_EVIDENCE = "catalogue:de_pegelonline:source.station.timeseries_equidistance"


def _stage_vertical_facts(unit: str, gauge_zero_unit: str | None) -> tuple[str, EvidenceFact, EvidenceFact]:
    """Branch purely on the native unit string, never on the (post-scaling) value.

    `cm` normalizes to the identity-preserving spelling `cm`: `admission()`'s
    own dimension table (`source_series.py`'s `_UNIT_DIMENSIONS`) supplies the
    ÷100 factor from there to the admitted `m`, exactly like `at_ehyd`'s own
    `cm` handling. `m+PNP`/`m+NN` are not recognized unit spellings at all (an
    undocumented source-specific code already denominated in metres), so each
    normalizes directly to `m` with no rescaling, matching `at_ehyd`'s
    `"m ü.A"` handling.

    `cm` and `m+PNP` land on the same `vertical_reference` ("gauge_zero")
    despite that different normalization; `m+NN` is the only regime with
    `vertical_reference` "above_sea_level", and its datum is simply "NN",
    established even when no `gaugeZero` is published for that station.
    """
    if unit == "m+NN":
        return "m", known("above_sea_level", TIMESERIES_EVIDENCE), known(_NN_VERTICAL_DATUM, TIMESERIES_EVIDENCE)
    if unit in ("cm", "m+PNP"):
        normalized_unit = "cm" if unit == "cm" else "m"
        vertical_reference = known("gauge_zero", TIMESERIES_EVIDENCE)
        vertical_datum = (
            known(gauge_zero_unit, GAUGE_ZERO_EVIDENCE)
            if gauge_zero_unit
            else EvidenceFact(state=EvidenceState.SOURCE_SILENT, evidence=(GAUGE_ZERO_EVIDENCE,))
        )
        return normalized_unit, vertical_reference, vertical_datum
    raise FatalContractError(f"Unsupported de_pegelonline stage unit: {unit!r}")


def _normalized_simple_unit(product_id: str, unit: str) -> str:
    normalized = _SIMPLE_NORMALIZED_UNITS[product_id].get(unit)
    if normalized is None:
        raise FatalContractError(f"Unsupported de_pegelonline {product_id} unit: {unit!r}")
    return normalized


def _frequency_fact(product_id: str, equidistance: int | None) -> EvidenceFact:
    if product_id in _SCHEDULED_PRODUCTS:
        return EvidenceFact()
    if equidistance is None:
        raise FatalContractError(f"de_pegelonline {product_id!r} requires its station's published 'equidistance'")
    if isinstance(equidistance, bool) or not isinstance(equidistance, int) or equidistance <= 0:
        raise FatalContractError(
            f"de_pegelonline equidistance must be a positive integer minute count, got {equidistance!r}"
        )
    canonical = canonicalize_frequency(f"PT{equidistance}M")
    return known(canonical, EQUIDISTANCE_EVIDENCE)


def _build_facts(
    product_id: str,
    *,
    unit: str,
    equidistance: int | None,
    gauge_zero_unit: str | None,
) -> PhysicalFacts:
    quantity = QUANTITIES[product_id]
    frequency = _frequency_fact(product_id, equidistance)
    if product_id in _STAGE_PRODUCTS:
        normalized_unit, vertical_reference, vertical_datum = _stage_vertical_facts(unit, gauge_zero_unit)
    else:
        normalized_unit = _normalized_simple_unit(product_id, unit)
        vertical_reference = EvidenceFact()
        vertical_datum = EvidenceFact()

    fact = PhysicalFacts(
        facts_id="unidentified",
        quantity=known(quantity, TIMESERIES_EVIDENCE),
        source_unit=known(unit, TIMESERIES_EVIDENCE),
        normalized_unit=normalized_unit,
        frequency=frequency,
        vertical_reference=vertical_reference,
        vertical_datum=vertical_datum,
    )
    return fact.model_copy(update={"facts_id": stable_id(fact.model_dump_json(exclude={"facts_id"}))})


def source_series(
    station_id: str,
    product_id: str,
    *,
    unit: str,
    equidistance: int | None = None,
    gauge_zero_unit: str | None = None,
    origin: Literal["catalogue", "response"] = "catalogue",
) -> SourceSeries:
    """Resolve one PEGELONLINE station/product's identity and established physical facts.

    Parameters
    ----------
    station_id
        PEGELONLINE station `uuid`.
    product_id
        One of `W`, `Q`, `WT`, `TRM`, `TRM_WT`.
    unit
        The station's published native unit for this timeseries (e.g. `cm`,
        `m+NN`, `m+PNP`, `m³/s`, `°C`).
    equidistance
        The station's published `equidistance` minute count for this
        timeseries, when PEGELONLINE publishes one. Required for `W`, `Q` and
        `WT` (PEGELONLINE always publishes one for these); ignored for `TRM`
        and `TRM_WT`, whose frequency stays `not_established` regardless.
    gauge_zero_unit
        The station's published `gaugeZero.unit` for its `W` timeseries, when
        present. Only consulted for `W`/`TRM`'s `cm`/`m+PNP` branches.
    origin
        Whether this call reflects a catalogue-time or response-time
        identification, per `SourceIdentity.origin`.

    Returns
    -------
    SourceSeries
        One concrete source identity with a single established `PhysicalFacts`
        segment.

    Raises
    ------
    FatalContractError
        If `station_id` is blank, `product_id` is not one of the five
        in-scope products, `unit` is not a unit witnessed for that product, or
        a regular (non-scheduled) product is missing its `equidistance`.
    """
    if not station_id.strip():
        raise FatalContractError("de_pegelonline source series requires a nonblank station identifier")
    if product_id not in QUANTITIES:
        raise FatalContractError(f"Unsupported de_pegelonline product: {product_id!r}")

    identity = SourceIdentity(
        namespace=NAMESPACE,
        published_id=product_id,
        origin=origin,
        evidence=(TIMESERIES_EVIDENCE,),
    )
    facts = _build_facts(product_id, unit=unit, equidistance=equidistance, gauge_zero_unit=gauge_zero_unit)
    return SourceSeries(
        series_id=stable_id(PROVIDER_ID, station_id, identity.namespace, identity.published_id),
        provider_id=PROVIDER_ID,
        station_id=station_id,
        product_id=product_id,
        identity=identity,
        facts=(facts,),
    )
