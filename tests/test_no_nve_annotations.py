"""Source-independent tests for no_nve observation annotations (#820)."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.engine import (
    Payload,
    SourceCallOrigin,
    UnknownOriginFact,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.observations import ObservationDataSchema, ReceiptAuthorship
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.no_nve.config import config
from rivretrieve._internal.providers.no_nve.parse import parse
from rivretrieve._internal.source_annotations import CATALOG_SCHEMA, AnnotationScope
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.transport import (
    TransportFailure,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

_STATION = "109.42.0"
_RETRIEVED_AT = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
_ORIGIN = SourceCallOrigin(
    "https://hydapi.nve.no/api/v1/Observations",
    {},
    200,
    _RETRIEVED_AT,
    "application/json",
    UnknownOriginFact(),
    UnknownOriginFact(),
)


def _series_block(
    *,
    station: str = _STATION,
    parameter: int = 1001,
    version: int = 1,
    unit: str = "m³/s",
    observations: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "stationId": station,
        "stationName": "Test",
        "parameter": parameter,
        "parameterName": "Vannføring",
        "parameterNameEng": "Discharge",
        "method": "Mean",
        "unit": unit,
        "serieVersionNo": version,
        "observationCount": len(observations),
        "observations": observations,
    }


def _payload(product: str, data: list[dict[str, object]], *, station: str = _STATION) -> Payload:
    return Payload(
        config().products[ProductId(product)].coordinates,
        ((station, ProductId(product)),),
        _make_fetch_window(WindowEndpoint(2025, 7, 1, 0, 0, 0, 0), WindowEndpoint(2025, 7, 10, 0, 0, 0, 0)),
        json.dumps({"data": data}).encode(),
        _ORIGIN,
        (),
    )


def test_no_nve_annotation_schema_and_official_reference() -> None:
    from rivretrieve._internal.providers.no_nve.annotations import NO_NVE_OBSERVATIONS_SCHEMA, NO_NVE_URL

    assert NO_NVE_OBSERVATIONS_SCHEMA.schema_id == "no_nve.observations"
    assert NO_NVE_OBSERVATIONS_SCHEMA.provider_id == "no_nve"
    assert NO_NVE_OBSERVATIONS_SCHEMA.scope is AnnotationScope.OBSERVATION
    assert [field.name for field in NO_NVE_OBSERVATIONS_SCHEMA.fields] == ["quality", "correction"]
    assert [field.dtype for field in NO_NVE_OBSERVATIONS_SCHEMA.fields] == ["Int64", "Int64"]
    fields = {field.name: field for field in NO_NVE_OBSERVATIONS_SCHEMA.fields}
    for field in fields.values():
        assert field.description
        assert field.reference_url == NO_NVE_URL
    for token in ("0 - unknown", "1 - uncontrolled", "2 - primary controlled", "3 - secondary controlled"):
        assert token in fields["quality"].description
    for token in (
        "0: No changes",
        "1: Manual- or ice correction",
        "2: Interpolation",
        "3: Value computed with models or/and other series",
        "4: Daily mean computed with arithmetic mean",
        "16: Value fetched from rejected period",
    ):
        assert token in fields["correction"].description


def test_no_nve_parse_preserves_quality_correction_nulls_and_multi_version_identity() -> None:
    blocks = [
        _series_block(
            version=1,
            observations=[
                {"time": "2025-07-02T11:00:00Z", "value": 12.5, "correction": 0, "quality": 0},
                {"time": "2025-07-03T11:00:00Z", "value": None, "correction": None, "quality": None},
            ],
        ),
        _series_block(
            version=2,
            observations=[
                {"time": "2025-07-02T11:00:00Z", "value": 12.9, "correction": 2, "quality": 3},
                {"time": "2025-07-03T11:00:00Z", "value": 14.0, "correction": -(1 << 63), "quality": (1 << 63) - 1},
            ],
        ),
    ]
    parsed = parse(_payload("discharge_daily_mean", blocks), config())

    assert all(outcome.status is OutcomeStatus.SUCCESS for outcome in parsed.outcomes)
    assert parsed.issues == ()
    assert parsed.rows.height == 4
    assert set(parsed.annotations.observation_tables) == {"no_nve.observations"}
    assert not parsed.annotations.series_tables

    table = parsed.annotations.observation_tables["no_nve.observations"]
    assert table.measurement_indices == (0, 1, 2, 3)
    assert table.rows["quality"].dtype == pl.Int64()
    assert table.rows["correction"].dtype == pl.Int64()
    assert table.rows["quality"].to_list() == [0, None, 3, (1 << 63) - 1]
    assert table.rows["correction"].to_list() == [0, None, 2, -(1 << 63)]


def test_no_nve_empty_series_emits_empty_annotations() -> None:
    parsed = parse(_payload("discharge_daily_mean", [_series_block(version=1, observations=[])]), config())
    assert parsed.outcomes[0].status is OutcomeStatus.EMPTY
    assert parsed.rows.is_empty()
    assert parsed.annotations.is_empty


@pytest.mark.parametrize("field", ["quality", "correction"])
@pytest.mark.parametrize("bad_value", [True, False, "1", 1.0, [1], {"v": 1}, 1 << 63, -(1 << 63) - 1])
def test_no_nve_rejects_invalid_quality_or_correction_without_partial_annotations(
    field: str, bad_value: object
) -> None:
    obs: dict[str, object] = {"time": "2025-07-02T11:00:00Z", "value": 12.5, "correction": 0, "quality": 3}
    obs[field] = bad_value
    parsed = parse(_payload("discharge_daily_mean", [_series_block(version=1, observations=[obs])]), config())

    assert parsed.rows.is_empty()
    assert parsed.annotations.is_empty
    assert parsed.outcomes[0].status is OutcomeStatus.UNSUPPORTED


@pytest.mark.parametrize("field", ["quality", "correction"])
def test_no_nve_rejects_missing_quality_or_correction_key(field: str) -> None:
    obs: dict[str, object] = {"time": "2025-07-02T11:00:00Z", "value": 12.5, "correction": 0, "quality": 3}
    del obs[field]
    parsed = parse(_payload("discharge_daily_mean", [_series_block(version=1, observations=[obs])]), config())

    assert parsed.rows.is_empty()
    assert parsed.annotations.is_empty
    assert parsed.outcomes[0].status is OutcomeStatus.UNSUPPORTED


def test_no_nve_public_projection_pick_to_utc_refresh_and_bundles(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    phase = {"step": "initial"}

    class _Transport:
        def __init__(self, obs_handler: Callable[[str], list[dict[str, object]]]) -> None:
            self.obs_handler = obs_handler
            self.calls: list[str] = []

        def send(self, request: TransportRequest) -> TransportResponse:
            self.calls.append(request.url)
            if request.url.endswith("/Series"):
                data = [_series_block(version=int(v), observations=[]) for v in ("1", "2")]
                return TransportResponse(
                    json.dumps({"data": data}).encode(),
                    200,
                    _RETRIEVED_AT,
                    "application/json",
                    request.url,
                    dict(request.params),
                )
            version = str(request.params.get("VersionNumber", ""))
            if phase["step"] == "fail_v2" and version == "2":
                raise TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=503)
            return TransportResponse(
                json.dumps({"data": self.obs_handler(version)}).encode(),
                200,
                _RETRIEVED_AT,
                "application/json",
                request.url,
                dict(request.params),
            )

    def obs_handler(version: str) -> list[dict[str, object]]:
        if phase["step"] == "reannotated":
            return [
                _series_block(
                    version=int(version),
                    observations=[
                        {"time": "2025-07-02T11:00:00Z", "value": 12.5, "correction": 2, "quality": 3},
                    ],
                )
            ]
        q_code = 0 if version == "1" else 3
        c_code = 0 if version == "1" else 1
        return [
            _series_block(
                version=int(version),
                observations=[
                    {"time": "2025-06-30T11:00:00Z", "value": 9.0, "correction": 0, "quality": 1},
                    {"time": "2025-07-02T11:00:00Z", "value": 12.5, "correction": c_code, "quality": q_code},
                    {"time": "2025-07-05T11:00:00Z", "value": 15.0, "correction": 0, "quality": 1},
                ],
            )
        ]

    transport = _Transport(obs_handler)
    monkeypatch.setenv("NVE_API_KEY", "protocol-only-nve-key")
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)

    selection = rr.pick(
        rr.find(provider="no_nve", station=_STATION, quantity="discharge", frequency="P1D", statistic="mean"),
        variant=["1", "2"],
    )
    assert rr.annotations(selection).is_empty()
    base_series = rr.series(selection)

    result = rr.fetch(selection, start="2025-07-02", end="2025-07-03", cache="reuse", receipts=True, on_issue="raise")
    assert result.issues == ()
    assert list(result.data.columns) == list(ObservationDataSchema.polars_schema)
    assert rr.series(result).columns == base_series.columns
    assert result.data.height == 2

    catalog = rr.annotations(result)
    assert list(catalog.columns) == list(CATALOG_SCHEMA)
    assert catalog["schema"].to_list() == ["no_nve.observations", "no_nve.observations"]
    assert catalog["name"].to_list() == ["quality", "correction"]
    assert catalog["dtype"].to_list() == ["Int64", "Int64"]
    assert catalog["row_count"].to_list() == [2, 2]

    projected = (
        result.to_polars(annotations=True)
        .join(rr.series(result).select("series_id", "variant"), on="series_id")
        .sort("variant")
    )
    assert projected["variant"].to_list() == ["1", "2"]
    assert projected["quality"].to_list() == [0, 3]
    assert projected["correction"].to_list() == [0, 1]

    picked = rr.pick(result, variant="2")
    assert picked.to_polars(annotations=["correction", "quality"]).columns == [
        *result.data.columns,
        "correction",
        "quality",
    ]
    assert picked.to_polars(annotations=True)["correction"].to_list() == [1]

    utc_result = rr.to_utc(result)
    pl_testing.assert_frame_equal(
        utc_result.to_polars(annotations=True).sort(["series_id", "time"]),
        result.to_polars(annotations=True).sort(["series_id", "time"]),
    )

    pandas_df = result.to_pandas(annotations=True)
    assert isinstance(pandas_df, pd.DataFrame)
    assert list(pandas_df.columns) == [*result.data.columns, "quality", "correction"]

    calls_before = len(transport.calls)
    reused = rr.fetch(selection, start="2025-07-02", end="2025-07-03", cache="reuse", receipts=True, on_issue="raise")
    assert len(transport.calls) == calls_before
    assert all(entry.authorship is ReceiptAuthorship.STORE_EXCERPT for entry in reused.receipts.entries)
    pl_testing.assert_frame_equal(
        reused.to_polars(annotations=True).sort(["series_id", "time"]),
        result.to_polars(annotations=True).sort(["series_id", "time"]),
    )

    restored = rr.from_bundle(rr.to_bundle(result))
    pl_testing.assert_frame_equal(rr.annotations(restored), rr.annotations(result))
    pl_testing.assert_frame_equal(
        restored.to_polars(annotations=True).sort(["series_id", "time"]),
        result.to_polars(annotations=True).sort(["series_id", "time"]),
    )

    # Status-only refresh and failed refresh preservation across selected versions.
    phase["step"] = "reannotated"
    refreshed = rr.fetch(selection, start="2025-07-02", end="2025-07-02", cache="refresh", on_issue="ignore")
    ref_df = (
        refreshed.to_polars(annotations=True)
        .join(rr.series(refreshed).select("series_id", "variant"), on="series_id")
        .sort("variant")
    )
    assert ref_df["quality"].to_list() == [3, 3]
    assert ref_df["correction"].to_list() == [2, 2]

    phase["step"] = "fail_v2"
    partial = rr.fetch(selection, start="2025-07-02", end="2025-07-02", cache="refresh", on_issue="ignore")
    outcomes = {
        dict(rr.series(partial).select("series_id", "variant").iter_rows())[o.series_id]: o.status
        for o in partial.outcomes
        if o.series_id
    }
    assert outcomes == {"1": OutcomeStatus.SUCCESS, "2": OutcomeStatus.FAILED}
    held = (
        rr.fetch(selection, start="2025-07-02", end="2025-07-02", cache="reuse", on_issue="ignore")
        .to_polars(annotations=True)
        .join(rr.series(refreshed).select("series_id", "variant"), on="series_id")
        .sort("variant")
    )
    assert held["quality"].to_list() == [0, 3]
    assert held["correction"].to_list() == [0, 2]
