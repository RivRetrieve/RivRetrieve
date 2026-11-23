"""Build modern executable catalogue identities and retain independent legacy claims."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

import polars as pl

from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.catalogues.schemas import CATALOGUE_SERIES_CLAIMS_SCHEMA
from rivretrieve._internal.catalogues.source_series import SourceDescriptions
from rivretrieve._internal.engine import ProviderConfig
from rivretrieve._internal.primitives import ProductId


def catalogue_claims(
    native: pl.DataFrame,
    products: Mapping[tuple[str, str, str], str],
    modern_stations: pl.DataFrame,
    *,
    evidence: tuple[str, ...],
) -> pl.DataFrame:
    """Project legacy claims only for matching modern agency-qualified stations."""
    native = native.join(
        modern_stations.select("agency_code", "monitoring_location_number", "station_id"),
        left_on=["agency_cd", "site_no"],
        right_on=["agency_code", "monitoring_location_number"],
        how="inner",
        validate="m:1",
    )
    columns = ("data_type_cd", "parm_cd", "stat_cd", "ts_id", "loc_web_ds")
    source = native.select("station_id", *columns).explode(columns)
    rows = []
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


MODERN_PRODUCT_ROUTES = {
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


def modern_product(properties: Mapping[str, object]) -> str | None:
    """Select supported computations without treating event maxima as instantaneous."""
    parameter = properties.get("parameter_code")
    period = properties.get("computation_period_identifier")
    statistic = properties.get("statistic_id")
    if "statistic_id" not in properties or not isinstance(properties.get("computation_identifier"), str):
        raise ValueError("Missing or malformed modern metadata computation coordinates")
    if (
        not isinstance(parameter, str)
        or not isinstance(period, str)
        or (statistic is not None and not isinstance(statistic, str))
    ):
        raise ValueError("Malformed modern metadata product coordinates")
    product = MODERN_PRODUCT_ROUTES.get((parameter, period, statistic))
    if product is None:
        return None
    computation = properties.get("computation_identifier")
    if period == "Points" and statistic is None and computation == "Max At Event Time":
        return None
    expected = (
        {"00003": "Mean", "00001": "Max", "00002": "Min"}.get(statistic or "")
        if period == "Daily"
        else "Instantaneous"
        if statistic == "00011"
        else "Unknown"
    )
    if computation != expected:
        raise ValueError("Unresolved modern metadata computation for supported route")
    return product


def modern_source_descriptions(
    features: Iterable[Mapping[str, object]],
    monitoring_locations: Mapping[str, str],
) -> SourceDescriptions:
    """Describe supported published series at selected modern monitoring locations."""
    from rivretrieve._internal.catalogues.source_series import SourceDescription
    from rivretrieve._internal.providers.usgs_nwis.config import UsgsNwisSourceCoordinates
    from rivretrieve._internal.providers.usgs_nwis.metadata import source_series

    stations = {location: station for station, location in monitoring_locations.items()}
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
        product = modern_product(properties)
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


def retain_source_descriptions(
    current: SourceDescriptions,
    historical: SourceDescriptions,
    published_ids: tuple[str, ...],
    monitoring_locations: Mapping[str, str],
) -> SourceDescriptions:
    """Retain only explicitly selected historical series absent from current metadata.

    The complete historical descriptors stay unchanged, including physical facts
    and identity evidence. Publication records the selected historical acquisition
    separately in the catalogue provenance.
    """
    if len(set(published_ids)) != len(published_ids):
        raise ValueError("Historical series selection contains duplicate published IDs")
    current_ids = {item.identity.published_id for item in current.descriptions}
    if current_ids.intersection(published_ids):
        raise ValueError("Historical series selection overlaps current metadata")
    selected = [item for item in historical.descriptions if item.identity.published_id in published_ids]
    if len(selected) != len(published_ids) or {item.identity.published_id for item in selected} != set(published_ids):
        raise ValueError("Historical series selection does not resolve exactly")
    if any(item.station_id not in monitoring_locations for item in selected):
        raise ValueError("Historical series station is absent from selected native inventory")
    return current.model_copy(
        update={
            "descriptions": tuple(
                sorted(
                    (*current.descriptions, *selected),
                    key=lambda item: (item.station_id, item.product_id, item.variant),
                )
            )
        }
    )
