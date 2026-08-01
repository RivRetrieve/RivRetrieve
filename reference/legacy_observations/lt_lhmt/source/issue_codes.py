from __future__ import annotations

from enum import StrEnum


class LtLhmtObservationIssueCodes(StrEnum):
    MISSING_DATA = "missing_data"
    PARTIAL_RESPONSE = "partial_response"
    SOURCE_REQUEST_FAILED = "source_request_failed"
    INVALID_NUMERIC_VALUE = "invalid_numeric_value"
    TIMEZONE_AMBIGUITY = "timezone_ambiguity"
    DATE_ONLY_TIMESTAMP = "date_only_timestamp"
    HTTP_NOT_FOUND = "http_not_found"
