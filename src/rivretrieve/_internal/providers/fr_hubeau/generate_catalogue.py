"""refresh : HubeauHydrometryStations × RetrievedAt × HubeauTemperatureStations × RetrievedAt → WithIssues[NativeTable]."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import urllib.request
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

import polars as pl

from rivretrieve._internal.catalogues.artifact import packaged_catalogue_artifact_from_components
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
from rivretrieve._internal.providers.fr_hubeau.metadata import (
    FrHubeauProductMetadata,
    FrHubeauStationProductMetadata,
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
    native_unit: str
    conversion_factor: float
    notes: str | None

    @property
    def metadata(self) -> FrHubeauProductMetadata:
        return FrHubeauProductMetadata(
            grandeur_code=self.grandeur_code,
            api_type=self.api_type,
            native_unit=self.native_unit,
            canonical_unit=self.canonical_unit,
            conversion_factor=self.conversion_factor,
            notes=self.notes,
        )


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
        native_unit="l/s",
        conversion_factor=1000.0,
        notes=(
            "Hubeau observations_tr grandeur Q (débit). "
            "Native unit l/s divided by 1000 to convert to m³/s. "
            "Timestamps are full UTC ISO 8601 (date_obs). "
            "Real-time only: Hubeau rejects requests older than ~1 month."
        ),
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
        native_unit="mm",
        conversion_factor=1000.0,
        notes=(
            "Hubeau observations_tr grandeur H (hauteur). "
            "Native unit mm divided by 1000 to convert to m. "
            "Timestamps are full UTC ISO 8601 (date_obs). "
            "Real-time only: Hubeau rejects requests older than ~1 month."
        ),
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
        native_unit="l/s",
        conversion_factor=1000.0,
        notes=(
            "Hubeau obs_elab grandeur QmnJ (débit moyen journalier). "
            "Native unit l/s divided by 1000 to convert to m³/s. "
            "Timestamps are date-only YYYY-MM-DD interpreted as UTC midnight."
        ),
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
        native_unit="l/s",
        conversion_factor=1000.0,
        notes=(
            "Hubeau obs_elab grandeur QIXnJ (débit instantané maximal journalier). "
            "Native unit l/s divided by 1000 to convert to m³/s. "
            "Timestamps are date-only YYYY-MM-DD interpreted as UTC midnight."
        ),
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
        native_unit="mm",
        conversion_factor=1000.0,
        notes=(
            "Hubeau obs_elab grandeur HIXnJ (hauteur instantanée maximale journalière). "
            "Native unit mm divided by 1000 to convert to m. "
            "Timestamps are date-only YYYY-MM-DD interpreted as UTC midnight. "
            "Note: daily mean height (HmnJ) does not exist in Hubeau obs_elab."
        ),
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
        native_unit="degC",
        conversion_factor=1.0,
        notes=(
            "Hubeau temperature/chronique endpoint. "
            "Temperature in °C, no conversion needed. "
            "Timestamps from date_mesure_temp + heure_mesure_temp, interpreted as UTC."
        ),
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


def generate_catalogue_from_fixture(
    hydro_fixture_path: Path | str,
    temp_fixture_path: Path | str,
    *,
    catalogue_date: date | None = None,
) -> GeneratedFrHubeauCatalogue:
    return generate_catalogue(
        _read_fixture_json(Path(hydro_fixture_path)),
        _read_fixture_json(Path(temp_fixture_path)),
        catalogue_date=catalogue_date,
        generator_input="fixture",
    )


def generate_catalogue_from_live(
    *,
    catalogue_date: date | None = None,
) -> GeneratedFrHubeauCatalogue:
    hydro_payload = _read_live_stations(HYDRO_STATIONS_URL, HYDRO_STATIONS_PARAMS, "hydrometric")
    temp_payload = _read_live_stations(TEMP_STATIONS_URL, TEMP_STATIONS_PARAMS, "temperature")
    return generate_catalogue(
        hydro_payload,
        temp_payload,
        catalogue_date=catalogue_date,
        generator_input="live",
    )


def generate_catalogue(
    hydro_payload: dict[str, object],
    temp_payload: dict[str, object],
    *,
    catalogue_date: date | None = None,
    generator_input: str = "fixture",
) -> GeneratedFrHubeauCatalogue:
    effective_date = catalogue_date or date.today()
    products = build_products()
    hydro_stations = build_hydro_stations(hydro_payload, generator_input=generator_input)
    temp_stations = build_temp_stations(temp_payload, generator_input=generator_input)

    # Merge: hydro first, then temp; both sorted by station_id afterwards.
    stations: StationCatalog = pl.concat([hydro_stations, temp_stations]).sort("station_id")

    hydro_ids = hydro_stations["station_id"].to_list()
    temp_ids = temp_stations["station_id"].to_list()
    station_products = build_station_products(
        hydro_station_ids=hydro_ids,
        temp_station_ids=temp_ids,
        catalogue_date=effective_date,
    )

    provider_info = build_provider_info(effective_date, generator_input=generator_input)
    validate_generated_catalogue(provider_info, products, stations, station_products)
    return GeneratedFrHubeauCatalogue(
        provider_info=provider_info,
        products=products,
        stations=stations,
        station_products=station_products,
    )


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
            "derived": False,
            "derivation_method": None,
            "metadata": _metadata_json(d.metadata),
        }
        for d in PRODUCT_DEFINITIONS
    ]
    return pl.DataFrame(rows, schema=PRODUCT_CATALOG_SCHEMA.polars_schema).sort("product_id")


def build_hydro_stations(
    raw_payload: dict[str, object],
    *,
    generator_input: str = "fixture",
) -> StationCatalog:
    rows = list(_iter_hydro_station_rows(raw_payload))
    if not rows:
        raise FatalContractError("fr_hubeau: hydrometric station build returned no rows with valid coordinates")
    if generator_input == "live" and len(rows) < MIN_LIVE_HYDRO_STATIONS:
        raise FatalContractError(
            f"fr_hubeau: live hydrometric catalogue returned only {len(rows)} stations "
            f"(expected ≥ {MIN_LIVE_HYDRO_STATIONS}); possible fetch failure"
        )
    return pl.DataFrame(rows, schema=STATION_CATALOG_SCHEMA.polars_schema).sort("station_id")


def build_temp_stations(
    raw_payload: dict[str, object],
    *,
    generator_input: str = "fixture",
) -> StationCatalog:
    rows = list(_iter_temp_station_rows(raw_payload))
    if generator_input == "live" and len(rows) < MIN_LIVE_TEMP_STATIONS:
        raise FatalContractError(
            f"fr_hubeau: live temperature catalogue returned only {len(rows)} stations "
            f"(expected ≥ {MIN_LIVE_TEMP_STATIONS}); possible fetch failure"
        )
    # Return empty schema-valid DataFrame when fixture has no temp stations.
    if not rows:
        return pl.DataFrame(schema=STATION_CATALOG_SCHEMA.polars_schema)
    return pl.DataFrame(rows, schema=STATION_CATALOG_SCHEMA.polars_schema).sort("station_id")


def build_station_products(
    *,
    hydro_station_ids: list[object],
    temp_station_ids: list[object],
    catalogue_date: date,
) -> StationProductCatalog:
    rows = []

    for station_id in hydro_station_ids:
        if not isinstance(station_id, str):
            raise FatalContractError("station_id must be a string")
        for d in HYDRO_PRODUCT_DEFS:
            metadata = FrHubeauStationProductMetadata(
                station_id=station_id,
                product_id=d.product_id,
                grandeur_code=d.grandeur_code,
                availability_source=AVAILABILITY_SOURCE,
                availability_note=(
                    "Materialised as availability=unknown; "
                    "referentiel/stations does not guarantee observed data for every grandeur."
                ),
            )
            rows.append(
                {
                    "provider_id": PROVIDER_ID,
                    "station_id": station_id,
                    "product_id": d.product_id,
                    "availability": "unknown",
                    "availability_reason": AVAILABILITY_REASON,
                    "start_date": None,
                    "end_date": None,
                    "last_catalogue_check": catalogue_date,
                    "metadata": _metadata_json(metadata),
                }
            )

    for station_id in temp_station_ids:
        if not isinstance(station_id, str):
            raise FatalContractError("temperature station_id must be a string")
        for d in TEMP_PRODUCT_DEFS:
            metadata = FrHubeauStationProductMetadata(
                station_id=station_id,
                product_id=d.product_id,
                grandeur_code=d.grandeur_code,
                availability_source=AVAILABILITY_SOURCE,
                availability_note=(
                    "Materialised as availability=unknown; "
                    "temperature/station does not guarantee observed data continuity."
                ),
            )
            rows.append(
                {
                    "provider_id": PROVIDER_ID,
                    "station_id": station_id,
                    "product_id": d.product_id,
                    "availability": "unknown",
                    "availability_reason": AVAILABILITY_REASON,
                    "start_date": None,
                    "end_date": None,
                    "last_catalogue_check": catalogue_date,
                    "metadata": _metadata_json(metadata),
                }
            )

    return pl.DataFrame(rows, schema=STATION_PRODUCT_CATALOG_SCHEMA.polars_schema).with_columns(
        pl.col("availability").cast(AvailabilityDtype)
    )


def build_provider_info(
    catalogue_date: date,
    *,
    generator_input: str,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "hydro_stations_url": HYDRO_STATIONS_URL,
        "hydro_sites_url": HYDRO_SITES_URL,
        "temp_stations_url": TEMP_STATIONS_URL,
        "obs_elab_url": "https://hubeau.eaufrance.fr/api/v2/hydrometrie/obs_elab",
        "obs_tr_url": "https://hubeau.eaufrance.fr/api/v2/hydrometrie/observations_tr",
        "temperature_url": "https://hubeau.eaufrance.fr/api/v1/temperature/chronique",
        "generator_input": generator_input,
        "timestamp_convention": "obs_elab=date_only_utc_midnight; obs_tr=utc_iso; temperature=utc_iso",
    }
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
        "metadata": json.dumps(metadata, sort_keys=True, separators=(",", ":")),
    }


def validate_generated_catalogue(
    provider_info: dict[str, object],
    products: ProductCatalog,
    stations: StationCatalog,
    station_products: StationProductCatalog,
) -> None:
    provider_info_df = pl.DataFrame([provider_info], schema=PROVIDER_INFO_CATALOG_SCHEMA.polars_schema)
    validate_catalogue(provider_info_df, PROVIDER_INFO_CATALOG_SCHEMA, on_issue="raise")
    validate_catalogue(products, PRODUCT_CATALOG_SCHEMA, on_issue="raise")
    validate_catalogue(stations, STATION_CATALOG_SCHEMA, on_issue="raise")
    validate_catalogue(station_products, STATION_PRODUCT_CATALOG_SCHEMA, on_issue="raise")
    packaged_catalogue_artifact_from_components(
        provider_info,
        products,
        stations,
        station_products,
        on_issue="raise",
    )


def write_catalogue(catalogue: GeneratedFrHubeauCatalogue, out_dir: Path | str) -> None:
    output_path = Path(out_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    with (output_path / "provider.json").open("w", encoding="utf-8") as f:
        json.dump(catalogue.provider_info, f, sort_keys=True, separators=(",", ":"))
        f.write("\n")
    catalogue.products.write_parquet(output_path / "products.parquet")
    catalogue.stations.write_parquet(output_path / "stations.parquet")
    catalogue.station_products.write_parquet(output_path / "station_products.parquet")


# ---------------------------------------------------------------------------
# Station row iterators
# ---------------------------------------------------------------------------


def _iter_hydro_station_rows(
    raw_payload: dict[str, object],
) -> Iterator[dict[str, object]]:
    data_list = raw_payload.get("data", [])
    if not isinstance(data_list, list):
        return

    seen: set[str] = set()
    for row in cast(list[dict[str, object]], data_list):
        if not isinstance(row, dict):
            continue

        station_id = _clean_text(row.get("code_station"))
        if station_id is None:
            continue
        if station_id in seen:
            continue

        lat = _to_float(row.get("latitude_station"))
        lon = _to_float(row.get("longitude_station"))
        if lat is None or lon is None:
            continue

        seen.add(station_id)

        yield {
            "provider_id": PROVIDER_ID,
            "station_id": station_id,
            "latitude": lat,
            "longitude": lon,
            "crs": "unknown",
        }


def _iter_temp_station_rows(raw_payload: dict[str, object]) -> Iterator[dict[str, object]]:
    data_list = raw_payload.get("data", [])
    if not isinstance(data_list, list):
        return

    seen: set[str] = set()
    for row in cast(list[dict[str, object]], data_list):
        if not isinstance(row, dict):
            continue

        station_id = _clean_text(row.get("code_station"))
        if station_id is None:
            continue
        if station_id in seen:
            continue

        # Temperature API uses 'latitude'/'longitude', not '*_station' variants.
        lat = _to_float(row.get("latitude"))
        lon = _to_float(row.get("longitude"))
        if lat is None or lon is None:
            continue

        seen.add(station_id)

        yield {
            "provider_id": PROVIDER_ID,
            "station_id": station_id,
            "latitude": lat,
            "longitude": lon,
            "crs": "unknown",
        }


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


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in ("nan", "none", "null"):
        return None
    return text


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _metadata_json(
    model: FrHubeauProductMetadata | FrHubeauStationProductMetadata,
) -> str:
    return json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the packaged fr_hubeau catalogue artifacts.")
    parser.add_argument("--hydro-fixture", type=Path, help="Path to a Hubeau referentiel/stations JSON fixture.")
    parser.add_argument("--live", action="store_true", help="Fetch live Hubeau station endpoints.")
    parser.add_argument(
        "--temp-fixture",
        type=Path,
        help="Path to a Hubeau temperature/station JSON fixture (used with --hydro-fixture).",
    )
    parser.add_argument("--out", type=Path, help="Output directory for provider.json and parquet files.")
    parser.add_argument("--native-out", type=Path, help="Output path for the native Parquet table.")
    parser.add_argument("--hydro-retrieved-at", type=_parse_retrieved_at)
    parser.add_argument("--temperature-retrieved-at", type=_parse_retrieved_at)
    parser.add_argument("--catalogue-date", type=date.fromisoformat, default=date.today())
    args = parser.parse_args(argv)

    if args.native_out is not None and args.out is not None:
        parser.error("--native-out cannot be combined with canonical --out")
    if args.live and args.native_out is not None:
        parser.error("--live cannot be combined with --native-out")
    if (args.hydro_fixture is None) != (args.temp_fixture is None):
        parser.error("--hydro-fixture and --temp-fixture must be supplied together")
    if args.live and args.hydro_fixture is not None:
        parser.error("--live cannot be combined with fixture input")

    native_instants_requested = args.hydro_retrieved_at is not None or args.temperature_retrieved_at is not None
    if args.native_out is not None:
        if args.hydro_fixture is None:
            parser.error("--hydro-fixture and --temp-fixture must be supplied together")
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

    if native_instants_requested:
        parser.error("--native-out is required for fixture-native materialization")
    if args.out is None:
        parser.error("canonical materialization requires --out")
    if args.live:
        catalogue = generate_catalogue_from_live(catalogue_date=args.catalogue_date)
    else:
        if args.hydro_fixture is None:
            parser.error("canonical materialization requires --live or both fixture paths")
        catalogue = generate_catalogue_from_fixture(
            args.hydro_fixture,
            args.temp_fixture,
            catalogue_date=args.catalogue_date,
        )
    write_catalogue(catalogue, args.out)
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
