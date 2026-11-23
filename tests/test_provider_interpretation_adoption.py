"""Source-independent tests for provider adoption of shared retrieval (#951)."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import openpyxl
import polars.testing as pl_testing
import pytest

import rivretrieve._internal.driver as driver_module
from rivretrieve._internal.engine import (
    ObservationRequest,
    Payload,
    ProviderConfig,
    RequestedWindow,
    SourceAcquisition,
    WindowEndpoint,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.observations import ReceiptMode
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.source_series import OutcomeStatus, SeriesScope
from rivretrieve._internal.transport import TransportResponse
from tests.test_internal_driver import _provenance


def _assert_annotation_bundles_equal(left: Any, right: Any) -> None:
    assert set(left.observation_tables) == set(right.observation_tables)
    for key in left.observation_tables:
        lt = left.observation_tables[key]
        rt = right.observation_tables[key]
        assert lt.schema == rt.schema
        assert lt.measurement_indices == rt.measurement_indices
        pl_testing.assert_frame_equal(lt.rows, rt.rows)
    assert set(left.series_tables) == set(right.series_tables)
    for key in left.series_tables:
        lt = left.series_tables[key]
        rt = right.series_tables[key]
        assert lt.schema == rt.schema
        pl_testing.assert_frame_equal(lt.rows, rt.rows)


def _assert_driver_results_identical(left: Any, right: Any) -> None:
    pl_testing.assert_frame_equal(left.canonical_rows, right.canonical_rows)
    _assert_annotation_bundles_equal(left.annotations, right.annotations)
    assert left.source_series == right.source_series
    assert left.inventories == right.inventories
    assert left.outcomes == right.outcomes
    assert left.issues == right.issues
    assert left.provenance == right.provenance
    assert [(e.content, e.origin, e.authorship) for e in left.receipts.entries] == [
        (e.content, e.origin, e.authorship) for e in right.receipts.entries
    ]


def _ba_workbook(rows: list[tuple[datetime, float | None]]) -> bytes:
    document = openpyxl.Workbook()
    sheet = document.active
    assert sheet is not None
    for row in [
        ("#Station Name", "Test station"),
        ("#Station Number", "4024"),
        ("#Station Parameter Name", "Vodostaj"),
        ("#Timeseries Name", "81 Web Kontinuirani"),
        ("#Unit Symbol", "cm"),
        ("#Rows", len(rows)),
        ("#", None),
        ("#Timestamp", "Value"),
        *rows,
    ]:
        sheet.append(row)
    stream = BytesIO()
    document.save(stream)
    document.close()
    return stream.getvalue()


@pytest.mark.parametrize("receipts", [ReceiptMode.OMIT, ReceiptMode.INCLUDE])
@pytest.mark.parametrize("empty_workbook", [False, True])
def test_ba_fhmzbih_reuses_metadata_interpretation_and_matches_parse_baseline(
    monkeypatch: pytest.MonkeyPatch,
    receipts: ReceiptMode,
    empty_workbook: bool,
) -> None:
    from rivretrieve._internal.providers.ba_fhmzbih import fetch as ba_fetch_mod
    from rivretrieve._internal.providers.ba_fhmzbih import parse as ba_parse_mod
    from rivretrieve._internal.providers.ba_fhmzbih.config import config, window_declarations

    workbook_bytes = _ba_workbook(
        [] if empty_workbook else [(datetime(2025, 9, 4, 0), 10.0), (datetime(2025, 9, 4, 1), None)]
    )
    meta_bytes = json.dumps(
        [
            {"metadata_station_no": "4024", "metadata_site_no": "site-7"},
            {"metadata_station_no": "9999", "metadata_site_no": "site-9"},
        ]
    ).encode()

    class _Transport:
        def send(self, request):
            if request.url.endswith("index.json"):
                return TransportResponse(
                    meta_bytes,
                    200,
                    datetime(2026, 9, 28, tzinfo=UTC),
                    "application/json",
                    request.url,
                    {},
                )
            return TransportResponse(
                workbook_bytes,
                200,
                datetime(2026, 9, 28, 1, tzinfo=UTC),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                request.url,
                {},
            )

    req = ObservationRequest(
        provider_id=ProviderId("ba_fhmzbih"),
        stations=("4024",),
        products=(ProductId("stage_reported"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2025, 9, 4)),
            WindowEndpoint.from_datetime(datetime(2025, 9, 4, 23, 59, 59)),
        ),
    )

    json_calls = 0
    real_loads = json.loads

    def counted_loads(*args: Any, **kwargs: Any) -> Any:
        nonlocal json_calls
        json_calls += 1
        return real_loads(*args, **kwargs)

    parse_coords: list[type[object]] = []
    real_parse = ba_parse_mod.parse

    def spied_parse(payload: Payload, cfg: ProviderConfig) -> Any:
        parse_coords.append(type(payload.source_coordinates.value))
        return real_parse(payload, cfg)

    monkeypatch.setattr(json, "loads", counted_loads)

    captured: list[SourceAcquisition] = []

    class _Stages:
        pass

    _Stages.config = config()
    _Stages.window_declarations = window_declarations()

    def _recording_fetch(*args: Any, **kwargs: Any) -> SourceAcquisition:
        acq = ba_fetch_mod.fetch(*args, **kwargs)
        assert isinstance(acq, SourceAcquisition)
        assert len(acq.interpretations) == 1
        captured.append(acq)
        return acq

    _Stages.fetch = staticmethod(_recording_fetch)
    _Stages.parse = staticmethod(spied_parse)

    result = driver_module.drive(req, _Stages(), provenance=_provenance(req), transport=_Transport(), receipts=receipts)

    assert json_calls == 1
    assert parse_coords == [ba_fetch_mod.BaFhmzbihSourceCoordinates]

    class _BaselineStages:
        pass

    _BaselineStages.config = config()
    _BaselineStages.window_declarations = window_declarations()
    _BaselineStages.fetch = staticmethod(lambda *args, **kwargs: replace(captured[0], interpretations=()))
    _BaselineStages.parse = staticmethod(real_parse)

    baseline = driver_module.drive(req, _BaselineStages(), provenance=_provenance(req), receipts=receipts)
    _assert_driver_results_identical(result, baseline)


@pytest.mark.parametrize(
    "bad_meta", [b"{not-json", json.dumps([{"metadata_station_no": "9999", "metadata_site_no": "x"}]).encode()]
)
def test_ba_fhmzbih_reuses_malformed_metadata_interpretation_and_enforces_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
    bad_meta: bytes,
) -> None:
    from rivretrieve._internal.providers.ba_fhmzbih import fetch as ba_fetch_mod
    from rivretrieve._internal.providers.ba_fhmzbih import parse as ba_parse_mod
    from rivretrieve._internal.providers.ba_fhmzbih.config import config, window_declarations

    class _Transport:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def send(self, request):
            self.calls.append(request.url)
            return TransportResponse(
                bad_meta,
                200,
                datetime(2026, 9, 28, tzinfo=UTC),
                "application/json",
                request.url,
                {},
            )

    req = ObservationRequest(
        provider_id=ProviderId("ba_fhmzbih"),
        stations=("4024",),
        products=(ProductId("stage_reported"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2025, 9, 4)),
            WindowEndpoint.from_datetime(datetime(2025, 9, 4, 23, 59, 59)),
        ),
    )

    json_calls = 0
    real_loads = json.loads

    def counted_loads(*args: Any, **kwargs: Any) -> Any:
        nonlocal json_calls
        json_calls += 1
        return real_loads(*args, **kwargs)

    parse_calls = 0
    real_parse = ba_parse_mod.parse

    def spied_parse(payload: Payload, cfg: ProviderConfig) -> Any:
        nonlocal parse_calls
        parse_calls += 1
        return real_parse(payload, cfg)

    monkeypatch.setattr(json, "loads", counted_loads)

    transport = _Transport()
    captured: list[SourceAcquisition] = []

    class _Stages:
        pass

    _Stages.config = config()
    _Stages.window_declarations = window_declarations()

    def _recording_fetch(*args: Any, **kwargs: Any) -> SourceAcquisition:
        acq = ba_fetch_mod.fetch(*args, **kwargs)
        assert isinstance(acq, SourceAcquisition)
        assert len(acq.interpretations) == 1
        captured.append(acq)
        return acq

    _Stages.fetch = staticmethod(_recording_fetch)
    _Stages.parse = staticmethod(spied_parse)

    result = driver_module.drive(req, _Stages(), provenance=_provenance(req), transport=transport)
    assert len(transport.calls) == 1
    assert json_calls == 1
    assert parse_calls == 0
    assert any(o.status is OutcomeStatus.UNSUPPORTED for o in result.outcomes)
    assert any(issue.code == "unsupported_source_structure" for issue in result.issues)

    class _BaselineStages:
        pass

    _BaselineStages.config = config()
    _BaselineStages.window_declarations = window_declarations()
    _BaselineStages.fetch = staticmethod(lambda *args, **kwargs: replace(captured[0], interpretations=()))
    _BaselineStages.parse = staticmethod(real_parse)

    baseline = driver_module.drive(req, _BaselineStages(), provenance=_provenance(req))
    _assert_driver_results_identical(result, baseline)

    # Context mismatch (scope differs from the handed-off interpretation) forces fallback to parse().
    mismatched_acq = replace(
        captured[0],
        value=(replace(captured[0].value[0], scope=SeriesScope(provider_ids=("ba_fhmzbih",), station_ids=("other",))),),
    )

    class _FallbackStages:
        pass

    _FallbackStages.config = config()
    _FallbackStages.window_declarations = window_declarations()
    _FallbackStages.fetch = staticmethod(lambda *args, **kwargs: mismatched_acq)
    _FallbackStages.parse = staticmethod(spied_parse)

    fallback_res = driver_module.drive(req, _FallbackStages(), provenance=_provenance(req))
    assert parse_calls == 1
    assert any(o.status is OutcomeStatus.UNSUPPORTED for o in fallback_res.outcomes)

    # Undeclared product in metadata interpretation raises FatalContractError.
    bad_meta_payload = replace(
        captured[0].value[0],
        station_products=(("4024", ProductId("undeclared_product")),),
    )
    with pytest.raises(FatalContractError, match="undeclared product"):
        ba_parse_mod.interpret_metadata_payload(bad_meta_payload, config())


@pytest.mark.parametrize("receipts", [ReceiptMode.OMIT, ReceiptMode.INCLUDE])
def test_ch_foen_reuses_archive_and_recent_interpretations_with_exact_parity(
    monkeypatch: pytest.MonkeyPatch,
    receipts: ReceiptMode,
) -> None:
    import gc
    import weakref

    from rivretrieve._internal.providers.ch_foen import official_fetch as foen_fetch_mod
    from rivretrieve._internal.providers.ch_foen import official_parse as foen_parse_mod
    from rivretrieve._internal.providers.ch_foen.official_config import config, window_declarations
    from rivretrieve._internal.providers.ch_foen.official_series import source_series

    recent_series = source_series(
        "2018",
        "data_live",
        "Q",
        None,
        units=("l/s",),
        evidence="synthetic:station-unit",
        temporal_evidence="synthetic:time",
        origin="catalogue",
    )

    archive_doc = {
        "data": {
            "water": {
                "observations": {
                    "data_1day_mean": [
                        {
                            "station": {"no": "2018"},
                            "parameterName": "Q",
                            "tsName": "TagMittel",
                            "unitSymbol": "m3/s",
                            "timestamp": "2025-01-01T23:00:00Z",
                            "value": 12.5,
                            "releaseState": "3",
                        },
                        {
                            "station": {"no": "2018"},
                            "parameterName": "Q",
                            "tsName": "TagMittel_01",
                            "unitSymbol": "l/s",
                            "timestamp": "2025-01-01T23:00:00Z",
                            "value": None,
                            "releaseState": None,
                        },
                    ]
                }
            }
        }
    }
    recent_doc = {
        "data": {
            "water": {
                "observations": {
                    "data_live": [
                        {
                            "stationNo": "2018",
                            "parameterName": "Q",
                            "timestamp": "2025-01-02T00:00:00Z",
                            "value": 1200.0,
                            "releaseStatus": 0,
                        },
                        {
                            "stationNo": "2018",
                            "parameterName": "Q",
                            "timestamp": "2025-01-02T00:10:00Z",
                            "value": None,
                            "releaseStatus": None,
                        },
                    ]
                }
            }
        }
    }

    class _Transport:
        def send(self, request):
            doc = recent_doc if "data_live(" in request.body else archive_doc
            return TransportResponse(
                json.dumps(doc).encode(),
                200,
                datetime(2026, 1, 1, tzinfo=UTC),
                "application/json",
                request.url,
                {},
            )

    req = ObservationRequest(
        provider_id=ProviderId("ch_foen"),
        stations=("2018",),
        products=(ProductId("discharge_1day_mean"), ProductId("discharge_recent")),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2025, 1, 2)),
            WindowEndpoint.from_datetime(datetime(2025, 1, 2, 23, 59, 59)),
        ),
        known_series=(recent_series,),
    )

    json_calls = 0
    real_loads = json.loads
    decoded_refs: list[weakref.ref[object]] = []

    class _WeakDict(dict):  # type: ignore[type-arg]
        pass

    def counted_loads(raw: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal json_calls
        json_calls += 1
        obj = real_loads(raw, *args, object_hook=_WeakDict, **kwargs)
        if isinstance(obj, _WeakDict) and "data" in obj:
            decoded_refs.append(weakref.ref(obj))
        return obj

    parse_calls = 0
    real_parse = foen_parse_mod.parse

    def spied_parse(payload: Payload, cfg: ProviderConfig) -> Any:
        nonlocal parse_calls
        parse_calls += 1
        return real_parse(payload, cfg)

    monkeypatch.setattr(json, "loads", counted_loads)
    captured: list[SourceAcquisition] = []

    class _Stages:
        pass

    _Stages.config = config()
    _Stages.window_declarations = window_declarations()

    def _recording_fetch(*args: Any, **kwargs: Any) -> SourceAcquisition:
        acq = foen_fetch_mod.fetch(*args, **kwargs)
        assert len(acq.interpretations) == 1
        captured.append(acq)
        return acq

    _Stages.fetch = staticmethod(_recording_fetch)
    _Stages.parse = staticmethod(spied_parse)

    result = driver_module.drive(req, _Stages(), provenance=_provenance(req), transport=_Transport(), receipts=receipts)
    gc.collect()

    assert len(captured) == 2
    assert json_calls == 2
    assert parse_calls == 0
    assert all(ref() is None for ref in decoded_refs)

    assert result.canonical_rows.height == 4

    class _BaselineStages:
        pass

    _BaselineStages.config = config()
    _BaselineStages.window_declarations = window_declarations()
    it = iter(captured)
    _BaselineStages.fetch = staticmethod(lambda *args, **kwargs: replace(next(it), interpretations=()))
    _BaselineStages.parse = staticmethod(real_parse)

    baseline = driver_module.drive(req, _BaselineStages(), provenance=_provenance(req), receipts=receipts)
    _assert_driver_results_identical(result, baseline)


def test_ch_foen_overflow_subdivision_malformed_row_and_refresh_failure_parity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import re
    import types
    from datetime import timedelta
    from functools import partial

    from rivretrieve._internal.providers.ch_foen import official_fetch as foen_fetch_mod
    from rivretrieve._internal.providers.ch_foen import official_parse as foen_parse_mod
    from rivretrieve._internal.providers.ch_foen.official_config import config, window_declarations
    from rivretrieve._internal.providers.ch_foen.official_series import source_series
    from rivretrieve._internal.source_series import RestrictionKind
    from rivretrieve._internal.store import StoreRoot

    archive_series = source_series(
        "2018",
        "data_10min_mean",
        "Q",
        "Variant",
        units=("m3/s",),
        evidence="synthetic:unit",
        temporal_evidence="synthetic:time",
        origin="catalogue",
    )
    req = ObservationRequest(
        provider_id=ProviderId("ch_foen"),
        stations=("2018",),
        products=(ProductId("discharge_10min_mean"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2025, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2025, 1, 1, 0, 0, 3)),
        ),
        known_series=(archive_series,),
        scope=SeriesScope(restriction=RestrictionKind.EXPLICIT, series_ids=(archive_series.series_id,)),
    )

    class _OverflowTransport:
        phase = "initial"

        def send(self, request):
            body = request.body.replace('\\"', '"')
            start, end = [
                datetime.fromisoformat(item).replace(tzinfo=None)
                for item in re.findall(r'_(?:gte|lt): "([^"]+)"', body)
            ]
            if self.phase in {"refresh_fail_http502", "non_2xx_302"}:
                code = 302 if self.phase == "non_2xx_302" else 502
                body_bytes = b"<html>redirect</html>" if code == 302 else b"bad-gateway"
                return TransportResponse(
                    body_bytes,
                    code,
                    datetime(2026, 1, 1, tzinfo=UTC),
                    "text/plain",
                    request.url,
                    {},
                )
            if (end - start) > timedelta(days=3) and self.phase == "overflow_ok":
                doc = {
                    "data": None,
                    "errors": [
                        {
                            "errorType": "ValidationError",
                            "message": (
                                "Query returned more than 10000 rows. Please narrow your query using filters or "
                                "specify a limit."
                            ),
                            "path": ["water", "observations", "data_10min_mean"],
                        }
                    ],
                }
            elif self.phase == "overflow_ok" and start >= datetime(2025, 1, 1, 0, 0, 1):
                # Malformed unitSymbol triggers bounded FAILED ParsedSeries on second child.
                doc = {
                    "data": {
                        "water": {
                            "observations": {
                                "data_10min_mean": [
                                    {
                                        "station": {"no": "2018"},
                                        "parameterName": "Q",
                                        "tsName": "Variant",
                                        "unitSymbol": [],
                                        "timestamp": "2025-01-01T00:00:02Z",
                                        "value": 12.0,
                                    }
                                ]
                            }
                        }
                    }
                }
            else:
                rows = [
                    {
                        "station": {"no": "2018"},
                        "parameterName": "Q",
                        "tsName": "Variant",
                        "unitSymbol": "m3/s",
                        "timestamp": stamp.isoformat() + "Z",
                        "value": value,
                        "releaseState": "3",
                    }
                    for stamp, value in [
                        (datetime(2025, 1, 1, 0, 0, 0), 10.0),
                        (datetime(2025, 1, 1, 0, 0, 2), 12.0),
                    ]
                    if start <= stamp < end
                ]
                doc = {"data": {"water": {"observations": {"data_10min_mean": rows}}}}
            return TransportResponse(
                json.dumps(doc).encode(),
                200,
                datetime(2026, 1, 1, tzinfo=UTC),
                "application/json",
                request.url,
                {},
            )

    transport = _OverflowTransport()
    store_impl = StoreRoot(tmp_path / "store_impl")

    json_calls = 0
    real_loads = json.loads

    def counted_loads(raw: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal json_calls
        json_calls += 1
        return real_loads(raw, *args, **kwargs)

    parse_calls = 0
    real_parse = foen_parse_mod.parse

    def spied_parse(payload: Payload, cfg: ProviderConfig) -> Any:
        nonlocal parse_calls
        parse_calls += 1
        return real_parse(payload, cfg)

    fetch_with_precision = partial(foen_fetch_mod.fetch, timestamp_precision=timedelta(seconds=1))
    captured: list[SourceAcquisition] = []

    class _Stages:
        pass

    _Stages.config = config()
    _Stages.window_declarations = window_declarations()

    def _recording_fetch(*args: Any, **kwargs: Any) -> SourceAcquisition:
        acq = fetch_with_precision(*args, **kwargs)
        captured.append(acq)
        return acq

    _Stages.fetch = staticmethod(_recording_fetch)
    _Stages.parse = staticmethod(spied_parse)

    # Seed cache in initial phase and retain exact seed acquisition for baseline parity.
    driver_module.drive(
        req, _Stages(), provenance=_provenance(req), transport=transport, cache="refresh", store=store_impl
    )
    assert parse_calls == 0
    assert len(captured) == 1
    seed_acq = captured[0]

    counted_json = types.SimpleNamespace(loads=counted_loads, dumps=json.dumps)

    # Phase 2: overflow + one valid child + one malformed-unit child.
    transport.phase = "overflow_ok"
    json_calls = 0
    captured.clear()
    monkeypatch.setattr(foen_fetch_mod, "json", counted_json)
    monkeypatch.setattr(foen_parse_mod, "json", counted_json)
    impl_overflow = driver_module.drive(
        req, _Stages(), provenance=_provenance(req), transport=transport, cache="bypass"
    )
    # 1 overflow parent + 2 children = 3 json.loads (0 driver parse calls; 0 json.loads from parse).
    assert json_calls == 3
    assert parse_calls == 0
    assert len(captured) == 1
    assert len(captured[0].interpretations) == 2

    class _BaselineStages:
        pass

    _BaselineStages.config = config()
    _BaselineStages.window_declarations = window_declarations()
    _BaselineStages.fetch = staticmethod(lambda *args, **kwargs: replace(captured[0], interpretations=()))
    _BaselineStages.parse = staticmethod(real_parse)
    monkeypatch.setattr(foen_fetch_mod, "json", json)
    monkeypatch.setattr(foen_parse_mod, "json", json)
    base_overflow = driver_module.drive(req, _BaselineStages(), provenance=_provenance(req), cache="bypass")
    _assert_driver_results_identical(impl_overflow, base_overflow)

    # Phase 3: refresh with HTTP 502 keeps held data and skips JSON decode on 502.
    transport.phase = "refresh_fail_http502"
    captured.clear()
    json_calls = 0
    monkeypatch.setattr(foen_fetch_mod, "json", counted_json)
    monkeypatch.setattr(foen_parse_mod, "json", counted_json)
    impl_fail = driver_module.drive(
        req, _Stages(), provenance=_provenance(req), transport=transport, cache="refresh", store=store_impl
    )
    assert json_calls == 0
    assert parse_calls == 0
    assert len(captured) == 1
    fail_acq = captured[0]
    assert impl_fail.canonical_rows.sort("time")["value"].to_list() == [10.0, 12.0]
    assert any(o.status is OutcomeStatus.FAILED and "HTTP 502" in (o.reason or "") for o in impl_fail.outcomes)

    monkeypatch.setattr(foen_fetch_mod, "json", json)
    monkeypatch.setattr(foen_parse_mod, "json", json)
    # Seed store_base2 with identical Phase 1 acquisition, then replay Phase 3 fail_acq without interpretations.
    store_base2 = StoreRoot(tmp_path / "store_base2")
    driver_module.drive(
        req,
        type(
            "SeedBase",
            (),
            {
                "config": config(),
                "window_declarations": window_declarations(),
                "fetch": staticmethod(lambda *a, **kw: replace(seed_acq, interpretations=())),
                "parse": staticmethod(real_parse),
            },
        )(),
        provenance=_provenance(req),
        transport=transport,
        cache="refresh",
        store=store_base2,
    )
    _BaselineStages.fetch = staticmethod(lambda *args, **kwargs: replace(fail_acq, interpretations=()))
    base_fail = driver_module.drive(
        req, _BaselineStages(), provenance=_provenance(req), cache="refresh", store=store_base2
    )
    _assert_driver_results_identical(impl_fail, base_fail)

    # Phase 4: non-2xx (e.g. HTTP 302 redirect) skips JSON decode cleanly both via driver and directly via fetch().
    transport.phase = "non_2xx_302"
    captured.clear()
    json_calls = 0
    monkeypatch.setattr(foen_fetch_mod, "json", counted_json)
    monkeypatch.setattr(foen_parse_mod, "json", counted_json)
    res_302 = driver_module.drive(req, _Stages(), provenance=_provenance(req), transport=transport, cache="bypass")
    assert json_calls == 0
    assert parse_calls == 0
    assert any(o.status is OutcomeStatus.FAILED and "HTTP 302" in (o.reason or "") for o in res_302.outcomes)

    from rivretrieve._internal.engine import _make_fetch_window as _mk_fw
    from rivretrieve._internal.window_planning import plan_windows as foen_plan_windows

    fw_direct = _mk_fw(req.window.start, req.window.end)
    rendered_direct = {
        ProductId("discharge_10min_mean"): foen_plan_windows(
            fw_direct, window_declarations().products[ProductId("discharge_10min_mean")]
        )
    }
    direct_302 = fetch_with_precision(
        ("2018",),
        (ProductId("discharge_10min_mean"),),
        rendered_direct,
        fw_direct,
        config(),
        transport,
    )
    assert json_calls == 0
    assert direct_302.value == ()
    assert direct_302.interpretations == ()
    assert len(direct_302.outcomes) == 1
    assert direct_302.outcomes[0].status is OutcomeStatus.FAILED
    assert direct_302.outcomes[0].reason == "Source returned HTTP 302"
    monkeypatch.setattr(foen_fetch_mod, "json", json)
    monkeypatch.setattr(foen_parse_mod, "json", json)


def test_ch_foen_data_live_context_mismatch_falls_back_to_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    from rivretrieve._internal.providers.ch_foen import official_fetch as foen_fetch_mod
    from rivretrieve._internal.providers.ch_foen import official_parse as foen_parse_mod
    from rivretrieve._internal.providers.ch_foen.official_config import config, window_declarations
    from rivretrieve._internal.providers.ch_foen.official_series import source_series

    recent_series = source_series(
        "2018",
        "data_live",
        "Q",
        None,
        units=("l/s",),
        evidence="synthetic:station-unit",
        temporal_evidence="synthetic:time",
        origin="catalogue",
    )
    doc = {
        "data": {
            "water": {
                "observations": {
                    "data_live": [
                        {
                            "stationNo": "2018",
                            "parameterName": "Q",
                            "timestamp": "2025-01-02T00:00:00Z",
                            "value": 100.0,
                            "releaseStatus": 0,
                        }
                    ]
                }
            }
        }
    }

    class _Transport:
        def send(self, request):
            return TransportResponse(
                json.dumps(doc).encode(),
                200,
                datetime(2026, 1, 1, tzinfo=UTC),
                "application/json",
                request.url,
                {},
            )

    req = ObservationRequest(
        provider_id=ProviderId("ch_foen"),
        stations=("2018",),
        products=(ProductId("discharge_recent"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2025, 1, 2)),
            WindowEndpoint.from_datetime(datetime(2025, 1, 2)),
        ),
        known_series=(recent_series,),
    )

    parse_calls = 0
    real_parse = foen_parse_mod.parse

    def spied_parse(payload: Payload, cfg: ProviderConfig) -> Any:
        nonlocal parse_calls
        parse_calls += 1
        return real_parse(payload, cfg)

    class _Stages:
        pass

    _Stages.config = config()
    _Stages.window_declarations = window_declarations()
    # Deliberately call real fetch with known_series=(), reproducing driver's `or pair_series` substitution.
    _Stages.fetch = staticmethod(
        lambda stations, products, rendered, fw, cfg, tr, *, scope=None, known_series=(): foen_fetch_mod.fetch(
            stations, products, rendered, fw, cfg, tr, scope=scope, known_series=()
        )
    )
    _Stages.parse = staticmethod(spied_parse)

    res = driver_module.drive(req, _Stages(), provenance=_provenance(req), transport=_Transport())
    assert parse_calls == 1
    assert res.canonical_rows["value"].to_list() == [pytest.approx(0.1)]
    assert any(o.status is OutcomeStatus.SUCCESS for o in res.outcomes)
    # Also ensure recent empty response reuses UNRESOLVED outcome cleanly when context matches.
    empty_doc = {"data": {"water": {"observations": {"data_live": []}}}}

    class _EmptyTransport:
        def send(self, request):
            return TransportResponse(
                json.dumps(empty_doc).encode(),
                200,
                datetime(2026, 1, 1, tzinfo=UTC),
                "application/json",
                request.url,
                {},
            )

    parse_calls = 0
    _Stages.fetch = staticmethod(foen_fetch_mod.fetch)
    empty_res = driver_module.drive(req, _Stages(), provenance=_provenance(req), transport=_EmptyTransport())
    assert parse_calls == 0
    assert any(o.status is OutcomeStatus.UNRESOLVED for o in empty_res.outcomes)


@pytest.mark.parametrize("receipts", [ReceiptMode.OMIT, ReceiptMode.INCLUDE])
@pytest.mark.parametrize(
    ("product_id", "rows_builder"),
    [
        (
            "discharge_reported",
            lambda p, a, v, f: {"Paikka_Id": p, "Aika": a, "Arvo": v, "Lippu_id": f},
        ),
        (
            "stage_reported",
            lambda p, a, v, f: {"Paikka_Id": p, "Aika": a, "Arvo": v, "Lippu_id": f},
        ),
        (
            "water_temperature_reported",
            lambda p, a, v: {"Paikka_Id": p, "Aika": a, "Arvo": v},
        ),
    ],
)
def test_fi_syke_three_page_pagination_single_decode_and_parity(
    monkeypatch: pytest.MonkeyPatch,
    receipts: ReceiptMode,
    product_id: str,
    rows_builder: Any,
) -> None:
    import types

    from rivretrieve._internal.providers.fi_syke import fetch as syke_fetch_mod
    from rivretrieve._internal.providers.fi_syke import parse as syke_parse_mod
    from rivretrieve._internal.providers.fi_syke.config import config, window_declarations
    from rivretrieve._internal.providers.fi_syke.series import describe_series

    series = describe_series("894", product_id)
    req = ObservationRequest(
        provider_id=ProviderId("fi_syke"),
        stations=("894",),
        products=(ProductId(product_id),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(1959, 1, 1)),
            WindowEndpoint.from_datetime(datetime(1959, 1, 5)),
        ),
        known_series=(series,),
    )

    def _row(day: int, val: object, flag: int | None = None) -> dict[str, object]:
        stamp = f"1959-01-{day:02d}T00:00:00"
        if product_id == "water_temperature_reported":
            return rows_builder(894, stamp, val)
        return rows_builder(894, stamp, val, flag)

    class _ThreePageTransport:
        def __init__(self) -> None:
            self.step = 0

        def send(self, request):
            base = request.url
            q = f"$filter={request.params['$filter'].replace(' ', '%20')}&$orderby=Aika%20asc"
            if self.step == 0:
                doc = {
                    "odata.metadata": "x",
                    "value": [_row(1, "10.0", 1), _row(2, None, None)],
                    "odata.nextLink": f"{base}?{q}&$skip=2",
                }
            elif self.step == 1:
                doc = {
                    "odata.metadata": "x",
                    "value": [],
                    "odata.nextLink": f"{base}?{q}&$skip=4",
                }
            else:
                doc = {
                    "odata.metadata": "x",
                    "value": [_row(3, 15.5, 2)],
                }
            self.step += 1
            return TransportResponse(
                json.dumps(doc).encode(),
                200,
                datetime(2026, 11, 8, tzinfo=UTC),
                "application/json",
                request.url,
                dict(request.params or {}),
            )

    json_calls = 0
    real_loads = json.loads

    def counted_loads(raw: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal json_calls
        json_calls += 1
        return real_loads(raw, *args, **kwargs)

    parse_calls = 0
    real_parse = syke_parse_mod.parse

    def spied_parse(payload: Payload, cfg: ProviderConfig) -> Any:
        nonlocal parse_calls
        parse_calls += 1
        return real_parse(payload, cfg)

    captured: list[SourceAcquisition] = []

    class _Stages:
        pass

    _Stages.config = config()
    _Stages.window_declarations = window_declarations()

    def _recording_fetch(*args: Any, **kwargs: Any) -> SourceAcquisition:
        acq = syke_fetch_mod.fetch(*args, **kwargs)
        captured.append(acq)
        return acq

    _Stages.fetch = staticmethod(_recording_fetch)
    _Stages.parse = staticmethod(spied_parse)

    counted_json = types.SimpleNamespace(loads=counted_loads, JSONDecodeError=json.JSONDecodeError)
    monkeypatch.setattr(syke_parse_mod, "json", counted_json)
    if hasattr(syke_fetch_mod, "json"):
        monkeypatch.setattr(syke_fetch_mod, "json", counted_json)

    impl = driver_module.drive(
        req,
        _Stages(),
        provenance=_provenance(req),
        transport=_ThreePageTransport(),
        receipts=receipts,
    )
    assert json_calls == 3
    assert parse_calls == 0
    assert len(captured) == 1
    assert len(captured[0].value) == 3
    assert len(captured[0].interpretations) == 3

    class _BaselineStages:
        pass

    _BaselineStages.config = config()
    _BaselineStages.window_declarations = window_declarations()
    _BaselineStages.fetch = staticmethod(lambda *a, **kw: replace(captured[0], interpretations=()))
    _BaselineStages.parse = staticmethod(real_parse)
    monkeypatch.setattr(syke_parse_mod, "json", json)
    if hasattr(syke_fetch_mod, "json"):
        monkeypatch.setattr(syke_fetch_mod, "json", json)
    base = driver_module.drive(
        req,
        _BaselineStages(),
        provenance=_provenance(req),
        receipts=receipts,
    )
    _assert_driver_results_identical(impl, base)


def test_fi_syke_late_page_failure_cycle_and_bad_nextlink_parity(monkeypatch: pytest.MonkeyPatch) -> None:
    import types

    from rivretrieve._internal.providers.fi_syke import fetch as syke_fetch_mod
    from rivretrieve._internal.providers.fi_syke import parse as syke_parse_mod
    from rivretrieve._internal.providers.fi_syke.config import config, window_declarations
    from rivretrieve._internal.providers.fi_syke.series import describe_series
    from rivretrieve._internal.transport import TransportFailure, TransportFailureCategory, TransportFailureReason

    series_q = describe_series("894", "discharge_reported")
    series_h = describe_series("894", "stage_reported")

    def _run_case(transport: Any, product_id: str, series_obj: Any, expected_pages: int) -> None:
        req = ObservationRequest(
            provider_id=ProviderId("fi_syke"),
            stations=("894",),
            products=(ProductId(product_id),),
            window=RequestedWindow(
                WindowEndpoint.from_datetime(datetime(1959, 1, 1)),
                WindowEndpoint.from_datetime(datetime(1959, 1, 5)),
            ),
            known_series=(series_obj,),
        )
        json_calls = 0
        real_loads = json.loads

        def counted_loads(raw: Any, *args: Any, **kwargs: Any) -> Any:
            nonlocal json_calls
            json_calls += 1
            return real_loads(raw, *args, **kwargs)

        parse_calls = 0
        real_parse = syke_parse_mod.parse

        def spied_parse(payload: Payload, cfg: ProviderConfig) -> Any:
            nonlocal parse_calls
            parse_calls += 1
            return real_parse(payload, cfg)

        captured: list[SourceAcquisition] = []

        class _Stages:
            pass

        _Stages.config = config()
        _Stages.window_declarations = window_declarations()
        _Stages.fetch = staticmethod(lambda *a, **kw: captured.append(r := syke_fetch_mod.fetch(*a, **kw)) or r)
        _Stages.parse = staticmethod(spied_parse)

        counted_json = types.SimpleNamespace(loads=counted_loads, JSONDecodeError=json.JSONDecodeError)
        monkeypatch.setattr(syke_parse_mod, "json", counted_json)
        if hasattr(syke_fetch_mod, "json"):
            monkeypatch.setattr(syke_fetch_mod, "json", counted_json)
        impl = driver_module.drive(req, _Stages(), provenance=_provenance(req), transport=transport)
        assert json_calls == expected_pages
        assert parse_calls == 0

        class _BaselineStages:
            pass

        _BaselineStages.config = config()
        _BaselineStages.window_declarations = window_declarations()
        _BaselineStages.fetch = staticmethod(lambda *a, **kw: replace(captured[0], interpretations=()))
        _BaselineStages.parse = staticmethod(real_parse)
        monkeypatch.setattr(syke_parse_mod, "json", json)
        if hasattr(syke_fetch_mod, "json"):
            monkeypatch.setattr(syke_fetch_mod, "json", json)
        base = driver_module.drive(req, _BaselineStages(), provenance=_provenance(req))
        _assert_driver_results_identical(impl, base)

    # Case 1: Late-page transport failure preserves page 1 + failed_requests.
    class _LateFailTransport:
        def __init__(self) -> None:
            self.n = 0

        def send(self, request):
            self.n += 1
            if self.n == 2:
                raise TransportFailure(
                    request,
                    TransportFailureReason.HTTP_STATUS,
                    1,
                    status_code=503,
                    category=TransportFailureCategory.HTTP_STATUS,
                )
            doc = {
                "value": [{"Paikka_Id": 894, "Aika": "1959-01-01T00:00:00", "Arvo": 4.0, "Lippu_id": None}],
                "odata.nextLink": (
                    f"{request.url}?$filter={request.params['$filter'].replace(' ', '%20')}&$orderby=Aika%20asc&$skip=1"
                ),
            }
            return TransportResponse(
                json.dumps(doc).encode(),
                200,
                datetime(2026, 11, 8, tzinfo=UTC),
                "application/json",
                request.url,
                dict(request.params or {}),
            )

    _run_case(_LateFailTransport(), "discharge_reported", series_q, expected_pages=1)

    # Case 2: Pagination cycle stops cleanly after 2 pages without extra issues/outcomes.
    class _CycleTransport:
        def __init__(self) -> None:
            self.n = 0

        def send(self, request):
            self.n += 1
            doc = {
                "value": [{"Paikka_Id": 894, "Aika": f"1959-01-0{self.n}T00:00:00", "Arvo": 100.0, "Lippu_id": None}],
                "odata.nextLink": (
                    f"{request.url}?$filter={request.params['$filter'].replace(' ', '%20')}&$orderby=Aika%20asc&$skip=1"
                ),
            }
            return TransportResponse(
                json.dumps(doc).encode(),
                200,
                datetime(2026, 11, 8, tzinfo=UTC),
                "application/json",
                request.url,
                dict(request.params or {}),
            )

    _run_case(_CycleTransport(), "stage_reported", series_h, expected_pages=2)

    # Case 3: Malformed odata.nextLink stops cleanly with 1 page.
    class _BadLinkTransport:
        def send(self, request):
            doc = {
                "value": [{"Paikka_Id": 894, "Aika": "1959-01-01T00:00:00", "Arvo": 7.0, "Lippu_id": None}],
                "odata.nextLink": "https://evil.example/other?$skip=1",
            }
            return TransportResponse(
                json.dumps(doc).encode(),
                200,
                datetime(2026, 11, 8, tzinfo=UTC),
                "application/json",
                request.url,
                dict(request.params or {}),
            )

    _run_case(_BadLinkTransport(), "discharge_reported", series_q, expected_pages=1)

    # Case 4: Multi-product partial failure isolation (discharge succeeds, stage hits HTTP 503).
    class _MultiProductTransport:
        def send(self, request):
            if "Vedenkorkeus" in request.url:
                raise TransportFailure(
                    request,
                    TransportFailureReason.HTTP_STATUS,
                    1,
                    status_code=503,
                    category=TransportFailureCategory.HTTP_STATUS,
                )
            doc = {"value": [{"Paikka_Id": 894, "Aika": "1959-01-01T00:00:00", "Arvo": 9.0, "Lippu_id": 1}]}
            return TransportResponse(
                json.dumps(doc).encode(),
                200,
                datetime(2026, 11, 8, tzinfo=UTC),
                "application/json",
                request.url,
                dict(request.params or {}),
            )

    req_multi = ObservationRequest(
        provider_id=ProviderId("fi_syke"),
        stations=("894",),
        products=(ProductId("discharge_reported"), ProductId("stage_reported")),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(1959, 1, 1)),
            WindowEndpoint.from_datetime(datetime(1959, 1, 5)),
        ),
        known_series=(series_q, series_h),
    )
    parse_calls = 0
    captured_multi: list[SourceAcquisition] = []
    json_calls = 0

    def counted_loads_multi(raw: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal json_calls
        json_calls += 1
        return json.loads(raw, *args, **kwargs)

    real_parse_multi = syke_parse_mod.parse

    def spied_parse_multi(payload: Payload, cfg: ProviderConfig) -> Any:
        nonlocal parse_calls
        parse_calls += 1
        return real_parse_multi(payload, cfg)

    class _MultiStages:
        pass

    _MultiStages.config = config()
    _MultiStages.window_declarations = window_declarations()
    _MultiStages.fetch = staticmethod(lambda *a, **kw: captured_multi.append(r := syke_fetch_mod.fetch(*a, **kw)) or r)
    _MultiStages.parse = staticmethod(spied_parse_multi)

    monkeypatch.setattr(
        syke_parse_mod, "json", types.SimpleNamespace(loads=counted_loads_multi, JSONDecodeError=json.JSONDecodeError)
    )
    if hasattr(syke_fetch_mod, "json"):
        monkeypatch.setattr(
            syke_fetch_mod,
            "json",
            types.SimpleNamespace(loads=counted_loads_multi, JSONDecodeError=json.JSONDecodeError),
        )
    impl_multi = driver_module.drive(
        req_multi, _MultiStages(), provenance=_provenance(req_multi), transport=_MultiProductTransport()
    )
    assert json_calls == 1
    assert parse_calls == 0
    assert impl_multi.canonical_rows["value"].to_list() == [9.0]
    assert any(o.status is OutcomeStatus.FAILED for o in impl_multi.outcomes)

    replay_iter = iter(captured_multi)

    class _BaselineMultiStages:
        pass

    _BaselineMultiStages.config = config()
    _BaselineMultiStages.window_declarations = window_declarations()
    _BaselineMultiStages.fetch = staticmethod(lambda *a, **kw: replace(next(replay_iter), interpretations=()))
    _BaselineMultiStages.parse = staticmethod(real_parse_multi)

    monkeypatch.setattr(syke_parse_mod, "json", json)
    if hasattr(syke_fetch_mod, "json"):
        monkeypatch.setattr(syke_fetch_mod, "json", json)
    base_multi = driver_module.drive(req_multi, _BaselineMultiStages(), provenance=_provenance(req_multi))
    _assert_driver_results_identical(impl_multi, base_multi)


def test_fi_syke_malformed_page_and_row_preserve_fetch_contract_and_followup_paging() -> None:
    from types import MappingProxyType

    from rivretrieve._internal.engine import InterpretationContext, RenderedWindow, _make_fetch_window
    from rivretrieve._internal.provider_series import UnsupportedSourceStructureError
    from rivretrieve._internal.providers.fi_syke.config import config, window_declarations
    from rivretrieve._internal.providers.fi_syke.fetch import fetch
    from rivretrieve._internal.providers.fi_syke.parse import parse
    from rivretrieve._internal.providers.fi_syke.series import describe_series

    fw = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(1959, 1, 1)),
        WindowEndpoint.from_datetime(datetime(1959, 1, 5)),
    )
    rendered = MappingProxyType(
        {ProductId("discharge_reported"): (RenderedWindow(fw.start.isoformat() + "Z", fw.end.isoformat() + "Z", fw),)}
    )

    # Subcase A: Malformed JSON stops paging and omits interpretation without crashing fetch; parse raises.
    class _BadJsonTransport:
        def send(self, request):
            return TransportResponse(
                b"{not-json",
                200,
                datetime(2026, 11, 8, tzinfo=UTC),
                "application/json",
                request.url,
                dict(request.params or {}),
            )

    acq_bad_json = fetch(("894",), (ProductId("discharge_reported"),), rendered, fw, config(), _BadJsonTransport())
    assert len(acq_bad_json.value) == 1
    assert acq_bad_json.interpretations == ()
    with pytest.raises(UnsupportedSourceStructureError):
        parse(acq_bad_json.value[0], config())

    # Subcase A2: Non-list "value" also omits interpretation and stops paging even if odata.nextLink is present.
    class _NonListValueTransport:
        def __init__(self) -> None:
            self.calls = 0

        def send(self, request):
            self.calls += 1
            doc = {
                "value": "not-a-list",
                "odata.nextLink": (
                    f"{request.url}?$filter={request.params['$filter'].replace(' ', '%20')}&$orderby=Aika%20asc&$skip=1"
                ),
            }
            return TransportResponse(
                json.dumps(doc).encode(),
                200,
                datetime(2026, 11, 8, tzinfo=UTC),
                "application/json",
                request.url,
                dict(request.params or {}),
            )

    non_list_transport = _NonListValueTransport()
    acq_non_list = fetch(("894",), (ProductId("discharge_reported"),), rendered, fw, config(), non_list_transport)
    assert non_list_transport.calls == 1
    assert len(acq_non_list.value) == 1
    assert acq_non_list.interpretations == ()
    with pytest.raises(UnsupportedSourceStructureError):
        parse(acq_non_list.value[0], config())

    # Subcase B: Valid JSON envelope with malformed row still follows valid odata.nextLink to page 2!
    class _BadRowPagedTransport:
        def __init__(self) -> None:
            self.n = 0

        def send(self, request):
            self.n += 1
            if self.n == 1:
                doc = {
                    "value": [{"Paikka_Id": 894, "Arvo": 1.0, "Lippu_id": None}],  # missing Aika
                    "odata.nextLink": (
                        f"{request.url}?$filter={request.params['$filter'].replace(' ', '%20')}"
                        "&$orderby=Aika%20asc&$skip=1"
                    ),
                }
            else:
                doc = {
                    "value": [{"Paikka_Id": 894, "Aika": "1959-01-02T00:00:00", "Arvo": 2.0, "Lippu_id": None}],
                }
            return TransportResponse(
                json.dumps(doc).encode(),
                200,
                datetime(2026, 11, 8, tzinfo=UTC),
                "application/json",
                request.url,
                dict(request.params or {}),
            )

    acq_bad_row = fetch(("894",), (ProductId("discharge_reported"),), rendered, fw, config(), _BadRowPagedTransport())
    assert len(acq_bad_row.value) == 2
    assert len(acq_bad_row.interpretations) == 1
    assert acq_bad_row.interpretations[0].context == InterpretationContext.from_payload(acq_bad_row.value[1])
    assert acq_bad_row.interpretations[0].parsed.rows["value"].to_list() == [2.0]
    with pytest.raises(UnsupportedSourceStructureError):
        parse(acq_bad_row.value[0], config())

    # And through driver, malformed page still raises UnsupportedSourceStructureError.
    req = ObservationRequest(
        provider_id=ProviderId("fi_syke"),
        stations=("894",),
        products=(ProductId("discharge_reported"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(1959, 1, 1)),
            WindowEndpoint.from_datetime(datetime(1959, 1, 5)),
        ),
        known_series=(describe_series("894", "discharge_reported"),),
    )

    class _Stages:
        pass

    _Stages.config = config()
    _Stages.window_declarations = window_declarations()
    _Stages.fetch = staticmethod(fetch)
    _Stages.parse = staticmethod(parse)
    with pytest.raises(UnsupportedSourceStructureError):
        driver_module.drive(req, _Stages(), provenance=_provenance(req), transport=_BadRowPagedTransport())


def test_fi_syke_context_mismatch_falls_back_to_parse() -> None:
    from rivretrieve._internal.providers.fi_syke import fetch as syke_fetch_mod
    from rivretrieve._internal.providers.fi_syke import parse as syke_parse_mod
    from rivretrieve._internal.providers.fi_syke.config import config, window_declarations
    from rivretrieve._internal.providers.fi_syke.series import describe_series

    series = describe_series("894", "discharge_reported")
    req = ObservationRequest(
        provider_id=ProviderId("fi_syke"),
        stations=("894",),
        products=(ProductId("discharge_reported"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(1959, 1, 1)),
            WindowEndpoint.from_datetime(datetime(1959, 1, 5)),
        ),
        known_series=(series,),
    )

    class _Transport:
        def send(self, request):
            doc = {"value": [{"Paikka_Id": 894, "Aika": "1959-01-01T00:00:00", "Arvo": 5.0, "Lippu_id": None}]}
            return TransportResponse(
                json.dumps(doc).encode(),
                200,
                datetime(2026, 11, 8, tzinfo=UTC),
                "application/json",
                request.url,
                dict(request.params or {}),
            )

    parse_calls = 0
    real_parse = syke_parse_mod.parse

    def spied_parse(payload: Payload, cfg: ProviderConfig) -> Any:
        nonlocal parse_calls
        parse_calls += 1
        return real_parse(payload, cfg)

    class _Stages:
        pass

    _Stages.config = config()
    _Stages.window_declarations = window_declarations()
    _Stages.fetch = staticmethod(
        lambda stations, products, rendered, fw, cfg, tr, *, scope=None, known_series=(): syke_fetch_mod.fetch(
            stations, products, rendered, fw, cfg, tr, scope=None, known_series=()
        )
    )
    _Stages.parse = staticmethod(spied_parse)

    res = driver_module.drive(req, _Stages(), provenance=_provenance(req), transport=_Transport())
    assert parse_calls == 1
    assert res.canonical_rows["value"].to_list() == [5.0]

    # Also verify non-default attempts/attempt_traces flow through SourceCallOrigin.from_response cleanly.
    from rivretrieve._internal.transport import TransportAttempt

    class _TracedTransport:
        def send(self, request):
            doc = {"value": [{"Paikka_Id": 894, "Aika": "1959-01-01T00:00:00", "Arvo": 6.0, "Lippu_id": None}]}
            return TransportResponse(
                json.dumps(doc).encode(),
                200,
                datetime(2026, 11, 8, tzinfo=UTC),
                "application/json",
                request.url,
                dict(request.params or {}),
                attempts=2,
                attempt_traces=(
                    TransportAttempt(
                        attempt_id="syke-attempt-1",
                        url=request.url,
                        request_parameters=dict(request.params or {}),
                        retrieved_at=datetime(2026, 11, 8, tzinfo=UTC),
                        status_code=503,
                    ),
                    TransportAttempt(
                        attempt_id="syke-attempt-2",
                        url=request.url,
                        request_parameters=dict(request.params or {}),
                        retrieved_at=datetime(2026, 11, 8, tzinfo=UTC),
                        status_code=200,
                        content_type="application/json",
                    ),
                ),
            )

    parse_calls = 0
    captured_traced: list[SourceAcquisition] = []
    _Stages.fetch = staticmethod(lambda *a, **kw: captured_traced.append(r := syke_fetch_mod.fetch(*a, **kw)) or r)
    traced_res = driver_module.drive(req, _Stages(), provenance=_provenance(req), transport=_TracedTransport())
    assert parse_calls == 0
    assert traced_res.canonical_rows["value"].to_list() == [6.0]
    assert captured_traced[0].value[0].origin.attempts == 2
    assert len(captured_traced[0].value[0].attempt_traces) == 2

    # And FatalContractError propagates out of interpret_page/fetch without suppression.
    with pytest.raises(FatalContractError):
        syke_parse_mod.interpret_page(
            replace(
                captured_traced[0].value[0],
                station_products=(("894", ProductId("discharge_reported")), ("895", ProductId("stage_reported"))),
            ),
            config(),
        )
    with pytest.raises(FatalContractError):
        syke_fetch_mod.fetch(
            (),
            (ProductId("discharge_reported"),),
            {},
            captured_traced[0].value[0].fetch_window,
            config(),
            _TracedTransport(),
        )


def test_br_ana_telemetry_and_daily_single_decode_and_single_sha256(monkeypatch: pytest.MonkeyPatch) -> None:
    import hashlib
    import types

    from rivretrieve._internal.engine import SourceCallOrigin, UnknownOriginFact, _make_fetch_window
    from rivretrieve._internal.providers.br_ana import parse as ana_parse_mod
    from rivretrieve._internal.providers.br_ana.config import config

    cfg = config()
    fw = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2024, 1, 1)),
        WindowEndpoint.from_datetime(datetime(2024, 1, 2)),
    )
    origin = SourceCallOrigin(
        url="https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/HidroinfoanaSerieTelemetricaAdotada/v1",
        request_parameters={},
        status_code=200,
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        content_type="application/json",
        source_path=UnknownOriginFact(),
        query=UnknownOriginFact(),
    )

    def _payload(product_name: str, document: object, raw_bytes: bytes | None = None) -> Payload:
        pid = ProductId(product_name)
        return Payload(
            source_coordinates=cfg.products[pid].coordinates,
            station_products=(("15400000", pid),),
            fetch_window=fw,
            content=raw_bytes if raw_bytes is not None else json.dumps(document).encode(),
            origin=origin,
            prerequisite_calls=(),
        )

    # Telemetry payloads: discharge + stage (with valid, null, duplicate timestamps), empty, and malformed.
    telem_q = _payload(
        "discharge_instantaneous",
        {
            "status": "OK",
            "code": 200,
            "items": [
                {
                    "codigoestacao": "15400000",
                    "Data_Hora_Medicao": "2024-01-01 00:00:00",
                    "Vazao_Adotada": "12.5",
                    "Vazao_Adotada_Status": "0",
                },
                {
                    "codigoestacao": "15400000",
                    "Data_Hora_Medicao": "2024-01-01 00:00:00",
                    "Vazao_Adotada": "13.0",
                    "Vazao_Adotada_Status": "1",
                },
                {
                    "codigoestacao": "15400000",
                    "Data_Hora_Medicao": "2024-01-01 01:00:00",
                    "Vazao_Adotada": None,
                    "Vazao_Adotada_Status": None,
                },
            ],
        },
    )
    telem_h = _payload(
        "stage_instantaneous",
        {
            "status": "OK",
            "code": 200,
            "items": [
                {
                    "codigoestacao": "15400000",
                    "Data_Hora_Medicao": "2024-01-01 00:00:00",
                    "Cota_Adotada": "150",
                    "Cota_Adotada_Status": "0",
                }
            ],
        },
    )
    telem_empty = _payload("discharge_instantaneous", {"status": "OK", "code": 200, "items": []})
    telem_bad_json = _payload("discharge_instantaneous", {}, raw_bytes=b"{not-json")
    telem_bad_row = _payload(
        "discharge_instantaneous",
        {
            "status": "OK",
            "code": 200,
            "items": [
                {
                    "codigoestacao": "15400000",
                    "Data_Hora_Medicao": "not-a-timestamp",
                    "Vazao_Adotada": "1.0",
                    "Vazao_Adotada_Status": "0",
                }
            ],
        },
    )

    daily_row_base = {
        "codigoestacao": "15400000",
        "Data_Hora_Dado": "2024-01-01 00:00:00",
        "Mediadiaria": "1",
        "Metodo_Obtencao_Vazoes": "1",
        **{f"Vazao_{d:02d}": "10.0" if d == 1 else None for d in range(1, 32)},
        **{f"Vazao_{d:02d}_Status": "1" if d == 1 else None for d in range(1, 32)},
    }
    daily_multi = _payload(
        "discharge_daily_mean_bruto",
        {
            "status": "OK",
            "code": 200,
            "items": [
                {
                    **daily_row_base,
                    "Nivel_Consistencia": "2",
                },  # present consistido, bruto requested -> unresolved + outcome + inventory
                {**daily_row_base, "Nivel_Consistencia": "bad"},  # invalid consistency triggers invalid outcome too
            ],
        },
    )
    daily_empty = _payload("discharge_daily_mean_bruto", {"status": "OK", "code": 200, "items": []})

    cases = [telem_q, telem_h, telem_empty, telem_bad_json, telem_bad_row, daily_multi, daily_empty]
    baseline_outputs = [ana_parse_mod.parse(p, cfg) for p in cases]

    json_calls = 0
    sha_calls = 0
    real_loads = json.loads
    real_sha256 = hashlib.sha256

    def counted_loads(raw: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal json_calls
        json_calls += 1
        return real_loads(raw, *args, **kwargs)

    def counted_sha256(data: Any = b"") -> Any:
        nonlocal sha_calls
        sha_calls += 1
        return real_sha256(data)

    monkeypatch.setattr(
        ana_parse_mod,
        "json",
        types.SimpleNamespace(loads=counted_loads, JSONDecodeError=json.JSONDecodeError),
    )
    monkeypatch.setattr(ana_parse_mod, "hashlib", types.SimpleNamespace(sha256=counted_sha256))

    for payload, expected in zip(cases, baseline_outputs, strict=True):
        json_calls = 0
        sha_calls = 0
        actual = ana_parse_mod.parse(payload, cfg)
        assert json_calls == 1
        assert sha_calls == 1
        pl_testing.assert_frame_equal(actual.rows, expected.rows)
        _assert_annotation_bundles_equal(actual.annotations, expected.annotations)
        assert actual.series == expected.series
        assert actual.inventories == expected.inventories
        assert actual.outcomes == expected.outcomes
        assert actual.issues == expected.issues


def test_no_nve_single_decode_and_single_sha256(monkeypatch: pytest.MonkeyPatch) -> None:
    import hashlib
    import types

    from rivretrieve._internal.engine import SourceCallOrigin, UnknownOriginFact, _make_fetch_window
    from rivretrieve._internal.providers.no_nve import parse as nve_parse_mod
    from rivretrieve._internal.providers.no_nve.config import config

    cfg = config()
    pid = ProductId("discharge_daily_mean")
    fw = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2024, 1, 1)),
        WindowEndpoint.from_datetime(datetime(2024, 1, 3)),
    )
    origin = SourceCallOrigin(
        url="https://hydapi.nve.no/api/v1/Observations",
        request_parameters={},
        status_code=200,
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        content_type="application/json",
        source_path=UnknownOriginFact(),
        query=UnknownOriginFact(),
    )

    def _payload(raw: object) -> Payload:
        content = raw if isinstance(raw, bytes) else json.dumps(raw).encode()
        return Payload(
            source_coordinates=cfg.products[pid].coordinates,
            station_products=(("109.42.0", pid),),
            fetch_window=fw,
            content=content,
            origin=origin,
            prerequisite_calls=(),
        )

    valid_v1 = {
        "stationId": "109.42.0",
        "parameter": 1001,
        "serieVersionNo": 1,
        "method": "Mean",
        "unit": "m³/s",
        "observationCount": 1,
        "observations": [{"time": "2024-01-01T11:00:00Z", "value": 4.2, "quality": 3, "correction": 0}],
    }
    repeated_v2 = {
        "stationId": "109.42.0",
        "parameter": 1001,
        "serieVersionNo": 2,
        "method": "Mean",
        "unit": "m³/s",
        "observationCount": 0,
        "observations": [],
    }
    bad_unit_v3 = {
        "stationId": "109.42.0",
        "parameter": 1001,
        "serieVersionNo": 3,
        "method": "Mean",
        "unit": "",
        "observationCount": 0,
        "observations": [],
    }
    cases = [
        _payload({"data": [valid_v1, repeated_v2, dict(repeated_v2), bad_unit_v3]}),
        _payload({"data": []}),
        _payload(b"{invalid-json"),
    ]
    baseline_outputs = [nve_parse_mod.parse(p, cfg) for p in cases]

    json_calls = 0
    sha_calls = 0
    real_loads = json.loads
    real_sha256 = hashlib.sha256

    def counted_loads(raw: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal json_calls
        json_calls += 1
        return real_loads(raw, *args, **kwargs)

    def counted_sha256(data: Any = b"") -> Any:
        nonlocal sha_calls
        sha_calls += 1
        return real_sha256(data)

    monkeypatch.setattr(
        nve_parse_mod,
        "json",
        types.SimpleNamespace(loads=counted_loads, JSONDecodeError=json.JSONDecodeError),
    )
    monkeypatch.setattr(nve_parse_mod, "hashlib", types.SimpleNamespace(sha256=counted_sha256))

    for payload, expected in zip(cases, baseline_outputs, strict=True):
        json_calls = 0
        sha_calls = 0
        actual = nve_parse_mod.parse(payload, cfg)
        assert json_calls == 1
        assert sha_calls == 1
        pl_testing.assert_frame_equal(actual.rows, expected.rows)
        _assert_annotation_bundles_equal(actual.annotations, expected.annotations)
        assert actual.series == expected.series
        assert actual.inventories == expected.inventories
        assert actual.outcomes == expected.outcomes
        assert actual.issues == expected.issues


@pytest.mark.parametrize("cache_mode", ["bypass", "refresh"])
def test_ch_foen_overflow_subdivision_with_child_transport_failure(tmp_path: Path, cache_mode: str) -> None:
    import re
    from datetime import timedelta
    from functools import partial

    from rivretrieve._internal.providers.ch_foen import official_fetch as foen_fetch_mod
    from rivretrieve._internal.providers.ch_foen import official_parse as foen_parse_mod
    from rivretrieve._internal.providers.ch_foen.official_config import config, window_declarations
    from rivretrieve._internal.providers.ch_foen.official_series import source_series
    from rivretrieve._internal.source_series import RestrictionKind
    from rivretrieve._internal.store import StoreRoot

    archive_series = source_series(
        "2018",
        "data_10min_mean",
        "Q",
        "Variant",
        units=("m3/s",),
        evidence="synthetic:unit",
        temporal_evidence="synthetic:time",
        origin="catalogue",
    )
    req = ObservationRequest(
        provider_id=ProviderId("ch_foen"),
        stations=("2018",),
        products=(ProductId("discharge_10min_mean"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2025, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2025, 1, 1, 0, 0, 3)),
        ),
        known_series=(archive_series,),
        scope=SeriesScope(restriction=RestrictionKind.EXPLICIT, series_ids=(archive_series.series_id,)),
    )

    class _OverflowChild503Transport:
        def __init__(self, *, fail_all_children: bool = False) -> None:
            self.fail_all_children = fail_all_children

        def send(self, request):
            body = request.body.replace('\\"', '"')
            start, end = [
                datetime.fromisoformat(item).replace(tzinfo=None)
                for item in re.findall(r'_(?:gte|lt): "([^"]+)"', body)
            ]
            if (end - start) > timedelta(days=3):
                doc = {
                    "data": None,
                    "errors": [
                        {
                            "errorType": "ValidationError",
                            "message": (
                                "Query returned more than 10000 rows. Please narrow your query using filters or "
                                "specify a limit."
                            ),
                            "path": ["water", "observations", "data_10min_mean"],
                        }
                    ],
                }
                return TransportResponse(
                    json.dumps(doc).encode(), 200, datetime(2026, 1, 1, tzinfo=UTC), "application/json", request.url, {}
                )
            if self.fail_all_children or start >= datetime(2025, 1, 1, 0, 0, 1):
                return TransportResponse(
                    b"service-unavailable", 503, datetime(2026, 1, 1, tzinfo=UTC), "text/plain", request.url, {}
                )
            doc = {
                "data": {
                    "water": {
                        "observations": {
                            "data_10min_mean": [
                                {
                                    "station": {"no": "2018"},
                                    "parameterName": "Q",
                                    "tsName": "Variant",
                                    "unitSymbol": "m3/s",
                                    "timestamp": "2025-01-01T00:00:00Z",
                                    "value": 10.0,
                                    "releaseState": "3",
                                }
                            ]
                        }
                    }
                }
            }
            return TransportResponse(
                json.dumps(doc).encode(), 200, datetime(2026, 1, 1, tzinfo=UTC), "application/json", request.url, {}
            )

    class _Stages:
        pass

    _Stages.config = config()
    _Stages.window_declarations = window_declarations()
    _Stages.fetch = staticmethod(partial(foen_fetch_mod.fetch, timestamp_precision=timedelta(seconds=1)))
    _Stages.parse = staticmethod(foen_parse_mod.parse)

    store = StoreRoot(tmp_path / f"store_{cache_mode}") if cache_mode == "refresh" else None
    result = driver_module.drive(
        req,
        _Stages(),
        provenance=_provenance(req),
        cache=cache_mode,
        store=store,
        transport=_OverflowChild503Transport(),
    )
    assert result.canonical_rows["value"].to_list() == [10.0]
    assert [o.status for o in result.outcomes] == [OutcomeStatus.FAILED, OutcomeStatus.SUCCESS]
    assert any(
        issue.code == "source.request_failed" and issue.details.get("status_code") == 503 for issue in result.issues
    )
    calls = result.provenance.calls_made
    failed_idx = next(i for i, c in enumerate(calls) if c.get("status_code") == 503)
    overflow_idx = next(
        i for i, c in enumerate(calls) if c.get("status_code") == 200 and not c.get("prerequisite_acquisition_ids")
    )
    assert overflow_idx < failed_idx
    overflow_id = calls[overflow_idx]["call_id"]
    assert overflow_id in calls[failed_idx]["prerequisite_acquisition_ids"]

    all_failed_store = StoreRoot(tmp_path / f"store_all_failed_{cache_mode}") if cache_mode == "refresh" else None
    all_failed = driver_module.drive(
        req,
        _Stages(),
        provenance=_provenance(req),
        cache=cache_mode,
        store=all_failed_store,
        transport=_OverflowChild503Transport(fail_all_children=True),
    )
    assert all_failed.canonical_rows.height == 0
    failed_outcomes = [o for o in all_failed.outcomes if o.status is OutcomeStatus.FAILED]
    assert len(failed_outcomes) == 2
    af_calls = all_failed.provenance.calls_made
    assert len([c for c in af_calls if c.get("status_code") == 503]) == 2
    assert af_calls[0]["status_code"] == 200
    assert all(af_calls[0]["call_id"] in c["prerequisite_acquisition_ids"] for c in af_calls[1:])
