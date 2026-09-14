"""France availability : GoverningEvidenceJSON → FranceAvailability (pure).

This decoder checks public ledger consistency, not the private source bytes.
Body-backed offline verification remains a separate acceptance requirement.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal, Self, cast
from urllib.parse import parse_qsl, urlsplit  # noqa: TID251 -- structural parsing only

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from rivretrieve._internal.acquisition_provenance import MaterialIdentity

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
]
Basis = Literal[
    "publisher_count",
    "historical_positive_witness",
    "two_exact_windows_empty",
    "preserved_history_failure",
    "replacement_window_failure_prior_empty_claim_unverified",
]
ROUTES = {
    "discharge_instantaneous": ("observations_tr", "grandeur_hydro", "Q"),
    "stage_instantaneous": ("observations_tr", "grandeur_hydro", "H"),
    "discharge_daily_mean": ("obs_elab", "grandeur_hydro_elab", "QmnJ"),
    "discharge_daily_max": ("obs_elab", "grandeur_hydro_elab", "QIXnJ"),
    "stage_daily_max": ("obs_elab", "grandeur_hydro_elab", "HIXnJ"),
    "water_temperature_reported": ("chronique", None, None),
}


class _LedgerModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    @field_validator("material", "native_table", mode="before", check_fields=False)
    @classmethod
    def material_integer_is_not_coerced(cls, value: object) -> object:
        if isinstance(value, dict) and type(cast(dict[str, object], value).get("byte_count")) is not int:
            raise ValueError("material byte count must be a non-boolean integer")
        return value


class AvailabilityAcquisition(_LedgerModel):
    http_status: int
    material: MaterialIdentity
    media_type: str
    method: Literal["http_request"]
    receipt_id: str | None = None
    reference: str
    requested_from: tuple[str]
    retrieved_at_start: datetime
    role: Literal["publisher_count", "historical_check"]

    @model_validator(mode="after")
    def check_identity(self) -> Self:
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
        return self


class StationProductAvailability(_LedgerModel):
    acquisitions: tuple[AvailabilityAcquisition, ...]
    availability: Literal["available", "unknown"]
    basis: Basis
    code_station: str
    product_id: Product
    published_count_or_new_witness_points: int
    status: Status

    @model_validator(mode="after")
    def check_conclusion(self) -> Self:
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
        return self

    @property
    def reason(self) -> str:
        return {
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


class AvailabilitySummary(_LedgerModel):
    available: int
    by_status: dict[Status, int]
    pairs: int
    stations: int
    unknown: int


class FranceAvailability(_LedgerModel):
    native_table: MaterialIdentity
    pairs: tuple[StationProductAvailability, ...]
    research_head: str
    schema_version: Literal[1]
    scope: str
    summary: AvailabilitySummary

    @model_validator(mode="after")
    def check_accounting(self) -> Self:
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
        return self
