from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

import requests

BASE_URL = "https://www.dws.gov.za/Hydrology/Verified/HyData.aspx"
CATALOGUE_URL = "https://www.dws.gov.za/hydrology/Verified/HyCatalogue.aspx"
VARIABLE_CODE = "100.00"


@dataclass(frozen=True)
class ZaDwsTransportRequest:
    url: str
    timeout_seconds: float


@dataclass(frozen=True)
class ZaDwsTransportResponse:
    content: str
    status_code: int
    retrieved_at: datetime


def _default_transport(req: ZaDwsTransportRequest) -> ZaDwsTransportResponse:
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(req.url, headers=headers, timeout=req.timeout_seconds)
    return ZaDwsTransportResponse(
        content=response.text,
        status_code=response.status_code,
        retrieved_at=datetime.now(UTC),
    )


@dataclass
class ZaDwsObservationClient:
    """HTTP client for the DWS Verified Hydrology portal (South Africa).

    No authentication is required. The portal serves HTML responses with
    a ``<pre>`` block containing whitespace-delimited records.
    """

    timeout_seconds: float = field(default=60.0)
    transport: Callable[[ZaDwsTransportRequest], ZaDwsTransportResponse] | None = field(default=None)

    def fetch(
        self,
        station_id: str,
        data_type: str,
        start_date: date,
        end_date: date,
    ) -> ZaDwsTransportResponse:
        """Fetch observation data for one station/data_type/window.

        Args:
            station_id: DWS station code (e.g. ``"X3H001"``).
            data_type: ``"Daily"`` for daily means or ``"Point"`` for sub-daily readings.
            start_date: Inclusive window start.
            end_date: Inclusive window end.
        """
        url = (
            f"{BASE_URL}?Station={station_id}{VARIABLE_CODE}"
            f"&DataType={data_type}"
            f"&StartDT={start_date.isoformat()}"
            f"&EndDT={end_date.isoformat()}"
            f"&SiteType=RIV"
        )
        transport = self.transport or _default_transport
        return transport(ZaDwsTransportRequest(url=url, timeout_seconds=self.timeout_seconds))
