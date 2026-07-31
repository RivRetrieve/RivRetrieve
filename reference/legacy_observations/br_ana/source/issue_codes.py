from __future__ import annotations

from enum import StrEnum


class BrAnaObservationIssueCodes(StrEnum):
    MISSING_DATA = "missing_data"
    PARTIAL_RESPONSE = "partial_response"
    SOURCE_REQUEST_FAILED = "source_request_failed"
    DATE_ONLY_TIMESTAMP = "date_only_timestamp"
    NAIVE_LOCAL_TIMESTAMP = "naive_local_timestamp"
    HTTP_NOT_FOUND = "http_not_found"
    AUTH_MISSING = "auth_missing"
    AUTH_FAILED = "auth_failed"
