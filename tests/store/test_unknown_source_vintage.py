"""Unknown source_vintage contracts for unlabelled static bulk archives."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

import rivretrieve as rr
from rivretrieve._internal import discovery
from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.engine import (
    CacheConfig,
    Instant,
    ObservationStoreConfig,
    ProductConfig,
    ProviderConfig,
    SourceCoordinates,
    Unit,
    ZoneValue,
)
from rivretrieve._internal.observations import StoreExcerptReceipt
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.ca_eccc.declaration import declaration as ca_eccc_declaration
from rivretrieve._internal.providers.pl_imgw.bulk import ImgwCompileRequest
from rivretrieve._internal.providers.pl_imgw.declaration import declaration as pl_imgw_declaration
from rivretrieve._internal.providers.registration import BulkCompileRequest, BulkStore, DownloadedBulkArtifact
from rivretrieve._internal.registry import ProviderRegistry
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.store import (
    ArtifactChecksum,
    NativeObservationBatch,
    ObservationBatchStream,
    PublisherArtifact,
    SourceUnitContribution,
    SourceUnitCount,
    StoreReader,
    StoreRoot,
    certify_store,
    certify_store_batches,
    source_unit_inventory_fingerprint,
)
from rivretrieve._internal.store.integrity import audit_store
from rivretrieve._internal.store.validation import StoreManifest
from tests.store.certification_support import COLUMNS, artifact_and_request, complete, fixture_series, rows


def test_downloaded_bulk_artifact_and_compile_request_handle_none_and_reject_mixed_or_datetime(tmp_path: Path) -> None:
    artifact_a = tmp_path / "a.zip"
    artifact_b = tmp_path / "b.zip"
    artifact_a.write_bytes(b"a")
    artifact_b.write_bytes(b"b")

    undated_a = DownloadedBulkArtifact(artifact_a, "https://example.test/a.zip", None)
    undated_b = DownloadedBulkArtifact(artifact_b, "https://example.test/b.zip", None)
    assert undated_a.source_vintage is None

    with pytest.raises(TypeError):
        DownloadedBulkArtifact(artifact_a, "https://example.test/a.zip", datetime(2026, 1, 1, tzinfo=UTC))  # type: ignore[arg-type]

    undated_compile = BulkCompileRequest(
        publisher_artifacts=(undated_a, undated_b),
        destination=StoreRoot(tmp_path / "store_undated"),
        built_at=datetime(2026, 11, 19, 12, 0, tzinfo=UTC),
        compiler_version="0.1.5",
    )
    assert undated_compile.source_vintage is None

    dated_a = DownloadedBulkArtifact(artifact_a, "https://example.test/a.zip", date(2026, 1, 1))
    dated_b = DownloadedBulkArtifact(artifact_b, "https://example.test/b.zip", date(2026, 2, 1))
    dated_compile = BulkCompileRequest(
        publisher_artifacts=(dated_a, dated_b),
        destination=StoreRoot(tmp_path / "store_dated"),
        built_at=datetime(2026, 11, 19, 12, 0, tzinfo=UTC),
        compiler_version="0.1.5",
    )
    assert dated_compile.source_vintage == date(2026, 2, 1)

    with pytest.raises(ValueError, match="mix dated and undated"):
        BulkCompileRequest(
            publisher_artifacts=(dated_a, undated_b),
            destination=StoreRoot(tmp_path / "store_mixed"),
            built_at=datetime(2026, 11, 19, 12, 0, tzinfo=UTC),
            compiler_version="0.1.5",
        )


def test_store_compile_request_rejects_datetime_and_roundtrips_none_source_vintage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    artifact, base_request = artifact_and_request(tmp_path)
    built_at = datetime(2026, 11, 19, 12, 0, 0, tzinfo=UTC)

    bad_request = replace(base_request, source_vintage=datetime(2026, 1, 1, tzinfo=UTC))
    with pytest.raises(TypeError, match="datetime.date or None"):
        certify_store(bad_request, artifact, lambda _: complete(rows()))

    for streaming in (False, True):
        run_dir = tmp_path / ("streaming" if streaming else "batch")
        run_dir.mkdir()
        run_artifact, run_base = artifact_and_request(run_dir)
        second_artifact = run_dir / "second.zip"
        second_artifact.write_bytes(b"second publisher bytes")
        first_pub = run_base.publisher_artifact
        second_pub = PublisherArtifact(
            "https://example.test/second.zip",
            ArtifactChecksum(f"sha256:{hashlib.sha256(second_artifact.read_bytes()).hexdigest()}"),
        )
        request = replace(
            run_base,
            built_at=built_at,
            source_vintage=None,
            publisher_artifacts=(first_pub, second_pub) if streaming else (),
        )
        if not streaming:
            validated = certify_store(request, run_artifact, lambda _: complete(rows()))
        else:
            unit = SourceUnitCount("1998.csv", 1, 1)
            stream = ObservationBatchStream(
                COLUMNS,
                (NativeObservationBatch(rows(), (unit,), (SourceUnitContribution("1998.csv", 1),)),),
                1,
                1,
                source_unit_inventory_fingerprint((("1998.csv", 1, 1),)),
            )
            validated = certify_store_batches(request, (run_artifact, second_artifact), lambda _, s=stream: s)

        assert isinstance(validated.manifest, StoreManifest)
        assert validated.manifest.source_vintage is None
        assert validated.manifest.built_at == built_at
        raw_manifest = json.loads((Path(validated.root) / "manifest.json").read_text(encoding="utf-8"))
        assert raw_manifest["source_vintage"] is None
        assert raw_manifest["built_at"] == "2026-11-19T12:00:00.000000Z"
        assert audit_store(validated.root, ProviderId("fixture_bulk")).rows_checked == 1
        status = StoreReader().status(validated.root, ProviderId("fixture_bulk"))
        assert status.source_vintage is None
        assert status.built_at == built_at

    # Public fetch, StoreExcerptReceipt, and bundle round-trip preserve source_vintage=None.
    store = StoreRoot(tmp_path / "streaming" / "store")
    config = ProviderConfig(
        zone=ZoneValue("unknown"),
        products={ProductId("discharge"): ProductConfig(SourceCoordinates({}), Unit.M3_S, Instant())},
        cache=CacheConfig(ObservationStoreConfig(format_version=10)),
    )
    registry = ProviderRegistry()
    registry.register(
        "fixture_bulk",
        stub_packaged_catalogue_artifact("fixture_bulk"),
        bulk_config=config,
        observation_store=store,
    )
    monkeypatch.setattr(discovery, "_registry", registry)
    monkeypatch.setattr(discovery, "_provider_lookup", registry.get)
    monkeypatch.setattr(discovery, "_ensure_default_providers_registered", lambda: None)

    selection = rr._internal.selection._Selection(  # noqa: SLF001
        scope=rr._internal.source_series.SeriesScope(provider_ids=("fixture_bulk",)),  # noqa: SLF001
        known_series=(fixture_series(),),
    )
    fetched = rr.fetch(selection, start="1998-01-01", end="1998-01-05", receipts=True, on_issue="ignore")
    assert fetched.outcomes[0].status is OutcomeStatus.SUCCESS
    assert fetched.provenance.source_vintage is None
    assert fetched.provenance.publisher_artifact_urls == (
        "https://example.test/publisher.zip",
        "https://example.test/second.zip",
    )
    assert len(fetched.provenance.publisher_artifact_checksums) == 2
    assert len(fetched.receipts.entries) == 1
    receipt = fetched.receipts.entries[0]
    assert isinstance(receipt, StoreExcerptReceipt)
    assert receipt.source_vintage is None

    restored = rr.from_bundle(rr.to_bundle(fetched))
    assert restored.provenance.source_vintage is None
    assert restored.provenance.publisher_artifact_urls == fetched.provenance.publisher_artifact_urls
    assert restored.provenance.publisher_artifact_checksums == fetched.provenance.publisher_artifact_checksums
    restored_receipt = restored.receipts.entries[0]
    assert isinstance(restored_receipt, StoreExcerptReceipt)
    assert restored_receipt.source_vintage is None


def test_dated_providers_refuse_undated_source_vintage(tmp_path: Path) -> None:
    artifact = tmp_path / "codz_2022_01.zip"
    artifact.write_bytes(b"zip")
    undated = DownloadedBulkArtifact(
        artifact,
        "https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/dobowe/2022/codz_2022_01.zip",
        None,
    )
    request = BulkCompileRequest(
        publisher_artifacts=(undated,),
        destination=StoreRoot(tmp_path / "store"),
        built_at=datetime(2026, 11, 19, 12, 0, tzinfo=UTC),
        compiler_version="0.1.5",
    )

    assert isinstance(ca_eccc_declaration.observations, BulkStore)
    with pytest.raises(ValueError, match="source_vintage"):
        ca_eccc_declaration.observations.compile(request)

    assert isinstance(pl_imgw_declaration.observations, BulkStore)
    with pytest.raises(ValueError, match="source_vintage"):
        pl_imgw_declaration.observations.compile(request)

    with pytest.raises(ValueError, match="source vintage"):
        ImgwCompileRequest(
            publisher_artifact=artifact,
            destination=StoreRoot(tmp_path / "imgw_store"),
            publisher_url=undated.url,
            source_vintage=date(2022, 1, 31),
            built_at=datetime(2026, 11, 19, 12, 0, tzinfo=UTC),
            compiler_version="0.1.5",
            publisher_artifacts=(undated,),
        )
