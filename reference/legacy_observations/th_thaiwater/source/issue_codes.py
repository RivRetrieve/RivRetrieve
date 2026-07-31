from __future__ import annotations

from enum import StrEnum


class ThThaiWaterObservationIssueCodes(StrEnum):
    MISSING_DATA = "missing_data"
    PARTIAL_RESPONSE = "partial_response"
    SOURCE_REQUEST_FAILED = "source_request_failed"
    INVALID_NUMERIC_VALUE = "invalid_numeric_value"
    TIMEZONE_LOCAL_TO_UTC = "timezone_local_to_utc"
    HTTP_NOT_FOUND = "http_not_found"
