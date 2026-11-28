"""Ireland EPA HydroNet product declarations for offline catalogue generation.

Each product is one HydroNet station parameter (``S`` water level, ``Q``
discharge) at the resolution named by its full-history file
(``complete_daymean.zip`` or ``complete_15min.zip``). Step 2 establishes only
the quantity and the published unit symbol, read from the ``#Station Parameter
Name`` and ``#Unit Symbol`` headers of retained hosted files. Frequency,
statistic, temporal support, timestamps and vertical reference remain unknown
until the series meaning is established from source evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from rivretrieve._internal.catalogues.products import product_row
from rivretrieve._internal.catalogues.source_series import SourceDescription, SourceDescriptions
from rivretrieve._internal.provider_series import SeriesMapping

PROVIDER_ID = "ie_epa"

_SERIES_FIELD_EVIDENCE = ("catalogue:ie_epa:source.series.fields",)
_ASSOCIATION_EVIDENCE = ("catalogue:ie_epa:source.station_product.associations",)

type Parameter = Literal["S", "Q"]
type FullHistoryFile = Literal["complete_daymean", "complete_15min"]
type RollingFile = Literal["1year_daymean", "3_months"]

FULL_HISTORY_FILES: tuple[FullHistoryFile, ...] = ("complete_daymean", "complete_15min")
ROLLING_FILES: tuple[RollingFile, ...] = ("1year_daymean", "3_months")
PARAMETERS: tuple[Parameter, ...] = ("S", "Q")
GAUGINGS_FILE = "Q/complete_gaugings.zip"


@dataclass(frozen=True, slots=True)
class ProductSpec:
    """One HydroNet parameter at the resolution of one full-history file."""

    product_id: str
    parameter: Parameter
    file: FullHistoryFile
    parameter_name: str
    quantity: Literal["stage", "discharge"]
    source_unit: Literal["m", "m³/s"]
    normalized_unit: Literal["m", "m3/s"]

    @property
    def native_coordinate(self) -> str:
        """Station-relative HydroNet path whose listing sets availability."""
        return f"{self.parameter}/{self.file}.zip"

    def series_mapping(self) -> SeriesMapping:
        """Map only the source-verified quantity and unit; other facts stay unknown."""
        return SeriesMapping(
            namespace=f"ie_epa.hydronet.{self.parameter}.{self.file}",
            quantity=self.quantity,
            source_unit=self.source_unit,
            normalized_unit=self.normalized_unit,
            evidence=_SERIES_FIELD_EVIDENCE,
            identity_evidence=_ASSOCIATION_EVIDENCE,
        )


PRODUCT_SPECS: tuple[ProductSpec, ...] = (
    ProductSpec("discharge_15min", "Q", "complete_15min", "River Discharge", "discharge", "m³/s", "m3/s"),
    ProductSpec("discharge_daily", "Q", "complete_daymean", "River Discharge", "discharge", "m³/s", "m3/s"),
    ProductSpec("stage_15min", "S", "complete_15min", "Stage", "stage", "m", "m"),
    ProductSpec("stage_daily", "S", "complete_daymean", "Stage", "stage", "m", "m"),
)
PRODUCT_BY_FILE: dict[tuple[Parameter, FullHistoryFile], ProductSpec] = {
    (spec.parameter, spec.file): spec for spec in PRODUCT_SPECS
}


def catalogue_product_rows() -> list[dict[str, object]]:
    """Build product rows; facts not established from source evidence are ``unknown``."""
    return [
        product_row(
            provider_id=PROVIDER_ID,
            product_id=spec.product_id,
            native_id=spec.native_coordinate,
            facts=spec.series_mapping().physical_facts(),
        )
        for spec in PRODUCT_SPECS
    ]


def describe_associations() -> SourceDescriptions:
    """Describe each product's source identity and its established physical facts."""
    descriptions = []
    for spec in PRODUCT_SPECS:
        mapping = spec.series_mapping()
        descriptions.append(
            SourceDescription(
                product_id=spec.product_id,
                native_coordinate=spec.native_coordinate,
                identity=mapping.identity(),
                facts=(mapping.physical_facts(),),
            )
        )
    return SourceDescriptions(provider_id=PROVIDER_ID, descriptions=tuple(descriptions))
