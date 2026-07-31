from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import requests

BASE_URL = "https://api-v3.thaiwater.net/api/v1/thaiwater30/public"
GRAPH_URL = f"{BASE_URL}/waterlevel_graph"
METADATA_URL = f"{BASE_URL}/waterlevel_load"


@dataclass(frozen=True)
class ThThaiWaterTransportRequest:
    url: str
    params: dict[str, str]
    timeout_seconds: float


@dataclass(frozen=True)
class ThThaiWaterTransportResponse:
    content: bytes
    status_code: int
    retrieved_at: datetime


@dataclass(frozen=True)
class ThThaiWaterObservationClient:
    timeout_seconds: float = 60.0
    transport: Callable[[ThThaiWaterTransportRequest], ThThaiWaterTransportResponse] | None = None

    def fetch(self, station_id: str, start_date: str, end_date: str) -> ThThaiWaterTransportResponse:
        params = {
            "station_type": "tele_waterlevel",
            "station_id": station_id,
            "start_date": start_date,
            "end_date": end_date,
        }
        request = ThThaiWaterTransportRequest(url=GRAPH_URL, params=params, timeout_seconds=self.timeout_seconds)
        transport = self.transport or _default_transport
        return transport(request)

    def endpoint_for(self, station_id: str, start_date: str, end_date: str) -> str:
        return (
            f"{GRAPH_URL}?station_type=tele_waterlevel"
            f"&station_id={station_id}&start_date={start_date}&end_date={end_date}"
        )


def _default_transport(request: ThThaiWaterTransportRequest) -> ThThaiWaterTransportResponse:
    response = requests.get(request.url, params=request.params, timeout=request.timeout_seconds)
    response.raise_for_status()
    return ThThaiWaterTransportResponse(
        content=response.content,
        status_code=response.status_code,
        retrieved_at=datetime.now(UTC),
    )
