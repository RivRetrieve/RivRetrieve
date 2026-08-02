from __future__ import annotations

import hashlib
import io
import json
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import polars.testing as pl_testing
import pytest

from rivretrieve._internal.catalogues.native import RetrievedAt, read_native_table
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.usgs_nwis import generate_catalogue as generator
from rivretrieve._internal.providers.usgs_nwis.generate_catalogue import (
    PRODUCT_DEFINITIONS,
    generate_catalogue,
    generate_catalogue_from_fixture,
)

FIXTURE_PATH = Path("tests/test_data/usgs_nwis_metadata_sites.json")
SERIES_FIXTURE_PATH = Path("tests/test_data/usgs_nwis_metadata_series.json")
EXPANDED_FIXTURE_PATH = Path("tests/test_data/usgs_nwis_metadata_expanded.json")
NATIVE_PATH = Path("src/rivretrieve/_internal/providers/usgs_nwis/catalogue/native.parquet")
ATTESTED_DATETIME = datetime(2026, 8, 2, 1, 14, 11, tzinfo=UTC)
ATTESTED_RETRIEVED_AT = RetrievedAt(ATTESTED_DATETIME)

SERIES_HEADER = (
    "agency_cd",
    "site_no",
    "station_nm",
    "site_tp_cd",
    "dec_lat_va",
    "dec_long_va",
    "coord_acy_cd",
    "dec_coord_datum_cd",
    "alt_va",
    "alt_acy_va",
    "alt_datum_cd",
    "huc_cd",
    "data_type_cd",
    "parm_cd",
    "stat_cd",
    "ts_id",
    "loc_web_ds",
    "medium_grp_cd",
    "parm_grp_cd",
    "srs_id",
    "access_cd",
    "begin_date",
    "end_date",
    "count_nu",
)
SERIES_FORMAT = (
    "5s",
    "15s",
    "50s",
    "7s",
    "16s",
    "16s",
    "1s",
    "10s",
    "8s",
    "3s",
    "10s",
    "16s",
    "2s",
    "5s",
    "5s",
    "5n",
    "30s",
    "3s",
    "3s",
    "5n",
    "4n",
    "20d",
    "20d",
    "5n",
)
EXPANDED_HEADER = (
    "agency_cd",
    "site_no",
    "station_nm",
    "site_tp_cd",
    "lat_va",
    "long_va",
    "dec_lat_va",
    "dec_long_va",
    "coord_meth_cd",
    "coord_acy_cd",
    "coord_datum_cd",
    "dec_coord_datum_cd",
    "district_cd",
    "state_cd",
    "county_cd",
    "country_cd",
    "land_net_ds",
    "map_nm",
    "map_scale_fc",
    "alt_va",
    "alt_meth_cd",
    "alt_acy_va",
    "alt_datum_cd",
    "huc_cd",
    "basin_cd",
    "topo_cd",
    "instruments_cd",
    "construction_dt",
    "inventory_dt",
    "drain_area_va",
    "contrib_drain_area_va",
    "tz_cd",
    "local_time_fg",
    "reliability_cd",
    "gw_file_cd",
    "nat_aqfr_cd",
    "aqfr_cd",
    "aqfr_type_cd",
    "well_depth_va",
    "hole_depth_va",
    "depth_src_cd",
    "project_no",
)
EXPANDED_FORMAT = (
    "5s",
    "15s",
    "50s",
    "7s",
    "16s",
    "16s",
    "16s",
    "16s",
    "1s",
    "1s",
    "10s",
    "10s",
    "3s",
    "2s",
    "3s",
    "2s",
    "23s",
    "20s",
    "7s",
    "8s",
    "1s",
    "3s",
    "10s",
    "16s",
    "2s",
    "1s",
    "30s",
    "8s",
    "8s",
    "8s",
    "8s",
    "6s",
    "1s",
    "1s",
    "30s",
    "10s",
    "8s",
    "1s",
    "8s",
    "8s",
    "1s",
    "12s",
)
SERIES_ONLY_FIELDS = SERIES_HEADER[12:]
NATIVE_SCHEMA = pl.Schema(
    {
        **dict.fromkeys(EXPANDED_HEADER, pl.String),
        **{name: pl.List(pl.String) for name in SERIES_ONLY_FIELDS},
        "retrieved_at": pl.Datetime(time_unit="us", time_zone="UTC"),
    }
)


def _fixture_rows(path: Path) -> list[dict[str, str]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, list)
    assert all(isinstance(row, dict) for row in value)
    return value


def _rdb_text(
    header: tuple[str, ...],
    format_row: tuple[str, ...],
    rows: list[dict[str, str]],
) -> str:
    return "\n".join(
        [
            "# source comment",
            "\t".join(header),
            "\t".join(format_row),
            *("\t".join(row[name] for name in header) for row in rows),
        ]
    )


def _fixture_refresh() -> object:
    return generator.refresh_native_table_from_fixtures(
        SERIES_FIXTURE_PATH,
        EXPANDED_FIXTURE_PATH,
        retrieved_at=ATTESTED_RETRIEVED_AT,
    )


def test_generate_catalogue_from_fixture_station_count() -> None:
    catalogue = generate_catalogue_from_fixture(FIXTURE_PATH, catalogue_date=date(2026, 6, 1))
    assert catalogue.stations.height == 5  # fixture has 5 representative stations


def test_generate_catalogue_station_07374000() -> None:
    catalogue = generate_catalogue_from_fixture(FIXTURE_PATH, catalogue_date=date(2026, 6, 1))
    row = catalogue.stations.filter(catalogue.stations["station_id"] == "07374000")
    assert row.height == 1
    assert abs(row["latitude"][0] - 30.44) < 0.1
    assert abs(row["longitude"][0] - (-91.19)) < 0.1
    assert row["crs"][0] == "unknown"


def test_generate_catalogue_product_count() -> None:
    catalogue = generate_catalogue_from_fixture(FIXTURE_PATH, catalogue_date=date(2026, 6, 1))
    assert catalogue.products.height == len(PRODUCT_DEFINITIONS)


def test_generate_catalogue_canonical_product_ids() -> None:
    catalogue = generate_catalogue_from_fixture(FIXTURE_PATH, catalogue_date=date(2026, 6, 1))
    product_ids = set(catalogue.products["product_id"].to_list())
    assert "discharge_daily_mean" in product_ids
    assert "discharge_instantaneous" in product_ids
    assert "stage_daily_mean" in product_ids
    assert "stage_daily_max" in product_ids
    assert "stage_daily_min" in product_ids
    assert "stage_instantaneous" in product_ids


def test_generate_catalogue_station_products_count() -> None:
    catalogue = generate_catalogue_from_fixture(FIXTURE_PATH, catalogue_date=date(2026, 6, 1))
    assert catalogue.station_products.height == catalogue.stations.height * len(PRODUCT_DEFINITIONS)


def test_generate_catalogue_station_products_availability_unknown() -> None:
    catalogue = generate_catalogue_from_fixture(FIXTURE_PATH, catalogue_date=date(2026, 6, 1))
    avail_vals = catalogue.station_products["availability"].unique().to_list()
    assert avail_vals == ["unknown"]


def test_generate_catalogue_provider_info_fields() -> None:
    catalogue = generate_catalogue_from_fixture(FIXTURE_PATH, catalogue_date=date(2026, 6, 1))
    pi = catalogue.provider_info
    assert pi["provider_id"] == "usgs_nwis"
    assert pi["catalogue_version"] == "2026-06-01"
    assert pi["live_stations"] is False
    assert pi["live_products"] is False
    assert pi["live_station_products"] is False


def test_live_mode_rejects_too_few_stations() -> None:
    """Guard: --live must produce ≥10 000 stations or raise, preventing a test fixture from being committed as the packaged catalogue."""

    tiny_fixture = [
        {"site_no": "07374000", "station_nm": "Mississippi R.", "dec_lat_va": "30.4", "dec_long_va": "-91.2"}
    ]
    with pytest.raises(FatalContractError, match="live catalogue has only"):
        generate_catalogue(tiny_fixture, generator_input="live")


def test_strict_rdb_parser_preserves_source_strings_and_empty_fields() -> None:
    rows = _fixture_rows(SERIES_FIXTURE_PATH)

    parsed = generator.parse_series_rdb(_rdb_text(SERIES_HEADER, SERIES_FORMAT, rows))

    assert parsed == rows
    assert parsed[2]["stat_cd"] == ""
    assert parsed[2]["loc_web_ds"] == "[(2)]"


@pytest.mark.parametrize(
    "header",
    [
        SERIES_HEADER[:-1],
        (*SERIES_HEADER, "unexpected"),
        (SERIES_HEADER[1], SERIES_HEADER[1], *SERIES_HEADER[2:]),
        (SERIES_HEADER[1], SERIES_HEADER[0], *SERIES_HEADER[2:]),
        (*SERIES_HEADER[:-1], "substituted"),
    ],
)
def test_strict_rdb_parser_rejects_non_exact_headers(header: tuple[str, ...]) -> None:
    rows = _fixture_rows(SERIES_FIXTURE_PATH)
    values = [rows[0].get(name, "value") for name in header]
    text = "\n".join(("\t".join(header), "\t".join("1s" for _ in header), "\t".join(values)))

    with pytest.raises(FatalContractError, match="header"):
        generator.parse_series_rdb(text)


def test_strict_rdb_parser_rejects_non_exact_format_row() -> None:
    rows = _fixture_rows(EXPANDED_FIXTURE_PATH)
    malformed_format = (*EXPANDED_FORMAT[:-2], EXPANDED_FORMAT[-1], EXPANDED_FORMAT[-2])

    with pytest.raises(FatalContractError, match="format"):
        generator.parse_expanded_rdb(_rdb_text(EXPANDED_HEADER, malformed_format, rows))


@pytest.mark.parametrize(
    "data_line",
    [
        "not data",
        "\t".join("value" for _ in range(len(SERIES_HEADER) - 1)),
        "\t".join("value" for _ in range(len(SERIES_HEADER) + 1)),
    ],
)
def test_strict_rdb_parser_rejects_malformed_rows(data_line: str) -> None:
    text = "\n".join(("\t".join(SERIES_HEADER), "\t".join(SERIES_FORMAT), data_line))

    with pytest.raises(FatalContractError, match="row"):
        generator.parse_series_rdb(text)


def test_strict_rdb_parser_rejects_empty_data() -> None:
    text = "\n".join(("\t".join(SERIES_HEADER), "\t".join(SERIES_FORMAT)))

    with pytest.raises(FatalContractError, match="empty"):
        generator.parse_series_rdb(text)


@pytest.mark.parametrize("site_no", [None, "", "   "])
def test_refresh_rejects_absent_or_blank_site_no(site_no: str | None) -> None:
    series = _fixture_rows(SERIES_FIXTURE_PATH)
    expanded = _fixture_rows(EXPANDED_FIXTURE_PATH)
    if site_no is None:
        del series[0]["site_no"]
    else:
        series[0]["site_no"] = site_no

    with pytest.raises(FatalContractError, match="site_no"):
        generator.refresh_native_table(
            series,
            expanded,
            retrieved_at=ATTESTED_RETRIEVED_AT,
            input_kind=generator.NativeInputKind.FIXTURE,
        )


def test_refresh_rejects_duplicate_expanded_site() -> None:
    expanded = _fixture_rows(EXPANDED_FIXTURE_PATH)

    with pytest.raises(FatalContractError, match="duplicate"):
        generator.refresh_native_table(
            _fixture_rows(SERIES_FIXTURE_PATH),
            [expanded[0], dict(expanded[0])],
            retrieved_at=ATTESTED_RETRIEVED_AT,
            input_kind=generator.NativeInputKind.FIXTURE,
        )


@pytest.mark.parametrize("orphan_pass", ["series", "expanded"])
def test_refresh_rejects_cross_pass_orphan(orphan_pass: str) -> None:
    series = _fixture_rows(SERIES_FIXTURE_PATH)
    expanded = _fixture_rows(EXPANDED_FIXTURE_PATH)
    if orphan_pass == "series":
        series[0]["site_no"] = "99999999"
    else:
        expanded[0]["site_no"] = "99999999"

    with pytest.raises(FatalContractError, match="site sets"):
        generator.refresh_native_table(
            series,
            expanded,
            retrieved_at=ATTESTED_RETRIEVED_AT,
            input_kind=generator.NativeInputKind.FIXTURE,
        )


def test_refresh_rejects_conflicting_repeated_fact_within_series() -> None:
    series = _fixture_rows(SERIES_FIXTURE_PATH)
    series[1]["station_nm"] = "CONFLICT"

    with pytest.raises(FatalContractError, match="station_nm"):
        generator.refresh_native_table(
            series,
            _fixture_rows(EXPANDED_FIXTURE_PATH),
            retrieved_at=ATTESTED_RETRIEVED_AT,
            input_kind=generator.NativeInputKind.FIXTURE,
        )


def test_refresh_rejects_conflicting_repeated_fact_between_passes() -> None:
    expanded = _fixture_rows(EXPANDED_FIXTURE_PATH)
    expanded[0]["huc_cd"] = "CONFLICT"

    with pytest.raises(FatalContractError, match="huc_cd"):
        generator.refresh_native_table(
            _fixture_rows(SERIES_FIXTURE_PATH),
            expanded,
            retrieved_at=ATTESTED_RETRIEVED_AT,
            input_kind=generator.NativeInputKind.FIXTURE,
        )


def test_refresh_rejects_malformed_series_shape() -> None:
    series = _fixture_rows(SERIES_FIXTURE_PATH)
    del series[0]["count_nu"]

    with pytest.raises(FatalContractError, match="series row"):
        generator.refresh_native_table(
            series,
            _fixture_rows(EXPANDED_FIXTURE_PATH),
            retrieved_at=ATTESTED_RETRIEVED_AT,
            input_kind=generator.NativeInputKind.FIXTURE,
        )


def test_refresh_rejects_missing_required_data_type() -> None:
    series = [row for row in _fixture_rows(SERIES_FIXTURE_PATH) if row["data_type_cd"] == "dv"]

    with pytest.raises(FatalContractError, match="dv and uv"):
        generator.refresh_native_table(
            series,
            _fixture_rows(EXPANDED_FIXTURE_PATH),
            retrieved_at=ATTESTED_RETRIEVED_AT,
            input_kind=generator.NativeInputKind.FIXTURE,
        )


def test_fixture_refresh_is_exempt_from_live_minimum() -> None:
    outcome = _fixture_refresh()

    assert outcome.value.data.height == 1


def test_supplied_national_refresh_enforces_live_minimum() -> None:
    with pytest.raises(FatalContractError, match="10,000"):
        generator.refresh_native_table(
            _fixture_rows(SERIES_FIXTURE_PATH),
            _fixture_rows(EXPANDED_FIXTURE_PATH),
            retrieved_at=ATTESTED_RETRIEVED_AT,
            input_kind=generator.NativeInputKind.SUPPLIED_NATIONAL,
        )


def test_fixture_refresh_preserves_exact_source_data_and_alignment() -> None:
    series_rows = _fixture_rows(SERIES_FIXTURE_PATH)
    expanded_row = _fixture_rows(EXPANDED_FIXTURE_PATH)[0]
    ordered_series = sorted(series_rows, key=lambda row: tuple(row[name] for name in SERIES_HEADER))
    expected_row: dict[str, object] = dict(expanded_row)
    expected_row.update({name: [row[name] for row in ordered_series] for name in SERIES_ONLY_FIELDS})
    expected_row["retrieved_at"] = ATTESTED_DATETIME
    expected = pl.DataFrame([expected_row], schema=NATIVE_SCHEMA)

    outcome = _fixture_refresh()

    assert outcome.issues == ()
    pl_testing.assert_frame_equal(outcome.value.data, expected, check_exact=True)
    assert len({len(outcome.value.data[name].item()) for name in SERIES_ONLY_FIELDS}) == 1
    records = list(zip(*(outcome.value.data[name].item() for name in SERIES_ONLY_FIELDS), strict=True))
    assert records == sorted(records)
    assert {(row["data_type_cd"], row["parm_cd"], row["stat_cd"]) for row in series_rows} == {
        ("dv", "00060", "00003"),
        ("dv", "00065", "00003"),
        ("uv", "00060", ""),
        ("uv", "00065", ""),
    }


class _FixtureResponse(io.BytesIO):
    status = 200


def test_live_transport_uses_exact_102_in_scope_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    series_bytes = _rdb_text(SERIES_HEADER, SERIES_FORMAT, _fixture_rows(SERIES_FIXTURE_PATH)).encode()
    expanded_bytes = _rdb_text(EXPANDED_HEADER, EXPANDED_FORMAT, _fixture_rows(EXPANDED_FIXTURE_PATH)).encode()
    calls: list[tuple[str, int]] = []

    def fake_urlopen(url: str, *, timeout: int) -> _FixtureResponse:
        calls.append((url, timeout))
        return _FixtureResponse(series_bytes if "seriesCatalogOutput=true" in url else expanded_bytes)

    monkeypatch.setattr(generator.urllib.request, "urlopen", fake_urlopen)

    series, expanded = generator.read_live_native_rows()

    expected_urls = [
        url
        for state_cd in generator._US_STATE_CODES
        for url in (
            generator.SERIES_CATALOGUE_URL.format(state_cd=state_cd),
            generator.EXPANDED_SITE_URL.format(state_cd=state_cd),
        )
    ]
    assert calls == [(url, 60) for url in expected_urls]
    assert len(series) == len(generator._US_STATE_CODES) * 4
    assert len(expanded) == len(generator._US_STATE_CODES)
    assert not any(f"stateCd={territory}" in url for url in expected_urls for territory in ("GU", "MP", "PR", "VI"))


def test_native_cli_requires_strict_z_retrieval_instant(tmp_path: Path) -> None:
    common = ["--rdb-dir", str(tmp_path.resolve()), "--native-out", str(tmp_path / "native.parquet")]
    with pytest.raises(SystemExit):
        generator.main(common)
    with pytest.raises(SystemExit):
        generator.main([*common, "--retrieved-at", "2026-08-02T01:14:11+00:00"])


def test_native_cli_writes_table_without_rewriting_canonical_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    native_out = tmp_path / "native.parquet"
    sentinel = tmp_path / "provider.json"
    sentinel.write_text("unchanged", encoding="utf-8")
    expected = _fixture_refresh()

    monkeypatch.setattr(generator, "refresh_native_table_from_rdb_directory", lambda *args, **kwargs: expected)

    result = generator.main(
        [
            "--rdb-dir",
            str(tmp_path.resolve()),
            "--native-out",
            str(native_out),
            "--retrieved-at",
            "2026-08-02T01:14:11Z",
        ]
    )

    assert result == 0
    assert sentinel.read_text(encoding="utf-8") == "unchanged"
    pl_testing.assert_frame_equal(read_native_table(native_out).data, expected.value.data, check_exact=True)


@pytest.mark.parametrize(
    "argv",
    [
        ["--fixture", str(FIXTURE_PATH), "--native-out", "native.parquet", "--retrieved-at", "2026-08-02T01:14:11Z"],
        ["--live", "--native-out", "native.parquet", "--retrieved-at", "2026-08-02T01:14:11Z"],
        ["--rdb-dir", ".", "--out", "catalogue", "--retrieved-at", "2026-08-02T01:14:11Z"],
        [
            "--rdb-dir",
            ".",
            "--native-out",
            "native.parquet",
            "--catalogue-date",
            "2026-08-02",
            "--retrieved-at",
            "2026-08-02T01:14:11Z",
        ],
    ],
)
def test_cli_rejects_cross_mode_combinations(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        generator.main(argv)


def test_committed_native_table_exact_schema_counts_and_provenance() -> None:
    native = read_native_table(NATIVE_PATH).data

    assert native.schema == NATIVE_SCHEMA
    assert native.height == 26_258
    assert native["site_no"].to_list() == sorted(native["site_no"].to_list())
    assert native["retrieved_at"].n_unique() == 1
    assert native["retrieved_at"].item(0) == ATTESTED_DATETIME
    ids = native["site_no"].to_list()
    digest = hashlib.sha256(json.dumps(ids, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    assert digest == "8ad79dac66b25a9dc46ebd30b650c1e647b44d9b31c9bc4fdd17c5e46f4ee241"
    total_records = 0
    for row in native.iter_rows(named=True):
        aligned = list(zip(*(row[name] for name in SERIES_ONLY_FIELDS), strict=True))
        total_records += len(aligned)
        assert aligned == sorted(aligned)
    assert total_records == 2_036_546


def test_committed_native_table_representative_station() -> None:
    row = read_native_table(NATIVE_PATH).data.filter(pl.col("site_no") == "02339495").row(0, named=True)

    assert row["station_nm"] == "OSELIGEE CREEK NEAR LANETT AL"
    assert row["dec_coord_datum_cd"] == "NAD83"
    assert row["alt_va"] == ""
    assert row["alt_datum_cd"] == ""
    assert row["drain_area_va"] == "86.4"
    assert row["tz_cd"] == "CST"
    assert row["basin_cd"] == ""
    assert len({len(row[name]) for name in SERIES_ONLY_FIELDS}) == 1
    records = [
        dict(zip(SERIES_ONLY_FIELDS, values, strict=True))
        for values in zip(*(row[name] for name in SERIES_ONLY_FIELDS), strict=True)
    ]
    keys = {(record["data_type_cd"], record["parm_cd"], record["stat_cd"]) for record in records}
    assert len(records) == len(keys) == 21
    assert {
        ("dv", "00060", "00003"),
        ("dv", "00065", "00003"),
        ("uv", "00060", ""),
        ("uv", "00065", ""),
    } <= keys


def test_fixture_refresh_frame_equals_matching_committed_subset() -> None:
    committed_row = read_native_table(NATIVE_PATH).data.filter(pl.col("site_no") == "02339495").row(0, named=True)
    wanted = {
        ("dv", "00060", "00003"),
        ("dv", "00065", "00003"),
        ("uv", "00060", ""),
        ("uv", "00065", ""),
    }
    indexes = [
        index
        for index, key in enumerate(
            zip(committed_row["data_type_cd"], committed_row["parm_cd"], committed_row["stat_cd"], strict=True)
        )
        if key in wanted
    ]
    subset_row = {name: committed_row[name] for name in EXPANDED_HEADER}
    subset_row.update({name: [committed_row[name][index] for index in indexes] for name in SERIES_ONLY_FIELDS})
    subset_row["retrieved_at"] = committed_row["retrieved_at"]
    committed_subset = pl.DataFrame([subset_row], schema=NATIVE_SCHEMA)

    pl_testing.assert_frame_equal(_fixture_refresh().value.data, committed_subset, check_exact=True)
