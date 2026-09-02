"""refresh : HubeauHydrometryStations × RetrievedAt × HubeauTemperatureStations × RetrievedAt → WithIssues[NativeTable]; build : NativeTable × FranceOriginDeclarations → GeneratedFrHubeauCatalogue (pure)."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast

import polars as pl

from rivretrieve._internal.acquisition_provenance import AcquisitionProvenance, verify_provenance_recordings
from rivretrieve._internal.catalogue_origins import OriginDeclarations, enforce_catalogue_origins
from rivretrieve._internal.catalogues.artifact import (
    PackagedCatalogArtifact,
    packaged_catalogue_artifact_from_components,
)
from rivretrieve._internal.catalogues.native import (
    RETRIEVED_AT_DTYPE,
    NativeTable,
    RetrievedAt,
    read_native_table,
    stamp_native_table,
    write_native_table,
)
from rivretrieve._internal.catalogues.schemas import (
    PRODUCT_CATALOG_SCHEMA,
    PROVIDER_INFO_CATALOG_SCHEMA,
    STATION_CATALOG_SCHEMA,
    STATION_PRODUCT_CATALOG_SCHEMA,
    AvailabilityDtype,
    ProductCatalog,
    StationCatalog,
    StationProductCatalog,
    validate_catalogue,
)
from rivretrieve._internal.engine import WithIssues
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.fr_hubeau.origins import (
    NATIVE_TABLE_BYTE_SIZE,
    NATIVE_TABLE_SHA256,
    build_acquisition_provenance,
)

PROVIDER_ID = ProviderId("fr_hubeau")
PROVIDER_NAME = "Hubeau / SCHAPI — French national hydrometric network"

HYDRO_STATIONS_URL = "https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/stations"
HYDRO_STATIONS_PARAMS = "format=json&size=5000&in_use=true"
HYDRO_SITES_URL = "https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/sites"
TEMP_STATIONS_URL = "https://hubeau.eaufrance.fr/api/v1/temperature/station"
TEMP_STATIONS_PARAMS = "size=5000"

AVAILABILITY_REASON = "Hubeau catalogue does not expose per-variable station availability"
AVAILABILITY_SOURCE = "provider_station_catalogue_assumption"
MIN_LIVE_HYDRO_STATIONS = 500
MIN_LIVE_TEMP_STATIONS = 50

NATIVE_SOURCE_COLUMNS = (
    "altitude_ref_alti_station",
    "code_commune_station",
    "code_cours_eau",
    "code_departement",
    "code_finalite_station",
    "code_projection",
    "code_regime_station",
    "code_region",
    "code_sandre_reseau_station",
    "code_site",
    "code_station",
    "code_systeme_alti_site",
    "commentaire_influence_locale_station",
    "commentaire_station",
    "coordonnee_x_station",
    "coordonnee_y_station",
    "date_activation_ref_alti_station",
    "date_debut_ref_alti_station",
    "date_fermeture_station",
    "date_maj_ref_alti_station",
    "date_maj_station",
    "date_ouverture_station",
    "descriptif_station",
    "en_service",
    "geometry",
    "influence_locale_station",
    "latitude_station",
    "libelle_commune",
    "libelle_cours_eau",
    "libelle_departement",
    "libelle_region",
    "libelle_site",
    "libelle_station",
    "longitude_station",
    "qualification_donnees_station",
    "type_contexte_loi_stat_station",
    "type_loi_station",
    "type_station",
    "uri_cours_eau",
    "uri_station",
    "localisation",
    "coordonnee_x",
    "coordonnee_y",
    "code_type_projection",
    "longitude",
    "latitude",
    "code_commune",
    "code_troncon_hydro",
    "code_masse_eau",
    "libelle_masse_eau",
    "uri_masse_eau",
    "code_sous_bassin",
    "libelle_sous_bassin",
    "code_bassin",
    "libelle_bassin",
    "uri_bassin",
    "pk",
    "altitude",
    "date_maj_infos",
    "libelle_type_projection",
    "date_mise_en_service",
    "date_mise_hors_service",
    "code_eu_masse_eau",
    "code_eu_bassin",
    "superficie_topo",
    "superficie_reelle",
    "premier_mois_etiage",
    "commentaire",
    "nature_station",
    "type_entite_hydro",
    "uri_sous_bassin",
)

HYDROMETRY_REQUIRED_FIELDS = NATIVE_SOURCE_COLUMNS[:39]
TEMPERATURE_REQUIRED_FIELDS = (
    "code_station",
    "libelle_station",
    "uri_station",
    "localisation",
    "coordonnee_x",
    "coordonnee_y",
    "code_type_projection",
    "longitude",
    "latitude",
    "code_commune",
    "libelle_commune",
    "code_departement",
    "libelle_departement",
    "code_region",
    "libelle_region",
    "code_troncon_hydro",
    "code_cours_eau",
    "libelle_cours_eau",
    "uri_cours_eau",
    "code_masse_eau",
    "libelle_masse_eau",
    "uri_masse_eau",
    "code_sous_bassin",
    "libelle_sous_bassin",
    "code_bassin",
    "libelle_bassin",
    "uri_bassin",
    "pk",
    "altitude",
    "date_maj_infos",
    "geometry",
    "libelle_type_projection",
    "date_mise_en_service",
    "date_mise_hors_service",
    "code_eu_masse_eau",
    "code_eu_bassin",
    "superficie_topo",
    "superficie_reelle",
    "premier_mois_etiage",
    "commentaire",
    "nature_station",
    "type_entite_hydro",
    "uri_sous_bassin",
)

_FLOAT_COLUMNS = frozenset(
    {
        "altitude",
        "altitude_ref_alti_station",
        "coordonnee_x",
        "coordonnee_x_station",
        "coordonnee_y",
        "coordonnee_y_station",
        "latitude",
        "latitude_station",
        "longitude",
        "longitude_station",
        "pk",
        "superficie_reelle",
        "superficie_topo",
    }
)
_INTEGER_COLUMNS = frozenset(
    {
        "code_projection",
        "code_regime_station",
        "code_systeme_alti_site",
        "code_type_projection",
        "influence_locale_station",
        "premier_mois_etiage",
        "qualification_donnees_station",
        "type_contexte_loi_stat_station",
        "type_loi_station",
    }
)
_GEOMETRY_DTYPE = pl.Struct(
    {
        "coordinates": pl.List(pl.Float64),
        "crs": pl.Struct(
            {
                "properties": pl.Struct({"name": pl.String}),
                "type": pl.String,
            }
        ),
        "type": pl.String,
    }
)


def _native_source_dtype(column: str) -> pl.DataType | type[pl.DataType]:
    if column in _FLOAT_COLUMNS:
        return pl.Float64
    if column in _INTEGER_COLUMNS:
        return pl.Int64
    if column == "en_service":
        return pl.Boolean
    if column == "code_sandre_reseau_station":
        return pl.List(pl.String)
    if column == "geometry":
        return _GEOMETRY_DTYPE
    return pl.String


NATIVE_SOURCE_SCHEMA = pl.Schema({column: _native_source_dtype(column) for column in NATIVE_SOURCE_COLUMNS})
NATIVE_SCHEMA = pl.Schema(
    {
        **dict(NATIVE_SOURCE_SCHEMA),
        "source_endpoint": pl.String,
        "retrieved_at": RETRIEVED_AT_DTYPE,
    }
)


@dataclass(frozen=True)
class GeneratedFrHubeauCatalogue:
    provider_info: dict[str, object]
    products: ProductCatalog
    stations: StationCatalog
    station_products: StationProductCatalog
    acquisition_provenance: AcquisitionProvenance
    public_artifact: PackagedCatalogArtifact


@dataclass(frozen=True)
class ProductDefinition:
    product_id: str
    observed_property: str
    frequency: str
    statistic: str
    period_type: str
    period_anchor: str
    canonical_unit: str
    api_type: str
    grandeur_code: str | None


PRODUCT_DEFINITIONS: tuple[ProductDefinition, ...] = (
    # --- obs_tr (real-time, ~1 month lookback) --------------------------------
    ProductDefinition(
        product_id="discharge_instantaneous",
        observed_property="discharge",
        frequency="irregular",
        statistic="instantaneous",
        period_type="instant",
        period_anchor="instant",
        canonical_unit="m3/s",
        api_type="obs_tr",
        grandeur_code="Q",
    ),
    ProductDefinition(
        product_id="stage_instantaneous",
        observed_property="stage",
        frequency="irregular",
        statistic="instantaneous",
        period_type="instant",
        period_anchor="instant",
        canonical_unit="m",
        api_type="obs_tr",
        grandeur_code="H",
    ),
    # --- obs_elab (historical archive) ----------------------------------------
    # NOTE: HmnJ (daily mean height) does NOT exist in Hubeau obs_elab.
    # The grandeur_hydro request parameter is ignored by the API; filtering is
    # done by the parser on the grandeur_hydro_elab field in each response row.
    ProductDefinition(
        product_id="discharge_daily_mean",
        observed_property="discharge",
        frequency="daily",
        statistic="mean",
        period_type="interval",
        period_anchor="provider_defined",
        canonical_unit="m3/s",
        api_type="obs_elab",
        grandeur_code="QmnJ",
    ),
    ProductDefinition(
        product_id="discharge_daily_max",
        observed_property="discharge",
        frequency="daily",
        statistic="max",
        period_type="interval",
        period_anchor="provider_defined",
        canonical_unit="m3/s",
        api_type="obs_elab",
        grandeur_code="QIXnJ",
    ),
    ProductDefinition(
        product_id="stage_daily_max",
        observed_property="stage",
        frequency="daily",
        statistic="max",
        period_type="interval",
        period_anchor="provider_defined",
        canonical_unit="m",
        api_type="obs_elab",
        grandeur_code="HIXnJ",
    ),
    # --- temperature/chronique (historical archive) ---------------------------
    ProductDefinition(
        product_id="water_temperature_instantaneous",
        observed_property="water_temperature",
        frequency="irregular",
        statistic="instantaneous",
        period_type="instant",
        period_anchor="instant",
        canonical_unit="degC",
        api_type="temperature",
        grandeur_code=None,
    ),
)

HYDRO_PRODUCT_DEFS = tuple(d for d in PRODUCT_DEFINITIONS if d.api_type in {"obs_elab", "obs_tr"})
TEMP_PRODUCT_DEFS = tuple(d for d in PRODUCT_DEFINITIONS if d.api_type == "temperature")
EXPECTED_PRODUCT_IDS = frozenset(d.product_id for d in PRODUCT_DEFINITIONS)


def refresh_native_table(
    hydro_payload: object,
    temperature_payload: object,
    *,
    hydro_retrieved_at: RetrievedAt,
    temperature_retrieved_at: RetrievedAt,
) -> WithIssues[NativeTable]:
    hydro_result = _validated_native_rows(
        hydro_payload,
        source_endpoint="hydrometry",
        required_fields=HYDROMETRY_REQUIRED_FIELDS,
    )
    if isinstance(hydro_result, Issue):
        return _failed_native_refresh(hydro_result)
    temperature_result = _validated_native_rows(
        temperature_payload,
        source_endpoint="temperature",
        required_fields=TEMPERATURE_REQUIRED_FIELDS,
    )
    if isinstance(temperature_result, Issue):
        return _failed_native_refresh(temperature_result)

    hydro_ids = [cast(str, row["code_station"]) for row in hydro_result]
    temperature_ids = [cast(str, row["code_station"]) for row in temperature_result]
    collision = set(hydro_ids).intersection(temperature_ids)
    if collision:
        station_id = sorted(collision)[0]
        return _failed_native_refresh(_native_issue(f"fr_hubeau station {station_id} occurs in both station endpoints"))
    if len(hydro_ids) != 6454:
        return _failed_native_refresh(
            _native_issue(f"fr_hubeau hydrometry response contains {len(hydro_ids)} stations; expected 6454")
        )
    if len(temperature_ids) != 869:
        return _failed_native_refresh(
            _native_issue(f"fr_hubeau temperature response contains {len(temperature_ids)} stations; expected 869")
        )

    hydro_frame = _native_endpoint_frame(
        hydro_result,
        "hydrometrie/referentiel/stations",
        HYDROMETRY_REQUIRED_FIELDS,
    )
    temperature_frame = _native_endpoint_frame(
        temperature_result,
        "temperature/station",
        TEMPERATURE_REQUIRED_FIELDS,
    )
    stamped_hydro = stamp_native_table(hydro_frame, hydro_retrieved_at)
    stamped_temperature = stamp_native_table(temperature_frame, temperature_retrieved_at)
    union = pl.concat([stamped_hydro.data, stamped_temperature.data]).select(NATIVE_SCHEMA.names()).sort("code_station")
    return WithIssues(value=NativeTable(union), issues=())


def refresh_native_table_from_fixtures(
    hydro_fixture_path: Path | str,
    temperature_fixture_path: Path | str,
    *,
    hydro_retrieved_at: RetrievedAt,
    temperature_retrieved_at: RetrievedAt,
) -> WithIssues[NativeTable]:
    return refresh_native_table(
        _read_fixture_json(Path(hydro_fixture_path)),
        _read_fixture_json(Path(temperature_fixture_path)),
        hydro_retrieved_at=hydro_retrieved_at,
        temperature_retrieved_at=temperature_retrieved_at,
    )


def native_table_content_digest(native_table: NativeTable) -> str:
    payload = {
        "columns": native_table.data.columns,
        "rows": [[_native_json_value(value) for value in row] for row in native_table.data.iter_rows(named=False)],
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _native_json_value(value: object) -> object:
    if isinstance(value, datetime):
        utc_value = value.astimezone(UTC)
        return utc_value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if isinstance(value, list):
        return [_native_json_value(member) for member in value]
    if isinstance(value, dict):
        return {key: _native_json_value(member) for key, member in value.items()}
    return value


def _validated_native_rows(
    payload: object,
    *,
    source_endpoint: str,
    required_fields: tuple[str, ...],
) -> list[dict[str, object]] | Issue:
    if not isinstance(payload, dict):
        return _native_issue(f"fr_hubeau {source_endpoint} response must be an object")
    payload_mapping = cast("dict[str, object]", payload)
    data = payload_mapping.get("data")
    if not isinstance(data, list):
        return _native_issue(f"fr_hubeau {source_endpoint} response data must be a list")
    count = payload_mapping.get("count")
    if type(count) is not int:
        return _native_issue(f"fr_hubeau {source_endpoint} response count must be a non-boolean integer")
    if count != len(data):
        return _native_issue(f"fr_hubeau {source_endpoint} response count {count} does not match {len(data)} rows")

    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    required_set = set(required_fields)
    for index, raw_row in enumerate(data):
        if not isinstance(raw_row, dict):
            return _native_issue(f"fr_hubeau {source_endpoint} station {index} must be an object")
        row_mapping = cast("dict[str, object]", raw_row)
        raw_id = row_mapping.get("code_station")
        identifier = raw_id if isinstance(raw_id, str) and raw_id.strip() else index
        if not required_set.issubset(row_mapping):
            return _native_issue(f"fr_hubeau {source_endpoint} station {identifier} is missing required source fields")
        if not isinstance(raw_id, str) or not raw_id or not raw_id.strip():
            return _native_issue(f"fr_hubeau {source_endpoint} station {index} has invalid code_station")
        if not _row_values_inhabit_native_schema(row_mapping, required_fields):
            return _native_issue(
                f"fr_hubeau {source_endpoint} station {identifier} has source values outside the native schema"
            )
        if raw_id in seen:
            return _native_issue(f"fr_hubeau {source_endpoint} repeats code_station {raw_id}")
        seen.add(raw_id)
        rows.append(row_mapping)
    return rows


def _row_values_inhabit_native_schema(row: Mapping[str, object], required_fields: tuple[str, ...]) -> bool:
    for column in required_fields:
        value = row[column]
        if value is None:
            continue
        if column in _FLOAT_COLUMNS:
            if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
                return False
        elif column in _INTEGER_COLUMNS:
            if type(value) is not int:
                return False
        elif column == "en_service":
            if not isinstance(value, bool):
                return False
        elif column == "code_sandre_reseau_station":
            if not isinstance(value, list) or not all(isinstance(member, str) for member in value):
                return False
        elif column == "geometry":
            if not _geometry_inhabits_native_schema(value):
                return False
        elif not isinstance(value, str):
            return False
    return True


def _geometry_inhabits_native_schema(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != {"coordinates", "crs", "type"}:
        return False
    geometry = cast("dict[str, object]", value)
    coordinates = geometry["coordinates"]
    crs = geometry["crs"]
    if not isinstance(coordinates, list) or not all(
        not isinstance(member, bool) and isinstance(member, int | float) and math.isfinite(member)
        for member in coordinates
    ):
        return False
    if not isinstance(crs, dict):
        return False
    crs_mapping = cast("dict[str, object]", crs)
    if set(crs_mapping) != {"properties", "type"} or not isinstance(crs_mapping["type"], str):
        return False
    properties = crs_mapping["properties"]
    if not isinstance(properties, dict):
        return False
    properties_mapping = cast("dict[str, object]", properties)
    return (
        set(properties_mapping) == {"name"}
        and isinstance(properties_mapping["name"], str)
        and isinstance(geometry["type"], str)
    )


def _native_endpoint_frame(
    rows: list[dict[str, object]],
    source_endpoint: str,
    required_fields: tuple[str, ...],
) -> pl.DataFrame:
    aligned_rows = [
        {
            **{column: row[column] if column in required_fields else None for column in NATIVE_SOURCE_COLUMNS},
            "source_endpoint": source_endpoint,
        }
        for row in rows
    ]
    schema = pl.Schema({**dict(NATIVE_SOURCE_SCHEMA), "source_endpoint": pl.String})
    return pl.DataFrame(aligned_rows, schema=schema)


def _native_issue(message: str) -> Issue:
    return Issue(
        severity="error",
        code="invalid_native_station_capture",
        message=message,
        provider_id=PROVIDER_ID,
    )


def _failed_native_refresh(issue: Issue) -> WithIssues[NativeTable]:
    empty = NativeTable(pl.DataFrame(schema=NATIVE_SCHEMA))
    return WithIssues(value=empty, issues=(issue,))


def build_catalogue(
    native_table: NativeTable,
    origins: Mapping[str, OriginDeclarations],
) -> GeneratedFrHubeauCatalogue:
    endpoints = native_table.data["source_endpoint"].unique().sort().to_list()
    expected = frozenset({"hydrometrie/referentiel/stations", "temperature/station"})
    unknown = sorted(value for value in endpoints if value not in expected)
    if unknown:
        _raise_catalogue_issue(
            "catalogue_native.unknown_source_endpoint",
            f"fr_hubeau native table contains unknown source_endpoint {unknown[0]}",
        )
    hydro = NativeTable(native_table.data.filter(pl.col("source_endpoint") == "hydrometrie/referentiel/stations"))
    temperature = NativeTable(native_table.data.filter(pl.col("source_endpoint") == "temperature/station"))
    if hydro.data.height != 6454:
        raise FatalContractError(f"fr_hubeau native hydrometry partition has {hydro.data.height} rows; expected 6454")
    if temperature.data.height != 869:
        raise FatalContractError(
            f"fr_hubeau native temperature partition has {temperature.data.height} rows; expected 869"
        )
    hydro_origins = origins["hydrometrie/referentiel/stations"]
    temperature_origins = origins["temperature/station"]
    _require_origin_columns(hydro, hydro_origins)
    _require_origin_columns(temperature, temperature_origins)
    hydro_stations = build_hydro_stations(hydro)
    temperature_stations = build_temp_stations(temperature)
    enforce_catalogue_origins(PROVIDER_ID, hydro_origins, hydro, hydro_stations)
    enforce_catalogue_origins(PROVIDER_ID, temperature_origins, temperature, temperature_stations)
    stations: StationCatalog = pl.concat([hydro_stations, temperature_stations]).sort("station_id")
    hydro_dates = hydro.data.select(
        pl.col("code_station").cast(pl.String).alias("station_id"),
        pl.col("retrieved_at").dt.date().alias("retrieved_date"),
    ).sort("station_id")
    temperature_dates = temperature.data.select(
        pl.col("code_station").cast(pl.String).alias("station_id"),
        pl.col("retrieved_at").dt.date().alias("retrieved_date"),
    ).sort("station_id")
    products = build_products()
    station_products = build_station_products(hydro_dates, temperature_dates)
    maximum_retrieved_at = native_table.data["retrieved_at"].max()
    if not isinstance(maximum_retrieved_at, datetime):
        raise FatalContractError("fr_hubeau native table has no valid retrieved_at values")
    provider_info = build_provider_info(maximum_retrieved_at.date())
    acquisition_provenance = build_acquisition_provenance(
        station_ids=tuple(stations.get_column("station_id").cast(pl.String).to_list()),
        station_product_keys=tuple(station_products.select("station_id", "product_id").iter_rows()),
    )
    artifact = validate_generated_catalogue(provider_info, products, stations, station_products, acquisition_provenance)
    return GeneratedFrHubeauCatalogue(
        provider_info,
        products,
        stations,
        station_products,
        acquisition_provenance,
        artifact,
    )


def _require_origin_columns(native_table: NativeTable, origins: OriginDeclarations) -> None:
    for canonical_column, origin in origins.items():
        native_column = getattr(origin, "native_column", None)
        if native_column is not None and str(native_column) not in native_table.data.columns:
            _raise_catalogue_issue(
                "catalogue_origin.absent_native_column",
                f"fr_hubeau.{canonical_column}: native column '{native_column}' does not exist",
            )


def _raise_catalogue_issue(code: str, message: str) -> None:
    issue = Issue(severity="error", code=code, message=message, provider_id=PROVIDER_ID)
    raise FatalContractError(message, issues=(issue,))


def build_products() -> ProductCatalog:
    rows = [
        {
            "provider_id": PROVIDER_ID,
            "product_id": d.product_id,
            "observed_property": d.observed_property,
            "frequency": d.frequency,
            "statistic": d.statistic,
            "period_type": d.period_type,
            "period_anchor": d.period_anchor,
            "unit": d.canonical_unit,
            "native_id": d.grandeur_code or d.api_type,
        }
        for d in PRODUCT_DEFINITIONS
    ]
    return pl.DataFrame(rows, schema=PRODUCT_CATALOG_SCHEMA.polars_schema).sort("product_id")


def build_hydro_stations(native_table: NativeTable) -> StationCatalog:
    from rivretrieve._internal.providers.fr_hubeau.origins import CODE_PROJECTION_31_METROPOLITAN_BOUNDS

    correction_rows = native_table.data.filter(pl.col("code_projection") == 31)
    for row in correction_rows.select(
        "code_station",
        "latitude_station",
        "longitude_station",
        "coordonnee_x_station",
        "coordonnee_y_station",
    ).iter_rows(named=True):
        station_id = row["code_station"]
        if (
            row["coordonnee_x_station"] != row["latitude_station"]
            or row["coordonnee_y_station"] != row["longitude_station"]
        ):
            _raise_catalogue_issue(
                "catalogue_coordinate.correction_precondition_failed",
                f"fr_hubeau station {station_id} code_projection=31 does not match the documented transposition signature",
            )
        corrected_latitude = row["longitude_station"]
        corrected_longitude = row["latitude_station"]
        latitude_bounds = CODE_PROJECTION_31_METROPOLITAN_BOUNDS["latitude"]
        longitude_bounds = CODE_PROJECTION_31_METROPOLITAN_BOUNDS["longitude"]
        if not (
            latitude_bounds[0] <= corrected_latitude <= latitude_bounds[1]
            and longitude_bounds[0] <= corrected_longitude <= longitude_bounds[1]
        ):
            _raise_catalogue_issue(
                "catalogue_coordinate.outside_metropolitan_bounds",
                f"fr_hubeau station {station_id} remains outside the evidenced metropolitan bounds after code_projection=31 correction",
            )
    return (
        native_table.data.select(
            pl.lit(PROVIDER_ID, dtype=pl.String).alias("provider_id"),
            pl.col("code_station").cast(pl.String).alias("station_id"),
            pl.when(pl.col("code_projection") == 31)
            .then(pl.col("longitude_station"))
            .otherwise(pl.col("latitude_station"))
            .alias("latitude"),
            pl.when(pl.col("code_projection") == 31)
            .then(pl.col("latitude_station"))
            .otherwise(pl.col("longitude_station"))
            .alias("longitude"),
            pl.lit("EPSG:4326").alias("crs"),
        )
        .cast(STATION_CATALOG_SCHEMA.polars_schema)
        .sort("station_id")
    )


def build_temp_stations(native_table: NativeTable) -> StationCatalog:
    return (
        native_table.data.select(
            pl.lit(PROVIDER_ID, dtype=pl.String).alias("provider_id"),
            pl.col("code_station").cast(pl.String).alias("station_id"),
            pl.col("latitude"),
            pl.col("longitude"),
            pl.lit("EPSG:4326").alias("crs"),
        )
        .cast(STATION_CATALOG_SCHEMA.polars_schema)
        .sort("station_id")
    )


def build_station_products(
    hydro_station_dates: pl.DataFrame,
    temperature_station_dates: pl.DataFrame,
) -> StationProductCatalog:
    rows: list[dict[str, object]] = []
    for station_id, catalogue_date in hydro_station_dates.iter_rows():
        if not isinstance(station_id, str) or not isinstance(catalogue_date, date):
            raise FatalContractError("hydrometry station retrieval date must pair a string identifier with a date")
        for d in HYDRO_PRODUCT_DEFS:
            rows.append(
                {
                    "provider_id": PROVIDER_ID,
                    "station_id": station_id,
                    "product_id": d.product_id,
                    "availability": (
                        "available"
                        if (station_id, d.product_id)
                        in {
                            ("1011000101", "discharge_daily_mean"),
                            ("1011000101", "discharge_daily_max"),
                            ("1011000101", "stage_daily_max"),
                            ("Y251002001", "discharge_instantaneous"),
                            ("Y251002001", "stage_instantaneous"),
                            ("01001336", "water_temperature_instantaneous"),
                        }
                        else "unknown"
                    ),
                    "availability_reason": (
                        "Non-empty official source recording"
                        if (station_id, d.product_id)
                        in {
                            ("1011000101", "discharge_daily_mean"),
                            ("1011000101", "discharge_daily_max"),
                            ("1011000101", "stage_daily_max"),
                            ("Y251002001", "discharge_instantaneous"),
                            ("Y251002001", "stage_instantaneous"),
                            ("01001336", "water_temperature_instantaneous"),
                        }
                        else AVAILABILITY_REASON
                    ),
                    "published_record_start_date": None,
                    "published_record_end_date": None,
                    "last_catalogue_check": date(2026, 9, 2)
                    if (station_id, d.product_id)
                    in {
                        ("1011000101", "discharge_daily_mean"),
                        ("1011000101", "discharge_daily_max"),
                        ("1011000101", "stage_daily_max"),
                        ("Y251002001", "discharge_instantaneous"),
                        ("Y251002001", "stage_instantaneous"),
                        ("01001336", "water_temperature_instantaneous"),
                    }
                    else catalogue_date,
                }
            )

    for station_id, catalogue_date in temperature_station_dates.iter_rows():
        if not isinstance(station_id, str) or not isinstance(catalogue_date, date):
            raise FatalContractError("temperature station retrieval date must pair a string identifier with a date")
        for d in TEMP_PRODUCT_DEFS:
            rows.append(
                {
                    "provider_id": PROVIDER_ID,
                    "station_id": station_id,
                    "product_id": d.product_id,
                    "availability": (
                        "available"
                        if (station_id, d.product_id)
                        in {
                            ("1011000101", "discharge_daily_mean"),
                            ("1011000101", "discharge_daily_max"),
                            ("1011000101", "stage_daily_max"),
                            ("Y251002001", "discharge_instantaneous"),
                            ("Y251002001", "stage_instantaneous"),
                            ("01001336", "water_temperature_instantaneous"),
                        }
                        else "unknown"
                    ),
                    "availability_reason": (
                        "Non-empty official source recording"
                        if (station_id, d.product_id)
                        in {
                            ("1011000101", "discharge_daily_mean"),
                            ("1011000101", "discharge_daily_max"),
                            ("1011000101", "stage_daily_max"),
                            ("Y251002001", "discharge_instantaneous"),
                            ("Y251002001", "stage_instantaneous"),
                            ("01001336", "water_temperature_instantaneous"),
                        }
                        else AVAILABILITY_REASON
                    ),
                    "published_record_start_date": None,
                    "published_record_end_date": None,
                    "last_catalogue_check": date(2026, 9, 2)
                    if (station_id, d.product_id)
                    in {
                        ("1011000101", "discharge_daily_mean"),
                        ("1011000101", "discharge_daily_max"),
                        ("1011000101", "stage_daily_max"),
                        ("Y251002001", "discharge_instantaneous"),
                        ("Y251002001", "stage_instantaneous"),
                        ("01001336", "water_temperature_instantaneous"),
                    }
                    else catalogue_date,
                }
            )

    return (
        pl.DataFrame(rows, schema=STATION_PRODUCT_CATALOG_SCHEMA.polars_schema)
        .with_columns(pl.col("availability").cast(AvailabilityDtype))
        .sort("station_id", "product_id")
    )


def build_provider_info(
    catalogue_date: date,
) -> dict[str, object]:
    return {
        "provider_id": PROVIDER_ID,
        "name": PROVIDER_NAME,
        "live_stations": False,
        "live_products": False,
        "live_station_products": False,
        "bulk_observations": (
            "true: 365-day window decomposition with paginated obs_elab, observations_tr, "
            "and temperature/chronique requests; partial failures reported as recoverable issues"
        ),
        "catalogue_version": catalogue_date.isoformat(),
        "license": None,
        "citation": None,
    }


def validate_generated_catalogue(
    provider_info: dict[str, object],
    products: ProductCatalog,
    stations: StationCatalog,
    station_products: StationProductCatalog,
    acquisition_provenance: AcquisitionProvenance,
) -> PackagedCatalogArtifact:
    provider_info_df = pl.DataFrame([provider_info], schema=PROVIDER_INFO_CATALOG_SCHEMA.polars_schema)
    validate_catalogue(provider_info_df, PROVIDER_INFO_CATALOG_SCHEMA, on_issue="raise")
    validate_catalogue(products, PRODUCT_CATALOG_SCHEMA, on_issue="raise")
    validate_catalogue(stations, STATION_CATALOG_SCHEMA, on_issue="raise")
    validate_catalogue(station_products, STATION_PRODUCT_CATALOG_SCHEMA, on_issue="raise")
    return packaged_catalogue_artifact_from_components(
        provider_info,
        products,
        stations,
        station_products,
        acquisition_provenance=acquisition_provenance,
        on_issue="raise",
    )


def write_catalogue(catalogue: GeneratedFrHubeauCatalogue, out_dir: Path | str) -> None:
    output_path = Path(out_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    with (output_path / "provider.json").open("w", encoding="utf-8") as f:
        json.dump(catalogue.public_artifact.provider_info, f, sort_keys=True, separators=(",", ":"))
        f.write("\n")
    catalogue.public_artifact.products.write_parquet(output_path / "products.parquet")
    catalogue.public_artifact.stations.write_parquet(output_path / "stations.parquet")
    catalogue.public_artifact.station_products.write_parquet(output_path / "station_products.parquet")
    (output_path / "provenance.json").write_text(
        catalogue.acquisition_provenance.model_dump_json() + "\n", encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Live fetchers
# ---------------------------------------------------------------------------


def _read_live_stations(base_url: str, query_params: str, label: str) -> dict[str, object]:
    """Fetch all pages from a Hubeau station catalogue endpoint."""
    initial_url = f"{base_url}?{query_params}"
    all_data: list[object] = []
    current_url: str | None = initial_url

    while current_url is not None:
        try:
            with urllib.request.urlopen(current_url, timeout=60) as response:
                if response.status < 200 or response.status >= 300:
                    raise FatalContractError(
                        f"fr_hubeau {label} stations live request failed with HTTP {response.status}: {current_url}"
                    )
                page = json.load(response)
        except OSError as exc:
            raise FatalContractError(f"fr_hubeau {label} stations live request failed: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise FatalContractError(f"fr_hubeau {label} stations live response is not valid JSON: {exc}") from exc

        if not isinstance(page, dict):
            raise FatalContractError(f"fr_hubeau {label} stations live response must be a JSON object")

        data = page.get("data", [])
        if isinstance(data, list):
            all_data.extend(data)

        next_url_raw = page.get("next")
        current_url = next_url_raw if isinstance(next_url_raw, str) and next_url_raw.strip() else None

    return cast("dict[str, object]", {"data": all_data})


def _read_fixture_json(path: Path) -> dict[str, object]:
    try:
        with path.open(encoding="utf-8") as f:
            value = json.load(f)
    except OSError as exc:
        raise FatalContractError(f"Unable to read fr_hubeau fixture: {path}") from exc
    except json.JSONDecodeError as exc:
        raise FatalContractError(f"fr_hubeau fixture is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise FatalContractError("fr_hubeau fixture must contain a JSON object")
    return cast("dict[str, object]", value)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh or build the packaged fr_hubeau catalogue artifacts.")
    parser.add_argument("--hydro-fixture", type=Path, help="Path to a Hubeau referentiel/stations JSON fixture.")
    parser.add_argument(
        "--temp-fixture",
        type=Path,
        help="Path to a Hubeau temperature/station JSON fixture (used with --hydro-fixture).",
    )
    parser.add_argument("--native", type=Path, help="Committed native Parquet input for canonical build.")
    parser.add_argument("--out", type=Path, help="Output directory for provider.json and parquet files.")
    parser.add_argument("--native-out", type=Path, help="Output path for the native Parquet table.")
    parser.add_argument("--hydro-retrieved-at", type=_parse_retrieved_at)
    parser.add_argument("--temperature-retrieved-at", type=_parse_retrieved_at)
    args = parser.parse_args(argv)

    refresh_requested = any(
        value is not None
        for value in (
            args.hydro_fixture,
            args.temp_fixture,
            args.native_out,
            args.hydro_retrieved_at,
            args.temperature_retrieved_at,
        )
    )
    if args.native is not None:
        if refresh_requested:
            parser.error("--native build mode cannot be combined with refresh sources or retrieval instants")
        if args.out is None:
            parser.error("--out is required for canonical build")
        from rivretrieve._internal.providers.fr_hubeau.origins import FRANCE_ORIGIN_DECLARATIONS

        catalogue = build_catalogue(
            read_native_table(
                args.native,
                expected_sha256=NATIVE_TABLE_SHA256,
                expected_byte_size=NATIVE_TABLE_BYTE_SIZE,
            ),
            FRANCE_ORIGIN_DECLARATIONS,
        )
        verify_provenance_recordings(catalogue.acquisition_provenance, Path(__file__).resolve().parents[5])
        write_catalogue(catalogue, args.out)
        return 0

    if args.out is not None:
        parser.error("--native is required for canonical build")
    if (args.hydro_fixture is None) != (args.temp_fixture is None):
        parser.error("--hydro-fixture and --temp-fixture must be supplied together")
    if args.hydro_fixture is None:
        parser.error("--native is required for canonical build")
    if args.native_out is None:
        parser.error("--native-out is required for fixture-native materialization")
    if args.hydro_retrieved_at is None or args.temperature_retrieved_at is None:
        parser.error(
            "--hydro-retrieved-at and --temperature-retrieved-at are required for fixture-native materialization"
        )
    outcome = refresh_native_table_from_fixtures(
        args.hydro_fixture,
        args.temp_fixture,
        hydro_retrieved_at=args.hydro_retrieved_at,
        temperature_retrieved_at=args.temperature_retrieved_at,
    )
    native_table = _raise_on_native_issues(outcome)
    write_native_table(native_table, args.native_out)
    written = read_native_table(args.native_out)
    print(native_table_content_digest(written))
    return 0


def _parse_retrieved_at(value: str) -> RetrievedAt:
    return RetrievedAt(datetime.fromisoformat(value))


def _raise_on_native_issues(outcome: WithIssues[NativeTable]) -> NativeTable:
    errors = tuple(issue for issue in outcome.issues if issue.severity == "error")
    if errors:
        raise FatalContractError(issues=errors)
    return outcome.value


if __name__ == "__main__":
    raise SystemExit(main())
