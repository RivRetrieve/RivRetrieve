"""Recorded-evidence driver/parse replay tests for Belgium - Wallonia (`be_wal`)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import polars as pl
import pytest

from rivretrieve._internal.catalogues.source_series import catalogue_series
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
from rivretrieve._internal.providers.be_wal.annotations import BE_WAL_QUALITY_SCHEMA
from rivretrieve._internal.providers.be_wal.config import config, window_declarations
from rivretrieve._internal.providers.be_wal.fetch import fetch
from rivretrieve._internal.providers.be_wal.parse import parse
from rivretrieve._internal.providers.be_wal.series import PRODUCT_SPECS, source_series
from rivretrieve._internal.recordings import RecordedRequest, RecordingEnvelope, ReplayTransport
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.store import StoreRoot
from rivretrieve._internal.transport import TRANSPORT_POLICY, HttpMethod
from tests._catalogue import catalogue_reader
from tests.test_internal_driver import _provenance

_SCOPE = "maintenance/observations/be_wal/retrieval"

_FAMILY_STATION = {
    "discharge": "1046",
    "discharge_ultrasonic": "2708",
    "stage": "1046",
    "stage_absolute": "7102",
    "water_temperature": "7102",
}

_EDGE_SLUGS: tuple[str, ...] = (
    "edge-L8220-water-temp-ascii",
    "edge-3643-q1h-dst-spring-2024",
    "edge-3643-h1h-dst-autumn-2024",
    "edge-L8910-stage-neg-2024",
    "edge-3561-q20-null-minus1-2011",
    "edge-6228-q20-flood-200-2021",
    "edge-9434-q20-1929",
    "edge-5922-hsonde-daily-2024",
    "edge-1046-q20-2030-empty",
    "edge-uncat-9434-q20-tslist",
    "edge-uncat-9434-q20-val",
    "edge-uncat-3270-no-debit-tslist",
    "edge-uncat-invalid-station-tslist",
    "edge-2708-qu05-chunk1-365d",
    "edge-2708-qu05-chunk2-tail",
    "edge-9434-q1h-chunk1-3650d",
    "edge-9434-q1h-chunk2-tail",
    "edge-err-tsid-999999999-500",
    "edge-err-05-10yr-datasource-500",
)

_RECORDING_SLUGS: tuple[str, ...] = (
    *(f"prod-{_FAMILY_STATION[spec.family]}-{spec.product_id.replace('_', '-')}" for spec in PRODUCT_SPECS),
    *_EDGE_SLUGS,
)


@dataclass(frozen=True)
class _BeWalStages:
    config: ProviderConfig = config()
    window_declarations: ProductWindowDeclarations = window_declarations()
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
def test_recorded_all_62_products_replay_with_exact_catalogue_identities_and_cet_timezone(
    retained_evidence_root: Path, tmp_path: Path
) -> None:
    replay = _replay(retained_evidence_root)
    artifact = catalogue_reader("be_wal").artifact
    pkg_series, _ = catalogue_series(artifact)
    by_pair = {(s.station_id, s.product_id): s for s in pkg_series}

    for spec in PRODUCT_SPECS:
        station = _FAMILY_STATION[spec.family]
        if spec.frequency == "P1Y":
            s_dt, e_dt = datetime(2024, 1, 1), datetime(2024, 1, 2)
        elif spec.frequency == "P1M":
            s_dt, e_dt = datetime(2024, 7, 1), datetime(2024, 7, 2)
        elif spec.frequency == "P1D":
            s_dt, e_dt = datetime(2024, 7, 1), datetime(2024, 7, 2, 23, 59, 59)
        else:
            s_dt, e_dt = datetime(2024, 7, 1), datetime(2024, 7, 1, 23, 59, 59)

        known = by_pair[(station, spec.product_id)]
        req = ObservationRequest(
            provider_id=ProviderId("be_wal"),
            stations=(station,),
            products=(ProductId(spec.product_id),),
            window=RequestedWindow(WindowEndpoint.from_datetime(s_dt), WindowEndpoint.from_datetime(e_dt)),
            known_series=(known,),
        )
        res = drive(
            req,
            _BeWalStages(),
            provenance=_provenance(req),
            receipts=ReceiptMode.INCLUDE,
            transport=replay,
            cache="bypass",
            store=StoreRoot(tmp_path / f"store-{spec.product_id}"),
        )
        assert res.issues == ()
        assert res.canonical_rows.height >= 1
        assert res.canonical_rows["time_zone"].unique().to_list() == ["+01:00"]
        assert res.canonical_rows["series_id"].unique().to_list() == [known.series_id]
        assert res.canonical_rows["facts_id"].unique().to_list() == [known.facts[0].facts_id]
        assert [o.status for o in res.outcomes] == [OutcomeStatus.SUCCESS]
        assert len(res.receipts.entries) == 1


@pytest.mark.recorded(_SCOPE)
def test_recorded_dst_nulls_flood_200_1929_multichunk_and_uncatalogued_fallback(
    retained_evidence_root: Path, tmp_path: Path
) -> None:
    replay = _replay(retained_evidence_root)
    artifact = catalogue_reader("be_wal").artifact
    pkg_series, _ = catalogue_series(artifact)
    by_pair = {(s.station_id, s.product_id): s for s in pkg_series}

    def _run(
        station: str,
        product_id: str,
        start_dt: datetime,
        end_dt: datetime,
        *,
        use_known: bool = True,
        ts_id_override: str | None = None,
        tag: str,
    ):
        known = (
            (
                source_series(station, product_id, ts_id=ts_id_override, origin="catalogue")
                if ts_id_override is not None
                else by_pair[(station, product_id)],
            )
            if use_known
            else ()
        )
        req = ObservationRequest(
            provider_id=ProviderId("be_wal"),
            stations=(station,),
            products=(ProductId(product_id),),
            window=RequestedWindow(WindowEndpoint.from_datetime(start_dt), WindowEndpoint.from_datetime(end_dt)),
            known_series=known,
        )
        return drive(
            req,
            _BeWalStages(),
            provenance=_provenance(req),
            receipts=ReceiptMode.OMIT,
            transport=replay,
            cache="bypass",
            store=StoreRoot(tmp_path / f"store-{tag}"),
        )

    dst_spring = _run(
        "3643", "discharge_hourly_mean", datetime(2024, 3, 30), datetime(2024, 4, 1, 23), tag="dst-spring"
    )
    assert dst_spring.canonical_rows.height == 72

    dst_autumn = _run("3643", "stage_hourly_mean", datetime(2024, 10, 26), datetime(2024, 10, 28, 23), tag="dst-autumn")
    assert dst_autumn.canonical_rows.height == 72

    null_res = _run("3561", "discharge_daily_mean", datetime(2011, 8, 1), datetime(2011, 8, 10), tag="nulls")
    assert null_res.canonical_rows.height == 10
    assert null_res.canonical_rows["value"].null_count() == 5
    q_table = null_res.annotations.observation_tables[BE_WAL_QUALITY_SCHEMA.schema_id]
    assert q_table.rows["measured"].to_list() == [True] * 10
    assert q_table.rows.filter(pl.col("quality_code") == -1).height == 5

    flood_res = _run("6228", "discharge_daily_mean", datetime(2021, 7, 12), datetime(2021, 7, 18), tag="flood")
    assert flood_res.canonical_rows["value"].max() == pytest.approx(402.9)

    neg_res = _run("L8910", "stage_daily_mean", datetime(2024, 8, 18), datetime(2024, 8, 25), tag="neg")
    assert neg_res.canonical_rows.filter(pl.col("value") < 0).height == 1

    hist_res = _run("9434", "discharge_daily_mean", datetime(1929, 1, 1), datetime(1929, 1, 10), tag="1929")
    assert hist_res.canonical_rows.height == 10
    assert hist_res.canonical_rows["time"][0] == datetime(1929, 1, 1)

    empty_res = _run("1046", "discharge_daily_mean", datetime(2030, 1, 1), datetime(2030, 1, 2), tag="empty")
    assert empty_res.canonical_rows.is_empty()
    assert [o.status for o in empty_res.outcomes] == [OutcomeStatus.EMPTY]

    uncat_ok = _run(
        "9434", "discharge_daily_mean", datetime(2024, 7, 1), datetime(2024, 7, 3), use_known=False, tag="u-ok"
    )
    assert uncat_ok.canonical_rows["series_id"].unique().to_list() == [
        by_pair[("9434", "discharge_daily_mean")].series_id
    ]

    uncat_nm = _run(
        "3270", "discharge_daily_mean", datetime(2024, 7, 1), datetime(2024, 7, 3), use_known=False, tag="u-nm"
    )
    assert [o.status for o in uncat_nm.outcomes] == [OutcomeStatus.NO_MATCH]

    res_365 = _run(
        "2708", "discharge_ultrasonic_complete", datetime(2024, 1, 1), datetime(2024, 12, 31, 23, 59, 59), tag="365d"
    )
    assert res_365.canonical_rows.height == 8486

    res_3650 = _run("9434", "discharge_hourly_mean", datetime(2016, 1, 1), datetime(2026, 1, 5, 23), tag="3650d")
    assert res_3650.canonical_rows.height == 87792

    res_500 = _run(
        "9434",
        "discharge_daily_mean",
        datetime(2024, 7, 1),
        datetime(2024, 7, 2),
        ts_id_override="999999999",
        tag="err500",
    )
    assert res_500.canonical_rows.is_empty()
    assert [o.status for o in res_500.outcomes] == [OutcomeStatus.FAILED]
