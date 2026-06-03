from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import requests

OBS_ELAB_URL = "https://hubeau.eaufrance.fr/api/v2/hydrometrie/obs_elab"
OBS_TR_URL = "https://hubeau.eaufrance.fr/api/v2/hydrometrie/observations_tr"
TEMPERATURE_URL = "https://hubeau.eaufrance.fr/api/v1/temperature/chronique"
TEMPERATURE_STATIONS_URL = "https://hubeau.eaufrance.fr/api/v1/temperature/station"

# Kept for backward-compat import; primary base URL is now per-endpoint.
BASE_URL = OBS_ELAB_URL


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

    # ---- obs_elab (daily elaborated) ----------------------------------------

    def initial_params_obs_elab(
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

    def endpoint_for_obs_elab(self, station_id: str, grandeur: str, start_date: str, end_date: str) -> str:
        return (
            f"{OBS_ELAB_URL}?code_entite={station_id}"
            f"&date_debut_obs={start_date}&date_fin_obs={end_date}"
            f"&grandeur_hydro={grandeur}&size=20000"
        )

    # ---- observations_tr (real-time / instantaneous) ------------------------

    def initial_params_obs_tr(
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

    def endpoint_for_obs_tr(self, station_id: str, grandeur: str, start_date: str, end_date: str) -> str:
        return (
            f"{OBS_TR_URL}?code_entite={station_id}"
            f"&date_debut_obs={start_date}&date_fin_obs={end_date}"
            f"&grandeur_hydro={grandeur}&size=20000"
        )

    # ---- temperature chronique ----------------------------------------------

    def initial_params_temperature(
        self,
        station_id: str,
        start_date: str,
        end_date: str,
    ) -> dict[str, object]:
        return {
            "code_station": station_id,
            "date_debut_mesure": start_date,
            "date_fin_mesure": end_date,
            "size": 20000,
        }

    def endpoint_for_temperature(self, station_id: str, start_date: str, end_date: str) -> str:
        return (
            f"{TEMPERATURE_URL}?code_station={station_id}"
            f"&date_debut_mesure={start_date}&date_fin_mesure={end_date}&size=20000"
        )

    # ---- legacy shim kept for backward-compat with existing tests -----------

    def initial_params(
        self,
        station_id: str,
        grandeur: str,
        start_date: str,
        end_date: str,
    ) -> dict[str, object]:
        return self.initial_params_obs_elab(station_id, grandeur, start_date, end_date)

    def endpoint_for(self, station_id: str, grandeur: str, start_date: str, end_date: str) -> str:
        return self.endpoint_for_obs_elab(station_id, grandeur, start_date, end_date)


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
