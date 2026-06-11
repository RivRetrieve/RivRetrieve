from __future__ import annotations

from enum import StrEnum


class ZaDwsObservationIssueCodes(StrEnum):
    MISSING_DATA = "missing_data"
    PARTIAL_RESPONSE = "partial_response"
    HTTP_NOT_FOUND = "http_not_found"
    INVALID_ROW = "invalid_row"
    TIMEZONE_LOCAL_TO_UTC = "timezone_local_to_utc"
    DATE_ONLY_TIMESTAMP = "date_only_timestamp"
    SOURCE_REQUEST_FAILED = "source_request_failed"
