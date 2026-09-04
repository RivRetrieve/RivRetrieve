"""CatalogueOrigin ≔ Field | Authored | NotPublished | Documented | Withheld; origin gate : EnrolledProvider × OriginDeclarations × NativeTable × StationCatalog → list[Issue]."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, cast

import polars as pl

from rivretrieve._internal.catalogues.native import NativeTable
from rivretrieve._internal.catalogues.schemas import STATION_CATALOG_SCHEMA, StationCatalog
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProviderId

_HTTP_DOCUMENTATION_URL = re.compile(r"https?://[^\s/?#]+(?:[/?#][^\s]*)?")


class NativeColumn(str):
    """An exact, non-empty column name in a provider's native table."""

    def __new__(cls, value: str) -> NativeColumn:
        if not isinstance(value, str):
            raise TypeError("native column name must be a string")
        if not value.strip():
            raise ValueError("native column name must not be empty")
        return super().__new__(cls, value)


class Evidence(str):
    """An absolute HTTP(S) link to a provider's own documentation."""

    def __new__(cls, value: str) -> Evidence:
        if not isinstance(value, str):
            raise TypeError("evidence must be a string")
        if _HTTP_DOCUMENTATION_URL.fullmatch(value) is None:
            raise ValueError("evidence must be an absolute HTTP(S) documentation link")
        return super().__new__(cls, value)


class DocumentedValue(str):
    """An exact, non-empty constant stated in provider documentation."""

    def __new__(cls, value: str) -> DocumentedValue:
        if not isinstance(value, str):
            raise TypeError("documented value must be a string")
        if not value.strip():
            raise ValueError("documented value must not be empty")
        return super().__new__(cls, value)


class AuthoredValue(str):
    """An exact, non-empty canonical constant authored by RivRetrieve."""

    def __new__(cls, value: str) -> AuthoredValue:
        if not isinstance(value, str):
            raise TypeError("authored value must be a string")
        if not value.strip():
            raise ValueError("authored value must not be empty")
        return super().__new__(cls, value)


class FieldTransform(StrEnum):
    """An explicit established conversion from one native field to one canonical value."""

    IDENTITY = "identity"
    FLOAT = "float"
    STRUCT_MEMBER = "struct_member"
    JAPAN_COMBINED_DMS = "japan_combined_dms"
    DWS_UNSIGNED_DMS = "dws_unsigned_dms"
    USGS_DATUM_TO_CRS = "usgs_datum_to_crs"
    FRANCE_PROJECTION_31 = "france_projection_31"


@dataclass(frozen=True, slots=True)
class Field:
    native_column: NativeColumn
    transform: FieldTransform = FieldTransform.IDENTITY

    def __post_init__(self) -> None:
        if not isinstance(self.native_column, NativeColumn):
            raise TypeError("Field.native_column must be a NativeColumn")
        if not isinstance(self.transform, FieldTransform):
            raise TypeError("Field.transform must be a FieldTransform")


@dataclass(frozen=True, slots=True)
class Authored:
    value: AuthoredValue

    def __post_init__(self) -> None:
        if not isinstance(self.value, AuthoredValue):
            raise TypeError("Authored.value must be an AuthoredValue")


@dataclass(frozen=True, slots=True)
class NotPublished:
    evidence: Evidence

    def __post_init__(self) -> None:
        if not isinstance(self.evidence, Evidence):
            raise TypeError("NotPublished.evidence must be Evidence")


@dataclass(frozen=True, slots=True)
class Withheld:
    """A canonical placeholder whose source fact lacks acquisition evidence."""

    reason: Literal["acquisition_not_established"] = "acquisition_not_established"
    marker: Literal["unknown"] = "unknown"


@dataclass(frozen=True, slots=True)
class Documented:
    value: DocumentedValue
    evidence: Evidence

    def __post_init__(self) -> None:
        if not isinstance(self.value, DocumentedValue):
            raise TypeError("Documented.value must be a DocumentedValue")
        if not isinstance(self.evidence, Evidence):
            raise TypeError("Documented.evidence must be Evidence")


type CatalogueOrigin = Field | Authored | NotPublished | Documented | Withheld
type OriginDeclarations = Mapping[str, object]

ORIGIN_GATE_ENROLLED_PROVIDERS = frozenset(
    {
        ProviderId("ba_fhmzbih"),
        ProviderId("ca_eccc"),
        ProviderId("ch_foen"),
        ProviderId("cz_chmi"),
        ProviderId("fr_hubeau"),
        ProviderId("jp_mlit"),
        ProviderId("lt_lhmt"),
        ProviderId("no_nve"),
        ProviderId("pl_imgw"),
        ProviderId("th_thaiwater"),
        ProviderId("usgs_nwis"),
        ProviderId("za_dws"),
    }
)
"""The twelve providers with complete audited catalogue origin declarations. br_ana remains explicitly deferred."""


def validate_catalogue_origins(
    provider_id: ProviderId,
    declarations: OriginDeclarations,
    native_table: NativeTable,
    stations: StationCatalog,
) -> list[Issue]:
    """Report invalid origins, including row loss and contradicted field declarations."""
    issues: list[Issue] = []
    native_station_id = _resolve_station_id_alignment_key(declarations, native_table, stations)
    native_by_station: dict[object, Mapping[str, object]] = {}
    canonical_by_station: dict[object, Mapping[str, object]] = {}
    native_alignment_valid = True
    canonical_alignment_valid = True
    if native_station_id is None:
        issues.append(
            Issue(
                severity="error",
                code="catalogue_origin.unresolvable_alignment_key",
                message=(
                    f"{provider_id}.station_id: rule (c) could not be evaluated because the station_id "
                    "alignment key is unresolvable"
                ),
                details={"canonical_column": "station_id"},
                provider_id=provider_id,
            )
        )
    else:
        station_origin = declarations["station_id"]
        assert isinstance(station_origin, Field)
        for row in native_table.data.iter_rows(named=True):
            try:
                station_id = _field_value("station_id", station_origin, row)
            except (KeyError, TypeError, ValueError):
                station_id = None
            if station_id is None or station_id in native_by_station:
                issues.append(
                    Issue(
                        severity="error",
                        code="catalogue_origin.unresolvable_alignment_key",
                        message=f"{provider_id}.station_id: native alignment identities must be non-null and unique",
                        details={"canonical_column": "station_id"},
                        provider_id=provider_id,
                    )
                )
                native_by_station = {}
                native_alignment_valid = False
                break
            native_by_station[station_id] = row
        for row in stations.iter_rows(named=True):
            station_id = row["station_id"]
            if station_id is None or station_id in canonical_by_station:
                issues.append(
                    Issue(
                        severity="error",
                        code="catalogue_origin.unresolvable_alignment_key",
                        message=f"{provider_id}.station_id: canonical alignment identities must be non-null and unique",
                        details={"canonical_column": "station_id"},
                        provider_id=provider_id,
                    )
                )
                canonical_by_station = {}
                canonical_alignment_valid = False
                break
            canonical_by_station[station_id] = row
        if (
            native_alignment_valid
            and canonical_alignment_valid
            and native_by_station.keys() != canonical_by_station.keys()
        ):
            missing = sorted(str(value) for value in native_by_station.keys() - canonical_by_station.keys())
            unexpected = sorted(str(value) for value in canonical_by_station.keys() - native_by_station.keys())
            issues.append(
                Issue(
                    severity="error",
                    code="catalogue_origin.station_row_mismatch",
                    message=f"{provider_id}.station_id: native and canonical station rows are not one-to-one",
                    details={
                        "canonical_column": "station_id",
                        "missing_station_ids": missing,
                        "unexpected_station_ids": unexpected,
                    },
                    provider_id=provider_id,
                )
            )

    for column in STATION_CATALOG_SCHEMA.columns:
        canonical_column = column.name
        details: dict[str, object] = {"canonical_column": canonical_column}
        if canonical_column not in declarations:
            issues.append(
                Issue(
                    severity="error",
                    code="catalogue_origin.undeclared_column",
                    message=f"{provider_id}.{canonical_column}: canonical column has no origin declaration",
                    details=details,
                    provider_id=provider_id,
                )
            )
            continue

        origin = declarations[canonical_column]
        if isinstance(origin, Field):
            native_column = str(origin.native_column)
            if native_column not in native_table.data.columns:
                issues.append(
                    Issue(
                        severity="error",
                        code="catalogue_origin.absent_native_column",
                        message=f"{provider_id}.{canonical_column}: native column '{native_column}' does not exist",
                        details=details,
                        provider_id=provider_id,
                    )
                )
                continue
            for station_id in native_by_station.keys() & canonical_by_station.keys():
                try:
                    expected = _field_value(
                        canonical_column,
                        origin,
                        native_by_station[station_id],
                    )
                except (KeyError, TypeError, ValueError):
                    issues.append(
                        Issue(
                            severity="error",
                            code="catalogue_origin.field_conversion_failed",
                            message=(
                                f"{provider_id}.{canonical_column}: declared native field '{native_column}' "
                                f"cannot undergo {origin.transform.value} conversion"
                            ),
                            details=details,
                            provider_id=provider_id,
                        )
                    )
                    break
                actual = canonical_by_station[station_id][canonical_column]
                if actual != expected:
                    unpropagated = actual is None and expected is not None
                    issues.append(
                        Issue(
                            severity="error",
                            code=(
                                "catalogue_origin.unpropagated_value"
                                if unpropagated
                                else "catalogue_origin.field_value_mismatch"
                            ),
                            message=(
                                f"{provider_id}.{canonical_column}: canonical value is null where native column "
                                f"'{native_column}' has a value"
                                if unpropagated
                                else f"{provider_id}.{canonical_column}: emitted value does not reproduce the "
                                f"declared native field '{native_column}' through {origin.transform.value}"
                            ),
                            details=details,
                            provider_id=provider_id,
                        )
                    )
                    break
        elif isinstance(origin, Authored):
            if not isinstance(getattr(origin, "value", None), AuthoredValue):
                issues.append(
                    Issue(
                        severity="error",
                        code="catalogue_origin.malformed_authored_value",
                        message=f"{provider_id}.{canonical_column}: Authored origin must carry AuthoredValue",
                        details=details,
                        provider_id=provider_id,
                    )
                )
            elif _has_value_other_than(stations, canonical_column, origin.value):
                issues.append(
                    Issue(
                        severity="error",
                        code="catalogue_origin.authored_value_mismatch",
                        message=(
                            f"{provider_id}.{canonical_column}: emitted value does not match authored value "
                            f"'{origin.value}'"
                        ),
                        details=details,
                        provider_id=provider_id,
                    )
                )
        elif isinstance(origin, Documented):
            if not isinstance(getattr(origin, "evidence", None), Evidence):
                issues.append(
                    Issue(
                        severity="error",
                        code="catalogue_origin.missing_evidence",
                        message=f"{provider_id}.{canonical_column}: Documented origin must carry Evidence",
                        details=details,
                        provider_id=provider_id,
                    )
                )
            elif not isinstance(getattr(origin, "value", None), DocumentedValue):
                issues.append(
                    Issue(
                        severity="error",
                        code="catalogue_origin.malformed_documented_value",
                        message=f"{provider_id}.{canonical_column}: Documented origin must carry DocumentedValue",
                        details=details,
                        provider_id=provider_id,
                    )
                )
            elif _has_value_other_than(stations, canonical_column, origin.value):
                issues.append(
                    Issue(
                        severity="error",
                        code="catalogue_origin.documented_value_mismatch",
                        message=(
                            f"{provider_id}.{canonical_column}: emitted value does not match documented value "
                            f"'{origin.value}'"
                        ),
                        details=details,
                        provider_id=provider_id,
                    )
                )
        elif isinstance(origin, Withheld):
            if origin.reason != "acquisition_not_established":
                issues.append(
                    Issue(
                        severity="error",
                        code="catalogue_origin.malformed_withheld_reason",
                        message=f"{provider_id}.{canonical_column}: Withheld origin has an invalid reason",
                        details=details,
                        provider_id=provider_id,
                    )
                )
            elif origin.marker != "unknown" or _has_value_other_than(
                stations,
                canonical_column,
                DocumentedValue(origin.marker),
            ):
                issues.append(
                    Issue(
                        severity="error",
                        code="catalogue_origin.withheld_marker_mismatch",
                        message=(
                            f"{provider_id}.{canonical_column}: Withheld origin must emit only the "
                            f"unavailable marker {origin.marker!r}"
                        ),
                        details=details,
                        provider_id=provider_id,
                    )
                )
        elif not isinstance(origin, NotPublished) or not isinstance(getattr(origin, "evidence", None), Evidence):
            issues.append(
                Issue(
                    severity="error",
                    code="catalogue_origin.missing_evidence",
                    message=f"{provider_id}.{canonical_column}: NotPublished origin must carry Evidence",
                    details=details,
                    provider_id=provider_id,
                )
            )
    return issues


def enforce_catalogue_origins(
    provider_id: ProviderId,
    declarations: OriginDeclarations,
    native_table: NativeTable,
    stations: StationCatalog,
) -> None:
    if provider_id not in ORIGIN_GATE_ENROLLED_PROVIDERS:
        raise FatalContractError(f"{provider_id}: provider is not enrolled in catalogue origin gate")
    issues = validate_catalogue_origins(provider_id, declarations, native_table, stations)
    if issues:
        raise FatalContractError(issues[0].message, issues=issues)


_JAPAN_DMS = re.compile(r"北緯\s*(\d+)度(\d+)分(\d+)秒\s*東経\s*(\d+)度(\d+)分(\d+)秒")
_USGS_DATUM_TO_CRS = {
    "NAD27": "EPSG:4267",
    "NAD83": "EPSG:4269",
    "OLDHI": "EPSG:4135",
    "WGS72": "EPSG:4322",
    "WGS84": "EPSG:4326",
}


def _field_value(
    canonical_column: str,
    origin: Field,
    native_row: Mapping[str, object],
) -> object:
    value = native_row[str(origin.native_column)]
    transform = origin.transform
    if transform is FieldTransform.IDENTITY:
        return value
    if transform is FieldTransform.FLOAT:
        if isinstance(value, bool) or not isinstance(value, str | int | float):
            raise ValueError("numeric field is absent")
        return float(value)
    if transform is FieldTransform.STRUCT_MEMBER:
        if not isinstance(value, Mapping) or canonical_column not in {"latitude", "longitude"}:
            raise ValueError("coordinate structure is invalid")
        return cast("Mapping[str, object]", value)[canonical_column]
    if transform is FieldTransform.JAPAN_COMBINED_DMS:
        if not isinstance(value, str) or (match := _JAPAN_DMS.fullmatch(value)) is None:
            raise ValueError("combined DMS coordinate is invalid")
        parts = tuple(map(int, match.groups()))
        offset = 0 if canonical_column == "latitude" else 3 if canonical_column == "longitude" else -1
        if offset < 0:
            raise ValueError("combined DMS is only a coordinate conversion")
        degrees, minutes, seconds = parts[offset : offset + 3]
        return degrees + minutes / 60 + seconds / 3600
    if transform is FieldTransform.DWS_UNSIGNED_DMS:
        if not isinstance(value, str) or canonical_column not in {"latitude", "longitude"}:
            raise ValueError("unsigned DMS coordinate is invalid")
        parts = value.split(":")
        if len(parts) != 3:
            raise ValueError("unsigned DMS coordinate is invalid")
        degrees, minutes, seconds = map(float, parts)
        magnitude = degrees + minutes / 60 + seconds / 3600
        return -magnitude if canonical_column == "latitude" else magnitude
    if transform is FieldTransform.USGS_DATUM_TO_CRS:
        if not isinstance(value, str) or canonical_column != "crs":
            raise ValueError("USGS datum is invalid")
        return _USGS_DATUM_TO_CRS.get(value, "unknown")
    if transform is FieldTransform.FRANCE_PROJECTION_31:
        if canonical_column not in {"latitude", "longitude"}:
            raise ValueError("France projection conversion is only a coordinate conversion")
        if native_row.get("code_projection") == 31:
            other = "longitude_station" if canonical_column == "latitude" else "latitude_station"
            return native_row[other]
        return value
    raise AssertionError(f"unsupported field transform: {transform}")


def _resolve_station_id_alignment_key(
    declarations: OriginDeclarations,
    native_table: NativeTable,
    stations: StationCatalog,
) -> str | None:
    station_id_origin = declarations.get("station_id")
    if not isinstance(station_id_origin, Field):
        return None
    native_station_id = str(station_id_origin.native_column)
    if native_station_id not in native_table.data.columns or "station_id" not in stations.columns:
        return None
    return native_station_id


def _has_value_other_than(
    stations: StationCatalog,
    canonical_column: str,
    documented_value: str,
) -> bool:
    mismatches = stations.select(
        (pl.col(canonical_column) != pl.lit(str(documented_value))).fill_null(True).alias("mismatch")
    )
    return mismatches["mismatch"].any()
