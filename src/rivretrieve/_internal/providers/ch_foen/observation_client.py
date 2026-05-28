from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import requests

_EMBEDDED_PUBLIC_TOKEN = "0yLbh-D7RMe1sX1iIudFel8CcqCI8sVfuRTaliUp56MgE6kub8-nSd05_EJ4zTTKt0lUzw8zcO73zL9QhC3jtA=="


@dataclass(frozen=True)
class ChFoenTransportRequest:
    endpoint: str
    query: str
    headers: dict[str, str]
    timeout_seconds: float


@dataclass(frozen=True)
class ChFoenTransportResponse:
    content: bytes
    status_code: int | None
    retrieved_at: datetime


@dataclass(frozen=True)
class ChFoenObservationClient:
    token: str | None = None
    endpoint: str = "https://influx.konzept.space/api/v2/query?org=api.existenz.ch"
    timeout_seconds: float = 60.0
    transport: Callable[[ChFoenTransportRequest], ChFoenTransportResponse] | None = None

    def fetch(self, query: str) -> ChFoenTransportResponse:
        request = ChFoenTransportRequest(
            endpoint=self.endpoint,
            query=query,
            headers={
                "Authorization": f"Token {self.resolved_token}",
                "Accept": "application/csv",
                "Content-type": "application/vnd.flux",
            },
            timeout_seconds=self.timeout_seconds,
        )
        transport = self.transport or _default_transport
        return transport(request)

    @property
    def resolved_token(self) -> str:
        if self.token is not None:
            return self.token
        return os.environ.get("CH_FOEN_INFLUX_TOKEN") or _EMBEDDED_PUBLIC_TOKEN

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}("
            f"endpoint={self.endpoint!r}, "
            "token='<redacted>', "
            f"timeout_seconds={self.timeout_seconds!r}, "
            f"transport={self.transport!r})"
        )


def _default_transport(request: ChFoenTransportRequest) -> ChFoenTransportResponse:
    response = requests.post(
        request.endpoint,
        headers=request.headers,
        data=request.query,
        timeout=request.timeout_seconds,
    )
    response.raise_for_status()
    return ChFoenTransportResponse(
        content=response.content,
        status_code=response.status_code,
        retrieved_at=datetime.now(UTC),
    )
