"""refresh : HubeauHydrometryStations × RetrievedAt × HubeauTemperatureStations × RetrievedAt → WithIssues[NativeTable]; build : NativeTable × FranceOriginDeclarations × FranceAvailability → GeneratedFrHubeauCatalogue (pure)."""

from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Literal, Never, cast
from urllib.parse import parse_qsl, urlsplit  # noqa: TID251 -- structural parsing only

import polars as pl
from pydantic import BaseModel, ConfigDict

from rivretrieve._internal.acquisition_provenance import (
    AcquisitionProvenance,
    AcquisitionRecord,
    CatalogueBuildInputs,
    EvidenceReference,
    MaterialIdentity,
    NativeTableIdentity,
    verify_provenance_recordings,
)
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
from rivretrieve._internal.catalogues.products import product_row
from rivretrieve._internal.catalogues.schemas import (
    PRODUCT_CATALOG_SCHEMA,
    PROVIDER_INFO_CATALOG_SCHEMA,
    STATION_CATALOG_SCHEMA,
    STATION_PRODUCT_CATALOG_SCHEMA,
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
    NATIVE_TABLE_SEMANTIC_SHA256,
    NATIVE_TABLE_SHA256,
    Projection31BoundsError,
    Projection31PreconditionError,
    build_acquisition_provenance,
    hydrometry_coordinates,
)


class NativeInventoryCapture(BaseModel):
    """Resolved identities of the two source-owned station acquisitions."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    native_table: NativeTableIdentity
    hydrometry: AcquisitionRecord
    temperature: AcquisitionRecord
    evidence: tuple[EvidenceReference, ...]


Product = Literal[
    "discharge_instantaneous",
    "stage_instantaneous",
    "discharge_daily_mean",
    "discharge_daily_max",
    "stage_daily_max",
    "water_temperature_reported",
]
Status = Literal[
    "available",
    "empty_no_data_published",
    "empty_in_both_history_windows",
    "history_check_failed",
    "recent_window_empty_history_unchecked",
    "catalogue_membership_history_unchecked",
]
Basis = Literal[
    "publisher_count",
    "historical_positive_witness",
    "two_exact_windows_empty",
    "preserved_history_failure",
    "replacement_window_failure_prior_empty_claim_unverified",
    "catalogue_membership",
]
ROUTES = {
    "discharge_instantaneous": ("observations_tr", "grandeur_hydro", "Q"),
    "stage_instantaneous": ("observations_tr", "grandeur_hydro", "H"),
    "discharge_daily_mean": ("obs_elab", "grandeur_hydro_elab", "QmnJ"),
    "discharge_daily_max": ("obs_elab", "grandeur_hydro_elab", "QIXnJ"),
    "stage_daily_max": ("obs_elab", "grandeur_hydro_elab", "HIXnJ"),
    "water_temperature_reported": ("chronique", None, None),
}


@dataclass(frozen=True)
class AvailabilityAcquisition:
    http_status: int
    material: MaterialIdentity
    media_type: str
    method: Literal["http_request"]
    receipt_id: str | None
    reference: str
    requested_from: tuple[str]
    retrieved_at_start: datetime
    role: Literal["publisher_count", "historical_check"]

    def __post_init__(self) -> None:
        if self.retrieved_at_start.utcoffset() is None:
            raise ValueError("availability acquisition requires a zoned retrieval instant")
        if type(self.material.byte_count) is not int or self.material.byte_count <= 0:
            raise ValueError("availability material requires a positive byte count")
        for location in (self.reference, self.material.filename):
            for part in location.split("!"):
                path = PurePosixPath(part)
                if path.is_absolute() or ".." in path.parts or not part:
                    raise ValueError("availability material reference must be relative")
        if "!" in self.reference:
            archive, member = self.reference.split("!", 1)
            if not archive.endswith(".tar.xz") or member != f"bodies/{self.receipt_id}.body":
                raise ValueError("availability receipt member mismatch")
            expected = self.reference
        else:
            if not self.reference.endswith(".receipt.json"):
                raise ValueError("availability sidecar reference required")
            expected = self.reference.removesuffix(".receipt.json") + ".body"
        if self.material.filename != expected:
            raise ValueError("availability material does not match receipt reference")
        if not self.media_type.strip() or (self.receipt_id is not None and not self.receipt_id.strip()):
            raise ValueError("availability acquisition identity is blank")


@dataclass(frozen=True)
class StationProductAvailability:
    acquisitions: tuple[AvailabilityAcquisition, ...]
    availability: Literal["available", "unknown"]
    basis: Basis
    code_station: str
    product_id: Product
    published_count_or_new_witness_points: int
    status: Status
    catalogue_checked_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.basis == "catalogue_membership":
            if (
                not self.code_station
                or self.acquisitions
                or self.availability != "unknown"
                or self.status != "catalogue_membership_history_unchecked"
                or self.published_count_or_new_witness_points != 0
                or self.catalogue_checked_at is None
                or self.catalogue_checked_at.utcoffset() is None
            ):
                raise ValueError("unchecked membership must not assert observation acquisitions")
            return
        if not self.code_station or not self.acquisitions:
            raise ValueError("availability requires station and acquisitions")
        count = self.published_count_or_new_witness_points
        if count < 0 or self.availability != ("available" if self.status == "available" else "unknown"):
            raise ValueError("availability conclusion mismatch")
        windows = []
        for index, acquisition in enumerate(self.acquisitions):
            expected_role = "publisher_count" if index == 0 else "historical_check"
            if acquisition.role != expected_role:
                raise ValueError("availability acquisition order/role mismatch")
            parsed = urlsplit(acquisition.requested_from[0])
            entries = parse_qsl(parsed.query, keep_blank_values=True)
            query = dict(entries)
            if parsed.scheme != "https" or parsed.fragment or len(entries) != len(query):
                raise ValueError("invalid availability request URL")
            route, field, metric = ROUTES[self.product_id]
            if index == 0:
                temp = self.product_id == "water_temperature_reported"
                path = "/api/v1/temperature/chronique" if temp else f"/api/v2/hydrometrie/{route}"
                expected_query = {
                    "code_station" if temp else "code_entite": self.code_station,
                    "size": "1",
                    "fields": "code_station",
                }
                if field is not None and metric is not None:
                    expected_query[field] = metric
                if parsed.netloc != "hubeau.eaufrance.fr" or parsed.path != path or query != expected_query:
                    raise ValueError("publisher count station/product request mismatch")
                if acquisition.http_status not in (200, 206):
                    raise ValueError("publisher count acquisition must succeed")
            else:
                if not self.product_id.endswith("_instantaneous"):
                    raise ValueError("historical route requires instantaneous product")
                if (
                    parsed.netloc != "hydro.eaufrance.fr"
                    or parsed.path != f"/stationhydro/ajax/{self.code_station}/series"
                ):
                    raise ValueError("historical station route mismatch")
                if (
                    query.get("hydro_series[simpleAndInterpolatedAndHourlyVariable]") != metric
                    or query.get("hydro_series[statusData]") != "raw"
                    or query.get("hydro_series[variableType]") != "simple_and_interpolated_and_hourly_variable"
                ):
                    raise ValueError("historical source product mismatch")
                expected_keys = {
                    "hydro_series[startAt]",
                    "hydro_series[endAt]",
                    "hydro_series[variableType]",
                    "hydro_series[simpleAndInterpolatedAndHourlyVariable]",
                    "hydro_series[statusData]",
                }
                if set(query) != expected_keys:
                    raise ValueError("unexpected historical request parameters")
                window = (query["hydro_series[startAt]"], query["hydro_series[endAt]"])
                if datetime.strptime(window[0], "%d/%m/%Y") > datetime.strptime(window[1], "%d/%m/%Y"):
                    raise ValueError("historical request bounds reversed")
                windows.append(window)
                if acquisition.http_status != 200 and not 400 <= acquisition.http_status <= 599:
                    raise ValueError("historical acquisition status invalid")
        history = self.acquisitions[1:]
        if not history:
            status = (
                "available"
                if count
                else (
                    "recent_window_empty_history_unchecked"
                    if self.product_id.endswith("_instantaneous")
                    else "empty_no_data_published"
                )
            )
            if self.status != status or self.basis != "publisher_count":
                raise ValueError("publisher count conclusion mismatch")
        elif self.basis == "historical_positive_witness":
            if (
                count <= 0
                or self.status != "available"
                or len(history) != 1
                or history[0].http_status != 200
                or windows[0][0] != windows[0][1]
            ):
                raise ValueError("historical positive witness mismatch")
        else:
            if (
                count != 0
                or len(history) < 2
                or set(windows) != {("01/06/2026", "08/06/2026"), ("01/06/2023", "08/06/2023")}
            ):
                raise ValueError("historical two-window conclusion mismatch")
            successes = sum(a.http_status == 200 for a in history)
            if successes == len(history) and len(history) != 2:
                raise ValueError("duplicate successful historical windows")
            status = "empty_in_both_history_windows" if successes == len(history) else "history_check_failed"
            basis = (
                "two_exact_windows_empty"
                if successes == len(history)
                else (
                    "preserved_history_failure"
                    if successes == 0
                    else "replacement_window_failure_prior_empty_claim_unverified"
                )
            )
            if self.status != status or self.basis != basis:
                raise ValueError("historical failed/empty distinction mismatch")

    @property
    def reason(self) -> str:
        return {
            "catalogue_membership_history_unchecked": "Hub’Eau catalogue membership; observation history has not been checked",
            "available": (
                "Publisher observation count is positive for the recorded query; numerical values and continuity are not implied"
                if self.basis == "publisher_count"
                else "Numerical historical witness in the exact recorded one-day station query"
            ),
            "empty_no_data_published": "Publisher whole-record count was zero at acquisition; future availability remains unknown",
            "empty_in_both_history_windows": "Both specified historical windows were empty; whole-history availability remains unknown",
            "history_check_failed": "Historical check failed; historical availability remains unknown",
            "recent_window_empty_history_unchecked": "Recent publisher count was zero; historical availability was not checked",
        }[self.status]


@dataclass(frozen=True)
class AvailabilitySummary:
    available: int
    by_status: Mapping[Status, int]
    pairs: int
    stations: int
    unknown: int


@dataclass(frozen=True)
class FranceAvailability:
    native_table: MaterialIdentity
    pairs: tuple[StationProductAvailability, ...]
    research_head: str
    schema_version: Literal[1]
    scope: str
    summary: AvailabilitySummary

    def __post_init__(self) -> None:
        keys = {(r.code_station, r.product_id) for r in self.pairs}
        statuses = Counter(r.status for r in self.pairs)
        available = statuses["available"]
        if len(keys) != len(self.pairs):
            raise ValueError("duplicate station/product availability")
        if (
            self.summary.pairs != len(keys)
            or self.summary.stations != len({k[0] for k in keys})
            or self.summary.available != available
            or self.summary.unknown != len(keys) - available
            or self.summary.by_status != dict(statuses)
        ):
            raise ValueError("availability ledger accounting mismatch")
        if (
            not self.scope.strip()
            or len(self.research_head) != 40
            or any(c not in "0123456789abcdef" for c in self.research_head)
        ):
            raise ValueError("availability ledger scope/revision invalid")


def _object(value: object, required: tuple[str, ...], optional: tuple[str, ...] = ()) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("availability document component must be an object")
    document = cast(dict[str, object], value)
    if not set(required) <= set(document) or not set(document) <= set(required) | set(optional):
        raise ValueError("availability document component has unexpected or absent fields")
    return document


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("availability field must be a string")
    return value


def _integer(value: object) -> int:
    if type(value) is not int:
        raise ValueError("availability field must be a non-boolean integer")
    return value


def _array(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("availability field must be an array")
    return cast(list[object], value)


def _choice[T: str](value: object, choices: tuple[T, ...]) -> T:
    for choice in choices:
        if isinstance(value, str) and value == choice:
            return choice
    raise ValueError("availability field is outside the declared vocabulary")


def _material(value: object) -> MaterialIdentity:
    raw = _object(value, ("filename", "byte_count", "sha256"))
    return MaterialIdentity(
        filename=_string(raw["filename"]), byte_count=_integer(raw["byte_count"]), sha256=_string(raw["sha256"])
    )


def _acquisition(value: object) -> AvailabilityAcquisition:
    raw = _object(
        value,
        (
            "http_status",
            "material",
            "media_type",
            "method",
            "reference",
            "requested_from",
            "retrieved_at_start",
            "role",
        ),
        ("receipt_id",),
    )
    requests = _array(raw["requested_from"])
    if len(requests) != 1:
        raise ValueError("availability acquisition must name exactly one request")
    return AvailabilityAcquisition(
        http_status=_integer(raw["http_status"]),
        material=_material(raw["material"]),
        media_type=_string(raw["media_type"]),
        method=_choice(raw["method"], ("http_request",)),
        receipt_id=None if "receipt_id" not in raw or raw["receipt_id"] is None else _string(raw["receipt_id"]),
        reference=_string(raw["reference"]),
        requested_from=(_string(requests[0]),),
        retrieved_at_start=datetime.fromisoformat(_string(raw["retrieved_at_start"])),
        role=_choice(raw["role"], ("publisher_count", "historical_check")),
    )


def parse_station_product_availability(value: object) -> StationProductAvailability:
    """Parse one source-identity-bound ledger row without opening a store."""
    raw = _object(
        value,
        (
            "acquisitions",
            "availability",
            "basis",
            "code_station",
            "product_id",
            "published_count_or_new_witness_points",
            "status",
        ),
    )
    return StationProductAvailability(
        acquisitions=tuple(_acquisition(item) for item in _array(raw["acquisitions"])),
        availability=_choice(raw["availability"], ("available", "unknown")),
        basis=_choice(
            raw["basis"],
            (
                "publisher_count",
                "historical_positive_witness",
                "two_exact_windows_empty",
                "preserved_history_failure",
                "replacement_window_failure_prior_empty_claim_unverified",
            ),
        ),
        code_station=_string(raw["code_station"]),
        product_id=_choice(
            raw["product_id"],
            (
                "discharge_instantaneous",
                "stage_instantaneous",
                "discharge_daily_mean",
                "discharge_daily_max",
                "stage_daily_max",
                "water_temperature_reported",
            ),
        ),
        published_count_or_new_witness_points=_integer(raw["published_count_or_new_witness_points"]),
        status=_status(raw["status"]),
    )


def _status(value: object) -> Status:
    return _choice(
        value,
        (
            "available",
            "empty_no_data_published",
            "empty_in_both_history_windows",
            "history_check_failed",
            "recent_window_empty_history_unchecked",
        ),
    )


def decode_availability(document: str | bytes) -> FranceAvailability:
    """Decode the explicitly supplied public ledger, without reading private source bodies."""
    raw = _object(
        json.loads(document), ("native_table", "pairs", "research_head", "schema_version", "scope", "summary")
    )
    summary = _object(raw["summary"], ("available", "by_status", "pairs", "stations", "unknown"))
    by_status = summary["by_status"]
    if not isinstance(by_status, dict):
        raise ValueError("availability status accounting must be an object")
    if _integer(raw["schema_version"]) != 1:
        raise ValueError("unsupported availability ledger revision")
    return FranceAvailability(
        native_table=_material(raw["native_table"]),
        pairs=tuple(parse_station_product_availability(item) for item in _array(raw["pairs"])),
        research_head=_string(raw["research_head"]),
        schema_version=1,
        scope=_string(raw["scope"]),
        summary=AvailabilitySummary(
            available=_integer(summary["available"]),
            by_status=MappingProxyType(
                {_status(key): _integer(count) for key, count in cast(dict[str, object], by_status).items()}
            ),
            pairs=_integer(summary["pairs"]),
            stations=_integer(summary["stations"]),
            unknown=_integer(summary["unknown"]),
        ),
    )


PROVIDER_ID = ProviderId("fr_hubeau")
PROVIDER_NAME = "Hub’Eau — French hydrometry and water temperature"

HYDRO_STATIONS_URL = "https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/stations"
HYDRO_STATIONS_PARAMS = "format=json&size=5000&in_use=true"
HYDRO_SITES_URL = "https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/sites"
TEMP_STATIONS_URL = "https://hubeau.eaufrance.fr/api/v1/temperature/station"
TEMP_STATIONS_PARAMS = "size=5000"

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
    api_type: str
    grandeur_code: str | None


PRODUCT_DEFINITIONS: tuple[ProductDefinition, ...] = (
    # --- obs_elab (historical archive) ----------------------------------------
    # NOTE: HmnJ (daily mean height) does NOT exist in Hubeau obs_elab.
    # The grandeur_hydro request parameter is ignored by the API; filtering is
    # done by the parser on the grandeur_hydro_elab field in each response row.
    ProductDefinition(
        product_id="discharge_daily_mean",
        api_type="obs_elab",
        grandeur_code="QmnJ",
    ),
    ProductDefinition(
        product_id="discharge_daily_max",
        api_type="obs_elab",
        grandeur_code="QIXnJ",
    ),
    ProductDefinition(
        product_id="stage_daily_max",
        api_type="obs_elab",
        grandeur_code="HIXnJ",
    ),
    # --- temperature/chronique (historical archive) ---------------------------
    ProductDefinition(
        product_id="water_temperature_reported",
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
    if payload_mapping.get("next") is not None:
        return _native_issue(f"fr_hubeau {source_endpoint} response has unconsumed pagination")
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
    availability: FranceAvailability,
    *,
    native_capture: NativeInventoryCapture | None = None,
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
    hydro_origins = origins["hydrometrie/referentiel/stations"]
    temperature_origins = origins["temperature/station"]
    _require_origin_columns(hydro, hydro_origins)
    _require_origin_columns(temperature, temperature_origins)
    hydro_stations = build_hydro_stations(hydro)
    temperature_stations = build_temp_stations(temperature)
    enforce_catalogue_origins(PROVIDER_ID, hydro_origins, hydro, hydro_stations)
    enforce_catalogue_origins(PROVIDER_ID, temperature_origins, temperature, temperature_stations)
    stations: StationCatalog = pl.concat([hydro_stations, temperature_stations]).sort("station_id")
    hydro_ids = tuple(hydro.data["code_station"].to_list())
    temperature_ids = tuple(temperature.data["code_station"].to_list())
    expected_pairs = {(station, d.product_id) for station in hydro_ids for d in HYDRO_PRODUCT_DEFS}
    expected_pairs.update((station, d.product_id) for station in temperature_ids for d in TEMP_PRODUCT_DEFS)
    availability = hubeau_availability(availability, expected_pairs, native_table)
    expected_digest = (
        native_capture.native_table.semantic_digest.sha256
        if native_capture and native_capture.native_table.semantic_digest
        else NATIVE_TABLE_SEMANTIC_SHA256
    )
    if native_table_content_digest(native_table) != expected_digest:
        raise FatalContractError("Hub’Eau native content does not match its acquisition identity")
    products = build_products()
    station_products = build_station_products(availability)
    maximum_retrieved_at = native_table.data["retrieved_at"].max()
    if not isinstance(maximum_retrieved_at, datetime):
        raise FatalContractError("fr_hubeau native table has no valid retrieved_at values")
    provider_info = build_provider_info(maximum_retrieved_at.date())
    acquisition_provenance = build_acquisition_provenance(
        hydrometry_station_ids=hydro_ids,
        temperature_station_ids=temperature_ids,
        availability=availability,
        native_capture=native_capture,
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


def hubeau_availability(
    historical: FranceAvailability,
    expected_pairs: set[tuple[str, str]],
    native_table: NativeTable,
) -> FranceAvailability:
    """Reuse only service-owned evidence; membership alone leaves history unknown."""
    identity = historical.native_table
    if (identity.sha256, identity.byte_count, identity.filename) != (
        NATIVE_TABLE_SHA256,
        NATIVE_TABLE_BYTE_SIZE,
        "src/rivretrieve/_internal/providers/fr_hubeau/catalogue/native.parquet",
    ):
        raise FatalContractError("Historical France availability native material identity mismatch")
    existing: dict[tuple[str, str], StationProductAvailability] = {
        (pair.code_station, pair.product_id): pair
        for pair in historical.pairs
        if pair.product_id in EXPECTED_PRODUCT_IDS
    }
    retrievals = dict(native_table.data.select("code_station", "retrieved_at").iter_rows())
    pairs = tuple(
        existing.get(key)
        or StationProductAvailability(
            acquisitions=(),
            availability="unknown",
            basis="catalogue_membership",
            code_station=key[0],
            product_id=cast(Product, key[1]),
            published_count_or_new_witness_points=0,
            status="catalogue_membership_history_unchecked",
            catalogue_checked_at=retrievals[key[0]],
        )
        for key in sorted(expected_pairs)
    )
    statuses = Counter(pair.status for pair in pairs)
    return replace(
        historical,
        pairs=pairs,
        scope="Hub’Eau station daily hydrometry and Naïades temperature",
        summary=AvailabilitySummary(
            available=statuses["available"],
            by_status=MappingProxyType(dict(statuses)),
            pairs=len(pairs),
            stations=len(retrievals),
            unknown=len(pairs) - statuses["available"],
        ),
    )


def _require_origin_columns(native_table: NativeTable, origins: OriginDeclarations) -> None:
    for canonical_column, origin in origins.items():
        native_column = getattr(origin, "native_column", None)
        if native_column is not None and str(native_column) not in native_table.data.columns:
            _raise_catalogue_issue(
                "catalogue_origin.absent_native_column",
                f"fr_hubeau.{canonical_column}: native column '{native_column}' does not exist",
            )


def _raise_catalogue_issue(code: str, message: str) -> Never:
    issue = Issue(severity="error", code=code, message=message, provider_id=PROVIDER_ID)
    raise FatalContractError(message, issues=(issue,))


def build_products() -> ProductCatalog:
    from rivretrieve._internal.providers.fr_hubeau.config import SERIES_MAPPINGS

    rows = [
        product_row(
            PROVIDER_ID, d.product_id, d.grandeur_code or d.api_type, SERIES_MAPPINGS[d.product_id].physical_facts()
        )
        for d in PRODUCT_DEFINITIONS
    ]
    return pl.DataFrame(rows, schema=PRODUCT_CATALOG_SCHEMA.polars_schema).sort("product_id")


def build_hydro_stations(native_table: NativeTable) -> StationCatalog:
    rows: list[dict[str, object]] = []
    for native_row in native_table.data.iter_rows(named=True):
        station_id = native_row["code_station"]
        try:
            latitude, longitude = hydrometry_coordinates(native_row)
        except Projection31PreconditionError:
            _raise_catalogue_issue(
                "catalogue_coordinate.correction_precondition_failed",
                f"fr_hubeau station {station_id} code_projection=31 does not match the documented transposition signature",
            )
        except Projection31BoundsError:
            _raise_catalogue_issue(
                "catalogue_coordinate.outside_metropolitan_bounds",
                f"fr_hubeau station {station_id} remains outside the evidenced metropolitan bounds after code_projection=31 correction",
            )
        rows.append(
            {
                "provider_id": PROVIDER_ID,
                "station_id": station_id,
                "latitude": latitude,
                "longitude": longitude,
                "crs": "EPSG:4326",
            }
        )
    return pl.DataFrame(rows, schema=STATION_CATALOG_SCHEMA.polars_schema).sort("station_id")


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


def build_station_products(availability: FranceAvailability) -> StationProductCatalog:
    rows = [
        {
            "provider_id": PROVIDER_ID,
            "station_id": pair.code_station,
            "product_id": pair.product_id,
            "availability": pair.availability,
            "availability_reason": pair.reason,
            "published_record_start_date": None,
            "published_record_end_date": None,
            "last_catalogue_check": (
                max(a.retrieved_at_start for a in pair.acquisitions).date()
                if pair.acquisitions
                else pair.catalogue_checked_at.date()
                if pair.catalogue_checked_at
                else None
            ),
        }
        for pair in availability.pairs
    ]
    return pl.DataFrame(rows, schema=STATION_PRODUCT_CATALOG_SCHEMA.polars_schema).sort("station_id", "product_id")


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
            "true: paginated obs_elab and temperature/chronique requests; "
            "partial failures reported as recoverable issues"
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


def write_catalogue(
    catalogue: GeneratedFrHubeauCatalogue,
    out_dir: Path | str,
    *,
    build_inputs: CatalogueBuildInputs | None = None,
    native_table: NativeTable | None = None,
) -> None:
    """Write a catalogue using adopted build inputs and its verified native table."""
    from rivretrieve._internal.catalogues.artifact import REQUIRED_ARTIFACT_FILES
    from rivretrieve._internal.catalogues.publication import build_catalogue_metadata
    from rivretrieve._internal.providers.fr_hubeau.config import SERIES_MAPPINGS
    from rivretrieve._internal.providers.fr_hubeau.config import config as source_config
    from rivretrieve._internal.providers.fr_hubeau.origins import FRANCE_ORIGIN_DECLARATIONS, STATION_METADATA_FIELDS

    if build_inputs is None or native_table is None:
        raise FatalContractError("Catalogue publication requires explicit build_inputs and native_table")

    output_path = Path(out_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    with (output_path / "provider.json").open("w", encoding="utf-8") as f:
        json.dump(catalogue.public_artifact.provider_info, f, sort_keys=True, separators=(",", ":"))
        f.write("\n")
    catalogue.public_artifact.products.write_parquet(output_path / "products.parquet")
    catalogue.public_artifact.stations.write_parquet(output_path / "stations.parquet")
    catalogue.public_artifact.station_products.write_parquet(output_path / "station_products.parquet")
    metadata = build_catalogue_metadata(
        catalogue.acquisition_provenance,
        tuple(FRANCE_ORIGIN_DECLARATIONS.values()),
        {name: (output_path / name).read_bytes() for name in REQUIRED_ARTIFACT_FILES},
        source_config=source_config(),
        source_mappings=SERIES_MAPPINGS,
        build_inputs=build_inputs,
        native_table=native_table,
        metadata_fields=STATION_METADATA_FIELDS,
    )
    for name, content in metadata.items():
        (output_path / name).write_bytes(content)


def _read_fixture_json(path: Path) -> dict[str, object]:
    try:
        content = path.read_bytes()
        value = json.loads(lzma.decompress(content) if path.suffix == ".xz" else content)
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
    parser.add_argument("--native-capture", type=Path, help="Acquisition manifest for the supplied native snapshot.")
    parser.add_argument("--native", type=Path, help="Retained native Parquet input for canonical build.")
    parser.add_argument(
        "--evidence-root",
        type=Path,
        help="External retained inputs in their repository-relative layout, required for canonical build.",
    )
    parser.add_argument(
        "--availability-ledger", type=Path, help="Reviewed compressed France station-product availability ledger."
    )
    parser.add_argument("--out", type=Path, help="Output directory for provider.json and parquet files.")
    parser.add_argument("--native-out", type=Path, help="Output path for the native Parquet table.")
    parser.add_argument("--hydro-retrieved-at", type=_parse_retrieved_at)
    parser.add_argument("--temperature-retrieved-at", type=_parse_retrieved_at)
    parser.add_argument("--build-inputs", type=Path, help="Reviewed adopted catalogue build inputs JSON.")
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
        if args.availability_ledger is None:
            parser.error("--availability-ledger is required for canonical build")
        if args.evidence_root is None:
            parser.error("--evidence-root is required for canonical build")
        if args.build_inputs is None:
            parser.error("--out requires --build-inputs")
        build_inputs = CatalogueBuildInputs.model_validate_json(args.build_inputs.read_bytes())
        availability = decode_availability(lzma.decompress(args.availability_ledger.read_bytes()))
        from rivretrieve._internal.providers.fr_hubeau.origins import FRANCE_ORIGIN_DECLARATIONS

        capture = (
            NativeInventoryCapture.model_validate_json(args.native_capture.read_bytes())
            if args.native_capture
            else None
        )
        native_table = read_native_table(
            args.native,
            expected_sha256=capture.native_table.sha256 if capture else NATIVE_TABLE_SHA256,
            expected_byte_size=capture.native_table.byte_size if capture else NATIVE_TABLE_BYTE_SIZE,
        )
        catalogue = build_catalogue(
            native_table,
            FRANCE_ORIGIN_DECLARATIONS,
            availability,
            native_capture=capture,
        )
        verify_provenance_recordings(catalogue.acquisition_provenance, args.evidence_root)
        write_catalogue(catalogue, args.out, build_inputs=build_inputs, native_table=native_table)
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
