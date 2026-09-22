"""Build modern executable catalogue identities and retain independent legacy claims."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

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


def modern_source_descriptions(
    features: Iterable[Mapping[str, object]],
    monitoring_locations: Mapping[str, str],
) -> SourceDescriptions:
    """Match supported metadata records inside the retained native station scope."""
    from rivretrieve._internal.catalogues.source_series import SourceDescription
    from rivretrieve._internal.providers.usgs_nwis.config import UsgsNwisSourceCoordinates
    from rivretrieve._internal.providers.usgs_nwis.metadata import source_series

    stations = {location: station for station, location in monitoring_locations.items()}
    routes = {
        ("00060", "Daily", "00003"): "discharge_daily_mean",
        ("00065", "Daily", "00003"): "stage_daily_mean",
        ("00065", "Daily", "00001"): "stage_daily_max",
        ("00065", "Daily", "00002"): "stage_daily_min",
        **{
            (parameter, "Points", statistic): product
            for parameter, product in (("00060", "discharge_instantaneous"), ("00065", "stage_instantaneous"))
            for statistic in ("00011", None)
        },
    }
    result = {}
    for properties in features:
        location = properties.get("monitoring_location_id")
        if not isinstance(location, str):
            raise ValueError("Missing or malformed monitoring_location_id")
        station = stations.get(location)
        if station is None:
            continue
        parameter = properties.get("parameter_code")
        period = properties.get("computation_period_identifier")
        statistic = properties.get("statistic_id")
        if (
            not isinstance(parameter, str)
            or not isinstance(period, str)
            or (statistic is not None and not isinstance(statistic, str))
        ):
            raise ValueError("Malformed modern metadata product coordinates")
        product = routes.get((parameter, period, statistic))
        if product is None:
            continue
        coordinates = UsgsNwisSourceCoordinates(
            "daily" if period == "Daily" else "continuous",
            parameter,
            statistic if period == "Daily" else None,
        )
        series = source_series(
            properties, station, product, coordinates, metadata=True, monitoring_location_id=location
        )
        description = SourceDescription(
            product_id=product,
            station_id=station,
            series_id=series.series_id,
            identity=series.identity,
            variant=series.variant,
            facts=series.facts,
        )
        if series.series_id in result:
            raise ValueError(f"Duplicate modern metadata series {series.variant}")
        result[series.series_id] = description
    return SourceDescriptions(
        provider_id="usgs_nwis",
        descriptions=tuple(sorted(result.values(), key=lambda item: (item.station_id, item.product_id, item.variant))),
    )
