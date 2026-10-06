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
from polars.testing import assert_frame_equal

import rivretrieve as rr
import rivretrieve._internal.bulk as lifecycle
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.pl_imgw import bulk
from rivretrieve._internal.providers.pl_imgw.declaration import declaration
from rivretrieve._internal.providers.registration import BulkStore
from rivretrieve._internal.registry import ProviderRegistry
from rivretrieve._internal.store import ObservationStoreRefusedError, StoreRoot, validate_store
from rivretrieve._internal.store.lifecycle import StoreTransactionError

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
    assert not tuple(Path(root).parent.glob(".store.workspace-*/publisher-artifact.download*"))


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
    if failure == "compiler":
        with pytest.raises(StoreTransactionError) as caught:
            rr.download("pl_imgw")
        assert type(caught.value.original) is expected_error
        assert reason in str(caught.value.original)
        assert caught.value.__cause__ is caught.value.original
        assert caught.value.cleanup_errors == ()
        assert caught.value.generation_id is None
        assert caught.value.committed_path == Path(root)
        assert caught.value.transaction_id
        assert any(path.name.startswith(".store.workspace-") for path in caught.value.residue_paths)
    else:
        with pytest.raises(expected_error, match=reason):
            rr.download("pl_imgw")
    after = {path.relative_to(root): path.read_bytes() for path in Path(root).rglob("*") if path.is_file()}
    assert after == before
    assert validate_store(root, ProviderId("pl_imgw")).manifest == original.manifest
    assert rr.cache_status("pl_imgw").source_vintage == date(2023, 10, 31)
    pending = tuple(Path(root).parent.glob(".store.workspace-*/publisher-artifact.download*"))
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
def test_public_refresh_replaces_with_valid_shorter_history(public_imgw, monkeypatch, replacement):
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
    responses.clear()
    responses.update(publication(replacement_layout, null=True))
    calls.clear()

    refreshed = rr.download("pl_imgw")

    names = [name for yearly_names in replacement_layout.values() for name in yearly_names]
    vintage = (
        date(2022, 10, 31)
        if replacement == "missing-year"
        else (date(2022, 11, 30) if replacement == "missing-terminal-month" else date(2022, 12, 31))
    )
    assert_provenance(root, refreshed, responses, names, vintage)
    assert refreshed.manifest.source_vintage < original.manifest.source_vintage
    assert [url for url in calls if url.endswith(".zip")] == [f"{ROOT}{name[5:9]}/{name}" for name in names]
    rows = pl.read_parquet(list(Path(root).rglob("*.parquet")), hive_partitioning=True)
    expected = []
    definitions = {str(series.product_id): series for series in original.manifest.series}
    for name in names:
        year = int(name[5:9])
        month = int(name[10:12]) if len(name) == 16 else 1
        # These fixtures use only hydrological months 1 and 2 (November/December).
        native = ("1", "S", "R", str(year), str(month), "01", "9999", "99999.999", "99.9", str(month + 10))
        for product, definition in definitions.items():
            facts = definition.facts[0]
            expected.append(
                {
                    "station_id": "1",
                    "time": datetime(year - 1, month + 10, 1),
                    "time_zone": "unknown",
                    "value": None,
                    "value_state": "published_null",
                    "series_id": definition.series_id,
                    "facts_id": facts.facts_id,
                    "source_unit": facts.source_unit.value,
                    **dict(zip((column.name for column in bulk.IMGW_SOURCE_COLUMNS), native, strict=True)),
                    "product": product,
                    "year": year - 1,
                }
            )
    # Exact full physical rows detect old-row union, retained-cell loss and fabricated coverage.
    assert_frame_equal(rows, pl.DataFrame(expected, schema=rows.schema), check_row_order=False)


@pytest.mark.parametrize("failure", ["transfer", "invalid-archive", "certification"])
def test_public_failed_shorter_refresh_preserves_committed_generation(public_imgw, monkeypatch, failure):
    from rivretrieve._internal.store import certification

    root, responses, calls = public_imgw
    responses.update(publication({2023: ["codz_2023.zip"]}))
    original = rr.download("pl_imgw")
    before = {path.relative_to(root): path.read_bytes() for path in Path(root).rglob("*") if path.is_file()}
    names = ["codz_2023_01.zip", "codz_2023_02.zip"]
    responses.clear()
    responses.update(publication({2023: names}, null=True))
    calls.clear()
    failed_url = f"{ROOT}2023/{names[-1]}"
    error = OSError("shorter candidate failed")
    if failure == "transfer":
        responses[failed_url] = error
    elif failure == "invalid-archive":
        responses[failed_url] = b"not a ZIP"
    else:
        verify = certification._verify_streamed_read_back

        def fail_after_readback(*args, **kwargs):
            verify(*args, **kwargs)
            raise error

        monkeypatch.setattr(certification, "_verify_streamed_read_back", fail_after_readback)

    with pytest.raises(OSError if failure == "transfer" else StoreTransactionError) as caught:
        rr.download("pl_imgw")

    assert [url for url in calls if url.endswith(".zip")] == [f"{ROOT}2023/{name}" for name in names]
    if failure == "transfer":
        assert caught.value is error
    else:
        assert isinstance(caught.value, StoreTransactionError)
        assert caught.value.committed_path == Path(root)
        assert caught.value.cleanup_errors == ()
        if failure == "certification":
            assert caught.value.original is error
        else:
            assert isinstance(caught.value.original, ValueError)
            assert "valid ZIP" in str(caught.value.original)
        # Complete downloaded inputs remain discoverable after failed compilation.
        retained = tuple(Path(root).parent.glob(".store.workspace-*/publisher-artifact.download*"))
        assert sorted(path.name for path in retained) == sorted("publisher-artifact.download-" + name for name in names)
        for path in retained:
            name = path.name.removeprefix("publisher-artifact.download-")
            assert path.read_bytes() == responses[f"{ROOT}2023/{name}"]
    assert {path.relative_to(root): path.read_bytes() for path in Path(root).rglob("*") if path.is_file()} == before
    assert validate_store(root, ProviderId("pl_imgw")).manifest == original.manifest
    assert rr.cache_status("pl_imgw").source_vintage == original.manifest.source_vintage


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
    # Explicit download rebuilds refused stores too, including from shorter history.
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
    assert not tuple(Path(root).parent.glob(".store.workspace-*/publisher-artifact.download*"))


@pytest.mark.recorded("tests/test_data/pl_imgw_date_fields/codz_1992_07.zip")
def test_public_exact_archive_compiles_blank_calendar_cell_without_losing_source(
    retained_evidence_root: Path, public_imgw, monkeypatch
):
    from polars.testing import assert_frame_equal

    from rivretrieve._internal.primitives import ProductId
    from rivretrieve._internal.store import StoreQuery, read_store

    root, responses, _calls = public_imgw
    monkeypatch.setattr(bulk, "FIRST_PUBLISHED_YEAR", 1992)
    names = [f"codz_1992_{month:02d}.zip" for month in range(1, 8)]
    responses.update(publication({1992: names}))
    # Only July's hydrological archive is recorded source data. The preceding
    # six tiny publications are synthetic continuity fixtures.
    source = retained_evidence_root / "tests/test_data/pl_imgw_date_fields/codz_1992_07.zip"
    responses[f"{ROOT}1992/{names[-1]}"] = source.read_bytes()
    result = rr.download("pl_imgw")
    assert_provenance(root, result, responses, names, date(1992, 5, 31))
    assert sum(result.manifest.partition_row_counts.values()) == (25408 + 6) * 3
    query = StoreQuery(
        root,
        ProviderId("pl_imgw"),
        ("149220010",),
        tuple(ProductId(name) for name in ("discharge_daily", "stage_daily", "water_temperature_daily")),
        datetime(1992, 5, 16),
        datetime(1992, 5, 16),
    )
    rows = read_store(query).physical_rows.sort("product")
    source_cells = (" 149220010", "NOWOSIELCE", "Pielnica (22618)", "1992", "07", "16", "137", ".170", "99.9", "")
    expected = pl.DataFrame(
        {
            "product": ["discharge_daily", "stage_daily", "water_temperature_daily"],
            "time": [datetime(1992, 5, 16)] * 3,
            "time_zone": ["unknown"] * 3,
            "value": [0.17, 137.0, None],
            "value_state": ["published_value", "published_value", "published_null"],
            **{column.name: [value] * 3 for column, value in zip(bulk.IMGW_SOURCE_COLUMNS, source_cells, strict=True)},
        }
    )
    assert_frame_equal(rows.select(expected.columns), expected)


@pytest.mark.parametrize(
    "failure",
    ["missing-hydro-month", "conflicting-month", "noninteger-month", "invalid-day", "period", "certification"],
)
def test_public_date_failure_preserves_existing_store_and_exact_recovery_bytes(public_imgw, monkeypatch, failure):
    from dataclasses import replace

    from rivretrieve._internal.store.certification import StoreCertificationError

    root, responses, _calls = public_imgw
    responses.update(publication({2023: ["codz_2023.zip"]}))
    previous = rr.download("pl_imgw")
    before = {path.relative_to(root): path.read_bytes() for path in Path(root).rglob("*") if path.is_file()}
    cells = ["1", "S", "R", "2023", "01", "01", "100", "10", "7", " \t"]
    changes = {
        "missing-hydro-month": (4, ""),
        "conflicting-month": (9, "12"),
        "noninteger-month": (9, "NULL"),
        "invalid-day": (5, "31"),
        "period": (3, "2022"),
    }
    if failure in changes:
        position, value = changes[failure]
        cells[position] = value
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive_file:
        archive_file.writestr("codz_2023.csv", ";".join(cells) + "\r\n")
    responses[f"{ROOT}2023/codz_2023.zip"] = content.getvalue()
    if failure == "certification":
        original_decode = bulk.decode_imgw_batches
        calls = 0

        def corrupt_second_decode(paths, *, workspace, **resource_inputs):
            nonlocal calls
            calls += 1
            stream = original_decode(paths, workspace=workspace, **resource_inputs)
            if calls == 1:
                return stream

            def changed():
                for batch in stream.batches:
                    # A verifier must detect filling the retained source blank,
                    # even though the correctly derived timestamp stays unchanged.
                    yield replace(batch, rows=batch.rows.with_columns(pl.lit("11").alias("IMGW_DAILY.calendar_month")))

            return replace(stream, batches=changed())

        monkeypatch.setattr(bulk, "decode_imgw_batches", corrupt_second_decode)
    reasons = {
        "missing-hydro-month": "month_indicator",
        "conflicting-month": "inconsistent month",
        "noninteger-month": "calendar_month",
        "invalid-day": "calendar date",
        "period": "filename publication period",
        "certification": "read-back differs",
    }
    error = StoreCertificationError if failure == "certification" else ValueError
    with pytest.raises(StoreTransactionError) as caught:
        rr.download("pl_imgw")
    assert type(caught.value.original) is error
    assert reasons[failure] in str(caught.value.original)
    assert caught.value.__cause__ is caught.value.original
    assert caught.value.cleanup_errors == ()
    assert caught.value.generation_id is None
    assert caught.value.committed_path == Path(root)
    assert caught.value.transaction_id
    assert any(path.name.startswith(".store.workspace-") for path in caught.value.residue_paths)
    assert {path.relative_to(root): path.read_bytes() for path in Path(root).rglob("*") if path.is_file()} == before
    assert validate_store(root, ProviderId("pl_imgw")).manifest == previous.manifest
    assert rr.cache_status("pl_imgw").source_vintage == previous.manifest.source_vintage
    (retained,) = Path(root).parent.glob(".store.workspace-*/publisher-artifact.download*")
    assert retained.read_bytes() == content.getvalue()


@pytest.mark.parametrize("calendar_cell", ["", " \t"])
def test_public_compiler_preserves_exact_additional_month_blank(public_imgw, calendar_cell):
    from polars.testing import assert_frame_equal

    root, responses, _calls = public_imgw
    responses.update(publication({2023: ["codz_2023.zip"]}))
    cells = ("1", "S", "R", "2023", "01", "01", "100", "10", "7", calendar_cell)
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive_file:
        archive_file.writestr("codz_2023.csv", ";".join(cells) + "\r\n")
    responses[f"{ROOT}2023/codz_2023.zip"] = content.getvalue()
    result = rr.download("pl_imgw")
    assert_provenance(root, result, responses, ["codz_2023.zip"], date(2023, 10, 31))
    rows = pl.read_parquet(list(Path(root).rglob("*.parquet")), hive_partitioning=False)
    expected = pl.DataFrame(
        {
            "time": [datetime(2022, 11, 1)] * 3,
            **{column.name: [value] * 3 for column, value in zip(bulk.IMGW_SOURCE_COLUMNS, cells, strict=True)},
        }
    )
    assert_frame_equal(rows.select(expected.columns), expected)
