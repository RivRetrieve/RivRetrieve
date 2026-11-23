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
from rivretrieve._internal.providers.ee_est.fetch import fetch
from rivretrieve._internal.providers.ee_est.parse import parse
from rivretrieve._internal.providers.ee_est.series import PRODUCT_SPECS, source_series
from rivretrieve._internal.recordings import RecordedRequest, RecordingEnvelope, ReplayTransport
from rivretrieve._internal.source_series import OutcomeStatus
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
    "fh-41061-wl-avg-2000-empty",
    "sj-sja5524000-lookup",
    "fh-41022-probe-limit1",
    "fh-41960-probe-limit1",
)


@dataclass(frozen=True)
class _EeEstStages:
    config: ProviderConfig = config()
    window_declarations: ProductWindowDeclarations = window_declarations()
    fetch = staticmethod(fetch)
    parse = staticmethod(parse)


def _envelope_from_capture(root: Path, slug: str) -> RecordingEnvelope:
    base = root / _SCOPE / "web" / slug
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

    for spec in PRODUCT_SPECS:
        if spec.source_api == "estmodel":
            y_start = 2026 if spec.product_id in {"discharge_daily_mean", "water_temperature_daily_mean"} else 2025
            start_dt, end_dt = datetime(y_start, 1, 1), datetime(2026, 11, 22, 23, 59, 59, 999999)
            expected_rows = 326 if y_start == 2026 else 691
            known = source_series("SJA8821000", spec.product_id)
        else:
            start_dt, end_dt = datetime(2024, 3, 30, 0, 0), datetime(2024, 4, 1, 23, 59, 59, 999999)
            expected_rows = 72
            known = source_series("SJA8821000", spec.product_id, jaam_kood=41061)

        req = ObservationRequest(
            provider_id=ProviderId("ee_est"),
            stations=("SJA8821000",),
            products=(ProductId(spec.product_id),),
            window=RequestedWindow(WindowEndpoint.from_datetime(start_dt), WindowEndpoint.from_datetime(end_dt)),
            known_series=(known,),
        )
        res = drive(
            req,
            _EeEstStages(),
            provenance=_provenance(req),
            receipts=ReceiptMode.INCLUDE,
            transport=replay,
            cache="bypass",
            store=StoreRoot(tmp_path / f"store-{spec.product_id}"),
        )
        assert res.canonical_rows.height == expected_rows
        assert res.canonical_rows["series_id"].unique().to_list() == [known.series_id]
        assert res.canonical_rows["facts_id"].unique().to_list() == [known.facts[0].facts_id]
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
        else:
            assert res.canonical_rows["time_zone"].unique().to_list() == ["+00:00"]


@pytest.mark.recorded(_SCOPE)
def test_recorded_deep_history_negative_stage_nulls_empty_404_and_dual_code_lookup(
    retained_evidence_root: Path, tmp_path: Path
) -> None:
    replay = _replay(retained_evidence_root)

    # 1. 1867 Tartu H (25-year chunk) & negative gauge-zero stages at Räpina
    tartu_req = ObservationRequest(
        provider_id=ProviderId("ee_est"),
        stations=("SJA7331000",),
        products=(ProductId("stage_daily_mean"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(1867, 1, 1)),
            WindowEndpoint.from_datetime(datetime(1891, 12, 31)),
        ),
        known_series=(source_series("SJA7331000", "stage_daily_mean"),),
    )
    tartu_res = drive(
        tartu_req,
        _EeEstStages(),
        provenance=_provenance(tartu_req),
        receipts=ReceiptMode.OMIT,
        transport=replay,
        cache="bypass",
        store=StoreRoot(tmp_path / "store-tartu"),
    )
    assert tartu_res.canonical_rows.height == 5432
    assert tartu_res.canonical_rows["time"][0] == datetime(1867, 4, 1)

    rapina_req = ObservationRequest(
        provider_id=ProviderId("ee_est"),
        stations=("SJA4456000",),
        products=(ProductId("stage_daily_mean"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2025, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2026, 11, 22)),
        ),
        known_series=(source_series("SJA4456000", "stage_daily_mean"),),
    )
    rapina_res = drive(
        rapina_req,
        _EeEstStages(),
        provenance=_provenance(rapina_req),
        receipts=ReceiptMode.OMIT,
        transport=replay,
        cache="bypass",
        store=StoreRoot(tmp_path / "store-rapina"),
    )
    assert rapina_res.canonical_rows.height == 691
    assert rapina_res.canonical_rows.filter(rapina_res.canonical_rows["value"] < 0).height == 101

    # 2. Konuvere 41116 vaartus=null rows preserved
    null_req = ObservationRequest(
        provider_id=ProviderId("ee_est"),
        stations=("SJA9204000",),
        products=(ProductId("stage_hourly_mean"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2025, 11, 27, 0, 0)),
            WindowEndpoint.from_datetime(datetime(2025, 11, 27, 23, 59, 59, 999999)),
        ),
        known_series=(source_series("SJA9204000", "stage_hourly_mean", jaam_kood=41116),),
    )
    null_res = drive(
        null_req,
        _EeEstStages(),
        provenance=_provenance(null_req),
        receipts=ReceiptMode.OMIT,
        transport=replay,
        cache="bypass",
        store=StoreRoot(tmp_path / "store-null"),
    )
    assert null_res.canonical_rows.height == 9
    assert null_res.canonical_rows["value"].null_count() == 9

    # 3. Dual-code SJA5524000 resolved live via f_seirejaamad -> 41022 without known_series
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
        _EeEstStages(),
        provenance=_provenance(dual_req),
        receipts=ReceiptMode.OMIT,
        transport=replay,
        cache="bypass",
        store=StoreRoot(tmp_path / "store-dual"),
    )
    assert dual_res.canonical_rows.height == 24
    assert dual_res.canonical_rows["series_id"].unique().to_list() == [
        source_series("SJA5524000", "stage_hourly_mean", jaam_kood=41022).series_id
    ]

    # 4. Valid empty [] vs HTTP 404 isolation
    empty_req = ObservationRequest(
        provider_id=ProviderId("ee_est"),
        stations=("SJA8821000",),
        products=(ProductId("discharge_daily_mean"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2030, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2030, 12, 31)),
        ),
        known_series=(source_series("SJA8821000", "discharge_daily_mean"),),
    )
    empty_res = drive(
        empty_req,
        _EeEstStages(),
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
        _EeEstStages(),
        provenance=_provenance(bad_req),
        receipts=ReceiptMode.OMIT,
        transport=replay,
        cache="bypass",
        store=StoreRoot(tmp_path / "store-404"),
    )
    assert bad_res.canonical_rows.is_empty()
    assert [o.status for o in bad_res.outcomes] == [OutcomeStatus.FAILED]
    assert any(issue.code == "source.http_not_found" for issue in bad_res.issues)
