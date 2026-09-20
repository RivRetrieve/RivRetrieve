"""Publisher field identities and independently established Swiss physical facts."""

from collections.abc import Iterable
from typing import Literal

from rivretrieve._internal.engine import ProviderConfig
from rivretrieve._internal.source_series import (
    EvidenceFact,
    PhysicalFacts,
    SourceIdentity,
    SourceSeries,
    known,
    stable_id,
)

PARAMETER_EVIDENCE = "https://api.existenz.ch/apiv1/hydro/parameters; recording ch_foen_parameters_2026-09-02"
_FIELDS = {
    "flow": ("discharge", "m3/s", "m3/s", "discharge_reported", "Abfluss m3/s"),
    "flow_ls": ("discharge", "l/s", "l/s", "discharge_reported", "Abfluss l/s"),
    "height": ("stage", "m", "m", "stage_reported", "Pegel m ü. M."),
    "height_abs": ("stage", "m", "m", "stage_reported", "Pegel m"),
    "temperature": ("temperature", "°C", "degC", "water_temperature_reported", "Wassertemperatur"),
}


def field_series(
    station: str, field: str, *, origin: Literal["catalogue", "response", "mapping"] = "mapping"
) -> SourceSeries:
    quantity, source_unit, normalized, product, description = _FIELDS[field]
    identity = stable_id("ch_foen", station, "field", field)
    facts = PhysicalFacts(
        facts_id=stable_id(identity, quantity, source_unit, "parameter-dictionary-2026-09-02"),
        quantity=known(quantity, PARAMETER_EVIDENCE),
        source_unit=known(source_unit, PARAMETER_EVIDENCE),
        normalized_unit=normalized,
        time_zone=known("+00:00", "Existenz REST Unix timestamps and Flux RFC3339 UTC labels"),
        vertical_reference=known("above_sea_level", PARAMETER_EVIDENCE + "; Pegel m ü. M.")
        if field == "height"
        else EvidenceFact(),
    )
    return SourceSeries(
        series_id=identity,
        provider_id="ch_foen",
        station_id=station,
        product_id=product,
        identity=SourceIdentity(
            namespace="existenz.parameter",
            published_id=field,
            description=description,
            origin=origin,
            evidence=(PARAMETER_EVIDENCE,),
        ),
        variant=field,
        facts=(facts,),
    )


def field_candidates(
    stations: Iterable[str], products: Iterable[str], config: ProviderConfig
) -> tuple[SourceSeries, ...]:
    """Return supported field candidates; this dictionary is not station availability."""
    selected = set(products)
    return tuple(
        field_series(station, field) for station in stations for field, data in _FIELDS.items() if data[3] in selected
    )
