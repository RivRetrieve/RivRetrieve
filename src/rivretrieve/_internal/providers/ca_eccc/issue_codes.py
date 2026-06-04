from __future__ import annotations

from enum import StrEnum


class CaEcccObservationIssueCodes(StrEnum):
    SOURCE_REQUEST_FAILED = "source_request_failed"
    HTTP_NOT_FOUND = "http_not_found"
    MISSING_DATA = "missing_data"
    PARTIAL_RESPONSE = "partial_response"
    DATE_ONLY_TIMESTAMP = "date_only_timestamp"
    PARSE_ERROR = "parse_error"
    # HYDAT-specific
    HYDAT_DOWNLOAD_STARTED = "hydat_download_started"
    HYDAT_DOWNLOAD_FAILED = "hydat_download_failed"
    HYDAT_NOT_AVAILABLE = "hydat_not_available"
    HYDAT_STALE = "hydat_stale"
