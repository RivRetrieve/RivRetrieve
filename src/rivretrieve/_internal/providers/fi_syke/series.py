"""SYKE Hydrologiarajapinta product identity.

Shared with generate_catalogue.py (maintainer-tier): this dataclass and tuple live
here, not there, matching au_bom's rationale -- a future declaration.py import graph
(series.py <- parse.py <- declaration.py) must never reach generate_catalogue.py, a
MAINTAINER_ROLES module (tests/test_provider_architecture_contracts.py).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ProductDefinition:
    product_id: str
    observed_property: str
    frequency: str
    statistic: str
    canonical_unit: str
    native_id: str


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
    ),
    ProductDefinition(
        product_id="stage_reported",
        observed_property="stage",
        frequency="daily",
        statistic="unknown",
        canonical_unit="m",
        native_id="Vedenkorkeus",
    ),
    ProductDefinition(
        product_id="water_temperature_reported",
        observed_property="water_temperature",
        frequency="daily",
        statistic="unknown",
        canonical_unit="degC",
        native_id="LampoPintavesi",
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
