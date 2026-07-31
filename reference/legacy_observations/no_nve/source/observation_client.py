from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

import requests

BASE_URL = "https://hydapi.nve.no/api/v1/"
STATIONS_URL = f"{BASE_URL}Stations"
OBSERVATIONS_URL = f"{BASE_URL}Observations"


@dataclass(frozen=True)
class NoNveTransportRequest:
    url: str
    headers: dict[str, str]
    params: dict[str, str | int | float]
    timeout_seconds: float


@dataclass(frozen=True)
class NoNveTransportResponse:
    content: bytes
    status_code: int
    retrieved_at: datetime


def _default_transport(request: NoNveTransportRequest) -> NoNveTransportResponse:
    resp = requests.get(
        request.url,
        headers=request.headers,
        params=request.params,  # type: ignore[arg-type]
        timeout=request.timeout_seconds,
    )
    resp.raise_for_status()
    return NoNveTransportResponse(
        content=resp.content,
        status_code=resp.status_code,
        retrieved_at=datetime.now(UTC),
    )


@dataclass
class NoNveObservationClient:
    """HTTP client for the NVE HydAPI.

    The API key is read from NVE_API_KEY unless supplied directly.
    Credentials are never written to provenance or raw metadata.
    """

    api_key: str | None = field(default=None)
    timeout_seconds: float = field(default=60.0)
    transport: Callable[[NoNveTransportRequest], NoNveTransportResponse] | None = field(default=None)

    def __post_init__(self) -> None:
        if self.api_key is None:
            self.api_key = os.environ.get("NVE_API_KEY")

    def has_credentials(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "X-API-Key": self.api_key or "",
        }

    def fetch_observations(
        self,
        station_id: str,
        parameter_id: int,
        resolution_time: int,
        reference_time: str,
    ) -> NoNveTransportResponse:
        """Fetch observations from NVE HydAPI Observations endpoint.

        reference_time is an ISO 8601 interval string, e.g. '2023-01-01/2023-12-31'.
        """
        params: dict[str, str | int | float] = {
            "StationId": station_id,
            "Parameter": parameter_id,
            "ResolutionTime": resolution_time,
            "ReferenceTime": reference_time,
        }
        req = NoNveTransportRequest(
            url=OBSERVATIONS_URL,
            headers=self._headers(),
            params=params,
            timeout_seconds=self.timeout_seconds,
        )
        transport = self.transport or _default_transport
        return transport(req)

    def endpoint_for(
        self,
        station_id: str,
        parameter_id: int,
        resolution_time: int,
        reference_time: str,
    ) -> str:
        return (
            f"{OBSERVATIONS_URL}"
            f"?StationId={station_id}"
            f"&Parameter={parameter_id}"
            f"&ResolutionTime={resolution_time}"
            f"&ReferenceTime={reference_time}"
        )
