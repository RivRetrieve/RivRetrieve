"""Tests for Austria eHYD series annotation extraction, alignment, storage, and public workflows."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.engine import (
    Payload,
    SourceCallOrigin,
    SourceCoordinates,
    UnknownOriginFact,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.observations import ObservationDataSchema, ReceiptAuthorship
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.at_ehyd.annotations import (
    AT_EHYD_GUIDE_URL,
    AT_EHYD_SERIES_SCHEMA,
)
from rivretrieve._internal.providers.at_ehyd.config import (
    AtEhydInfoCoordinates,
    AtEhydOwfCoordinates,
    AtEhydPegelCoordinates,
    AtEhydPegelEndpointCoordinates,
    config,
)
from rivretrieve._internal.providers.at_ehyd.parse import parse
from rivretrieve._internal.source_annotations import CATALOG_SCHEMA, AnnotationScope
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.transport import (
    TransportFailure,
    TransportFailureCategory,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

_RETRIEVED_AT = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
_RECORDED_SCOPE = "maintenance/observations/at_ehyd/retrieval"


def _origin(url: str = "https://ehyd.gv.at/services/test") -> SourceCallOrigin:
    return SourceCallOrigin(
        url=url,
        request_parameters={},
        status_code=200,
        retrieved_at=_RETRIEVED_AT,
        content_type="text/plain",
        source_path=UnknownOriginFact(),
        query=UnknownOriginFact(),
    )


def _window(start: datetime, end: datetime):
    return _make_fetch_window(WindowEndpoint.from_datetime(start), WindowEndpoint.from_datetime(end))


def _owf_csv(
    *,
    station: str = "209486",
    unit: str = "[m³/s]",
    descriptor: str = "Abfluss,I,mit,T,1",
    exportzeitraum: str = "[01.01.2020 00:00,01.01.2024 00:00]",
    include_interval_rule: bool = True,
    lines: list[str],
) -> bytes:
    header = [
        "Stammdaten:",
        "Messstelle:                ;Testpegel",
        f"HZB-Nummer:                ;{station}",
        f"Einheit:                   ;{unit}",
        f"Exportzeitreihe:           ;{descriptor}",
    ]
    if include_interval_rule:
        header.append(
            "Zeitreihenart:             ;Der Intervallwert gilt bis zum nächsten Zeitpunkt mit einem Wert oder Lücke."
        )
    header.extend([f"Exportzeitraum:            ;{exportzeitraum}", "Werte:", *lines, ""])
    return "\r\n".join(header).encode("cp1252")


def _info_bytes(station: str, files: list[tuple[int, str]]) -> bytes:
    return json.dumps(
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
                                                "fileNr": nr,
                                                "fileName": f"{prefix}-{station}.csv",
                                                "hzbnr": int(station),
                                                "msttyp": "owf",
                                            }
                                            for nr, prefix in files
                                        ]
                                    },
                                },
                            ]
                        }
                    }
                ],
            }
        ]
    ).encode("utf-8")


def _load_recorded_response(root: Path, group: str, name: str, request: TransportRequest) -> TransportResponse:
    base = root / _RECORDED_SCOPE / group / name
    content = base.with_suffix(".body").read_bytes()
    receipt = json.loads(base.with_suffix(".receipt.json").read_text())
    source = urlsplit(str(receipt["url"]))
    expected_params = {key: vals[0] for key, vals in parse_qs(source.query, keep_blank_values=True).items()}
    assert dict(request.params or {}) == expected_params
    headers = receipt.get("response_headers")
    content_type = headers.get("content-type") if isinstance(headers, dict) else None
    retrieved_at = datetime.fromisoformat(str(receipt["acquired_at"]).replace("Z", "+00:00"))
    return TransportResponse(
        content=content,
        status_code=int(str(receipt["http_status"])),
        retrieved_at=retrieved_at,
        content_type=str(content_type) if content_type is not None else None,
        url=f"{source.scheme}://{source.netloc}{source.path}",
        request_parameters=expected_params,
    )


def _select_products(station: str, *products: str) -> rr.Selection:
    selected = rr.find(provider="at_ehyd", station=station)
    series_ids = rr.as_frame(selected).filter(pl.col("product_id").is_in(products))["series_id"].to_list()
    assert len(series_ids) == len(products)
    return rr.pick(selected, series_id=series_ids)


def test_at_ehyd_series_schema_definition() -> None:
    assert AT_EHYD_GUIDE_URL == "https://ehyd.gv.at/assets/documents/eHYD_Allgemein.pdf"
    assert AT_EHYD_SERIES_SCHEMA.schema_id == "at_ehyd.series"
    assert AT_EHYD_SERIES_SCHEMA.provider_id == "at_ehyd"
    assert AT_EHYD_SERIES_SCHEMA.scope is AnnotationScope.SERIES
    assert [field.name for field in AT_EHYD_SERIES_SCHEMA.fields] == ["data_quality"]
    assert AT_EHYD_SERIES_SCHEMA.fields[0].dtype == "String"
    assert AT_EHYD_SERIES_SCHEMA.fields[0].reference_url == AT_EHYD_GUIDE_URL


@pytest.mark.parametrize(
    ("product_id", "prefix", "unit", "descriptor", "interval_rule", "lines"),
    [
        ("owf_abfl_tagesmittel", "Q-Tagesmittel", "[m³/s]", "Abfluss,I,mit,T,1", True, ["01.01.2023 00:00:00; 12,5"]),
        ("owf_abfl_monatsminima", "Q-Monatsminima", "[m³/s]", "Abfluss,M,min,M,1", False, ["05.01.2023 06:00:00; 1,2"]),
        (
            "owf_abfl_monatsmaxima",
            "Q-Monatsmaxima",
            "[m³/s]",
            "Abfluss,M,max,M,1",
            False,
            ["18.01.2023 06:00:00; 48,6"],
        ),
        (
            "owf_wasserst_tagesmittel",
            "W-Tagesmittel",
            "[cm]",
            "Wasserstand,I,mit,T,1",
            True,
            ["01.01.2023 00:00:00; 150"],
        ),
        (
            "owf_wasserst_monatsminima",
            "W-Monatsminima",
            "[cm]",
            "Wasserstand,M,min,M,1",
            False,
            ["05.01.2023 06:00:00; -50"],
        ),
        (
            "owf_wasserst_monatsmaxima",
            "W-Monatsmaxima",
            "[cm]",
            "Wasserstand,M,max,M,1",
            False,
            ["18.01.2023 06:00:00; 210"],
        ),
        (
            "owf_wassertemp_monatsmittel",
            "WT-Monatsmittel",
            "[°C]",
            "WTemperatur,I,mit,M,1",
            True,
            ["01.01.2023 00:00:00; 4,2"],
        ),
    ],
)
def test_at_ehyd_all_owf_products_emit_gepruefte_daten_series_annotation(
    product_id: str,
    prefix: str,
    unit: str,
    descriptor: str,
    interval_rule: bool,
    lines: list[str],
) -> None:
    payload = Payload(
        SourceCoordinates(AtEhydOwfCoordinates(product_id, prefix)),
        (("209486", ProductId(product_id)),),
        _window(datetime(2023, 1, 1), datetime(2023, 12, 31, 23, 59, 59)),
        _owf_csv(unit=unit, descriptor=descriptor, include_interval_rule=interval_rule, lines=lines),
        _origin(),
        (),
    )
    parsed = parse(payload, config())
    assert parsed.annotations.observation_tables == {}
    table = parsed.annotations.series_tables["at_ehyd.series"]
    assert table.schema == AT_EHYD_SERIES_SCHEMA
    assert table.rows.to_dicts() == [{"series_id": parsed.series[0].series_id, "data_quality": "Geprüfte Daten"}]


def test_at_ehyd_owf_gap_markers_and_bounded_empty_behavior() -> None:
    cfg = config()
    gapped = parse(
        Payload(
            SourceCoordinates(AtEhydOwfCoordinates("owf_abfl_tagesmittel", "Q-Tagesmittel")),
            (("209486", ProductId("owf_abfl_tagesmittel")),),
            _window(datetime(2023, 1, 1), datetime(2023, 1, 5, 23, 59, 59)),
            _owf_csv(
                lines=[
                    "01.01.2023 00:00:00; 10,0",
                    "02.01.2023 00:00:00; Lücke",
                    "03.01.2023 00:00:00; 11,0",
                    "01.01.2024 00:00:00; Lücke",
                ]
            ),
            _origin(),
            (),
        ),
        cfg,
    )
    assert any(issue.code == "source.gap_marker" for issue in gapped.issues)
    assert gapped.annotations.observation_tables == {}
    assert gapped.annotations.series_tables["at_ehyd.series"].rows["data_quality"].to_list() == ["Geprüfte Daten"]

    bounded_empty = parse(
        Payload(
            SourceCoordinates(AtEhydOwfCoordinates("owf_wassertemp_monatsmittel", "WT-Monatsmittel")),
            (("208058", ProductId("owf_wassertemp_monatsmittel")),),
            _window(datetime(2020, 1, 1), datetime(2023, 12, 31)),
            _owf_csv(
                station="208058",
                unit="[°C]",
                descriptor="WTemperatur,I,mit,M,1",
                exportzeitraum="[01.01.2020 00:00,01.01.2024 00:00]",
                lines=["Invalid; Lücke"],
            ),
            _origin(),
            (),
        ),
        cfg,
    )
    assert [item.status for item in bounded_empty.outcomes] == [OutcomeStatus.EMPTY]
    assert bounded_empty.annotations.series_tables["at_ehyd.series"].rows["data_quality"].to_list() == [
        "Geprüfte Daten"
    ]


@pytest.mark.parametrize(
    ("product_id", "subsystem", "parameter", "body"),
    [
        (
            "pegel_bgis_abfluss",
            "pegel_bgis",
            "Abfluss",
            {
                "hzbnr": 209486,
                "parameter": "Abfluss",
                "einheit": "m³/s",
                "valCount": 1,
                "categories": ["2026-10-31 10:00:00"],
                "data": [15.5],
            },
        ),
        (
            "pegel_bgis_wasserstand",
            "pegel_bgis",
            "Wasserstand",
            {
                "hzbnr": 209486,
                "parameter": "Wasserstand",
                "einheit": "cm",
                "valCount": 1,
                "categories": ["2026-10-31 10:00:00"],
                "data": [120.0],
            },
        ),
        (
            "pegel_longterm_abfluss",
            "pegel_longterm",
            "Abfluss",
            {
                "parameter": "Abfluss",
                "einheit": "m³/s",
                "points_in_time": ["2026-10-31"],
                "current_value": [14.2],
            },
        ),
        (
            "pegel_longterm_wasserstand",
            "pegel_longterm",
            "Wasserstand",
            {
                "parameter": "Wasserstand",
                "einheit": "cm",
                "points_in_time": ["2026-10-31"],
                "current_value": [125.0],
            },
        ),
    ],
)
def test_at_ehyd_all_pegel_products_emit_ungepruefte_rohdaten_series_annotation(
    product_id: str,
    subsystem: str,
    parameter: str,
    body: dict[str, object],
) -> None:
    payload = Payload(
        SourceCoordinates(AtEhydPegelCoordinates(subsystem, parameter)),
        (("209486", ProductId(product_id)),),
        _window(datetime(2026, 10, 30), datetime(2026, 11, 1)),
        json.dumps(body).encode("utf-8"),
        _origin(),
        (),
    )
    parsed = parse(payload, config())
    assert parsed.annotations.observation_tables == {}
    table = parsed.annotations.series_tables["at_ehyd.series"]
    assert table.rows.to_dicts() == [{"series_id": parsed.series[0].series_id, "data_quality": "ungeprüfte Rohdaten!"}]


def test_at_ehyd_unsuccessful_outcomes_omit_annotations_and_multipair_merges() -> None:
    cfg = config()
    win = _window(datetime(2026, 10, 30), datetime(2026, 11, 1))

    failed = parse(
        Payload(
            SourceCoordinates(AtEhydOwfCoordinates("owf_abfl_tagesmittel", "Q-Tagesmittel")),
            (("209486", ProductId("owf_abfl_tagesmittel")),),
            win,
            b"",
            _origin(),
            (),
        ),
        cfg,
    )
    assert [item.status for item in failed.outcomes] == [OutcomeStatus.FAILED]
    assert failed.annotations.is_empty

    unsupported = parse(
        Payload(
            SourceCoordinates(AtEhydOwfCoordinates("owf_wasserst_monatsminima", "W-Monatsminima")),
            (("203539", ProductId("owf_wasserst_monatsminima")),),
            win,
            _owf_csv(
                station="203539",
                unit="[]",
                descriptor="Wasserstand,M,min,M,1",
                exportzeitraum="[01.01.1997 00:00,+-Infty]",
                include_interval_rule=False,
                lines=["01.01.2020 00:00:00; 10"],
            ),
            _origin(),
            (),
        ),
        cfg,
    )
    assert [item.status for item in unsupported.outcomes] == [OutcomeStatus.UNSUPPORTED]
    assert unsupported.annotations.is_empty

    unresolved = parse(
        Payload(
            SourceCoordinates(AtEhydPegelCoordinates("pegel_bgis", "Wasserstand")),
            (("209288", ProductId("pegel_bgis_wasserstand")),),
            win,
            json.dumps(
                {
                    "hzbnr": 209288,
                    "parameter": "Wasserstand",
                    "einheit": "cm",
                    "valCount": 0,
                    "categories": None,
                    "data": None,
                }
            ).encode("utf-8"),
            _origin(),
            (),
        ),
        cfg,
    )
    assert [item.status for item in unresolved.outcomes] == [OutcomeStatus.UNRESOLVED]
    assert unresolved.annotations.is_empty

    no_match_info = parse(
        Payload(
            SourceCoordinates(AtEhydInfoCoordinates()),
            (("200675", ProductId("owf_abfl_tagesmittel")),),
            win,
            b"[[]]",
            _origin(),
            (),
        ),
        cfg,
    )
    assert [item.status for item in no_match_info.outcomes] == [OutcomeStatus.NO_MATCH]
    assert no_match_info.annotations.is_empty

    mixed_bgis = parse(
        Payload(
            SourceCoordinates(AtEhydPegelEndpointCoordinates("pegel_bgis")),
            (
                ("209486", ProductId("pegel_bgis_abfluss")),
                ("209486", ProductId("pegel_bgis_wasserstand")),
            ),
            win,
            json.dumps(
                {
                    "hzbnr": 209486,
                    "parameter": "Abfluss",
                    "einheit": "m³/s",
                    "valCount": 1,
                    "categories": ["2026-10-31 10:00:00"],
                    "data": [15.5],
                }
            ).encode("utf-8"),
            _origin(),
            (),
        ),
        cfg,
    )
    outcomes_by_product = {item.product_id: item.status for item in mixed_bgis.outcomes}
    assert OutcomeStatus.SUCCESS in {
        item.status for item in mixed_bgis.outcomes if item.product_id == "pegel_bgis_abfluss"
    }
    assert outcomes_by_product["pegel_bgis_wasserstand"] is OutcomeStatus.NO_MATCH
    q_series_id = next(item.series_id for item in mixed_bgis.series if item.product_id == "pegel_bgis_abfluss")
    assert mixed_bgis.annotations.series_tables["at_ehyd.series"].rows.to_dicts() == [
        {"series_id": q_series_id, "data_quality": "ungeprüfte Rohdaten!"}
    ]


def test_at_ehyd_public_series_annotations_cache_pick_to_utc_and_bundle_roundtrip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))

    owf_csv = _owf_csv(
        station="209486",
        descriptor="Abfluss,I,mit,T,1",
        unit="[m³/s]",
        exportzeitraum="[01.01.2020 00:00,01.01.2024 00:00]",
        lines=[
            "01.01.2020 00:00:00; 10,0",
            "02.01.2020 00:00:00; Lücke",
            "03.01.2020 00:00:00; 12,0",
            "01.01.2024 00:00:00; Lücke",
        ],
    )
    info_doc = _info_bytes("209486", [(5, "Q-Tagesmittel")])
    bgis_doc = json.dumps(
        {
            "hzbnr": 206557,
            "parameter": "Wasserstand",
            "einheit": "cm",
            "valCount": 2,
            "categories": ["2020-01-01 00:00:00", "2020-01-03 00:00:00"],
            "data": [150.0, 175.0],
        }
    ).encode("utf-8")

    class _MixedTransport:
        calls = 0
        fail_all = False

        def send(self, request: TransportRequest) -> TransportResponse:
            self.calls += 1
            if self.fail_all:
                raise TransportFailure(
                    request,
                    TransportFailureReason.HTTP_STATUS,
                    1,
                    status_code=503,
                    category=TransportFailureCategory.HTTP_STATUS,
                )
            params = dict(request.params or {})
            if request.url.endswith("/Messstellen/info"):
                return TransportResponse(info_doc, 200, _RETRIEVED_AT, "application/json", request.url, params)
            if request.url.endswith("/MessstellenExtraData/owf"):
                return TransportResponse(owf_csv, 200, _RETRIEVED_AT, "text/csv", request.url, params)
            assert request.url.endswith("/Diagram/pegelBgis")
            return TransportResponse(bgis_doc, 200, _RETRIEVED_AT, "application/json", request.url, params)

    transport = _MixedTransport()
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)

    owf_sel = _select_products("209486", "owf_abfl_tagesmittel")
    bgis_sel = _select_products("206557", "pegel_bgis_wasserstand")
    combined_sel = rr.pick(
        rr.find(provider="at_ehyd", station=["209486", "206557"]),
        series_id=[
            *owf_sel.series[0].series_id.split(),
            *bgis_sel.series[0].series_id.split(),
        ],
    )
    assert rr.annotations(combined_sel).is_empty()

    fresh = rr.fetch(
        combined_sel,
        start="2020-01-01T00:00:00",
        end="2020-01-03T00:00:00",
        cache="reuse",
        receipts=True,
    )
    calls_after_fresh = transport.calls
    assert calls_after_fresh == 3

    catalog = rr.annotations(fresh)
    assert catalog.schema == CATALOG_SCHEMA
    assert catalog.select("schema", "scope", "name").rows() == [("at_ehyd.series", "series", "data_quality")]

    series_plain = rr.series(fresh)
    assert "data_quality" not in series_plain.columns
    series_with_ann = rr.series(fresh, annotations=True)
    assert "data_quality" in series_with_ann.columns
    quality_by_product = dict(series_with_ann.select("product_id", "data_quality").iter_rows())
    assert quality_by_product == {
        "owf_abfl_tagesmittel": "Geprüfte Daten",
        "pegel_bgis_wasserstand": "ungeprüfte Rohdaten!",
    }
    assert list(fresh.to_polars(annotations=True).columns) == list(ObservationDataSchema.polars_schema)

    cached_owf = rr.fetch(
        owf_sel,
        start="2020-01-01T00:00:00",
        end="2020-01-03T00:00:00",
        cache="reuse",
        receipts=True,
    )
    assert transport.calls == calls_after_fresh
    assert all(entry.authorship is ReceiptAuthorship.STORE_EXCERPT for entry in cached_owf.receipts.entries)
    pl_testing.assert_frame_equal(
        rr.annotations(cached_owf, schema="at_ehyd.series"),
        rr.annotations(rr.pick(fresh, station="209486"), schema="at_ehyd.series"),
    )
    assert rr.series(cached_owf, annotations=True)["data_quality"].to_list() == ["Geprüfte Daten"]

    picked = rr.pick(fresh, station="209486")
    assert rr.annotations(picked, schema="at_ehyd.series")["data_quality"].to_list() == ["Geprüfte Daten"]

    pegel_only = rr.fetch(bgis_sel, start="2020-01-01T00:00:00", end="2020-01-03T00:00:00", cache="reuse")
    utc_pegel = rr.to_utc(pegel_only)
    assert utc_pegel.data["time_zone"].unique().to_list() == ["+00:00"]
    assert rr.annotations(utc_pegel, schema="at_ehyd.series")["data_quality"].to_list() == ["ungeprüfte Rohdaten!"]

    bundle_path = tmp_path / "at_ehyd.rr"
    bundle_path.write_bytes(rr.to_bundle(fresh))
    restored = rr.from_bundle(bundle_path.read_bytes())
    pl_testing.assert_frame_equal(rr.annotations(restored), catalog)
    pl_testing.assert_frame_equal(
        rr.annotations(restored, schema="at_ehyd.series"),
        rr.annotations(fresh, schema="at_ehyd.series"),
    )
    pl_testing.assert_frame_equal(rr.series(restored, annotations=True), series_with_ann)

    transport.fail_all = True
    failed_refresh = rr.fetch(
        combined_sel,
        start="2020-01-01T00:00:00",
        end="2020-01-03T00:00:00",
        cache="refresh",
        on_issue="ignore",
    )
    assert any(issue.code == "source.request_failed" for issue in failed_refresh.issues)
    pl_testing.assert_frame_equal(failed_refresh.data, fresh.data)
    pl_testing.assert_frame_equal(
        rr.annotations(failed_refresh, schema="at_ehyd.series"),
        rr.annotations(fresh, schema="at_ehyd.series"),
    )
    pl_testing.assert_frame_equal(
        rr.series(failed_refresh, annotations=True).select(
            "provider_id", "station_id", "product_id", "series_id", "data_quality"
        ),
        series_with_ann.select("provider_id", "station_id", "product_id", "series_id", "data_quality"),
    )


@pytest.mark.recorded(_RECORDED_SCOPE)
def test_at_ehyd_recorded_replay_emits_series_annotations(
    retained_evidence_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _RecordedReplay:
        def send(self, request: TransportRequest) -> TransportResponse:
            if request.url.endswith("/Messstellen/info"):
                return _load_recorded_response(retained_evidence_root, "access", "messstellen-info-209486", request)
            if request.url.endswith("/MessstellenExtraData/owf"):
                return _load_recorded_response(
                    retained_evidence_root, "access", "owf-209486-file5-q-tagesmittel", request
                )
            if request.url.endswith("/Diagram/pegelBgis"):
                return _load_recorded_response(retained_evidence_root, "access", "pegel-bgis-209486", request)
            assert request.url.endswith("/Diagram/pegelLongterm")
            return _load_recorded_response(retained_evidence_root, "access", "pegel-longterm-209486", request)

    monkeypatch.setattr(discovery, "HttpClient", lambda: _RecordedReplay())

    owf_res = rr.fetch(
        _select_products("209486", "owf_abfl_tagesmittel"),
        start="2023-12-25",
        end="2023-12-31T23:59:59",
        cache="bypass",
    )
    assert rr.annotations(owf_res)["schema"].to_list() == ["at_ehyd.series"]
    assert rr.series(owf_res, annotations=True)["data_quality"].to_list() == ["Geprüfte Daten"]

    bgis_res = rr.fetch(
        _select_products("209486", "pegel_bgis_abfluss"),
        start="2026-09-25",
        end="2026-11-02",
        cache="bypass",
        on_issue="ignore",
    )
    assert rr.annotations(bgis_res)["schema"].to_list() == ["at_ehyd.series"]
    assert rr.series(bgis_res, annotations=True)["data_quality"].to_list() == ["ungeprüfte Rohdaten!"]

    lt_res = rr.fetch(
        _select_products("209486", "pegel_longterm_abfluss"),
        start="2026-01-01",
        end="2026-12-31T23:59:59",
        cache="bypass",
        on_issue="ignore",
    )
    assert rr.annotations(lt_res)["schema"].to_list() == ["at_ehyd.series"]
    assert rr.series(lt_res, annotations=True)["data_quality"].to_list() == ["ungeprüfte Rohdaten!"]
