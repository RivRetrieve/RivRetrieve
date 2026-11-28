"""Source-independent request-planning contract tests for lt_lhmt, pe_senamhi, and at_ehyd."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime

import pytest

import rivretrieve._internal.driver as driver_module
from rivretrieve._internal.engine import ObservationRequest, RequestedWindow, WindowEndpoint
from rivretrieve._internal.observations import ObservationProvenance, ReceiptMode
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.at_ehyd import parse as at_ehyd_parse
from rivretrieve._internal.providers.at_ehyd.declaration import declaration as at_declaration
from rivretrieve._internal.providers.at_ehyd.series import OWF_INTERVAL_RULE_TEXT
from rivretrieve._internal.providers.lt_lhmt import parse as lt_lhmt_parse
from rivretrieve._internal.providers.lt_lhmt.declaration import declaration as lt_declaration
from rivretrieve._internal.providers.pe_senamhi import parse as pe_senamhi_parse
from rivretrieve._internal.providers.pe_senamhi.declaration import declaration as pe_declaration
from rivretrieve._internal.providers.registration import LiveStages
from rivretrieve._internal.source_acquisition import SourceResponseMeaning
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.transport import (
    TransportFailure,
    TransportFailureCategory,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)


def _utc(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=UTC)


def test_control_providers_declare_request_planner() -> None:
    for decl in (lt_declaration, pe_declaration, at_declaration):
        assert isinstance(decl.observations, LiveStages)
        assert hasattr(decl.observations.stages, "request_planner")


def test_lt_lhmt_planner_shares_station_month_decodes_once_and_maps_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert isinstance(lt_declaration.observations, LiveStages)
    stages = lt_declaration.observations.stages

    class _LtTransport:
        def __init__(self) -> None:
            self.requests: list[TransportRequest] = []

        def send(self, request: TransportRequest) -> TransportResponse:
            self.requests.append(request)
            if request.url.endswith("/2023-07"):
                resp = TransportResponse(
                    content=b'{"error":"No data"}',
                    status_code=404,
                    retrieved_at=_utc(2023, 8, 1),
                    content_type="application/json",
                    url=request.url,
                    request_parameters={},
                )
                raise TransportFailure(
                    request,
                    TransportFailureReason.HTTP_STATUS,
                    1,
                    status_code=404,
                    category=TransportFailureCategory.HTTP_STATUS,
                    response=resp,
                )
            body = json.dumps(
                {
                    "station": {"code": "anyksciu-vms"},
                    "observations": [{"observationDateUtc": "2023-06-15", "waterDischarge": 14.2, "waterLevel": 115.0}],
                }
            ).encode()
            return TransportResponse(body, 200, _utc(2023, 8, 1), "application/json", request.url, {})

    loads_calls = 0
    real_loads = lt_lhmt_parse.json.loads

    def _counted_loads(*args: object, **kwargs: object) -> object:
        nonlocal loads_calls
        if sys._getframe(1).f_code.co_filename == lt_lhmt_parse.__file__:
            loads_calls += 1
        return real_loads(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(lt_lhmt_parse.json, "loads", _counted_loads)
    t = _LtTransport()
    res = driver_module.drive(
        ObservationRequest(
            ProviderId("lt_lhmt"),
            ("anyksciu-vms",),
            (ProductId("discharge_daily_mean"), ProductId("stage_daily_mean")),
            RequestedWindow(
                WindowEndpoint.from_datetime(datetime(2023, 6, 15)),
                WindowEndpoint.from_datetime(datetime(2023, 7, 1)),
            ),
        ),
        stages,
        provenance=ObservationProvenance(
            source="lhmt", provider_id=ProviderId("lt_lhmt"), requested_at=_utc(2023, 8, 1)
        ),
        receipts=ReceiptMode.INCLUDE,
        transport=t,
        cache="bypass",
    )
    # 2 months x 2 products = 2 GETs (1 per month), 1 decode for June, and July 404 -> NO_OBSERVATIONS cleanly.
    assert len(t.requests) == 2
    assert loads_calls == 1
    assert len(res.receipts.entries) == 1
    assert res.canonical_rows.height == 2
    assert any(
        call.get("response_meaning") == SourceResponseMeaning.NO_OBSERVATIONS for call in res.provenance.calls_made
    )


def test_pe_senamhi_planner_shares_monthly_decodes_once_handles_envelope_failure_and_keeps_phisis_separate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert isinstance(pe_declaration.observations, LiveStages)
    stages = pe_declaration.observations.stages

    class _PeTransport:
        def __init__(self, *, fail_envelope: bool = False) -> None:
            self.requests: list[TransportRequest] = []
            self.fail_envelope = fail_envelope

        def send(self, request: TransportRequest) -> TransportResponse:
            self.requests.append(request)
            params = dict(request.params or {})
            if request.url.endswith("/readings"):
                if self.fail_envelope:
                    content = b'{"status":false,"message":"source refusal","data":null}'
                else:
                    content = json.dumps(
                        {
                            "status": True,
                            "data": {
                                "columns": [
                                    {"column": "N_NIVELAGUA", "unit": "m"},
                                    {"column": "N_NIVELMEDIO", "unit": "m"},
                                ],
                                "readings": [
                                    {
                                        "date": "2026-01-15",
                                        "time": "",
                                        "values": [
                                            {"column": "N_NIVELAGUA", "value": 2.5},
                                            {"column": "N_NIVELMEDIO", "value": 3.1},
                                        ],
                                    }
                                ],
                            },
                        }
                    ).encode()
                return TransportResponse(content, 200, _utc(2026, 2, 1), "application/json", request.url, params)
            variable = str(params["variable"])
            unit = "m3/s" if variable == "FLOW" else "m"
            content = json.dumps(
                {
                    "status": True,
                    "data": {
                        "station": {"code": "A"},
                        "type": "HOURLY",
                        "variable": variable,
                        "unit": unit,
                        "hourly": [{"time": "2026-01-15T10:00:00", "value": 4.2}],
                        "daily": [],
                    },
                }
            ).encode()
            return TransportResponse(content, 200, _utc(2026, 2, 1), "application/json", request.url, params)

    loads_calls = 0
    real_loads = pe_senamhi_parse.json.loads

    def _counted_loads(*args: object, **kwargs: object) -> object:
        nonlocal loads_calls
        if sys._getframe(1).f_code.co_filename == pe_senamhi_parse.__file__:
            loads_calls += 1
        return real_loads(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(pe_senamhi_parse.json, "loads", _counted_loads)
    t_ok = _PeTransport()
    res_ok = driver_module.drive(
        ObservationRequest(
            ProviderId("pe_senamhi"),
            ("A",),
            (
                ProductId("monthly_archive_n_nivelagua"),
                ProductId("monthly_archive_n_nivelmedio"),
                ProductId("phisis_hourly_flow"),
                ProductId("phisis_hourly_level"),
            ),
            RequestedWindow(
                WindowEndpoint.from_datetime(datetime(2026, 1, 15)),
                WindowEndpoint.from_datetime(datetime(2026, 1, 15, 23, 59, 59)),
            ),
        ),
        stages,
        provenance=ObservationProvenance(
            source="senamhi", provider_id=ProviderId("pe_senamhi"), requested_at=_utc(2026, 2, 1)
        ),
        receipts=ReceiptMode.INCLUDE,
        transport=t_ok,
        cache="bypass",
    )
    # 2 monthly archive products share 1 GET; 2 PHISIS variables remain separate per-variable requests.
    monthly_reqs = [r for r in t_ok.requests if r.url.endswith("/readings")]
    flow_reqs = [r for r in t_ok.requests if (r.params or {}).get("variable") == "FLOW"]
    level_reqs = [r for r in t_ok.requests if (r.params or {}).get("variable") == "LEVEL"]
    assert len(monthly_reqs) == 1
    assert len(flow_reqs) >= 1 and len(level_reqs) >= 1
    assert loads_calls == len(t_ok.requests)
    assert len(res_ok.receipts.entries) == len(t_ok.requests)
    assert res_ok.canonical_rows.height == 4

    # Envelope failure ("status": false) -> single decode produces per-pair FAILED outcome + issue cleanly.
    loads_calls = 0
    t_fail = _PeTransport(fail_envelope=True)
    res_fail = driver_module.drive(
        ObservationRequest(
            ProviderId("pe_senamhi"),
            ("A",),
            (ProductId("monthly_archive_n_nivelagua"), ProductId("monthly_archive_n_nivelmedio")),
            RequestedWindow(
                WindowEndpoint.from_datetime(datetime(2026, 1, 15)),
                WindowEndpoint.from_datetime(datetime(2026, 1, 15)),
            ),
        ),
        stages,
        provenance=ObservationProvenance(
            source="senamhi", provider_id=ProviderId("pe_senamhi"), requested_at=_utc(2026, 2, 1)
        ),
        transport=t_fail,
        cache="bypass",
    )
    assert len(t_fail.requests) == 1
    assert loads_calls == 1
    assert len(res_fail.outcomes) == 2
    assert all(o.status is OutcomeStatus.FAILED for o in res_fail.outcomes)
    assert all(i.code == "source.response_failed" for i in res_fail.issues)


def test_at_ehyd_planner_dedups_info_lookup_shares_pegel_and_preserves_prereq_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert isinstance(at_declaration.observations, LiveStages)
    stages = at_declaration.observations.stages
    station = "204388"
    info_bytes = json.dumps(
        [
            {
                "caption": "Messstelle",
                "data": [
                    {
                        "info": {
                            "data": [
                                {"caption": "HZBNR", "text": int(station)},
                                {
                                    "tag": "dl_mstfiles",
                                    "data": {
                                        "fileData": [
                                            {
                                                "fileNr": 2,
                                                "fileName": f"W-Tagesmittel-{station}.csv",
                                                "hzbnr": int(station),
                                                "msttyp": "owf",
                                            },
                                            {
                                                "fileNr": 4,
                                                "fileName": f"Q-Tagesmittel-{station}.csv",
                                                "hzbnr": int(station),
                                                "msttyp": "owf",
                                            },
                                        ]
                                    },
                                },
                            ]
                        }
                    }
                ],
            }
        ]
    ).encode()

    def _owf_csv(unit: str, desc: str, val: str) -> bytes:
        return "\r\n".join(
            [
                "Stammdaten:",
                "Messstelle:                ;Testpegel",
                f"HZB-Nummer:                ;{station}",
                f"Einheit:                   ;[{unit}]",
                f"Exportzeitreihe:           ;{desc}",
                f"Zeitreihenart:             ;{OWF_INTERVAL_RULE_TEXT}",
                "Exportzeitraum:            ;[01.01.2023 00:00,02.01.2023 00:00]",
                "Werte:",
                f"01.01.2023 00:00:00; {val}",
                "",
            ]
        ).encode("cp1252")

    bgis_bytes = json.dumps(
        {
            "hzbnr": int(station),
            "parameter": "Abfluss",
            "einheit": "m³/s",
            "valCount": 1,
            "categories": ["2023-01-01 10:00:00"],
            "data": [14.2],
        }
    ).encode()

    class _EhydTransport:
        def __init__(self) -> None:
            self.requests: list[TransportRequest] = []

        def send(self, request: TransportRequest) -> TransportResponse:
            self.requests.append(request)
            params = dict(request.params or {})
            if request.url.endswith("/Messstellen/info"):
                return TransportResponse(info_bytes, 200, _utc(2023, 2, 1), "application/json", request.url, params)
            if request.url.endswith("/MessstellenExtraData/owf"):
                content = (
                    _owf_csv("m³/s", "Abfluss,I,mit,T,1", "12,5")
                    if params["file"] == "4"
                    else _owf_csv("cm", "Wasserstand,I,mit,T,1", "110")
                )
                return TransportResponse(content, 200, _utc(2023, 2, 1), "text/csv", request.url, params)
            assert request.url.endswith("/Diagram/pegelBgis")
            return TransportResponse(bgis_bytes, 200, _utc(2023, 2, 1), "application/json", request.url, params)

    loads_calls = 0
    real_loads = at_ehyd_parse.json.loads

    def _counted_loads(*args: object, **kwargs: object) -> object:
        nonlocal loads_calls
        if sys._getframe(1).f_code.co_filename == at_ehyd_parse.__file__:
            loads_calls += 1
        return real_loads(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(at_ehyd_parse.json, "loads", _counted_loads)
    t = _EhydTransport()
    res = driver_module.drive(
        ObservationRequest(
            ProviderId("at_ehyd"),
            (station,),
            (
                ProductId("owf_abfl_tagesmittel"),
                ProductId("owf_wasserst_tagesmittel"),
                ProductId("owf_wassertemp_monatsmittel"),
                ProductId("pegel_bgis_abfluss"),
                ProductId("pegel_bgis_wasserstand"),
            ),
            RequestedWindow(
                WindowEndpoint.from_datetime(datetime(2023, 1, 1)),
                WindowEndpoint.from_datetime(datetime(2023, 1, 1, 23, 59)),
            ),
        ),
        stages,
        provenance=ObservationProvenance(
            source="ehyd", provider_id=ProviderId("at_ehyd"), requested_at=_utc(2023, 2, 1)
        ),
        receipts=ReceiptMode.INCLUDE,
        transport=t,
        cache="bypass",
    )
    # 1 info lookup + 2 owf CSVs + 1 shared pegelBgis = 4 GETs total; 2 json.loads (1 info + 1 pegelBgis).
    assert len(t.requests) == 4
    assert loads_calls == 2
    assert {r.url.rsplit("/", 1)[-1] for r in t.requests} == {"info", "owf", "pegelBgis"}
    assert len([r for r in t.requests if r.url.endswith("/info")]) == 1
    assert len([r for r in t.requests if r.url.endswith("/pegelBgis")]) == 1
    # All 3 observed products return rows, missing owf gets NO_MATCH, unrelated pegel param gets NO_MATCH.
    assert set(res.canonical_rows["product_id"].unique().to_list()) == {
        "owf_abfl_tagesmittel",
        "owf_wasserst_tagesmittel",
        "pegel_bgis_abfluss",
    }
    by_prod = {o.product_id: o.status for o in res.outcomes}
    assert by_prod["owf_wassertemp_monatsmittel"] is OutcomeStatus.NO_MATCH
    assert by_prod["pegel_bgis_wasserstand"] is OutcomeStatus.NO_MATCH
    # owf CSV calls link back to info prerequisite; pegelBgis has no info prerequisite.
    info_calls = [c for c in res.provenance.calls_made if str(c.get("url", "")).endswith("/info")]
    assert len(info_calls) == 1
    info_call_id = info_calls[0].get("call_id") or info_calls[0].get("acquisition_id")
    assert info_call_id
    owf_calls = [c for c in res.provenance.calls_made if str(c.get("url", "")).endswith("/owf")]
    assert len(owf_calls) == 2
    assert all(c["prerequisite_acquisition_ids"] == (info_call_id,) for c in owf_calls)
    pegel_calls = [c for c in res.provenance.calls_made if str(c.get("url", "")).endswith("/pegelBgis")]
    assert len(pegel_calls) == 1
    assert pegel_calls[0]["prerequisite_acquisition_ids"] == ()
