from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import polars.testing as pl_testing
import pytest

from rivretrieve._internal.catalogues.native import NativeTable, RetrievedAt, read_native_table
from rivretrieve._internal.engine import WithIssues
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.za_dws import generate_catalogue as generator

_TEST_DATA_DIR = Path(__file__).parent / "test_data"
_METADATA_FIXTURE = _TEST_DATA_DIR / "za_dws_metadata.json"
_NATIVE_TABLE = Path(generator.__file__).parent / "catalogue" / "native.parquet"
ATTESTED_RETRIEVED_AT = RetrievedAt(datetime(2026, 8, 2, 18, 47, 1, tzinfo=UTC))
NATIVE_CONTENT_SHA256 = "7949369cf573d675cf8cb2374fa172038e10e492299572df442834d6a08e40fc"


def _pdf_bytes(lines: list[str]) -> bytes:
    def escaped(value: str) -> str:
        return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    commands = ["BT /F1 8 Tf 36 760 Td"]
    for index, line in enumerate(lines):
        if index:
            commands.append("0 -10 Td")
        commands.append(f"({escaped(line)}) Tj")
    commands.append("ET")
    stream = "\n".join(commands).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    payload = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(payload))
        payload.extend(f"{number} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(payload)
    payload.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        payload.extend(f"{offset:010d} 00000 n \n".encode())
    payload.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(payload)


def _index_bytes(filenames: tuple[str, ...] = generator.EXPECTED_PDF_FILENAMES) -> bytes:
    return "".join(f'<a href="dwafapp2_wma/{name}">{name}</a>' for name in filenames).encode()


def _captures(lines: list[str]) -> dict[str, tuple[bytes, RetrievedAt]]:
    return {
        filename: (_pdf_bytes(lines if index == 0 else []), ATTESTED_RETRIEVED_AT)
        for index, filename in enumerate(generator.EXPECTED_PDF_FILENAMES)
    }


def test_station_pattern_accepts_blank_drainage_region() -> None:
    line = "A8H017 Canal @ Scuidtsdrift 22:42:08 30:06:19 0"
    assert generator._STATION_PATTERN.fullmatch(line) is not None


def test_station_pattern_accepts_trailing_letter_suffix() -> None:
    line = "A2H090Q Hennops River @ Van Riebeeck Nat Res 25:53:08 28:18:10 A21A 451"
    assert generator._STATION_PATTERN.fullmatch(line) is not None


def test_station_pattern_accepts_component_suffix() -> None:
    line = "B6H018M01 Pipeline from Blyde Dam 24:32:05 30:47:47 0"
    assert generator._STATION_PATTERN.fullmatch(line) is not None


def test_parser_preserves_three_regression_rows() -> None:
    lines = [
        "A8H017 Canal @ Scuidtsdrift 22:42:08 30:06:19 0",
        "A2H090Q Hennops River @ Van Riebeeck Nat Res 25:53:08 28:18:10 A21A 451",
        "B6H018M01 Pipeline from Blyde Dam 24:32:05 30:47:47 0",
    ]
    outcome = generator._parse_pdf_native_rows(_pdf_bytes(lines), "WMA1_Limpopo-Olifants_River.pdf")
    assert outcome.issues == ()
    assert {row["Station"] for row in outcome.value} == {"A8H017", "A2H090Q", "B6H018M01"}


def test_parser_reports_only_coordinate_bearing_malformed_row() -> None:
    lines = [
        "A9H031 39",
        "B3H026 48",
        "C1H047 7",
        "K5H003 63",
        "A1H001 (continued)",
        "A1H001 Broken row 25:26:44 25:51:14 NOT-VALID",
        "A1H002 Sound row 25:26:44 25:51:14 A10A 1",
    ]
    outcome = generator._parse_pdf_native_rows(_pdf_bytes(lines), "sample.pdf")
    assert [row["Station"] for row in outcome.value] == ["A1H002"]
    assert len(outcome.issues) == 1
    issue = outcome.issues[0]
    assert issue.code == "pdf-row-parse"
    assert issue.severity == "error"
    assert issue.provider_id == "za_dws"
    assert issue.details == {"filename": "sample.pdf", "line": lines[5]}
    assert issue.message == f"za_dws: coordinate-bearing station row did not match in sample.pdf: {lines[5]}"


def test_invalid_pdf_is_an_issue() -> None:
    outcome = generator._parse_pdf_native_rows(b"not pdf", "broken.pdf")
    assert outcome.value == []
    assert outcome.issues[0].code == "invalid-pdf"
    assert outcome.issues[0].details["filename"] == "broken.pdf"


def test_refresh_rejects_incomplete_eight_pdf_input() -> None:
    outcome = generator.refresh_native_table_from_captures(_index_bytes(), {})
    assert outcome.value.data.schema == generator.NATIVE_SCHEMA
    assert outcome.issues[0].code == "incomplete-pdf-input"


def test_refresh_reports_below_minimum_with_exact_details(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [f"A{i // 1000 % 10}H{i % 1000:03d} Station {i} 25:00:00 28:00:00 A10A 0" for i in range(2863)]
    monkeypatch.setattr(generator, "MIN_REFRESH_STATIONS", 2905)
    outcome = generator.refresh_native_table_from_captures(_index_bytes(), _captures(rows))
    assert outcome.issues[0].code == "below-minimum"
    assert outcome.issues[0].details == {"actual": 2863, "minimum": 2905}


def test_refresh_rejects_duplicate_station(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(generator, "MIN_REFRESH_STATIONS", 1)
    line = "A1H001 Station 25:00:00 28:00:00 A10A 0"
    captures = _captures([line])
    second = generator.EXPECTED_PDF_FILENAMES[1]
    captures[second] = (_pdf_bytes([line]), ATTESTED_RETRIEVED_AT)
    outcome = generator.refresh_native_table_from_captures(_index_bytes(), captures)
    assert outcome.issues[0].code == "duplicate-station"
    assert outcome.issues[0].details == {"station": "A1H001"}


def test_refresh_is_deterministic_across_mapping_and_index_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(generator, "MIN_REFRESH_STATIONS", 1)
    lines = [
        "A2H001 Second 25:00:00 28:00:00 A10A 2",
        "A1H001 First 25:00:00 28:00:00 A10A 1",
    ]
    captures = _captures(lines)
    reversed_captures = dict(reversed(tuple(captures.items())))
    first = generator.refresh_native_table_from_captures(_index_bytes(), captures)
    second = generator.refresh_native_table_from_captures(
        _index_bytes(tuple(reversed(generator.EXPECTED_PDF_FILENAMES))), reversed_captures
    )
    assert first.issues == second.issues == ()
    assert first.value.data["Station"].to_list() == ["A1H001", "A2H001"]
    pl_testing.assert_frame_equal(first.value.data, second.value.data, check_exact=True)


def test_fixture_refresh_has_no_issues() -> None:
    assert (
        generator.refresh_native_table_from_fixture(_METADATA_FIXTURE, retrieved_at=ATTESTED_RETRIEVED_AT).issues == ()
    )


def test_fixture_refresh_height() -> None:
    assert (
        generator.refresh_native_table_from_fixture(
            _METADATA_FIXTURE, retrieved_at=ATTESTED_RETRIEVED_AT
        ).value.data.height
        == 3
    )


def test_fixture_refresh_exact_schema() -> None:
    outcome = generator.refresh_native_table_from_fixture(_METADATA_FIXTURE, retrieved_at=ATTESTED_RETRIEVED_AT)
    assert outcome.value.data.schema == generator.NATIVE_SCHEMA


def test_fixture_refresh_a1h001_triple() -> None:
    data = generator.refresh_native_table_from_fixture(_METADATA_FIXTURE, retrieved_at=ATTESTED_RETRIEVED_AT).value.data
    assert data.filter(pl.col("Station") == "A1H001").select(
        "Station", "Latitude (dd:mm:ss)", "Longitude (dd:mm:ss)"
    ).row(0) == ("A1H001", "25:26:44", "25:51:14")


def test_fixture_refresh_equals_committed_subset() -> None:
    actual = generator.refresh_native_table_from_fixture(
        _METADATA_FIXTURE, retrieved_at=ATTESTED_RETRIEVED_AT
    ).value.data
    expected = (
        read_native_table(_NATIVE_TABLE)
        .data.filter(pl.col("Station").is_in(["A1H001", "A2H090Q", "A8H017"]))
        .sort("Station")
    )
    pl_testing.assert_frame_equal(actual, expected, check_exact=True)


def test_committed_native_table_contract() -> None:
    data = read_native_table(_NATIVE_TABLE).data
    assert data.schema == generator.NATIVE_SCHEMA
    assert data.height == data["Station"].n_unique() == 2905
    assert data["Station"].to_list() == sorted(data["Station"].to_list())
    assert generator.native_table_content_sha256(NativeTable(data)) == NATIVE_CONTENT_SHA256


def test_committed_native_table_pdf_counts_and_instants() -> None:
    data = read_native_table(_NATIVE_TABLE).data
    assert dict(data.group_by("WMA source-file identity").len().iter_rows()) == dict(
        zip(generator.EXPECTED_PDF_FILENAMES, [544, 210, 417, 702, 406, 567, 19, 40], strict=True)
    )
    expected = {
        filename: datetime(2026, 8, 2, 18, 47, second, tzinfo=UTC)
        for filename, second in zip(generator.EXPECTED_PDF_FILENAMES, [1, 2, 3, 4, 5, 6, 7, 9], strict=True)
    }
    assert dict(data.select("WMA source-file identity", "retrieved_at").unique().iter_rows()) == expected


def test_committed_native_table_defect_decomposition() -> None:
    data = read_native_table(_NATIVE_TABLE).data
    suffix = {"A2H090Q", "B6H018M01"}
    assert set(data.filter(pl.col("Station").is_in(suffix))["Station"]) == suffix
    assert data.filter(pl.col("Drainage Region").is_null() & ~pl.col("Station").is_in(suffix)).height == 40
    assert data["Drainage Region"].null_count() == 41


@pytest.mark.parametrize(
    ("station", "expected"),
    [
        ("A8H017", ("Canal @ Scuidtsdrift", "22:42:08", "30:06:19", None, "0")),
        ("A2H090Q", ("Hennops River @ Van Riebeeck Nat Res", "25:53:08", "28:18:10", "A21A", "451")),
        ("B6H018M01", ("Pipeline from Blyde Dam", "24:32:05", "30:47:47", None, "0")),
    ],
)
def test_committed_native_representative_rows(station: str, expected: tuple[object, ...]) -> None:
    data = read_native_table(_NATIVE_TABLE).data
    row = data.filter(pl.col("Station") == station).select(
        "Description", "Latitude (dd:mm:ss)", "Longitude (dd:mm:ss)", "Drainage Region", "Catchment Area km**2"
    )
    assert row.row(0) == expected
    assert (
        data.filter(pl.col("Station") == station)["WMA source-file identity"][0] == generator.EXPECTED_PDF_FILENAMES[0]
    )


def test_committed_native_preserves_dms_sixty_tokens() -> None:
    data = read_native_table(_NATIVE_TABLE).data
    assert data.select(pl.col("Latitude (dd:mm:ss)").str.ends_with(":60").sum()).item() == 20
    assert data.select(pl.col("Longitude (dd:mm:ss)").str.ends_with(":60").sum()).item() == 24
    assert data.filter(pl.col("Station") == "B7H000")["Longitude (dd:mm:ss)"][0] == "31:49:60"


def test_live_index_request_failure_has_exact_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_url: str) -> tuple[bytes, int]:
        raise OSError("offline")

    monkeypatch.setattr(generator, "_request_bytes", fail)
    issue = generator.refresh_native_table_from_live(retrieved_at=ATTESTED_RETRIEVED_AT).issues[0]
    assert issue.model_dump() == {
        "severity": "error",
        "code": "index-request-failed",
        "message": f"za_dws: index request failed for {generator.CATALOGUE_URL}",
        "details": {"url": generator.CATALOGUE_URL, "error": "offline"},
        "provider_id": "za_dws",
    }


def test_live_index_http_403_is_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(generator, "_request_bytes", lambda _url: (b"", 403))
    issue = generator.refresh_native_table_from_live(retrieved_at=ATTESTED_RETRIEVED_AT).issues[0]
    assert issue.code == "index-http-error"
    assert issue.details == {"url": generator.CATALOGUE_URL, "status": 403}


@pytest.mark.parametrize(("status", "code"), [(None, "pdf-request-failed"), (403, "pdf-http-error")])
def test_live_pdf_failure_names_url(monkeypatch: pytest.MonkeyPatch, status: int | None, code: str) -> None:
    pdf_url = generator.CATALOGUE_BASE + "dwafapp2_wma/" + generator.EXPECTED_PDF_FILENAMES[0]

    def request(url: str) -> tuple[bytes, int]:
        if url == generator.CATALOGUE_URL:
            return _index_bytes(), 200
        if status is None:
            raise OSError("offline")
        return b"", status

    monkeypatch.setattr(generator, "_request_bytes", request)
    issue = generator.refresh_native_table_from_live(retrieved_at=ATTESTED_RETRIEVED_AT).issues[0]
    assert issue.code == code
    assert issue.details["url"] == pdf_url
    assert pdf_url in issue.message


def test_cli_error_issues_do_not_write(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    output = tmp_path / "native.parquet"
    issue = generator._issue(generator.CatalogueIssueCode.BELOW_MINIMUM, "low", {"actual": 0, "minimum": 2905})
    monkeypatch.setattr(
        generator,
        "refresh_native_table_from_fixture",
        lambda *_args, **_kwargs: WithIssues(value=generator._empty_native_table(), issues=(issue,)),
    )
    with pytest.raises(FatalContractError) as caught:
        generator.main(
            [
                "--fixture",
                str(_METADATA_FIXTURE),
                "--retrieved-at",
                "2026-08-02T18:47:01+00:00",
                "--native-out",
                str(output),
            ]
        )
    assert caught.value.issues == (issue,)
    assert not output.exists()


def test_cli_success_writes_native_table(tmp_path: Path) -> None:
    output = tmp_path / "native.parquet"
    assert (
        generator.main(
            [
                "--fixture",
                str(_METADATA_FIXTURE),
                "--retrieved-at",
                "2026-08-02T18:47:01+00:00",
                "--native-out",
                str(output),
            ]
        )
        == 0
    )
    assert output.is_file()
    assert read_native_table(output).data.height == 3


def test_cli_cross_mode_conflict_does_not_write(tmp_path: Path) -> None:
    output = tmp_path / "native.parquet"
    with pytest.raises(FatalContractError, match="native-source-mode-conflict"):
        generator.main(
            [
                "--fixture",
                str(_METADATA_FIXTURE),
                "--live",
                "--retrieved-at",
                "2026-08-02T18:47:01+00:00",
                "--native-out",
                str(output),
            ]
        )
    assert not output.exists()


def _synthetic_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, list[dict[str, object]]]:
    archive = tmp_path / "archive"
    archive.mkdir()
    entries: list[dict[str, object]] = []
    for expected in generator._EXPECTED_BINDINGS:
        filename = str(expected["file"])
        payload = _index_bytes() if filename == "HyCatalogue.aspx" else _pdf_bytes([])
        (archive / filename).write_bytes(payload)
        entry = dict(expected)
        entry["bytes"] = len(payload)
        entry["sha256"] = hashlib.sha256(payload).hexdigest()
        entries.append(entry)
    monkeypatch.setattr(generator, "_EXPECTED_BINDINGS", tuple(dict(entry) for entry in entries))
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(entries), encoding="utf-8")
    return archive, manifest, entries


@pytest.mark.parametrize(
    ("field", "value", "token"),
    [
        ("file", "wrong.pdf", "manifest-filename"),
        ("archived_url", "wrong", "manifest-archived-url"),
        ("origin_url", "wrong", "manifest-origin-url"),
        ("wayback_timestamp", "wrong", "manifest-wayback-timestamp"),
        ("http_status", 403, "manifest-http-status"),
        ("retrieved_at", "2026-08-02T18:47:08Z", "manifest-retrieved-at"),
    ],
)
def test_manifest_exact_binding_guards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: object, token: str
) -> None:
    archive, manifest, entries = _synthetic_archive(tmp_path, monkeypatch)
    entries[0][field] = value
    manifest.write_text(json.dumps(entries), encoding="utf-8")
    with pytest.raises(FatalContractError, match=token):
        generator.refresh_native_table_from_supplied_archive(archive, manifest)


@pytest.mark.parametrize(("value", "token"), [(123, "manifest-binding-type"), ("", "manifest-binding-blank")])
def test_manifest_field_type_and_blank_guards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: object, token: str
) -> None:
    archive, manifest, entries = _synthetic_archive(tmp_path, monkeypatch)
    entries[0]["origin_url"] = value
    manifest.write_text(json.dumps(entries), encoding="utf-8")
    with pytest.raises(FatalContractError, match=token):
        generator.refresh_native_table_from_supplied_archive(archive, manifest)


def test_manifest_missing_field_guard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    archive, manifest, entries = _synthetic_archive(tmp_path, monkeypatch)
    del entries[0]["origin_url"]
    manifest.write_text(json.dumps(entries), encoding="utf-8")
    with pytest.raises(FatalContractError, match="manifest-entry-missing-field"):
        generator.refresh_native_table_from_supplied_archive(archive, manifest)


@pytest.mark.parametrize(("content", "token"), [({}, "manifest-not-list"), ([], "manifest-entry-count")])
def test_manifest_structural_guards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: object, token: str
) -> None:
    archive, manifest, _entries = _synthetic_archive(tmp_path, monkeypatch)
    manifest.write_text(json.dumps(content), encoding="utf-8")
    with pytest.raises(FatalContractError, match=token):
        generator.refresh_native_table_from_supplied_archive(archive, manifest)


def test_manifest_missing_guard(tmp_path: Path) -> None:
    with pytest.raises(FatalContractError, match="manifest-missing"):
        generator.refresh_native_table_from_supplied_archive(tmp_path, tmp_path / "absent.json")


@pytest.mark.parametrize(
    ("kind", "token"), [("missing", "manifest-payload-missing"), ("extra", "manifest-payload-extra")]
)
def test_manifest_payload_set_guards(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, token: str) -> None:
    archive, manifest, entries = _synthetic_archive(tmp_path, monkeypatch)
    if kind == "missing":
        (archive / str(entries[0]["file"])).unlink()
    else:
        (archive / "extra").write_bytes(b"x")
    with pytest.raises(FatalContractError, match=token):
        generator.refresh_native_table_from_supplied_archive(archive, manifest)


@pytest.mark.parametrize(("field", "token"), [("bytes", "manifest-byte-count"), ("sha256", "manifest-sha256")])
def test_manifest_payload_predicate_halves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, token: str
) -> None:
    archive, manifest, entries = _synthetic_archive(tmp_path, monkeypatch)
    entries[0][field] = 1 if field == "bytes" else "0" * 64
    monkeypatch.setattr(generator, "_EXPECTED_BINDINGS", tuple(entries))
    manifest.write_text(json.dumps(entries), encoding="utf-8")
    with pytest.raises(FatalContractError, match=token):
        generator.refresh_native_table_from_supplied_archive(archive, manifest)
