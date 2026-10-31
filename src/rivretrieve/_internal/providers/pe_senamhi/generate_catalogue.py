"""Offline transformations of SENAMHI station registries and product witnesses."""

from collections.abc import Mapping
from datetime import date
from typing import cast

import polars as pl

from rivretrieve._internal.catalogues.native import NativeTable, RetrievedAt, stamp_native_table
from rivretrieve._internal.issues import FatalContractError

HYDROLOGICAL_CATEGORIES = frozenset({"05", "06", "18", "22"})
STATION_SOURCE_SCHEMA = pl.Schema(
    {
        "stationId": pl.String,
        "legacyStationId": pl.String,
        "typeId": pl.String,
        "typeDescription": pl.String,
        "name": pl.String,
        "categoryId": pl.String,
        "categoryDescription": pl.String,
        "categoryAbbreviation": pl.String,
        "conditionId": pl.String,
        "subTypeId": pl.String,
        "subTypeDescription": pl.String,
        "classId": pl.String,
        "receptionTypeDescription": pl.String,
        "provinceId": pl.String,
        "departmentId": pl.String,
        "districtId": pl.String,
        "zonalDirectionId": pl.String,
        "longitude": pl.String,
        "latitude": pl.String,
        "receptionTypeId": pl.Int64,
        "longitudeDegrees": pl.Int64,
        "longitudeMinutes": pl.Int64,
        "longitudeSeconds": pl.Float64,
        "latitudeDegrees": pl.Int64,
        "latitudeMinutes": pl.Int64,
        "latitudeSeconds": pl.Float64,
        "altitude": pl.Float64,
    }
)


def _data(payload: Mapping[str, object]) -> object:
    if payload.get("status") is not True:
        raise FatalContractError("SENAMHI selected response is not successful")
    return payload.get("data")


def _rows(payload: Mapping[str, object]) -> list[dict[str, object]]:
    data = _data(payload)
    if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
        raise FatalContractError("SENAMHI registry must contain source objects")
    return cast("list[dict[str, object]]", data)


def station_native_table(
    hydrological: Mapping[str, object],
    meteorological: Mapping[str, object],
    active: Mapping[str, object],
    *,
    retrieved_at: RetrievedAt,
) -> NativeTable:
    """Retain hydrological primary identities regardless of operational condition.

    Registry category codes identify hydrological exceptions under the meteorological
    type. Legacy identifiers and published relationships never merge stations.
    Optional metadata remains null; conflicting duplicate registry rows raise.
    """
    selected: dict[str, dict[str, object]] = {}
    for payload in (hydrological, meteorological, active):
        for row in _rows(payload):
            if row.get("typeId") != "H" and row.get("categoryId") not in HYDROLOGICAL_CATEGORIES:
                continue
            identity = row.get("stationId")
            if not isinstance(identity, str) or not identity.strip():
                raise FatalContractError("SENAMHI stationId must be a nonblank source string")
            values = {name: row.get(name) for name in STATION_SOURCE_SCHEMA}
            for name, dtype in STATION_SOURCE_SCHEMA.items():
                value = values[name]
                if value is not None and (
                    (dtype == pl.String and not isinstance(value, str))
                    or (dtype == pl.Int64 and type(value) is not int)
                    or (dtype == pl.Float64 and (isinstance(value, bool) or not isinstance(value, int | float)))
                ):
                    raise FatalContractError("SENAMHI registry metadata has invalid scalar types")
            if identity in selected and selected[identity] != values:
                raise FatalContractError("SENAMHI registry snapshots disagree for one primary identity")
            selected[identity] = values
    frame = pl.DataFrame(list(selected.values()), schema=STATION_SOURCE_SCHEMA).sort("stationId")
    return stamp_native_table(frame, retrieved_at)


ASSOCIATION_SCHEMA = pl.Schema(dict.fromkeys(("station_id", "subsystem", "resolution", "variable", "unit"), pl.String))
MONTHLY_LEVEL_FIELDS = frozenset(
    {
        "NIVEL_DEL_RIO_06H",
        "NIVEL_DEL_RIO_10H",
        "NIVEL_DEL_RIO_14H",
        "NIVEL_DEL_RIO_18H",
        "NIVEL_DEL_RIO_PROMEDIO",
        "N_NIVELAGUA",
        "N_NIVELMEDIO",
        "N_NIV_INST_00",
        "N_NIV_INST_10",
    }
)


def phisis_associations(
    payload: Mapping[str, object], *, station: str, resolution: str, variable: str, station_ids: set[str]
) -> pl.DataFrame:
    """Read recognized PHISIS identities even when their bounded window is empty.

    Units come from the response, independently of station levelType. Sample
    values and dates are not copied into the catalogue.
    """
    data = _data(payload)
    if not isinstance(data, dict):
        raise FatalContractError("PHISIS association requires an identifying response envelope")
    data = cast("dict[str, object]", data)
    identity = data.get("station")
    identity = cast("dict[str, object]", identity) if isinstance(identity, dict) else None
    if (
        station not in station_ids
        or not isinstance(identity, dict)
        or identity.get("code") != station
        or resolution not in {"DAILY", "HOURLY"}
        or data.get("type") != resolution
        or variable not in {"FLOW", "LEVEL"}
        or data.get("variable") != variable
    ):
        raise FatalContractError("PHISIS response differs from its selected station-variable request")
    unit = data.get("unit")
    if unit not in ({"m3/s"} if variable == "FLOW" else {"m", "m.s.n.m"}):
        raise FatalContractError("PHISIS association has an unsupported source unit")
    return pl.DataFrame([(station, "phisis", resolution, variable, unit)], schema=ASSOCIATION_SCHEMA, orient="row")


def monthly_associations(payload: Mapping[str, object], *, station: str, station_ids: set[str]) -> pl.DataFrame:
    """Preserve individually witnessed monthly level fields without assigning time meaning.

    The selected request supplies station identity because the monthly envelope
    does not repeat it. Meteorological-only answers establish no level association.
    """
    data = _data(payload)
    if station not in station_ids or not isinstance(data, dict):
        raise FatalContractError("Monthly association requires a selected registry station and columns")
    data = cast("dict[str, object]", data)
    columns = data.get("columns")
    if not isinstance(columns, list):
        raise FatalContractError("Monthly association requires source columns")
    rows = []
    for column in columns:
        if not isinstance(column, dict):
            raise FatalContractError("Monthly source column must be an object")
        column = cast("dict[str, object]", column)
        name = column.get("column")
        if name not in MONTHLY_LEVEL_FIELDS:
            continue
        if column.get("unit") != "m":
            raise FatalContractError("Monthly level association has an unsupported source unit")
        rows.append((station, "monthly_archive", None, name, column["unit"]))
    return pl.DataFrame(rows, schema=ASSOCIATION_SCHEMA, orient="row").unique().sort(ASSOCIATION_SCHEMA.names())


def association_product(subsystem: str, resolution: str | None, variable: str, unit: str) -> str:
    if subsystem == "phisis":
        suffix = "_above_sea_level" if unit == "m.s.n.m" else ""
        return f"phisis_{str(resolution).lower()}_{variable.lower()}{suffix}"
    return f"monthly_archive_{variable.lower()}"


def catalogue_tables(
    native: NativeTable, associations: pl.DataFrame, *, checked_on: "date"
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Build witnessed product candidates and leave all other station pairs unknown.

    Sampling frequency names remain source identity, without claiming temporal
    support or statistics. Sample dates never become published record bounds.
    """
    from rivretrieve._internal.catalogues.schemas import (
        PRODUCT_CATALOG_SCHEMA,
        STATION_CATALOG_SCHEMA,
        STATION_PRODUCT_CATALOG_SCHEMA,
        validate_catalogue,
    )

    stations = native.data.select(
        pl.lit("pe_senamhi").alias("provider_id"),
        pl.col("stationId").alias("station_id"),
        pl.col("latitude").cast(pl.Float64),
        pl.col("longitude").cast(pl.Float64),
        pl.lit("unknown").alias("crs"),
    ).sort("station_id")
    if not set(associations["station_id"]) <= set(stations["station_id"]):
        raise FatalContractError("SENAMHI association is absent from selected registry")
    rows = []
    for subsystem, resolution, variable, unit in (
        associations.select("subsystem", "resolution", "variable", "unit")
        .unique()
        .sort("subsystem", "resolution", "variable", "unit")
        .iter_rows()
    ):
        rows.append(
            {
                "provider_id": "pe_senamhi",
                "product_id": association_product(subsystem, resolution, variable, unit),
                "observed_property": "discharge" if variable == "FLOW" else "stage",
                "frequency": "unknown",
                "statistic": "unknown",
                "period_type": "unknown",
                "period_anchor": "unknown",
                "unit": "m3/s" if variable == "FLOW" else "m",
                "native_id": ":".join(
                    str(value) for value in (subsystem, resolution, variable, unit) if value is not None
                ),
            }
        )
    products = pl.DataFrame(rows, schema=PRODUCT_CATALOG_SCHEMA.polars_schema).sort("product_id")
    observed = {
        (station, association_product(subsystem, resolution, variable, unit))
        for station, subsystem, resolution, variable, unit in associations.iter_rows()
    }
    pairs = pl.DataFrame(
        [
            {
                "provider_id": "pe_senamhi",
                "station_id": station,
                "product_id": product,
                "availability": "available" if (station, product) in observed else "unknown",
                "availability_reason": "Recognized source association; historical inventory remains incomplete"
                if (station, product) in observed
                else "No association established by selected samples",
                "published_record_start_date": None,
                "published_record_end_date": None,
                "last_catalogue_check": checked_on,
            }
            for station in stations["station_id"]
            for product in products["product_id"]
        ],
        schema=STATION_PRODUCT_CATALOG_SCHEMA.polars_schema,
    )
    for frame, schema in (
        (products, PRODUCT_CATALOG_SCHEMA),
        (stations, STATION_CATALOG_SCHEMA),
        (pairs, STATION_PRODUCT_CATALOG_SCHEMA),
    ):
        validate_catalogue(frame, schema, on_issue="raise")
    return products, stations, pairs


def describe_associations(associations: pl.DataFrame):
    """Describe witnessed source identities with only established physical facts."""
    from rivretrieve._internal.catalogues.source_series import SourceDescription, SourceDescriptions
    from rivretrieve._internal.source_series import EvidenceFact, PhysicalFacts, SourceIdentity, known, stable_id

    evidence = "catalogue:pe_senamhi:source.station_product.associations"
    descriptions = []
    for station, subsystem, resolution, variable, unit in associations.sort(ASSOCIATION_SCHEMA.names()).iter_rows():
        facts = PhysicalFacts(
            facts_id="pending",
            quantity=known("discharge" if variable == "FLOW" else "stage", evidence),
            source_unit=known(unit, evidence),
            normalized_unit="m3/s" if variable == "FLOW" else "m",
            vertical_reference=known("above_sea_level", evidence) if unit == "m.s.n.m" else EvidenceFact(),
        )
        facts = facts.model_copy(update={"facts_id": stable_id(facts.model_dump_json(exclude={"facts_id"}))})
        descriptions.append(
            SourceDescription(
                product_id=association_product(subsystem, resolution, variable, unit),
                station_id=station,
                identity_key=(subsystem, resolution, variable, unit),
                native_coordinate=variable,
                identity=SourceIdentity(
                    namespace=f"senamhi.{subsystem}", published_id=variable, origin="catalogue", evidence=(evidence,)
                ),
                facts=(facts,),
            )
        )
    return SourceDescriptions(provider_id="pe_senamhi", descriptions=tuple(descriptions))
