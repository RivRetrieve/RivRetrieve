"""Source-independent tests for nl_rws retrieval configuration, fetching, and shared parsing."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from rivretrieve._internal.engine import (
    FetchWindow,
    Payload,
    RenderedWindow,
    SourceCallOrigin,
    SourceCoordinates,
    StopConvention,
    Unit,
    UnknownOriginFact,
    UnknownTemporalSupport,
    WindowEndpoint,
    WindowGranularity,
    WindowRenderingVocabulary,
    ZoneValue,
    _make_fetch_window,
)
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.nl_rws.annotations import NL_RWS_OBSERVATION_SCHEMA
from rivretrieve._internal.providers.nl_rws.config import (
    SHARED_ACQUISITION_PRODUCTS,
    config,
    window_declarations,
)
from rivretrieve._internal.providers.nl_rws.fetch import fetch
from rivretrieve._internal.providers.nl_rws.parse import parse, parse_group
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.transport import (
    HttpMethod,
    ReplaySafety,
    TransportFailure,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)


class _RecordingTransport:
    def __init__(self, responses: dict[str, bytes | int] | list[bytes | int]) -> None:
        self._responses = responses
        self.requests: list[TransportRequest] = []

    def send(self, request: TransportRequest) -> TransportResponse:
        self.requests.append(request)
        if isinstance(self._responses, list):
            outcome = self._responses[len(self.requests) - 1]
        else:
            body = json.loads(request.body.decode("utf-8")) if request.body else {}
            station = body["Locatie"]["Code"]
            outcome = self._responses[station]
        if isinstance(outcome, int):
            raise TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=outcome)
        status = 204 if outcome == b"" else 200
        return TransportResponse(
            status_code=status,
            content=outcome,
            url=request.url,
            request_parameters={},
            retrieved_at=datetime(2026, 11, 26, 10, 0, 0, tzinfo=UTC),
            content_type="application/json",
            attempts=1,
        )


def _endpoint(dt: datetime) -> WindowEndpoint:
    utc = dt.astimezone(UTC)
    return WindowEndpoint(
        utc.year,
        utc.month,
        utc.day,
        utc.hour,
        utc.minute,
        utc.second,
        utc.microsecond,
    )


def _window(start: datetime, stop: datetime) -> FetchWindow:
    return _make_fetch_window(_endpoint(start), _endpoint(stop))


def _rendered(start: datetime, stop: datetime) -> RenderedWindow:
    return RenderedWindow(
        start=start.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        stop=stop.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        bounds=_window(start, stop),
    )


def _sample_waarnemingen_json(*, include_nvt: bool = True, include_gem24h: bool = True) -> bytes:
    series_list: list[dict[str, object]] = []
    if include_nvt:
        series_list.append(
            {
                "AquoMetadata": {
                    "Compartiment": {"Code": "OW"},
                    "Grootheid": {"Code": "Q"},
                    "Eenheid": {"Code": "m3/s"},
                    "Hoedanigheid": {"Code": "NVT"},
                    "ProcesType": "meting",
                    "WaardeBewerkingsMethode": {"Code": "NVT"},
                    "WaardeBepalingsMethode": {"Code": "other:F216"},
                    "Groepering": {"Code": ""},
                },
                "MetingenLijst": [
                    {
                        "Tijdstip": "2020-03-01T00:00:00.000+01:00",
                        "Meetwaarde": {"Waarde_Numeriek": 4242.07, "Waarde_Alfanumeriek": "4242.07"},
                        "WaarnemingMetadata": {"Statuswaarde": "Ongecontroleerd", "Kwaliteitswaardecode": "00"},
                    },
                    {
                        "Tijdstip": "2020-03-01T00:10:00.000+01:00",
                        "Meetwaarde": {"Waarde_Numeriek": 9.99999e37, "Waarde_Alfanumeriek": ".999999E+38"},
                        "WaarnemingMetadata": {"Statuswaarde": "Ongecontroleerd", "Kwaliteitswaardecode": "99"},
                    },
                ],
            }
        )
        series_list.append(
            {
                "AquoMetadata": {
                    "Compartiment": {"Code": "OW"},
                    "Grootheid": {"Code": "Q"},
                    "Eenheid": {"Code": "m3/s"},
                    "Hoedanigheid": {"Code": "NVT"},
                    "ProcesType": "meting",
                    "WaardeBewerkingsMethode": {"Code": "NVT"},
                    "WaardeBepalingsMethode": {"Code": "other:F230"},
                    "Groepering": {"Code": ""},
                },
                "MetingenLijst": [
                    {
                        "Tijdstip": "2020-03-01T00:00:00.000+01:00",
                        "Meetwaarde": {"Waarde_Numeriek": 0.0, "Waarde_Alfanumeriek": "0"},
                        "WaarnemingMetadata": {"Statuswaarde": "Gecontroleerd", "Kwaliteitswaardecode": "00"},
                    }
                ],
            }
        )
    if include_gem24h:
        series_list.append(
            {
                "AquoMetadata": {
                    "Compartiment": {"Code": "OW"},
                    "Grootheid": {"Code": "Q"},
                    "Eenheid": {"Code": "m3/s"},
                    "Hoedanigheid": {"Code": "NVT"},
                    "ProcesType": "meting",
                    "WaardeBewerkingsMethode": {"Code": "GEM24H"},
                    "WaardeBepalingsMethode": {"Code": "other:F216"},
                    "Groepering": {"Code": ""},
                },
                "MetingenLijst": [
                    {
                        "Tijdstip": "2020-03-01T00:00:00.000+01:00",
                        "Meetwaarde": {"Waarde_Numeriek": 4312.0, "Waarde_Alfanumeriek": "4312"},
                        "WaarnemingMetadata": {"Statuswaarde": "Ongecontroleerd", "Kwaliteitswaardecode": "00"},
                    }
                ],
            }
        )
    # Include an out-of-scope forecast series that must be ignored cleanly
    series_list.append(
        {
            "AquoMetadata": {
                "Compartiment": {"Code": "OW"},
                "Grootheid": {"Code": "Q"},
                "Eenheid": {"Code": "m3/s"},
                "Hoedanigheid": {"Code": "NVT"},
                "ProcesType": "verwachting",
                "WaardeBewerkingsMethode": {"Code": "NVT"},
                "WaardeBepalingsMethode": {"Code": "RWSM-F232"},
                "Groepering": {"Code": ""},
            },
            "MetingenLijst": [
                {
                    "Tijdstip": "2020-03-01T00:00:00.000+01:00",
                    "Meetwaarde": {"Waarde_Numeriek": 9999.0, "Waarde_Alfanumeriek": "9999"},
                    "WaarnemingMetadata": {"Statuswaarde": "Ongecontroleerd", "Kwaliteitswaardecode": "00"},
                }
            ],
        }
    )
    return json.dumps({"Succesvol": True, "WaarnemingenLijst": series_list}).encode("utf-8")


def test_config_and_window_declarations_match_empirically_validated_spans() -> None:
    cfg = config()
    assert cfg.zone == ZoneValue("+01:00")
    assert len(cfg.products) == 10
    assert cfg.products[ProductId("discharge_m3d_nvt")].unit is Unit.M3_S
    assert cfg.products[ProductId("stage_nap_nvt")].unit is Unit.M
    assert cfg.products[ProductId("water_temperature_nvt")].unit is Unit.DEG_C
    for prod_cfg in cfg.products.values():
        assert isinstance(prod_cfg.semantics, UnknownTemporalSupport)

    decls = window_declarations().products
    assert len(decls) == 10
    for pid, decl in decls.items():
        assert decl.granularity == WindowGranularity("capped-span")
        assert decl.rendering is WindowRenderingVocabulary.ISO_INSTANT
        assert decl.stop_convention is StopConvention.INCLUSIVE
        if str(pid).endswith("_gem24h"):
            assert decl.size == 3650
        else:
            assert decl.size == 90

    assert len(SHARED_ACQUISITION_PRODUCTS) == 3
    assert all(isinstance(group, frozenset) and len(group) == 2 for group in SHARED_ACQUISITION_PRODUCTS)


def test_fetch_single_product_enforces_meting_and_preserves_milliseconds() -> None:
    cfg = config()
    start = datetime(2020, 3, 1, 0, 0, 0, tzinfo=UTC)
    stop = datetime(2020, 3, 5, 23, 59, 59, 999999, tzinfo=UTC)
    win = _rendered(start, stop)
    fw = _window(start, stop)
    transport = _RecordingTransport([_sample_waarnemingen_json(include_nvt=False, include_gem24h=True)])

    acq = fetch(
        ("lobith.bovenrijn.tolkamer",),
        (ProductId("discharge_m3s_gem24h"),),
        {ProductId("discharge_m3s_gem24h"): (win,)},
        fw,
        cfg,
        transport,
    )
    assert len(transport.requests) == 1
    req = transport.requests[0]
    assert req.method is HttpMethod.POST
    assert req.replay_safety is ReplaySafety.SAFE
    assert req.body is not None
    body = json.loads(req.body.decode("utf-8"))
    am = body["AquoPlusWaarnemingMetadata"]["AquoMetadata"]
    assert am["ProcesType"] == "meting"
    assert am["WaardeBewerkingsMethode"] == {"Code": "GEM24H"}
    assert body["Periode"]["Begindatumtijd"] == "2020-03-01T00:00:00.000+01:00"
    assert body["Periode"]["Einddatumtijd"] == "2020-03-05T23:59:59.999+01:00"
    assert len(acq.value) == 1
    assert not acq.failed_requests


def test_fetch_coacquires_matching_nvt_gem24h_pair_in_single_post_and_parse_group_splits() -> None:
    cfg = config()
    start = datetime(2020, 3, 1, 0, 0, 0, tzinfo=UTC)
    stop = datetime(2020, 3, 5, 23, 59, 59, tzinfo=UTC)
    win = _rendered(start, stop)
    fw = _window(start, stop)
    p_nvt = ProductId("discharge_m3s_nvt")
    p_gem = ProductId("discharge_m3s_gem24h")
    transport = _RecordingTransport([_sample_waarnemingen_json(include_nvt=True, include_gem24h=True)])

    acq = fetch(
        ("lobith.bovenrijn.tolkamer",),
        (p_nvt, p_gem),
        {p_nvt: (win,), p_gem: (win,)},
        fw,
        cfg,
        transport,
    )
    assert len(transport.requests) == 1
    assert transport.requests[0].body is not None
    am = json.loads(transport.requests[0].body.decode("utf-8"))["AquoPlusWaarnemingMetadata"]["AquoMetadata"]
    assert am["ProcesType"] == "meting"
    assert "WaardeBewerkingsMethode" not in am
    assert len(acq.value) == 1

    shared_payload = acq.value[0]
    pair_payloads = {
        ("lobith.bovenrijn.tolkamer", p_nvt): shared_payload,
        ("lobith.bovenrijn.tolkamer", p_gem): shared_payload,
    }
    parsed = parse_group(shared_payload, pair_payloads, cfg)
    nvt_res = parsed[("lobith.bovenrijn.tolkamer", p_nvt)]
    gem_res = parsed[("lobith.bovenrijn.tolkamer", p_gem)]

    # NVT has 2 parallel series (F216 + F230), 3 total rows (1 published null + 1 valid 0.0 + 1 normal)
    assert len(nvt_res.series) == 2
    assert {s.variant for s in nvt_res.series} == {"other:F216", "other:F230"}
    assert len(nvt_res.rows) == 3
    values = nvt_res.rows["value"].to_list()
    assert None in values
    assert 0.0 in values
    assert 4242.07 in values
    ann_table = nvt_res.annotations.observation_tables[NL_RWS_OBSERVATION_SCHEMA.schema_id]
    assert len(ann_table.rows) == 3
    assert ann_table.rows["kwaliteitswaardecode"].to_list() == ["00", "99", "00"]
    assert ann_table.rows["measured"].to_list() == [True, True, True]

    # GEM24H has 1 series, 1 row
    assert len(gem_res.series) == 1
    assert len(gem_res.rows) == 1
    assert gem_res.rows["value"].to_list() == [4312.0]


def test_fetch_isolates_transport_failures_and_splits_differing_rendered_windows() -> None:
    cfg = config()
    s1 = datetime(2020, 1, 1, 0, 0, 0, tzinfo=UTC)
    s2 = datetime(2020, 4, 1, 0, 0, 0, tzinfo=UTC)
    s3 = datetime(2020, 6, 30, 0, 0, 0, tzinfo=UTC)
    fw = _window(s1, s3)
    p_nvt = ProductId("discharge_m3s_nvt")
    p_gem = ProductId("discharge_m3s_gem24h")
    # Differing rendered_windows (2 NVT chunks vs 1 GEM24H chunk) -> separate requests with WaardeBewerkingsMethode
    transport = _RecordingTransport([b"", b"", b""])
    acq = fetch(
        ("lobith.bovenrijn.tolkamer",),
        (p_nvt, p_gem),
        {p_nvt: (_rendered(s1, s2), _rendered(s2 + timedelta(seconds=1), s3)), p_gem: (_rendered(s1, s3),)},
        fw,
        cfg,
        transport,
    )
    assert len(acq.value) == 3
    assert len(transport.requests) == 3
    wbws = [
        json.loads(r.body.decode("utf-8"))["AquoPlusWaarnemingMetadata"]["AquoMetadata"]["WaardeBewerkingsMethode"][
            "Code"
        ]
        for r in transport.requests
        if r.body is not None
    ]
    assert sorted(wbws) == ["GEM24H", "NVT", "NVT"]

    # Transport failure on one station does not block the other
    fail_transport = _RecordingTransport(
        {
            "bad.station": 400,
            "lobith.bovenrijn.tolkamer": b"",
        }
    )
    acq2 = fetch(
        ("bad.station", "lobith.bovenrijn.tolkamer"),
        (p_gem,),
        {p_gem: (_rendered(s1, s3),)},
        fw,
        cfg,
        fail_transport,
    )
    assert len(acq2.failed_requests) == 1
    assert acq2.failed_requests[0].series.station_id == "bad.station"
    assert len(acq2.value) == 1
    assert acq2.value[0].station_products == (("lobith.bovenrijn.tolkamer", p_gem),)


def test_parse_handles_http_204_empty_gem_only_and_invalid_json() -> None:
    cfg = config()
    start = datetime(1990, 3, 1, 0, 0, 0, tzinfo=UTC)
    stop = datetime(1990, 3, 10, 23, 59, 59, tzinfo=UTC)
    fw = _window(start, stop)
    p_nvt = ProductId("discharge_m3s_nvt")
    p_gem = ProductId("discharge_m3s_gem24h")
    origin = SourceCallOrigin(
        url="https://ddapi20-waterwebservices.rijkswaterstaat.nl/ONLINEWAARNEMINGENSERVICES/OphalenWaarnemingen",
        request_parameters={},
        status_code=200,
        retrieved_at=datetime(2026, 11, 26, 10, 0, 0, tzinfo=UTC),
        content_type="application/json",
        source_path=UnknownOriginFact(),
        query=UnknownOriginFact(),
        attempts=1,
    )

    # HTTP 204 empty bytes -> OutcomeStatus.NO_MATCH (no concrete series identity returned)
    p_empty = Payload(
        source_coordinates=SourceCoordinates(cfg.products[p_nvt].coordinates.value),
        station_products=(("lobith.bovenrijn.tolkamer", p_nvt),),
        fetch_window=fw,
        content=b"",
        origin=origin,
        prerequisite_calls=(),
    )
    res_empty = parse(p_empty, cfg)
    assert res_empty.rows.is_empty()
    assert len(res_empty.outcomes) == 1
    assert res_empty.outcomes[0].status is OutcomeStatus.NO_MATCH
    assert res_empty.inventories[0].members == ()

    # 1990 GEM24H-only payload in parse_group -> NVT is NO_MATCH, GEM24H is SUCCESS
    p_1990 = Payload(
        source_coordinates=SourceCoordinates(cfg.products[p_nvt].coordinates.value),
        station_products=(("lobith.bovenrijn.tolkamer", p_nvt), ("lobith.bovenrijn.tolkamer", p_gem)),
        fetch_window=fw,
        content=_sample_waarnemingen_json(include_nvt=False, include_gem24h=True),
        origin=origin,
        prerequisite_calls=(),
    )
    grouped = parse_group(
        p_1990,
        {("lobith.bovenrijn.tolkamer", p_nvt): p_1990, ("lobith.bovenrijn.tolkamer", p_gem): p_1990},
        cfg,
    )
    assert grouped[("lobith.bovenrijn.tolkamer", p_nvt)].outcomes[0].status is OutcomeStatus.NO_MATCH
    assert grouped[("lobith.bovenrijn.tolkamer", p_gem)].outcomes[0].status is OutcomeStatus.SUCCESS

    # Invalid JSON -> OutcomeStatus.FAILED
    p_bad = Payload(
        source_coordinates=SourceCoordinates(cfg.products[p_nvt].coordinates.value),
        station_products=(("lobith.bovenrijn.tolkamer", p_nvt),),
        fetch_window=fw,
        content=b"not-json",
        origin=origin,
        prerequisite_calls=(),
    )
    res_bad = parse(p_bad, cfg)
    assert res_bad.outcomes[0].status is OutcomeStatus.FAILED


def test_parse_merges_duplicate_methods_ignores_malformed_out_of_scope_and_preserves_negatives() -> None:
    cfg = config()
    start = datetime(2020, 3, 28, 0, 0, 0, tzinfo=UTC)
    stop = datetime(2020, 3, 30, 23, 59, 59, tzinfo=UTC)
    fw = _window(start, stop)
    p_stage = ProductId("stage_nap_nvt")
    origin = SourceCallOrigin(
        url="https://ddapi20-waterwebservices.rijkswaterstaat.nl/ONLINEWAARNEMINGENSERVICES/OphalenWaarnemingen",
        request_parameters={},
        status_code=200,
        retrieved_at=datetime(2026, 11, 26, 10, 0, 0, tzinfo=UTC),
        content_type="application/json",
        source_path=UnknownOriginFact(),
        query=UnknownOriginFact(),
        attempts=1,
    )
    body = json.dumps(
        {
            "WaarnemingenLijst": [
                # Out-of-scope forecast with malformed MetingenLijst must be skipped before row parsing
                {
                    "AquoMetadata": {
                        "Compartiment": {"Code": "OW"},
                        "Grootheid": {"Code": "WATHTE"},
                        "Eenheid": {"Code": "cm"},
                        "Hoedanigheid": {"Code": "NAP"},
                        "ProcesType": "verwachting",
                        "WaardeBewerkingsMethode": {"Code": "NVT"},
                        "WaardeBepalingsMethode": {"Code": "other:F999"},
                        "Groepering": {"Code": ""},
                    },
                    "MetingenLijst": [{"Tijdstip": None}],
                },
                # Two WaarnemingenLijst entries sharing other:F007 across mixed +01:00 / +02:00 offsets
                {
                    "AquoMetadata": {
                        "Compartiment": {"Code": "OW"},
                        "Grootheid": {"Code": "WATHTE"},
                        "Eenheid": {"Code": "cm"},
                        "Hoedanigheid": {"Code": "NAP"},
                        "ProcesType": "meting",
                        "WaardeBewerkingsMethode": {"Code": "NVT"},
                        "WaardeBepalingsMethode": {"Code": "other:F007"},
                        "Groepering": {"Code": ""},
                        "MeetApparaat": {"Code": "sensor-A"},
                    },
                    "MetingenLijst": [
                        {
                            "Tijdstip": "2020-03-28T12:00:00.000+01:00",
                            "Meetwaarde": {"Waarde_Numeriek": -12.5, "Waarde_Alfanumeriek": "-12.5"},
                            "WaarnemingMetadata": {"Statuswaarde": "Gecontroleerd", "Kwaliteitswaardecode": "00"},
                        }
                    ],
                },
                {
                    "AquoMetadata": {
                        "Compartiment": {"Code": "OW"},
                        "Grootheid": {"Code": "WATHTE"},
                        "Eenheid": {"Code": "cm"},
                        "Hoedanigheid": {"Code": "NAP"},
                        "ProcesType": "meting",
                        "WaardeBewerkingsMethode": {"Code": "NVT"},
                        "WaardeBepalingsMethode": {"Code": "other:F007"},
                        "Groepering": {"Code": ""},
                        "MeetApparaat": {"Code": "sensor-B"},
                    },
                    "MetingenLijst": [
                        {
                            "Tijdstip": "2020-03-29T12:00:00.000+02:00",
                            "Meetwaarde": {"Waarde_Numeriek": -3.0, "Waarde_Alfanumeriek": "-3.0"},
                            "WaarnemingMetadata": {"Statuswaarde": "Gecontroleerd", "Kwaliteitswaardecode": "00"},
                        }
                    ],
                },
                # Admitted series with empty MetingenLijst -> OutcomeStatus.EMPTY
                {
                    "AquoMetadata": {
                        "Compartiment": {"Code": "OW"},
                        "Grootheid": {"Code": "WATHTE"},
                        "Eenheid": {"Code": "cm"},
                        "Hoedanigheid": {"Code": "NAP"},
                        "ProcesType": "meting",
                        "WaardeBewerkingsMethode": {"Code": "NVT"},
                        "WaardeBepalingsMethode": {"Code": "other:F008"},
                        "Groepering": {"Code": ""},
                    },
                    "MetingenLijst": [],
                },
            ]
        }
    ).encode("utf-8")

    payload = Payload(
        source_coordinates=SourceCoordinates(cfg.products[p_stage].coordinates.value),
        station_products=(("hoek.van.holland", p_stage),),
        fetch_window=fw,
        content=body,
        origin=origin,
        prerequisite_calls=(),
    )
    res = parse(payload, cfg)
    assert len(res.series) == 2
    assert {s.variant for s in res.series} == {"other:F007", "other:F008"}
    f007 = next(s for s in res.series if s.variant == "other:F007")
    assert {f.time_zone.value for f in f007.facts} == {"+01:00", "+02:00"}
    assert len(res.rows) == 2
    assert res.rows["value"].to_list() == [-12.5, -3.0]
    assert len(res.inventories[0].members) == 2
    statuses = {o.series_id: o.status for o in res.outcomes}
    assert statuses[f007.series_id] is OutcomeStatus.SUCCESS
    f008 = next(s for s in res.series if s.variant == "other:F008")
    assert statuses[f008.series_id] is OutcomeStatus.EMPTY
