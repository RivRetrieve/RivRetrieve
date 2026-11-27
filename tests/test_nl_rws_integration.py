"""Source-independent public API integration tests for the Netherlands (`nl_rws`) provider."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

import rivretrieve as rr
from rivretrieve._internal import discovery
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.transport import (
    HttpMethod,
    TransportFailure,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")


class _RecordingTransport:
    """Fake HTTP transport keyed by (station, eenheid) or sequential response list (zero network)."""

    def __init__(
        self,
        responses: dict[str, bytes | int] | dict[tuple[str, str], bytes | int] | list[bytes | int],
    ) -> None:
        self._responses = responses
        self.requests: list[TransportRequest] = []

    def send(self, request: TransportRequest) -> TransportResponse:
        self.requests.append(request)
        if isinstance(self._responses, list):
            outcome = self._responses[len(self.requests) - 1]
        else:
            body = json.loads(request.body.decode("utf-8")) if request.body else {}
            station = body["Locatie"]["Code"]
            eenheid = body["AquoPlusWaarnemingMetadata"]["AquoMetadata"]["Eenheid"]["Code"]
            if (station, eenheid) in self._responses:
                outcome = self._responses[(station, eenheid)]  # type: ignore[index]
            else:
                outcome = self._responses[station]  # type: ignore[index]
        if isinstance(outcome, int):
            raise TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=outcome)
        status = 204 if outcome == b"" else 200
        return TransportResponse(
            status_code=status,
            content=outcome,
            url=request.url,
            request_parameters={},
            retrieved_at=datetime(2026, 11, 27, 6, 0, 0, tzinfo=UTC),
            content_type="application/json",
            attempts=1,
        )


def _waarnemingen(series: list[dict[str, object]]) -> bytes:
    return json.dumps({"WaarnemingenLijst": series}).encode("utf-8")


def _series_entry(
    *,
    grootheid: str,
    eenheid: str,
    hoedanigheid: str,
    wbw: str,
    wbm: str,
    metingen: list[dict[str, object]],
    proces_type: str = "meting",
) -> dict[str, object]:
    return {
        "AquoMetadata": {
            "Compartiment": {"Code": "OW"},
            "Grootheid": {"Code": grootheid},
            "Eenheid": {"Code": eenheid},
            "Hoedanigheid": {"Code": hoedanigheid},
            "ProcesType": proces_type,
            "WaardeBewerkingsMethode": {"Code": wbw},
            "WaardeBepalingsMethode": {"Code": wbm},
            "Groepering": {"Code": ""},
        },
        "MetingenLijst": metingen,
    }


def _obs(
    tijdstip: str,
    numeric: float | None,
    *,
    alpha: str | None = None,
    statuswaarde: str = "Gecontroleerd",
    qcode: str = "00",
) -> dict[str, object]:
    return {
        "Tijdstip": tijdstip,
        "Meetwaarde": {
            "Waarde_Numeriek": numeric,
            "Waarde_Alfanumeriek": alpha if alpha is not None else (str(numeric) if numeric is not None else None),
        },
        "WaarnemingMetadata": {
            "Statuswaarde": statuswaarde,
            "Kwaliteitswaardecode": qcode,
        },
    }


def test_public_discovery_exposes_nl_rws_catalogue_and_descriptor() -> None:
    providers = rr.providers()
    row = providers.filter(providers["provider_id"] == "nl_rws")
    assert row.height == 1
    assert row["credentials"].to_list() == [[]]
    assert row["access"].to_list() == ["open"]

    products = rr.products(provider="nl_rws")
    assert len(products) == 10
    assert set(products) == {
        "discharge_m3d_nvt",
        "discharge_m3s_gem24h",
        "discharge_m3s_nvt",
        "stage_msl_nvt",
        "stage_nap_gem24h",
        "stage_nap_nvt",
        "stage_plaatslr_nvt",
        "stage_taw_nvt",
        "water_temperature_gem24h",
        "water_temperature_nvt",
    }

    found_all = rr.as_frame(rr.find(provider="nl_rws"))
    assert found_all["station_id"].n_unique() == 1706
    lobith_sel = rr.find(provider="nl_rws", station="lobith.bovenrijn.tolkamer")
    assert rr.as_frame(lobith_sel).height == 10

    meta = rr.metadata(lobith_sel)
    assert meta.height >= 1
    assert set(meta["station_id"].to_list()) == {"lobith.bovenrijn.tolkamer"}

    descriptor = rr.describe("nl_rws")
    assert descriptor["name"] == "rivretrieve-nl_rws-catalogue"
    assert "CC0-1.0" in json.dumps(descriptor)


def test_fetch_converts_stage_cm_discharge_m3d_and_temperature_oc(monkeypatch: pytest.MonkeyPatch) -> None:
    # Stage in cm -> canonical m (including negative coastal/polder value and 0.0)
    stage_payload = _waarnemingen(
        [
            _series_entry(
                grootheid="WATHTE",
                eenheid="cm",
                hoedanigheid="NAP",
                wbw="NVT",
                wbm="other:F007",
                metingen=[
                    _obs("2020-03-01T12:00:00.000+01:00", -125.0),
                    _obs("2020-03-01T12:10:00.000+01:00", 0.0),
                ],
            )
        ]
    )
    t_stage = _RecordingTransport([stage_payload])
    monkeypatch.setattr(discovery, "HttpClient", lambda: t_stage)
    res_stage = rr.fetch(
        rr.find(provider="nl_rws", station="lobith.bovenrijn.tolkamer", quantity="stage", vertical_datum="NAP"),
        start="2020-03-01T00:00:00",
        end="2020-03-02T00:00:00",
        cache="bypass",
        on_issue="ignore",
    )
    assert len(t_stage.requests) == 1
    assert res_stage.data.height == 2
    assert res_stage.data["unit"].to_list() == ["m", "m"]
    assert res_stage.data["value"].to_list() == pytest.approx([-1.25, 0.0])

    # Discharge in m3/d -> canonical m3/s (divided by 86400) alongside co-acquired m3/s pair
    t_q = _RecordingTransport(
        {
            ("lobith.bovenrijn.tolkamer", "m3/d"): _waarnemingen(
                [
                    _series_entry(
                        grootheid="Q",
                        eenheid="m3/d",
                        hoedanigheid="NVT",
                        wbw="NVT",
                        wbm="other:F216",
                        metingen=[_obs("2020-03-01T12:00:00.000+01:00", 86400.0)],
                    )
                ]
            ),
            ("lobith.bovenrijn.tolkamer", "m3/s"): b"",
        }
    )
    monkeypatch.setattr(discovery, "HttpClient", lambda: t_q)
    res_q = rr.fetch(
        rr.find(provider="nl_rws", station="lobith.bovenrijn.tolkamer", quantity="discharge"),
        start="2020-03-01T00:00:00",
        end="2020-03-02T00:00:00",
        cache="bypass",
        on_issue="ignore",
    )
    m3d_rows = res_q.data.filter(res_q.data["product_id"] == "discharge_m3d_nvt")
    assert m3d_rows.height == 1
    assert m3d_rows["unit"].to_list() == ["m3/s"]
    assert m3d_rows["value"].to_list() == pytest.approx([1.0])

    # Temperature in oC -> canonical degC
    temp_payload = _waarnemingen(
        [
            _series_entry(
                grootheid="T",
                eenheid="oC",
                hoedanigheid="NVT",
                wbw="NVT",
                wbm="other:F001",
                metingen=[_obs("2020-03-01T12:00:00.000+01:00", 7.4)],
            )
        ]
    )
    t_temp = _RecordingTransport([temp_payload])
    monkeypatch.setattr(discovery, "HttpClient", lambda: t_temp)
    res_temp = rr.fetch(
        rr.find(provider="nl_rws", station="lobith.bovenrijn.tolkamer", quantity="temperature"),
        start="2020-03-01T00:00:00",
        end="2020-03-02T00:00:00",
        cache="bypass",
        on_issue="ignore",
    )
    assert len(t_temp.requests) == 1
    assert res_temp.data.height == 1
    assert res_temp.data["unit"].to_list() == ["degC"]
    assert res_temp.data["value"].to_list() == pytest.approx([7.4])


def test_fetch_coacquires_nvt_gem24h_preserves_parallel_methods_and_missing_annotations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    joint_payload = _waarnemingen(
        [
            _series_entry(
                grootheid="Q",
                eenheid="m3/s",
                hoedanigheid="NVT",
                wbw="NVT",
                wbm="other:F216",
                metingen=[
                    _obs(
                        "2020-03-01T12:00:00.000+01:00",
                        4242.07,
                        statuswaarde="Ongecontroleerd",
                        qcode="00",
                    ),
                    _obs(
                        "2020-03-01T12:10:00.000+01:00",
                        9.99999e37,
                        alpha=".999999E+38",
                        statuswaarde="Ongecontroleerd",
                        qcode="99",
                    ),
                ],
            ),
            _series_entry(
                grootheid="Q",
                eenheid="m3/s",
                hoedanigheid="NVT",
                wbw="NVT",
                wbm="other:F230",
                metingen=[_obs("2020-03-01T12:00:00.000+01:00", 4200.0)],
            ),
            _series_entry(
                grootheid="Q",
                eenheid="m3/s",
                hoedanigheid="NVT",
                wbw="GEM24H",
                wbm="other:F216",
                metingen=[_obs("2020-03-01T00:00:00.000+01:00", 4312.0)],
            ),
        ]
    )
    transport = _RecordingTransport(
        {
            ("lobith.bovenrijn.tolkamer", "m3/s"): joint_payload,
            ("lobith.bovenrijn.tolkamer", "m3/d"): b"",
        }
    )
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)

    selection = rr.find(provider="nl_rws", station="lobith.bovenrijn.tolkamer", quantity="discharge")
    res = rr.fetch(
        selection,
        start="2020-03-01T00:00:00",
        end="2020-03-02T00:00:00",
        cache="bypass",
        on_issue="ignore",
    )

    # Exactly 1 POST for co-acquired (discharge_m3s_nvt + discharge_m3s_gem24h), omitting WaardeBewerkingsMethode
    m3s_reqs = [
        r
        for r in transport.requests
        if r.body is not None
        and json.loads(r.body.decode("utf-8"))["AquoPlusWaarnemingMetadata"]["AquoMetadata"]["Eenheid"]["Code"]
        == "m3/s"
    ]
    assert len(m3s_reqs) == 1
    assert m3s_reqs[0].method is HttpMethod.POST
    assert m3s_reqs[0].body is not None
    am = json.loads(m3s_reqs[0].body.decode("utf-8"))["AquoPlusWaarnemingMetadata"]["AquoMetadata"]
    assert am["ProcesType"] == "meting"
    assert "WaardeBewerkingsMethode" not in am

    # Parallel F216 and F230 NVT series + GEM24H series remain distinct
    assert res.data.height == 4
    nvt_rows = res.data.filter(res.data["product_id"] == "discharge_m3s_nvt")
    gem_rows = res.data.filter(res.data["product_id"] == "discharge_m3s_gem24h")
    assert nvt_rows.height == 3
    assert nvt_rows["series_id"].n_unique() == 2
    assert None in nvt_rows["value"].to_list()
    assert gem_rows.height == 1
    assert gem_rows["value"].to_list() == pytest.approx([4312.0])

    # Observation annotations carried through assembly with qcode="99" preserved
    annotated = res.to_polars(annotations=True)
    assert annotated.height == 4
    assert "99" in annotated["kwaliteitswaardecode"].to_list()
    assert "Ongecontroleerd" in annotated["statuswaarde"].to_list()


def test_fetch_isolates_station_failures_and_handles_http_204_no_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Multi-station partial failure: one station HTTP 400, another succeeds
    gem_all = rr.find(provider="nl_rws", quantity="discharge", frequency="P1D")
    stations = rr.as_frame(gem_all)["station_id"].unique().sort().to_list()[:2]
    ok_station, fail_station = stations[0], stations[1]
    transport = _RecordingTransport(
        {
            ok_station: _waarnemingen(
                [
                    _series_entry(
                        grootheid="Q",
                        eenheid="m3/s",
                        hoedanigheid="NVT",
                        wbw="GEM24H",
                        wbm="other:F216",
                        metingen=[_obs("2020-03-01T00:00:00.000+01:00", 123.4)],
                    )
                ]
            ),
            fail_station: 400,
        }
    )
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    res = rr.fetch(
        rr.pick(gem_all, station=[ok_station, fail_station]),
        start="2020-03-01T00:00:00",
        end="2020-03-02T00:00:00",
        cache="bypass",
        on_issue="ignore",
    )
    assert res.data.height == 1
    assert res.data["station_id"].to_list() == [ok_station]
    outcomes_by_station = {o.station_id: o.status for o in res.outcomes}
    assert outcomes_by_station[ok_station] is OutcomeStatus.SUCCESS
    assert outcomes_by_station[fail_station] is OutcomeStatus.FAILED

    # HTTP 204 empty response -> empty data with OutcomeStatus.NO_MATCH (not FAILED)
    empty_transport = _RecordingTransport([b""])
    monkeypatch.setattr(discovery, "HttpClient", lambda: empty_transport)
    res_empty = rr.fetch(
        rr.pick(gem_all, station=ok_station),
        start="1990-03-01T00:00:00",
        end="1990-03-02T00:00:00",
        cache="bypass",
        on_issue="ignore",
    )
    assert res_empty.data.is_empty()
    assert len(res_empty.outcomes) == 1
    assert res_empty.outcomes[0].status is OutcomeStatus.NO_MATCH
