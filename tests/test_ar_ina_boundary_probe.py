"""INA Alerta5 boundary probes: recorded engine-planned interactions -> all 13 canonical products."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit  # noqa: TID251 - URL parsing for retained receipt replay only

import pytest

from rivretrieve._internal.boundary_probes import (
    FIRST_WALL_CLOCK_TIME,
    LAST_WALL_CLOCK_TIME,
    READING_COUNT,
    LiveBoundaryProbe,
    WallClockExpectation,
    run_manifest_boundary_probes,
)
from rivretrieve._internal.driver import drive
from rivretrieve._internal.engine import ObservationRequest, RequestedWindow, WindowEndpoint
from rivretrieve._internal.observations import ObservationProvenance
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.ar_ina.declaration import declaration
from rivretrieve._internal.providers.ar_ina.series import source_series
from rivretrieve._internal.providers.registration import LiveStages, load_manifest
from rivretrieve._internal.recordings import RecordedRequest, RecordingEnvelope, ReplayTransport
from rivretrieve._internal.transport import TRANSPORT_POLICY, HttpMethod

assert isinstance(declaration.observations, LiveStages)
_STAGES = declaration.observations.stages
_PROVIDER = ProviderId("ar_ina")
_SCOPE = "maintenance/observations/ar_ina/retrieval"

# (product_id, station_id, published_series_id, group, capture_name, start, end, count, first_time, last_time)
_PROBES: tuple[tuple[str, str, int, str, str, str, str, int, str, str], ...] = (
    (
        "discharge_daily_mean",
        "8",
        26605,
        "retrieval",
        "a5-obs-26605-var40-planned-20240101-20240105",
        "2024-01-01T00:00:00",
        "2024-01-05T00:00:00",
        4,
        "2024-01-01T03:00:00",
        "2024-01-04T03:00:00",
    ),
    (
        "discharge_instantaneous",
        "8",
        857,
        "verification",
        "a5-obs-857-var4-planned-20240101-20240106",
        "2024-01-01T00:00:00",
        "2024-01-06T00:00:00",
        5,
        "2024-01-01T03:00:00",
        "2024-01-05T03:00:00",
    ),
    (
        "discharge_monthly_max",
        "8",
        25869,
        "verification",
        "a5-obs-25869-var52-planned-20220101-20220602",
        "2022-01-01T00:00:00",
        "2022-06-02T00:00:00",
        6,
        "2022-01-01T03:00:00",
        "2022-06-01T03:00:00",
    ),
    (
        "discharge_monthly_mean",
        "8",
        24674,
        "retrieval",
        "a5-obs-24674-var48-planned-20240101-20240102",
        "2024-01-01T00:00:00",
        "2024-01-02T00:00:00",
        1,
        "2024-01-01T03:00:00",
        "2024-01-01T03:00:00",
    ),
    (
        "discharge_monthly_min",
        "8",
        25775,
        "verification",
        "a5-obs-25775-var51-planned-20220101-20220602",
        "2022-01-01T00:00:00",
        "2022-06-02T00:00:00",
        6,
        "2022-01-01T03:00:00",
        "2022-06-01T03:00:00",
    ),
    (
        "stage_4hourly",
        "2112",
        38398,
        "verification",
        "a5-obs-38398-var101-planned-20250101-20250104",
        "2025-01-01T00:00:00",
        "2025-01-04T00:00:00",
        18,
        "2025-01-01T03:00:00",
        "2025-01-03T23:00:00",
    ),
    (
        "stage_daily_mean",
        "8",
        26250,
        "verification",
        "a5-obs-26250-var39-planned-20240101-20240105",
        "2024-01-01T00:00:00",
        "2024-01-05T00:00:00",
        4,
        "2024-01-01T03:00:00",
        "2024-01-04T03:00:00",
    ),
    (
        "stage_hourly",
        "52",
        31605,
        "verification",
        "a5-obs-31605-var85-planned-20240101-20240103",
        "2024-01-01T00:00:00",
        "2024-01-03T00:00:00",
        49,
        "2024-01-01T00:00:00",
        "2024-01-03T00:00:00",
    ),
    (
        "stage_instantaneous",
        "1701",
        3307,
        "retrieval",
        "a5-obs-3307-var2-dense15m-2d-202401",
        "2024-01-03T00:00:00",
        "2024-01-04T00:00:00",
        96,
        "2024-01-03T00:00:10",
        "2024-01-03T23:45:10",
    ),
    (
        "stage_monthly_max",
        "8",
        25681,
        "verification",
        "a5-obs-25681-var50-planned-20220101-20220602",
        "2022-01-01T00:00:00",
        "2022-06-02T00:00:00",
        6,
        "2022-01-01T03:00:00",
        "2022-06-01T03:00:00",
    ),
    (
        "stage_monthly_mean",
        "8",
        25486,
        "verification",
        "a5-obs-25486-var33-planned-20240101-20240602",
        "2024-01-01T00:00:00",
        "2024-06-02T00:00:00",
        6,
        "2024-01-01T03:00:00",
        "2024-06-01T03:00:00",
    ),
    (
        "stage_monthly_min",
        "8",
        25587,
        "verification",
        "a5-obs-25587-var49-planned-20220101-20220602",
        "2022-01-01T00:00:00",
        "2022-06-02T00:00:00",
        6,
        "2022-01-01T03:00:00",
        "2022-06-01T03:00:00",
    ),
    (
        "stage_weekly_mean",
        "151",
        36030,
        "retrieval",
        "a5-obs-36030-var67-planned-20251006-20251007",
        "2025-10-06T00:00:00",
        "2025-10-07T00:00:00",
        1,
        "2025-10-06T03:00:00",
        "2025-10-06T03:00:00",
    ),
)


def _envelope_from_capture(root: Path, group: str, name: str) -> RecordingEnvelope:
    base = root / _SCOPE / group / name
    content = base.with_suffix(".body").read_bytes()
    receipt = json.loads(base.with_suffix(".receipt.json").read_bytes())
    parsed = urlsplit(str(receipt["url"]))
    params = {key: vals[0] for key, vals in parse_qs(parsed.query, keep_blank_values=True).items()}
    headers = receipt.get("response_headers")
    content_type = headers.get("content-type") if isinstance(headers, dict) else "application/json"
    status_code = int(str(receipt.get("status", receipt.get("http_status", 200))))
    retrieved_at = datetime.fromisoformat(str(receipt["acquired_at"]).replace("Z", "+00:00"))
    return RecordingEnvelope(
        request=RecordedRequest(
            method=HttpMethod.GET,
            url=f"{parsed.scheme}://{parsed.netloc}{parsed.path}",
            parameters=params,
            ordinary_headers={
                "Accept": "application/json",
                "User-Agent": TRANSPORT_POLICY.user_agent,
            },
        ),
        content=content,
        status_code=status_code,
        retrieved_at=retrieved_at,
        content_type=str(content_type) if content_type is not None else "application/json",
    )


def _runner(station: str, product: ProductId, published_series_id: int, start_str: str, end_str: str):
    known = source_series(station, str(product), published_series_id=published_series_id)

    def run(replay: ReplayTransport):
        request = ObservationRequest(
            provider_id=_PROVIDER,
            stations=(station,),
            products=(product,),
            window=RequestedWindow(
                WindowEndpoint.from_datetime(datetime.fromisoformat(start_str)),
                WindowEndpoint.from_datetime(datetime.fromisoformat(end_str)),
            ),
            known_series=(known,),
        )
        return drive(
            request,
            _STAGES,
            provenance=ObservationProvenance(source="ar_ina", provider_id=_PROVIDER),
            transport=replay,
            cache="bypass",
        ).canonical_rows

    return run


@pytest.mark.recorded(_SCOPE)
def test_all_thirteen_ar_ina_products_have_recorded_live_boundary_proofs(
    retained_evidence_root: Path,
) -> None:
    declared = load_manifest((_PROVIDER,))
    probes = tuple(
        LiveBoundaryProbe(
            provider_id=_PROVIDER,
            product_id=ProductId(product_name),
            recordings=(_envelope_from_capture(retained_evidence_root, group, capture_name),),
            assertions={
                READING_COUNT: count,
                FIRST_WALL_CLOCK_TIME: WallClockExpectation(first_time, "+00:00"),
                LAST_WALL_CLOCK_TIME: WallClockExpectation(last_time, "+00:00"),
            },
            run=_runner(station, ProductId(product_name), series_id, start_str, end_str),
        )
        for product_name, station, series_id, group, capture_name, start_str, end_str, count, first_time, last_time in _PROBES
    )
    results = run_manifest_boundary_probes(declared, probes)
    assert [frame.height for frame in results] == [item[7] for item in _PROBES]
