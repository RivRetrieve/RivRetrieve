"""Acquire independent MLIT intervals and retain HTML prerequisites and bounded failures.

Contributed by: Thiago von Däniken
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from typing import Literal

from rivretrieve._internal.engine import (
    FetchWindow,
    Payload,
    ProviderConfig,
    RenderedWindow,
    SourceAcquisition,
    SourceCallOrigin,
    SourceCoordinates,
    UnknownOriginFact,
)
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.provider_series import UnsupportedSourceStructureError
from rivretrieve._internal.providers.jp_mlit.config import SERIES_MAPPINGS, JpMlitSourceCoordinates
from rivretrieve._internal.source_acquisition import FailedSourceRequest, attempt_series_request
from rivretrieve._internal.source_series import SeriesScope, SeriesWindow, SourceSeries
from rivretrieve._internal.transport import HttpMethod, Transport, TransportRequest, TransportResponse

_BASE = "http://www1.river.go.jp"
_DSP_URL = f"{_BASE}/cgi-bin/DspWaterData.exe"
_TITLES = {2: "時刻水位月表検索結果", 3: "日水位年表検索結果", 6: "時刻流量月表検索結果", 7: "日流量年表検索結果"}
_NO_DATA_MARKERS = ("該当するデータはありません", "該当するデータがありません")
_STAGE_UNIT = (("text", "単位：m"),)
_DISCHARGE_UNIT = (
    ("text", "単位：m"),
    ("start", "sup"),
    ("text", "3"),
    ("end", "sup"),
    ("text", "/s"),
)
_UNIT_BY_KIND = {2: _STAGE_UNIT, 3: _STAGE_UNIT, 6: _DISCHARGE_UNIT, 7: _DISCHARGE_UNIT}


@dataclass(frozen=True, slots=True)
class JpMlitPayloadCoordinates:
    kind: int
    role: Literal["html", "dat"]


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_title = False
        self.title_parts: list[str] = []
        self.links: list[str] = []
        self.unit_cells: list[tuple[tuple[str, str], ...]] = []
        self._cell_tokens: list[tuple[str, str]] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.lower()
        if normalized == "title":
            self.in_title = True
        if normalized == "td":
            self._cell_tokens = []
        elif self._cell_tokens is not None:
            self._cell_tokens.append(("start", normalized))
        if normalized == "a":
            for name, value in attrs:
                if name.lower() == "href" and value and ".dat" in value.lower():
                    self.links.append(value)

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized == "title":
            self.in_title = False
        if normalized == "td" and self._cell_tokens is not None:
            if any(token == "text" and value.startswith("単位") for token, value in self._cell_tokens):
                self.unit_cells.append(tuple(self._cell_tokens))
            self._cell_tokens = None
        elif self._cell_tokens is not None:
            self._cell_tokens.append(("end", normalized))

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)
        value = data.strip()
        if self._cell_tokens is not None and value:
            if self._cell_tokens and self._cell_tokens[-1][0] == "text":
                token, prior = self._cell_tokens[-1]
                self._cell_tokens[-1] = (token, prior + value)
            else:
                self._cell_tokens.append(("text", value))


def _page(content: bytes, kind: int, station_id: str) -> tuple[str, ...]:
    try:
        text = content.decode("euc-jp", errors="strict")
    except UnicodeDecodeError as error:
        raise UnsupportedSourceStructureError("jp_mlit HTML is not strict EUC-JP") from error
    if "charset=EUC-JP" not in text:
        raise UnsupportedSourceStructureError("jp_mlit HTML does not declare EUC-JP")
    parser = _Page()
    parser.feed(text)
    if station_id not in text:
        raise UnsupportedSourceStructureError("jp_mlit HTML station identity differs from request")
    if "".join(parser.title_parts).strip() != _TITLES[kind]:
        raise UnsupportedSourceStructureError("jp_mlit HTML title differs from requested KIND")
    if parser.unit_cells and parser.unit_cells != [_UNIT_BY_KIND[kind]]:
        raise UnsupportedSourceStructureError(
            "jp_mlit HTML unit differs from the exact publisher unit for requested KIND"
        )
    if not parser.links:
        if any(marker in text for marker in _NO_DATA_MARKERS):
            return ()
        raise UnsupportedSourceStructureError("jp_mlit HTML has no uniquely established data or no-data result")
    if parser.unit_cells != [_UNIT_BY_KIND[kind]]:
        raise UnsupportedSourceStructureError(
            "jp_mlit HTML unit differs from the exact publisher unit for requested KIND"
        )
    if len(parser.links) != 1:
        raise UnsupportedSourceStructureError("jp_mlit HTML must publish exactly one DAT link")
    path = parser.links[0]
    if re.fullmatch(r"/dat/dload/download/[A-Za-z0-9._-]+\.dat", path) is None:
        raise UnsupportedSourceStructureError("jp_mlit HTML DAT link is off-host or malformed")
    return (f"{_BASE}{path}",)


def _origin(response: TransportResponse) -> SourceCallOrigin:
    return SourceCallOrigin(
        url=response.url,
        request_parameters=response.request_parameters,
        status_code=response.status_code,
        retrieved_at=response.retrieved_at,
        content_type=response.content_type if response.content_type is not None else UnknownOriginFact(),
        source_path=UnknownOriginFact(),
        query=UnknownOriginFact(),
        attempts=response.attempts,
    )


def fetch(
    stations: tuple[str, ...],
    products: tuple[ProductId, ...],
    rendered_windows: Mapping[ProductId, tuple[RenderedWindow, ...]],
    fetch_window: FetchWindow,
    config: ProviderConfig,
    transport: Transport,
    *,
    scope: SeriesScope | None = None,
    known_series: tuple[SourceSeries, ...] = (),
) -> SourceAcquisition:
    payloads: list[Payload] = []
    issues: list[Issue] = []
    failures: list[FailedSourceRequest] = []
    for station_id in stations:
        for product_id in products:
            try:
                product = config.products[product_id]
            except KeyError as error:
                raise FatalContractError(f"jp_mlit product is absent from provider config: {product_id}") from error
            coordinates = product.coordinates.value
            if not isinstance(coordinates, JpMlitSourceCoordinates):
                raise FatalContractError(f"jp_mlit product has invalid source coordinates: {product_id}")
            for window in rendered_windows[product_id]:
                if window.stop is None:
                    raise FatalContractError("jp_mlit window requires inclusive start and stop dates")
                if window.bounds is None:
                    raise FatalContractError("jp_mlit requires engine-established acquisition bounds")
                series = SERIES_MAPPINGS[product_id].source_series("jp_mlit", station_id, product_id)
                bounds = SeriesWindow(
                    start=datetime.fromisoformat(window.bounds.start.isoformat()),
                    end=datetime.fromisoformat(window.bounds.end.isoformat()),
                )
                params = {
                    "KIND": coordinates.kind,
                    "ID": station_id,
                    "BGNDATE": window.start.replace("-", ""),
                    "ENDDATE": window.stop.replace("-", ""),
                    "KAWABOU": "NO",
                }
                html = attempt_series_request(
                    transport, TransportRequest(method=HttpMethod.GET, url=_DSP_URL, params=params), series, bounds
                )
                if isinstance(html, FailedSourceRequest):
                    failures.append(html)
                    continue
                tag = ((station_id, product_id),)
                payloads.append(
                    Payload(
                        SourceCoordinates(JpMlitPayloadCoordinates(coordinates.kind, "html")),
                        tag,
                        window.bounds,
                        html.content,
                        _origin(html),
                        html.prerequisite_calls,
                        scope=scope,
                        known_series=known_series,
                        attempt_traces=html.attempt_traces,
                    )
                )
                try:
                    links = _page(html.content, coordinates.kind, station_id)
                except UnsupportedSourceStructureError:
                    # Parse retains this exact HTML and identifies its unsupported series.
                    # Do not follow unvalidated links or discard independent requests.
                    continue
                if not links:
                    issues.append(
                        Issue(
                            severity="warning",
                            code="source_no_data",
                            provider_id=ProviderId("jp_mlit"),
                            message=f"jp_mlit source established no data for {station_id} {product_id}",
                            details={
                                "station_id": station_id,
                                "product_id": product_id,
                                "begin": window.start,
                                "end": window.stop,
                            },
                        )
                    )
                    continue
                dat = attempt_series_request(
                    transport, TransportRequest(method=HttpMethod.GET, url=links[0]), series, bounds
                )
                if isinstance(dat, FailedSourceRequest):
                    failures.append(dat)
                    continue
                payloads.append(
                    Payload(
                        SourceCoordinates(JpMlitPayloadCoordinates(coordinates.kind, "dat")),
                        tag,
                        window.bounds,
                        dat.content,
                        _origin(dat),
                        dat.prerequisite_calls,
                        attempt_traces=dat.attempt_traces,
                        scope=scope,
                        known_series=known_series,
                    )
                )
    return SourceAcquisition(tuple(payloads), tuple(issues), failed_requests=tuple(failures))
