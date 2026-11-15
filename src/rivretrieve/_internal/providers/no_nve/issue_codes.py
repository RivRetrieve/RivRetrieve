from __future__ import annotations

from enum import StrEnum


class NoNveObservationIssueCodes(StrEnum):
    HTTP_NOT_FOUND = "http_not_found"
    SOURCE_REQUEST_FAILED = "source_request_failed"
    MISSING_DATA = "missing_data"
