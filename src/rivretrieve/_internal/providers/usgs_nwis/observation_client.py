from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import requests

DV_BASE_URL = "https://waterservices.usgs.gov/nwis/dv/"
IV_BASE_URL = "https://waterservices.usgs.gov/nwis/iv/"


@dataclass(frozen=True)
class UsgsNwisTransportRequest:
    url: str
    headers: dict[str, str]
    timeout_seconds: float


@dataclass(frozen=True)
class UsgsNwisTransportResponse:
    content: bytes
    status_code: int
    retrieved_at: datetime


@dataclass(frozen=True)
class UsgsNwisObservationClient:
    dv_base_url: str = DV_BASE_URL
    iv_base_url: str = IV_BASE_URL
    timeout_seconds: float = 30.0
    transport: Callable[[UsgsNwisTransportRequest], UsgsNwisTransportResponse] | None = None

    def fetch_dv(
        self,
        site_no: str,
        param_code: str,
        stat_code: str,
        start: str,
        end: str,
    ) -> UsgsNwisTransportResponse:
        url = self.dv_endpoint_for(site_no, param_code, stat_code, start, end)
        return self._fetch(url)

    def fetch_iv(
        self,
        site_no: str,
        param_code: str,
        start: str,
        end: str,
    ) -> UsgsNwisTransportResponse:
        url = self.iv_endpoint_for(site_no, param_code, start, end)
        return self._fetch(url)

    def dv_endpoint_for(
        self,
        site_no: str,
        param_code: str,
        stat_code: str,
        start: str,
        end: str,
    ) -> str:
        return (
            f"{self.dv_base_url}?format=json"
            f"&sites={site_no}"
            f"&startDT={start}&endDT={end}"
            f"&parameterCd={param_code}&statCd={stat_code}"
        )

    def iv_endpoint_for(
        self,
        site_no: str,
        param_code: str,
        start: str,
        end: str,
    ) -> str:
        return f"{self.iv_base_url}?format=json&sites={site_no}&startDT={start}&endDT={end}&parameterCd={param_code}"

    def _fetch(self, url: str) -> UsgsNwisTransportResponse:
        request = UsgsNwisTransportRequest(
            url=url,
            headers={"Accept": "application/json"},
            timeout_seconds=self.timeout_seconds,
        )
        transport = self.transport or _default_transport
        return transport(request)


def _default_transport(request: UsgsNwisTransportRequest) -> UsgsNwisTransportResponse:
    response = requests.get(
        request.url,
        headers=request.headers,
        timeout=request.timeout_seconds,
    )
    response.raise_for_status()
    return UsgsNwisTransportResponse(
        content=response.content,
        status_code=response.status_code,
        retrieved_at=datetime.now(UTC),
    )
