"""Source-independent public API tests for UK NRFA integration (#590)."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

import rivretrieve as rr
from rivretrieve._internal import discovery
from rivretrieve._internal.issues import FatalContractError, IssuePolicyError
from rivretrieve._internal.providers.uk_nrfa import declaration as nrfa_declaration
from rivretrieve._internal.source_series import EvidenceState
from rivretrieve._internal.transport import (
    HttpClient,
    SenderResponse,
    _ExecutableTransportRequest,
    _SystemClock,
)

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

_TS_URL = "https://nrfaapps.ceh.ac.uk/nrfa/ws/time-series"
_INFO_URL = "https://nrfaapps.ceh.ac.uk/nrfa/ws/station-info"

_PRODUCT_HEADERS: dict[str, dict[str, str]] = {
    "gdf": {
        "id": "gdf",
        "name": "Gauged Daily Flow",
        "parameter": "Flow",
        "units": "m3/s",
        "measurement-type": "Mean",
        "period": "P1D",
    },
    "ndf": {
        "id": "ndf",
        "name": "Naturalised Daily Flow",
        "parameter": "Flow",
        "units": "m3/s",
        "measurement-type": "Mean",
        "period": "P1D",
    },
    "gmf": {
        "id": "gmf",
        "name": "Gauged Monthly Flow",
        "parameter": "Flow",
        "units": "m3/s",
        "measurement-type": "Mean",
        "period": "P1M",
    },
    "nmf": {
        "id": "nmf",
        "name": "Naturalised Monthly Flow",
        "parameter": "Flow",
        "units": "m3/s",
        "measurement-type": "Mean",
        "period": "P1M",
    },
    "gauging-flow": {
        "id": "gauging-flow",
        "name": "Gauging - Flow",
        "parameter": "Flow",
        "units": "m3/s",
        "measurement-type": "Measured",
        "period": "PT1S",
    },
    "gauging-stage": {
        "id": "gauging-stage",
        "name": "Gauging - Stage",
        "parameter": "Stage",
        "units": "m",
        "measurement-type": "Measured",
        "period": "PT1S",
    },
    "amax-flow": {
        "id": "amax-flow",
        "name": "Annual Maxima - Flow",
        "parameter": "Flow",
        "units": "m3/s",
        "measurement-type": "Maximum",
        "period": "PT15M",
    },
    "amax-stage": {
        "id": "amax-stage",
        "name": "Annual Maxima - Stage",
        "parameter": "Stage",
        "units": "m",
        "measurement-type": "Maximum",
        "period": "PT15M",
    },
    "pot-flow": {
        "id": "pot-flow",
        "name": "Peaks Over Threshold - Flow",
        "parameter": "Flow",
        "units": "m3/s",
        "measurement-type": "Measured",
        "period": "PT15M",
    },
    "pot-stage": {
        "id": "pot-stage",
        "name": "Peaks Over Threshold - Stage",
        "parameter": "Stage",
        "units": "m",
        "measurement-type": "Measured",
        "period": "PT15M",
    },
}

_SAMPLE_STREAMS: dict[str, list[object]] = {
    "gdf": ["2020-01-01", 10.5],
    "ndf": ["2020-01-01", 11.2],
    "gmf": ["2020-01", 12.0],
    "nmf": ["2020-01", 13.0],
    "gauging-flow": ["2020-01-01T09:30:00", 14.5],
    "gauging-stage": ["2020-01-01T09:30:00", 1.25],
    "amax-flow": ["2020-01-02T04:15:00", 55.0],
    "amax-stage": ["2020-01-02T04:15:00", 2.85],
    "pot-flow": ["2020-01-02T04:15:00", 48.0],
    "pot-stage": ["2020-01-02T04:15:00", 2.60],
}


def _json_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(payload).encode("utf-8")


def _ts_payload(product_id: str, stream: list[object], *, station: int = 39001) -> bytes:
    return _json_bytes(
        {
            "timestamp": "2026-11-16T12:00:00Z",
            "station": {"id": station, "name": f"Station {station}"},
            "data-type": dict(_PRODUCT_HEADERS[product_id]),
            "data-stream": stream,
            "interval": "R1/2020-01-01/P1D",
        }
    )


def _station_info_payload(
    station: int = 39001,
    *,
    excluded_years: list[int] | None = None,
    rejected_periods: list[str] | None = None,
) -> bytes:
    return _json_bytes(
        {
            "data": [
                {
                    "id": station,
                    "peak-flow-rejected-amax-years": (
                        {"excluded-years": excluded_years} if excluded_years is not None else None
                    ),
                    "peak-flow-rejected-periods": (
                        {"rejected-periods": rejected_periods} if rejected_periods is not None else None
                    ),
                }
            ]
        }
    )


class _MutableClock:
    def __init__(self, now: datetime) -> None:
        self.now = now
        self._mono = 100.0

    def monotonic(self) -> float:
        self._mono += 10.0
        return self._mono

    def utcnow(self) -> datetime:
        return self.now


class _SyntheticTransport:
    def __init__(
        self,
        clock: _MutableClock,
        handler: Callable[[_ExecutableTransportRequest], SenderResponse],
    ) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []
        self._clock = clock
        self._handler = handler
        self._client = HttpClient(sender=self._sender, clock=clock, sleeper=lambda _: None)

    def _sender(self, request: _ExecutableTransportRequest, timeout_seconds: float) -> SenderResponse:
        del timeout_seconds
        params = {key: str(value) for key, value in (request.params or {}).items()}
        self.calls.append((request.url, params))
        return self._handler(request)

    def send(self, request: _ExecutableTransportRequest):
        return self._client.send(request)


def _install_mock_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    handler: Callable[[_ExecutableTransportRequest], SenderResponse],
    *,
    now: datetime = datetime(2026, 11, 17, 12, 0, 0, tzinfo=UTC),
) -> tuple[_MutableClock, _SyntheticTransport]:
    clock = _MutableClock(now)
    transport = _SyntheticTransport(clock, handler)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(_SystemClock, "utcnow", lambda self: clock.utcnow())
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    return clock, transport


def test_public_selection_and_fetch_across_all_ten_products(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def handler(request: _ExecutableTransportRequest) -> SenderResponse:
        params = request.params or {}
        if request.url == _INFO_URL:
            return SenderResponse(
                _station_info_payload(39001, excluded_years=[], rejected_periods=[]), 200, "application/json"
            )
        if request.url == _TS_URL:
            product = str(params["data-type"])
            return SenderResponse(_ts_payload(product, _SAMPLE_STREAMS[product]), 200, "application/json")
        raise AssertionError(f"Unexpected URL: {request.url}")

    _install_mock_env(monkeypatch, tmp_path, handler)

    all_products = rr.find(provider="uk_nrfa", station="39001")
    pre_series = rr.series(all_products)
    assert pre_series.height == 10
    assert set(pre_series["published_id"].to_list()) == set(_PRODUCT_HEADERS)
    assert set(pre_series["identity_namespace"].to_list()) == {"uk_nrfa/data-type"}

    # Physical-fact narrowing keeps gdf and ndf separate, and distinct from uk_ea.
    daily_flow = rr.find(provider="uk_nrfa", station="39001", quantity="discharge", frequency="daily", statistic="mean")
    assert sorted(rr.series(daily_flow)["published_id"].to_list()) == ["gdf", "ndf"]
    picked_gdf = rr.pick(daily_flow, variant="gdf")
    assert rr.series(picked_gdf)["published_id"].to_list() == ["gdf"]

    result = rr.fetch(all_products, start="2020-01-01", end="2020-01-05", cache="bypass", on_issue="ignore")
    assert result.data.height == 10
    assert set(result.data["station_id"].to_list()) == {"39001"}
    assert set(result.data["time_zone"].to_list()) == {"unknown"}
    assert set(result.data["product_id"].to_list()) == set(_PRODUCT_HEADERS)

    for product_id in _PRODUCT_HEADERS:
        rows = result.data.filter(pl.col("product_id") == product_id)
        assert rows.height == 1
        is_stage = product_id.endswith("stage")
        expected_quantity = "stage" if is_stage else "discharge"
        expected_unit = "m" if is_stage else "m3/s"
        assert rows["quantity"].to_list() == [expected_quantity]
        assert rows["source_unit"].to_list() == [expected_unit]
        assert rows["unit"].to_list() == [expected_unit]

    facts_by_product = {series.product_id: series.facts[0] for series in result.source_series}
    series_by_product = {series.product_id: series for series in result.source_series}
    for product_id, facts in facts_by_product.items():
        series_def = series_by_product[product_id]
        assert series_def.identity.namespace == "uk_nrfa/data-type"
        assert series_def.identity.published_id == product_id
        assert facts.time_zone.state == EvidenceState.NOT_ESTABLISHED
        assert facts.temporal_support.state == EvidenceState.NOT_ESTABLISHED
        assert facts.day_definition.state == EvidenceState.NOT_ESTABLISHED
        assert facts.timestamp_anchor.state == EvidenceState.NOT_ESTABLISHED
        assert facts.vertical_datum.state == EvidenceState.NOT_ESTABLISHED
        if product_id.endswith("stage"):
            assert facts.vertical_reference.state == EvidenceState.KNOWN
            assert facts.vertical_reference.value == "gauge_zero"
        else:
            assert facts.vertical_reference.state == EvidenceState.NOT_ESTABLISHED
        if product_id in {"gdf", "ndf"}:
            assert facts.frequency.value == "daily"
            assert facts.statistic.value == "mean"
        elif product_id in {"gmf", "nmf"}:
            assert facts.frequency.value == "monthly"
            assert facts.statistic.value == "mean"
        elif product_id == "amax-flow":
            assert facts.statistic.value == "max"
        elif product_id == "amax-stage":
            assert facts.statistic.state == EvidenceState.NOT_ESTABLISHED

    monthly_obs = rr.annotations(result, schema="uk_nrfa.observations").filter(
        pl.col("product_id").is_in(["gmf", "nmf"])
    )
    assert monthly_obs["source_label"].to_list() == ["2020-01", "2020-01"]
    monthly_times = result.data.filter(pl.col("product_id").is_in(["gmf", "nmf"]))["time"].to_list()
    assert monthly_times == [datetime(2020, 1, 1, 0, 0, 0), datetime(2020, 1, 1, 0, 0, 0)]

    by_provider = rr.fetch_by_provider(picked_gdf, start="2020-01-01", end="2020-01-05", cache="bypass")
    assert list(by_provider) == ["uk_nrfa"]
    assert by_provider["uk_nrfa"].data["value"].to_list() == [10.5]


def test_public_preserves_nulls_gaps_flags_metadata_and_rejections_without_filtering(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def handler(request: _ExecutableTransportRequest) -> SenderResponse:
        params = request.params or {}
        if request.url == _INFO_URL:
            return SenderResponse(
                _station_info_payload(82001, excluded_years=[1976], rejected_periods=["1975-01-01/1977-01-01"]),
                200,
                "application/json",
            )
        product = str(params["data-type"])
        streams: dict[str, list[object]] = {
            "gdf": [
                "2020-01-01",
                None,
                "2020-01-02",
                [None, "E"],
                # 2020-01-03 intentionally absent
                "2020-01-04",
                [4.2, "S"],
                "2020-01-05",
                [5.1, "E"],
            ],
            "amax-flow": ["1976-02-10T03:00:00", 88.0],
            "pot-flow": ["1976-02-10T03:00:00", 88.0],
        }
        return SenderResponse(_ts_payload(product, streams[product], station=82001), 200, "application/json")

    _install_mock_env(monkeypatch, tmp_path, handler)

    selection = rr.pick(rr.find(provider="uk_nrfa", station="82001"), variant=["gdf", "amax-flow", "pot-flow"])
    result = rr.fetch(selection, start="1975-01-01", end="2020-01-05", cache="bypass", on_issue="ignore")

    gdf_rows = result.data.filter(pl.col("product_id") == "gdf").sort("time")
    assert gdf_rows["time"].to_list() == [
        datetime(2020, 1, 1, 0, 0, 0),
        datetime(2020, 1, 2, 0, 0, 0),
        datetime(2020, 1, 4, 0, 0, 0),
        datetime(2020, 1, 5, 0, 0, 0),
    ]
    assert gdf_rows["value"].to_list() == [None, None, 4.2, 5.1]

    joined_gdf = result.to_polars(annotations=True).filter(pl.col("product_id") == "gdf").sort("time")
    assert joined_gdf["flag"].to_list() == [None, "E", "S", "E"]
    assert joined_gdf["source_label"].to_list() == ["2020-01-01", "2020-01-02", "2020-01-04", "2020-01-05"]

    obs_ann = rr.annotations(result, schema="uk_nrfa.observations").filter(pl.col("product_id") == "gdf").sort("time")
    assert obs_ann["measured"].to_list() == [True, True, True, True]
    assert obs_ann["flag"].to_list() == [None, "E", "S", "E"]

    # Rejected AMAX years and peak rejected periods remain attached without filtering peak observations.
    assert result.data.filter(pl.col("product_id") == "amax-flow")["value"].to_list() == [88.0]
    assert result.data.filter(pl.col("product_id") == "pot-flow")["value"].to_list() == [88.0]

    series_meta = rr.annotations(result, schema="uk_nrfa.series_metadata")
    assert series_meta.height == 3
    series_with_ann = rr.series(result, annotations=True).filter(pl.col("series_id").is_not_null())
    assert set(series_with_ann["measurement_type"].to_list()) == {"Mean", "Maximum", "Measured"}

    amax_rej = rr.annotations(result, schema="uk_nrfa.amax_rejection")
    assert amax_rej["rejected_amax_years"].to_list() == [[1976]]
    assert rr.series(result).filter(pl.col("series_id").is_in(amax_rej["series_id"].to_list()))[
        "product_id"
    ].to_list() == ["amax-flow"]

    periods_rej = rr.annotations(result, schema="uk_nrfa.peak_rejected_periods")
    assert periods_rej.height == 2
    assert set(
        rr.series(result).filter(pl.col("series_id").is_in(periods_rej["series_id"].to_list()))["product_id"].to_list()
    ) == {"amax-flow", "pot-flow"}


def test_public_window_rules_monthly_clipping_and_shared_peak_station_info(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def handler(request: _ExecutableTransportRequest) -> SenderResponse:
        params = request.params or {}
        if request.url == _INFO_URL:
            return SenderResponse(_station_info_payload(82001, excluded_years=[1980]), 200, "application/json")
        product = str(params["data-type"])
        if product in {"gmf", "nmf"}:
            assert "start-date" not in params
            assert "end-date" not in params
            stream = ["2019-12", 9.0, "2020-01", 10.0, "2020-02", 11.0, "2020-03", 12.0, "2020-04", 13.0]
        else:
            assert params["start-date"] == "2020-01-13"
            assert params["end-date"] == "2020-03-17"
            stream = ["2020-02-01", 10.5] if product == "gdf" else ["2020-02-01T10:00:00", 30.0]
        return SenderResponse(_ts_payload(product, stream, station=82001), 200, "application/json")

    _, transport = _install_mock_env(monkeypatch, tmp_path, handler)

    monthly_and_daily = rr.pick(rr.find(provider="uk_nrfa", station="82001"), variant=["gmf", "gdf"])
    clipped = rr.fetch(
        monthly_and_daily,
        start="2020-01-15T06:30:00.123456",
        end="2020-03-15T18:45:00.654321",
        cache="bypass",
    )
    gmf_rows = clipped.data.filter(pl.col("product_id") == "gmf").sort("time")
    assert gmf_rows["time"].to_list() == [datetime(2020, 2, 1, 0, 0, 0), datetime(2020, 3, 1, 0, 0, 0)]
    assert gmf_rows["value"].to_list() == [11.0, 12.0]
    gdf_rows = clipped.data.filter(pl.col("product_id") == "gdf")
    assert gdf_rows["value"].to_list() == [10.5]

    # All four peak products for one station issue only one shared /station-info request.
    transport.calls.clear()
    peaks = rr.pick(
        rr.find(provider="uk_nrfa", station="82001"),
        variant=["amax-flow", "amax-stage", "pot-flow", "pot-stage"],
    )
    peak_result = rr.fetch(
        peaks,
        start="2020-01-15T00:00:00.000001",
        end="2020-03-15T23:59:59.999999",
        cache="bypass",
    )
    assert peak_result.data.height == 4
    info_calls = [call for call in transport.calls if call[0] == _INFO_URL]
    ts_calls = [call for call in transport.calls if call[0] == _TS_URL]
    assert len(info_calls) == 1
    assert len(ts_calls) == 4


def test_public_empty_failure_isolation_and_fatal_contract_propagation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    mode = {"ndf": "http_400"}

    def handler(request: _ExecutableTransportRequest) -> SenderResponse:
        product = str((request.params or {})["data-type"])
        if product == "gdf":
            return SenderResponse(_ts_payload("gdf", ["2020-01-01", 10.0]), 200, "application/json")
        if product == "gmf":
            return SenderResponse(_ts_payload("gmf", []), 200, "application/json")
        if product == "ndf":
            if mode["ndf"] == "http_400":
                return SenderResponse(b"<html>400 Bad Request</html>", 400, "text/html")
            return SenderResponse(b"", 200, "application/json")
        raise AssertionError(f"Unexpected product: {product}")

    _install_mock_env(monkeypatch, tmp_path, handler)

    # Empty response stays distinct from failed requests and emits no error issue.
    empty_sel = rr.pick(rr.find(provider="uk_nrfa", station="39001"), variant="gmf")
    empty_res = rr.fetch(empty_sel, start="2035-01-01", end="2035-12-31", cache="bypass", on_issue="raise")
    assert empty_res.data.is_empty()
    assert [outcome.status.value for outcome in empty_res.outcomes] == ["empty"]
    assert not any(issue.severity in ("warning", "error") for issue in empty_res.issues)

    # HTTP 400 isolates failure onto ndf while returning valid gdf observations.
    pair_sel = rr.pick(rr.find(provider="uk_nrfa", station="39001"), variant=["gdf", "ndf"])
    partial_400 = rr.fetch(pair_sel, start="2020-01-01", end="2020-01-05", cache="bypass", on_issue="ignore")
    assert partial_400.data["product_id"].to_list() == ["gdf"]
    outcomes_400 = {
        outcome.product_id: outcome.status.value for outcome in partial_400.outcomes if outcome.series_id is not None
    }
    assert outcomes_400 == {"gdf": "success", "ndf": "failed"}
    assert [issue.code for issue in partial_400.issues if issue.severity == "error"] == ["source.request_failed"]
    with pytest.raises(IssuePolicyError):
        rr.fetch(pair_sel, start="2020-01-01", end="2020-01-05", cache="bypass", on_issue="raise")

    # 0-byte body triggers unsupported source structure on ndf while keeping gdf intact.
    mode["ndf"] = "empty_bytes"
    partial_bad = rr.fetch(pair_sel, start="2020-01-01", end="2020-01-05", cache="bypass", on_issue="ignore")
    assert partial_bad.data["product_id"].to_list() == ["gdf"]
    assert any(issue.code == "source.unsupported_structure" for issue in partial_bad.issues)

    # FatalContractError in a stage still raises even with on_issue="ignore".
    def raise_fatal(*args: object, **kwargs: object) -> object:
        raise FatalContractError("synthetic stage contract violation")

    stages = nrfa_declaration.declaration.observations.stages
    monkeypatch.setattr(stages, "parse", staticmethod(raise_fatal))
    gdf_sel = rr.pick(rr.find(provider="uk_nrfa", station="39001"), variant="gdf")
    with pytest.raises(FatalContractError, match="synthetic stage contract violation"):
        rr.fetch(gdf_sel, start="2020-01-01", end="2020-01-05", cache="bypass", on_issue="ignore")


def test_public_thirty_day_cache_retention_expiry_non_concealment_and_bundles(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fetch_state = {"value": 60.0, "fail_refetch": False}

    def handler(request: _ExecutableTransportRequest) -> SenderResponse:
        if fetch_state["fail_refetch"]:
            return SenderResponse(b"Service Unavailable", 503, "text/plain")
        if request.url == _INFO_URL:
            return SenderResponse(
                _station_info_payload(82001, excluded_years=[1976], rejected_periods=["1975-01-01/1976-12-31"]),
                200,
                "application/json",
            )
        return SenderResponse(
            _ts_payload("amax-flow", ["2020-01-02T04:15:00", fetch_state["value"]], station=82001),
            200,
            "application/json",
        )

    t0 = datetime(2026, 11, 17, 12, 0, 0, tzinfo=UTC)
    clock, transport = _install_mock_env(monkeypatch, tmp_path, handler, now=t0)

    sel = rr.pick(rr.find(provider="uk_nrfa", station="82001"), variant="amax-flow")
    first = rr.fetch(sel, start="2020-01-01", end="2020-01-05", cache="reuse")
    assert first.data["value"].to_list() == [60.0]
    assert len(transport.calls) == 2

    # Exactly 30 days later stays within NRFA's 30-day cache limit and hits local cache with zero HTTP calls.
    transport.calls.clear()
    clock.now = t0 + timedelta(days=30)
    reused = rr.fetch(sel, start="2020-01-01", end="2020-01-05", cache="reuse")
    assert transport.calls == []
    assert reused.data["value"].to_list() == [60.0]
    assert set(rr.annotations(reused)["schema"].to_list()) == {
        "uk_nrfa.observations",
        "uk_nrfa.series_metadata",
        "uk_nrfa.amax_rejection",
        "uk_nrfa.peak_rejected_periods",
    }

    # Portable bundle remains valid offline independently of local cache expiration.
    bundle_bytes = rr.to_bundle(reused)

    # At 30d + 1s, failing HTTP 503 refetch never conceals expired cache.
    clock.now = t0 + timedelta(days=30, seconds=1)
    fetch_state["fail_refetch"] = True
    failed_expiry = rr.fetch(sel, start="2020-01-01", end="2020-01-05", cache="reuse", on_issue="ignore")
    assert failed_expiry.data.is_empty()
    assert [outcome.status.value for outcome in failed_expiry.outcomes] == ["failed"]
    assert any(issue.code == "source.request_failed" for issue in failed_expiry.issues)
    with pytest.raises(IssuePolicyError):
        rr.fetch(sel, start="2020-01-01", end="2020-01-05", cache="reuse", on_issue="raise")

    # Recovery fetch succeeds once source recovers and updates cached value.
    fetch_state["fail_refetch"] = False
    fetch_state["value"] = 62.5
    refetched = rr.fetch(sel, start="2020-01-01", end="2020-01-05", cache="reuse")
    assert len(transport.calls) >= 2
    assert refetched.data["value"].to_list() == [62.5]

    restored = rr.from_bundle(bundle_bytes)
    assert isinstance(restored, type(first))
    assert restored.data["value"].to_list() == [60.0]
    assert rr.annotations(restored, schema="uk_nrfa.amax_rejection")["rejected_amax_years"].to_list() == [[1976]]


def test_uk_nrfa_public_provenance_terms(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def handler(request: _ExecutableTransportRequest) -> SenderResponse:
        del request
        return SenderResponse(_ts_payload("gdf", ["2020-01-01", 10.5]), 200, "application/json")

    _install_mock_env(monkeypatch, tmp_path, handler)

    expected_license = (
        "Click-Through Licence for Access to UK National River Flow Archive Data "
        "Available from the UK Centre for Ecology & Hydrology"
    )
    info = rr.describe("uk_nrfa")
    assert info["citation"] == "Data from the UK National River Flow Archive"
    assert info["license"] == expected_license

    sel = rr.pick(rr.find(provider="uk_nrfa", station="39001"), variant="gdf")
    result = rr.fetch(sel, start="2020-01-01", end="2020-01-05", cache="bypass", on_issue="raise")
    assert result.provenance.citation == "Data from the UK National River Flow Archive"
    assert result.provenance.license == expected_license
    assert not any(issue.code == "provenance.license_not_established" for issue in result.issues)
