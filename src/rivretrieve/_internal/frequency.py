from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

_ELAPSED_RE = re.compile(r"\APT(?:([0-9]+)H)?(?:([0-9]+)M)?(?:([0-9]+)S)?\Z")
_CALENDAR_DAYS_RE = re.compile(r"\AP(?:([0-9]+)W)?(?:([0-9]+)D)?\Z")
_CALENDAR_MONTHS_RE = re.compile(r"\AP(?:([0-9]+)Y)?(?:([0-9]+)M)?\Z")


class FrequencyFamily(StrEnum):
    """Disjoint duration families preserved across canonicalization."""

    ELAPSED = "elapsed"
    CALENDAR_DAYS = "calendar_days"
    CALENDAR_MONTHS = "calendar_months"


class FrequencyUnit(StrEnum):
    """Single-unit canonical suffixes within a frequency family."""

    SECONDS = "seconds"
    MINUTES = "minutes"
    HOURS = "hours"
    DAYS = "days"
    WEEKS = "weeks"
    MONTHS = "months"
    YEARS = "years"


def _reduce_elapsed(hours: int, minutes: int, seconds: int) -> tuple[int, FrequencyUnit, str]:
    total_seconds = hours * 3600 + minutes * 60 + seconds
    if total_seconds <= 0:
        raise ValueError("Frequency duration must be positive")
    if total_seconds % 3600 == 0:
        value = total_seconds // 3600
        return value, FrequencyUnit.HOURS, f"PT{value}H"
    if total_seconds % 60 == 0:
        value = total_seconds // 60
        return value, FrequencyUnit.MINUTES, f"PT{value}M"
    return total_seconds, FrequencyUnit.SECONDS, f"PT{total_seconds}S"


def _reduce_days(weeks: int, days: int) -> tuple[int, FrequencyUnit, str]:
    total_days = weeks * 7 + days
    if total_days <= 0:
        raise ValueError("Frequency duration must be positive")
    if total_days % 7 == 0:
        value = total_days // 7
        return value, FrequencyUnit.WEEKS, f"P{value}W"
    return total_days, FrequencyUnit.DAYS, f"P{total_days}D"


def _reduce_months(years: int, months: int) -> tuple[int, FrequencyUnit, str]:
    total_months = years * 12 + months
    if total_months <= 0:
        raise ValueError("Frequency duration must be positive")
    if total_months % 12 == 0:
        value = total_months // 12
        return value, FrequencyUnit.YEARS, f"P{value}Y"
    return total_months, FrequencyUnit.MONTHS, f"P{total_months}M"


def _parse_optional_int(raw: str | None) -> int:
    return 0 if raw is None else int(raw)


def _canonical_parts(family: FrequencyFamily, value: int, unit: FrequencyUnit) -> tuple[int, FrequencyUnit, str]:
    if family is FrequencyFamily.ELAPSED:
        if unit is FrequencyUnit.HOURS:
            return _reduce_elapsed(value, 0, 0)
        if unit is FrequencyUnit.MINUTES:
            return _reduce_elapsed(0, value, 0)
        if unit is FrequencyUnit.SECONDS:
            return _reduce_elapsed(0, 0, value)
    elif family is FrequencyFamily.CALENDAR_DAYS:
        if unit is FrequencyUnit.WEEKS:
            return _reduce_days(value, 0)
        if unit is FrequencyUnit.DAYS:
            return _reduce_days(0, value)
    elif family is FrequencyFamily.CALENDAR_MONTHS:
        if unit is FrequencyUnit.YEARS:
            return _reduce_months(value, 0)
        if unit is FrequencyUnit.MONTHS:
            return _reduce_months(0, value)
    raise ValueError(f"Unit {unit!r} is incompatible with frequency family {family!r}")


@dataclass(frozen=True, slots=True)
class Frequency:
    """Canonical reporting frequency represented in an ISO 8601 duration family.

    Three disjoint duration families are supported and never converted across
    family boundaries: elapsed time (``PT...H/M/S``), calendar weeks and days
    (``P...W/D``), and calendar years and months (``P...Y/M``).
    """

    family: FrequencyFamily
    value: int
    unit: FrequencyUnit
    canonical: str

    def __post_init__(self) -> None:
        if not isinstance(self.family, FrequencyFamily):
            raise ValueError(f"Unsupported frequency family: {self.family!r}")
        if not isinstance(self.unit, FrequencyUnit):
            raise ValueError(f"Unsupported frequency unit: {self.unit!r}")
        if type(self.value) is not int or self.value <= 0:
            raise ValueError(f"Frequency value must be a positive integer, got {self.value!r}")
        if not isinstance(self.canonical, str):
            raise ValueError(f"Canonical spelling must be a string, got {self.canonical!r}")
        expected_value, expected_unit, expected_canonical = _canonical_parts(self.family, self.value, self.unit)
        if (self.value, self.unit, self.canonical) != (expected_value, expected_unit, expected_canonical):
            raise ValueError(
                "Non-canonical Frequency components: "
                f"expected {(expected_value, expected_unit, expected_canonical)!r}, "
                f"got {(self.value, self.unit, self.canonical)!r}"
            )

    def __str__(self) -> str:
        return self.canonical

    @classmethod
    def parse(cls, raw: object) -> Frequency:
        """Parse and canonicalize an ISO 8601 duration string.

        Parameters
        ----------
        raw : object
            Candidate ISO 8601 duration string within one supported family.

        Returns
        -------
        Frequency
            Canonicalized frequency reduced to the largest exact whole-number unit
            within its family.

        Raises
        ------
        ValueError
            If ``raw`` is not a valid positive duration within a single
            supported family.
        """
        if not isinstance(raw, str):
            raise ValueError(
                "Unsupported frequency value: expected an ISO 8601 duration string such as "
                f"'PT15M', 'PT1H', 'P1D', 'P1W', 'P1M', or 'P1Y'; got {type(raw).__name__}"
            )

        if (match := _ELAPSED_RE.fullmatch(raw)) is not None and any(g is not None for g in match.groups()):
            family = FrequencyFamily.ELAPSED
            value, unit, canonical = _reduce_elapsed(
                _parse_optional_int(match.group(1)),
                _parse_optional_int(match.group(2)),
                _parse_optional_int(match.group(3)),
            )
            return cls(family=family, value=value, unit=unit, canonical=canonical)

        if (match := _CALENDAR_DAYS_RE.fullmatch(raw)) is not None and any(g is not None for g in match.groups()):
            family = FrequencyFamily.CALENDAR_DAYS
            value, unit, canonical = _reduce_days(
                _parse_optional_int(match.group(1)),
                _parse_optional_int(match.group(2)),
            )
            return cls(family=family, value=value, unit=unit, canonical=canonical)

        if (match := _CALENDAR_MONTHS_RE.fullmatch(raw)) is not None and any(g is not None for g in match.groups()):
            family = FrequencyFamily.CALENDAR_MONTHS
            value, unit, canonical = _reduce_months(
                _parse_optional_int(match.group(1)),
                _parse_optional_int(match.group(2)),
            )
            return cls(family=family, value=value, unit=unit, canonical=canonical)

        raise ValueError(
            f"Unsupported frequency {raw!r}. Use a positive ISO 8601 duration in one family, "
            "such as 'PT15M', 'PT1H', 'P1D', 'P1W', 'P1M', or 'P1Y'."
        )


DAILY = Frequency.parse("P1D")
MONTHLY = Frequency.parse("P1M")


def canonicalize_frequency(raw: object) -> str:
    """Return the canonical ISO 8601 duration spelling for ``raw``."""
    return Frequency.parse(raw).canonical
