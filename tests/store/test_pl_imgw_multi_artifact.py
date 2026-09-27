"""IMGW bulk acquisition spans source publication forms without losing artifacts."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from rivretrieve._internal.providers.pl_imgw.bulk import BASE_URL, download_imgw_history
from rivretrieve._internal.store.validation import StoreManifest


def _index(url: str, names: tuple[str, ...]) -> bytes:
    identity = "Index of /" + url.split("/", 3)[3].rstrip("/")
    links = "".join(f'<tr><td><a href="{name}">{name}</a></td></tr>' for name in names)
    return f"<html><head><title>{identity}</title></head><body><h1>{identity}</h1><table>{links}</table></body></html>".encode()


def _listing_transfer(transfer, names: tuple[str, ...]):
    years = sorted({name[5:9] for name in names})
    listings = {BASE_URL + "/": _index(BASE_URL + "/", tuple(year + "/" for year in years))}
    for year in years:
        url = f"{BASE_URL}/{year}/"
        listings[url] = _index(url, tuple(name for name in names if name[5:9] == year))

    def receive(url: str, destination: Path) -> None:
        if url in listings:
            destination.write_bytes(listings[url])
        else:
            transfer(url, destination)

    return receive


def _official_url(name: str) -> str:
    year = int(name[5:9])
    return f"https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/dobowe/{year}/{name}"


def test_imgw_near_sentinel_numeric_is_not_reclassified_as_published_null() -> None:
    from rivretrieve._internal.providers.pl_imgw.bulk import _native_value

    assert _native_value("999.0004", "codz_2022_01.csv", 1, "Flow [m^3/s]", frozenset({999.0})) == (
        999.0004,
        "published_value",
    )


def test_multi_artifact_compile_publishes_one_union_with_complete_provenance(tmp_path) -> None:
    import zipfile
    from datetime import UTC, datetime

    from rivretrieve._internal.providers.pl_imgw.bulk import DownloadedImgw, ImgwCompileRequest, compile_imgw
    from rivretrieve._internal.store import StoreRoot

    artifacts = []
    for month, calendar_month, day in ((1, 11, 1), (2, 12, 2)):
        path = tmp_path / f"codz_2022_{month:02d}.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(
                path.stem + ".csv",
                f"154210010;SEPOPOL;Lyna;2022;{month:02d};{day:02d};100;10.0;7.0;{calendar_month}\r\n".encode("cp1250"),
            )
        artifacts.append(DownloadedImgw(path, _official_url(path.name)))
    root = StoreRoot(tmp_path / "store")
    validated = compile_imgw(
        ImgwCompileRequest(
            artifacts[0].path,
            root,
            artifacts[0].url,
            max(item.source_vintage for item in artifacts),
            datetime(2026, 9, 2, tzinfo=UTC),
            "0.1.49",
            tuple(artifacts),
        )
    )

    assert isinstance(validated.manifest, StoreManifest)
    assert [item.url for item in validated.manifest.publisher_artifacts] == [item.url for item in artifacts]
    assert all(not item.path.exists() for item in artifacts)
    assert validated.manifest.partition_row_counts == {
        "product=discharge_daily/year=2021": 2,
        "product=stage_daily/year=2021": 2,
        "product=water_temperature_daily/year=2021": 2,
    }


def test_imgw_history_download_transfers_every_planned_artifact_once(tmp_path) -> None:
    calls: list[tuple[str, Path]] = []

    def transfer(url: str, destination: Path) -> None:
        calls.append((url, destination))
        destination.write_bytes(url.encode())

    downloaded = download_imgw_history(
        tmp_path / "publisher-artifact.download",
        today=date(2024, 6, 1),
        transfer=_listing_transfer(
            transfer, tuple(f"codz_2022_{month:02d}.zip" for month in range(1, 13)) + ("codz_2023.zip",)
        ),
        first_year=2022,
    )

    assert len(downloaded) == len(calls) == 13
    assert tuple(item.url for item in downloaded) == tuple(url for url, _path in calls)
    assert len({item.path for item in downloaded}) == 13
    assert all(item.path.read_bytes() == item.url.encode() for item in downloaded)


def test_multi_artifact_failure_retains_all_inputs_and_previous_store(tmp_path) -> None:
    import zipfile
    from datetime import UTC, datetime

    import pytest

    from rivretrieve._internal.primitives import ProviderId
    from rivretrieve._internal.providers.pl_imgw.bulk import DownloadedImgw, ImgwCompileRequest, compile_imgw
    from rivretrieve._internal.store import StoreRoot, validate_store

    root = StoreRoot(tmp_path / "store")
    initial = tmp_path / "codz_2023.zip"
    with zipfile.ZipFile(initial, "w") as archive:
        archive.writestr("codz_2023.csv", b"154210010;SEPOPOL;Lyna;2023;03;01;100;10.0;7.0;1\r\n")
    compile_imgw(
        ImgwCompileRequest(
            initial,
            root,
            _official_url("codz_2023.zip"),
            date(2023, 10, 31),
            datetime(2026, 9, 2, tzinfo=UTC),
            "0.1.49",
        )
    )
    valid = tmp_path / "codz_2022_01.zip"
    with zipfile.ZipFile(valid, "w") as archive:
        archive.writestr("codz_2022_01.csv", b"154210010;SEPOPOL;Lyna;2022;01;01;100;10.0;7.0;11\r\n")
    malformed = tmp_path / "codz_2022_02.zip"
    malformed.write_bytes(b"not a ZIP")
    artifacts = (
        DownloadedImgw(valid, _official_url("codz_2022_01.zip")),
        DownloadedImgw(malformed, _official_url("codz_2022_02.zip")),
    )
    with pytest.raises(ValueError, match="valid ZIP"):
        compile_imgw(
            ImgwCompileRequest(
                valid,
                root,
                artifacts[0].url,
                max(item.source_vintage for item in artifacts),
                datetime(2026, 9, 3, tzinfo=UTC),
                "0.1.49",
                artifacts,
            )
        )

    assert valid.exists() and malformed.exists()
    compiled_manifest = validate_store(root, ProviderId("pl_imgw")).manifest
    assert isinstance(compiled_manifest, StoreManifest)
    assert compiled_manifest.publisher_artifact.url == _official_url("codz_2023.zip")


def test_imgw_history_download_removes_partial_current_target_and_refuses_preexisting(tmp_path) -> None:
    import pytest

    base = tmp_path / "publisher-artifact.download"
    first_target = base.with_name(base.name + "-codz_2023.zip")
    first_target.write_bytes(b"existing")
    with pytest.raises(FileExistsError, match="already exists"):
        download_imgw_history(
            base,
            today=date(2024, 1, 1),
            transfer=_listing_transfer(lambda _url, _path: None, ("codz_2023.zip",)),
            first_year=2023,
        )
    assert first_target.read_bytes() == b"existing"

    first_target.unlink()

    def partial(_url: str, destination: Path) -> None:
        destination.write_bytes(b"partial")
        raise OSError("transfer failed")

    with pytest.raises(OSError, match="transfer failed"):
        download_imgw_history(
            base, today=date(2024, 1, 1), transfer=_listing_transfer(partial, ("codz_2023.zip",)), first_year=2023
        )
    assert not first_target.exists()


def test_second_artifact_unlink_failure_restores_every_artifact_and_previous_store(tmp_path, monkeypatch) -> None:
    import zipfile
    from datetime import UTC, datetime

    import pytest

    from rivretrieve._internal.primitives import ProviderId
    from rivretrieve._internal.providers.pl_imgw.bulk import DownloadedImgw, ImgwCompileRequest, compile_imgw
    from rivretrieve._internal.store import StoreRoot, validate_store

    root = StoreRoot(tmp_path / "store")
    initial = tmp_path / "codz_2023.zip"
    with zipfile.ZipFile(initial, "w") as archive:
        archive.writestr("codz_2023.csv", b"154210010;SEPOPOL;Lyna;2023;03;01;100;10.0;7.0;1\r\n")
    compile_imgw(
        ImgwCompileRequest(
            initial,
            root,
            _official_url("codz_2023.zip"),
            date(2023, 10, 31),
            datetime(2026, 9, 2, tzinfo=UTC),
            "0.1.49",
        )
    )
    artifacts = []
    for month, calendar_month in ((3, 1), (4, 2)):
        path = tmp_path / f"codz_2022_{month:02d}.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(
                path.stem + ".csv",
                f"154210010;SEPOPOL;Lyna;2022;{month:02d};01;100;10.0;7.0;{calendar_month}\r\n".encode(),
            )
        artifacts.append(DownloadedImgw(path, _official_url(path.name)))
    real_unlink = Path.unlink

    def fail_second(path: Path, *args, **kwargs):
        if path == artifacts[1].path:
            raise OSError("second unlink refused")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_second)

    with pytest.raises(OSError, match="second unlink refused"):
        compile_imgw(
            ImgwCompileRequest(
                artifacts[0].path,
                root,
                artifacts[0].url,
                max(item.source_vintage for item in artifacts),
                datetime(2026, 9, 3, tzinfo=UTC),
                "0.1.49",
                tuple(artifacts),
            )
        )

    assert all(item.path.exists() for item in artifacts)
    compiled_manifest = validate_store(root, ProviderId("pl_imgw")).manifest
    assert isinstance(compiled_manifest, StoreManifest)
    assert compiled_manifest.publisher_artifact.url == _official_url("codz_2023.zip")
    assert not tuple(tmp_path.glob(".publisher-artifacts.rollback-*"))


def test_imgw_plural_request_refuses_a_conflicting_singular_identity(tmp_path) -> None:
    from datetime import UTC, datetime

    import pytest

    from rivretrieve._internal.providers.pl_imgw.bulk import DownloadedImgw, ImgwCompileRequest
    from rivretrieve._internal.store import StoreRoot

    first = DownloadedImgw(tmp_path / "codz_2022_01.zip", _official_url("codz_2022_01.zip"))
    with pytest.raises(ValueError, match="must equal the first plural"):
        ImgwCompileRequest(
            tmp_path / "different.zip",
            StoreRoot(tmp_path / "store"),
            _official_url("codz_2022_02.zip"),
            date(2022, 1, 2),
            datetime(2026, 9, 2, tzinfo=UTC),
            "0.1.49",
            (first,),
        )


def test_post_commit_quarantine_cleanup_failure_is_loud_and_keeps_new_store_authoritative(
    tmp_path, monkeypatch
) -> None:
    import zipfile
    from datetime import UTC, datetime

    import pytest

    import rivretrieve._internal.store.certification as certification
    from rivretrieve._internal.providers.pl_imgw.bulk import DownloadedImgw, ImgwCompileRequest, compile_imgw
    from rivretrieve._internal.store import StoreRoot

    artifacts = []
    for month, calendar_month in ((3, 1), (4, 2)):
        path = tmp_path / f"codz_2022_{month:02d}.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(
                path.stem + ".csv",
                f"154210010;SEPOPOL;Lyna;2022;{month:02d};01;100;10.0;7.0;{calendar_month}\r\n".encode(),
            )
        artifacts.append(DownloadedImgw(path, _official_url(path.name)))
    real_remove = certification._remove_tree
    refused = False

    def fail_once(path: Path) -> None:
        nonlocal refused
        if path.name.startswith(".publisher-artifacts.rollback-") and not refused:
            refused = True
            next(path.iterdir()).unlink()
            raise OSError("rollback cleanup refused")
        real_remove(path)

    monkeypatch.setattr(certification, "_remove_tree", fail_once)
    root = StoreRoot(tmp_path / "store")

    with pytest.raises(certification.StorePostCommitCleanupError, match="new store is authoritative"):
        compile_imgw(
            ImgwCompileRequest(
                artifacts[0].path,
                root,
                artifacts[0].url,
                max(item.source_vintage for item in artifacts),
                datetime(2026, 9, 3, tzinfo=UTC),
                "0.1.49",
                tuple(artifacts),
            )
        )

    assert all(not item.path.exists() for item in artifacts)
    assert Path(root).is_dir()
    residues = tuple(tmp_path.glob(".publisher-artifacts.rollback-*"))
    assert len(residues) == 1
    assert len(tuple(residues[0].iterdir())) == 1
    assert not tuple(tmp_path.glob(".store.previous-*"))


def test_imgw_rejects_hydrological_month_that_disagrees_with_archive_name(tmp_path) -> None:
    import zipfile

    from rivretrieve._internal.providers.pl_imgw.bulk import decode_imgw_batches

    artifact = tmp_path / "codz_2022_03.zip"
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr("codz_2022_03.csv", b"1;S;R;2022;12;01;100;1;2;10\r\n")

    with pytest.raises(ValueError, match="filename.*hydrological"):
        next(iter(decode_imgw_batches(artifact).batches))


def test_imgw_plural_identity_rejects_duplicate_paths_urls_and_mislabeled_url(tmp_path) -> None:
    from datetime import UTC, datetime

    from rivretrieve._internal.providers.pl_imgw.bulk import DownloadedImgw, ImgwCompileRequest
    from rivretrieve._internal.store import StoreRoot

    path = tmp_path / "codz_2022_03.zip"
    first = DownloadedImgw(path, _official_url("codz_2022_03.zip"))
    duplicate_url = DownloadedImgw(tmp_path / "codz_2022_04.zip", first.url)
    mislabeled = DownloadedImgw(path, _official_url("codz_1999_01.zip"))
    common = (
        path,
        StoreRoot(tmp_path / "store"),
        first.url,
        first.source_vintage,
        datetime(2026, 9, 2, tzinfo=UTC),
        "0.1.49",
    )
    with pytest.raises(ValueError, match="duplicate publisher artifact path"):
        ImgwCompileRequest(*common, (first, first))
    with pytest.raises(ValueError, match="duplicate publisher artifact URL"):
        ImgwCompileRequest(*common, (first, duplicate_url))
    with pytest.raises(ValueError, match="URL basename"):
        ImgwCompileRequest(
            path, common[1], mislabeled.url, mislabeled.source_vintage, common[4], common[5], (mislabeled,)
        )


@pytest.mark.parametrize(
    "url",
    (
        "https://evil.example/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/dobowe/2022/codz_2022_03.zip",
        "https://danepubliczne.imgw.pl/wrong/2022/codz_2022_03.zip",
    ),
)
def test_imgw_identity_rejects_nonofficial_origin_or_directory(tmp_path, url: str) -> None:
    from datetime import UTC, datetime

    from rivretrieve._internal.providers.pl_imgw.bulk import DownloadedImgw, ImgwCompileRequest
    from rivretrieve._internal.store import StoreRoot

    path = tmp_path / "codz_2022_03.zip"
    item = DownloadedImgw(path, url)
    with pytest.raises(ValueError, match="exact official period template"):
        ImgwCompileRequest(
            path,
            StoreRoot(tmp_path / "store"),
            url,
            item.source_vintage,
            datetime(2026, 9, 2, tzinfo=UTC),
            "0.1.49",
            (item,),
        )


def _imgw_compile_request_for_names(tmp_path: Path, names: tuple[str, ...]):
    from datetime import UTC, datetime

    from rivretrieve._internal.providers.pl_imgw.bulk import DownloadedImgw, ImgwCompileRequest
    from rivretrieve._internal.store import StoreRoot

    artifacts = tuple(DownloadedImgw(tmp_path / name, _official_url(name)) for name in names)
    first = artifacts[0]
    return ImgwCompileRequest(
        first.path,
        StoreRoot(tmp_path / "store"),
        first.url,
        max(item.source_vintage for item in artifacts),
        datetime(2026, 9, 2, tzinfo=UTC),
        "0.1.49",
        artifacts,
    )


@pytest.mark.parametrize(
    "names",
    (
        ("codz_2022_01.zip", "codz_2022_03.zip"),
        ("codz_2021_12.zip", "codz_2022_02.zip"),
        ("codz_2022_12.zip", "codz_2024.zip"),
        ("codz_2023.zip", "codz_2025.zip"),
    ),
)
def test_imgw_plural_compile_identity_refuses_internal_period_gap(tmp_path: Path, names: tuple[str, ...]) -> None:
    with pytest.raises(ValueError, match="contiguous"):
        _imgw_compile_request_for_names(tmp_path, names)


@pytest.mark.parametrize("name", ("codz_2023_01.zip", "codz_2022.zip", "codz_2024_12.zip"))
def test_imgw_compile_identity_accepts_either_publication_form_in_any_year(tmp_path: Path, name: str) -> None:
    request = _imgw_compile_request_for_names(tmp_path, (name,))
    assert len(request.publisher_artifacts) == 1


@pytest.mark.parametrize(
    "names",
    (
        ("codz_2022_01.zip",),
        ("codz_2023.zip",),
        ("codz_2022_01.zip", "codz_2022_02.zip"),
        ("codz_2021_12.zip", "codz_2022_01.zip"),
        ("codz_2022_12.zip", "codz_2023.zip"),
        ("codz_2023.zip", "codz_2024.zip"),
    ),
)
def test_imgw_compile_identity_accepts_valid_regime_and_contiguous_periods(
    tmp_path: Path, names: tuple[str, ...]
) -> None:
    request = _imgw_compile_request_for_names(tmp_path, names)
    assert len(request.publisher_artifacts) == len(names)


def test_imgw_source_vintage_is_publisher_labelled_coverage_end() -> None:
    from rivretrieve._internal.providers.pl_imgw.bulk import DownloadedImgw

    assert DownloadedImgw(Path("codz_2022_01.zip"), _official_url("codz_2022_01.zip")).source_vintage == date(
        2021, 11, 30
    )
    assert DownloadedImgw(Path("codz_2022_02.zip"), _official_url("codz_2022_02.zip")).source_vintage == date(
        2021, 12, 31
    )
    assert DownloadedImgw(Path("codz_2022_12.zip"), _official_url("codz_2022_12.zip")).source_vintage == date(
        2022, 10, 31
    )
    assert DownloadedImgw(Path("codz_2023.zip"), _official_url("codz_2023.zip")).source_vintage == date(2023, 10, 31)


def test_imgw_streaming_first_batch_retains_bounded_rows(tmp_path, monkeypatch) -> None:
    import zipfile

    import rivretrieve._internal.providers.pl_imgw.bulk as bulk

    artifact = tmp_path / "codz_2022_03.zip"
    source = b"".join(f"{index:09d};S;R;2022;03;01;100;1;2;1\r\n".encode() for index in range(10))
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr("codz_2022_03.csv", source)
    monkeypatch.setattr(bulk, "IMGW_ROWS_PER_BATCH", 4)

    first = next(iter(bulk.decode_imgw_batches(artifact).batches))

    assert first.rows.height == 4


def test_imgw_history_download_includes_just_published_year_in_november(tmp_path) -> None:
    calls: list[str] = []

    def transfer(url: str, destination: Path) -> None:
        calls.append(url)
        destination.write_bytes(b"publisher")

    downloaded = download_imgw_history(
        tmp_path / "publisher.download",
        today=date(2024, 11, 1),
        transfer=_listing_transfer(transfer, ("codz_2023.zip", "codz_2024.zip")),
        first_year=2023,
    )

    assert [Path(item.url).name for item in downloaded] == ["codz_2023.zip", "codz_2024.zip"]
    assert calls == [item.url for item in downloaded]


@pytest.mark.parametrize("omission", ["product", "record"])
def test_imgw_real_decoder_reconciliation_refuses_omission(tmp_path, monkeypatch, omission: str) -> None:
    import zipfile
    from datetime import UTC, datetime

    import rivretrieve._internal.providers.pl_imgw.bulk as bulk
    from rivretrieve._internal.store import StoreRoot

    artifact = tmp_path / "codz_2022_03.zip"
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr(
            "codz_2022_03.csv",
            b"000000001;S;R;2022;03;01;100;1;2;1\r\n000000002;S;R;2022;03;02;101;2;3;1\r\n",
        )
    if omission == "product":
        original_emit = bulk._emit_source_row

        def omit_product(source, member, ordinal, output, **kwargs):
            original_emit(source, member, ordinal, output, **kwargs)
            output.pop()

        monkeypatch.setattr(bulk, "_emit_source_row", omit_product)
    else:
        original_records = bulk._iter_imgw_records

        def omit_record(path):
            rows = iter(original_records(path))
            next(rows)
            yield from rows

        monkeypatch.setattr(bulk, "_iter_imgw_records", omit_record)

    item = bulk.DownloadedImgw(artifact, _official_url(artifact.name))
    request = bulk.ImgwCompileRequest(
        artifact,
        StoreRoot(tmp_path / "store"),
        item.url,
        item.source_vintage,
        datetime(2026, 9, 2, tzinfo=UTC),
        "0.1.49",
    )
    with pytest.raises(
        ValueError, match="every declared product cell|did not emit every expected row|publisher-record inventory"
    ):
        bulk.compile_imgw(request)
    assert artifact.exists()


def test_imgw_identity_inventory_refuses_equal_count_record_substitution(tmp_path, monkeypatch) -> None:
    import zipfile
    from datetime import UTC, datetime

    import rivretrieve._internal.providers.pl_imgw.bulk as bulk
    from rivretrieve._internal.store import StoreRoot

    artifact = tmp_path / "codz_2022_03.zip"
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr("codz_2022_03.csv", b"1;S;R;2022;03;01;100;1;2;1\r\n2;S;R;2022;03;02;101;2;3;1\r\n")
    original = bulk._iter_imgw_records

    def substitute(path):
        records = list(original(path))
        yield records[1]
        yield records[1]

    monkeypatch.setattr(bulk, "_iter_imgw_records", substitute)
    item = bulk.DownloadedImgw(artifact, _official_url(artifact.name))
    request = bulk.ImgwCompileRequest(
        artifact,
        StoreRoot(tmp_path / "store"),
        item.url,
        item.source_vintage,
        datetime(2026, 9, 2, tzinfo=UTC),
        "0.1.49",
    )
    with pytest.raises(ValueError, match="identity inventory"):
        bulk.compile_imgw(request)
    assert artifact.exists()


def _tiny_artifact(tmp_path: Path, name: str, row: bytes):
    import zipfile

    from rivretrieve._internal.providers.pl_imgw.bulk import DownloadedImgw
    from rivretrieve._internal.providers.registration import DownloadedBulkArtifact

    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(path.stem + ".csv", row)
    item = DownloadedImgw(path, _official_url(name))
    return DownloadedBulkArtifact(path, item.url, item.source_vintage)


def _compile_declared(artifacts, root):
    from datetime import UTC, datetime

    from rivretrieve._internal.providers.pl_imgw.declaration import declaration
    from rivretrieve._internal.providers.registration import BulkCompileRequest, BulkStore

    assert isinstance(declaration.observations, BulkStore)
    return declaration.observations.compile(
        BulkCompileRequest(tuple(artifacts), root, datetime(2026, 9, 2, tzinfo=UTC), "0.1.49")
    )


@pytest.mark.parametrize("transition", [False, True], ids=["monthly", "monthly-to-annual"])
def test_real_declaration_persists_union_and_maximum_labelled_vintage(tmp_path, transition) -> None:
    import hashlib
    from datetime import datetime

    import polars as pl
    from polars.testing import assert_frame_equal

    from rivretrieve._internal.primitives import ProviderId
    from rivretrieve._internal.store import StoreRoot, validate_store

    if transition:
        names = ("codz_2022_12.zip", "codz_2023.zip")
        rows = (b"1;S;R;2022;12;01;100;10;7;10\r\n", b"1;S;R;2023;01;02;101;11;8;11\r\n")
        times = (datetime(2022, 10, 1), datetime(2022, 11, 2))
        vintage = date(2023, 10, 31)
    else:
        names = ("codz_1951_11.zip", "codz_1951_12.zip")
        rows = (b"1;S;R;1951;11;01;100;10;7;9\r\n", b"1;S;R;1951;12;02;101;11;8;10\r\n")
        times = (datetime(1951, 9, 1), datetime(1951, 10, 2))
        vintage = date(1951, 10, 31)
    artifacts = tuple(_tiny_artifact(tmp_path, name, row) for name, row in zip(names, rows, strict=True))
    checksums = ["sha256:" + hashlib.sha256(item.path.read_bytes()).hexdigest() for item in artifacts]
    root = StoreRoot(tmp_path / "store")
    compiled = _compile_declared(artifacts, root)
    reloaded = validate_store(root, ProviderId("pl_imgw"))
    assert compiled.manifest == reloaded.manifest
    for manifest in (compiled.manifest, reloaded.manifest):
        assert isinstance(manifest, StoreManifest)
        assert manifest.source_vintage == vintage
        assert [item.url for item in manifest.publisher_artifacts] == [item.url for item in artifacts]
        assert [str(item.sha256) for item in manifest.publisher_artifacts] == checksums
    expected = pl.DataFrame(
        {
            "product": [
                product for product in ("discharge_daily", "stage_daily", "water_temperature_daily") for _ in times
            ],
            "station_id": ["1"] * 6,
            "time": list(times) * 3,
            "value": [10.0, 11.0, 100.0, 101.0, 7.0, 8.0],
        }
    )
    actual = pl.read_parquet(list(Path(root).rglob("*.parquet")), hive_partitioning=True).select(expected.columns)
    assert_frame_equal(actual.sort("product", "time"), expected.sort("product", "time"))
    assert all(not item.path.exists() for item in artifacts)


@pytest.mark.parametrize(
    ("index", "wrong_date"),
    [(0, date(2021, 11, 29)), (1, date(2021, 12, 30)), (2, date(2022, 2, 1))],
    ids=["first-unchanged-max", "nonfirst-unchanged-max", "last-changed-max"],
)
def test_declaration_rejects_supplied_vintage_without_changing_inputs_or_store(tmp_path, index, wrong_date) -> None:
    from dataclasses import replace

    from rivretrieve._internal.primitives import ProviderId
    from rivretrieve._internal.store import StoreRoot, validate_store

    root = StoreRoot(tmp_path / "store")
    initial = _tiny_artifact(tmp_path, "codz_2023.zip", b"1;S;R;2023;03;01;100;10;7;1\r\n")
    previous = _compile_declared((initial,), root)
    before = {p.relative_to(root): p.read_bytes() for p in Path(root).rglob("*") if p.is_file()}
    artifacts = tuple(
        _tiny_artifact(
            tmp_path, f"codz_2022_{month:02d}.zip", f"1;S;R;2022;{month:02d};01;100;10;7;{calendar_month}\r\n".encode()
        )
        for month, calendar_month in ((1, 11), (2, 12), (3, 1))
    )
    inputs = {item.path: item.path.read_bytes() for item in artifacts}
    invalid = tuple(
        replace(item, source_vintage=wrong_date) if n == index else item for n, item in enumerate(artifacts)
    )
    if index < 2:
        assert max(item.source_vintage for item in invalid) == max(item.source_vintage for item in artifacts)
    with pytest.raises(ValueError, match="publisher-labelled coverage end"):
        _compile_declared(invalid, root)
    assert {path: path.read_bytes() for path in inputs} == inputs
    assert {p.relative_to(root): p.read_bytes() for p in Path(root).rglob("*") if p.is_file()} == before
    assert validate_store(root, ProviderId("pl_imgw")).manifest == previous.manifest


def test_imgw_plural_identity_rejects_disordered_periods(tmp_path) -> None:
    with pytest.raises(ValueError, match="out of period order"):
        _imgw_compile_request_for_names(tmp_path, ("codz_2022_02.zip", "codz_2022_01.zip"))


def test_imgw_plural_identity_rejects_repeated_overlapping_period(tmp_path) -> None:
    # Official publication regimes have disjoint periods; repeating a period repeats its URL.
    with pytest.raises(ValueError, match="duplicate publisher artifact"):
        _imgw_compile_request_for_names(tmp_path, ("codz_2023.zip", "codz_2023.zip"))


def test_imgw_plural_identity_rejects_inconsistent_aggregate_vintage(tmp_path) -> None:
    from dataclasses import replace

    request = _imgw_compile_request_for_names(tmp_path, ("codz_2022_01.zip", "codz_2022_02.zip"))
    with pytest.raises(ValueError, match="vintage"):
        replace(request, source_vintage=date(2021, 11, 30))
