from datetime import date
from types import SimpleNamespace

import pytest

from rivretrieve._internal import bulk


def test_insufficient_space_refuses_before_http_client_or_cache_creation(tmp_path, monkeypatch) -> None:
    store = tmp_path / "cache" / "ca_eccc" / "store"
    monkeypatch.setattr(
        bulk,
        "_bulk_registration",
        lambda provider: ("ca_eccc", bulk.ObservationStoreConfig(1, 1000), store, SimpleNamespace()),
    )
    client_created = False

    def client_factory():
        nonlocal client_created
        client_created = True
        raise AssertionError("HTTP client must not be created")

    with pytest.raises(bulk.InsufficientDiskSpaceError) as exc_info:
        bulk._download(
            "ca_eccc",
            free_space_probe=lambda path: 999,
            client_factory=client_factory,
            today=date(2026, 1, 1),
        )

    assert exc_info.value.required_bytes == 1000
    assert exc_info.value.available_bytes == 999
    assert "1000 bytes" in str(exc_info.value)
    assert "999 bytes" in str(exc_info.value)
    assert client_created is False
    assert not (tmp_path / "cache").exists()


def test_bulk_verbs_refuse_non_bulk_provider(monkeypatch) -> None:
    monkeypatch.setattr(bulk, "_ensure_default_providers_registered", lambda: None)

    class Handle:
        provider_id = "usgs_nwis"
        _store_config = None
        _store_root = None
        _bulk_operations = None

    monkeypatch.setattr(bulk._registry, "get", lambda provider: Handle())
    with pytest.raises(bulk.BulkOperationsUnavailableError, match="only for bulk providers"):
        bulk.cache_status("usgs_nwis")


def test_clear_cache_is_idempotent_and_confined_to_store(tmp_path, monkeypatch) -> None:
    store = tmp_path / "ca_eccc" / "store"
    store.mkdir(parents=True)
    (store / "partition.parquet").write_bytes(b"1234")
    neighbour = tmp_path / "ca_eccc" / "publisher.zip"
    neighbour.write_bytes(b"publisher")
    monkeypatch.setattr(
        bulk,
        "_bulk_registration",
        lambda provider: ("ca_eccc", bulk.ObservationStoreConfig(1, 1000), store, SimpleNamespace()),
    )

    first = bulk.clear_cache("ca_eccc")
    second = bulk.clear_cache("ca_eccc")

    assert first.existed is True
    assert first.bytes_freed == 4
    assert second.existed is False
    assert neighbour.read_bytes() == b"publisher"
