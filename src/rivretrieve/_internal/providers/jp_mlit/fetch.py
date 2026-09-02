"""jp_mlit fetch : stations × products × rendered windows × FetchWindow × ProviderConfig × Transport → WithIssues[Payload[]].

Contributed by: Thiago von Däniken
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Literal

from rivretrieve._internal.engine import (
    FetchWindow,
    Payload,
    ProviderConfig,
    RenderedWindow,
    SourceCallOrigin,
    SourceCoordinates,
    UnknownOriginFact,
    WithIssues,
)
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.jp_mlit.config import JpMlitSourceCoordinates
from rivretrieve._internal.transport import HttpMethod, Transport, TransportRequest, TransportResponse

_BASE = "http://www1.river.go.jp"
_DSP_URL = f"{_BASE}/cgi-bin/DspWaterData.exe"
_TITLES = {2: "時刻水位月表検索結果", 3: "日水位年表検索結果", 6: "時刻流量月表検索結果", 7: "日流量年表検索結果"}
_NO_DATA_MARKERS = ("該当するデータはありません", "該当するデータがありません")


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

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "title":
            self.in_title = True
        if tag.lower() == "a":
            for name, value in attrs:
                if name.lower() == "href" and value and ".dat" in value.lower():
                    self.links.append(value)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)


def _page(content: bytes, kind: int, station_id: str) -> tuple[str, ...]:
    try:
        text = content.decode("euc-jp", errors="strict")
    except UnicodeDecodeError as error:
        raise FatalContractError("jp_mlit HTML is not strict EUC-JP") from error
    if "charset=EUC-JP" not in text:
        raise FatalContractError("jp_mlit HTML does not declare EUC-JP")
    parser = _Page()
    parser.feed(text)
    if station_id not in text:
        raise FatalContractError("jp_mlit HTML station identity differs from request")
    if "".join(parser.title_parts).strip() != _TITLES[kind]:
        raise FatalContractError("jp_mlit HTML title differs from requested KIND")
    if not parser.links:
        if any(marker in text for marker in _NO_DATA_MARKERS):
            return ()
        raise FatalContractError("jp_mlit HTML has no uniquely established data or no-data result")
    if len(parser.links) != 1:
        raise FatalContractError("jp_mlit HTML must publish exactly one DAT link")
    path = parser.links[0]
    if re.fullmatch(r"/dat/dload/download/[A-Za-z0-9._-]+\.dat", path) is None:
        raise FatalContractError("jp_mlit HTML DAT link is off-host or malformed")
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
    )


def fetch(
    stations: tuple[str, ...],
    products: tuple[ProductId, ...],
    rendered_windows: Mapping[ProductId, tuple[RenderedWindow, ...]],
    fetch_window: FetchWindow,
    config: ProviderConfig,
    transport: Transport,
) -> WithIssues[tuple[Payload, ...]]:
    payloads: list[Payload] = []
    issues: list[Issue] = []
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
                params = {
                    "KIND": coordinates.kind,
                    "ID": station_id,
                    "BGNDATE": window.start.replace("-", ""),
                    "ENDDATE": window.stop.replace("-", ""),
                    "KAWABOU": "NO",
                }
                html = transport.send(TransportRequest(method=HttpMethod.GET, url=_DSP_URL, params=params))
                if not 200 <= html.status_code < 300:
                    raise FatalContractError(f"jp_mlit HTML request returned unexpected HTTP status {html.status_code}")
                tag = ((station_id, product_id),)
                payloads.append(
                    Payload(
                        SourceCoordinates(JpMlitPayloadCoordinates(coordinates.kind, "html")),
                        tag,
                        fetch_window,
                        html.content,
                        _origin(html),
                    )
                )
                links = _page(html.content, coordinates.kind, station_id)
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
                dat = transport.send(TransportRequest(method=HttpMethod.GET, url=links[0]))
                if not 200 <= dat.status_code < 300:
                    raise FatalContractError(f"jp_mlit DAT request returned unexpected HTTP status {dat.status_code}")
                payloads.append(
                    Payload(
                        SourceCoordinates(JpMlitPayloadCoordinates(coordinates.kind, "dat")),
                        tag,
                        fetch_window,
                        dat.content,
                        _origin(dat),
                    )
                )
    return WithIssues(tuple(payloads), tuple(issues))
