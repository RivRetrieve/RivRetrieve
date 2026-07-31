from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

import requests

METADATA_URL = "https://vodostaji.voda.ba/data/internet/layers/20/index.json"
WORKBOOK_URL_TEMPLATE = "https://vodostaji.voda.ba/data/internet/stations/{group}/{station_id}/{code}/{file}"

# The portal shards stations across numbered groups; the group for a given
# station is not exposed in the metadata snapshot and must be discovered by
# probing each group in turn until a non-404 workbook is found.
STATION_GROUPS: tuple[int, ...] = tuple(range(1, 11))


@dataclass(frozen=True)
class BaFhmzbihTransportRequest:
    url: str
    timeout_seconds: float


@dataclass(frozen=True)
class BaFhmzbihTransportResponse:
    content: bytes
    status_code: int
    retrieved_at: datetime


def _default_transport(request: BaFhmzbihTransportRequest) -> BaFhmzbihTransportResponse:
    response = requests.get(request.url, timeout=request.timeout_seconds)
    return BaFhmzbihTransportResponse(
        content=response.content,
        status_code=response.status_code,
        retrieved_at=datetime.now(UTC),
    )


@dataclass
class BaFhmzbihObservationClient:
    """HTTP client for the vodostaji.voda.ba FHMZBiH portal.

    No authentication is required. Workbooks are sharded across ten numbered
    "station groups"; the group for a station is discovered by probing
    ``STATION_GROUPS`` in order and caching the first group that returns a
    non-404, non-empty response. The cache is per-client-instance — callers
    that retrieve multiple products for the same station benefit from reusing
    one client.
    """

    timeout_seconds: float = field(default=20.0)
    transport: Callable[[BaFhmzbihTransportRequest], BaFhmzbihTransportResponse] | None = field(default=None)

    _group_cache: dict[str, int] = field(default_factory=dict, init=False, repr=False, compare=False)

    def workbook_url(self, station_id: str, group: int, code: str, file: str) -> str:
        return WORKBOOK_URL_TEMPLATE.format(group=group, station_id=station_id, code=code, file=file)

    def fetch_workbook(
        self,
        station_id: str,
        code: str,
        file: str,
    ) -> tuple[BaFhmzbihTransportResponse | None, int | None, list[str]]:
        """Fetch a workbook for ``station_id``, discovering its station group.

        Returns ``(response, group, probed_urls)``. ``response`` is ``None``
        if every group probe returned 404 or an error. ``probed_urls`` lists
        every URL that was attempted, in order, for provenance/debugging.
        """
        transport = self.transport or _default_transport
        probed: list[str] = []

        cached_group = self._group_cache.get(station_id)
        groups = (cached_group, *(g for g in STATION_GROUPS if g != cached_group)) if cached_group else STATION_GROUPS

        for group in groups:
            if group is None:
                continue
            url = self.workbook_url(station_id, group, code, file)
            probed.append(url)
            try:
                response = transport(BaFhmzbihTransportRequest(url=url, timeout_seconds=self.timeout_seconds))
            except (requests.RequestException, OSError, TimeoutError):
                continue
            if response.status_code == 200 and len(response.content) > 0:
                self._group_cache[station_id] = group
                return response, group, probed

        return None, None, probed

    def fetch_metadata(self) -> BaFhmzbihTransportResponse:
        transport = self.transport or _default_transport
        return transport(BaFhmzbihTransportRequest(url=METADATA_URL, timeout_seconds=self.timeout_seconds))
