"""Public Ireland OPW (`ie_opw`) retrieval, series_id parity, cache, annotations, and isolation tests."""

from __future__ import annotations

import io
import json
import warnings
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

import polars as pl
import pytest
from polars.testing import assert_frame_equal

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.discovery import EmptySelectionError, _Selection
from rivretrieve._internal.issues import IssuePolicyError
from rivretrieve._internal.observations import ObservationResult
from rivretrieve._internal.providers.ie_opw.annotations import (
    IE_OPW_DAILY_STAGE_SCHEMA,
    IE_OPW_SERIES_SCHEMA,
)
from rivretrieve._internal.providers.ie_opw.series import PRODUCT_SPECS
from rivretrieve._internal.selection import UnknownStationError
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.transport import (
    TransportFailure,
    TransportFailureCategory,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)

_RETRIEVED_AT = datetime(2026, 11, 23, 21, 0, tzinfo=UTC)

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")


def _select_products(station: str, *products: str) -> _Selection:
    selected = rr.find(provider="ie_opw", station=station)
    series_ids = rr.as_frame(selected).filter(pl.col("product_id").is_in(products))["series_id"].to_list()
    assert len(series_ids) == len(products)
    picked = rr.pick(selected, series_id=series_ids)
    assert isinstance(picked, _Selection)
    return picked


def _raise_http_failure(request: TransportRequest, status_code: int = 503) -> NoReturn:
    raise TransportFailure(
        request,
        TransportFailureReason.HTTP_STATUS,
        1,
        status_code=status_code,
        category=TransportFailureCategory.HTTP_STATUS,
    )


def _json_response(request: TransportRequest, payload: object, status_code: int = 200) -> TransportResponse:
    return TransportResponse(
        content=json.dumps(payload).encode("utf-8"),
        status_code=status_code,
        retrieved_at=_RETRIEVED_AT,
        content_type="application/json",
        url=request.url,
        request_parameters={},
    )


def _zip_response(
    request: TransportRequest,
    *,
    station: str,
    param: str,
    unit: str,
    rows: list[tuple[str, str, str]],
) -> TransportResponse:
    shortnames = {
        "Q": "WEB.Cmd.Runoff",
        "S": "WEB.Cmd.P-Continuous.Absolute",
        "TWater": "WEB.Cmd.P-Water-Temp",
    }
    header = [
        f"#station_name;Station {station}",
        f"#station_no;{station}",
        "#station_latitude;54.83831806",
        "#station_longitude;-7.575758056",
        f"#stationparameter_name;{param}",
        f"#ts_shortname;{shortnames[param]}",
        f"#ts_unitsymbol;{unit}",
        "#WTO_OBJECT;DEELE",
        "#RBD;NORTH WESTERN IRBD",
        f"#rows;{len(rows)}",
        "#Timestamp;Value;Quality Code",
    ]
    body_text = "\n".join(header + [f"{ts};{val};{qc}" for ts, val, qc in rows]) + "\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("tsvalues.csv", body_text)
    return TransportResponse(
        content=buf.getvalue(),
        status_code=200,
        retrieved_at=_RETRIEVED_AT,
        content_type="application/zip",
        url=request.url,
        request_parameters={},
    )


def _daily_blocks(
    station: str,
    param: str,
    unit: str,
    rows: list[list[object]],
) -> list[dict[str, object]]:
    if param == "S":
        shortnames = ("WEB.Day.Mean", "WEB.Day.Min", "WEB.Day.Max")
        columns = "Timestamp,Value,Quality Code,Aggregation Accuracy %"
    elif param == "TWater":
        shortnames = ("WEB.Day.Min-Water-Temp", "WEB.Day.Mean-Water-Temp", "WEB.Day.Max-Water-Temp")
        columns = "Timestamp,Value,Quality Code"
    else:
        shortnames = ("WEB.Day.Mean", "WEB.Day.Min", "WEB.Day.Max")
        columns = "Timestamp,Value,Quality Code"
    return [
        {
            "station_name": f"Station {station}",
            "station_no": station,
            "station_latitude": "54.83831806",
            "station_longitude": "-7.575758056",
            "stationparameter_name": param,
            "ts_shortname": short,
            "ts_unitsymbol": unit,
            "columns": columns,
            "data": [list(item) for item in rows],
        }
        for short in shortnames
    ]


@pytest.mark.parametrize(
    ("product_id", "raw_value", "expected_unit"),
    [
        ("discharge_daily_mean", 4.25, "m3/s"),
        ("stage_daily_min", -0.249, "m"),
        ("water_temperature_instantaneous", 11.6, "degC"),
    ],
)
def test_public_fetch_picked_by_catalogue_series_id_returns_matching_rows(
    monkeypatch: pytest.MonkeyPatch,
    product_id: str,
    raw_value: float,
    expected_unit: str,
) -> None:
    class _ParityTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            if request.url.endswith("/Q/year.json"):
                return _json_response(
                    request, _daily_blocks("01041", "Q", "cumec", [["2025-07-15T00:00:00.000Z", raw_value, 31]])
                )
            if request.url.endswith("/S/year.json"):
                return _json_response(
                    request, _daily_blocks("01041", "S", "m", [["2025-07-15T00:00:00.000Z", raw_value, 31, 100.0]])
                )
            if request.url.endswith("/TWater/WaterTemperature_complete.zip"):
                return _zip_response(
                    request,
                    station="01041",
                    param="TWater",
                    unit="°C",
                    rows=[
                        ("2025-07-15T00:00:00.000Z", f"{raw_value}", "254"),
                        ("2025-07-16T00:00:00.000Z", f"{raw_value}", "254"),
                    ],
                )
            raise AssertionError(f"Unexpected URL: {request.url}")

    monkeypatch.setattr(discovery, "HttpClient", _ParityTransport)
    selection = _select_products("01041", product_id)
    cat_frame = rr.series(selection)
    assert cat_frame.height == 1
    cat_series_id = cat_frame["series_id"][0]
    cat_facts_id = cat_frame["facts_id"][0]

    unpicked = rr.fetch(selection, start="2025-07-15", end="2025-07-15T23:59:59", cache="bypass")
    assert unpicked.issues == ()
    assert unpicked.data["series_id"].to_list() == [cat_series_id]
    assert unpicked.data["facts_id"].to_list() == [cat_facts_id]

    picked = rr.pick(selection, series_id=[cat_series_id])
    assert isinstance(picked, _Selection)
    result = rr.fetch(picked, start="2025-07-15", end="2025-07-15T23:59:59", cache="bypass")

    assert result.issues == ()
    assert result.data.height == 1
    assert result.data["series_id"].to_list() == [cat_series_id]
    assert result.data["facts_id"].to_list() == [cat_facts_id]
    assert result.data["unit"].to_list() == [expected_unit]
    assert result.data["time_zone"].to_list() == ["+00:00"]
    assert result.data["value"].to_list() == [pytest.approx(raw_value)]
    assert [o.status for o in result.outcomes] == [OutcomeStatus.SUCCESS]
    assert rr.series(result)["series_id"].to_list() == [cat_series_id]
    assert rr.series(result)["facts_id"].to_list() == [cat_facts_id]


def test_public_fetch_shared_daily_group_and_cache_reuse_full_and_subset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = 0

    class _CacheTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            nonlocal calls
            calls += 1
            assert request.url.endswith("/01041/Q/year.json")
            return _json_response(
                request,
                _daily_blocks(
                    "01041",
                    "Q",
                    "cumec",
                    [
                        ["2025-07-15T00:00:00.000Z", 2.5, 31],
                        ["2025-07-16T00:00:00.000Z", None, -1],
                    ],
                ),
            )

    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(discovery, "HttpClient", _CacheTransport)

    daily_sel = _select_products("01041", "discharge_daily_mean", "discharge_daily_min", "discharge_daily_max")
    first = rr.fetch(daily_sel, start="2025-07-15", end="2025-07-16", cache="reuse")
    assert calls == 1
    assert first.data.height == 3
    assert rr.annotations(first, schema=IE_OPW_SERIES_SCHEMA.schema_id).filter(pl.col("measured").not_()).height == 3

    reused = rr.fetch(daily_sel, start="2025-07-15", end="2025-07-16", cache="reuse")
    assert calls == 1
    assert_frame_equal(reused.data, first.data)
    assert_frame_equal(
        rr.annotations(reused, schema=IE_OPW_SERIES_SCHEMA.schema_id),
        rr.annotations(first, schema=IE_OPW_SERIES_SCHEMA.schema_id),
    )

    subset_sel = _select_products("01041", "discharge_daily_mean")
    subset = rr.fetch(subset_sel, start="2025-07-15", end="2025-07-15", cache="reuse")
    assert calls == 1
    assert subset.data["product_id"].to_list() == ["discharge_daily_mean"]
    assert subset.data["value"].to_list() == [pytest.approx(2.5)]


def test_public_all_12_products_annotations_to_polars_utc_bundle_and_provenance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))

    class _All12Transport:
        def __init__(self) -> None:
            self.calls = 0

        def send(self, request: TransportRequest) -> TransportResponse:
            self.calls += 1
            if request.url.endswith("/Q/year.json"):
                return _json_response(
                    request, _daily_blocks("01041", "Q", "cumec", [["2025-07-15T00:00:00.000Z", 3.2, 31]])
                )
            if request.url.endswith("/S/year.json"):
                return _json_response(
                    request, _daily_blocks("01041", "S", "m", [["2025-07-15T00:00:00.000Z", 0.45, 31, 100.0]])
                )
            if request.url.endswith("/TWater/year.json"):
                return _json_response(
                    request,
                    _daily_blocks(
                        "01041",
                        "TWater",
                        "°C",
                        [
                            ["2025-07-15T00:00:00.000Z", 15.1, 254],
                            ["2025-07-16T00:00:00.000Z", None, -1],
                        ],
                    ),
                )
            if request.url.endswith("/Q/Discharge_complete.zip"):
                return _zip_response(
                    request,
                    station="01041",
                    param="Q",
                    unit="cumec",
                    rows=[("2025-07-15T12:00:00.000Z", "3.4", "31")],
                )
            if request.url.endswith("/S/Waterlevel_complete.zip"):
                return _zip_response(
                    request,
                    station="01041",
                    param="S",
                    unit="m",
                    rows=[("2025-07-15T12:00:00.000Z", "0.47", "31")],
                )
            if request.url.endswith("/TWater/WaterTemperature_complete.zip"):
                return _zip_response(
                    request,
                    station="01041",
                    param="TWater",
                    unit="°C",
                    rows=[
                        ("2025-07-15T12:00:00.000Z", "15.3", "254"),
                        ("2025-07-15T13:00:00.000Z", "", "-1"),
                    ],
                )
            raise AssertionError(f"Unexpected URL: {request.url}")

    transport = _All12Transport()
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)

    selection = rr.find(provider="ie_opw", station="01041")
    assert len(selection.series) == len(PRODUCT_SPECS) == 12
    result = rr.fetch(selection, start="2025-07-15", end="2025-07-16T23:59:59", cache="bypass", receipts=True)
    # 3 shared daily year.json requests + 3 complete.zip requests = 6 HTTP calls.
    assert transport.calls == 6
    assert result.issues == ()
    assert result.receipts is not None and len(result.receipts.entries) == 6
    assert result.data["product_id"].n_unique() == 12
    assert result.data.height == 12
    assert result.data["value"].null_count() == 0

    q_rows = result.data.filter(pl.col("product_id").str.starts_with("discharge_"))
    assert q_rows["source_unit"].unique().to_list() == ["cumec"]
    assert q_rows["unit"].unique().to_list() == ["m3/s"]

    ann_catalog = rr.annotations(result)
    assert set(ann_catalog["schema"].to_list()) == {IE_OPW_SERIES_SCHEMA.schema_id, IE_OPW_DAILY_STAGE_SCHEMA.schema_id}
    series_ann = rr.annotations(result, schema=IE_OPW_SERIES_SCHEMA.schema_id)
    stage_ann = rr.annotations(result, schema=IE_OPW_DAILY_STAGE_SCHEMA.schema_id)
    assert series_ann.filter(pl.col("measured").not_()).height == 4
    assert stage_ann["aggregation_accuracy_pct"].to_list() == [100.0, 100.0, 100.0]

    joined = result.to_polars(annotations=True)
    assert "quality_code" in joined.columns
    assert "aggregation_accuracy_pct" in joined.columns
    assert joined.height == 12

    utc_result = rr.to_utc(result)
    assert utc_result.data.height == 12

    acq_prov = result.provenance.acquisition_provenance
    assert acq_prov is not None
    statements = [stmt for record in acq_prov.header.source_records for stmt in record.statements]
    assert any(stmt.kind == "license" and stmt.exact_text == "CC BY 4.0" for stmt in statements)
    assert any(
        stmt.kind == "citation" and stmt.exact_text is not None and "Office of Public Works" in stmt.exact_text
        for stmt in statements
    )

    restored = rr.from_bundle(rr.to_bundle(result))
    assert isinstance(restored, ObservationResult)
    assert_frame_equal(restored.data, result.data)
    assert_frame_equal(rr.annotations(restored, schema=IE_OPW_SERIES_SCHEMA.schema_id), series_ann)
    assert_frame_equal(rr.annotations(restored, schema=IE_OPW_DAILY_STAGE_SCHEMA.schema_id), stage_ann)


def test_public_failure_isolation_refresh_retention_and_closed_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    two_stations = rr.pick(
        rr.find(provider="ie_opw", quantity="discharge", frequency="P1D", statistic="mean"),
        station=["01041", "07012"],
    )
    assert isinstance(two_stations, _Selection)

    class _FaultTransport:
        def __init__(self) -> None:
            self.fail_all_code: int | None = None

        def send(self, request: TransportRequest) -> TransportResponse:
            if self.fail_all_code is not None:
                _raise_http_failure(request, self.fail_all_code)
            if "/01041/" in request.url:
                return _json_response(
                    request, _daily_blocks("01041", "Q", "cumec", [["2025-07-15T00:00:00.000Z", 5.2, 31]])
                )
            _raise_http_failure(request, 503)

    fault = _FaultTransport()
    monkeypatch.setattr(discovery, "HttpClient", lambda: fault)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        partial = rr.fetch(two_stations, start="2025-07-15", end="2025-07-15", cache="reuse", on_issue="warn")
    assert caught
    assert partial.data["station_id"].to_list() == ["01041"]
    assert partial.data["value"].to_list() == [pytest.approx(5.2)]
    assert {o.station_id: o.status for o in partial.outcomes} == {
        "01041": OutcomeStatus.SUCCESS,
        "07012": OutcomeStatus.FAILED,
    }

    s01041 = _select_products("01041", "discharge_daily_mean")
    fault.fail_all_code = 503
    with pytest.raises(IssuePolicyError):
        rr.fetch(s01041, start="2025-07-15", end="2025-07-15", cache="refresh", on_issue="raise")
    retained = rr.fetch(s01041, start="2025-07-15", end="2025-07-15", cache="refresh", on_issue="ignore")
    assert retained.data["value"].to_list() == [pytest.approx(5.2)]

    # Mismatched time_zone and excluded lake/tidal/rainfall stations fail closed without network calls.
    class _ForbidSendTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            raise AssertionError(f"closed failure must not send HTTP requests: {request.url}")

    monkeypatch.setattr(discovery, "HttpClient", _ForbidSendTransport)
    empty_tz = rr.find(provider="ie_opw", station="01041", time_zone="Europe/Dublin")
    with pytest.raises(EmptySelectionError, match="ie_opw"):
        rr.fetch(empty_tz, start="2025-07-15", end="2025-07-15")
    for excluded in ("30089", "06062", "80101"):
        with pytest.raises(UnknownStationError):
            rr.find(provider="ie_opw", station=excluded)
