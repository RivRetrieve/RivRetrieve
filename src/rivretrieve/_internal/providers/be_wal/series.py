"""Published Belgium - Wallonia (`be_wal`) KiWIS series mappings for offline catalogue generation.

Step 2 establishes the full 62-product native ladder across standard discharge
(``Débit``), ultrasonic discharge (``Débit ultrason``), gauge-zero stage
(``Hauteur`` / ``Hauteur sonde``), elevation stage (``Hauteur absolue`` under
``Hauteur`` / ``Hauteur sonde``), and water temperature (``Température Eau`` /
``Temperature Eau``) alongside verified station-product ``KiWIS.ts_id``
associations while keeping temporal and vertical physical meanings unestablished
(``None`` -> ``unknown``) until Step 3 certifies meaning witnesses.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import polars as pl

from rivretrieve._internal.catalogues.products import product_row
from rivretrieve._internal.catalogues.source_series import SourceDescription, SourceDescriptions
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.provider_series import SeriesMapping
from rivretrieve._internal.source_series import SourceIdentity

KIWIS_NAMESPACE = "KiWIS.ts_id"
_ASSOCIATION_EVIDENCE = ("catalogue:be_wal:source.station_product.kiwis_tslist",)
_FIELD_EVIDENCE = ("catalogue:be_wal:source.series.fields",)

_CADENCES_FULL: tuple[tuple[str, str], ...] = (
    ("complete", "05-{stem}.Complet"),
    ("hourly_mean", "10-{stem}.1h.Moyen"),
    ("hourly_min", "11-{stem}.1h.Minimum"),
    ("hourly_max", "12-{stem}.1h.Maximum"),
    ("daily_mean", "20-{stem}.Jour.Moyen"),
    ("daily_min", "21-{stem}.Jour.Minimum"),
    ("daily_max", "22-{stem}.Jour.Maximum"),
    ("monthly_mean", "40-{stem}.Mois.Moyen"),
    ("monthly_min", "41-{stem}.Mois.Minimum"),
    ("monthly_max", "42-{stem}.Mois.Maximum"),
    ("yearly_mean", "50-{stem}.An.Moyen"),
    ("yearly_min", "51-{stem}.An.Minimum"),
    ("yearly_max", "52-{stem}.An.Maximum"),
)

_CADENCES_NO_YEARLY: tuple[tuple[str, str], ...] = tuple(
    item for item in _CADENCES_FULL if not item[0].startswith("yearly_")
)


@dataclass(frozen=True, slots=True)
class ProductSpec:
    """Native KiWIS mapping for one SPW Hydrométrie hydrological product."""

    product_id: str
    family: Literal["discharge", "discharge_ultrasonic", "stage", "stage_absolute", "water_temperature"]
    native_id: str
    stationparameter_names: tuple[str, ...]
    quantity: Literal["discharge", "stage", "temperature"]
    source_unit: str
    normalized_unit: str

    def series_mapping(self, *, published_id: str | None = None) -> SeriesMapping:
        """Build Step 2 mapping with only source-verified quantity and native unit."""
        return SeriesMapping(
            namespace=KIWIS_NAMESPACE,
            published_id=published_id or self.native_id,
            quantity=self.quantity,
            source_unit=self.source_unit,
            normalized_unit=self.normalized_unit,
            evidence=_ASSOCIATION_EVIDENCE,
            identity_evidence=_FIELD_EVIDENCE,
        )


def _family_specs() -> tuple[ProductSpec, ...]:
    specs: list[ProductSpec] = []
    families: tuple[
        tuple[
            Literal["discharge", "discharge_ultrasonic", "stage", "stage_absolute", "water_temperature"],
            str,
            str,
            tuple[str, ...],
            Literal["discharge", "stage", "temperature"],
            str,
            str,
            tuple[tuple[str, str], ...],
        ],
        ...,
    ] = (
        ("discharge", "discharge", "Debit", ("Débit",), "discharge", "m³/s", "m3/s", _CADENCES_FULL),
        (
            "discharge_ultrasonic",
            "discharge_ultrasonic",
            "Debit ultrason",
            ("Débit ultrason",),
            "discharge",
            "m³/s",
            "m3/s",
            _CADENCES_FULL,
        ),
        ("stage", "stage", "Hauteur", ("Hauteur", "Hauteur sonde"), "stage", "m", "m", _CADENCES_FULL),
        (
            "stage_absolute",
            "stage_absolute",
            "Hauteur absolue",
            ("Hauteur", "Hauteur sonde"),
            "stage",
            "m",
            "m",
            _CADENCES_FULL,
        ),
        (
            "water_temperature",
            "water_temperature",
            "Temperature",
            ("Température Eau", "Temperature Eau"),
            "temperature",
            "°C",
            "degC",
            _CADENCES_NO_YEARLY,
        ),
    )
    for family, prefix, stem, params, quantity, src_unit, norm_unit, cadences in families:
        for suffix, pattern in cadences:
            specs.append(
                ProductSpec(
                    product_id=f"{prefix}_{suffix}",
                    family=family,
                    native_id=pattern.format(stem=stem),
                    stationparameter_names=params,
                    quantity=quantity,
                    source_unit=src_unit,
                    normalized_unit=norm_unit,
                )
            )
    return tuple(specs)


PRODUCT_SPECS: tuple[ProductSpec, ...] = _family_specs()
PRODUCT_BY_ID: dict[str, ProductSpec] = {spec.product_id: spec for spec in PRODUCT_SPECS}
SPEC_BY_ROUTE_KEY: dict[tuple[str, str], ProductSpec] = {
    (param_name, spec.native_id): spec for spec in PRODUCT_SPECS for param_name in spec.stationparameter_names
}


def catalogue_product_rows() -> list[dict[str, object]]:
    """Build deterministic product catalogue rows matching `PRODUCT_CATALOG_SCHEMA`."""
    return [
        product_row(
            provider_id="be_wal",
            product_id=spec.product_id,
            native_id=spec.native_id,
            facts=spec.series_mapping().physical_facts(),
        )
        for spec in sorted(PRODUCT_SPECS, key=lambda item: item.product_id)
    ]


def describe_associations(associations: pl.DataFrame) -> SourceDescriptions:
    """Emit concrete `KiWIS.ts_id` source descriptions for every available station-product pair."""
    ordered = associations.filter(pl.col("available")).sort("station_id", "product_id")
    seen_pairs: set[tuple[str, str]] = set()
    descriptions: list[SourceDescription] = []
    for station_id, product_id, ts_id, ts_name in ordered.select(
        "station_id", "product_id", "ts_id", "ts_name"
    ).iter_rows():
        pair = (str(station_id), str(product_id))
        if pair in seen_pairs:
            raise FatalContractError(f"Duplicate be_wal association for {pair!r}")
        seen_pairs.add(pair)
        spec = PRODUCT_BY_ID.get(str(product_id))
        if spec is None:
            raise FatalContractError(f"Unsupported be_wal product {product_id!r}")
        if str(ts_name) != spec.native_id:
            raise FatalContractError(f"be_wal ts_name {ts_name!r} disagrees with {spec.native_id!r}")
        ts_id_str = str(ts_id)
        mapping = spec.series_mapping(published_id=ts_id_str)
        descriptions.append(
            SourceDescription(
                product_id=spec.product_id,
                station_id=str(station_id),
                native_coordinate=spec.native_id,
                identity=SourceIdentity(
                    namespace=mapping.namespace,
                    published_id=ts_id_str,
                    origin="catalogue",
                    evidence=_ASSOCIATION_EVIDENCE,
                ),
                variant=ts_id_str,
                facts=(mapping.physical_facts(),),
            )
        )
    return SourceDescriptions(provider_id="be_wal", descriptions=tuple(descriptions))
