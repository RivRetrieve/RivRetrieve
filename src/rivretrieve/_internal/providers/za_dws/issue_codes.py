from __future__ import annotations

from enum import StrEnum


class ZaDwsObservationIssueCodes(StrEnum):
    HTTP_NOT_FOUND = "http_not_found"
    SOURCE_REQUEST_FAILED = "source_request_failed"
    NO_DATA_FOR_PERIOD = "no_data_for_period"
    SENTINEL_MISSING_VALUE = "sentinel_missing_value"
    SOURCE_QUALITY_CODE = "source_quality_code"
