"""A compact HYDAT-derived store and separate OGC capture prove Canada's products."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

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
from rivretrieve._internal.providers.ca_eccc.declaration import declaration
from rivretrieve._internal.providers.registration import DeclaredProvider
from rivretrieve._internal.recordings import ReplayTransport, UnmatchedRequestError, read_recording
from rivretrieve._internal.store import StoreQuery, StoreRoot, read_store
from rivretrieve._internal.transport import HttpMethod, TransportRequest

_DATA = Path(__file__).parent / "test_data"
_STORE = StoreRoot(_DATA / "boundary_stores" / "ca_eccc_02GA010_2020_01")
_PRODUCTS = tuple(ProductId(value) for value in ("discharge_daily_mean", "stage_daily_mean"))


def test_hydat_attestation_executes_exact_validated_store_queries_for_both_products() -> None:
    probes = tuple(
        StoreBoundaryProbe(
            ProviderId("ca_eccc"),
            product,
            StoreQuery(
                _STORE,
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


def test_ogc_recording_is_corroboration_not_hydat_replay_or_compiler_input() -> None:
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
        StoreQuery(_STORE, ProviderId("ca_eccc"), ("02GA010",), _PRODUCTS, datetime(2020, 1, 1), datetime(2020, 1, 3))
    )

    assert recording.request.url == "https://api.weather.gc.ca/collections/hydrometric-daily-mean/items"
    assert recording.content.startswith(b'{"type":"FeatureCollection"')
    assert "replayed through ReplayTransport" in attestation["corroboration_recording"]["role"]
    assert "never HYDAT compiler input" in attestation["corroboration_recording"]["role"]
    assert attestation["committed_store"]["compiler_input_committed"] is False
    assert store.manifest.publisher_artifact.url.startswith("https://example.invalid/")
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


def test_compact_mechanical_store_uses_canonical_public_path_without_claiming_hydat_provenance(monkeypatch) -> None:
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
        observation_store=_STORE,
    )
    monkeypatch.setattr(discovery, "_registry", registry)
    monkeypatch.setattr(discovery, "_provider_lookup", registry.get)
    monkeypatch.setattr(discovery, "_ensure_default_providers_registered", lambda: None)
    selection = rr.find(provider="ca_eccc", station="02GA010", product="discharge_daily_mean")
    result = rr.fetch(selection, start="2020-01-01", end="2020-01-03", on_issue="raise", receipts=True)

    assert result.data.columns == ["time", "time_zone", "station_id", "product_id", "value"]
    assert result.data["value"].to_list() == [31.0, 19.299999237060547, 15.300000190734863]
    (receipt,) = result.receipts.entries
    assert isinstance(receipt, StoreExcerptReceipt)
    assert receipt.authorship is ReceiptAuthorship.STORE_EXCERPT
    assert receipt.executed_query.stations == ("02GA010",)
    assert receipt.executed_query.products == (ProductId("discharge_daily_mean"),)
    excerpt = pl.read_parquet(BytesIO(receipt.content))
    assert excerpt["value"].to_list() == [31.0, 19.299999237060547, 15.300000190734863, 15.899999618530272, 23.0]
    assert excerpt["DLY_FLOWS.FLOW_SYMBOL1"].to_list() == [None] * 5
    assert result.provenance.publisher_artifact_urls == (
        "https://example.invalid/rivretrieve/ca_eccc_02GA010_exact-row-attestation.zip",
    )
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
