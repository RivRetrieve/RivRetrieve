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


def test_streaming_readback_detects_exact_value_mutation_and_rolls_back(tmp_path: Path, monkeypatch) -> None:
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
    original = certification.compile_store_batches

    def mutating_writer(staged_request, stream):
        evidence = original(staged_request, stream)
        path = Path(staged_request.destination) / "product=discharge" / "year=1998" / "part-0.parquet"
        frame = pl.read_parquet(path).with_columns(pl.lit(999.0).alias("value"))
        frame.write_parquet(path)
        return evidence

    monkeypatch.setattr(certification, "compile_store_batches", mutating_writer)
    batch = NativeObservationBatch(
        rows(value=2.0), (SourceUnitCount("unit-1", 1, 1),), (SourceUnitContribution("unit-1", 1),)
    )
    with pytest.raises(Exception, match="read-back differs"):
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
        frame = frame.select(*frame.columns[:4], frame.columns[5], frame.columns[4])
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


def test_backup_cleanup_failure_is_loud_after_commit(tmp_path: Path, monkeypatch) -> None:
    import rivretrieve._internal.store.certification as certification

    prior = _published_store(tmp_path)
    artifact, request = artifact_and_request(tmp_path)
    real_remove = certification._remove_tree

    def refuse_backup(path: Path) -> None:
        if path.name.startswith(".store.previous-"):
            raise OSError("backup cleanup refused")
        real_remove(path)

    monkeypatch.setattr(certification, "_remove_tree", refuse_backup)
    with pytest.raises(certification.StorePostCommitCleanupError, match="new store is authoritative"):
        certify_store(request, artifact, lambda _path: complete(rows(value=2.0)))

    assert not artifact.exists()
    assert Path(prior.destination).is_dir()
    assert len(tuple(tmp_path.glob(".store.previous-*"))) == 1


def test_precommit_artifact_restore_error_does_not_suppress_previous_store_restore(tmp_path: Path, monkeypatch) -> None:
    from datetime import datetime

    import rivretrieve._internal.store.certification as certification
    from rivretrieve._internal.primitives import ProductId
    from rivretrieve._internal.store import StoreQuery, read_store

    prior = _published_store(tmp_path)
    artifact, request = artifact_and_request(tmp_path)
    real_validate = certification.validate_store
    calls = 0

    def fail_destination_validation(root, provider_id):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("destination validation refused")
        return real_validate(root, provider_id)

    monkeypatch.setattr(certification, "validate_store", fail_destination_validation)
    monkeypatch.setattr(
        certification,
        "_restore_linked_artifacts",
        lambda _artifacts, _copies: (_ for _ in ()).throw(OSError("artifact restore refused")),
    )

    def decode(_path):
        return ObservationBatchStream(
            COLUMNS,
            (
                NativeObservationBatch(
                    rows(value=2.0),
                    (SourceUnitCount("new.csv", 1, 1),),
                    (SourceUnitContribution("new.csv", 1),),
                ),
            ),
            1,
            1,
            source_unit_inventory_fingerprint((("new.csv", 1, 1),)),
        )

    with pytest.raises(certification.StoreCertificationError, match="pre-commit rollback was incomplete"):
        certify_store_batches(request, artifact, decode)

    restored = read_store(
        StoreQuery(
            prior.destination,
            ProviderId("fixture_bulk"),
            ("station-1",),
            (ProductId("discharge"),),
            datetime(1998, 1, 1),
            datetime(1998, 12, 31),
        )
    )
    assert restored.rows["value"].to_list() == [1.0]


@pytest.mark.parametrize("certifier", ["non_streaming", "streaming"])
def test_failed_publication_retries_prior_store_restore_in_outer_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, certifier: str
) -> None:
    """A failed immediate restore is retried by the shared outer rollback."""
    import hashlib
    import os

    import rivretrieve._internal.store.certification as certification
    from rivretrieve._internal.store import ArtifactChecksum, PublisherArtifact

    prior = _published_store(tmp_path)
    destination = Path(prior.destination)
    artifact = tmp_path / "publisher-second.zip"
    artifact.write_bytes(b"second publisher artifact")
    request = replace(
        prior,
        publisher_artifact=PublisherArtifact(
            "https://example.test/publisher-second.zip",
            ArtifactChecksum("sha256:" + hashlib.sha256(artifact.read_bytes()).hexdigest()),
        ),
    )
    real_replace = os.replace
    restore_attempts = 0

    def fail_publish_and_first_restore(source: Path | str, target: Path | str) -> None:
        nonlocal restore_attempts
        source_path = Path(source)
        target_path = Path(target)
        if source_path.name.startswith(".store.staging-") and target_path == destination:
            raise OSError("stage publication refused")
        if source_path.name.startswith(".store.previous-") and target_path == destination:
            restore_attempts += 1
            if restore_attempts == 1:
                raise OSError("immediate prior-store restore refused")
        real_replace(source_path, target_path)

    monkeypatch.setattr(certification.os, "replace", fail_publish_and_first_restore)
    batch = NativeObservationBatch(
        rows(value=2.0),
        (SourceUnitCount("new.csv", 1, 1),),
        (SourceUnitContribution("new.csv", 1),),
    )

    with pytest.raises(certification.StoreCertificationError, match="immediate prior-store restore refused"):
        if certifier == "non_streaming":
            certify_store(request, artifact, lambda _path: complete(rows(value=2.0)))
        else:
            certify_store_batches(
                request,
                artifact,
                lambda _path: ObservationBatchStream(
                    COLUMNS, (batch,), 1, 1, source_unit_inventory_fingerprint((("new.csv", 1, 1),))
                ),
            )

    assert restore_attempts == 2
    assert artifact.exists()
    compiled_manifest = validate_store(prior.destination, ProviderId("fixture_bulk")).manifest
    assert isinstance(compiled_manifest, StoreManifest)
    assert compiled_manifest.publisher_artifact.url == ("https://example.test/publisher.zip")
    assert not tuple(tmp_path.glob(".store.staging-*"))
    assert not tuple(tmp_path.glob(".store.previous-*"))
    assert not tuple(tmp_path.glob(".publisher-artifacts.rollback-*"))


def test_non_streaming_staging_cleanup_failure_is_aggregated_without_touching_artifact_or_prior_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import rivretrieve._internal.store.certification as certification
    from rivretrieve._internal.store import compile_store

    prior = _published_store(tmp_path)
    artifact, request = artifact_and_request(tmp_path)
    real_remove = certification._remove_tree

    def write_then_fail(staged_request, materialized_rows):
        compile_store(staged_request, materialized_rows)
        raise RuntimeError("writer refused after staging")

    def fail_stage_cleanup(path: Path) -> None:
        if path.name.startswith(".store.staging-"):
            raise OSError("staging cleanup refused")
        real_remove(path)

    monkeypatch.setattr(certification, "_remove_tree", fail_stage_cleanup)
    with pytest.raises(certification.StoreCertificationError, match="cleanup OSError: staging cleanup refused"):
        certify_store(request, artifact, lambda _path: complete(rows(value=2.0)), writer=write_then_fail)

    assert artifact.exists()
    compiled_manifest = validate_store(prior.destination, ProviderId("fixture_bulk")).manifest
    assert isinstance(compiled_manifest, StoreManifest)
    assert compiled_manifest.publisher_artifact.url == ("https://example.test/publisher.zip")
    assert len(tuple(tmp_path.glob(".store.staging-*"))) == 1
    assert not tuple(tmp_path.glob(".store.previous-*"))


def test_non_streaming_prior_store_restore_failure_is_aggregated_and_backup_is_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import rivretrieve._internal.store.certification as certification

    _published_store(tmp_path)
    artifact, request = artifact_and_request(tmp_path)
    real_validate = certification.validate_store
    validation_calls = 0

    def fail_destination_validation(root, provider_id):
        nonlocal validation_calls
        validation_calls += 1
        if validation_calls == 2:
            raise RuntimeError("destination validation refused")
        return real_validate(root, provider_id)

    monkeypatch.setattr(certification, "validate_store", fail_destination_validation)
    monkeypatch.setattr(
        certification,
        "_restore_previous",
        lambda _destination, _backup: (_ for _ in ()).throw(OSError("prior-store restoration refused")),
    )

    with pytest.raises(
        certification.StoreCertificationError, match="restoration OSError: prior-store restoration refused"
    ):
        certify_store(request, artifact, lambda _path: complete(rows(value=2.0)))

    assert artifact.exists()
    assert len(tuple(tmp_path.glob(".store.previous-*"))) == 1
    assert not tuple(tmp_path.glob(".store.staging-*"))


def test_first_backup_rename_failure_leaves_untouched_destination_and_never_attempts_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    import rivretrieve._internal.store.certification as certification

    prior = _published_store(tmp_path)
    destination = Path(prior.destination)
    artifact, request = artifact_and_request(tmp_path)
    real_replace = os.replace
    restore_attempts = 0

    def fail_first_rename(source: Path | str, target: Path | str) -> None:
        nonlocal restore_attempts
        source_path = Path(source)
        target_path = Path(target)
        if source_path == destination and target_path.name.startswith(".store.previous-"):
            raise OSError("backup rename refused")
        if source_path.name.startswith(".store.previous-"):
            restore_attempts += 1
        real_replace(source_path, target_path)

    monkeypatch.setattr(certification.os, "replace", fail_first_rename)
    with pytest.raises(OSError, match="backup rename refused"):
        certify_store(request, artifact, lambda _path: complete(rows(value=2.0)))

    assert restore_attempts == 0
    assert artifact.exists()
    compiled_manifest = validate_store(prior.destination, ProviderId("fixture_bulk")).manifest
    assert isinstance(compiled_manifest, StoreManifest)
    assert compiled_manifest.publisher_artifact.url == ("https://example.test/publisher.zip")
    assert not tuple(tmp_path.glob(".store.staging-*"))
    assert not tuple(tmp_path.glob(".store.previous-*"))


def test_non_streaming_artifact_remains_until_staged_and_published_store_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import rivretrieve._internal.store.certification as certification

    artifact, request = artifact_and_request(tmp_path)
    real_validate = certification.validate_store
    validation_calls = 0

    def observe_validation(root, provider_id):
        nonlocal validation_calls
        validation_calls += 1
        assert artifact.exists()
        return real_validate(root, provider_id)

    monkeypatch.setattr(certification, "validate_store", observe_validation)
    certify_store(request, artifact, lambda _path: complete(rows(value=2.0)))

    assert validation_calls == 2
    assert not artifact.exists()


def test_streaming_rollback_link_setup_cleanup_failure_is_aggregated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib

    import rivretrieve._internal.store.certification as certification
    from rivretrieve._internal.store import ArtifactChecksum, PublisherArtifact

    prior = _published_store(tmp_path)
    artifact = tmp_path / "publisher-second.zip"
    artifact.write_bytes(b"second publisher artifact")
    request = replace(
        prior,
        publisher_artifact=PublisherArtifact(
            "https://example.test/publisher-second.zip",
            ArtifactChecksum("sha256:" + hashlib.sha256(artifact.read_bytes()).hexdigest()),
        ),
    )
    batch = NativeObservationBatch(
        rows(value=2.0),
        (SourceUnitCount("new.csv", 1, 1),),
        (SourceUnitContribution("new.csv", 1),),
    )
    real_remove = certification._remove_tree

    monkeypatch.setattr(
        certification.os, "link", lambda _source, _target: (_ for _ in ()).throw(OSError("link refused"))
    )

    def fail_quarantine_cleanup(path: Path) -> None:
        if path.name.startswith(".publisher-artifacts.rollback-"):
            raise OSError("rollback-link cleanup refused")
        real_remove(path)

    monkeypatch.setattr(certification, "_remove_tree", fail_quarantine_cleanup)
    with pytest.raises(certification.StoreCertificationError, match="rollback-link cleanup refused"):
        certify_store_batches(
            request,
            artifact,
            lambda _path: ObservationBatchStream(
                COLUMNS, (batch,), 1, 1, source_unit_inventory_fingerprint((("new.csv", 1, 1),))
            ),
        )

    assert artifact.exists()
    compiled_manifest = validate_store(prior.destination, ProviderId("fixture_bulk")).manifest
    assert isinstance(compiled_manifest, StoreManifest)
    assert compiled_manifest.publisher_artifact.url == ("https://example.test/publisher.zip")
    assert len(tuple(tmp_path.glob(".publisher-artifacts.rollback-*"))) == 1
    assert not tuple(tmp_path.glob(".store.staging-*"))


def test_linked_artifact_restoration_attempts_each_missing_artifact_and_aggregates_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    import rivretrieve._internal.store.certification as certification

    artifacts = (tmp_path / "first.zip", tmp_path / "second.zip")
    copies = (tmp_path / "first.copy", tmp_path / "second.copy")
    copies[0].write_bytes(b"first")
    copies[1].write_bytes(b"second")
    real_link = os.link

    def fail_first_restore(source: Path | str, target: Path | str) -> None:
        if Path(target) == artifacts[0]:
            raise OSError("first artifact restore refused")
        real_link(source, target)

    monkeypatch.setattr(certification.os, "link", fail_first_restore)
    with pytest.raises(certification.StoreCertificationError, match="first artifact restore refused"):
        certification._restore_linked_artifacts(artifacts, copies)

    assert not artifacts[0].exists()
    assert artifacts[1].read_bytes() == b"second"
