"""A compact HYDAT-derived store and separate OGC capture prove Canada's products."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlsplit

import polars as pl
import pytest

from rivretrieve._internal.boundary_probes import (
    FIRST_WALL_CLOCK_TIME,
    LAST_WALL_CLOCK_TIME,
    READING_COUNT,
    StoreBoundaryProbe,
    WallClockExpectation,
    run_manifest_boundary_probes,
)
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.ca_eccc.bulk import HydatCompileRequest, compile_hydat
from rivretrieve._internal.providers.ca_eccc.declaration import declaration
from rivretrieve._internal.providers.registration import DeclaredProvider
from rivretrieve._internal.recordings import ReplayTransport, UnmatchedRequestError, read_recording
from rivretrieve._internal.store import StoreQuery, StoreRoot, read_store
from rivretrieve._internal.store.validation import StoreManifest
from rivretrieve._internal.transport import HttpMethod, TransportRequest

_DATA = Path(__file__).parent / "test_data"
_STORE = StoreRoot(_DATA / "boundary_stores" / "ca_eccc_02GA010_2020_01")
_PRODUCTS = tuple(ProductId(value) for value in ("discharge_daily_mean", "stage_daily_mean"))
_DERIVED_INPUT = _DATA / "ca_eccc_02GA010_2020_01_derived_input.zip"
_DERIVED_SHA256 = "e495f496c829df145add21a5e9aae321abfff3096734933a6287ae3f559e6cb2"
_DERIVED_URL = (
    "https://raw.githubusercontent.com/RivRetrieve/RivRetrieve/main/"
    "tests/test_data/ca_eccc_02GA010_2020_01_derived_input.zip"
)


def _compiled_derived_store(tmp_path: Path) -> StoreRoot:
    copied = tmp_path / "derived-input.zip"
    shutil.copyfile(_DERIVED_INPUT, copied)
    root = StoreRoot(tmp_path / "compiled-store")
    compile_hydat(
        HydatCompileRequest(copied, root, _DERIVED_URL, date(2020, 1, 31), datetime(2026, 9, 2, tzinfo=UTC), "0.1.49")
    )
    return root


def test_committed_derived_input_replays_through_production_compiler(tmp_path: Path) -> None:
    assert hashlib.sha256(_DERIVED_INPUT.read_bytes()).hexdigest() == _DERIVED_SHA256
    copied_input = tmp_path / "derived-input.zip"
    shutil.copyfile(_DERIVED_INPUT, copied_input)
    compiled = compile_hydat(
        HydatCompileRequest(
            copied_input,
            StoreRoot(tmp_path / "store"),
            _DERIVED_URL,
            date(2020, 1, 31),
            datetime(2026, 9, 2, tzinfo=UTC),
            "0.1.49",
        )
    )
    assert isinstance(compiled.manifest, StoreManifest)
    assert sum(compiled.manifest.partition_row_counts.values()) == 62
    assert str(compiled.manifest.publisher_artifact.sha256) == f"sha256:{_DERIVED_SHA256}"
    assert compiled.manifest.publisher_artifact.url == _DERIVED_URL


def test_derived_compiler_preserves_attested_native_cells_for_both_products(tmp_path: Path) -> None:
    current_store = _compiled_derived_store(tmp_path)
    probes = tuple(
        StoreBoundaryProbe(
            ProviderId("ca_eccc"),
            product,
            StoreQuery(
                current_store,
                ProviderId("ca_eccc"),
                ("02GA010",),
                (product,),
                datetime(2020, 1, 1),
                datetime(2020, 1, 3),
            ),
            {
                READING_COUNT: 3,
                FIRST_WALL_CLOCK_TIME: WallClockExpectation("2020-01-01T00:00:00", "unknown"),
                LAST_WALL_CLOCK_TIME: WallClockExpectation("2020-01-03T00:00:00", "unknown"),
            },
        )
        for product in _PRODUCTS
    )
    assert len(run_manifest_boundary_probes((DeclaredProvider("ca_eccc", declaration),), probes)) == 2
    flow_partition = pl.read_parquet(Path(current_store) / "product=discharge_daily_mean/year=2020/part-0.parquet")
    level_partition = pl.read_parquet(Path(current_store) / "product=stage_daily_mean/year=2020/part-0.parquet")
    assert flow_partition["DLY_FLOWS.NO_DAYS"].unique().to_list() == [31]
    assert level_partition["DLY_LEVELS.NO_DAYS"].unique().to_list() == [31]


def test_ogc_recording_is_corroboration_not_hydat_replay_or_compiler_input(tmp_path: Path) -> None:
    recording = read_recording(_DATA / "ca_eccc_02GA010_daily_2020-01-01_2020-01-03.ogc.recording.json")
    response = ReplayTransport((recording,)).send(
        TransportRequest(
            recording.request.method,
            recording.request.url,
            params=recording.request.parameters,
            body=recording.request.body,
        )
    )
    attestation = json.loads((Path(_STORE) / "attestation.json").read_text())
    store = read_store(
        StoreQuery(
            _compiled_derived_store(tmp_path),
            ProviderId("ca_eccc"),
            ("02GA010",),
            _PRODUCTS,
            datetime(2020, 1, 1),
            datetime(2020, 1, 3),
        )
    )

    assert recording.request.url == "https://api.weather.gc.ca/collections/hydrometric-daily-mean/items"
    assert recording.content.startswith(b'{"type":"FeatureCollection"')
    assert "replayed through ReplayTransport" in attestation["corroboration_recording"]["role"]
    assert "never HYDAT compiler input" in attestation["corroboration_recording"]["role"]
    assert attestation["committed_store"]["compiler_input_committed"] is True
    assert isinstance(store.manifest, StoreManifest)
    assert store.manifest.publisher_artifact.url == _DERIVED_URL
    fixture_identity = urlsplit(store.manifest.publisher_artifact.url)
    assert fixture_identity.hostname == "raw.githubusercontent.com"
    assert fixture_identity.hostname not in {"collaboration.cmc.ec.gc.ca", "api.weather.gc.ca"}
    assert attestation["full_publisher_artifact"]["sha256"] != str(
        store.manifest.publisher_artifact.sha256
    ).removeprefix("sha256:")
    payload = json.loads(response.content)
    properties = [feature["properties"] for feature in payload["features"]]
    by_product = {
        product: store.rows.filter(store.rows["product_id"] == product).sort("time")["value"].to_list()
        for product in _PRODUCTS
    }
    assert [item["DISCHARGE"] for item in properties] == by_product[ProductId("discharge_daily_mean")]
    assert [item["LEVEL"] for item in properties] == by_product[ProductId("stage_daily_mean")]


def test_compact_mechanical_store_uses_canonical_public_path_without_claiming_hydat_provenance(
    monkeypatch, tmp_path: Path
) -> None:
    from io import BytesIO

    import polars as pl

    import rivretrieve as rr
    import rivretrieve._internal.discovery as discovery
    from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
    from rivretrieve._internal.observations import ReceiptAuthorship, StoreExcerptReceipt
    from rivretrieve._internal.providers.ca_eccc.config import config
    from rivretrieve._internal.registry import ProviderRegistry

    registry = ProviderRegistry()
    registry.register(
        "ca_eccc",
        load_packaged_catalogue_artifact(declaration.catalogue, on_issue="raise"),
        bulk_config=config,
        observation_store=_compiled_derived_store(tmp_path),
    )
    monkeypatch.setattr(discovery, "_registry", registry)
    monkeypatch.setattr(discovery, "_provider_lookup", registry.get)
    monkeypatch.setattr(discovery, "_ensure_default_providers_registered", lambda: None)
    selection = rr.find(
        provider="ca_eccc", station="02GA010", quantity="discharge", frequency="daily", statistic="mean"
    )
    selection = rr.pick(selection, temporal_support="interval")
    result = rr.fetch(selection, start="2020-01-01", end="2020-01-03", on_issue="raise", receipts=True)
    assert result.data["facts_id"].unique().to_list() == [selection.series[0].facts[0].facts_id]

    assert result.data.columns == [
        "time",
        "time_zone",
        "station_id",
        "product_id",
        "series_id",
        "facts_id",
        "quantity",
        "source_unit",
        "unit",
        "value",
    ]
    assert result.data["value"].to_list() == [31.0, 19.299999237060547, 15.300000190734863]
    (receipt,) = result.receipts.entries
    assert isinstance(receipt, StoreExcerptReceipt)
    assert receipt.authorship is ReceiptAuthorship.STORE_EXCERPT
    assert receipt.executed_query.stations == ("02GA010",)
    assert receipt.executed_query.products == (ProductId("discharge_daily_mean"),)
    excerpt = pl.read_parquet(BytesIO(receipt.content))
    assert excerpt["facts_id"].unique().to_list() == [selection.series[0].facts[0].facts_id]
    assert excerpt["value"].to_list() == [31.0, 19.299999237060547, 15.300000190734863, 15.899999618530272, 23.0]
    assert excerpt["DLY_FLOWS.FLOW_SYMBOL1"].to_list() == [None] * 5
    assert excerpt["DLY_FLOWS.NO_DAYS"].to_list() == [31] * 5
    assert result.provenance.publisher_artifact_urls == (_DERIVED_URL,)
    omitted = rr.fetch(selection, start="2020-01-01", end="2020-01-03", on_issue="raise")
    assert omitted.receipts.entries == ()


@pytest.mark.parametrize(
    "mutation",
    (
        lambda request: replace(request, method=HttpMethod.POST),
        lambda request: replace(request, params={**(request.params or {}), "limit": 4}),
        lambda request: replace(request, body=b"unexpected"),
    ),
)
def test_canada_ogc_replay_refuses_any_request_mutation(mutation) -> None:
    recording = read_recording(_DATA / "ca_eccc_02GA010_daily_2020-01-01_2020-01-03.ogc.recording.json")
    request = TransportRequest(
        recording.request.method,
        recording.request.url,
        params=recording.request.parameters,
        body=recording.request.body,
    )
    with pytest.raises(UnmatchedRequestError):
        ReplayTransport((recording,)).send(mutation(request))
