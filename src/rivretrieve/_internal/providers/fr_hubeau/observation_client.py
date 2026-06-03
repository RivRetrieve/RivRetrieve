from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import requests

BASE_URL = "https://hubeau.eaufrance.fr/api/v2/hydrometrie/obs_elab"


@dataclass(frozen=True)
class FrHubeauTransportRequest:
    url: str
    params: dict[str, object] | None
    timeout_seconds: float


@dataclass(frozen=True)
class FrHubeauTransportResponse:
    content: bytes
    status_code: int
    retrieved_at: datetime


@dataclass(frozen=True)
class FrHubeauObservationClient:
    timeout_seconds: float = 60.0
    transport: Callable[[FrHubeauTransportRequest], FrHubeauTransportResponse] | None = None

    def fetch(
        self,
        url: str,
        params: dict[str, object] | None,
    ) -> FrHubeauTransportResponse:
        request = FrHubeauTransportRequest(
            url=url,
            params=params,
            timeout_seconds=self.timeout_seconds,
        )
        transport = self.transport or _default_transport
        return transport(request)

    def initial_params(
        self,
        station_id: str,
        grandeur: str,
        start_date: str,
        end_date: str,
    ) -> dict[str, object]:
        return {
            "code_entite": station_id,
            "date_debut_obs": start_date,
            "date_fin_obs": end_date,
            "grandeur_hydro": grandeur,
            "size": 20000,
        }

    def endpoint_for(self, station_id: str, grandeur: str, start_date: str, end_date: str) -> str:
        return (
            f"{BASE_URL}?code_entite={station_id}"
            f"&date_debut_obs={start_date}&date_fin_obs={end_date}"
            f"&grandeur_hydro={grandeur}&size=20000"
        )


def _default_transport(request: FrHubeauTransportRequest) -> FrHubeauTransportResponse:
    response = requests.get(
        request.url,
        params=request.params,
        timeout=request.timeout_seconds,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    response.raise_for_status()
    return FrHubeauTransportResponse(
        content=response.content,
        status_code=response.status_code,
        retrieved_at=datetime.now(UTC),
    )
