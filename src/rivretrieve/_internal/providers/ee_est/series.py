"""Published Estonian Keskkonnaagentuur series mappings for offline catalogue generation.

Step 2 builds the 18-product registry and station-product availability across
EstModel (daily Q/H/T MEAN/MAXIMUM/MINIMUM) and keskkonnaandmed.envir.ee
`f_hydroseire` (hourly Äravool/WL/WT avg/max/min) while keeping temporal and
vertical physical meanings unestablished (`None` -> unknown) until Step 3
retains and verifies physical-meaning witnesses.
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

ESTMODEL_NAMESPACE = "EE_EST.estmodel.series"
FH_NAMESPACE = "EE_EST.f_hydroseire.series"
_ASSOCIATION_EVIDENCE = ("catalogue:ee_est:source.station_product.associations",)
_FIELD_EVIDENCE = ("catalogue:ee_est:source.series.fields",)


@dataclass(frozen=True, slots=True)
class ProductSpec:
    """Native source mapping for one Estonian hydrological product."""

    product_id: str
    source_api: Literal["estmodel", "f_hydroseire"]
    native_id: str
    quantity: Literal["discharge", "stage", "temperature"]
    source_unit: str
    em_parameter: str | None = None
    em_type: str | None = None
    fh_aegrida_nimi: str | None = None

    def series_mapping(self) -> SeriesMapping:
        """Build Step 2 mapping with only source-verified quantity and native unit."""
        namespace = ESTMODEL_NAMESPACE if self.source_api == "estmodel" else FH_NAMESPACE
        return SeriesMapping(
            namespace=namespace,
            published_id=self.native_id,
            quantity=self.quantity,
            source_unit=self.source_unit,
            normalized_unit=self.source_unit,
            evidence=_ASSOCIATION_EVIDENCE,
            identity_evidence=_FIELD_EVIDENCE,
        )


PRODUCT_SPECS: tuple[ProductSpec, ...] = (
    # EstModel daily series (estmodel.envir.ee/stations/{code}/measurements)
    ProductSpec("discharge_daily_mean", "estmodel", "Q:MEAN", "discharge", "m3/s", em_parameter="Q", em_type="MEAN"),
    ProductSpec(
        "discharge_daily_max", "estmodel", "Q:MAXIMUM", "discharge", "m3/s", em_parameter="Q", em_type="MAXIMUM"
    ),
    ProductSpec(
        "discharge_daily_min", "estmodel", "Q:MINIMUM", "discharge", "m3/s", em_parameter="Q", em_type="MINIMUM"
    ),
    ProductSpec("stage_daily_mean", "estmodel", "H:MEAN", "stage", "m", em_parameter="H", em_type="MEAN"),
    ProductSpec("stage_daily_max", "estmodel", "H:MAXIMUM", "stage", "m", em_parameter="H", em_type="MAXIMUM"),
    ProductSpec("stage_daily_min", "estmodel", "H:MINIMUM", "stage", "m", em_parameter="H", em_type="MINIMUM"),
    ProductSpec(
        "water_temperature_daily_mean", "estmodel", "T:MEAN", "temperature", "degC", em_parameter="T", em_type="MEAN"
    ),
    ProductSpec(
        "water_temperature_daily_max",
        "estmodel",
        "T:MAXIMUM",
        "temperature",
        "degC",
        em_parameter="T",
        em_type="MAXIMUM",
    ),
    ProductSpec(
        "water_temperature_daily_min",
        "estmodel",
        "T:MINIMUM",
        "temperature",
        "degC",
        em_parameter="T",
        em_type="MINIMUM",
    ),
    # Keskkonnaandmed PostgREST hourly series (keskkonnaandmed.envir.ee/f_hydroseire)
    ProductSpec(
        "discharge_hourly_mean", "f_hydroseire", "Äravool avg", "discharge", "m3/s", fh_aegrida_nimi="Äravool avg"
    ),
    ProductSpec(
        "discharge_hourly_max", "f_hydroseire", "Äravool max", "discharge", "m3/s", fh_aegrida_nimi="Äravool max"
    ),
    ProductSpec(
        "discharge_hourly_min", "f_hydroseire", "Äravool min", "discharge", "m3/s", fh_aegrida_nimi="Äravool min"
    ),
    ProductSpec("stage_hourly_mean", "f_hydroseire", "WL avg", "stage", "cm", fh_aegrida_nimi="WL avg"),
    ProductSpec("stage_hourly_max", "f_hydroseire", "WL max", "stage", "cm", fh_aegrida_nimi="WL max"),
    ProductSpec("stage_hourly_min", "f_hydroseire", "WL min", "stage", "cm", fh_aegrida_nimi="WL min"),
    ProductSpec(
        "water_temperature_hourly_mean", "f_hydroseire", "WT avg", "temperature", "degC", fh_aegrida_nimi="WT avg"
    ),
    ProductSpec(
        "water_temperature_hourly_max", "f_hydroseire", "WT max", "temperature", "degC", fh_aegrida_nimi="WT max"
    ),
    ProductSpec(
        "water_temperature_hourly_min", "f_hydroseire", "WT min", "temperature", "degC", fh_aegrida_nimi="WT min"
    ),
)

PRODUCT_BY_ID: dict[str, ProductSpec] = {spec.product_id: spec for spec in PRODUCT_SPECS}
EM_KEY_TO_PRODUCT: dict[tuple[str, str], ProductSpec] = {
    (spec.em_parameter, spec.em_type): spec
    for spec in PRODUCT_SPECS
    if spec.source_api == "estmodel" and spec.em_parameter is not None and spec.em_type is not None
}
FH_AEGRIDA_TO_PRODUCT: dict[str, ProductSpec] = {
    spec.fh_aegrida_nimi: spec
    for spec in PRODUCT_SPECS
    if spec.source_api == "f_hydroseire" and spec.fh_aegrida_nimi is not None
}


def catalogue_product_rows() -> list[dict[str, object]]:
    """Build deterministic product catalogue rows matching `PRODUCT_CATALOG_SCHEMA`."""
    return [
        product_row(
            provider_id="ee_est",
            product_id=spec.product_id,
            native_id=spec.native_id,
            facts=spec.series_mapping().physical_facts(),
        )
        for spec in sorted(PRODUCT_SPECS, key=lambda item: item.product_id)
    ]


def describe_associations(associations: pl.DataFrame) -> SourceDescriptions:
    """Emit concrete source descriptions for every witnessed available pair."""
    descriptions: list[SourceDescription] = []
    available = associations.filter(pl.col("available")).sort("station_id", "product_id")
    for station_id, jaam_kood, product_id, native_id in available.select(
        "station_id", "jaam_kood", "product_id", "native_id"
    ).iter_rows():
        spec = PRODUCT_BY_ID.get(product_id)
        if spec is None:
            raise FatalContractError(f"Unsupported ee_est product {product_id!r}")
        mapping = spec.series_mapping()
        if spec.source_api == "estmodel":
            published_id = f"{station_id}:{spec.native_id}"
        else:
            if jaam_kood is None:
                raise FatalContractError(
                    f"Missing jaam_kood on available f_hydroseire series {station_id}/{product_id}"
                )
            published_id = f"{jaam_kood}:{spec.native_id}"
        descriptions.append(
            SourceDescription(
                product_id=product_id,
                station_id=station_id,
                native_coordinate=native_id,
                identity=SourceIdentity(
                    namespace=mapping.namespace,
                    published_id=published_id,
                    origin="mapping",
                    evidence=_FIELD_EVIDENCE,
                ),
                facts=(mapping.physical_facts(),),
            )
        )
    return SourceDescriptions(provider_id="ee_est", descriptions=tuple(descriptions))
