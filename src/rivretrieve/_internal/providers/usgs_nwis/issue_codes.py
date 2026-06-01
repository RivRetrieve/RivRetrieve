from __future__ import annotations

from enum import StrEnum


class UsgsNwisObservationIssueCodes(StrEnum):
    MISSING_DATA = "missing_data"
    PARTIAL_RESPONSE = "partial_response"
    SOURCE_REQUEST_FAILED = "source_request_failed"
    INVALID_NUMERIC_VALUE = "invalid_numeric_value"
    NO_DATA_VALUE = "no_data_value"
    TIMEZONE_CONVERSION = "timezone_conversion"
    HTTP_NOT_FOUND = "http_not_found"
