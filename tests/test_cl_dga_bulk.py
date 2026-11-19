"""Synthetic and store-contract tests for Chile DGA (cl_dga) bulk download and compilation."""

from __future__ import annotations

import zipfile
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

DAILY_HEADER = (
    "CODIGO ESTACION",
    "NOMBRE ESTACION",
    "COD_REGION",
    "REGION",
    "COMUNA",
    "LAT",
    "LONG",
    "UTM_ESTE",
    "UTM_NORTE",
    "ALTITUD",
    "FECHA",
    "Caudal_diario",
    "Unidad",
)

MONTHLY_HEADER = (
    "CODIGO ESTACION",
    "NOMBRE ESTACION",
    "COD_REGION",
    "REGION",
    "COMUNA",
    "LAT",
    "LONG",
    "UTM_ESTE",
    "UTM_NORTE",
    "ALTITUD",
    "Año",
    "Mes",
    "Caudal_Medio_mensual",
    "Unidad",
)


def _csv_line(fields: tuple[str, ...] | list[str]) -> str:
    return ",".join(fields) + "\n"


def _station_fields(
    station_id: str = "01001002",
    name: str = "RIO CAQUENA EN VERTEDERO",
    lat: str = "0175952 ",
    lon: str = "0691525 ",
) -> tuple[str, ...]:
    return (station_id, name, "15", "ARICA Y PARINACOTA", "PUTRE", lat, lon, "473068", "8010256", "4400")


def _write_text_zip(path: Path, member: str, payload: bytes) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, payload)
    return path


def _daily_zip(path: Path, rows: list[tuple[str, str, str]], *, station_fn=None) -> Path:
    lines = [_csv_line(DAILY_HEADER)]
    for station_id, fecha, value in rows:
        prefix = station_fn(station_id) if station_fn is not None else _station_fields(station_id=station_id)
        lines.append(_csv_line((*prefix, fecha, value, "m3/s")))
    return _write_text_zip(path, "caudal_diario_historico.txt", "".join(lines).encode("utf-8"))


def _monthly_zip(path: Path, rows: list[tuple[str, str, str, str]], *, station_fn=None) -> Path:
    lines = [_csv_line(MONTHLY_HEADER)]
    for station_id, year_str, month_str, value in rows:
        prefix = station_fn(station_id) if station_fn is not None else _station_fields(station_id=station_id)
        lines.append(_csv_line((*prefix, year_str, month_str, value, "m3/s")))
    return _write_text_zip(path, "caudal_medio_mensual_historico.txt", "".join(lines).encode("utf-8"))


def test_download_dga_history_uses_transfer_only_without_probe_and_sets_none_vintage(tmp_path: Path) -> None:
    from rivretrieve._internal.providers.cl_dga.bulk import (
        CL_DGA_DAILY_URL,
        CL_DGA_MONTHLY_URL,
        download_dga_history,
    )

    destination = tmp_path / "publisher-artifact.download"
    calls: list[tuple[str, Path]] = []

    def fail_probe(url: str) -> int:
        raise AssertionError(f"HEAD probe must never be called for DGA: {url}")

    def transfer(url: str, target: Path) -> None:
        calls.append((url, target))
        target.write_bytes(b"zip-bytes-" + url.encode("ascii"))

    downloaded = download_dga_history(
        destination,
        today=date(2026, 11, 19),
        probe=fail_probe,
        transfer=transfer,
        previous_source_vintage=None,
    )

    assert len(downloaded) == 2
    assert calls == [
        (CL_DGA_DAILY_URL, tmp_path / "publisher-artifact.download-caudal_diario_historico.zip"),
        (CL_DGA_MONTHLY_URL, tmp_path / "publisher-artifact.download-caudal_medio_mensual_historico.zip"),
    ]
    assert downloaded[0].url == CL_DGA_DAILY_URL
    assert downloaded[0].path == tmp_path / "publisher-artifact.download-caudal_diario_historico.zip"
    assert downloaded[0].source_vintage is None
    assert downloaded[1].url == CL_DGA_MONTHLY_URL
    assert downloaded[1].path == tmp_path / "publisher-artifact.download-caudal_medio_mensual_historico.zip"
    assert downloaded[1].source_vintage is None
    assert downloaded[0].path.is_file()
    assert downloaded[1].path.is_file()


def test_download_dga_history_refuses_existing_or_symlink_targets_and_cleans_partials(tmp_path: Path) -> None:
    from rivretrieve._internal.providers.cl_dga.bulk import (
        CL_DGA_DAILY_URL,
        CL_DGA_MONTHLY_URL,
        download_dga_history,
    )

    base = tmp_path / "publisher-artifact.download"
    base.write_bytes(b"existing-base")
    with pytest.raises(FileExistsError):
        download_dga_history(
            base,
            today=date(2026, 11, 19),
            probe=lambda _: 405,
            transfer=lambda _u, _p: None,
        )
    base.unlink()

    existing_monthly = tmp_path / "publisher-artifact.download-caudal_medio_mensual_historico.zip"
    existing_monthly.write_bytes(b"existing-monthly")
    transferred: list[str] = []
    with pytest.raises(FileExistsError):
        download_dga_history(
            base,
            today=date(2026, 11, 19),
            probe=lambda _: 405,
            transfer=lambda url, _p: transferred.append(url),
        )
    assert transferred == []
    existing_monthly.unlink()

    symlink_target = tmp_path / "publisher-artifact.download-caudal_diario_historico.zip"
    symlink_target.symlink_to(tmp_path / "dangling")
    with pytest.raises(FileExistsError):
        download_dga_history(
            base,
            today=date(2026, 11, 19),
            probe=lambda _: 405,
            transfer=lambda url, _p: transferred.append(url),
        )
    assert transferred == []
    symlink_target.unlink()

    def failing_second_transfer(url: str, target: Path) -> None:
        if url == CL_DGA_DAILY_URL:
            target.write_bytes(b"daily-ok")
            return
        assert url == CL_DGA_MONTHLY_URL
        target.write_bytes(b"partial-monthly")
        raise RuntimeError("network reset mid-download")

    with pytest.raises(RuntimeError, match="network reset"):
        download_dga_history(
            base,
            today=date(2026, 11, 19),
            probe=lambda _: 405,
            transfer=failing_second_transfer,
        )
    assert list(tmp_path.iterdir()) == []


def test_cl_dga_source_dispositions_and_compile_request_validation(tmp_path: Path) -> None:
    from rivretrieve._internal.providers.cl_dga.bulk import (
        CL_DGA_DAILY_URL,
        CL_DGA_MONTHLY_URL,
        CL_DGA_SOURCE_COLUMNS,
        CL_DGA_SOURCE_DISPOSITIONS,
        ClDgaCompileRequest,
    )
    from rivretrieve._internal.providers.registration import DownloadedBulkArtifact
    from rivretrieve._internal.store import Disposition, StoreRoot

    assert len(CL_DGA_SOURCE_COLUMNS) == 27
    assert len(CL_DGA_SOURCE_DISPOSITIONS) == 27
    by_col = {d.source_column: d for d in CL_DGA_SOURCE_DISPOSITIONS}
    assert sum(1 for d in CL_DGA_SOURCE_DISPOSITIONS if d.disposition is Disposition.RETAINED) == 23
    assert sum(1 for d in CL_DGA_SOURCE_DISPOSITIONS if d.disposition is Disposition.RECONSTRUCTIBLE) == 4
    assert sum(1 for d in CL_DGA_SOURCE_DISPOSITIONS if d.disposition is Disposition.DELIBERATELY_DISCARDED) == 0
    for col in (
        "caudal_diario.CODIGO ESTACION",
        "caudal_diario.Unidad",
        "caudal_medio_mensual.CODIGO ESTACION",
        "caudal_medio_mensual.Unidad",
    ):
        assert by_col[col].disposition is Disposition.RECONSTRUCTIBLE
        assert by_col[col].reconstruction_rule

    daily = _daily_zip(tmp_path / "caudal_diario_historico.zip", [("01001002", "01/01/2020", "1.5")])
    monthly = _monthly_zip(tmp_path / "caudal_medio_mensual_historico.zip", [("01001002", "2020", "1", "1.5")])
    dest = StoreRoot(tmp_path / "store")
    built_at = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)

    valid = ClDgaCompileRequest(
        publisher_artifacts=(
            DownloadedBulkArtifact(daily, CL_DGA_DAILY_URL, None),
            DownloadedBulkArtifact(monthly, CL_DGA_MONTHLY_URL, None),
        ),
        destination=dest,
        built_at=built_at,
        compiler_version="1",
    )
    assert len(valid.publisher_artifacts) == 2

    with pytest.raises(ValueError, match="2 publisher"):
        ClDgaCompileRequest(
            publisher_artifacts=(DownloadedBulkArtifact(daily, CL_DGA_DAILY_URL, None),),
            destination=dest,
            built_at=built_at,
            compiler_version="1",
        )

    with pytest.raises(ValueError, match="source_vintage"):
        ClDgaCompileRequest(
            publisher_artifacts=(
                DownloadedBulkArtifact(daily, CL_DGA_DAILY_URL, date(2026, 11, 19)),
                DownloadedBulkArtifact(monthly, CL_DGA_MONTHLY_URL, None),
            ),
            destination=dest,
            built_at=built_at,
            compiler_version="1",
        )

    with pytest.raises(ValueError, match="URL"):
        ClDgaCompileRequest(
            publisher_artifacts=(
                DownloadedBulkArtifact(monthly, CL_DGA_MONTHLY_URL, None),
                DownloadedBulkArtifact(daily, CL_DGA_DAILY_URL, None),
            ),
            destination=dest,
            built_at=built_at,
            compiler_version="1",
        )


def test_compile_cl_dga_preserves_duplicates_metadata_special_values_and_sorts_unsorted_stations(
    tmp_path: Path,
) -> None:
    from rivretrieve._internal.providers.cl_dga.bulk import (
        CL_DGA_DAILY_URL,
        CL_DGA_MONTHLY_URL,
        ClDgaCompileRequest,
        compile_cl_dga,
    )
    from rivretrieve._internal.providers.registration import DownloadedBulkArtifact
    from rivretrieve._internal.store import StoreRoot, ValueState
    from rivretrieve._internal.store.integrity import audit_store

    # Intentionally unsorted stations, leading zeros, duplicates on same day, blank, zero, sci notation, leap day.
    daily_rows = [
        ("02112007", "29/02/2024", "1.2E-4"),
        ("01001002", "01/01/2020", "0.0"),
        ("01001002", "01/01/2020", "3.25"),
        ("01001002", "02/01/2020", ""),
        ("02112007", "05/03/2020", "4.5"),
    ]
    monthly_rows = [
        ("02112007", "2024", "2", "0.0"),
        ("01001002", "2020", "1", "1.625"),
        ("01001002", "2020", "12", ""),
    ]
    daily = _daily_zip(tmp_path / "caudal_diario_historico.zip", daily_rows)
    monthly = _monthly_zip(tmp_path / "caudal_medio_mensual_historico.zip", monthly_rows)

    store_root = StoreRoot(tmp_path / "store")
    validated = compile_cl_dga(
        ClDgaCompileRequest(
            publisher_artifacts=(
                DownloadedBulkArtifact(daily, CL_DGA_DAILY_URL, None),
                DownloadedBulkArtifact(monthly, CL_DGA_MONTHLY_URL, None),
            ),
            destination=store_root,
            built_at=datetime(2026, 11, 19, 12, 0, tzinfo=UTC),
            compiler_version="1",
        )
    )
    assert validated.manifest.source_vintage is None
    assert not daily.exists() and not monthly.exists()
    audited = audit_store(store_root, validated.manifest.provider_id)
    assert audited.rows_checked == 8

    daily_2020 = pl.read_parquet(Path(store_root) / "product=discharge_daily" / "year=2020" / "part-0.parquet")
    assert daily_2020["station_id"].to_list() == ["01001002", "01001002", "01001002", "02112007"]
    assert daily_2020["time_zone"].unique().to_list() == ["unknown"]
    assert daily_2020["value"].to_list() == [0.0, 3.25, None, 4.5]
    assert daily_2020["value_state"].to_list() == [
        ValueState.PUBLISHED_VALUE.value,
        ValueState.PUBLISHED_VALUE.value,
        ValueState.PUBLISHED_BLANK.value,
        ValueState.PUBLISHED_VALUE.value,
    ]
    assert daily_2020["caudal_diario.LAT"].unique().to_list() == ["0175952 "]
    assert daily_2020["caudal_diario.FECHA"].to_list() == ["01/01/2020", "01/01/2020", "02/01/2020", "05/03/2020"]
    assert daily_2020["caudal_diario.Caudal_diario"].to_list() == ["0.0", "3.25", "", "4.5"]
    assert daily_2020["caudal_medio_mensual.Año"].null_count() == 4

    daily_2024 = pl.read_parquet(Path(store_root) / "product=discharge_daily" / "year=2024" / "part-0.parquet")
    assert daily_2024["time"].to_list() == [datetime(2024, 2, 29)]
    assert daily_2024["value"].to_list() == [pytest.approx(1.2e-4)]

    monthly_2020 = pl.read_parquet(Path(store_root) / "product=discharge_monthly_mean" / "year=2020" / "part-0.parquet")
    assert monthly_2020["time"].to_list() == [datetime(2020, 1, 1), datetime(2020, 12, 1)]
    assert monthly_2020["caudal_medio_mensual.Mes"].to_list() == ["1", "12"]
    assert monthly_2020["caudal_medio_mensual.Año"].to_list() == ["2020", "2020"]
    assert monthly_2020["caudal_diario.FECHA"].null_count() == 2


@pytest.mark.parametrize(
    "case",
    [
        "wrong_member",
        "extra_member",
        "regional_15_monthly",
        "utf8_bom",
        "crlf",
        "invalid_utf8",
        "header_only",
        "ragged_row",
        "bad_station_code",
        "bad_unit",
        "invalid_daily_date",
        "padded_month",
        "negative_value",
        "nan_value",
        "inf_value",
        "spaced_value",
        "malformed_quote",
        "nul_byte",
        "plus_sign_value",
    ],
)
def test_compile_cl_dga_rejects_malformed_archives_and_rows(tmp_path: Path, case: str) -> None:
    from rivretrieve._internal.providers.cl_dga.bulk import (
        CL_DGA_DAILY_URL,
        CL_DGA_MONTHLY_URL,
        ClDgaCompileRequest,
        compile_cl_dga,
    )
    from rivretrieve._internal.providers.registration import DownloadedBulkArtifact
    from rivretrieve._internal.store import StoreRoot

    daily = _daily_zip(tmp_path / "caudal_diario_historico.zip", [("01001002", "01/01/2020", "1.0")])
    monthly = _monthly_zip(tmp_path / "caudal_medio_mensual_historico.zip", [("01001002", "2020", "1", "1.0")])

    if case == "wrong_member":
        _write_text_zip(
            daily,
            "other.txt",
            (_csv_line(DAILY_HEADER) + _csv_line((*_station_fields(), "01/01/2020", "1.0", "m3/s"))).encode(),
        )
    elif case == "extra_member":
        with zipfile.ZipFile(daily, "w") as archive:
            archive.writestr(
                "caudal_diario_historico.txt",
                (_csv_line(DAILY_HEADER) + _csv_line((*_station_fields(), "01/01/2020", "1.0", "m3/s"))).encode(),
            )
            archive.writestr("extra.txt", b"x")
    elif case == "regional_15_monthly":
        header_15 = (*MONTHLY_HEADER[:10], "FECHA", *MONTHLY_HEADER[10:])
        _write_text_zip(
            monthly,
            "caudal_medio_mensual_15_historico.txt",
            (_csv_line(header_15) + _csv_line((*_station_fields(), "", "2020", "1", "1.0", "m3/s"))).encode(),
        )
    elif case == "utf8_bom":
        _write_text_zip(
            daily,
            "caudal_diario_historico.txt",
            b"\xef\xbb\xbf"
            + (_csv_line(DAILY_HEADER) + _csv_line((*_station_fields(), "01/01/2020", "1.0", "m3/s"))).encode(),
        )
    elif case == "crlf":
        _write_text_zip(
            daily,
            "caudal_diario_historico.txt",
            (_csv_line(DAILY_HEADER) + _csv_line((*_station_fields(), "01/01/2020", "1.0", "m3/s")))
            .replace("\n", "\r\n")
            .encode(),
        )
    elif case == "invalid_utf8":
        _write_text_zip(
            daily,
            "caudal_diario_historico.txt",
            _csv_line(DAILY_HEADER).encode()
            + b"\xff,"
            + _csv_line((*_station_fields()[1:], "01/01/2020", "1.0", "m3/s")).encode(),
        )
    elif case == "header_only":
        _write_text_zip(daily, "caudal_diario_historico.txt", _csv_line(DAILY_HEADER).encode())
    elif case == "ragged_row":
        _write_text_zip(
            daily, "caudal_diario_historico.txt", (_csv_line(DAILY_HEADER) + "01001002,only_two_cols\n").encode()
        )
    elif case == "bad_station_code":
        _daily_zip(daily, [("1001002", "01/01/2020", "1.0")])
    elif case == "bad_unit":
        _write_text_zip(
            daily,
            "caudal_diario_historico.txt",
            (_csv_line(DAILY_HEADER) + _csv_line((*_station_fields(), "01/01/2020", "1.0", "l/s"))).encode(),
        )
    elif case == "invalid_daily_date":
        _daily_zip(daily, [("01001002", "29/02/2025", "1.0")])
    elif case == "padded_month":
        _monthly_zip(monthly, [("01001002", "2020", "01", "1.0")])
    elif case == "negative_value":
        _daily_zip(daily, [("01001002", "01/01/2020", "-0.1")])
    elif case == "nan_value":
        _daily_zip(daily, [("01001002", "01/01/2020", "NaN")])
    elif case == "inf_value":
        _daily_zip(daily, [("01001002", "01/01/2020", "inf")])
    elif case == "spaced_value":
        _daily_zip(daily, [("01001002", "01/01/2020", " 1.0")])
    elif case == "malformed_quote":
        fields = list(_station_fields())
        fields[1] = '"RIO"X'
        _write_text_zip(
            daily,
            "caudal_diario_historico.txt",
            (_csv_line(DAILY_HEADER) + _csv_line((*fields, "01/01/2020", "1.0", "m3/s"))).encode(),
        )
    elif case == "nul_byte":
        fields = list(_station_fields())
        fields[1] = "RIO\x00CAQUENA"
        _write_text_zip(
            daily,
            "caudal_diario_historico.txt",
            (_csv_line(DAILY_HEADER) + _csv_line((*fields, "01/01/2020", "1.0", "m3/s"))).encode(),
        )
    elif case == "plus_sign_value":
        _daily_zip(daily, [("01001002", "01/01/2020", "+1.0")])

    with pytest.raises((ValueError, zipfile.BadZipFile)):
        compile_cl_dga(
            ClDgaCompileRequest(
                publisher_artifacts=(
                    DownloadedBulkArtifact(daily, CL_DGA_DAILY_URL, None),
                    DownloadedBulkArtifact(monthly, CL_DGA_MONTHLY_URL, None),
                ),
                destination=StoreRoot(tmp_path / "store"),
                built_at=datetime(2026, 11, 19, 12, 0, tzinfo=UTC),
                compiler_version="1",
            )
        )


def test_compile_cl_dga_rejects_insufficient_disk_space(tmp_path: Path) -> None:
    from rivretrieve._internal.providers.cl_dga.bulk import (
        CL_DGA_DAILY_URL,
        CL_DGA_MONTHLY_URL,
        ClDgaCompileRequest,
        compile_cl_dga,
    )
    from rivretrieve._internal.providers.registration import DownloadedBulkArtifact
    from rivretrieve._internal.store import StoreRoot
    from rivretrieve._internal.store.resources import InsufficientPreparationSpaceError

    daily = _daily_zip(tmp_path / "caudal_diario_historico.zip", [("01001002", "01/01/2020", "1.0")])
    monthly = _monthly_zip(tmp_path / "caudal_medio_mensual_historico.zip", [("01001002", "2020", "1", "1.0")])

    with pytest.raises(InsufficientPreparationSpaceError):
        compile_cl_dga(
            ClDgaCompileRequest(
                publisher_artifacts=(
                    DownloadedBulkArtifact(daily, CL_DGA_DAILY_URL, None),
                    DownloadedBulkArtifact(monthly, CL_DGA_MONTHLY_URL, None),
                ),
                destination=StoreRoot(tmp_path / "store"),
                built_at=datetime(2026, 11, 19, 12, 0, tzinfo=UTC),
                compiler_version="1",
                free_space_probe=lambda _path: 10,
            )
        )


def test_cl_dga_declaration_and_multi_batch_unsorted_replay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from rivretrieve._internal.engine import Daily, DailyLabelTime, DayDefinition, UnknownTemporalSupport
    from rivretrieve._internal.primitives import ProductId
    from rivretrieve._internal.providers.cl_dga import bulk as bulk_mod
    from rivretrieve._internal.providers.cl_dga.declaration import declaration
    from rivretrieve._internal.providers.registration import BulkStore, DownloadedBulkArtifact
    from rivretrieve._internal.store import StoreRoot
    from rivretrieve._internal.store.integrity import audit_store

    assert isinstance(declaration.observations, BulkStore)
    assert declaration.required_credentials == ()
    assert declaration.observations.config.products[ProductId("discharge_daily")].semantics == Daily(
        DayDefinition("unknown"),
        DailyLabelTime("00:00"),
    )
    assert declaration.observations.config.products[ProductId("discharge_monthly_mean")].semantics == (
        UnknownTemporalSupport()
    )

    monkeypatch.setattr(bulk_mod, "CL_DGA_ROWS_PER_BATCH", 3)
    daily_rows = [
        ("03430001", "01/01/2024", "1.0"),
        ("01001002", "02/01/2024", "2.0"),
        ("02112007", "03/01/2024", "3.0"),
        ("01001002", "01/01/2024", "4.0"),
        ("01001002", "01/01/2024", "5.0"),
        ("03430001", "04/01/2024", "6.0"),
        ("02112007", "05/01/2024", "7.0"),
    ]
    monthly_rows = [
        ("03430001", "2024", "1", "1.5"),
        ("01001002", "2024", "1", "2.5"),
        ("02112007", "2024", "1", "3.5"),
        ("01001002", "2024", "2", "4.5"),
    ]
    daily = _daily_zip(tmp_path / "caudal_diario_historico.zip", daily_rows)
    monthly = _monthly_zip(tmp_path / "caudal_medio_mensual_historico.zip", monthly_rows)

    store_root = StoreRoot(tmp_path / "store")
    validated = bulk_mod.compile_cl_dga(
        bulk_mod.ClDgaCompileRequest(
            publisher_artifacts=(
                DownloadedBulkArtifact(daily, bulk_mod.CL_DGA_DAILY_URL, None),
                DownloadedBulkArtifact(monthly, bulk_mod.CL_DGA_MONTHLY_URL, None),
            ),
            destination=store_root,
            built_at=datetime(2026, 11, 19, 12, 0, tzinfo=UTC),
            compiler_version="1",
        )
    )
    assert audit_store(store_root, validated.manifest.provider_id).rows_checked == 11
    part = pl.read_parquet(Path(store_root) / "product=discharge_daily" / "year=2024" / "part-0.parquet")
    assert part["station_id"].to_list() == [
        "01001002",
        "01001002",
        "01001002",
        "02112007",
        "02112007",
        "03430001",
        "03430001",
    ]
    assert part.filter(pl.col("station_id") == "01001002")["value"].to_list() == [2.0, 4.0, 5.0]
    assert not list(tmp_path.glob(".cl-dga-spill-*"))


def test_cl_dga_end_to_end_public_api_windows_refresh_and_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from io import BytesIO
    from types import SimpleNamespace

    import rivretrieve as rr
    from rivretrieve._internal import bulk as bulk_shared
    from rivretrieve._internal import discovery
    from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
    from rivretrieve._internal.issues import FatalContractError
    from rivretrieve._internal.observations import ReceiptAuthorship, StoreExcerptReceipt
    from rivretrieve._internal.providers.cl_dga.bulk import CL_DGA_DAILY_URL, CL_DGA_MONTHLY_URL
    from rivretrieve._internal.providers.cl_dga.declaration import declaration
    from rivretrieve._internal.source_series import ClippingAxis, OutcomeStatus
    from rivretrieve._internal.store import StorePresence

    packaged = load_packaged_catalogue_artifact(declaration.catalogue, on_issue="raise")
    assert str(packaged.provider_info["bulk_observations"]).startswith("true:")

    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))

    v1_daily = _daily_zip(
        tmp_path / "src_v1_d.zip",
        [
            ("01001002", "31/12/2023", "1.1"),
            ("01001002", "01/01/2024", "1.2"),
            ("01001002", "29/02/2024", "1.2E-4"),
            ("01001002", "29/02/2024", "0.0"),
            ("01001002", "01/03/2024", ""),
        ],
    ).read_bytes()
    v1_monthly = _monthly_zip(
        tmp_path / "src_v1_m.zip",
        [
            ("01001002", "2023", "12", "1.1"),
            ("01001002", "2024", "1", "2.1"),
            ("01001002", "2024", "2", "3.1"),
            ("01001002", "2024", "3", "4.1"),
        ],
    ).read_bytes()
    v2_daily = _daily_zip(
        tmp_path / "src_v2_d.zip",
        [("02112007", "05/01/2024", "9.5")],
    ).read_bytes()
    v2_monthly = _monthly_zip(
        tmp_path / "src_v2_m.zip",
        [("02112007", "2024", "1", "8.5")],
    ).read_bytes()

    payloads = {CL_DGA_DAILY_URL: v1_daily, CL_DGA_MONTHLY_URL: v1_monthly}
    fail_http = False
    http_methods: list[str] = []

    class FakeHttpClient:
        def send(self, request):
            http_methods.append(str(request.method))
            assert str(request.method).upper() == "GET"
            if fail_http:
                return SimpleNamespace(status_code=503, content=b"unavailable")
            return SimpleNamespace(status_code=200, content=payloads[request.url])

    monkeypatch.setattr(discovery, "HttpClient", FakeHttpClient)
    monkeypatch.setattr(bulk_shared, "HttpClient", FakeHttpClient)

    rr.download("cl_dga")
    assert set(http_methods) == {"GET"}
    status = rr.cache_status("cl_dga")
    assert status.presence is StorePresence.PRESENT
    assert status.source_vintage is None
    assert rr.audit_cache("cl_dga").rows_checked == 9

    daily_sel = rr.find(provider="cl_dga", station="01001002", frequency="daily")
    assert len(daily_sel.series) == 1

    # Daily year boundary + leap day + duplicates + published blank.
    daily_res = rr.fetch(daily_sel, start="2023-12-31", end="2024-03-01", receipts=True, on_issue="raise")
    assert daily_res.data["time"].to_list() == [
        datetime(2023, 12, 31),
        datetime(2024, 1, 1),
        datetime(2024, 2, 29),
        datetime(2024, 2, 29),
        datetime(2024, 3, 1),
    ]
    assert daily_res.data["value"].to_list() == [1.1, 1.2, 0.0, pytest.approx(1.2e-4), None]
    assert daily_res.provenance.source_vintage is None
    (receipt,) = daily_res.receipts.entries
    assert isinstance(receipt, StoreExcerptReceipt)
    assert receipt.authorship is ReceiptAuthorship.STORE_EXCERPT
    assert receipt.source_vintage is None
    excerpt = pl.read_parquet(BytesIO(receipt.content))
    assert excerpt["value"].to_list() == [1.1, 1.2, pytest.approx(1.2e-4), 0.0, None]
    assert excerpt["value_state"].to_list() == ["published_value"] * 4 + ["published_blank"]
    assert excerpt["caudal_diario.LAT"].unique().to_list() == ["0175952 "]

    # Bundle export/import round-trip preserves unknown source_vintage and retained data.
    restored = rr.from_bundle(rr.to_bundle(daily_res))
    assert restored.data.equals(daily_res.data)
    assert restored.provenance.source_vintage is None
    restored_receipt = restored.receipts.entries[0]
    assert isinstance(restored_receipt, StoreExcerptReceipt)
    assert restored_receipt.source_vintage is None

    # Monthly CALENDAR_MONTH mid-month and year-boundary windows.
    monthly_sel = rr.find(provider="cl_dga", station="01001002", frequency="monthly")
    assert len(monthly_sel.series) == 1
    assert monthly_sel.series[0].facts[0].clipping_axis is ClippingAxis.CALENDAR_MONTH
    mid_month = rr.fetch(monthly_sel, start="2024-02-10", end="2024-02-20", on_issue="raise")
    assert mid_month.data["time"].to_list() == [datetime(2024, 2, 1)]
    assert mid_month.data["value"].to_list() == [3.1]

    ym_boundary = rr.fetch(monthly_sel, start="2023-12-15", end="2024-01-10", on_issue="raise")
    assert ym_boundary.data["time"].to_list() == [datetime(2023, 12, 1), datetime(2024, 1, 1)]
    assert ym_boundary.data["value"].to_list() == [1.1, 2.1]

    # Empty date window returns OutcomeStatus.EMPTY.
    empty_res = rr.fetch(daily_sel, start="1950-01-01", end="1950-01-31", on_issue="ignore")
    assert empty_res.data.is_empty()
    assert empty_res.outcomes[0].status == OutcomeStatus.EMPTY

    # Failed refresh preserves the prior certified store intact.
    fail_http = True
    with pytest.raises(FatalContractError, match="HTTP 503"):
        rr.download("cl_dga")
    still_valid = rr.fetch(daily_sel, start="2023-12-31", end="2023-12-31", on_issue="raise")
    assert still_valid.data["value"].to_list() == [1.1]

    # Valid refresh atomically replaces the store including station removals.
    fail_http = False
    payloads = {CL_DGA_DAILY_URL: v2_daily, CL_DGA_MONTHLY_URL: v2_monthly}
    rr.download("cl_dga")
    assert rr.audit_cache("cl_dga").rows_checked == 2
    removed = rr.fetch(daily_sel, start="2024-01-01", end="2024-03-01", on_issue="ignore")
    assert removed.data.is_empty()
    assert removed.outcomes[0].status is OutcomeStatus.UNRESOLVED
    new_sel = rr.find(provider="cl_dga", station="02112007", frequency="daily")
    assert rr.fetch(new_sel, start="2024-01-05", end="2024-01-05", on_issue="raise").data["value"].to_list() == [9.5]

    rr.clear_cache("cl_dga")
    assert rr.cache_status("cl_dga").presence is StorePresence.ABSENT


def test_decode_cl_dga_abandoned_unsorted_sort_closes_sqlite_before_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import gc
    import sqlite3
    import tempfile

    from rivretrieve._internal.providers.cl_dga import bulk as bulk_mod

    monkeypatch.setattr(bulk_mod, "CL_DGA_ROWS_PER_BATCH", 1)
    daily = _daily_zip(
        tmp_path / "caudal_diario_historico.zip",
        [("02112007", "01/01/2024", "1.0"), ("01001002", "01/01/2024", "2.0")],
    )
    monthly = _monthly_zip(
        tmp_path / "caudal_medio_mensual_historico.zip",
        [("01001002", "2024", "1", "3.0")],
    )

    events: list[str] = []
    real_connect = sqlite3.connect
    real_cleanup = tempfile.TemporaryDirectory.cleanup

    class TrackedConnection:
        def __init__(self, conn: sqlite3.Connection) -> None:
            self._conn = conn

        def __getattr__(self, name: str):
            return getattr(self._conn, name)

        def close(self) -> None:
            events.append("sqlite_close")
            self._conn.close()

    def tracked_connect(*args, **kwargs):
        return TrackedConnection(real_connect(*args, **kwargs))

    def tracked_cleanup(self: tempfile.TemporaryDirectory[str]) -> None:
        if Path(self.name).name.startswith(".cl-dga-spill-"):
            events.append("spill_cleanup")
        real_cleanup(self)

    monkeypatch.setattr(bulk_mod.sqlite3, "connect", tracked_connect)
    monkeypatch.setattr(tempfile.TemporaryDirectory, "cleanup", tracked_cleanup)

    workspace = tmp_path / "work"
    workspace.mkdir()
    stream = bulk_mod.decode_cl_dga_batches((daily, monthly), workspace=workspace)
    iterator = iter(stream.batches)
    next(iterator)
    assert events == []
    del iterator, stream
    gc.collect()

    assert events == ["sqlite_close", "spill_cleanup"]
    assert not list(workspace.glob(".cl-dga-spill-*"))
