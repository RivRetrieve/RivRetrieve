"""cache location and consent : PublicCacheInputs → ResolvedStoreEffects."""

from pathlib import Path

import pytest

import rivretrieve as rr
from rivretrieve._internal import discovery
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.store import StoreRoot

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")


def test_dotenv_relocates_live_and_compiled_store_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RIVRETRIEVE_CACHE_DIR", raising=False)
    cache = tmp_path / "held"
    (tmp_path / ".env").write_text(f"RIVRETRIEVE_CACHE_DIR={cache}\n")
    for provider in ("usgs_nwis", "ca_eccc"):
        status = rr.cache_status(provider)
        assert status.store == cache / provider / "store"
        assert not status.exists
    assert not cache.exists()


def test_environment_overrides_dotenv_and_can_change_after_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("RIVRETRIEVE_CACHE_DIR=from-file\n")
    rr.providers()
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "first"))
    assert rr.cache_status("ca_eccc").store == tmp_path / "first" / "ca_eccc" / "store"
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "second"))
    assert rr.cache_status("ca_eccc").store == tmp_path / "second" / "ca_eccc" / "store"


def test_explicit_registered_store_remains_default_without_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RIVRETRIEVE_CACHE_DIR", raising=False)
    registered = StoreRoot(tmp_path / "registered" / "store")
    assert discovery._resolve_store_root("ca_eccc", registered) == registered


def test_clear_live_cache_removes_only_provider_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    store = tmp_path / "usgs_nwis" / "store"
    store.mkdir(parents=True)
    (store / "manifest.json").write_bytes(b"incompatible cache deliberately awaiting clear")
    sibling = store.parent / "user-notes.txt"
    sibling.write_text("keep")
    result = rr.clear_cache("usgs_nwis")
    assert result.removed_paths == (store,)
    assert result.bytes_freed == len(b"incompatible cache deliberately awaiting clear")
    assert sibling.read_text() == "keep"
    assert not rr.cache_status("usgs_nwis").exists


def test_refresh_bulk_refuses_before_store_or_transport(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    selection = rr.find(
        provider="ca_eccc", station="02GA010", quantity="discharge", frequency="daily", statistic="mean"
    )
    with pytest.raises(FatalContractError, match=r'rivretrieve.download\("ca_eccc"\)'):
        rr.fetch(selection, start="2020-01-01", end="2020-01-02", cache="refresh")
    assert not (tmp_path / "cache").exists()


@pytest.mark.parametrize("mode", (True, None, "automatic", [], 1))
def test_invalid_cache_mode_is_refused_before_retrieval(mode: object) -> None:
    selection = rr.find(provider="usgs_nwis", station="07374000")
    with pytest.raises(ValueError, match="cache must be"):
        rr.fetch(selection, start="2020-01-01", cache=mode)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]


def test_multi_provider_refresh_refuses_before_live_provider_transfer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    selection = rr.find(
        provider=("usgs_nwis", "ca_eccc"),
        station=("07374000", "02GA010"),
        quantity="discharge",
        frequency="daily",
        statistic="mean",
    )

    def no_transport(*args: object) -> None:
        pytest.fail("bulk refresh must be refused before constructing a live transport")

    monkeypatch.setattr(discovery, "_credentialed_transport", no_transport)
    with pytest.raises(FatalContractError, match=r'rivretrieve.download\("ca_eccc"\)'):
        rr.fetch_by_provider(selection, start="2020-01-01", end="2020-01-02", cache="refresh")
    assert not (tmp_path / "cache").exists()


def test_clear_recovers_interrupted_accumulated_publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    provider = tmp_path / "usgs_nwis"
    backup = provider / ".store.backup-interrupted"
    backup.mkdir(parents=True)
    (backup / "manifest.json").write_bytes(b"held")
    pending = provider / ".store.pending-interrupted"
    pending.mkdir()
    (pending / "manifest.json").write_bytes(b"candidate")
    unrelated = provider / "notes"
    unrelated.write_bytes(b"keep")
    result = rr.clear_cache("usgs_nwis")
    assert set(result.removed_paths) == {backup, pending}
    assert result.bytes_freed == len(b"heldcandidate")
    assert unrelated.read_bytes() == b"keep"
    assert not rr.cache_status("usgs_nwis").exists
