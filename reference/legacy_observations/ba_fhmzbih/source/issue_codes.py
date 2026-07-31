from __future__ import annotations

from enum import StrEnum


class BaFhmzbihObservationIssueCodes(StrEnum):
    MISSING_DATA = "missing_data"
    PARTIAL_RESPONSE = "partial_response"
    SOURCE_REQUEST_FAILED = "source_request_failed"
    HTTP_NOT_FOUND = "http_not_found"
    INVALID_ROW = "invalid_row"
    STATION_GROUP_NOT_FOUND = "station_group_not_found"
    TIMEZONE_LOCAL_TO_UTC = "timezone_local_to_utc"
    REQUESTED_RANGE_BEYOND_WINDOW = "requested_range_beyond_window"
