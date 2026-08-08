from __future__ import annotations

import hashlib
import io
import json
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import polars.testing as pl_testing
import pytest

from rivretrieve._internal.catalogues.native import NativeTable, RetrievedAt, read_native_table
from rivretrieve._internal.catalogues.schemas import (
    PRODUCT_CATALOG_SCHEMA,
    STATION_CATALOG_SCHEMA,
    STATION_PRODUCT_CATALOG_SCHEMA,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.usgs_nwis import generate_catalogue as generator
from rivretrieve._internal.providers.usgs_nwis.generate_catalogue import PRODUCT_DEFINITIONS
from rivretrieve._internal.providers.usgs_nwis.origins import STATION_CATALOGUE_ORIGINS

SERIES_FIXTURE_PATH = Path("tests/test_data/usgs_nwis_metadata_series.json")
EXPANDED_FIXTURE_PATH = Path("tests/test_data/usgs_nwis_metadata_expanded.json")
NATIVE_PATH = Path("src/rivretrieve/_internal/providers/usgs_nwis/catalogue/native.parquet")
CATALOGUE_PATH = NATIVE_PATH.parent
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


def _series_row(
    data_type_cd: str,
    parm_cd: str,
    stat_cd: str,
    begin_date: str = "2001-01-02",
    end_date: str = "2025-03-04",
) -> dict[str, str]:
    row = dict.fromkeys(SERIES_ONLY_FIELDS, "")
    row.update(
        data_type_cd=data_type_cd,
        parm_cd=parm_cd,
        stat_cd=stat_cd,
        begin_date=begin_date,
        end_date=end_date,
    )
    return row


def _complete_product_series() -> list[dict[str, str]]:
    return [_series_row(*definition.series_key) for definition in PRODUCT_DEFINITIONS]


def _native_table(station_specs: list[dict[str, object]] | None = None) -> NativeTable:
    specs = station_specs or [{"site_no": "station-a", "series": _complete_product_series()}]
    rows: list[dict[str, object]] = []
    for index, spec in enumerate(specs):
        source_series = spec.get("series", _complete_product_series())
        assert isinstance(source_series, list)
        row: dict[str, object] = dict.fromkeys(EXPANDED_HEADER, "")
        row.update(
            agency_cd="USGS",
            site_no=spec.get("site_no", f"station-{index}"),
            station_nm=f"Station {index}",
            dec_lat_va=spec.get("dec_lat_va", "40.125"),
            dec_long_va=spec.get("dec_long_va", "-72.875"),
            dec_coord_datum_cd=spec.get("datum", "NAD83"),
        )
        row.update({name: [series[name] for series in source_series] for name in SERIES_ONLY_FIELDS})
        row["retrieved_at"] = spec.get("retrieved_at", ATTESTED_DATETIME)
        rows.append(row)
    return NativeTable(pl.DataFrame(rows, schema=NATIVE_SCHEMA))


def _frame_content_sha256(frame: pl.DataFrame) -> str:
    rows = [
        [value.isoformat() if isinstance(value, date | datetime) else value for value in row]
        for row in frame.iter_rows()
    ]
    return hashlib.sha256(json.dumps(rows, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def test_existing_generation_path_does_not_fabricate_all_unknown_station_products() -> None:
    catalogue = generator.build_catalogue(read_native_table(NATIVE_PATH), STATION_CATALOGUE_ORIGINS)

    assert "unknown" not in set(catalogue.station_products["availability"].cast(str))


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
    expanded_template = _fixture_rows(EXPANDED_FIXTURE_PATH)[0]
    series_template = _fixture_rows(SERIES_FIXTURE_PATH)[0]
    expanded_rows: list[dict[str, str]] = []
    series_rows: list[dict[str, str]] = []
    for index in range(9_999):
        site_no = f"{index:08d}"
        expanded_rows.append({**expanded_template, "site_no": site_no})
        for definition in PRODUCT_DEFINITIONS:
            data_type_cd, parm_cd, stat_cd = definition.series_key
            series_rows.append(
                {
                    **series_template,
                    "site_no": site_no,
                    "data_type_cd": data_type_cd,
                    "parm_cd": parm_cd,
                    "stat_cd": stat_cd,
                }
            )

    with pytest.raises(
        FatalContractError,
        match="USGS supplied-national native input has only 9,999 stations; expected at least 10,000",
    ):
        generator.refresh_native_table(
            series_rows,
            expanded_rows,
            retrieved_at=ATTESTED_RETRIEVED_AT,
            input_kind=generator.NativeInputKind.SUPPLIED_NATIONAL,
        )


def _national_product_records(*, omitted_key: tuple[str, str, str] | None = None) -> dict[str, list[tuple[str, ...]]]:
    records: list[tuple[str, ...]] = []
    for definition in PRODUCT_DEFINITIONS:
        key = definition.series_key
        if key == omitted_key:
            continue
        record = dict.fromkeys(SERIES_ONLY_FIELDS, "")
        record.update(zip(("data_type_cd", "parm_cd", "stat_cd"), key, strict=True))
        records.append(tuple(record[name] for name in SERIES_ONLY_FIELDS))
    return {"national": records}


def test_national_product_validation_rejects_a_product_with_zero_matching_rows() -> None:
    missing_key = ("dv", "00065", "00001")

    with pytest.raises(FatalContractError, match="zero matching series rows"):
        generator._validate_national_products(_national_product_records(omitted_key=missing_key))


def test_national_product_validation_accepts_the_complete_product_key_set() -> None:
    generator._validate_national_products(_national_product_records())


def test_station_product_matching_covers_absent_unique_duplicate_agreeing_blank_and_conflicting_series() -> None:
    definitions = {definition.product_id: definition for definition in PRODUCT_DEFINITIONS}
    first_series = [
        _series_row(*definitions["discharge_daily_mean"].series_key),
        _series_row(*definitions["discharge_instantaneous"].series_key),
        _series_row(*definitions["discharge_instantaneous"].series_key),
        _series_row(*definitions["stage_daily_mean"].series_key, begin_date="", end_date=""),
        _series_row(*definitions["stage_daily_max"].series_key, begin_date="2000-01-01", end_date="2010-01-01"),
        _series_row(*definitions["stage_daily_max"].series_key, begin_date="2001-01-01", end_date="2010-01-01"),
        _series_row(*definitions["stage_instantaneous"].series_key),
    ]
    native = _native_table(
        [
            {"site_no": "outcomes", "series": first_series},
            {"site_no": "national-coverage", "series": _complete_product_series()},
        ]
    )

    result = generator.build_catalogue(native, STATION_CATALOGUE_ORIGINS).station_products.filter(
        pl.col("station_id") == "outcomes"
    )
    rows = {row["product_id"]: row for row in result.iter_rows(named=True)}
    assert (
        rows["discharge_daily_mean"]
        | {
            "availability": "available",
            "availability_reason": None,
            "published_record_start_date": date(2001, 1, 2),
            "published_record_end_date": date(2025, 3, 4),
        }
        == rows["discharge_daily_mean"]
    )
    assert rows["discharge_instantaneous"]["availability"] == "available"
    assert rows["discharge_instantaneous"]["published_record_start_date"] == date(2001, 1, 2)
    assert rows["discharge_instantaneous"]["published_record_end_date"] == date(2025, 3, 4)
    assert rows["stage_daily_mean"]["availability_reason"] == "Matching USGS source series states blank coverage dates"
    assert (
        rows["stage_daily_max"]["availability_reason"]
        == "Several matching USGS source series state conflicting coverage boundaries"
    )
    assert rows["stage_daily_min"]["availability"] == "unavailable"
    assert (
        rows["stage_daily_min"]["availability_reason"]
        == "No matching USGS source series was published for this station-product"
    )
    assert rows["stage_daily_min"]["published_record_start_date"] is None
    assert rows["stage_daily_min"]["published_record_end_date"] is None


@pytest.mark.parametrize("omitted", PRODUCT_DEFINITIONS, ids=lambda definition: definition.product_id)
def test_native_build_rejects_product_with_zero_national_matches(omitted: object) -> None:
    assert isinstance(omitted, generator.ProductDefinition)
    series = [row for row in _complete_product_series() if _series_key_from_row(row) != omitted.series_key]
    native = _native_table(
        [
            {"site_no": "first", "series": series},
            {"site_no": "second", "series": list(series)},
        ]
    )

    with pytest.raises(FatalContractError, match=omitted.product_id):
        generator.build_catalogue(native, STATION_CATALOGUE_ORIGINS)


def _series_key_from_row(row: dict[str, str]) -> tuple[str, str, str]:
    return (row["data_type_cd"], row["parm_cd"], row["stat_cd"])


def test_native_build_allows_a_product_absent_locally_when_present_nationally() -> None:
    rhode_island_series = [
        row
        for row in _complete_product_series()
        if _series_key_from_row(row) not in {("dv", "00065", "00001"), ("dv", "00065", "00002")}
    ]
    native = _native_table(
        [
            {"site_no": "rhode-island", "series": rhode_island_series},
            {"site_no": "elsewhere", "series": _complete_product_series()},
        ]
    )

    station_products = generator.build_catalogue(native, STATION_CATALOGUE_ORIGINS).station_products
    local = station_products.filter(pl.col("station_id") == "rhode-island")
    assert set(
        local.filter(pl.col("product_id").is_in(["stage_daily_max", "stage_daily_min"]))["availability"].cast(str)
    ) == {"unavailable"}


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("NAD27", "EPSG:4267"),
        ("NAD83", "EPSG:4269"),
        ("OLDHI", "EPSG:4135"),
        ("WGS72", "EPSG:4322"),
        ("WGS84", "EPSG:4326"),
        ("OLDAK", "unknown"),
        ("OLDGUAM", "unknown"),
        ("OLDPR", "unknown"),
        ("OLDSAMOA", "unknown"),
        ("PUERTORICO", "unknown"),
        ("", "unknown"),
        ("UNRECOGNISED", "unknown"),
    ],
)
def test_datum_token_maps_only_when_licensed(token: str, expected: str) -> None:
    catalogue = generator.build_catalogue(_native_table([{"datum": token}]), STATION_CATALOGUE_ORIGINS)

    assert catalogue.stations["crs"].item() == expected


def test_station_frame_preserves_native_identity_and_coordinates_exactly() -> None:
    native = _native_table([{"site_no": "  exact-id  ", "dec_lat_va": "41.125", "dec_long_va": "-73.875"}])

    stations = generator.build_catalogue(native, STATION_CATALOGUE_ORIGINS).stations
    expected = pl.DataFrame(
        [
            {
                "provider_id": "usgs_nwis",
                "station_id": "  exact-id  ",
                "latitude": 41.125,
                "longitude": -73.875,
                "crs": "EPSG:4269",
            }
        ],
        schema=STATION_CATALOG_SCHEMA.polars_schema,
    )
    pl_testing.assert_frame_equal(stations, expected, check_exact=True)


def test_catalogue_dates_derive_only_from_native_retrieved_at() -> None:
    native = _native_table(
        [
            {"site_no": "older", "retrieved_at": datetime(2026, 7, 31, 23, tzinfo=UTC)},
            {"site_no": "newer", "retrieved_at": datetime(2026, 8, 3, 1, tzinfo=UTC)},
        ]
    )

    catalogue = generator.build_catalogue(native, STATION_CATALOGUE_ORIGINS)
    dates = {
        station_id: set(rows["last_catalogue_check"])
        for station_id, rows in catalogue.station_products.partition_by("station_id", as_dict=True).items()
    }
    assert dates[("older",)] == {date(2026, 7, 31)}
    assert dates[("newer",)] == {date(2026, 8, 3)}
    assert catalogue.provider_info["catalogue_version"] == "2026-08-03"


def test_usgs_build_is_gated_on_origins() -> None:
    broken = dict(STATION_CATALOGUE_ORIGINS)
    del broken["longitude"]

    with pytest.raises(
        FatalContractError,
        match=r"usgs_nwis\.longitude: canonical column has no origin declaration",
    ):
        generator.build_catalogue(_native_table(), broken)


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("site_no", " ", "blank required site_no"),
        ("dec_lat_va", "", "blank required dec_lat_va"),
        ("dec_long_va", " ", "blank required dec_long_va"),
        ("dec_lat_va", "north", "nonnumeric required dec_lat_va"),
        ("dec_long_va", "west", "nonnumeric required dec_long_va"),
    ],
)
def test_native_build_rejects_invalid_required_native_value(column: str, value: str, message: str) -> None:
    spec: dict[str, object] = {column: value}

    with pytest.raises(FatalContractError, match=message):
        generator.build_catalogue(_native_table([spec]), STATION_CATALOGUE_ORIGINS)


def test_native_build_rejects_malformed_series_alignment() -> None:
    native = _native_table()
    malformed = native.data.with_columns(pl.col("end_date").list.slice(1).alias("end_date"))

    with pytest.raises(FatalContractError, match="station-a.*misaligned source-series"):
        generator.build_catalogue(NativeTable(malformed), STATION_CATALOGUE_ORIGINS)


def test_native_build_rejects_non_exact_schema() -> None:
    native = _native_table()
    reordered = native.data.select("site_no", *[column for column in native.data.columns if column != "site_no"])

    with pytest.raises(FatalContractError, match="USGS native table does not have the exact required schema"):
        generator.build_catalogue(NativeTable(reordered), STATION_CATALOGUE_ORIGINS)


def test_native_build_rejects_invalid_nonblank_coverage_date() -> None:
    series = _complete_product_series()
    series[0]["begin_date"] = "not-a-date"

    with pytest.raises(FatalContractError, match="invalid nonblank coverage date"):
        generator.build_catalogue(_native_table([{"series": series}]), STATION_CATALOGUE_ORIGINS)


def test_native_build_rejects_impossible_retrieval_timestamp() -> None:
    with pytest.raises(FatalContractError, match="native table retrieved_at must not contain nulls"):
        _native_table([{"retrieved_at": None}])


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
    capsys: pytest.CaptureFixture[str],
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
    assert capsys.readouterr().out == (
        f"USGS native table canonical SHA-256: {generator.native_table_content_sha256(expected.value)}\n"
    )


@pytest.mark.parametrize(
    "case",
    [
        "removed-fixture",
        "live-with-out",
        "rdb-with-out",
    ],
)
def test_cli_rejects_cross_mode_combinations(
    case: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        pytest.fail("invalid CLI reached file or network seam")

    monkeypatch.setattr(generator, "read_native_table", fail)
    monkeypatch.setattr(generator, "refresh_native_table_from_live", fail)
    monkeypatch.setattr(generator, "refresh_native_table_from_rdb_directory", fail)
    argv_by_case = {
        "removed-fixture": ["--fixture", "removed.json"],
        "live-with-out": [
            "--live",
            "--out",
            "catalogue",
            "--native-out",
            "native.parquet",
            "--retrieved-at",
            "2026-08-02T01:14:11Z",
        ],
        "rdb-with-out": [
            "--rdb-dir",
            str(tmp_path.resolve()),
            "--out",
            "catalogue",
            "--native-out",
            "native.parquet",
            "--retrieved-at",
            "2026-08-02T01:14:11Z",
        ],
    }

    with pytest.raises(SystemExit):
        generator.main(argv_by_case[case])


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["--native", "native.parquet"], "--native requires --out"),
        (
            ["--native", "native.parquet", "--out", "catalogue", "--native-out", "other.parquet"],
            "--native cannot be combined with --native-out or --retrieved-at",
        ),
        (
            [
                "--native",
                "native.parquet",
                "--out",
                "catalogue",
                "--retrieved-at",
                "2026-08-02T01:14:11Z",
            ],
            "--native cannot be combined with --native-out or --retrieved-at",
        ),
    ],
    ids=["requires-out", "rejects-native-out", "rejects-retrieved-at"],
)
def test_cli_rejects_invalid_native_mode_options(
    argv: list[str],
    message: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        generator,
        "read_native_table",
        lambda path: pytest.fail(f"invalid CLI reached native reader: {path}"),
    )

    with pytest.raises(SystemExit):
        generator.main(argv)

    assert message in capsys.readouterr().err


def test_cli_rejects_relative_rdb_directory(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        generator,
        "refresh_native_table_from_rdb_directory",
        lambda *args, **kwargs: pytest.fail("invalid CLI reached RDB reader"),
    )

    with pytest.raises(SystemExit):
        generator.main(
            [
                "--rdb-dir",
                "relative-rdb",
                "--native-out",
                "native.parquet",
                "--retrieved-at",
                "2026-08-02T01:14:11Z",
            ]
        )

    assert "--rdb-dir must be an absolute path" in capsys.readouterr().err


def test_committed_native_table_exact_schema_counts_and_provenance() -> None:
    native_table = read_native_table(NATIVE_PATH)
    native = native_table.data

    assert native.schema == NATIVE_SCHEMA
    assert native.height == 26_258
    assert native["site_no"].to_list() == sorted(native["site_no"].to_list())
    assert native["retrieved_at"].n_unique() == 1
    assert native["retrieved_at"].item(0) == ATTESTED_DATETIME
    ids = native["site_no"].to_list()
    digest = hashlib.sha256(json.dumps(ids, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    assert digest == "8ad79dac66b25a9dc46ebd30b650c1e647b44d9b31c9bc4fdd17c5e46f4ee241"
    assert generator.native_table_content_sha256(native_table) == (
        "e4384cea2ff00e5a120d244977d2dd75bc00ec4c8ba941e3e83f06239cd5777f"
    )
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


def test_committed_canonical_artifacts_have_pinned_whole_content() -> None:
    provider_bytes = (CATALOGUE_PATH / "provider.json").read_bytes()
    products = pl.read_parquet(CATALOGUE_PATH / "products.parquet")
    stations = pl.read_parquet(CATALOGUE_PATH / "stations.parquet")
    station_products = pl.read_parquet(CATALOGUE_PATH / "station_products.parquet")

    assert products.schema == PRODUCT_CATALOG_SCHEMA.polars_schema
    assert stations.schema == STATION_CATALOG_SCHEMA.polars_schema
    assert station_products.schema == STATION_PRODUCT_CATALOG_SCHEMA.polars_schema
    assert (
        hashlib.sha256(provider_bytes).hexdigest() == "c0a4074f979ac2670695b08c325a55b9be548591a18db53ae7011fd054b02f59"
    )
    assert _frame_content_sha256(products) == "0bb5ae6f406f5258119a9c0d198a8db1a5e77a211d0d693186bb18d01cacbccc"
    assert _frame_content_sha256(stations) == "27b3dfc6d71445798eda982d6f9d11de4839be1f6adbb30faed8052cefdc26c7"
    assert _frame_content_sha256(station_products) == (
        "a8ac1cc876ef1b2aac04fc09141eb9b0e5e59df3c767f7bddfdcb27fc59152d8"
    )


def test_native_build_is_network_free_and_byte_deterministic(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def fail_network(*args: object, **kwargs: object) -> object:
        calls.append("network")
        raise AssertionError("network must not be accessed during build")

    monkeypatch.setattr(generator, "read_live_native_rows", fail_network)
    monkeypatch.setattr(generator.urllib.request, "urlopen", fail_network)
    first = tmp_path / "first"
    second = tmp_path / "second"

    assert generator.main(["--native", str(NATIVE_PATH), "--out", str(first)]) == 0
    assert generator.main(["--native", str(NATIVE_PATH), "--out", str(second)]) == 0
    assert calls == []
    for artifact_name in ("provider.json", "products.parquet", "stations.parquet", "station_products.parquet"):
        assert (first / artifact_name).read_bytes() == (second / artifact_name).read_bytes()
        assert (first / artifact_name).read_bytes() == (CATALOGUE_PATH / artifact_name).read_bytes()
