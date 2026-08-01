from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import requests

DAILY_URL_TEMPLATE = "https://opendata.chmi.cz/hydrology/historical/data/daily/H_{station_id}_DQ_{year}.json"
HOURLY_URL_TEMPLATE = "https://opendata.chmi.cz/hydrology/historical/data/hourly/H_{station_id}_HQ_{year}.json"


@dataclass(frozen=True)
class CzChmiTransportRequest:
    url: str
    timeout_seconds: float


@dataclass(frozen=True)
class CzChmiTransportResponse:
    content: bytes
    status_code: int
    retrieved_at: datetime


@dataclass(frozen=True)
class CzChmiObservationClient:
    timeout_seconds: float = 30.0
    transport: Callable[[CzChmiTransportRequest], CzChmiTransportResponse] | None = None

    def fetch(self, station_id: str, year: int, url_type: str) -> CzChmiTransportResponse:
        url = self._url_for(station_id, year, url_type)
        request = CzChmiTransportRequest(url=url, timeout_seconds=self.timeout_seconds)
        transport = self.transport or _default_transport
        return transport(request)

    def endpoint_for(self, station_id: str, year: int, url_type: str) -> str:
        return self._url_for(station_id, year, url_type)

    def _url_for(self, station_id: str, year: int, url_type: str) -> str:
        if url_type == "daily":
            return DAILY_URL_TEMPLATE.format(station_id=station_id, year=year)
        if url_type == "hourly":
            return HOURLY_URL_TEMPLATE.format(station_id=station_id, year=year)
        raise ValueError(f"Unknown url_type: {url_type!r}")


def _default_transport(request: CzChmiTransportRequest) -> CzChmiTransportResponse:
    response = requests.get(request.url, timeout=request.timeout_seconds)
    response.raise_for_status()
    return CzChmiTransportResponse(
        content=response.content,
        status_code=response.status_code,
        retrieved_at=datetime.now(UTC),
    )
