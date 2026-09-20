"""Preserve NWIS catalogue timeseries claims without equating them to response methods."""

from __future__ import annotations

from collections.abc import Mapping

import polars as pl

from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.catalogues.schemas import CATALOGUE_SERIES_CLAIMS_SCHEMA
from rivretrieve._internal.catalogues.source_series import SourceDescriptions
from rivretrieve._internal.engine import ProviderConfig
from rivretrieve._internal.primitives import ProductId


def catalogue_claims(native: pl.DataFrame, products: Mapping[tuple[str, str, str], str]) -> pl.DataFrame:
    """Project parallel publisher catalogue arrays at their established source coordinates."""
    columns = ("data_type_cd", "parm_cd", "stat_cd", "ts_id", "loc_web_ds")
    source = native.select("site_no", *columns).explode(columns)
    rows = []
    evidence = [
        "catalogue:usgs_nwis:source.station_product.nwis_series_availability_and_coverage",
        "catalogue:usgs_nwis:source.product.nwis_parameter_statistic_data_type_codes",
    ]
    for station, data_type, parameter, statistic, ts_id, description in source.iter_rows():
        product = products.get((data_type, parameter, statistic))
        if product is None:
            continue
        rows.append(
            {
                "provider_id": "usgs_nwis",
                "station_id": station,
                "product_id": product,
                "namespace": "NWIS.ts_id",
                "published_id": ts_id,
                "description": description,
                "native_coordinates": [
                    {"name": name, "value": value}
                    for name, value in (
                        ("data_type_cd", data_type),
                        ("parm_cd", parameter),
                        ("stat_cd", statistic),
                    )
                ],
                "evidence": evidence,
            }
        )
    return pl.DataFrame(rows, schema=CATALOGUE_SERIES_CLAIMS_SCHEMA.polars_schema).unique(maintain_order=True)


def describe_catalogue(artifact: PackagedCatalogArtifact, *, config: ProviderConfig) -> SourceDescriptions:
    """Retain IV instantaneous temporal support in the shared physical vocabulary."""
    from rivretrieve._internal.catalogues.source_descriptions import generic_source_descriptions
    from rivretrieve._internal.engine import Instant
    from rivretrieve._internal.source_series import EvidenceFact, known

    descriptions = generic_source_descriptions(artifact, config)
    result = []
    for item in descriptions.descriptions:
        definition = config.products[ProductId(item.product_id)]
        if isinstance(definition.semantics, Instant):
            item = item.model_copy(
                update={
                    "facts": tuple(
                        facts.model_copy(
                            update={
                                "temporal_support": known(
                                    "instantaneous", "catalogue:usgs_nwis:source.usgs.instantaneous_value_definition"
                                ),
                                "statistic": known(
                                    "instantaneous", "catalogue:usgs_nwis:source.usgs.instantaneous_value_definition"
                                ),
                                "frequency": EvidenceFact(
                                    evidence=(
                                        "catalogue:usgs_nwis:source.product.nwis_parameter_statistic_data_type_codes",
                                    )
                                ),
                            }
                        )
                        for facts in item.facts
                    )
                }
            )
        result.append(item)
    return descriptions.model_copy(update={"descriptions": tuple(result)})
