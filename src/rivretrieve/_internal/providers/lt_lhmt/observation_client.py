from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import requests

DATA_URL_TEMPLATE = "https://api.meteo.lt/v1/hydro-stations/{station_id}/observations/historical/{year_month}"


@dataclass(frozen=True)
class LtLhmtTransportRequest:
    url: str
    headers: dict[str, str]
    timeout_seconds: float


@dataclass(frozen=True)
class LtLhmtTransportResponse:
    content: bytes
    status_code: int
    retrieved_at: datetime


@dataclass(frozen=True)
class LtLhmtObservationClient:
    base_url: str = "https://api.meteo.lt/v1/hydro-stations"
    timeout_seconds: float = 20.0
    transport: Callable[[LtLhmtTransportRequest], LtLhmtTransportResponse] | None = None

    def fetch(self, station_id: str, year_month: str) -> LtLhmtTransportResponse:
        url = f"{self.base_url}/{station_id}/observations/historical/{year_month}"
        request = LtLhmtTransportRequest(
            url=url,
            headers={"Accept": "application/json"},
            timeout_seconds=self.timeout_seconds,
        )
        transport = self.transport or _default_transport
        return transport(request)

    def endpoint_for(self, station_id: str, year_month: str) -> str:
        return f"{self.base_url}/{station_id}/observations/historical/{year_month}"


def _default_transport(request: LtLhmtTransportRequest) -> LtLhmtTransportResponse:
    response = requests.get(
        request.url,
        headers=request.headers,
        timeout=request.timeout_seconds,
    )
    response.raise_for_status()
    return LtLhmtTransportResponse(
        content=response.content,
        status_code=response.status_code,
        retrieved_at=datetime.now(UTC),
    )
