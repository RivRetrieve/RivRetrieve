from __future__ import annotations

from enum import StrEnum


class NoNveObservationIssueCodes(StrEnum):
    HTTP_NOT_FOUND = "http_not_found"
    SOURCE_REQUEST_FAILED = "source_request_failed"
    MISSING_DATA = "missing_data"
    SOURCE_QUALITY_CODE = "source_quality_code"
    SOURCE_CORRECTION_CODE = "source_correction_code"
