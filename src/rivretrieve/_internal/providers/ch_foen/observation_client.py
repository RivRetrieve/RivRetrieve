from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChFoenObservationClient:
    token: str
    endpoint: str = "https://influx.konzept.space/api/v2/query?org=api.existenz.ch"
    timeout_seconds: float = 60.0

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}("
            f"endpoint={self.endpoint!r}, "
            "token='<redacted>', "
            f"timeout_seconds={self.timeout_seconds!r})"
        )
