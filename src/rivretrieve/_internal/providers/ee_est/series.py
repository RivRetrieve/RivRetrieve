"""Published Estonian Keskkonnaagentuur series identities and physical facts.

Step 3 establishes frequency, statistic, interval temporal support, stage
gauge-zero vertical reference (with source-silent datum), fixed ``+00:00`` UTC
time zone on ``f_hydroseire`` (`timeline_ts_utc` only, never DST-folded
``timeline_ts_local``), and conservative temporal silence (``day_definition``,
``timestamp_anchor``, EstModel ``time_zone``) with ``label_time="00:00"`` on
EstModel daily series (`ClippingAxis.CALENDAR_DATE`).
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

_ASSOCIATION_EVIDENCE = "catalogue:ee_est:source.station_product.associations"
_EM_FIELD_EVIDENCE = "catalogue:ee_est:source.series.fields"
_FH_FIELD_EVIDENCE = "catalogue:ee_est:source.series.hourly_fields"
_TEMPORAL_EVIDENCE = "catalogue:ee_est:source.series.temporal_semantics"
_STAGE_VERTICAL_EVIDENCE = "catalogue:ee_est:source.series.stage_vertical_reference"


@dataclass(frozen=True, slots=True)
class ProductSpec:
    """Native source mapping and verified physical contract for one ee_est product."""

    product_id: str
    source_api: Literal["estmodel", "f_hydroseire"]
    native_id: str
    quantity: Literal["discharge", "stage", "temperature"]
    source_unit: str
    frequency: Literal["daily", "hourly"]
    statistic: Literal["mean", "max", "min"]
    em_parameter: str | None = None
    em_type: str | None = None
    fh_aegrida_nimi: str | None = None

    def series_mapping(self) -> SeriesMapping:
        """Build verified Step 3 source mapping preserving explicit temporal/vertical silence."""
        is_em = self.source_api == "estmodel"
        namespace = ESTMODEL_NAMESPACE if is_em else FH_NAMESPACE
        evidence: list[str] = [_ASSOCIATION_EVIDENCE, _TEMPORAL_EVIDENCE]
        if not is_em:
            evidence.append(_FH_FIELD_EVIDENCE)
        if self.quantity == "stage":
            evidence.append(_STAGE_VERTICAL_EVIDENCE)
        identity_evidence = (_EM_FIELD_EVIDENCE,) if is_em else (_EM_FIELD_EVIDENCE, _FH_FIELD_EVIDENCE)
        return SeriesMapping(
            namespace=namespace,
            published_id=self.native_id,
            quantity=self.quantity,
            source_unit=self.source_unit,
            normalized_unit=self.source_unit,
            frequency=self.frequency,
            statistic=self.statistic,
            time_zone=None if is_em else "+00:00",
            evidence=tuple(evidence),
            identity_evidence=identity_evidence,
            temporal_support="interval",
            day_definition=None,
            timestamp_anchor=None,
            vertical_reference="gauge_zero" if self.quantity == "stage" else None,
            vertical_datum=None,
            label_time="00:00" if is_em else None,
        )


PRODUCT_SPECS: tuple[ProductSpec, ...] = (
    # EstModel daily series (estmodel.envir.ee/stations/{code}/measurements)
    ProductSpec(
        "discharge_daily_mean",
        "estmodel",
        "Q:MEAN",
        "discharge",
        "m3/s",
        "daily",
        "mean",
        em_parameter="Q",
        em_type="MEAN",
    ),
    ProductSpec(
        "discharge_daily_max",
        "estmodel",
        "Q:MAXIMUM",
        "discharge",
        "m3/s",
        "daily",
        "max",
        em_parameter="Q",
        em_type="MAXIMUM",
    ),
    ProductSpec(
        "discharge_daily_min",
        "estmodel",
        "Q:MINIMUM",
        "discharge",
        "m3/s",
        "daily",
        "min",
        em_parameter="Q",
        em_type="MINIMUM",
    ),
    ProductSpec(
        "stage_daily_mean",
        "estmodel",
        "H:MEAN",
        "stage",
        "m",
        "daily",
        "mean",
        em_parameter="H",
        em_type="MEAN",
    ),
    ProductSpec(
        "stage_daily_max",
        "estmodel",
        "H:MAXIMUM",
        "stage",
        "m",
        "daily",
        "max",
        em_parameter="H",
        em_type="MAXIMUM",
    ),
    ProductSpec(
        "stage_daily_min",
        "estmodel",
        "H:MINIMUM",
        "stage",
        "m",
        "daily",
        "min",
        em_parameter="H",
        em_type="MINIMUM",
    ),
    ProductSpec(
        "water_temperature_daily_mean",
        "estmodel",
        "T:MEAN",
        "temperature",
        "degC",
        "daily",
        "mean",
        em_parameter="T",
        em_type="MEAN",
    ),
    ProductSpec(
        "water_temperature_daily_max",
        "estmodel",
        "T:MAXIMUM",
        "temperature",
        "degC",
        "daily",
        "max",
        em_parameter="T",
        em_type="MAXIMUM",
    ),
    ProductSpec(
        "water_temperature_daily_min",
        "estmodel",
        "T:MINIMUM",
        "temperature",
        "degC",
        "daily",
        "min",
        em_parameter="T",
        em_type="MINIMUM",
    ),
    # Keskkonnaandmed PostgREST hourly series (keskkonnaandmed.envir.ee/f_hydroseire)
    ProductSpec(
        "discharge_hourly_mean",
        "f_hydroseire",
        "Äravool avg",
        "discharge",
        "m3/s",
        "hourly",
        "mean",
        fh_aegrida_nimi="Äravool avg",
    ),
    ProductSpec(
        "discharge_hourly_max",
        "f_hydroseire",
        "Äravool max",
        "discharge",
        "m3/s",
        "hourly",
        "max",
        fh_aegrida_nimi="Äravool max",
    ),
    ProductSpec(
        "discharge_hourly_min",
        "f_hydroseire",
        "Äravool min",
        "discharge",
        "m3/s",
        "hourly",
        "min",
        fh_aegrida_nimi="Äravool min",
    ),
    ProductSpec(
        "stage_hourly_mean",
        "f_hydroseire",
        "WL avg",
        "stage",
        "cm",
        "hourly",
        "mean",
        fh_aegrida_nimi="WL avg",
    ),
    ProductSpec(
        "stage_hourly_max",
        "f_hydroseire",
        "WL max",
        "stage",
        "cm",
        "hourly",
        "max",
        fh_aegrida_nimi="WL max",
    ),
    ProductSpec(
        "stage_hourly_min",
        "f_hydroseire",
        "WL min",
        "stage",
        "cm",
        "hourly",
        "min",
        fh_aegrida_nimi="WL min",
    ),
    ProductSpec(
        "water_temperature_hourly_mean",
        "f_hydroseire",
        "WT avg",
        "temperature",
        "degC",
        "hourly",
        "mean",
        fh_aegrida_nimi="WT avg",
    ),
    ProductSpec(
        "water_temperature_hourly_max",
        "f_hydroseire",
        "WT max",
        "temperature",
        "degC",
        "hourly",
        "max",
        fh_aegrida_nimi="WT max",
    ),
    ProductSpec(
        "water_temperature_hourly_min",
        "f_hydroseire",
        "WT min",
        "temperature",
        "degC",
        "hourly",
        "min",
        fh_aegrida_nimi="WT min",
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
            id_evidence = (_EM_FIELD_EVIDENCE,)
        else:
            if jaam_kood is None:
                raise FatalContractError(
                    f"Missing jaam_kood on available f_hydroseire series {station_id}/{product_id}"
                )
            published_id = f"{jaam_kood}:{spec.native_id}"
            id_evidence = (_EM_FIELD_EVIDENCE, _FH_FIELD_EVIDENCE)
        descriptions.append(
            SourceDescription(
                product_id=product_id,
                station_id=station_id,
                native_coordinate=native_id,
                identity=SourceIdentity(
                    namespace=mapping.namespace,
                    published_id=published_id,
                    origin="mapping",
                    evidence=id_evidence,
                ),
                facts=(mapping.physical_facts(),),
            )
        )
    return SourceDescriptions(provider_id="ee_est", descriptions=tuple(descriptions))
