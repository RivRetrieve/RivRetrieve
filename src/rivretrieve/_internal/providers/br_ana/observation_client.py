from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

import requests

AUTH_URL = "https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/OAUth/v1"
DISCHARGE_URL = "https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/HidroSerieVazao/v1"
STAGE_URL = "https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/HidroSerieCotas/v1"

# Pre-encoded Portuguese parameter names used by the ANA Hidroweb API.
# The API requires these exact percent-encoded forms; passing them via
# requests.get(params=dict) would double-encode them.
_ENCODED_STATION_PARAM = "C%C3%B3digo%20da%20Esta%C3%A7%C3%A3o"
_ENCODED_FILTER_TYPE_PARAM = "Tipo%20Filtro%20Data"
_ENCODED_START_PARAM = "Data%20Inicial%20(yyyy-MM-dd)"
_ENCODED_END_PARAM = "Data%20Final%20(yyyy-MM-dd)"

# Token is valid for 60 minutes per ANA documentation; we cache for 55 min to be safe.
_TOKEN_TTL_SECONDS = 3300.0


@dataclass(frozen=True)
class BrAnaTransportRequest:
    url: str
    headers: dict[str, str]
    timeout_seconds: float


@dataclass(frozen=True)
class BrAnaTransportResponse:
    content: bytes
    status_code: int
    retrieved_at: datetime


def _default_transport(request: BrAnaTransportRequest) -> BrAnaTransportResponse:
    response = requests.get(
        request.url,
        headers=request.headers,
        timeout=request.timeout_seconds,
    )
    response.raise_for_status()
    return BrAnaTransportResponse(
        content=response.content,
        status_code=response.status_code,
        retrieved_at=datetime.now(UTC),
    )


@dataclass
class BrAnaObservationClient:
    """HTTP client for ANA Hidroweb with token management.

    Credentials are read from ANA_IDENTIFICADOR / ANA_SENHA env vars unless
    supplied directly.  These names match the actual API header parameters
    and the R hydrodownloadR convention.
    The token is fetched lazily and cached for its TTL.
    Credentials are NEVER written to provenance or raw metadata.
    """

    username: str | None = field(default=None)
    password: str | None = field(default=None)
    timeout_seconds: float = field(default=60.0)
    transport: Callable[[BrAnaTransportRequest], BrAnaTransportResponse] | None = field(default=None)

    # Mutable state for token caching — not part of the frozen contract.
    _token: str | None = field(default=None, init=False, repr=False, compare=False)
    _token_expiry: float = field(default=0.0, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.username is None:
            self.username = os.environ.get("ANA_IDENTIFICADOR")
        if self.password is None:
            self.password = os.environ.get("ANA_SENHA")

    def has_credentials(self) -> bool:
        return bool(self.username and self.password)

    def fetch_token(self) -> str | None:
        """Return a valid cached token or fetch a new one. Returns None on failure."""
        if self._token and time.monotonic() < self._token_expiry:
            return self._token

        if not self.has_credentials():
            return None

        request = BrAnaTransportRequest(
            url=AUTH_URL,
            headers={
                "accept": "*/*",
                "Identificador": self.username or "",
                "Senha": self.password or "",
            },
            timeout_seconds=self.timeout_seconds,
        )
        transport = self.transport or _default_transport
        try:
            response = transport(request)
        except (requests.RequestException, OSError, TimeoutError):
            return None

        import json

        try:
            data = json.loads(response.content)
        except (json.JSONDecodeError, ValueError):
            return None

        if not isinstance(data, dict):
            return None

        items = data.get("items")
        if not isinstance(items, dict):
            return None
        token = items.get("tokenautenticacao")
        if not isinstance(token, str) or not token.strip():
            return None

        self._token = token
        self._token_expiry = time.monotonic() + _TOKEN_TTL_SECONDS
        return self._token

    def fetch_data(
        self,
        station_id: str,
        product_id: str,
        start_date: str,
        end_date: str,
        token: str,
    ) -> BrAnaTransportResponse:
        base_url = DISCHARGE_URL if product_id == "discharge_daily_mean" else STAGE_URL
        url = (
            f"{base_url}"
            f"?{_ENCODED_STATION_PARAM}={station_id}"
            f"&{_ENCODED_FILTER_TYPE_PARAM}=DATA_LEITURA"
            f"&{_ENCODED_START_PARAM}={start_date}"
            f"&{_ENCODED_END_PARAM}={end_date}"
        )
        request = BrAnaTransportRequest(
            url=url,
            headers={"accept": "*/*", "Authorization": f"Bearer {token}"},
            timeout_seconds=self.timeout_seconds,
        )
        transport = self.transport or _default_transport
        return transport(request)

    def endpoint_for(self, station_id: str, product_id: str, start_date: str, end_date: str) -> str:
        base_url = DISCHARGE_URL if product_id == "discharge_daily_mean" else STAGE_URL
        return (
            f"{base_url}"
            f"?{_ENCODED_STATION_PARAM}={station_id}"
            f"&{_ENCODED_FILTER_TYPE_PARAM}=DATA_LEITURA"
            f"&{_ENCODED_START_PARAM}={start_date}"
            f"&{_ENCODED_END_PARAM}={end_date}"
        )
