from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import requests

BASE_URL = "http://www1.river.go.jp"
DSP_URL = f"{BASE_URL}/cgi-bin/DspWaterData.exe"

_DAT_LINK_PATTERN = re.compile(r'href="(/dat/dload/download/[^"]+)"', re.IGNORECASE)
_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": BASE_URL}


@dataclass(frozen=True)
class JpMlitTransportRequest:
    url: str
    params: dict[str, str | int | None] | None
    timeout_seconds: float


@dataclass(frozen=True)
class JpMlitTransportResponse:
    content: bytes
    status_code: int
    retrieved_at: datetime


@dataclass(frozen=True)
class JpMlitDatResponse:
    """Holds the decoded Shift-JIS .dat content for one window."""

    dat_content: str
    html_url: str
    dat_url: str | None
    retrieved_at: datetime


@dataclass(frozen=True)
class JpMlitObservationClient:
    timeout_seconds: float = 60.0
    transport: Callable[[JpMlitTransportRequest], JpMlitTransportResponse] | None = None

    def fetch_html(
        self,
        station_id: str,
        kind: int,
        begin_date: str,
        end_date: str,
    ) -> JpMlitTransportResponse:
        """Fetch the DspWaterData HTML page for a station/kind/window."""
        params: dict[str, str | int | None] = {
            "KIND": kind,
            "ID": station_id,
            "BGNDATE": begin_date,
            "ENDDATE": end_date,
            "KAWABOU": "NO",
        }
        request = JpMlitTransportRequest(
            url=DSP_URL,
            params=params,
            timeout_seconds=self.timeout_seconds,
        )
        transport = self.transport or _default_transport
        return transport(request)

    def fetch_dat(self, dat_path: str) -> JpMlitTransportResponse:
        """Fetch a .dat file from its path relative to BASE_URL."""
        dat_url = f"{BASE_URL}{dat_path}"
        request = JpMlitTransportRequest(
            url=dat_url,
            params=None,
            timeout_seconds=self.timeout_seconds,
        )
        transport = self.transport or _default_transport
        return transport(request)

    def fetch_observation_window(
        self,
        station_id: str,
        kind: int,
        begin_date: str,
        end_date: str,
    ) -> JpMlitDatResponse:
        """Fetch HTML page then follow the .dat link; returns decoded Shift-JIS content."""
        html_url = _build_html_url(station_id, kind, begin_date, end_date)
        html_resp = self.fetch_html(station_id, kind, begin_date, end_date)

        # Decode HTML as EUC-JP to find .dat link.
        html_text = html_resp.content.decode("euc-jp", errors="replace")
        match = _DAT_LINK_PATTERN.search(html_text)
        if match is None:
            return JpMlitDatResponse(
                dat_content="",
                html_url=html_url,
                dat_url=None,
                retrieved_at=html_resp.retrieved_at,
            )

        dat_path = match.group(1)
        dat_resp = self.fetch_dat(dat_path)
        dat_content = dat_resp.content.decode("shift_jis", errors="replace")

        return JpMlitDatResponse(
            dat_content=dat_content,
            html_url=html_url,
            dat_url=f"{BASE_URL}{dat_path}",
            retrieved_at=dat_resp.retrieved_at,
        )


def _build_html_url(station_id: str, kind: int, begin_date: str, end_date: str) -> str:
    return f"{DSP_URL}?KIND={kind}&ID={station_id}&BGNDATE={begin_date}&ENDDATE={end_date}&KAWABOU=NO"


def _default_transport(request: JpMlitTransportRequest) -> JpMlitTransportResponse:
    response = requests.get(
        request.url,
        params=request.params,
        timeout=request.timeout_seconds,
        headers=_HEADERS,
    )
    response.raise_for_status()
    return JpMlitTransportResponse(
        content=response.content,
        status_code=response.status_code,
        retrieved_at=datetime.now(UTC),
    )
