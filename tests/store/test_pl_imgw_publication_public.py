"""Public IMGW downloads use publisher listings and preserve certified stores."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import polars as pl
import pytest

import rivretrieve as rr
import rivretrieve._internal.bulk as lifecycle
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.pl_imgw import bulk
from rivretrieve._internal.providers.pl_imgw.declaration import declaration
from rivretrieve._internal.providers.registration import BulkStore
from rivretrieve._internal.registry import ProviderRegistry
from rivretrieve._internal.store import ObservationStoreRefusedError, StoreRoot, validate_store

ROOT = "https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/dobowe/"


def index(url: str, names: list[str]) -> bytes:
    title = "Index of " + urlsplit(url).path.rstrip("/")
    parent = urlsplit(url).path.rstrip("/").rsplit("/", 1)[0] + "/"
    links = f'<tr><td><a href="{parent}">Parent Directory</a></td></tr>'
    links += "".join(f'<tr><td><a href="{name}">{name}</a></td></tr>' for name in names)
    return (
        f"<html><head><title>{title}</title></head><body><h1>{title}</h1><table>{links}</table></body></html>".encode()
    )


def archive(name: str, *, null: bool = False) -> bytes:
    year = int(name[5:9])
    month = int(name[10:12]) if len(name) == 16 else 1
    calendar_month = month + 10 if month <= 2 else month - 2
    values = "9999;99999.999;99.9" if null else "100;10;7"
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as zipped:
        zipped.writestr(name.removesuffix(".zip") + ".csv", f"1;S;R;{year};{month};01;{values};{calendar_month}\r\n")
    return content.getvalue()


def publication(layout: dict[int, list[str]], *, null: bool = False) -> dict[str, bytes]:
    responses = {ROOT: index(ROOT, [f"{year}/" for year in reversed(layout)])}
    for year, names in layout.items():
        directory = f"{ROOT}{year}/"
        responses[directory] = index(directory, list(reversed(names)))
        responses.update({directory + name: archive(name, null=null) for name in names})
    return responses


@pytest.fixture
def public_imgw(tmp_path, monkeypatch, stub_packaged_catalogue_artifact):
    operations = declaration.observations
    assert isinstance(operations, BulkStore)
    root = StoreRoot(tmp_path / "pl_imgw" / "store")
    registry = ProviderRegistry()
    registry.register(
        "pl_imgw",
        stub_packaged_catalogue_artifact("pl_imgw"),
        bulk_config=operations.config,
        observation_store=root,
        bulk_operations=operations,
    )
    responses: dict[str, object] = {}
    calls: list[str] = []

    class OfflineClient:
        def send(self, request):
            assert request.method.value == "GET"
            calls.append(request.url)
            response = responses[request.url]
            if isinstance(response, Exception):
                raise response
            if isinstance(response, int):
                return SimpleNamespace(status_code=response, content=b"publisher failure")
            return SimpleNamespace(status_code=200, content=response)

    class Clock(date):
        @classmethod
        def today(cls):
            return cls(2026, 11, 1)

    monkeypatch.setattr(lifecycle, "_ensure_default_providers_registered", lambda: None)
    monkeypatch.setattr(lifecycle, "_registry", registry)
    monkeypatch.setattr(lifecycle, "HttpClient", OfflineClient)
    monkeypatch.setattr(lifecycle, "date", Clock)
    monkeypatch.setattr(bulk, "FIRST_PUBLISHED_YEAR", 2023)
    return root, responses, calls


def assert_provenance(root, result, responses, names, vintage):
    expected = [
        (f"{ROOT}{name[5:9]}/{name}", "sha256:" + hashlib.sha256(responses[f"{ROOT}{name[5:9]}/{name}"]).hexdigest())
        for name in names
    ]
    assert [(item.url, item.sha256) for item in result.manifest.publisher_artifacts] == expected
    assert result.manifest.source_vintage == vintage
    assert validate_store(root, ProviderId("pl_imgw")).manifest == result.manifest
    assert rr.cache_status("pl_imgw").source_vintage == vintage
    assert not tuple(Path(root).parent.glob("publisher-artifact.download*"))


@pytest.mark.parametrize("empty_trailing_directory", [False, True])
def test_public_download_ignores_unpublished_trailing_year_at_november_boundary(public_imgw, empty_trailing_directory):
    root, responses, calls = public_imgw
    names = [f"codz_{year}.zip" for year in (2023, 2024, 2025)]
    layout = {2023: names[:1], 2024: names[1:2], 2025: names[2:]}
    if empty_trailing_directory:
        layout[2026] = []
    responses.update(publication(layout))
    result = rr.download("pl_imgw")
    assert_provenance(root, result, responses, names, date(2025, 10, 31))
    assert [url for url in calls if url.endswith(".zip")] == [f"{ROOT}{name[5:9]}/{name}" for name in names]
    assert f"{ROOT}2026/codz_2026.zip" not in calls


def test_public_annual_to_partial_monthly_history_preserves_nulls_and_archive_vintage(public_imgw, monkeypatch):
    root, responses, _calls = public_imgw
    monkeypatch.setattr(bulk, "FIRST_PUBLISHED_YEAR", 2022)
    names = ["codz_2022.zip", "codz_2023_01.zip", "codz_2023_02.zip", "codz_2023_03.zip"]
    responses.update(publication({2022: names[:1], 2023: names[1:]}, null=True))
    result = rr.download("pl_imgw")
    assert_provenance(root, result, responses, names, date(2023, 1, 31))
    rows = pl.read_parquet(list(Path(root).rglob("*.parquet")), hive_partitioning=False)
    assert rows.height == 12
    assert rows["value"].null_count() == 12
    assert rows["value_state"].unique().to_list() == ["published_null"]
    assert rows["time"].max() == datetime(2023, 1, 1)


def test_public_refresh_replaces_annual_edition_with_exclusive_monthly_edition(public_imgw):
    root, responses, calls = public_imgw
    responses.update(publication({2023: ["codz_2023.zip"]}))
    original = rr.download("pl_imgw")
    names = [f"codz_2023_{month:02d}.zip" for month in range(1, 13)]
    responses.clear()
    responses.update(publication({2023: names}))
    calls.clear()
    refreshed = rr.download("pl_imgw")
    assert_provenance(root, refreshed, responses, names, date(2023, 10, 31))
    assert refreshed.manifest.publisher_artifacts != original.manifest.publisher_artifacts
    assert f"{ROOT}2023/codz_2023.zip" not in calls


@pytest.mark.parametrize(
    "failure",
    [
        "discovery",
        "index404",
        "historical-year-gap",
        "unsupported",
        "malformed",
        "empty",
        "gap",
        "overlap",
        "duplicate",
        "zip404",
        "transfer",
        "compiler",
        "partial-write",
    ],
)
def test_public_failed_refresh_preserves_store_bytes_and_provenance(public_imgw, monkeypatch, failure):
    root, responses, calls = public_imgw
    responses.update(publication({2023: ["codz_2023.zip"]}))
    original = rr.download("pl_imgw")
    before = {path.relative_to(root): path.read_bytes() for path in Path(root).rglob("*") if path.is_file()}
    names = ["codz_2023.zip", "codz_2024_01.zip", "codz_2024_02.zip"]
    responses.clear()
    responses.update(publication({2023: names[:1], 2024: names[1:]}))
    calls.clear()
    expected_error = ValueError
    if failure == "discovery":
        responses[f"{ROOT}2024/"] = 503
        expected_error = FatalContractError
    elif failure == "index404":
        responses[f"{ROOT}2024/"] = 404
        expected_error = FatalContractError
    elif failure == "historical-year-gap":
        responses.clear()
        responses.update(publication({2023: [names[0]], 2025: ["codz_2025.zip"]}))
    elif failure == "unsupported":
        responses[f"{ROOT}2024/"] = index(f"{ROOT}2024/", ["codz_2024.tar.gz"])
    elif failure == "malformed":
        responses[f"{ROOT}2024/"] = b"<html><body>Maintenance</body></html>"
    elif failure == "empty":
        responses.clear()
        responses.update(publication({2023: [], 2024: []}))
    elif failure == "gap":
        responses[f"{ROOT}2024/"] = index(f"{ROOT}2024/", [names[2]])
    elif failure == "overlap":
        responses[f"{ROOT}2023/"] = index(f"{ROOT}2023/", [names[0], "codz_2023_01.zip"])
    elif failure == "duplicate":
        responses[f"{ROOT}2023/"] = index(f"{ROOT}2023/", [names[0], names[0]])
    elif failure == "zip404":
        responses[f"{ROOT}2024/{names[2]}"] = 404
        expected_error = FatalContractError
    elif failure == "transfer":
        responses[f"{ROOT}2024/{names[2]}"] = OSError("connection interrupted")
        expected_error = OSError
    elif failure == "compiler":
        responses[f"{ROOT}2024/{names[2]}"] = b"not a ZIP"
    elif failure == "partial-write":
        original_write = Path.write_bytes

        def interrupted_write(path, content):
            if path.name.endswith(names[2]):
                original_write(path, content[:10])
                raise OSError("partial disk write")
            return original_write(path, content)

        monkeypatch.setattr(Path, "write_bytes", interrupted_write)
        expected_error = OSError
    reason = {
        "discovery": "HTTP 503",
        "index404": "HTTP 404",
        "historical-year-gap": "gap",
        "unsupported": "unsupported",
        "malformed": "identity or structure",
        "empty": "no supported daily history",
        "gap": "gap",
        "overlap": "overlap",
        "duplicate": "duplicate",
        "zip404": "HTTP 404",
        "transfer": "connection interrupted",
        "compiler": "valid ZIP",
        "partial-write": "partial disk write",
    }[failure]
    with pytest.raises(expected_error, match=reason):
        rr.download("pl_imgw")
    after = {path.relative_to(root): path.read_bytes() for path in Path(root).rglob("*") if path.is_file()}
    assert after == before
    assert validate_store(root, ProviderId("pl_imgw")).manifest == original.manifest
    assert rr.cache_status("pl_imgw").source_vintage == date(2023, 10, 31)
    pending = tuple(Path(root).parent.glob("publisher-artifact.download*"))
    if failure == "compiler":
        assert sorted(path.name for path in pending) == sorted("publisher-artifact.download-" + name for name in names)
        for path in pending:
            name = path.name.removeprefix("publisher-artifact.download-")
            assert path.read_bytes() == responses[f"{ROOT}{name[5:9]}/{name}"]
    else:
        assert not pending
    if failure in {"zip404", "transfer", "compiler", "partial-write"}:
        assert [url for url in calls if url.endswith(".zip")] == [f"{ROOT}{name[5:9]}/{name}" for name in names]


@pytest.mark.parametrize("replacement", ["missing-year", "missing-terminal-month", "partial-monthly-replacement"])
def test_public_refresh_cannot_shorten_previously_published_history(public_imgw, monkeypatch, replacement):
    root, responses, calls = public_imgw
    monkeypatch.setattr(bulk, "FIRST_PUBLISHED_YEAR", 2022)
    if replacement == "missing-terminal-month":
        original_layout = {2022: ["codz_2022.zip"], 2023: ["codz_2023_01.zip", "codz_2023_02.zip"]}
        replacement_layout = {2022: ["codz_2022.zip"], 2023: ["codz_2023_01.zip"]}
    else:
        original_layout = {2022: ["codz_2022.zip"], 2023: ["codz_2023.zip"]}
        replacement_layout = {2022: ["codz_2022.zip"]}
        if replacement == "partial-monthly-replacement":
            replacement_layout[2023] = ["codz_2023_01.zip", "codz_2023_02.zip"]
    responses.update(publication(original_layout))
    original = rr.download("pl_imgw")
    before = {path.relative_to(root): path.read_bytes() for path in Path(root).rglob("*") if path.is_file()}
    responses.clear()
    responses.update(publication(replacement_layout))
    calls.clear()

    with pytest.raises(ValueError, match="(?i)(shorten|regress|previous|coverage)"):
        rr.download("pl_imgw")

    assert {path.relative_to(root): path.read_bytes() for path in Path(root).rglob("*") if path.is_file()} == before
    assert validate_store(root, ProviderId("pl_imgw")).manifest == original.manifest
    assert rr.cache_status("pl_imgw").source_vintage == original.manifest.source_vintage
    assert not any(url.endswith(".zip") for url in calls)
    assert not tuple(Path(root).parent.glob("publisher-artifact.download*"))


@pytest.mark.parametrize("refused_manifest", ["incompatible", "malformed"])
def test_public_download_rebuilds_refused_existing_store(public_imgw, refused_manifest):
    root, responses, calls = public_imgw
    responses.update(publication({2023: ["codz_2023.zip"]}))
    rr.download("pl_imgw")
    manifest_path = Path(root) / "manifest.json"
    if refused_manifest == "incompatible":
        manifest = json.loads(manifest_path.read_bytes())
        manifest["format_version"] = 4
        manifest_path.write_text(json.dumps(manifest))
    else:
        manifest_path.write_bytes(b"{malformed JSON")
    with pytest.raises(ObservationStoreRefusedError) as refusal:
        validate_store(root, ProviderId("pl_imgw"))
    assert refusal.value.refusal.kind.value == refused_manifest
    responses.clear()
    # A refused store cannot establish a vintage floor. Explicit download rebuilds it.
    names = ["codz_2023_01.zip"]
    responses.update(publication({2023: names}))
    calls.clear()

    rebuilt = rr.download("pl_imgw")

    assert_provenance(root, rebuilt, responses, names, date(2022, 11, 30))
    assert calls[0] == ROOT


def test_public_download_propagates_unexpected_previous_store_validation_failure(public_imgw, monkeypatch):
    root, responses, calls = public_imgw
    responses.update(publication({2023: ["codz_2023.zip"]}))
    original = rr.download("pl_imgw")
    before = {path.relative_to(root): path.read_bytes() for path in Path(root).rglob("*") if path.is_file()}
    manifest_path = Path(root) / "manifest.json"
    read_bytes = Path.read_bytes

    def unexpected_failure(path):
        if path == manifest_path:
            raise RuntimeError("unexpected manifest validation failure")
        return read_bytes(path)

    calls.clear()
    with monkeypatch.context() as fault:
        fault.setattr(Path, "read_bytes", unexpected_failure)
        with pytest.raises(RuntimeError, match="unexpected manifest validation failure"):
            rr.download("pl_imgw")

    assert not calls
    assert {path.relative_to(root): path.read_bytes() for path in Path(root).rglob("*") if path.is_file()} == before
    assert validate_store(root, ProviderId("pl_imgw")).manifest == original.manifest
    assert not tuple(Path(root).parent.glob("publisher-artifact.download*"))
