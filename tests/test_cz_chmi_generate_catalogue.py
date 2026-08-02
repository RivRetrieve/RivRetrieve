from __future__ import annotations

import copy
import hashlib
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import polars as pl
import polars.testing as pl_testing
import pytest

from rivretrieve._internal.catalogues.native import RetrievedAt, read_native_table
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.cz_chmi import generate_catalogue

FIXTURE_PATH = Path("tests/test_data/cz_chmi_metadata.json")
NATIVE_PATH = Path("src/rivretrieve/_internal/providers/cz_chmi/catalogue/native.parquet")
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


def test_generate_catalogue_from_fixture_station_count() -> None:
    cat = generate_catalogue.generate_catalogue_from_fixture(FIXTURE_PATH)
    assert cat.stations.height == 3


def test_generate_catalogue_from_fixture_product_count() -> None:
    cat = generate_catalogue.generate_catalogue_from_fixture(FIXTURE_PATH)
    assert cat.products.height == 5


def test_generate_catalogue_from_fixture_station_products_cross() -> None:
    cat = generate_catalogue.generate_catalogue_from_fixture(FIXTURE_PATH)
    assert cat.station_products.height == 3 * 5


def test_generate_catalogue_station_fields_are_source_correct() -> None:
    cat = generate_catalogue.generate_catalogue_from_fixture(FIXTURE_PATH)
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

    with pytest.raises(FatalContractError):
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

    with pytest.raises(FatalContractError):
        generate_catalogue.refresh_native_table(payload, retrieved_at=ATTESTED_RETRIEVED_AT)


@pytest.mark.parametrize(
    "row",
    [
        "not-a-row",
        EXPECTED_ROWS[0][:-1],
        [*EXPECTED_ROWS[0], "extra"],
    ],
)
def test_refresh_rejects_invalid_row_shape(row: object) -> None:
    payload = _valid_payload()
    _data_block(payload)["values"] = [row]

    with pytest.raises(FatalContractError):
        generate_catalogue.refresh_native_table(payload, retrieved_at=ATTESTED_RETRIEVED_AT)


@pytest.mark.parametrize("station_id", [None, 206200, "", "   "])
def test_refresh_rejects_invalid_obj_id(station_id: object) -> None:
    payload = _valid_payload()
    row = copy.deepcopy(EXPECTED_ROWS[0])
    row[0] = station_id
    _data_block(payload)["values"] = [row]

    with pytest.raises(FatalContractError):
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
        [
            "--fixture",
            str(FIXTURE_PATH),
            "--out",
            "catalogue",
            "--native-out",
            "native.parquet",
            "--retrieved-at",
            "2026-08-02T00:14:31Z",
        ],
        [
            "--fixture",
            str(FIXTURE_PATH),
            "--out",
            "catalogue",
            "--retrieved-at",
            "2026-08-02T00:14:31Z",
        ],
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
    digest = hashlib.sha256(
        json.dumps(ids, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()

    assert table.height == 831
    assert table.schema == NATIVE_SCHEMA
    assert table["retrieved_at"].n_unique() == 1
    assert table["retrieved_at"].item(0) == ATTESTED_DATETIME
    assert digest == "6af66556b1a0315cb22c40a31991ce5369c74d532e25d6a2796389ad7088bb9e"


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
