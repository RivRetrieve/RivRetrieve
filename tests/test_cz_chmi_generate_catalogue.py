from __future__ import annotations

import copy
import hashlib
import io
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast

import polars as pl
import polars.testing as pl_testing
import pytest
from pypdf import PdfReader

from rivretrieve._internal.catalogue_origins import (
    Authored,
    AuthoredValue,
    Evidence,
    Field,
    FloatConversion,
    NativeColumn,
    NotPublished,
)
from rivretrieve._internal.catalogues.native import NativeTable, RetrievedAt, read_native_table
from rivretrieve._internal.catalogues.schemas import (
    PRODUCT_CATALOG_SCHEMA,
    STATION_CATALOG_SCHEMA,
    STATION_PRODUCT_CATALOG_SCHEMA,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.cz_chmi import generate_catalogue

FIXTURE_PATH = Path("tests/test_data/cz_chmi_metadata.json")
NATIVE_PATH = Path("src/rivretrieve/_internal/providers/cz_chmi/catalogue/native.parquet")
CATALOGUE_PATH = NATIVE_PATH.parent
ATTESTED_DATETIME = datetime(2026, 8, 2, 0, 14, 31, tzinfo=UTC)
ATTESTED_RETRIEVED_AT = RetrievedAt(ATTESTED_DATETIME)
EXPECTED_HEADER = [
    "objID",
    "DBC",
    "STATION_NAME",
    "STREAM_NAME",
    "GEOGR1",
    "GEOGR2",
    "SPA_TYP",
    "SPAH_DS",
    "SPAH_UNIT",
    "DRYH",
    "SPA1H",
    "SPA2H",
    "SPA3H",
    "SPA4H",
    "SPAQ_DS",
    "SPAQ_UNIT",
    "DRYQ",
    "SPA1Q",
    "SPA2Q",
    "SPA3Q",
    "SPA4Q",
    "PLO_STA",
    "HLGP4",
]
EXPECTED_ROWS = [
    [
        "0-203-1-206200",
        "206200",
        "Slapany",
        "Odrava",
        50.0285906,
        12.3757759,
        "H",
        "vodní stav",
        "CM",
        30,
        None,
        None,
        None,
        221,
        "průtok",
        "M3_S",
        0.53,
        None,
        None,
        None,
        88.3,
        266.89,
        "1-13-01-0570",
    ],
    [
        "0-203-1-016000",
        "016000",
        "Jaroměř",
        "Labe",
        50.3427582,
        15.9249555,
        "Q",
        "vodní stav",
        "CM",
        None,
        None,
        None,
        None,
        None,
        "průtok",
        "M3_S",
        3.53,
        None,
        None,
        None,
        359,
        1223.72,
        "1-01-02-0600",
    ],
    [
        "0-203-1-020000",
        "020000",
        "Krčín",
        "Metuje",
        50.3517105,
        16.1299498,
        "H",
        "vodní stav",
        "CM",
        17,
        110,
        160,
        210,
        331,
        "průtok",
        "M3_S",
        1.11,
        24.9,
        42.8,
        65.9,
        144,
        498.55,
        "1-01-03-0511",
    ],
]
NATIVE_SCHEMA = pl.Schema(
    {
        "objID": pl.String,
        "DBC": pl.String,
        "STATION_NAME": pl.String,
        "STREAM_NAME": pl.String,
        "GEOGR1": pl.Float64,
        "GEOGR2": pl.Float64,
        "SPA_TYP": pl.String,
        "SPAH_DS": pl.String,
        "SPAH_UNIT": pl.String,
        "DRYH": pl.Float64,
        "SPA1H": pl.Float64,
        "SPA2H": pl.Float64,
        "SPA3H": pl.Float64,
        "SPA4H": pl.Float64,
        "SPAQ_DS": pl.String,
        "SPAQ_UNIT": pl.String,
        "DRYQ": pl.Float64,
        "SPA1Q": pl.Float64,
        "SPA2Q": pl.Float64,
        "SPA3Q": pl.Float64,
        "SPA4Q": pl.Float64,
        "PLO_STA": pl.Float64,
        "HLGP4": pl.String,
        "retrieved_at": pl.Datetime(time_unit="us", time_zone="UTC"),
    }
)
CZ_ORIGINS = {
    "provider_id": Authored(AuthoredValue("cz_chmi")),
    "station_id": Field(NativeColumn("objID")),
    "latitude": Field(NativeColumn("GEOGR1"), FloatConversion()),
    "longitude": Field(NativeColumn("GEOGR2"), FloatConversion()),
    "crs": NotPublished(Evidence("https://opendata.chmi.cz/hydrology/read_me/Popis_kodu_historical.pdf")),
}

CRS_EVIDENCE_PATH = Path("tests/test_data/cz_chmi_popis_kodu_historical.pdf")
CRS_ABSENCE_TOKENS = (
    "wgs84",
    "wgs 84",
    "wgs-84",
    "epsg",
    "datum",
    "crs",
    "srid",
    "coordinate reference",
    "geodetic",
    "geodät",
    "ellipsoid",
    "etrs",
    "souřadnic",
    "referenč",
    "elipsoid",
    "s-jtsk",
)


def test_publisher_crs_evidence_names_coordinates_but_no_reference_system() -> None:
    capture = CRS_EVIDENCE_PATH.read_bytes()
    reader = PdfReader(CRS_EVIDENCE_PATH)
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    folded = text.casefold()

    assert len(capture) == 423_157
    assert hashlib.sha256(capture).hexdigest() == ("41958b49634d2dc01b51ff72b65d054402628cd154bbcd6b8020def12d88d45a")
    assert capture.count(b"/Font") == 31
    assert capture.count(b"/DCTDecode") == 0
    assert len(reader.pages) == 1
    assert text
    assert "GEOGR1" in text and "Zeměpisná šířka" in text
    assert "GEOGR2" in text and "Zeměpisná délka" in text
    assert all(token.casefold() not in folded for token in CRS_ABSENCE_TOKENS)


def _fixture_payload() -> dict[str, object]:
    value = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return cast("dict[str, object]", value)


def _valid_payload() -> dict[str, object]:
    return {
        "zaznamID": "4A269A04057F71A9E064020820AA46CE",
        "datovyZdrojID": "hydrologie",
        "datovyTokID": "Open.Data.Metadata",
        "datumVytvoreni": "2026-02-06T11:07:39Z",
        "verzeDat": "1.0",
        "data": {
            "type": "DataCollection",
            "data": {
                "header": ",".join(EXPECTED_HEADER),
                "values": copy.deepcopy(EXPECTED_ROWS),
            },
        },
    }


def _data_block(payload: dict[str, object]) -> dict[str, object]:
    data = cast("dict[str, object]", payload["data"])
    return cast("dict[str, object]", data["data"])


class _FixtureResponse(io.BytesIO):
    status = 200


def _build_committed_catalogue() -> generate_catalogue.GeneratedCzChmiCatalogue:
    return generate_catalogue.build_catalogue(read_native_table(NATIVE_PATH), CZ_ORIGINS)


def test_committed_native_build_has_expected_counts_and_schema() -> None:
    cat = _build_committed_catalogue()

    assert cat.stations.height == 831
    assert cat.products.height == 5
    assert cat.station_products.height == 831 * 5
    assert cat.products.schema == PRODUCT_CATALOG_SCHEMA.polars_schema
    assert cat.stations.schema == STATION_CATALOG_SCHEMA.polars_schema
    assert cat.station_products.schema == STATION_PRODUCT_CATALOG_SCHEMA.polars_schema


def test_generate_catalogue_station_fields_are_source_correct() -> None:
    cat = _build_committed_catalogue()
    station = cat.stations.filter(pl.col("station_id") == "0-203-1-016000")

    assert station.height == 1
    assert station["latitude"][0] == 50.3427582
    assert station["longitude"][0] == 15.9249555
    assert station["crs"][0] == "unknown"


@pytest.mark.parametrize(
    "path",
    [
        ("zaznamID",),
        ("datovyZdrojID",),
        ("datovyTokID",),
        ("datumVytvoreni",),
        ("verzeDat",),
        ("data",),
        ("data", "type"),
        ("data", "data"),
        ("data", "data", "header"),
        ("data", "data", "values"),
    ],
)
def test_refresh_rejects_missing_envelope_keys(path: tuple[str, ...]) -> None:
    payload = _valid_payload()
    target = payload
    for key in path[:-1]:
        target = cast("dict[str, object]", target[key])
    del target[path[-1]]

    with pytest.raises(FatalContractError, match=rf"cz_chmi metadata missing required key: '{path[-1]}'"):
        generate_catalogue.refresh_native_table(payload, retrieved_at=ATTESTED_RETRIEVED_AT)


@pytest.mark.parametrize(
    "header",
    [
        ",".join(EXPECTED_HEADER[:-1]),
        ",".join([*EXPECTED_HEADER, "objID"]),
        ",".join(["stationID", *EXPECTED_HEADER[1:]]),
        ",".join([EXPECTED_HEADER[1], EXPECTED_HEADER[0], *EXPECTED_HEADER[2:]]),
    ],
)
def test_refresh_rejects_non_exact_header(header: str) -> None:
    payload = _valid_payload()
    _data_block(payload)["header"] = header

    with pytest.raises(
        FatalContractError,
        match="cz_chmi metadata header does not match the required source header",
    ):
        generate_catalogue.refresh_native_table(payload, retrieved_at=ATTESTED_RETRIEVED_AT)


@pytest.mark.parametrize(
    "row",
    [
        "not-a-row",
    ],
)
def test_refresh_rejects_invalid_row_shape(row: object) -> None:
    payload = _valid_payload()
    rows = cast("list[object]", copy.deepcopy(EXPECTED_ROWS))
    rows[1] = row
    _data_block(payload)["values"] = rows

    with pytest.raises(FatalContractError, match=r"cz_chmi metadata row 2 must be a list"):
        generate_catalogue.refresh_native_table(payload, retrieved_at=ATTESTED_RETRIEVED_AT)


@pytest.mark.parametrize(
    ("row", "value_count"),
    [
        (EXPECTED_ROWS[0][:-1], 22),
        ([*EXPECTED_ROWS[0], "extra"], 24),
    ],
)
def test_refresh_rejects_invalid_row_width(row: list[object], value_count: int) -> None:
    payload = _valid_payload()
    rows = cast("list[object]", copy.deepcopy(EXPECTED_ROWS))
    rows[1] = row
    _data_block(payload)["values"] = rows

    with pytest.raises(
        FatalContractError,
        match=rf"cz_chmi metadata row 2 has {value_count} values; expected 23",
    ):
        generate_catalogue.refresh_native_table(payload, retrieved_at=ATTESTED_RETRIEVED_AT)


@pytest.mark.parametrize("station_id", [None, 206200, "", "   "])
def test_refresh_rejects_invalid_obj_id(station_id: object) -> None:
    payload = _valid_payload()
    row = cast("list[object]", copy.deepcopy(EXPECTED_ROWS[0]))
    row[0] = station_id
    rows = cast("list[object]", copy.deepcopy(EXPECTED_ROWS))
    rows[1] = row
    _data_block(payload)["values"] = rows

    with pytest.raises(FatalContractError, match=r"cz_chmi metadata row 2 has an invalid objID"):
        generate_catalogue.refresh_native_table(payload, retrieved_at=ATTESTED_RETRIEVED_AT)


def test_refresh_fixture_is_network_free_and_source_faithful(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_network(url: str) -> object:
        raise AssertionError(f"unexpected live request to {url}")

    monkeypatch.setattr(generate_catalogue, "_read_live_json", fail_network)
    outcome = generate_catalogue.refresh_native_table_from_fixture(
        FIXTURE_PATH,
        retrieved_at=ATTESTED_RETRIEVED_AT,
    )

    assert outcome.issues == ()
    assert outcome.value.data.height == 3
    assert outcome.value.data.schema == NATIVE_SCHEMA
    assert outcome.value.data["GEOGR1"].to_list() == [
        row[4] for row in sorted(EXPECTED_ROWS, key=lambda row: cast("str", row[0]))
    ]
    assert outcome.value.data["SPA1H"].null_count() == 2


def test_refresh_live_transport_seam_uses_url_and_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, int]] = []
    fixture_bytes = json.dumps(_valid_payload(), ensure_ascii=False).encode()

    def fake_urlopen(url: str, *, timeout: int) -> _FixtureResponse:
        calls.append((url, timeout))
        return _FixtureResponse(fixture_bytes)

    monkeypatch.setattr(generate_catalogue.urllib.request, "urlopen", fake_urlopen)
    outcome = generate_catalogue.refresh_native_table_from_live(retrieved_at=ATTESTED_RETRIEVED_AT)

    assert calls == [(generate_catalogue.METADATA_URL, 30)]
    assert outcome.value.data.height == 3
    assert outcome.issues == ()


def test_refresh_cli_writes_fixture_native_table(tmp_path: Path) -> None:
    output_path = tmp_path / "native.parquet"

    result = generate_catalogue.main(
        [
            "--fixture",
            str(FIXTURE_PATH),
            "--native-out",
            str(output_path),
            "--retrieved-at",
            "2026-08-02T00:14:31Z",
        ]
    )

    assert result == 0
    assert read_native_table(output_path).data.schema == NATIVE_SCHEMA


@pytest.mark.parametrize(
    "argv",
    [
        ["--fixture", str(FIXTURE_PATH), "--native-out", "native.parquet"],
        ["--fixture", str(FIXTURE_PATH), "--out", "catalogue"],
        ["--live", "--out", "catalogue"],
        ["--native", str(NATIVE_PATH), "--native-out", "native.parquet", "--retrieved-at", "2026-08-02T00:14:31Z"],
        ["--native", str(NATIVE_PATH), "--out", "catalogue", "--retrieved-at", "2026-08-02T00:14:31Z"],
    ],
)
def test_cli_rejects_invalid_mode_combinations(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        generate_catalogue.main(argv)

    assert exc_info.value.code != 0


def test_active_fixture_is_verbatim_attested_subset() -> None:
    fixture = _fixture_payload()
    expected = _valid_payload()

    assert {key: fixture[key] for key in fixture if key != "data"} == {
        key: expected[key] for key in expected if key != "data"
    }
    assert cast("dict[str, object]", fixture["data"])["type"] == "DataCollection"
    block = _data_block(fixture)
    assert block["header"] == ",".join(EXPECTED_HEADER)
    assert block["values"] == EXPECTED_ROWS
    assert [[type(value) for value in row] for row in cast("list[list[object]]", block["values"])] == [
        [type(value) for value in row] for row in EXPECTED_ROWS
    ]


def test_previous_fixture_source_defects_are_not_retained() -> None:
    rows = cast("list[list[object]]", _data_block(_fixture_payload())["values"])
    by_id = {row[0]: row for row in rows}

    assert by_id["0-203-1-016000"][4:6] == [50.3427582, 15.9249555]
    assert by_id["0-203-1-020000"][4:6] == [50.3517105, 16.1299498]
    assert "0-204-1-001000" not in by_id


def test_committed_native_table_invariants() -> None:
    table = read_native_table(NATIVE_PATH).data
    ids = sorted(cast("list[str]", table["objID"].to_list()))
    id_digest = hashlib.sha256(
        json.dumps(ids, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    canonical_table = {
        "columns": table.columns,
        "rows": [
            [value.isoformat().replace("+00:00", "Z") if isinstance(value, datetime) else value for value in row]
            for row in table.sort("objID").iter_rows()
        ],
    }
    table_digest = hashlib.sha256(
        json.dumps(
            canonical_table,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()

    assert table.height == 831
    assert table.schema == NATIVE_SCHEMA
    assert table["retrieved_at"].n_unique() == 1
    assert table["retrieved_at"].item(0) == ATTESTED_DATETIME
    assert id_digest == "6af66556b1a0315cb22c40a31991ce5369c74d532e25d6a2796389ad7088bb9e"
    assert table_digest == "b13d49902967e6f2fe182348999d24af711868f0c38032c425485aa41a66dd2b"


def test_fixture_refresh_equals_committed_source_rows_exactly() -> None:
    committed = read_native_table(NATIVE_PATH).data
    fixture = generate_catalogue.refresh_native_table_from_fixture(
        FIXTURE_PATH,
        retrieved_at=ATTESTED_RETRIEVED_AT,
    ).value.data
    expected = committed.filter(pl.col("objID").is_in([row[0] for row in EXPECTED_ROWS]))

    pl_testing.assert_frame_equal(fixture, expected, check_exact=True)
    coordinates = {
        station_id: (latitude, longitude)
        for station_id, latitude, longitude in committed.select("objID", "GEOGR1", "GEOGR2").iter_rows()
        if station_id in {row[0] for row in EXPECTED_ROWS}
    }
    assert coordinates == {
        "0-203-1-206200": (50.0285906, 12.3757759),
        "0-203-1-016000": (50.3427582, 15.9249555),
        "0-203-1-020000": (50.3517105, 16.1299498),
    }


def test_native_build_is_gated_on_origins() -> None:
    broken = dict(CZ_ORIGINS)
    del broken["longitude"]

    with pytest.raises(
        FatalContractError,
        match=r"cz_chmi\.longitude: canonical column has no origin declaration",
    ):
        generate_catalogue.build_catalogue(read_native_table(NATIVE_PATH), broken)


def test_native_and_canonical_identity_and_coordinates_are_exactly_aligned() -> None:
    native = read_native_table(NATIVE_PATH).data
    stations = _build_committed_catalogue().stations
    expected = (
        native.select(
            pl.lit("cz_chmi").alias("provider_id"),
            pl.col("objID").alias("station_id"),
            pl.col("GEOGR1").alias("latitude"),
            pl.col("GEOGR2").alias("longitude"),
            pl.lit("unknown").alias("crs"),
        )
        .cast(STATION_CATALOG_SCHEMA.polars_schema)
        .sort("station_id")
    )

    pl_testing.assert_frame_equal(stations, expected, check_exact=True)
    assert {"STATION_NAME", "STREAM_NAME", "PLO_STA", "HLGP4"} <= set(native.columns)


def test_committed_stations_artifact_equals_native_exactly_and_is_inside_czechia() -> None:
    native = read_native_table(NATIVE_PATH).data
    committed = pl.read_parquet(CATALOGUE_PATH / "stations.parquet")
    expected = (
        native.select(
            pl.lit("cz_chmi").alias("provider_id"),
            pl.col("objID").alias("station_id"),
            pl.col("GEOGR1").alias("latitude"),
            pl.col("GEOGR2").alias("longitude"),
            pl.lit("unknown").alias("crs"),
        )
        .cast(STATION_CATALOG_SCHEMA.polars_schema)
        .sort("station_id")
    )

    pl_testing.assert_frame_equal(committed, expected, check_exact=True)
    assert committed["latitude"].is_between(48.55, 51.06, closed="both").all()
    assert committed["longitude"].is_between(12.09, 18.90, closed="both").all()


def test_mixed_retrieval_dates_flow_to_station_products_and_provider_version() -> None:
    source = read_native_table(NATIVE_PATH).data.head(2)
    station_ids = source["objID"].to_list()
    mixed = source.with_columns(
        pl.when(pl.col("objID") == station_ids[0])
        .then(datetime(2026, 7, 31, 12, tzinfo=UTC))
        .otherwise(datetime(2026, 8, 3, 12, tzinfo=UTC))
        .cast(pl.Datetime(time_unit="us", time_zone="UTC"))
        .alias("retrieved_at")
    )

    catalogue = generate_catalogue.build_catalogue(NativeTable(mixed), CZ_ORIGINS)

    assert set(catalogue.station_products.filter(pl.col("station_id") == station_ids[0])["last_catalogue_check"]) == {
        date(2026, 7, 31)
    }
    assert set(catalogue.station_products.filter(pl.col("station_id") == station_ids[1])["last_catalogue_check"]) == {
        date(2026, 8, 3)
    }
    assert catalogue.provider_info["catalogue_version"] == "2026-08-03"


def _two_row_native() -> pl.DataFrame:
    return read_native_table(NATIVE_PATH).data.head(2)


def test_build_rejects_empty_native_table_by_message() -> None:
    empty = read_native_table(NATIVE_PATH).data.head(0)

    with pytest.raises(FatalContractError, match="Czech native table must not be empty"):
        generate_catalogue.build_catalogue(NativeTable(empty), CZ_ORIGINS)


@pytest.mark.parametrize("station_id", [None, 206200, "", "   "])
def test_build_rejects_one_invalid_obj_id_in_multi_row_native_by_message(station_id: object) -> None:
    source = _two_row_native()
    broken = source.with_columns(pl.Series("objID", [source["objID"].item(0), station_id], dtype=pl.Object))

    with pytest.raises(FatalContractError, match=r"cz_chmi native station row 2 has an invalid objID"):
        generate_catalogue.build_catalogue(NativeTable(broken), CZ_ORIGINS)


@pytest.mark.parametrize(("column", "label"), [("GEOGR1", "latitude"), ("GEOGR2", "longitude")])
def test_build_rejects_one_missing_coordinate_in_multi_row_native_by_message(column: str, label: str) -> None:
    station_id = _two_row_native()["objID"].item(1)
    broken = _two_row_native().with_columns(
        pl.when(pl.int_range(pl.len()) == 1).then(None).otherwise(pl.col(column)).alias(column)
    )

    with pytest.raises(
        FatalContractError,
        match=rf"cz_chmi native station {station_id} has missing or null {label}",
    ):
        generate_catalogue.build_catalogue(NativeTable(broken), CZ_ORIGINS)


@pytest.mark.parametrize(("column", "label"), [("GEOGR1", "latitude"), ("GEOGR2", "longitude")])
def test_build_rejects_one_non_numeric_coordinate_in_multi_row_native_by_message(column: str, label: str) -> None:
    source = _two_row_native()
    station_id = source["objID"].item(1)
    broken = source.with_columns(pl.Series(column, [source[column].item(0), "not-numeric"], dtype=pl.Object))

    with pytest.raises(
        FatalContractError,
        match=rf"cz_chmi native station {station_id} has non-numeric {label}",
    ):
        generate_catalogue.build_catalogue(NativeTable(broken), CZ_ORIGINS)


def test_build_rejects_invalid_per_row_retrieval_date_pairing_by_message() -> None:
    station_id = _two_row_native()["objID"].item(1)
    station_dates = pl.DataFrame(
        {
            "station_id": [_two_row_native()["objID"].item(0), station_id],
            "retrieved_date": [date(2026, 8, 2), None],
        }
    )

    with pytest.raises(
        FatalContractError,
        match=rf"cz_chmi station {station_id} retrieval date is invalid",
    ):
        generate_catalogue.build_station_products(station_dates)


def test_build_rejects_invalid_station_identifier_in_multi_row_dates_by_message() -> None:
    station_dates = pl.DataFrame(
        {
            "station_id": [_two_row_native()["objID"].item(0), None],
            "retrieved_date": [date(2026, 8, 2), date(2026, 8, 2)],
        }
    )

    with pytest.raises(
        FatalContractError,
        match="cz_chmi station retrieval date has an invalid identifier",
    ):
        generate_catalogue.build_station_products(station_dates)


def test_native_table_rejects_null_retrieval_timestamps_before_build() -> None:
    broken = _two_row_native().with_columns(pl.lit(None).cast(NATIVE_SCHEMA["retrieved_at"]).alias("retrieved_at"))

    with pytest.raises(FatalContractError, match="native table retrieved_at must not contain nulls"):
        NativeTable(broken)


def test_legacy_canonical_generation_apis_are_removed() -> None:
    assert not hasattr(generate_catalogue, "generate_catalogue")
    assert not hasattr(generate_catalogue, "generate_catalogue_from_fixture")
    assert not hasattr(generate_catalogue, "generate_catalogue_from_live")


def test_native_cli_writes_five_artifacts_without_touching_native(tmp_path: Path) -> None:
    native_bytes = NATIVE_PATH.read_bytes()

    result = generate_catalogue.main(["--native", str(NATIVE_PATH), "--out", str(tmp_path)])

    assert result == 0
    assert NATIVE_PATH.read_bytes() == native_bytes
    assert {path.name for path in tmp_path.iterdir()} == {
        "croissant.json",
        "provider.json",
        "products.parquet",
        "stations.parquet",
        "station_products.parquet",
        "provenance.json",
    }


def test_native_build_is_network_free_and_byte_deterministic(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def fail_network(*args: object, **kwargs: object) -> object:
        calls.append("network")
        raise AssertionError("network must not be accessed during build")

    monkeypatch.setattr(generate_catalogue, "_read_live_json", fail_network)
    monkeypatch.setattr(generate_catalogue.urllib.request, "urlopen", fail_network)

    result = generate_catalogue.main(["--native", str(NATIVE_PATH), "--out", str(tmp_path)])

    assert result == 0
    assert calls == []
    for artifact_name in ("provider.json", "products.parquet", "stations.parquet", "station_products.parquet"):
        assert (tmp_path / artifact_name).read_bytes() == (CATALOGUE_PATH / artifact_name).read_bytes()
