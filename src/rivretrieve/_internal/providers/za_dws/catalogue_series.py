"""Publisher field definitions for DWS catalogue-only discovery."""

import polars as pl

from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.catalogues.source_series import SourceDescription, SourceDescriptions
from rivretrieve._internal.source_series import ClippingAxis, PhysicalFacts, SourceIdentity, known

DAILY_EVIDENCE = "tests/recordings/za_dws/X3H001_daily_2020-01.html"
POINT_EVIDENCE = "tests/recordings/za_dws/X3H001_point_2020-01.html"


def describe_catalogue(artifact: PackagedCatalogArtifact) -> SourceDescriptions:
    descriptions = []
    for row in artifact.products.iter_rows(named=True):
        product = row["product_id"]
        daily = product == "discharge_daily_mean"
        stage = product == "stage_instantaneous"
        evidence = DAILY_EVIDENCE if daily else POINT_EVIDENCE
        facts = PhysicalFacts(
            facts_id=product,
            quantity=known("stage" if stage else "discharge", evidence),
            source_unit=known("m" if stage else "cubic metres/sec", evidence),
            normalized_unit="m" if stage else "m3/s",
        )
        if daily:
            facts = facts.model_copy(
                update={
                    "frequency": known("daily", evidence),
                    "statistic": known("mean", evidence),
                    "temporal_support": known("interval", evidence),
                    "clipping_axis": ClippingAxis.CALENDAR_DATE,
                }
            )
        descriptions.append(
            SourceDescription(
                product_id=product,
                native_coordinate=row["native_id"],
                identity=SourceIdentity(
                    namespace=f"za_dws/{product}",
                    origin="mapping",
                    description="Catalogue field mapping; station-specific variable identity is unresolved",
                    evidence=(evidence,),
                ),
                facts=(facts,),
            )
        )
    return SourceDescriptions(provider_id="za_dws", descriptions=tuple(descriptions))


def catalogue_claims(stations: list[str]) -> "pl.DataFrame":
    """Retain historical X3H001 identities without a national identity inference."""
    from rivretrieve._internal.catalogues.schemas import CATALOGUE_SERIES_CLAIMS_SCHEMA

    rows = []
    if "X3H001" in stations:
        for product, route, column in (
            ("discharge_daily_mean", "Daily", "D AVG F/R"),
            ("discharge_instantaneous", "Point", "COR.FLOW"),
            ("stage_instantaneous", "Point", "COR.LEVEL"),
        ):
            rows.append(
                {
                    "provider_id": "za_dws",
                    "station_id": "X3H001",
                    "product_id": product,
                    "namespace": "za_dws:HyData:Variable",
                    "published_id": "100.00",
                    "description": "Surface Water Level",
                    "native_coordinates": [
                        {"name": "Station", "value": "X3H001100.00"},
                        {"name": "DataType", "value": route},
                        {"name": "column", "value": column},
                    ],
                    "evidence": [
                        "catalogue:za_dws:source.product.daily_field_definition"
                        if route == "Daily"
                        else "catalogue:za_dws:source.product.point_field_definitions"
                    ],
                }
            )
    return pl.DataFrame(rows, schema=CATALOGUE_SERIES_CLAIMS_SCHEMA.polars_schema)
