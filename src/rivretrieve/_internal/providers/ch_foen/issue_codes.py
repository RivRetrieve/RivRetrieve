from __future__ import annotations

from enum import StrEnum


class ChFoenObservationIssueCodes(StrEnum):
    OBSERVATIONS_NOT_YET_IMPLEMENTED = "observations_not_yet_implemented"
    MISSING_DATA = "missing_data"
    PARTIAL_RESPONSE = "partial_response"
    SOURCE_REQUEST_FAILED = "source_request_failed"
    GAP = "gap"
    OVERLAP = "overlap"
    CONFLICT = "conflict"
    UNIT_CONVERSION_AMBIGUITY = "unit_conversion_ambiguity"
    TIMEZONE_AMBIGUITY = "timezone_ambiguity"
    INVALID_TIMESTAMP = "invalid_timestamp"
    INVALID_NUMERIC_VALUE = "invalid_numeric_value"


class ChFoenParserFatalCodes(StrEnum):
    MALFORMED_CSV = "malformed_csv"
    MISSING_REQUIRED_COLUMN = "missing_required_column"
