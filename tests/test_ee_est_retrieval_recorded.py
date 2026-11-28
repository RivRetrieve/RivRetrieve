"""Recorded replay of retained Keskkonnaagentuur (`ee_est`) HTTP captures across all 18 products."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit  # noqa: TID251 - URL query parsing for receipt replay only

import pytest

from rivretrieve._internal.driver import drive
from rivretrieve._internal.engine import (
    ObservationRequest,
    ProductWindowDeclarations,
    ProviderConfig,
    RequestedWindow,
    WindowEndpoint,
)
from rivretrieve._internal.observations import ReceiptMode
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.ee_est.annotations import EE_EST_ESTMODEL_SCHEMA
from rivretrieve._internal.providers.ee_est.config import config, window_declarations
from rivretrieve._internal.providers.ee_est.declaration import declaration
from rivretrieve._internal.providers.ee_est.fetch import EeEstRequestPlanner, fetch
from rivretrieve._internal.providers.ee_est.parse import parse
from rivretrieve._internal.providers.ee_est.series import PRODUCT_SPECS
from rivretrieve._internal.recordings import RecordedRequest, RecordingEnvelope, ReplayTransport
from rivretrieve._internal.source_series import InventoryCompleteness, OutcomeStatus
from rivretrieve._internal.store import StoreRoot
from rivretrieve._internal.transport import TRANSPORT_POLICY, HttpMethod
from tests.test_internal_driver import _provenance

_SCOPE = "maintenance/observations/ee_est/retrieval"

_RECORDING_SLUGS: tuple[str, ...] = (
    "em-sja8821000-q-mean-2026",
    "em-sja8821000-q-max-2025-2026",
    "em-sja8821000-q-min-2025-2026",
    "em-sja8821000-h-mean-2025-2026",
    "em-sja8821000-h-max-2025-2026",
    "em-sja8821000-h-min-2025-2026",
    "em-sja8821000-t-mean-2026",
    "em-sja8821000-t-max-2025-2026",
    "em-sja8821000-t-min-2025-2026",
    "em-sja7331000-h-mean-1867-1891",
    "em-sja7331000-q-mean-1902-1926",
    "em-sja4456000-h-mean-2025-2026",
    "em-sja5432000-q-mean-2024",
    "em-sja8821000-q-mean-2030-empty",
    "em-invalid-station-404",
    "fh-41061-q-avg-dst-spring-2024",
    "fh-41061-q-max-dst-spring-2024",
    "fh-41061-q-min-dst-spring-2024",
    "fh-41061-wl-avg-dst-spring-2024",
    "fh-41061-wl-max-dst-spring-2024",
    "fh-41061-wl-min-dst-spring-2024",
    "fh-41061-wt-avg-dst-spring-2024",
    "fh-41061-wt-max-dst-spring-2024",
    "fh-41061-wt-min-dst-spring-2024",
    "fh-41061-wl-avg-dst-autumn-2024",
    "fh-41116-wl-avg-null-2025-11-27",
    "fh-41022-wl-avg-2026-10-01",
    "fh-41960-wl-avg-2026-10-01",
    "fh-41061-wl-avg-2000-empty",
    "sj-sja5524000-lookup",
)

# Independently read (published_id, series_id, facts_id, first_point, last_point) across Ahja captures.
_AHJA_EXPECTED: dict[str, tuple[str, str, str, tuple[datetime, float], tuple[datetime, float]]] = {
    "discharge_daily_max": (
        "SJA8821000:Q:MAXIMUM",
        "8d5f1211ace42f5621f6e55df27d02885fb9dbae066fe9f235b15b47d8a0e69b",
        "587cba49185cb659adbedc12b97d138d95fe6b03ea818cf2220e5f3aa500ee7f",
        (datetime(2025, 1, 1), 10.1),
        (datetime(2026, 11, 22), 6.84),
    ),
    "discharge_daily_mean": (
        "SJA8821000:Q:MEAN",
        "3685ee849e4be6f1af09d452f783bdf46462a09626592cb3043b73c373a17011",
        "03fa4d2ae7b1636f0afcb5ff59c1aa0d9ba33b8b63dca435f18a4a86757c06db",
        (datetime(2026, 1, 1), 5.5),
        (datetime(2026, 11, 22), 6.66),
    ),
    "discharge_daily_min": (
        "SJA8821000:Q:MINIMUM",
        "731c57d24af12a4c4fb704625f6cecf07c37b01d7f1c9a17d79b3000fb4d1f97",
        "9860ddadb41c37a75434506c8fa14818622cf91ebeecfca7aa15c4717e8fd6d1",
        (datetime(2025, 1, 1), 9.1),
        (datetime(2026, 11, 22), 6.41),
    ),
    "stage_daily_max": (
        "SJA8821000:H:MAXIMUM",
        "12fad742fc86372a169008ea9cb37368b18d235e06c54d461a95b324bff110a0",
        "9976cb124bb9e00c9ca11bd292769e73c4abde3005631f26a15274d2c6493536",
        (datetime(2025, 1, 1), 0.82),
        (datetime(2026, 11, 22), 0.57),
    ),
    "stage_daily_mean": (
        "SJA8821000:H:MEAN",
        "319737a873debd3970ca582b32fb2d29a52b887fa3a59fd5f5cd8d63281641a7",
        "2f9eebd3f0e1f8bdb613092ea3c710248c57c51d0cc9f887f126b8a0fe42fb91",
        (datetime(2025, 1, 1), 0.76),
        (datetime(2026, 11, 22), 0.56),
    ),
    "stage_daily_min": (
        "SJA8821000:H:MINIMUM",
        "588017b5e2db53d8378de2ec9b90a9010a9014d68a0583e735d7c493675d04cf",
        "e4c11cf4df6e1985ccc7fc6b3f45be915ee4f5619d73a20c39ba64ab9a92de27",
        (datetime(2025, 1, 1), 0.75),
        (datetime(2026, 11, 22), 0.55),
    ),
    "water_temperature_daily_max": (
        "SJA8821000:T:MAXIMUM",
        "3204da93d3c36e57d53cba14335183aae49db746af3d903f7bdf104b2ef6be0d",
        "74376b04234e8e407e9e413e5146786427692393c6f3b9f30325bc2899b9094e",
        (datetime(2025, 1, 1), 2.4),
        (datetime(2026, 11, 22), 3.5),
    ),
    "water_temperature_daily_mean": (
        "SJA8821000:T:MEAN",
        "582ad74ff1394e345d5fd0fa97608f78085e5b856e9c8afc63d96764cbdce408",
        "bad1fec715595a520ba222c0b57df3b73a4b7d6090ef9e19e1c89c237be6d598",
        (datetime(2026, 1, 1), 0.2),
        (datetime(2026, 11, 22), 3.4),
    ),
    "water_temperature_daily_min": (
        "SJA8821000:T:MINIMUM",
        "5f512bb46ac18fd320611472ea92e3fa97c7d4ac0fce348cee54fba93812a863",
        "d464cacc3dd092945e9b93825fc7f585b8e2a37d64d89d32447d0644e931daad",
        (datetime(2025, 1, 1), 1.3),
        (datetime(2026, 11, 22), 3.3),
    ),
    "discharge_hourly_max": (
        "41061:Äravool max",
        "25cadb415641f6123654cdbbad74f4199343bac6bda2c4e5a49e9d70e7777175",
        "f91c38349550b8cdd288f1dfa5125ceebb9897597f5fae69c848a49c8a4bef3c",
        (datetime(2024, 3, 30, 0, 0), 10.975),
        (datetime(2024, 4, 1, 23, 0), 10.665),
    ),
    "discharge_hourly_mean": (
        "41061:Äravool avg",
        "721af9089dd31b30b8ea086ec55a27a5fc8e2125ec4ca2659604e7e98551826e",
        "a60534ff3c6adadb55e902012288dd53d38805a285ae5fd7c5dbb020775ba1fa",
        (datetime(2024, 3, 30, 0, 0), 10.95),
        (datetime(2024, 4, 1, 23, 0), 10.641),
    ),
    "discharge_hourly_min": (
        "41061:Äravool min",
        "b9bc2cc82171c2bbd2f31d8b6c822f1c557c5b46df8172fe25084ba42e53f712",
        "f9b8038ea4062d701057fc30e5e1673053524564476d55332fe1cac7364dcc89",
        (datetime(2024, 3, 30, 0, 0), 10.926),
        (datetime(2024, 4, 1, 23, 0), 10.63),
    ),
    "stage_hourly_max": (
        "41061:WL max",
        "2986999f2ac47521f8c280d5b22e7029959265e208554f10f69f69ee47161701",
        "539e3dc2965ba5758e28dfa9745189d3a0390d6f5f77ea9e5583fc97127feedf",
        (datetime(2024, 3, 30, 0, 0), 1.1534),
        (datetime(2024, 4, 1, 23, 0), 1.1444),
    ),
    "stage_hourly_mean": (
        "41061:WL avg",
        "d8882a9d825e990daeddb93d1989506c4ef4fa48845c97f4bb719bbbc1ed5383",
        "fdb48a01f8dc1003e6c2015078d4c29b25c02c5ea25646b098e272ae951b6537",
        (datetime(2024, 3, 30, 0, 0), 1.1514),
        (datetime(2024, 4, 1, 23, 0), 1.1424),
    ),
    "stage_hourly_min": (
        "41061:WL min",
        "d5943c11d79f29fa4829332e143eb8bd4c6d9ce0af1d3b3160ad07c07b3dabe1",
        "ec3bf750865bee907f1a0ec7b7df68d212c70cfa97860f0317eda5de3732e7cd",
        (datetime(2024, 3, 30, 0, 0), 1.1494),
        (datetime(2024, 4, 1, 23, 0), 1.1414),
    ),
    "water_temperature_hourly_max": (
        "41061:WT max",
        "f22859ad0d79d241fc19947b235a70deec02259ff52c05b5de92053772484f13",
        "95e36955089310de36a472011c6013403ad3c4ecbd5e8e371b2ea2439c0d3b60",
        (datetime(2024, 3, 30, 0, 0), 5.2),
        (datetime(2024, 4, 1, 23, 0), 7.9),
    ),
    "water_temperature_hourly_mean": (
        "41061:WT avg",
        "1d069edb3420f52467fa4442911d2d3c942fb8755128e27f918b35af27ecab36",
        "09927a42b45c87ccf44195710e4deeb0ea628752201006379737d7f1688832b0",
        (datetime(2024, 3, 30, 0, 0), 5.2),
        (datetime(2024, 4, 1, 23, 0), 7.8),
    ),
    "water_temperature_hourly_min": (
        "41061:WT min",
        "2b27f39eeeacb3fb4fcc77986a1640b5739416ecfce965073f47f28ea42e5238",
        "f95ba465e082327b26e819605bd0ee1153419b4caec1ed88024261045e8d4875",
        (datetime(2024, 3, 30, 0, 0), 5.2),
        (datetime(2024, 4, 1, 23, 0), 7.7),
    ),
}


@dataclass(frozen=True)
class _EeEstStages:
    observation_source: str = "live"
    config: ProviderConfig = config()
    window_declarations: ProductWindowDeclarations = window_declarations()
    request_planner: EeEstRequestPlanner = EeEstRequestPlanner()
    fetch = staticmethod(fetch)
    parse = staticmethod(parse)


def _envelope_from_capture(root: Path, slug: str, *, subdir: str = "web") -> RecordingEnvelope:
    base = root / _SCOPE / subdir / slug
    body = base.with_suffix(".body").read_bytes()
    receipt = json.loads(base.with_suffix(".receipt.json").read_text())
    url = str(receipt["url"])
    parts = urlsplit(url)
    params = {key: vals[0] for key, vals in parse_qs(parts.query, keep_blank_values=True).items()}
    req_headers = dict(receipt.get("request_headers") or {})
    ordinary_headers = {**req_headers, "User-Agent": TRANSPORT_POLICY.user_agent}
    retrieved_raw = str(receipt.get("retrieved_at") or receipt.get("acquired_at")).replace("Z", "+00:00")
    media_type = receipt.get("media_type")
    return RecordingEnvelope(
        request=RecordedRequest(
            HttpMethod.GET,
            f"{parts.scheme}://{parts.netloc}{parts.path}",
            params,
            ordinary_headers=ordinary_headers,
        ),
        content=body,
        status_code=int(str(receipt["http_status"])),
        retrieved_at=datetime.fromisoformat(retrieved_raw),
        content_type=str(media_type) if isinstance(media_type, str) and media_type else None,
    )


def _replay(root: Path) -> ReplayTransport:
    return ReplayTransport(tuple(_envelope_from_capture(root, slug) for slug in _RECORDING_SLUGS))


@pytest.mark.recorded(_SCOPE)
def test_recorded_all_18_products_replay_at_ahja_with_annotations_and_dst_utc(
    retained_evidence_root: Path, tmp_path: Path
) -> None:
    replay = _replay(retained_evidence_root)
    packaged_stages = declaration.observations.stages

    for spec in PRODUCT_SPECS:
        if spec.source_api == "estmodel":
            y_start = 2026 if spec.product_id in {"discharge_daily_mean", "water_temperature_daily_mean"} else 2025
            start_dt, end_dt = datetime(y_start, 1, 1), datetime(2026, 11, 22, 23, 59, 59, 999999)
            expected_rows = 326 if y_start == 2026 else 691
        else:
            start_dt, end_dt = datetime(2024, 3, 30, 0, 0), datetime(2024, 4, 1, 23, 59, 59, 999999)
            expected_rows = 72

        expected_pub, expected_sid, expected_fid, first_pair, last_pair = _AHJA_EXPECTED[spec.product_id]
        req = ObservationRequest(
            provider_id=ProviderId("ee_est"),
            stations=("SJA8821000",),
            products=(ProductId(spec.product_id),),
            window=RequestedWindow(WindowEndpoint.from_datetime(start_dt), WindowEndpoint.from_datetime(end_dt)),
        )
        res = drive(
            req,
            packaged_stages,
            provenance=_provenance(req),
            receipts=ReceiptMode.INCLUDE,
            transport=replay,
            cache="bypass",
            store=StoreRoot(tmp_path / f"store-{spec.product_id}"),
        )
        assert res.canonical_rows.height == expected_rows
        assert res.canonical_rows["series_id"].unique().to_list() == [expected_sid]
        assert res.canonical_rows["facts_id"].unique().to_list() == [expected_fid]
        assert [s.identity.published_id for s in res.source_series] == [expected_pub]
        rows_sorted = res.canonical_rows.sort("time")
        assert rows_sorted["time"][0] == first_pair[0]
        assert rows_sorted["value"][0] == pytest.approx(first_pair[1])
        assert rows_sorted["time"][-1] == last_pair[0]
        assert rows_sorted["value"][-1] == pytest.approx(last_pair[1])
        assert [o.status for o in res.outcomes] == [OutcomeStatus.SUCCESS]
        assert len(res.receipts.entries) == 1
        if spec.source_api == "estmodel":
            ann = res.annotations.observation_tables[EE_EST_ESTMODEL_SCHEMA.schema_id].rows["qualityFlag"].to_list()
            if spec.quantity == "temperature":
                assert all(flag is None for flag in ann)
            elif y_start == 2026:
                assert ann == ["UNCHECKED"] * 326
            else:
                assert ann[:365] == [None] * 365
                assert ann[365:] == ["UNCHECKED"] * 326
            if spec.product_id == "stage_daily_mean":
                h_by_time = {
                    t: (v, qf)
                    for t, v, qf in zip(rows_sorted["time"].to_list(), rows_sorted["value"].to_list(), ann, strict=True)
                }
                assert h_by_time[datetime(2025, 12, 31)][0] == pytest.approx(1.04)
                assert h_by_time[datetime(2025, 12, 31)][1] is None
                assert h_by_time[datetime(2026, 1, 1)][0] == pytest.approx(1.01)
                assert h_by_time[datetime(2026, 1, 1)][1] == "UNCHECKED"
        else:
            assert res.canonical_rows["time_zone"].unique().to_list() == ["+00:00"]
            if spec.product_id == "stage_hourly_mean":
                vals_by_time = dict(zip(rows_sorted["time"].to_list(), rows_sorted["value"].to_list(), strict=True))
                assert vals_by_time[datetime(2024, 3, 31, 0, 0)] == pytest.approx(1.1414)
                assert vals_by_time[datetime(2024, 3, 31, 1, 0)] == pytest.approx(1.1383)
                assert vals_by_time[datetime(2024, 3, 31, 2, 0)] == pytest.approx(1.1353)

    # Autumn DST transition on UTC hourly timeline (41061:WL avg, 2024-10-26..2024-10-28)
    autumn_req = ObservationRequest(
        provider_id=ProviderId("ee_est"),
        stations=("SJA8821000",),
        products=(ProductId("stage_hourly_mean"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2024, 10, 26, 0, 0)),
            WindowEndpoint.from_datetime(datetime(2024, 10, 28, 23, 59, 59, 999999)),
        ),
    )
    autumn_res = drive(
        autumn_req,
        packaged_stages,
        provenance=_provenance(autumn_req),
        receipts=ReceiptMode.OMIT,
        transport=replay,
        cache="bypass",
        store=StoreRoot(tmp_path / "store-autumn-dst"),
    )
    assert autumn_res.canonical_rows.height == 72
    assert autumn_res.canonical_rows["series_id"].unique().to_list() == [
        "d8882a9d825e990daeddb93d1989506c4ef4fa48845c97f4bb719bbbc1ed5383"
    ]
    autumn_map = dict(
        zip(
            autumn_res.canonical_rows["time"].to_list(),
            autumn_res.canonical_rows["value"].to_list(),
            strict=True,
        )
    )
    assert autumn_map[datetime(2024, 10, 26, 0, 0)] == pytest.approx(0.488)
    assert autumn_map[datetime(2024, 10, 27, 0, 0)] == pytest.approx(0.516)
    assert autumn_map[datetime(2024, 10, 27, 1, 0)] == pytest.approx(0.516)
    assert autumn_map[datetime(2024, 10, 27, 2, 0)] == pytest.approx(0.515)
    assert autumn_map[datetime(2024, 10, 28, 23, 0)] == pytest.approx(0.491)


@pytest.mark.recorded(_SCOPE)
def test_recorded_deep_history_negative_stage_nulls_empty_404_and_dual_code_lookup(
    retained_evidence_root: Path, tmp_path: Path
) -> None:
    replay = _replay(retained_evidence_root)
    packaged_stages = declaration.observations.stages

    # 1. 1867 Tartu H (25-year chunk) & negative gauge-zero stages at Räpina
    tartu_req = ObservationRequest(
        provider_id=ProviderId("ee_est"),
        stations=("SJA7331000",),
        products=(ProductId("stage_daily_mean"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(1867, 1, 1)),
            WindowEndpoint.from_datetime(datetime(1891, 12, 31)),
        ),
    )
    tartu_res = drive(
        tartu_req,
        packaged_stages,
        provenance=_provenance(tartu_req),
        receipts=ReceiptMode.OMIT,
        transport=replay,
        cache="bypass",
        store=StoreRoot(tmp_path / "store-tartu"),
    )
    assert tartu_res.canonical_rows.height == 5432
    assert tartu_res.canonical_rows["series_id"].unique().to_list() == [
        "a9318e9dccbca0930d28b622ba159e2ac66d0084c746c379278225cb2d8f71cc"
    ]
    tartu_sorted = tartu_res.canonical_rows.sort("time")
    assert tartu_sorted["time"][0] == datetime(1867, 4, 1)
    assert tartu_sorted["value"][0] == pytest.approx(1.73)
    assert tartu_sorted["time"][-1] == datetime(1891, 11, 13)
    assert tartu_sorted["value"][-1] == pytest.approx(0.35)

    rapina_req = ObservationRequest(
        provider_id=ProviderId("ee_est"),
        stations=("SJA4456000",),
        products=(ProductId("stage_daily_mean"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2025, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2026, 11, 22)),
        ),
    )
    rapina_res = drive(
        rapina_req,
        packaged_stages,
        provenance=_provenance(rapina_req),
        receipts=ReceiptMode.OMIT,
        transport=replay,
        cache="bypass",
        store=StoreRoot(tmp_path / "store-rapina"),
    )
    assert rapina_res.canonical_rows.height == 691
    assert rapina_res.canonical_rows["series_id"].unique().to_list() == [
        "a6fb603be5e66b1067fce1b50e720ac2dc91e445a59ad5a536ac471f47431949"
    ]
    assert rapina_res.canonical_rows.filter(rapina_res.canonical_rows["value"] < 0).height == 101
    rapina_map = dict(
        zip(rapina_res.canonical_rows["time"].to_list(), rapina_res.canonical_rows["value"].to_list(), strict=True)
    )
    assert rapina_map[datetime(2025, 4, 18)] == pytest.approx(-0.04)
    assert rapina_map[datetime(2025, 10, 5)] == pytest.approx(-0.23)
    assert rapina_map[datetime(2026, 11, 22)] == pytest.approx(-0.05)

    # 2. Konuvere 41116 vaartus=null rows preserved
    null_req = ObservationRequest(
        provider_id=ProviderId("ee_est"),
        stations=("SJA9204000",),
        products=(ProductId("stage_hourly_mean"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2025, 11, 27, 0, 0)),
            WindowEndpoint.from_datetime(datetime(2025, 11, 27, 23, 59, 59, 999999)),
        ),
    )
    null_res = drive(
        null_req,
        packaged_stages,
        provenance=_provenance(null_req),
        receipts=ReceiptMode.OMIT,
        transport=replay,
        cache="bypass",
        store=StoreRoot(tmp_path / "store-null"),
    )
    assert null_res.canonical_rows.height == 9
    assert null_res.canonical_rows["series_id"].unique().to_list() == [
        "2bc275081c14cb367b39c6ac3d43b56051cb06f5e5267b904c421a274ce10992"
    ]
    assert null_res.canonical_rows.sort("time")["time"].to_list()[:2] == [
        datetime(2025, 11, 27, 0, 0),
        datetime(2025, 11, 27, 1, 0),
    ]
    assert null_res.canonical_rows["value"].null_count() == 9

    # 3. Dual-code SJA5524000 queries BOTH 41022 and 41960 cleanly (dynamic AND packaged station_codes)
    expected_41022_sid = "1091ce4c857da51bb29fc8c74c87b04065d61aafb129a7cadf3c5fb2aaa20249"
    for label, stages in (("dynamic", _EeEstStages()), ("packaged", packaged_stages)):
        dual_req = ObservationRequest(
            provider_id=ProviderId("ee_est"),
            stations=("SJA5524000",),
            products=(ProductId("stage_hourly_mean"),),
            window=RequestedWindow(
                WindowEndpoint.from_datetime(datetime(2026, 10, 1, 0, 0)),
                WindowEndpoint.from_datetime(datetime(2026, 10, 1, 23, 59, 59, 999999)),
            ),
        )
        dual_res = drive(
            dual_req,
            stages,
            provenance=_provenance(dual_req),
            receipts=ReceiptMode.OMIT,
            transport=replay,
            cache="bypass",
            store=StoreRoot(tmp_path / f"store-dual-{label}"),
        )
        assert dual_res.canonical_rows.height == 24
        assert dual_res.canonical_rows["series_id"].unique().to_list() == [expected_41022_sid]
        assert [s.identity.published_id for s in dual_res.source_series] == ["41022:WL avg"]
        dual_sorted = dual_res.canonical_rows.sort("time")
        assert dual_sorted["time"][0] == datetime(2026, 10, 1, 0, 0)
        assert dual_sorted["value"][0] == pytest.approx(0.3447)
        assert dual_sorted["time"][-1] == datetime(2026, 10, 1, 23, 0)
        assert dual_sorted["value"][-1] == pytest.approx(0.3637)
        assert all(
            inv.completeness is InventoryCompleteness.COMPLETE
            and inv.members == (expected_41022_sid,)
            and sum(1 for ev in inv.evidence if ev.startswith("source-call:")) == 2
            for inv in dual_res.inventories
        )

    # 4. Valid empty [] vs HTTP 404 isolation
    empty_req = ObservationRequest(
        provider_id=ProviderId("ee_est"),
        stations=("SJA8821000",),
        products=(ProductId("discharge_daily_mean"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2030, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2030, 12, 31)),
        ),
    )
    empty_res = drive(
        empty_req,
        packaged_stages,
        provenance=_provenance(empty_req),
        receipts=ReceiptMode.OMIT,
        transport=replay,
        cache="bypass",
        store=StoreRoot(tmp_path / "store-empty"),
    )
    assert empty_res.canonical_rows.is_empty()
    assert [o.status for o in empty_res.outcomes] == [OutcomeStatus.EMPTY]

    bad_req = ObservationRequest(
        provider_id=ProviderId("ee_est"),
        stations=("INVALID_STATION",),
        products=(ProductId("discharge_daily_mean"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2024, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2024, 12, 31)),
        ),
    )
    bad_res = drive(
        bad_req,
        packaged_stages,
        provenance=_provenance(bad_req),
        receipts=ReceiptMode.OMIT,
        transport=replay,
        cache="bypass",
        store=StoreRoot(tmp_path / "store-404"),
    )
    assert bad_res.canonical_rows.is_empty()
    assert [o.status for o in bad_res.outcomes] == [OutcomeStatus.FAILED]
    assert any(issue.code == "source.http_not_found" for issue in bad_res.issues)
