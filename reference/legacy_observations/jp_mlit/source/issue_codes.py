from __future__ import annotations

from enum import StrEnum


class JpMlitObservationIssueCodes(StrEnum):
    MISSING_DATA = "missing_data"
    PARTIAL_RESPONSE = "partial_response"
    SOURCE_REQUEST_FAILED = "source_request_failed"
    NO_DAT_LINK = "no_dat_link"
    INVALID_DAT_CONTENT = "invalid_dat_content"
    DATE_ONLY_TIMESTAMP = "date_only_timestamp"
    TIMEZONE_LOCAL_TO_UTC = "timezone_local_to_utc"
    HTTP_NOT_FOUND = "http_not_found"
