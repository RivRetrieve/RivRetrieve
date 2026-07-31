from __future__ import annotations

from enum import StrEnum


class PlImgwObservationIssueCodes(StrEnum):
    MISSING_DATA = "missing_data"
    PARTIAL_RESPONSE = "partial_response"
    SOURCE_REQUEST_FAILED = "source_request_failed"
    HTTP_NOT_FOUND = "http_not_found"
    INVALID_ROW = "invalid_row"
    DATE_ONLY_TIMESTAMP = "date_only_timestamp"
