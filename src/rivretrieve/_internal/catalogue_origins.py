"""CatalogueOrigin ≔ Field | Authored | NotPublished | Documented | Withheld; origin gate : EnrolledProvider × OriginDeclarations × NativeTable × StationCatalog → list[Issue]."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast, final

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
    """An exact, non-empty provider identity authored by RivRetrieve."""

    def __new__(cls, value: str) -> AuthoredValue:
        if not isinstance(value, str):
            raise TypeError("authored value must be a string")
        if not value.strip():
            raise ValueError("authored value must not be empty")
        return super().__new__(cls, value)


class ConversionName(str):
    """A stable non-empty name for one native-to-canonical conversion contract."""

    def __new__(cls, value: str) -> ConversionName:
        if not isinstance(value, str):
            raise TypeError("conversion name must be a string")
        if not value.strip():
            raise ValueError("conversion name must not be empty")
        return super().__new__(cls, value)


class FieldConversion(ABC):
    """A typed, immutable native-field conversion invoked by the generic origin gate."""

    __slots__ = ()

    @property
    @abstractmethod
    def name(self) -> ConversionName:
        """Return the stable conversion-contract name."""

    @abstractmethod
    def apply(
        self,
        canonical_column: str,
        native_column: NativeColumn,
        native_row: Mapping[str, object],
    ) -> object:
        """Convert one native row to the declared canonical field value."""

    @final
    def __eq__(self, other: object) -> bool:
        return type(self) is type(other) and self.name == other.name

    @final
    def __hash__(self) -> int:
        return hash((type(self), self.name))

    @final
    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


class IdentityConversion(FieldConversion):
    """Copy the declared native field without conversion."""

    __slots__ = ()

    @property
    def name(self) -> ConversionName:
        return ConversionName("identity")

    def apply(
        self,
        canonical_column: str,
        native_column: NativeColumn,
        native_row: Mapping[str, object],
    ) -> object:
        del canonical_column
        return native_row[str(native_column)]


class FloatConversion(FieldConversion):
    """Convert a source-neutral scalar numeric representation to float."""

    __slots__ = ()

    @property
    def name(self) -> ConversionName:
        return ConversionName("float")

    def apply(
        self,
        canonical_column: str,
        native_column: NativeColumn,
        native_row: Mapping[str, object],
    ) -> object:
        del canonical_column
        value = native_row[str(native_column)]
        if isinstance(value, bool) or not isinstance(value, str | int | float):
            raise ValueError("numeric field is absent")
        return float(value)


class StructMemberConversion(FieldConversion):
    """Select the canonical coordinate name from a source-neutral coordinate structure."""

    __slots__ = ()

    @property
    def name(self) -> ConversionName:
        return ConversionName("struct_member")

    def apply(
        self,
        canonical_column: str,
        native_column: NativeColumn,
        native_row: Mapping[str, object],
    ) -> object:
        value = native_row[str(native_column)]
        if not isinstance(value, Mapping) or canonical_column not in {"latitude", "longitude"}:
            raise ValueError("coordinate structure is invalid")
        return cast("Mapping[str, object]", value)[canonical_column]


@dataclass(frozen=True, slots=True)
class Field:
    native_column: NativeColumn
    conversion: FieldConversion = IdentityConversion()

    def __post_init__(self) -> None:
        if not isinstance(self.native_column, NativeColumn):
            raise TypeError("Field.native_column must be a NativeColumn")
        if not isinstance(self.conversion, FieldConversion):
            raise TypeError("Field.conversion must be a FieldConversion")


@dataclass(frozen=True, slots=True)
class Authored:
    """The RivRetrieve-authored provider identity origin."""

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
        ProviderId("br_ana"),
        ProviderId("ca_eccc"),
        ProviderId("ch_foen"),
        ProviderId("cz_chmi"),
        ProviderId("fr_hubeau"),
        ProviderId("fr_hydroportail"),
        ProviderId("jp_mlit"),
        ProviderId("lt_lhmt"),
        ProviderId("no_nve"),
        ProviderId("pl_imgw"),
        ProviderId("th_thaiwater"),
        ProviderId("usgs_nwis"),
        ProviderId("za_dws"),
    }
)
"""Providers with explicit catalogue origin declarations."""


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
                                f"cannot undergo {origin.conversion.name} conversion"
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
                                f"declared native field '{native_column}' through {origin.conversion.name}"
                            ),
                            details=details,
                            provider_id=provider_id,
                        )
                    )
                    break
        elif isinstance(origin, Authored):
            if canonical_column != "provider_id":
                issues.append(
                    Issue(
                        severity="error",
                        code="catalogue_origin.authored_scope_invalid",
                        message=(
                            f"{provider_id}.{canonical_column}: Authored origin is permitted only for provider_id"
                        ),
                        details=details,
                        provider_id=provider_id,
                    )
                )
            elif not isinstance(getattr(origin, "value", None), AuthoredValue):
                issues.append(
                    Issue(
                        severity="error",
                        code="catalogue_origin.malformed_authored_value",
                        message=f"{provider_id}.{canonical_column}: Authored origin must carry AuthoredValue",
                        details=details,
                        provider_id=provider_id,
                    )
                )
            elif origin.value != provider_id:
                issues.append(
                    Issue(
                        severity="error",
                        code="catalogue_origin.authored_provider_mismatch",
                        message=(
                            f"{provider_id}.{canonical_column}: authored value '{origin.value}' must equal "
                            f"gate provider identity '{provider_id}'"
                        ),
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
        elif isinstance(origin, NotPublished):
            if not isinstance(getattr(origin, "evidence", None), Evidence):
                issues.append(
                    Issue(
                        severity="error",
                        code="catalogue_origin.missing_evidence",
                        message=f"{provider_id}.{canonical_column}: NotPublished origin must carry Evidence",
                        details=details,
                        provider_id=provider_id,
                    )
                )
            elif _has_value_other_than(stations, canonical_column, "unknown"):
                issues.append(
                    Issue(
                        severity="error",
                        code="catalogue_origin.not_published_marker_mismatch",
                        message=f"{provider_id}.{canonical_column}: NotPublished origin must emit only 'unknown'",
                        details=details,
                        provider_id=provider_id,
                    )
                )
        else:
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


def _field_value(
    canonical_column: str,
    origin: Field,
    native_row: Mapping[str, object],
) -> object:
    return origin.conversion.apply(canonical_column, origin.native_column, native_row)


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
