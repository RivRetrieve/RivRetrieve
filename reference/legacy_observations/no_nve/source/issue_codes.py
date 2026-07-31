from __future__ import annotations

from enum import StrEnum


class NoNveObservationIssueCodes(StrEnum):
    AUTH_MISSING = "auth_missing"
    AUTH_FAILED = "auth_failed"
    SOURCE_REQUEST_FAILED = "source_request_failed"
    HTTP_NOT_FOUND = "http_not_found"
    MISSING_DATA = "missing_data"
    PARTIAL_RESPONSE = "partial_response"
    DATE_ONLY_TIMESTAMP = "date_only_timestamp"
    TIMEZONE_LOCAL_TO_UTC = "timezone_local_to_utc"
    PARSE_ERROR = "parse_error"
