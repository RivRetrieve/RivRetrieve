"""Streaming certification refuses incomplete or inconsistent batches atomically."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.store import (
    NativeObservationBatch,
    ObservationBatchStream,
    SourceUnitContribution,
    SourceUnitCount,
    certify_store,
    certify_store_batches,
    source_unit_inventory_fingerprint,
    validate_store,
)
from rivretrieve._internal.store.validation import StoreManifest
from tests.store.certification_support import COLUMNS, artifact_and_request, complete, fixture_series, rows


def _published_store(tmp_path: Path):
    artifact, request = artifact_and_request(tmp_path)
    certify_store(request, artifact, lambda _path: complete(rows(value=1.0)))
    return request


@pytest.mark.parametrize("defect", ["incomplete", "duplicate", "schema"])
def test_invalid_late_stream_batch_cannot_replace_previous_store_or_delete_artifact(
    tmp_path: Path, defect: str
) -> None:
    prior = _published_store(tmp_path)
    artifact = tmp_path / "publisher-second.zip"
    artifact.write_bytes(b"second publisher artifact")
    import hashlib

    from rivretrieve._internal.store import ArtifactChecksum, PublisherArtifact

    request = replace(
        prior,
        publisher_artifact=PublisherArtifact(
            "https://example.test/publisher-second.zip",
            ArtifactChecksum("sha256:" + hashlib.sha256(artifact.read_bytes()).hexdigest()),
        ),
    )
    first = NativeObservationBatch(
        rows(value=2.0), (SourceUnitCount("unit-1", 1, 1),), (SourceUnitContribution("unit-1", 1),)
    )
    if defect == "incomplete":
        second = NativeObservationBatch(
            rows(value=3.0), (SourceUnitCount("unit-2", 1, 1),), (SourceUnitContribution("unit-2", 0),)
        )
    elif defect == "duplicate":
        second = NativeObservationBatch(
            rows(value=3.0), (SourceUnitCount("unit-1", 1, 1),), (SourceUnitContribution("unit-1", 1),)
        )
    else:
        second = NativeObservationBatch(
            rows(value=3.0).drop("raw_value"),
            (SourceUnitCount("unit-2", 1, 1),),
            (SourceUnitContribution("unit-2", 1),),
        )

    with pytest.raises((ValueError, TypeError)):
        certify_store_batches(
            request,
            artifact,
            lambda _path: ObservationBatchStream(
                COLUMNS, (first, second), 2, 2, source_unit_inventory_fingerprint((("unit-1", 1, 1), ("unit-2", 1, 1)))
            ),
        )

    assert artifact.exists()
    validated = validate_store(prior.destination, ProviderId("fixture_bulk"))
    assert isinstance(validated.manifest, StoreManifest)
    assert validated.manifest.publisher_artifact.url == "https://example.test/publisher.zip"
    assert not tuple(tmp_path.glob(".store.staging-*"))
    assert not tuple(tmp_path.glob(".store.previous-*"))


@pytest.mark.parametrize("mutation", ["stage-bytes", "stage-values", "after-replay"])
def test_streaming_readback_detects_exact_value_mutation_and_rolls_back(tmp_path: Path, monkeypatch, mutation) -> None:
    import polars as pl

    import rivretrieve._internal.store.certification as certification

    prior = _published_store(tmp_path)
    artifact = tmp_path / "publisher-second.zip"
    artifact.write_bytes(b"second publisher artifact")
    import hashlib

    from rivretrieve._internal.store import ArtifactChecksum, PublisherArtifact

    request = replace(
        prior,
        publisher_artifact=PublisherArtifact(
            "https://example.test/publisher-second.zip",
            ArtifactChecksum("sha256:" + hashlib.sha256(artifact.read_bytes()).hexdigest()),
        ),
    )

    def change_value(stage):
        path = Path(stage) / "product=discharge" / "year=1998" / "part-0.parquet"
        frame = pl.read_parquet(path).with_columns(pl.lit(999.0).alias("value"))
        frame.write_parquet(path)

    original = certification.compile_store_batches

    def mutating_writer(staged_request, stream):
        evidence = original(staged_request, stream)
        change_value(staged_request.destination)
        if mutation == "stage-values":
            from rivretrieve._internal.store.integrity import seal_store

            # Reach independent source equality, rather than byte-integrity refusal.
            seal_store(staged_request.destination, staged_request.provider_id)
        return evidence

    original_replay = certification._verify_streamed_read_back

    def mutating_replay(stage, *args):
        original_replay(stage, *args)
        change_value(stage)

    if mutation == "after-replay":
        monkeypatch.setattr(certification, "_verify_streamed_read_back", mutating_replay)
    else:
        monkeypatch.setattr(certification, "compile_store_batches", mutating_writer)
    batch = NativeObservationBatch(
        rows(value=2.0), (SourceUnitCount("unit-1", 1, 1),), (SourceUnitContribution("unit-1", 1),)
    )
    with pytest.raises(Exception, match="read-back differs" if mutation == "stage-values" else "file_identity|digest"):
        certify_store_batches(
            request,
            artifact,
            lambda _path: ObservationBatchStream(
                COLUMNS, (batch,), 1, 1, source_unit_inventory_fingerprint((("unit-1", 1, 1),))
            ),
        )

    assert artifact.exists()
    validated = validate_store(prior.destination, ProviderId("fixture_bulk"))
    assert isinstance(validated.manifest, StoreManifest)
    assert validated.manifest.publisher_artifact.url == "https://example.test/publisher.zip"


def test_validation_refuses_station_order_regression_across_arrow_batches(tmp_path: Path) -> None:
    import polars as pl

    from rivretrieve._internal.store import ObservationStoreRefusedError, compile_store

    _artifact, request = artifact_and_request(tmp_path)
    frame = pl.concat([rows(station="station-z")] * 65_537, rechunk=True)
    request = replace(request, series=(fixture_series("station-z"),))
    compile_store(request, frame)
    partition = Path(request.destination) / "product=discharge" / "year=1998" / "part-0.parquet"
    broken = pl.read_parquet(partition)
    broken = (
        broken.with_row_index("index")
        .with_columns(
            pl.when(pl.col("index") == 65_536)
            .then(pl.lit("station-a"))
            .otherwise(pl.col("station_id"))
            .alias("station_id")
        )
        .drop("index")
    )
    broken.write_parquet(partition, row_group_size=65_536)

    with pytest.raises(ObservationStoreRefusedError, match="partition.order"):
        validate_store(request.destination, ProviderId("fixture_bulk"))


@pytest.mark.parametrize("mutation", ["extra", "order", "type"])
def test_validation_enforces_exact_retained_physical_schema(tmp_path: Path, mutation: str) -> None:
    import polars as pl

    from rivretrieve._internal.store import ObservationStoreRefusedError, compile_store

    _artifact, request = artifact_and_request(tmp_path)
    compile_store(request, rows())
    partition = Path(request.destination) / "product=discharge" / "year=1998" / "part-0.parquet"
    frame = pl.read_parquet(partition)
    if mutation == "extra":
        frame = frame.with_columns(pl.lit("UNDECLARED").alias("injected"))
    elif mutation == "order":
        original = frame
        frame = frame.select(*frame.columns[:4], frame.columns[5], frame.columns[4], *frame.columns[6:])
        # Only order differs; no missing column can cause the refusal instead.
        import polars.testing as pl_testing

        pl_testing.assert_frame_equal(frame.select(original.columns), original)
        assert frame.columns != original.columns
    else:
        frame = frame.with_columns(pl.col("raw_value").cast(pl.Binary))
    frame.write_parquet(partition)

    with pytest.raises(ObservationStoreRefusedError, match="partition.schema"):
        validate_store(request.destination, ProviderId("fixture_bulk"))


def test_validation_rejects_store_bound_to_another_provider(tmp_path: Path) -> None:
    from rivretrieve._internal.store import ObservationStoreRefusedError, compile_store

    _artifact, request = artifact_and_request(tmp_path)
    compile_store(request, rows())
    with pytest.raises(ObservationStoreRefusedError, match="manifest.provider_id"):
        validate_store(request.destination, ProviderId("other_provider"))
