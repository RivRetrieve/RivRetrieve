"""Recorded-response verification tests for `nl_rws` replaying genuine retained DDAPI 2.0 bytes."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

import rivretrieve as rr
from rivretrieve._internal import discovery
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.transport import (
    TransportFailure,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)

_REQUIREMENT = "maintenance/catalogue/nl_rws/official"
_ACCESS = "maintenance/catalogue/nl_rws/official/access"
_VERIFICATION = "maintenance/catalogue/nl_rws/official/verification"
_RETRIEVED_AT = datetime(2026, 11, 25, 13, 45, 0, tzinfo=UTC)

pytestmark = [
    pytest.mark.usefixtures("reuse_packaged_catalogues"),
    pytest.mark.recorded(_REQUIREMENT),
]


class _RetainedReplayTransport:
    """Replay exact retained DDAPI 2.0 bytes keyed by (grootheid, eenheid, hoedanigheid) or default."""

    def __init__(self, responses: dict[tuple[str, str, str], bytes | int] | bytes | int) -> None:
        self._responses = responses
        self.requests: list[TransportRequest] = []

    def send(self, request: TransportRequest) -> TransportResponse:
        self.requests.append(request)
        if isinstance(self._responses, (bytes, int)):
            outcome: bytes | int = self._responses
        else:
            body = json.loads(request.body.decode("utf-8")) if request.body else {}
            am = body["AquoPlusWaarnemingMetadata"]["AquoMetadata"]
            key = (am["Grootheid"]["Code"], am["Eenheid"]["Code"], am["Hoedanigheid"]["Code"])
            outcome = self._responses.get(key, b"")
        if isinstance(outcome, int):
            raise TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=outcome)
        return TransportResponse(
            status_code=204 if outcome == b"" else 200,
            content=outcome,
            url=request.url,
            request_parameters={},
            retrieved_at=_RETRIEVED_AT,
            content_type="application/json",
            attempts=1,
        )


def test_recorded_lobith_2020_discharge_coacquisition_and_parallel_methods(
    monkeypatch: pytest.MonkeyPatch, retained_evidence_root: Path
) -> None:
    raw = (retained_evidence_root / _ACCESS / "02_obs_q_m3s_lobith_2020_03_meting.json").read_bytes()
    transport = _RetainedReplayTransport({("Q", "m3/s", "NVT"): raw})
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)

    res = rr.fetch(
        rr.find(provider="nl_rws", station="lobith.bovenrijn.tolkamer", quantity="discharge"),
        start="2020-03-01T00:00:00",
        end="2020-03-05T23:59:59",
        cache="bypass",
        on_issue="ignore",
    )
    assert res.data.height == 1445
    assert sorted(res.data["product_id"].unique().to_list()) == ["discharge_m3s_gem24h", "discharge_m3s_nvt"]
    assert res.data["unit"].unique().to_list() == ["m3/s"]
    assert res.data["time_zone"].unique().to_list() == ["+01:00"]
    nvt = res.data.filter(res.data["product_id"] == "discharge_m3s_nvt")
    gem = res.data.filter(res.data["product_id"] == "discharge_m3s_gem24h")
    assert nvt.height == 1440
    assert nvt["series_id"].n_unique() == 2
    assert gem.height == 5


def test_recorded_lobith_1990_gem24h_only_and_1901_historical_depth(
    monkeypatch: pytest.MonkeyPatch, retained_evidence_root: Path
) -> None:
    # 1990 GEM24H-only response: GEM24H succeeds (10 rows), NVT returns NO_MATCH
    raw_1990 = (retained_evidence_root / _ACCESS / "03_obs_q_m3s_lobith_1990_03_meting.json").read_bytes()
    t_1990 = _RetainedReplayTransport({("Q", "m3/s", "NVT"): raw_1990})
    monkeypatch.setattr(discovery, "HttpClient", lambda: t_1990)
    res_1990 = rr.fetch(
        rr.find(provider="nl_rws", station="lobith.bovenrijn.tolkamer", quantity="discharge"),
        start="1990-03-01T00:00:00",
        end="1990-03-10T23:59:59",
        cache="bypass",
        on_issue="ignore",
    )
    assert res_1990.data.height == 10
    assert res_1990.data["product_id"].unique().to_list() == ["discharge_m3s_gem24h"]
    statuses_1990 = {o.product_id: o.status for o in res_1990.outcomes}
    assert statuses_1990["discharge_m3s_gem24h"] is OutcomeStatus.SUCCESS
    assert statuses_1990["discharge_m3s_nvt"] is OutcomeStatus.NO_MATCH

    # 1901-01 far-back Lobith response: 31 genuine daily NVT observations from January 1901
    raw_1901 = (retained_evidence_root / _VERIFICATION / "01_obs_q_m3s_lobith_1901_01_earliest.json").read_bytes()
    t_1901 = _RetainedReplayTransport({("Q", "m3/s", "NVT"): raw_1901})
    monkeypatch.setattr(discovery, "HttpClient", lambda: t_1901)
    res_1901 = rr.fetch(
        rr.find(provider="nl_rws", station="lobith.bovenrijn.tolkamer", quantity="discharge"),
        start="1901-01-01T00:00:00",
        end="1901-01-31T23:59:59",
        cache="bypass",
        on_issue="ignore",
    )
    assert res_1901.data.height == 31
    assert res_1901.data["product_id"].unique().to_list() == ["discharge_m3s_nvt"]
    assert res_1901.data["unit"].unique().to_list() == ["m3/s"]


def test_recorded_dst_transition_preserves_fixed_cet_offset(
    monkeypatch: pytest.MonkeyPatch, retained_evidence_root: Path
) -> None:
    raw = (retained_evidence_root / _ACCESS / "12_obs_dst_lobith_2020_03_29_meting.json").read_bytes()
    transport = _RetainedReplayTransport({("Q", "m3/s", "NVT"): raw})
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)

    res = rr.fetch(
        rr.find(provider="nl_rws", station="lobith.bovenrijn.tolkamer", quantity="discharge"),
        start="2020-03-28T22:00:00",
        end="2020-03-29T06:00:00",
        cache="bypass",
        on_issue="ignore",
    )
    assert res.data.height == 87
    assert res.data["time_zone"].unique().to_list() == ["+01:00"]


def test_recorded_qcode_99_missing_sentinel_emits_null_with_annotation(
    monkeypatch: pytest.MonkeyPatch, retained_evidence_root: Path
) -> None:
    raw = (retained_evidence_root / _VERIFICATION / "02_obs_q_m3s_lobith_2020_01_01_qcode99.json").read_bytes()
    transport = _RetainedReplayTransport({("Q", "m3/s", "NVT"): raw})
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)

    res = rr.fetch(
        rr.find(provider="nl_rws", station="lobith.bovenrijn.tolkamer", quantity="discharge"),
        start="2020-01-01T00:00:00",
        end="2020-01-01T23:59:59",
        cache="bypass",
        on_issue="ignore",
    )
    assert res.data.height == 288
    assert res.data["value"].null_count() == 1
    annotated = res.to_polars(annotations=True)
    null_rows = annotated.filter(annotated["value"].is_null())
    assert null_rows.height == 1
    assert null_rows["kwaliteitswaardecode"].to_list() == ["99"]


@pytest.mark.parametrize(
    (
        "filename",
        "station",
        "quantity",
        "vertical_datum",
        "start",
        "end",
        "expected_product",
        "expected_unit",
        "min_rows",
    ),
    [
        (
            "18_obs_q_m3d_nonempty_meting.json",
            "denoever.waddenzee.voorhaven",
            "discharge",
            None,
            "2011-12-01T00:00:00",
            "2011-12-31T23:59:59",
            "discharge_m3d_nvt",
            "m3/s",
            31,
        ),
        (
            "07_obs_wathte_nap_lobith_2020_03_meting.json",
            "lobith.bovenrijn.tolkamer",
            "stage",
            "NAP",
            "2020-03-01T00:00:00",
            "2020-03-03T23:59:59",
            "stage_nap_nvt",
            "m",
            432,
        ),
        (
            "08_obs_wathte_msl_a12_2026_11_meting.json",
            "a12",
            "stage",
            "MSL",
            "2026-11-20T00:00:00",
            "2026-11-22T23:59:59",
            "stage_msl_nvt",
            "m",
            432,
        ),
        (
            "09_obs_wathte_taw_eijsden_2026_11_meting.json",
            "eijsden.grens",
            "stage",
            "TAW",
            "2026-11-20T00:00:00",
            "2026-11-22T23:59:59",
            "stage_taw_nvt",
            "m",
            432,
        ),
        (
            "19_obs_wathte_plaatslr_nonempty_meting.json",
            "markermeer.midden",
            "stage",
            "PLAATSLR",
            "2024-02-28T00:00:00",
            "2024-02-28T23:59:59",
            "stage_plaatslr_nvt",
            "m",
            54,
        ),
        (
            "11_obs_t_oc_maarssen_2026_11_meting.json",
            "maarssen.kanaal",
            "temperature",
            None,
            "2026-11-20T00:00:00",
            "2026-11-22T23:59:59",
            "water_temperature_nvt",
            "degC",
            432,
        ),
    ],
)
def test_recorded_all_admitted_units_and_vertical_references(
    monkeypatch: pytest.MonkeyPatch,
    retained_evidence_root: Path,
    filename: str,
    station: str,
    quantity: str,
    vertical_datum: str | None,
    start: str,
    end: str,
    expected_product: str,
    expected_unit: str,
    min_rows: int,
) -> None:
    raw = (retained_evidence_root / _ACCESS / filename).read_bytes()
    doc = json.loads(raw)
    am = doc["WaarnemingenLijst"][0]["AquoMetadata"]
    key = (am["Grootheid"]["Code"], am["Eenheid"]["Code"], am["Hoedanigheid"]["Code"])
    transport = _RetainedReplayTransport({key: raw})
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)

    sel = rr.find(provider="nl_rws", station=station, quantity=quantity, vertical_datum=vertical_datum)
    res = rr.fetch(sel, start=start, end=end, cache="bypass", on_issue="ignore")
    matched = res.data.filter(res.data["product_id"] == expected_product)
    assert matched.height >= min_rows
    assert matched["unit"].unique().to_list() == [expected_unit]
    assert matched["time_zone"].unique().to_list() == ["+01:00"]
    if expected_product == "stage_taw_nvt":
        annotated = res.to_polars(annotations=True)
        assert "25" in annotated["kwaliteitswaardecode"].to_list()


def test_recorded_http_204_empty_and_http_400_error(
    monkeypatch: pytest.MonkeyPatch, retained_evidence_root: Path
) -> None:
    raw_204 = (retained_evidence_root / _ACCESS / "13_obs_empty_1800.json").read_bytes()
    assert raw_204 == b""
    monkeypatch.setattr(discovery, "HttpClient", lambda: _RetainedReplayTransport(raw_204))
    res_204 = rr.fetch(
        rr.find(provider="nl_rws", station="lobith.bovenrijn.tolkamer", quantity="discharge", frequency="P1D"),
        start="1800-01-01T00:00:00",
        end="1800-01-02T23:59:59",
        cache="bypass",
        on_issue="ignore",
    )
    assert res_204.data.is_empty()
    assert [o.status for o in res_204.outcomes] == [OutcomeStatus.NO_MATCH]

    raw_400 = (retained_evidence_root / _ACCESS / "14_obs_error_bad_station.json").read_bytes()
    assert len(raw_400) > 0
    monkeypatch.setattr(discovery, "HttpClient", lambda: _RetainedReplayTransport(400))
    res_400 = rr.fetch(
        rr.find(provider="nl_rws", station="lobith.bovenrijn.tolkamer", quantity="discharge", frequency="P1D"),
        start="2020-03-01T00:00:00",
        end="2020-03-02T23:59:59",
        cache="bypass",
        on_issue="ignore",
    )
    assert res_400.data.is_empty()
    assert [o.status for o in res_400.outcomes] == [OutcomeStatus.FAILED]
