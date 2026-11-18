"""Boundary probes across all ten UK NRFA observation products using retained captures."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import polars as pl
import pytest

from rivretrieve._internal import driver as driver_module
from rivretrieve._internal.boundary_probes import (
    FIRST_WALL_CLOCK_TIME,
    LAST_WALL_CLOCK_TIME,
    READING_COUNT,
    LiveBoundaryProbe,
    WallClockExpectation,
    run_manifest_boundary_probes,
)
from rivretrieve._internal.engine import ObservationRequest, RequestedWindow, WindowEndpoint
from rivretrieve._internal.observations import ObservationProvenance
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.registration import DeclaredProvider
from rivretrieve._internal.providers.uk_nrfa.config import (
    SHARED_ACQUISITION_PRODUCTS,
    config,
    window_declarations,
)
from rivretrieve._internal.providers.uk_nrfa.declaration import declaration
from rivretrieve._internal.providers.uk_nrfa.fetch import fetch
from rivretrieve._internal.providers.uk_nrfa.parse import parse
from rivretrieve._internal.recordings import RecordedRequest, RecordingEnvelope, ReplayTransport
from rivretrieve._internal.transport import TRANSPORT_POLICY, HttpMethod

_RETRIEVAL_SCOPE = "maintenance/observations/uk_nrfa/retrieval"
_VERIFICATION_SCOPE = "maintenance/observations/uk_nrfa/verification"


def _nrfa_stages():
    resolved_config = config()
    resolved_windows = window_declarations()

    class _Stages:
        observation_source = "live"
        config = resolved_config
        window_declarations = resolved_windows
        shared_acquisition_products = SHARED_ACQUISITION_PRODUCTS
        fetch = staticmethod(fetch)
        parse = staticmethod(parse)

    return _Stages


def _content_type(receipt: dict[str, Any]) -> str | None:
    headers = receipt.get("headers") or {}
    for key, value in headers.items():
        if str(key).lower() == "content-type":
            return str(value)
    return None


def _envelope(directory: Path, filename: str) -> RecordingEnvelope:
    body = (directory / filename).read_bytes()
    receipt = json.loads((directory / f"{filename}.receipt.json").read_bytes())
    parts = urlsplit(str(receipt["url"]))
    base_url = f"{parts.scheme}://{parts.netloc}{parts.path}"
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    return RecordingEnvelope(
        request=RecordedRequest(
            method=HttpMethod.GET,
            url=base_url,
            parameters=params,
            ordinary_headers={"Accept": "application/json", "User-Agent": TRANSPORT_POLICY.user_agent},
        ),
        content=body,
        status_code=int(receipt["status"]),
        retrieved_at=datetime.fromisoformat(str(receipt["retrieved_at"])),
        content_type=_content_type(receipt),
    )


def _probe(
    *,
    station: str,
    product: str,
    start: datetime,
    end: datetime,
    recordings: tuple[RecordingEnvelope, ...],
    reading_count: int,
    first_time: str,
    last_time: str,
) -> LiveBoundaryProbe:
    stages = _nrfa_stages()

    def _run(transport: ReplayTransport) -> pl.DataFrame:
        request = ObservationRequest(
            ProviderId("uk_nrfa"),
            (station,),
            (ProductId(product),),
            RequestedWindow(WindowEndpoint.from_datetime(start), WindowEndpoint.from_datetime(end)),
        )
        assembled = driver_module.drive(
            request,
            stages,
            provenance=ObservationProvenance(source="recorded", provider_id=ProviderId("uk_nrfa"), request={}),
            transport=transport,
        )
        return assembled.canonical_rows

    return LiveBoundaryProbe(
        provider_id=ProviderId("uk_nrfa"),
        product_id=ProductId(product),
        recordings=recordings,
        assertions={
            READING_COUNT: reading_count,
            FIRST_WALL_CLOCK_TIME: WallClockExpectation(first_time, "unknown"),
            LAST_WALL_CLOCK_TIME: WallClockExpectation(last_time, "unknown"),
        },
        run=_run,
    )


@pytest.mark.recorded(_RETRIEVAL_SCOPE, _VERIFICATION_SCOPE)
def test_uk_nrfa_boundary_probes_cover_all_ten_products(retained_evidence_root: Path) -> None:
    ret_root = retained_evidence_root / _RETRIEVAL_SCOPE
    verif_root = retained_evidence_root / _VERIFICATION_SCOPE

    probes = (
        _probe(
            station="39001",
            product="gdf",
            start=datetime(2020, 1, 3, 0, 0, 0),
            end=datetime(2020, 1, 3, 23, 59, 59),
            recordings=(_envelope(ret_root, "gdf-39001-2020-01.json"),),
            reading_count=1,
            first_time="2020-01-03T00:00:00",
            last_time="2020-01-03T00:00:00",
        ),
        _probe(
            station="39001",
            product="ndf",
            start=datetime(1995, 1, 3, 0, 0, 0),
            end=datetime(1995, 1, 8, 23, 59, 59),
            recordings=(_envelope(ret_root, "ndf-39001-1995-01.json"),),
            reading_count=6,
            first_time="1995-01-03T00:00:00",
            last_time="1995-01-08T00:00:00",
        ),
        _probe(
            station="39001",
            product="gmf",
            start=datetime(1883, 1, 1, 0, 0, 0),
            end=datetime(2025, 9, 30, 23, 59, 59),
            recordings=(_envelope(ret_root, "gmf-39001-full.json"),),
            reading_count=1712,
            first_time="1883-01-01T00:00:00",
            last_time="2025-09-01T00:00:00",
        ),
        _probe(
            station="39001",
            product="nmf",
            start=datetime(1883, 1, 1, 0, 0, 0),
            end=datetime(2025, 9, 30, 23, 59, 59),
            recordings=(_envelope(ret_root, "nmf-39001-full.json"),),
            reading_count=1712,
            first_time="1883-01-01T00:00:00",
            last_time="2025-09-01T00:00:00",
        ),
        _probe(
            station="39001",
            product="gauging-flow",
            start=datetime(2024, 7, 9, 0, 0, 0),
            end=datetime(2024, 7, 9, 23, 59, 59),
            recordings=(_envelope(verif_root, "gauging-flow-39001-2024-07.json"),),
            reading_count=1,
            first_time="2024-07-09T12:00:22",
            last_time="2024-07-09T12:00:22",
        ),
        _probe(
            station="39001",
            product="gauging-stage",
            start=datetime(2024, 7, 9, 0, 0, 0),
            end=datetime(2024, 7, 9, 23, 59, 59),
            recordings=(_envelope(verif_root, "gauging-stage-39001-2024-07.json"),),
            reading_count=1,
            first_time="2024-07-09T12:00:22",
            last_time="2024-07-09T12:00:22",
        ),
        _probe(
            station="82001",
            product="amax-flow",
            start=datetime(1962, 1, 3, 0, 0, 0),
            end=datetime(1985, 12, 29, 23, 59, 59),
            recordings=(
                _envelope(ret_root, "station-info-peak-82001.json"),
                _envelope(ret_root, "amax-flow-82001-1962-1985.json"),
            ),
            reading_count=22,
            first_time="1963-11-12T00:00:00",
            last_time="1985-09-21T12:45:00",
        ),
        _probe(
            station="6007",
            product="amax-stage",
            start=datetime(2024, 12, 31, 0, 0, 0),
            end=datetime(2024, 12, 31, 23, 59, 59),
            recordings=(
                _envelope(verif_root, "station-info-peak-6007.json"),
                _envelope(verif_root, "amax-stage-6007-2024-12.json"),
            ),
            reading_count=1,
            first_time="2024-12-31T22:30:00",
            last_time="2024-12-31T22:30:00",
        ),
        _probe(
            station="39001",
            product="pot-flow",
            start=datetime(1883, 1, 3, 0, 0, 0),
            end=datetime(2025, 12, 29, 23, 59, 59),
            recordings=(
                _envelope(ret_root, "station-info-peak-39001.json"),
                _envelope(ret_root, "pot-flow-39001-1883-2025.json"),
            ),
            reading_count=535,
            first_time="1883-01-03T00:00:00",
            last_time="2025-02-25T16:30:00",
        ),
        _probe(
            station="82001",
            product="pot-stage",
            start=datetime(1962, 1, 3, 0, 0, 0),
            end=datetime(1985, 12, 29, 23, 59, 59),
            recordings=(
                _envelope(ret_root, "station-info-peak-82001.json"),
                _envelope(ret_root, "pot-stage-82001-1962-1985.json"),
            ),
            reading_count=106,
            first_time="1963-10-02T00:00:00",
            last_time="1985-09-21T12:45:00",
        ),
    )

    frames = run_manifest_boundary_probes((DeclaredProvider("uk_nrfa", declaration),), probes)
    assert len(frames) == 10
