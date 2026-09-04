"""NVE catalogue maintenance : StationCapture × RetrievedAt → NativeTable; NativeTable × OriginDeclarations → PackagedCatalogArtifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import IntEnum
from pathlib import Path
from typing import cast

import polars as pl

from rivretrieve._internal.acquisition_provenance import (
    AcquisitionProvenance,
    serialize_acquisition_provenance,
)
from rivretrieve._internal.catalogue_origins import OriginDeclarations, enforce_catalogue_origins
from rivretrieve._internal.catalogues.artifact import (
    PackagedCatalogArtifact,
    packaged_catalogue_artifact_from_components,
)
from rivretrieve._internal.catalogues.native import (
    NativeTable,
    read_native_table,
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
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.record_observations import credential_value
from rivretrieve._internal.transport import (
    AuthenticatedTransport,
    CredentialHeader,
    HttpClient,
    HttpMethod,
    Transport,
    TransportRequest,
)

PROVIDER_ID = ProviderId("no_nve")
PROVIDER_NAME = "NVE HydAPI — Norwegian Water Resources and Energy Directorate"
STATIONS_URL = "https://hydapi.nve.no/api/v1/Stations"
TERMS_URL = "https://hydapi.nve.no/UserDocumentation/"
_CAPTURE_SCHEMA_VERSION = 1
_ENVELOPE_FIELDS = ("currentLink", "apiVersion", "license", "createdAt", "queryTime", "itemCount", "data")
_CANONICALIZATION = (
    "Verify the complete Active=1 all-station and Active=0 active-only envelopes and all nested station, seriesList, and resolutionList members.",
    "Require every active-only station in the all-station response and reject differing overlap or duplicate identities.",
    "Collapse byte-semantically identical overlap, order rows by stationId, retain source field order, and use the earliest containing response retrieval instant.",
)
STATION_FIELDS = (
    "stationId",
    "stationName",
    "latitude",
    "longitude",
    "utmEast_Z33",
    "utmNorth_Z33",
    "masl",
    "riverName",
    "councilNumber",
    "councilName",
    "countyName",
    "drainageBasinKey",
    "hierarchy",
    "lakeArea",
    "lakeName",
    "lakeNo",
    "regineNo",
    "reservoirNo",
    "reservoirName",
    "stationTypeName",
    "stationStatusName",
    "drainageBasinArea",
    "drainageBasinAreaNorway",
    "gradient1085",
    "gradientBasin",
    "gradientRiver",
    "heightMinimum",
    "heightHypso10",
    "heightHypso20",
    "heightHypso30",
    "heightHypso40",
    "heightHypso50",
    "heightHypso60",
    "heightHypso70",
    "heightHypso80",
    "heightHypso90",
    "heightMaximum",
    "lengthKmBasin",
    "lengthKmRiver",
    "percentAgricul",
    "percentBog",
    "percentEffBog",
    "percentEffLake",
    "percentForest",
    "percentGlacier",
    "percentLake",
    "percentMountain",
    "percentUrban",
    "utmZoneGravi",
    "utmEastGravi",
    "utmNorthGravi",
    "utmZoneInlet",
    "utmEastInlet",
    "utmNorthInlet",
    "utmZoneOutlet",
    "utmEastOutlet",
    "utmNorthOutlet",
    "annualRunoff",
    "specificDischarge",
    "regulationArea",
    "areaReservoirs",
    "volumeReservoirs",
    "regulationPartReservoirs",
    "transferAreaIn",
    "transferAreaOut",
    "reservoirAreaIn",
    "reservoirAreaOut",
    "reservoirVolumeIn",
    "reservoirVolumeOut",
    "remainingArea",
    "numberReservoirs",
    "firstYearRegulation",
    "catchmentRegTypeName",
    "owner",
    "qNumberOfYears",
    "qStartYear",
    "qEndYear",
    "qm",
    "q5",
    "q10",
    "q20",
    "q50",
    "hm",
    "h5",
    "h10",
    "h20",
    "h50",
    "culQm",
    "culQ5",
    "culQ10",
    "culQ20",
    "culQ50",
    "culHm",
    "culH5",
    "culH10",
    "culH20",
    "culH50",
    "seriesList",
)
SERIES_FIELDS = ("parameterName", "parameter", "versionNo", "unit", "serieFrom", "serieTo", "resolutionList")
RESOLUTION_FIELDS = ("resTime", "method", "timeOffset", "dataFromTime", "dataToTime")
_STATION_NULLABLE_STRINGS = (
    "stationId",
    "stationName",
    "riverName",
    "councilNumber",
    "councilName",
    "countyName",
    "hierarchy",
    "lakeName",
    "regineNo",
    "reservoirNo",
    "reservoirName",
    "stationTypeName",
    "stationStatusName",
    "catchmentRegTypeName",
    "owner",
)
_STATION_REQUIRED_INTEGERS = ("utmEast_Z33", "utmNorth_Z33", "masl", "drainageBasinKey", "lakeNo")
_STATION_NULLABLE_INTEGERS = (
    "heightMinimum",
    "heightHypso10",
    "heightHypso20",
    "heightHypso30",
    "heightHypso40",
    "heightHypso50",
    "heightHypso60",
    "heightHypso70",
    "heightHypso80",
    "heightHypso90",
    "heightMaximum",
    "utmZoneGravi",
    "utmEastGravi",
    "utmNorthGravi",
    "utmZoneInlet",
    "utmEastInlet",
    "utmNorthInlet",
    "utmZoneOutlet",
    "utmEastOutlet",
    "utmNorthOutlet",
    "numberReservoirs",
    "firstYearRegulation",
    "qNumberOfYears",
    "qStartYear",
    "qEndYear",
)
_STATION_REQUIRED_NUMBERS = ("latitude", "longitude", "lakeArea")
_STATION_NULLABLE_NUMBERS = tuple(
    field
    for field in STATION_FIELDS
    if field
    not in {
        *_STATION_NULLABLE_STRINGS,
        *_STATION_REQUIRED_INTEGERS,
        *_STATION_NULLABLE_INTEGERS,
        *_STATION_REQUIRED_NUMBERS,
        "seriesList",
    }
)

_LICENSE = "The data provided by the API is licensed under the Norwegian License for Open Government Data (NLOD) which is compatible with CC Navngivelse 3.0 Norge (CC BY 3.0)."
_CITATION = "When using data from this service, if possible, please refer to this service as origin of data."


class StationActivityFilter(IntEnum):
    """NVE Stations query modes: Active=1 returns all stations; Active=0 returns only active stations."""

    ALL = 1
    ACTIVE_ONLY = 0

    @property
    def request_url(self) -> str:
        return f"{STATIONS_URL}?Active={int(self)}"


@dataclass(frozen=True, slots=True)
class CapturedStationResponse:
    activity: StationActivityFilter
    repository_path: str
    requested_url: str
    retrieved_at: datetime
    byte_size: int
    sha256: str
    response_row_count: int
    accepted_row_count: int
    distinct_station_count: int


@dataclass(frozen=True, slots=True)
class NativeTableAttestation:
    repository_path: str
    byte_size: int
    sha256: str
    semantic_sha256: str


@dataclass(frozen=True, slots=True)
class StationCatalogueCapture:
    responses: tuple[CapturedStationResponse, CapturedStationResponse]
    overlap_station_count: int
    distinct_station_count: int
    canonicalization: tuple[str, ...]
    native_table: NativeTableAttestation


@dataclass(frozen=True, slots=True)
class ProductDefinition:
    product_id: str
    observed_property: str
    frequency: str
    statistic: str
    period_type: str
    period_anchor: str
    canonical_unit: str
    parameter_id: int
    resolution_time: int


PRODUCT_DEFINITIONS = (
    ProductDefinition("stage_daily_mean", "stage", "daily", "mean", "interval", "provider_defined", "m", 1000, 1440),
    ProductDefinition("stage_hourly_mean", "stage", "hourly", "mean", "interval", "provider_defined", "m", 1000, 60),
    ProductDefinition("stage_instantaneous", "stage", "irregular", "instantaneous", "instant", "instant", "m", 1000, 0),
    ProductDefinition(
        "discharge_daily_mean", "discharge", "daily", "mean", "interval", "provider_defined", "m3/s", 1001, 1440
    ),
    ProductDefinition(
        "discharge_hourly_mean", "discharge", "hourly", "mean", "interval", "provider_defined", "m3/s", 1001, 60
    ),
    ProductDefinition(
        "discharge_instantaneous", "discharge", "irregular", "instantaneous", "instant", "instant", "m3/s", 1001, 0
    ),
    ProductDefinition(
        "water_temperature_daily_mean",
        "water_temperature",
        "daily",
        "mean",
        "interval",
        "provider_defined",
        "degC",
        1003,
        1440,
    ),
    ProductDefinition(
        "water_temperature_hourly_mean",
        "water_temperature",
        "hourly",
        "mean",
        "interval",
        "provider_defined",
        "degC",
        1003,
        60,
    ),
    ProductDefinition(
        "water_temperature_instantaneous",
        "water_temperature",
        "irregular",
        "instantaneous",
        "instant",
        "instant",
        "degC",
        1003,
        0,
    ),
)
EXPECTED_PRODUCT_IDS = frozenset(item.product_id for item in PRODUCT_DEFINITIONS)
_PARAM_RES_TO_PRODUCT = {(item.parameter_id, item.resolution_time): item.product_id for item in PRODUCT_DEFINITIONS}


@dataclass(frozen=True, slots=True)
class GeneratedNoNveCatalogue:
    provider_info: dict[str, object]
    products: ProductCatalog
    stations: StationCatalog
    station_products: StationProductCatalog
    acquisition_provenance: AcquisitionProvenance
    public_artifact: PackagedCatalogArtifact


def read_capture_record(path: Path | str) -> StationCatalogueCapture:
    """Parse the closed, secret-free station-capture attestation."""
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FatalContractError(f"no_nve station capture record cannot be read: {path}") from exc
    expected = {
        "schema_version",
        "responses",
        "overlap_station_count",
        "distinct_station_count",
        "canonicalization",
        "native_table",
    }
    if (
        not isinstance(document, dict)
        or set(document) != expected
        or document["schema_version"] != _CAPTURE_SCHEMA_VERSION
    ):
        raise FatalContractError("no_nve station capture record has an unexpected shape")
    raw_responses = document["responses"]
    if not isinstance(raw_responses, list) or len(raw_responses) != 2:
        raise FatalContractError("no_nve station capture record must declare exactly two responses")
    responses = tuple(_parse_recorded_response(item) for item in raw_responses)
    if tuple(item.activity for item in responses) != (StationActivityFilter.ALL, StationActivityFilter.ACTIVE_ONLY):
        raise FatalContractError(
            "no_nve station capture record must declare all-station Active=1 then active-only Active=0"
        )
    native = document["native_table"]
    if not isinstance(native, dict) or set(native) != {"repository_path", "byte_size", "sha256", "semantic_sha256"}:
        raise FatalContractError("no_nve station capture native-table identity has an unexpected shape")
    canonicalization = document["canonicalization"]
    if not isinstance(canonicalization, list) or tuple(canonicalization) != _CANONICALIZATION:
        raise FatalContractError("no_nve station capture canonicalization rules are invalid")
    return StationCatalogueCapture(
        responses=cast("tuple[CapturedStationResponse, CapturedStationResponse]", responses),
        overlap_station_count=_nonnegative_int(document["overlap_station_count"], "overlap_station_count"),
        distinct_station_count=_positive_int(document["distinct_station_count"], "distinct_station_count"),
        canonicalization=tuple(canonicalization),
        native_table=NativeTableAttestation(
            repository_path=_relative_path(native["repository_path"]),
            byte_size=_positive_int(native["byte_size"], "native table byte_size"),
            sha256=_sha256(native["sha256"]),
            semantic_sha256=_sha256(native["semantic_sha256"]),
        ),
    )


def _parse_recorded_response(value: object) -> CapturedStationResponse:
    expected = {
        "active",
        "repository_path",
        "requested_url",
        "retrieved_at",
        "byte_size",
        "sha256",
        "response_row_count",
        "accepted_row_count",
        "distinct_station_count",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise FatalContractError("no_nve station capture response identity has an unexpected shape")
    mapping = cast("dict[str, object]", value)
    active_value = mapping["active"]
    instant_value = mapping["retrieved_at"]
    if type(active_value) is not int or not isinstance(instant_value, str):
        raise FatalContractError("no_nve station capture response has invalid activity or retrieval instant")
    try:
        activity = StationActivityFilter(active_value)
        retrieved_at = datetime.fromisoformat(instant_value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FatalContractError("no_nve station capture response has invalid activity or retrieval instant") from exc
    offset = retrieved_at.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise FatalContractError("no_nve station capture retrieval instant must be UTC")
    requested_url = mapping["requested_url"]
    if not isinstance(requested_url, str) or requested_url != activity.request_url:
        raise FatalContractError("no_nve station capture request URL is not the exact Stations Active request")
    return CapturedStationResponse(
        activity=activity,
        repository_path=_relative_path(mapping["repository_path"]),
        requested_url=requested_url,
        retrieved_at=retrieved_at,
        byte_size=_positive_int(mapping["byte_size"], "response byte_size"),
        sha256=_sha256(mapping["sha256"]),
        response_row_count=_nonnegative_int(mapping["response_row_count"], "response_row_count"),
        accepted_row_count=_nonnegative_int(mapping["accepted_row_count"], "accepted_row_count"),
        distinct_station_count=_nonnegative_int(mapping["distinct_station_count"], "distinct_station_count"),
    )


def materialize_captured_native_table(capture: StationCatalogueCapture, repository_root: Path | str) -> NativeTable:
    """Verify both complete responses and deterministically materialize their exact station union."""
    root = Path(repository_root)
    response_rows: dict[StationActivityFilter, list[dict[str, object]]] = {}
    for response in capture.responses:
        try:
            body = (root / response.repository_path).read_bytes()
        except OSError as exc:
            raise FatalContractError(f"no_nve captured response cannot be read: {response.repository_path}") from exc
        if len(body) != response.byte_size or hashlib.sha256(body).hexdigest() != response.sha256:
            raise FatalContractError(f"no_nve captured response identity mismatch: {response.repository_path}")
        rows = _parse_station_response(body, response.activity)
        ids = [cast("str", row["stationId"]) for row in rows]
        if (len(rows), len(rows), len(set(ids))) != (
            response.response_row_count,
            response.accepted_row_count,
            response.distinct_station_count,
        ):
            raise FatalContractError(f"no_nve captured response counts mismatch: {response.repository_path}")
        response_rows[response.activity] = rows
    active_only_by_id = {cast("str", row["stationId"]): row for row in response_rows[StationActivityFilter.ACTIVE_ONLY]}
    all_by_id = {cast("str", row["stationId"]): row for row in response_rows[StationActivityFilter.ALL]}
    overlap = set(active_only_by_id) & set(all_by_id)
    if any(row["stationStatusName"] != "Aktiv" for row in active_only_by_id.values()):
        raise FatalContractError("no_nve Active=0 response contains a station not marked Aktiv")
    if overlap != set(active_only_by_id) or not (set(all_by_id) - set(active_only_by_id)):
        raise FatalContractError("no_nve Active=0 active-only response is not a strict subset of Active=1 all stations")
    if len(overlap) != capture.overlap_station_count:
        raise FatalContractError("no_nve captured response overlap count mismatch")
    for station_id in overlap:
        if active_only_by_id[station_id] != all_by_id[station_id]:
            raise FatalContractError(
                f"no_nve station {station_id} differs between all-station and active-only responses"
            )
    union = dict(active_only_by_id)
    union.update(all_by_id)
    if len(union) != capture.distinct_station_count:
        raise FatalContractError("no_nve captured response distinct-station count mismatch")
    retrieved_at_by_activity = {response.activity: response.retrieved_at for response in capture.responses}
    source_rows = []
    for station_id in sorted(union):
        row = dict(union[station_id])
        containing_instants = [
            retrieved_at_by_activity[activity]
            for activity, members in (
                (StationActivityFilter.ALL, all_by_id),
                (StationActivityFilter.ACTIVE_ONLY, active_only_by_id),
            )
            if station_id in members
        ]
        instant = min(containing_instants)
        row["retrieved_at"] = instant
        source_rows.append(row)
    try:
        frame = pl.from_dicts(source_rows, infer_schema_length=None, strict=True)
        frame = frame.select(*STATION_FIELDS, "retrieved_at")
        frame = frame.with_columns(pl.col("retrieved_at").cast(pl.Datetime("us", "UTC")))
    except pl.exceptions.PolarsError as exc:
        raise FatalContractError("no_nve captured station rows cannot form one native table") from exc
    return NativeTable(frame)


def _parse_station_response(body: bytes, activity: StationActivityFilter) -> list[dict[str, object]]:
    try:
        document = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FatalContractError(f"no_nve Active={int(activity)} response is not valid UTF-8 JSON") from exc
    if not isinstance(document, dict) or tuple(document) != _ENVELOPE_FIELDS:
        raise FatalContractError(f"no_nve Active={int(activity)} response envelope has an unexpected shape")
    if document["currentLink"] != activity.request_url or document["apiVersion"] != "1.0":
        raise FatalContractError(f"no_nve Active={int(activity)} response does not attest the exact request")
    if any(not isinstance(document[name], str) or not document[name] for name in ("license", "createdAt", "queryTime")):
        raise FatalContractError(f"no_nve Active={int(activity)} response metadata has invalid types")
    data = document["data"]
    if type(document["itemCount"]) is not int or not isinstance(data, list) or document["itemCount"] != len(data):
        raise FatalContractError(f"no_nve Active={int(activity)} response itemCount does not match data")
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for index, item in enumerate(data):
        if not isinstance(item, dict) or tuple(item) != STATION_FIELDS:
            raise FatalContractError(f"no_nve Active={int(activity)} station row {index} has an unexpected shape")
        row = cast("dict[str, object]", item)
        station_id = row["stationId"]
        if not isinstance(station_id, str) or not station_id.strip():
            raise FatalContractError(f"no_nve Active={int(activity)} station row {index} has an invalid stationId")
        if station_id in seen:
            raise FatalContractError(f"no_nve Active={int(activity)} response duplicates station {station_id}")
        _validate_station_scalar_types(station_id, row)
        _validate_series_list(station_id, row["seriesList"])
        _validate_json_value(row, f"station {station_id}")
        seen.add(station_id)
        rows.append(row)
    return rows


def _validate_station_scalar_types(station_id: str, row: Mapping[str, object]) -> None:
    invalid_strings = [
        name for name in _STATION_NULLABLE_STRINGS if row[name] is not None and not isinstance(row[name], str)
    ]
    invalid_integers = [name for name in _STATION_REQUIRED_INTEGERS if type(row[name]) is not int] + [
        name for name in _STATION_NULLABLE_INTEGERS if row[name] is not None and type(row[name]) is not int
    ]
    invalid_numbers = [name for name in _STATION_REQUIRED_NUMBERS if type(row[name]) not in (int, float)] + [
        name for name in _STATION_NULLABLE_NUMBERS if row[name] is not None and type(row[name]) not in (int, float)
    ]
    invalid = sorted((*invalid_strings, *invalid_integers, *invalid_numbers))
    if invalid:
        raise FatalContractError(f"no_nve station {station_id} has invalid source field types: {', '.join(invalid)}")
    latitude = cast("float | int", row["latitude"])
    longitude = cast("float | int", row["longitude"])
    if (
        not math.isfinite(latitude)
        or not -90 <= latitude <= 90
        or not math.isfinite(longitude)
        or not -180 <= longitude <= 180
    ):
        raise FatalContractError(f"no_nve station {station_id} has invalid source coordinates")


def _validate_series_list(station_id: str, value: object) -> None:
    if not isinstance(value, list):
        raise FatalContractError(f"no_nve station {station_id} seriesList must be a complete list")
    seen_series: set[tuple[int, int]] = set()
    for series_index, item in enumerate(value):
        if not isinstance(item, dict) or tuple(item) != SERIES_FIELDS:
            raise FatalContractError(
                f"no_nve station {station_id} seriesList item {series_index} has an unexpected shape"
            )
        series = cast("dict[str, object]", item)
        if (
            any(
                series[name] is not None and not isinstance(series[name], str)
                for name in ("parameterName", "unit", "serieFrom", "serieTo")
            )
            or type(series["parameter"]) is not int
            or type(series["versionNo"]) is not int
        ):
            raise FatalContractError(
                f"no_nve station {station_id} seriesList item {series_index} has invalid source types"
            )
        series_identity = (series["parameter"], series["versionNo"])
        if series_identity in seen_series:
            raise FatalContractError(f"no_nve station {station_id} has a duplicate series member")
        seen_series.add(series_identity)
        resolutions = series["resolutionList"]
        if not isinstance(resolutions, list):
            raise FatalContractError(
                f"no_nve station {station_id} seriesList item {series_index} resolutionList must be a list"
            )
        seen: set[tuple[int, str | None, int]] = set()
        for resolution_index, resolution in enumerate(resolutions):
            if not isinstance(resolution, dict) or tuple(resolution) != RESOLUTION_FIELDS:
                raise FatalContractError(
                    f"no_nve station {station_id} resolutionList item {resolution_index} has an unexpected shape"
                )
            resolution_row = cast("dict[str, object]", resolution)
            if (
                any(
                    resolution_row[name] is not None and not isinstance(resolution_row[name], str)
                    for name in ("method", "dataFromTime", "dataToTime")
                )
                or type(resolution_row["resTime"]) is not int
                or type(resolution_row["timeOffset"]) is not int
            ):
                raise FatalContractError(
                    f"no_nve station {station_id} resolutionList item {resolution_index} has invalid source types"
                )
            identity = (
                resolution_row["resTime"],
                cast("str | None", resolution_row["method"]),
                resolution_row["timeOffset"],
            )
            if identity in seen:
                raise FatalContractError(f"no_nve station {station_id} has a duplicate resolution member")
            seen.add(identity)


def _validate_json_value(value: object, location: str) -> None:
    if value is None or type(value) in (str, int, float, bool):
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_value(item, location)
        return
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        for item in value.values():
            _validate_json_value(item, location)
        return
    raise FatalContractError(f"no_nve {location} contains a non-JSON source value")


def native_table_semantic_digest(table: NativeTable) -> str:
    """Hash the exact ordered semantic frame, independent of Parquet encoding."""
    payload = {
        "columns": table.data.columns,
        "rows": [[_canonical_value(value) for value in row] for row in table.data.iter_rows()],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    return hashlib.sha256(canonical).hexdigest()


def _canonical_value(value: object) -> object:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, list | tuple):
        return [_canonical_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _canonical_value(item) for key, item in value.items()}
    return value


def build_catalogue(native_table: NativeTable, origins: OriginDeclarations) -> GeneratedNoNveCatalogue:
    """Build the canonical catalogue without network access."""
    _validate_native_table(native_table)
    products = build_products()
    stations = build_stations(native_table)
    enforce_catalogue_origins(PROVIDER_ID, origins, native_table, stations)
    station_products = build_station_products(native_table)
    maximum = native_table.data["retrieved_at"].max()
    if not isinstance(maximum, datetime):
        raise FatalContractError("no_nve native table has no retrieval instant")
    provider_info = build_provider_info(maximum.date())
    from rivretrieve._internal.providers.no_nve.origins import build_acquisition_provenance

    provenance = build_acquisition_provenance()
    artifact = validate_generated_catalogue(provider_info, products, stations, station_products, provenance)
    return GeneratedNoNveCatalogue(provider_info, products, stations, station_products, provenance, artifact)


def _validate_native_table(table: NativeTable) -> None:
    if table.data.is_empty():
        raise FatalContractError("no_nve native table must not be empty")
    if tuple(table.data.columns) != (*STATION_FIELDS, "retrieved_at"):
        raise FatalContractError("no_nve native table has an unexpected source shape")
    seen: set[str] = set()
    previous: str | None = None
    for index, row in enumerate(table.data.iter_rows(named=True)):
        station_id = row["stationId"]
        if not isinstance(station_id, str) or not station_id.strip():
            raise FatalContractError(f"no_nve native row {index} has invalid stationId")
        if station_id in seen or (previous is not None and station_id < previous):
            raise FatalContractError("no_nve native table station identities must be unique and sorted")
        _validate_station_scalar_types(station_id, row)
        _validate_series_list(station_id, row["seriesList"])
        seen.add(station_id)
        previous = station_id


def build_products() -> ProductCatalog:
    return pl.DataFrame(
        [
            {
                "provider_id": PROVIDER_ID,
                "product_id": item.product_id,
                "observed_property": item.observed_property,
                "frequency": item.frequency,
                "statistic": item.statistic,
                "period_type": item.period_type,
                "period_anchor": item.period_anchor,
                "unit": item.canonical_unit,
                "native_id": f"{item.parameter_id}:{item.resolution_time}",
            }
            for item in PRODUCT_DEFINITIONS
        ],
        schema=PRODUCT_CATALOG_SCHEMA.polars_schema,
    ).sort("product_id")


def build_stations(native_table: NativeTable) -> StationCatalog:
    try:
        return native_table.data.select(
            pl.lit(PROVIDER_ID).cast(pl.String).alias("provider_id"),
            pl.col("stationId").cast(pl.String, strict=True).alias("station_id"),
            pl.col("latitude").cast(pl.Float64, strict=True),
            pl.col("longitude").cast(pl.Float64, strict=True),
            pl.lit("unknown").cast(pl.String).alias("crs"),
        ).sort("station_id")
    except pl.exceptions.PolarsError as exc:
        raise FatalContractError("no_nve native station identity or coordinates are invalid") from exc


def _available_pairs(station_id: str, series_list: object) -> set[tuple[int, int]]:
    _validate_series_list(station_id, series_list)
    result: set[tuple[int, int]] = set()
    for series in cast("list[dict[str, object]]", series_list):
        parameter = cast("int", series["parameter"])
        for resolution in cast("list[dict[str, object]]", series["resolutionList"]):
            result.add((parameter, cast("int", resolution["resTime"])))
    return result


def build_station_products(native_table: NativeTable) -> StationProductCatalog:
    rows: list[dict[str, object]] = []
    for station_id, series_list, retrieved_at in native_table.data.select(
        "stationId", "seriesList", "retrieved_at"
    ).iter_rows():
        if not isinstance(station_id, str) or not isinstance(retrieved_at, datetime):
            raise FatalContractError("no_nve native station-product inputs have invalid types")
        available_pairs = _available_pairs(station_id, series_list)
        for item in PRODUCT_DEFINITIONS:
            pair = (item.parameter_id, item.resolution_time)
            available = pair in available_pairs
            rows.append(
                {
                    "provider_id": PROVIDER_ID,
                    "station_id": station_id,
                    "product_id": item.product_id,
                    "availability": "available" if available else "unavailable",
                    "availability_reason": (
                        f"NVE seriesList contains parameter {item.parameter_id}, resTime {item.resolution_time}"
                        if available
                        else f"Complete NVE seriesList does not contain parameter {item.parameter_id}, resTime {item.resolution_time}"
                    ),
                    "published_record_start_date": None,
                    "published_record_end_date": None,
                    "last_catalogue_check": retrieved_at.date(),
                }
            )
    return (
        pl.DataFrame(rows, schema=STATION_PRODUCT_CATALOG_SCHEMA.polars_schema)
        .with_columns(pl.col("availability").cast(AvailabilityDtype))
        .sort("station_id", "product_id")
    )


def build_provider_info(catalogue_date: date) -> dict[str, object]:
    return {
        "provider_id": PROVIDER_ID,
        "name": PROVIDER_NAME,
        "live_stations": False,
        "live_products": False,
        "live_station_products": False,
        "bulk_observations": "true: credentialed NVE HydAPI LiveStages observation retrieval",
        "catalogue_version": catalogue_date.isoformat(),
        "license": _LICENSE,
        "citation": _CITATION,
    }


def validate_generated_catalogue(
    provider_info: dict[str, object],
    products: ProductCatalog,
    stations: StationCatalog,
    station_products: StationProductCatalog,
    provenance: AcquisitionProvenance,
) -> PackagedCatalogArtifact:
    validate_catalogue(
        pl.DataFrame([provider_info], schema=PROVIDER_INFO_CATALOG_SCHEMA.polars_schema),
        PROVIDER_INFO_CATALOG_SCHEMA,
        on_issue="raise",
    )
    validate_catalogue(products, PRODUCT_CATALOG_SCHEMA, on_issue="raise")
    validate_catalogue(stations, STATION_CATALOG_SCHEMA, on_issue="raise")
    validate_catalogue(station_products, STATION_PRODUCT_CATALOG_SCHEMA, on_issue="raise")
    return packaged_catalogue_artifact_from_components(
        provider_info, products, stations, station_products, acquisition_provenance=provenance, on_issue="raise"
    )


def write_catalogue(catalogue: GeneratedNoNveCatalogue, out_dir: Path | str) -> None:
    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "provider.json").write_text(
        json.dumps(catalogue.public_artifact.provider_info, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    catalogue.public_artifact.products.write_parquet(output / "products.parquet")
    catalogue.public_artifact.stations.write_parquet(output / "stations.parquet")
    catalogue.public_artifact.station_products.write_parquet(output / "station_products.parquet")
    (output / "provenance.json").write_text(
        serialize_acquisition_provenance(catalogue.acquisition_provenance) + "\n", encoding="utf-8"
    )


def capture_station_catalogue(
    transport: Transport,
    response_dir: Path | str,
    response_repository_directory: str,
) -> tuple[tuple[CapturedStationResponse, CapturedStationResponse], dict[StationActivityFilter, bytes]]:
    """Issue the complete two-request NVE station campaign through a scoped transport."""
    output = Path(response_dir)
    relative_directory = _relative_path(response_repository_directory)
    captured: list[CapturedStationResponse] = []
    bodies: dict[StationActivityFilter, bytes] = {}
    for activity in (StationActivityFilter.ALL, StationActivityFilter.ACTIVE_ONLY):
        response = transport.send(
            TransportRequest(HttpMethod.GET, STATIONS_URL, {"Active": int(activity)}, {"Accept": "application/json"})
        )
        if response.status_code != 200:
            raise FatalContractError(f"no_nve Stations Active={int(activity)} returned HTTP {response.status_code}")
        if response.content_type != "application/json; charset=utf-8":
            raise FatalContractError(f"no_nve Stations Active={int(activity)} returned unexpected content type")
        if response.url != STATIONS_URL or dict(response.request_parameters) != {"Active": int(activity)}:
            raise FatalContractError("no_nve station capture transport did not execute the exact request")
        if response.applied_credential_header_names != ("X-API-Key",):
            raise FatalContractError("no_nve station capture did not apply the declared credential header")
        rows = _parse_station_response(response.content, activity)
        filename = f"no_nve_stations_active_{int(activity)}.json"
        bodies[activity] = response.content
        captured.append(
            CapturedStationResponse(
                activity=activity,
                repository_path=f"{relative_directory}/{filename}",
                requested_url=activity.request_url,
                retrieved_at=response.retrieved_at,
                byte_size=len(response.content),
                sha256=hashlib.sha256(response.content).hexdigest(),
                response_row_count=len(rows),
                accepted_row_count=len(rows),
                distinct_station_count=len({cast("str", row["stationId"]) for row in rows}),
            )
        )
    output.mkdir(parents=True, exist_ok=True)
    for activity, body in bodies.items():
        (output / f"no_nve_stations_active_{int(activity)}.json").write_bytes(body)
    return cast("tuple[CapturedStationResponse, CapturedStationResponse]", tuple(captured)), bodies


def write_capture_record(capture: StationCatalogueCapture, path: Path | str) -> None:
    document = {
        "schema_version": _CAPTURE_SCHEMA_VERSION,
        "responses": [
            {
                "active": int(item.activity),
                "repository_path": item.repository_path,
                "requested_url": item.requested_url,
                "retrieved_at": item.retrieved_at.astimezone(UTC)
                .isoformat(timespec="microseconds")
                .replace("+00:00", "Z"),
                "byte_size": item.byte_size,
                "sha256": item.sha256,
                "response_row_count": item.response_row_count,
                "accepted_row_count": item.accepted_row_count,
                "distinct_station_count": item.distinct_station_count,
            }
            for item in capture.responses
        ],
        "overlap_station_count": capture.overlap_station_count,
        "distinct_station_count": capture.distinct_station_count,
        "canonicalization": list(capture.canonicalization),
        "native_table": {
            "repository_path": capture.native_table.repository_path,
            "byte_size": capture.native_table.byte_size,
            "sha256": capture.native_table.sha256,
            "semantic_sha256": capture.native_table.semantic_sha256,
        },
    }
    Path(path).write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _relative_path(value: object) -> str:
    if not isinstance(value, str) or not value or Path(value).is_absolute() or ".." in Path(value).parts:
        raise FatalContractError("no_nve capture repository path must be relative")
    return value


def _sha256(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise FatalContractError("no_nve capture SHA-256 is invalid")
    return value


def _nonnegative_int(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise FatalContractError(f"no_nve capture {name} must be a nonnegative integer")
    return value


def _positive_int(value: object, name: str) -> int:
    result = _nonnegative_int(value, name)
    if result == 0:
        raise FatalContractError(f"no_nve capture {name} must be positive")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Capture, materialize, or build the NVE station catalogue.", allow_abbrev=False
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--capture-responses", type=Path, metavar="DIR")
    mode.add_argument("--materialize-record", type=Path, metavar="JSON")
    mode.add_argument("--native", type=Path, metavar="PARQUET")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--capture-record-out", type=Path)
    parser.add_argument("--native-out", type=Path)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    if args.capture_responses is not None:
        if args.env_file is None or args.capture_record_out is None or args.native_out is None or args.out is not None:
            parser.error(
                "--capture-responses requires --env-file, --capture-record-out, and --native-out; it cannot use --out"
            )
        secret = credential_value("NVE_API_KEY", os.environ, args.env_file)
        transport = AuthenticatedTransport(
            HttpClient(), (CredentialHeader("X-API-Key", secret, ("https://hydapi.nve.no",)),)
        )
        try:
            repository_root = args.repository_root.resolve()
            response_repository_directory = args.capture_responses.resolve().relative_to(repository_root).as_posix()
            native_repository_path = args.native_out.resolve().relative_to(repository_root).as_posix()
        except ValueError as exc:
            raise FatalContractError(
                "no_nve capture response and native paths must be inside the repository root"
            ) from exc
        responses, bodies = capture_station_catalogue(
            transport,
            args.capture_responses,
            response_repository_directory,
        )
        placeholder_native_identity = NativeTableAttestation("pending", 1, "0" * 64, "0" * 64)
        active_only_rows = _parse_station_response(
            bodies[StationActivityFilter.ACTIVE_ONLY], StationActivityFilter.ACTIVE_ONLY
        )
        all_rows = _parse_station_response(bodies[StationActivityFilter.ALL], StationActivityFilter.ALL)
        active_only_ids = {cast("str", row["stationId"]) for row in active_only_rows}
        all_ids = {cast("str", row["stationId"]) for row in all_rows}
        temporary = StationCatalogueCapture(
            responses=responses,
            overlap_station_count=len(active_only_ids & all_ids),
            distinct_station_count=len(active_only_ids | all_ids),
            canonicalization=_CANONICALIZATION,
            native_table=placeholder_native_identity,
        )
        # Materialize from the just-written, digest-bound responses through the same offline path.
        table = materialize_captured_native_table(temporary, args.repository_root)
        write_native_table(table, args.native_out)
        native_bytes = args.native_out.read_bytes()
        capture = StationCatalogueCapture(
            responses=responses,
            overlap_station_count=temporary.overlap_station_count,
            distinct_station_count=temporary.distinct_station_count,
            canonicalization=temporary.canonicalization,
            native_table=NativeTableAttestation(
                repository_path=native_repository_path,
                byte_size=len(native_bytes),
                sha256=hashlib.sha256(native_bytes).hexdigest(),
                semantic_sha256=native_table_semantic_digest(table),
            ),
        )
        write_capture_record(capture, args.capture_record_out)
        print(
            f"no_nve station capture: Active=1 {responses[0].response_row_count} rows/{responses[0].byte_size} bytes/{responses[0].sha256}; Active=0 {responses[1].response_row_count} rows/{responses[1].byte_size} bytes/{responses[1].sha256}; overlap {capture.overlap_station_count}; distinct {capture.distinct_station_count}; native {capture.native_table.byte_size} bytes/{capture.native_table.sha256}; semantic {capture.native_table.semantic_sha256}"
        )
        return 0
    if args.materialize_record is not None:
        if (
            args.native_out is None
            or args.out is not None
            or args.env_file is not None
            or args.capture_record_out is not None
        ):
            parser.error("--materialize-record requires --native-out and cannot use capture or build options")
        capture = read_capture_record(args.materialize_record)
        table = materialize_captured_native_table(capture, args.repository_root)
        if native_table_semantic_digest(table) != capture.native_table.semantic_sha256:
            raise FatalContractError("no_nve materialized native semantic digest mismatch")
        candidate = args.native_out.with_name(f".{args.native_out.name}.candidate")
        write_native_table(table, candidate)
        candidate_bytes = candidate.read_bytes()
        if (
            len(candidate_bytes) != capture.native_table.byte_size
            or hashlib.sha256(candidate_bytes).hexdigest() != capture.native_table.sha256
        ):
            candidate.unlink()
            raise FatalContractError("no_nve materialized native raw identity mismatch")
        candidate.replace(args.native_out)
        return 0
    if args.native is not None:
        if (
            args.out is None
            or args.native_out is not None
            or args.capture_record_out is not None
            or args.env_file is not None
        ):
            parser.error("--native requires --out and cannot use capture options")
        from rivretrieve._internal.providers.no_nve.origins import (
            NATIVE_TABLE_BYTE_SIZE,
            NATIVE_TABLE_SHA256,
            STATION_CATALOGUE_ORIGINS,
        )

        table = read_native_table(
            args.native, expected_sha256=NATIVE_TABLE_SHA256, expected_byte_size=NATIVE_TABLE_BYTE_SIZE
        )
        write_catalogue(build_catalogue(table, STATION_CATALOGUE_ORIGINS), args.out)
        return 0
    raise AssertionError("unreachable catalogue mode")


if __name__ == "__main__":
    raise SystemExit(main())
