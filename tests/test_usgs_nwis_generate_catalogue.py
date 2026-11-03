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
from rivretrieve._internal.recordings import read_recording

# Decoded historical native-table subsets, not HTTP response recordings.
# Exact equality with the retained snapshot is tested below.
SERIES_FIXTURE_PATH = Path("tests/test_data/usgs_nwis_metadata_series.json")
EXPANDED_FIXTURE_PATH = Path("tests/test_data/usgs_nwis_metadata_expanded.json")
NATIVE_PATH = Path("tests/test_data/usgs_nwis_historical/native.parquet")
CATALOGUE_PATH = Path("src/rivretrieve/_internal/providers/usgs_nwis/catalogue")
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


def _fixture_refresh(retained_evidence_root) -> object:
    return generator.refresh_native_table_from_fixtures(
        (retained_evidence_root / SERIES_FIXTURE_PATH),
        (retained_evidence_root / EXPANDED_FIXTURE_PATH),
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


@pytest.mark.derived("tests/test_data/usgs_nwis_metadata_series.json")
def test_strict_rdb_parser_preserves_source_strings_and_empty_fields(
    retained_evidence_root,
) -> None:
    rows = _fixture_rows(retained_evidence_root / SERIES_FIXTURE_PATH)

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
@pytest.mark.derived("tests/test_data/usgs_nwis_metadata_series.json")
def test_strict_rdb_parser_rejects_non_exact_headers(retained_evidence_root, header: tuple[str, ...]) -> None:
    rows = _fixture_rows(retained_evidence_root / SERIES_FIXTURE_PATH)
    values = [rows[0].get(name, "value") for name in header]
    text = "\n".join(("\t".join(header), "\t".join("1s" for _ in header), "\t".join(values)))

    with pytest.raises(FatalContractError, match="header"):
        generator.parse_series_rdb(text)


@pytest.mark.derived("tests/test_data/usgs_nwis_metadata_expanded.json")
def test_strict_rdb_parser_rejects_non_exact_format_row(
    retained_evidence_root,
) -> None:
    rows = _fixture_rows(retained_evidence_root / EXPANDED_FIXTURE_PATH)
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
@pytest.mark.derived(
    "tests/test_data/usgs_nwis_metadata_expanded.json",
    "tests/test_data/usgs_nwis_metadata_series.json",
)
def test_refresh_rejects_absent_or_blank_site_no(retained_evidence_root, site_no: str | None) -> None:
    series = _fixture_rows(retained_evidence_root / SERIES_FIXTURE_PATH)
    expanded = _fixture_rows(retained_evidence_root / EXPANDED_FIXTURE_PATH)
    if site_no is None:
        del series[0]["site_no"]
    else:
        series[0]["site_no"] = site_no

    with pytest.raises(FatalContractError, match="site_no"):
        generator.refresh_native_table(
            series,
            expanded,
            retrieved_at=ATTESTED_RETRIEVED_AT,
        )


@pytest.mark.derived(
    "tests/test_data/usgs_nwis_metadata_expanded.json",
    "tests/test_data/usgs_nwis_metadata_series.json",
)
def test_refresh_rejects_series_without_expanded_site(retained_evidence_root) -> None:
    series = _fixture_rows(retained_evidence_root / SERIES_FIXTURE_PATH)
    expanded = _fixture_rows(retained_evidence_root / EXPANDED_FIXTURE_PATH)
    series[0]["site_no"] = "99999999"

    with pytest.raises(FatalContractError, match="series identities have no expanded site record"):
        generator.refresh_native_table(
            series,
            expanded,
            retrieved_at=ATTESTED_RETRIEVED_AT,
        )


@pytest.mark.derived(
    "tests/test_data/usgs_nwis_metadata_expanded.json",
    "tests/test_data/usgs_nwis_metadata_series.json",
)
def test_refresh_rejects_conflicting_repeated_fact_within_series(
    retained_evidence_root,
) -> None:
    series = _fixture_rows(retained_evidence_root / SERIES_FIXTURE_PATH)
    series[1]["station_nm"] = "CONFLICT"

    with pytest.raises(FatalContractError, match="station_nm"):
        generator.refresh_native_table(
            series,
            _fixture_rows(retained_evidence_root / EXPANDED_FIXTURE_PATH),
            retrieved_at=ATTESTED_RETRIEVED_AT,
        )


@pytest.mark.derived(
    "tests/test_data/usgs_nwis_metadata_expanded.json",
    "tests/test_data/usgs_nwis_metadata_series.json",
)
def test_refresh_rejects_conflicting_repeated_fact_between_passes(
    retained_evidence_root,
) -> None:
    expanded = _fixture_rows(retained_evidence_root / EXPANDED_FIXTURE_PATH)
    expanded[0]["huc_cd"] = "CONFLICT"

    with pytest.raises(FatalContractError, match="huc_cd"):
        generator.refresh_native_table(
            _fixture_rows(retained_evidence_root / SERIES_FIXTURE_PATH),
            expanded,
            retrieved_at=ATTESTED_RETRIEVED_AT,
        )


@pytest.mark.derived(
    "tests/test_data/usgs_nwis_metadata_expanded.json",
    "tests/test_data/usgs_nwis_metadata_series.json",
)
def test_refresh_rejects_malformed_series_shape(
    retained_evidence_root,
) -> None:
    series = _fixture_rows(retained_evidence_root / SERIES_FIXTURE_PATH)
    del series[0]["count_nu"]

    with pytest.raises(FatalContractError, match="series row"):
        generator.refresh_native_table(
            series,
            _fixture_rows(retained_evidence_root / EXPANDED_FIXTURE_PATH),
            retrieved_at=ATTESTED_RETRIEVED_AT,
        )


def test_native_build_rejects_impossible_retrieval_timestamp() -> None:
    with pytest.raises(FatalContractError, match="native table retrieved_at must not contain nulls"):
        _native_table([{"retrieved_at": None}])


@pytest.mark.derived(
    "tests/test_data/usgs_nwis_metadata_expanded.json",
    "tests/test_data/usgs_nwis_metadata_series.json",
)
def test_fixture_refresh_preserves_exact_source_data_and_alignment(
    retained_evidence_root,
) -> None:
    series_rows = _fixture_rows(retained_evidence_root / SERIES_FIXTURE_PATH)
    expanded_row = _fixture_rows(retained_evidence_root / EXPANDED_FIXTURE_PATH)[0]
    ordered_series = sorted(series_rows, key=lambda row: tuple(row[name] for name in SERIES_HEADER))
    expected_row: dict[str, object] = dict(expanded_row)
    expected_row.update({name: [row[name] for row in ordered_series] for name in SERIES_ONLY_FIELDS})
    expected_row["retrieved_at"] = ATTESTED_DATETIME
    expected = pl.DataFrame([expected_row], schema=NATIVE_SCHEMA)

    outcome = _fixture_refresh(retained_evidence_root)

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


def test_live_transport_includes_all_site_types_across_50_states_and_dc(monkeypatch: pytest.MonkeyPatch) -> None:
    from urllib.parse import parse_qs, urlsplit

    # Authored source rows: site classification must not exclude daily discharge.
    expanded_row = dict.fromkeys(EXPANDED_HEADER, "")
    expanded_row.update(agency_cd="USGS", site_no="synthetic-field", site_tp_cd="FA-FON")
    series_row = {name: expanded_row.get(name, "") for name in SERIES_HEADER}
    series_row.update(data_type_cd="dv", parm_cd="00060", stat_cd="00003")
    series_bytes = _rdb_text(SERIES_HEADER, SERIES_FORMAT, [series_row]).encode()
    expanded_bytes = _rdb_text(EXPANDED_HEADER, EXPANDED_FORMAT, [expanded_row]).encode()
    calls: list[str] = []

    def fake_urlopen(url: str, *, timeout: int) -> _FixtureResponse:
        calls.append(url)
        return _FixtureResponse(series_bytes if "seriesCatalogOutput=true" in url else expanded_bytes)

    monkeypatch.setattr(generator.urllib.request, "urlopen", fake_urlopen)
    series, expanded = generator.read_live_native_rows()

    states = [
        "AL",
        "AK",
        "AZ",
        "AR",
        "CA",
        "CO",
        "CT",
        "DE",
        "FL",
        "GA",
        "HI",
        "ID",
        "IL",
        "IN",
        "IA",
        "KS",
        "KY",
        "LA",
        "ME",
        "MD",
        "MA",
        "MI",
        "MN",
        "MS",
        "MO",
        "MT",
        "NE",
        "NV",
        "NH",
        "NJ",
        "NM",
        "NY",
        "NC",
        "ND",
        "OH",
        "OK",
        "OR",
        "PA",
        "RI",
        "SC",
        "SD",
        "TN",
        "TX",
        "UT",
        "VT",
        "VA",
        "WA",
        "WV",
        "WI",
        "WY",
        "DC",
    ]
    expected = [
        {
            "format": ["rdb"],
            "parameterCd": ["00060,00065"],
            "stateCd": [state],
            **output,
        }
        for state in states
        for output in ({"seriesCatalogOutput": ["true"]}, {"siteOutput": ["expanded"]})
    ]
    actual = [parse_qs(urlsplit(url).query) for url in calls]
    assert len(actual) == 102
    assert all(query in actual for query in expected)
    assert series == [series_row] * 51
    assert expanded == [expanded_row] * 51


@pytest.mark.derived("tests/test_data/usgs_nwis_historical/native.parquet")
def test_historical_native_table_exact_schema_counts_and_provenance(
    retained_evidence_root,
) -> None:
    native_table = read_native_table(retained_evidence_root / NATIVE_PATH)
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


@pytest.mark.derived("tests/test_data/usgs_nwis_historical/native.parquet")
def test_historical_native_table_representative_station(
    retained_evidence_root,
) -> None:
    row = (
        read_native_table(retained_evidence_root / NATIVE_PATH)
        .data.filter(pl.col("site_no") == "02339495")
        .row(0, named=True)
    )

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


@pytest.mark.derived(
    "tests/test_data/usgs_nwis_historical/native.parquet",
    "tests/test_data/usgs_nwis_metadata_expanded.json",
    "tests/test_data/usgs_nwis_metadata_series.json",
)
def test_fixture_refresh_frame_equals_matching_historical_subset(
    retained_evidence_root,
) -> None:
    committed_row = (
        read_native_table(retained_evidence_root / NATIVE_PATH)
        .data.filter(pl.col("site_no") == "02339495")
        .row(0, named=True)
    )
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

    pl_testing.assert_frame_equal(
        _fixture_refresh(retained_evidence_root).value.data, committed_subset, check_exact=True
    )


@pytest.mark.derived(
    "research/usgs-modern-coverage/legacy-catalogue/products.parquet",
    "research/usgs-modern-coverage/legacy-catalogue/provider.json",
    "research/usgs-modern-coverage/legacy-catalogue/station_products.parquet",
    "research/usgs-modern-coverage/legacy-catalogue/stations.parquet",
)
def test_committed_canonical_artifacts_have_pinned_whole_content(
    retained_evidence_root,
) -> None:
    provider_bytes = (
        (retained_evidence_root / "research/usgs-modern-coverage/legacy-catalogue") / "provider.json"
    ).read_bytes()
    products = pl.read_parquet(
        (retained_evidence_root / "research/usgs-modern-coverage/legacy-catalogue") / "products.parquet"
    )
    stations = pl.read_parquet(
        (retained_evidence_root / "research/usgs-modern-coverage/legacy-catalogue") / "stations.parquet"
    )
    station_products = pl.read_parquet(
        (retained_evidence_root / "research/usgs-modern-coverage/legacy-catalogue") / "station_products.parquet"
    )

    assert products.schema == PRODUCT_CATALOG_SCHEMA.polars_schema
    assert stations.schema == STATION_CATALOG_SCHEMA.polars_schema
    assert station_products.schema == STATION_PRODUCT_CATALOG_SCHEMA.polars_schema
    assert (
        hashlib.sha256(provider_bytes).hexdigest() == "69fce539d44cae99e42bfd8e51e60b49f2e0d5e0c71a253ce7068e45eb685d38"
    )
    assert products["period_anchor"].unique().to_list() == ["unknown"]
    assert _frame_content_sha256(products) == "31d4d14c535aff2a04be0deb7e738c575ac4f736956db6dbfb2279f3e267aa59"
    assert _frame_content_sha256(stations) == "27b3dfc6d71445798eda982d6f9d11de4839be1f6adbb30faed8052cefdc26c7"
    assert _frame_content_sha256(station_products) == (
        "a8ac1cc876ef1b2aac04fc09141eb9b0e5e59df3c767f7bddfdcb27fc59152d8"
    )


@pytest.mark.recorded(
    "tests/test_data/usgs_nwis_02339495_site_expanded.recording.json",
    "tests/test_data/usgs_nwis_02339495_site_series.recording.json",
)
def test_live_rdb_recordings_preserve_source_strings_and_native_alignment(
    retained_evidence_root,
) -> None:
    data = retained_evidence_root / "tests/test_data"
    series_recording = read_recording(data / "usgs_nwis_02339495_site_series.recording.json")
    expanded_recording = read_recording(data / "usgs_nwis_02339495_site_expanded.recording.json")
    series = generator.parse_series_rdb(series_recording.content.decode("utf-8"))
    expanded = generator.parse_expanded_rdb(expanded_recording.content.decode("utf-8"))
    assert len(series) == 21
    assert len(expanded) == 1
    instantaneous = next(row for row in series if row["ts_id"] == "2761")
    assert instantaneous["stat_cd"] == ""
    assert instantaneous["loc_web_ds"] == "[(2)]"
    assert expanded[0]["station_nm"] == "OSELIGEE CREEK NEAR LANETT AL"
    assert expanded[0]["alt_va"] == ""
    assert expanded[0]["drain_area_va"] == "86.4"

    refreshed = generator.refresh_native_table(
        series,
        expanded,
        retrieved_at=RetrievedAt(expanded_recording.retrieved_at),
    )
    ordered = sorted(series, key=lambda row: tuple(row[name] for name in SERIES_HEADER))
    expected_row: dict[str, object] = dict(expanded[0])
    expected_row.update({name: [row[name] for row in ordered] for name in SERIES_ONLY_FIELDS})
    expected_row["retrieved_at"] = expanded_recording.retrieved_at
    pl_testing.assert_frame_equal(
        refreshed.value.data, pl.DataFrame([expected_row], schema=NATIVE_SCHEMA), check_exact=True
    )
    assert refreshed.issues == ()


def test_missing_publication_inputs_leave_destination_untouched(tmp_path: Path) -> None:
    from types import SimpleNamespace

    output = tmp_path / "catalogue"
    # The prerequisite is present. No catalogue frames should be read or written.
    catalogue = SimpleNamespace(source_descriptions=object())
    with pytest.raises(FatalContractError, match="requires explicit build_inputs and native_table"):
        generator.write_catalogue(catalogue, output)
    assert not output.exists()


def test_current_publication_requires_selected_provenance_before_writing(tmp_path):
    from types import SimpleNamespace

    native = _native_table()
    catalogue = SimpleNamespace(source_descriptions=object())
    output = tmp_path / "output"
    with pytest.raises(FatalContractError, match="explicit acquisition_provenance"):
        generator.write_catalogue(catalogue, output, build_inputs=object(), native_table=native)
    assert not output.exists()


def _modern_cli_arguments(tmp_path):
    baseline = tmp_path / "baseline.json"
    baseline.write_text("{}")
    manifest = tmp_path / "retention.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "historical_series_ids": [],
                "retained_station_ids": [],
            }
        )
    )
    return [
        "--baseline-locations",
        str(baseline),
        "--baseline-sha256",
        hashlib.sha256(baseline.read_bytes()).hexdigest(),
        "--modern-metadata",
        str(tmp_path / "metadata"),
        "--monitoring-locations",
        str(tmp_path / "locations.json"),
        "--retention-manifest",
        str(manifest),
        "--retained-metadata",
        str(tmp_path / "historical"),
    ]


def test_modern_cli_requires_output_before_reading_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(generator, "read_modern_metadata", lambda _: pytest.fail("unexpected source read"))
    with pytest.raises(SystemExit):
        generator.main(_modern_cli_arguments(tmp_path))


@pytest.mark.parametrize(
    "manifest",
    [
        [],
        {"schema_version": 2, "historical_series_ids": [], "retained_station_ids": []},
        {"schema_version": 1, "historical_series_ids": ["same", "same"], "retained_station_ids": []},
        {"schema_version": 1, "historical_series_ids": [], "retained_station_ids": [""]},
    ],
)
def test_modern_cli_rejects_invalid_retention_before_reading_sources(tmp_path, monkeypatch, manifest):
    args = _modern_cli_arguments(tmp_path)
    (tmp_path / "retention.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(generator, "read_modern_metadata", lambda _: pytest.fail("unexpected source read"))
    with pytest.raises(FatalContractError, match="retention manifest"):
        generator.main([*args, "--native-out", str(tmp_path / "native.parquet")])
    assert not (tmp_path / "native.parquet").exists()


def test_modern_cli_requires_publication_inputs_before_reading_or_writing(tmp_path, monkeypatch):
    monkeypatch.setattr(generator, "read_modern_metadata", lambda _: pytest.fail("unexpected source read"))
    output = tmp_path / "catalogue"
    native = tmp_path / "native.parquet"
    with pytest.raises(SystemExit):
        generator.main([*_modern_cli_arguments(tmp_path), "--out", str(output), "--native-out", str(native)])
    assert not output.exists()
    assert not native.exists()


def test_modern_cli_passes_manifest_selection_and_uses_source_retrieval_time(tmp_path, monkeypatch):
    from types import SimpleNamespace

    args = _modern_cli_arguments(tmp_path)
    (tmp_path / "retention.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "historical_series_ids": ["old-series"],
                "retained_station_ids": ["USGS-001"],
            }
        )
    )
    reads = []

    def read(path):
        reads.append(path)
        return ([{"id": path.name}], [{"retrieved_at": "2026-10-30T00:00:00+00:00"}])

    monkeypatch.setattr(generator, "read_modern_metadata", read)
    monkeypatch.setattr(
        generator,
        "read_monitoring_locations",
        lambda path: (
            [{"id": "USGS-001"}],
            [{"retrieved_at": "2026-10-31T12:00:00+00:00"}],
        ),
    )
    seen = {}
    native = _native_table()

    def build(features, locations, **kwargs):
        seen.update(features=features, locations=locations, **kwargs)
        return SimpleNamespace(source_native=native.data)

    monkeypatch.setattr(generator, "build_modern_catalogue", build)
    output = tmp_path / "native.parquet"
    assert generator.main([*args, "--native-out", str(output)]) == 0
    assert reads == [tmp_path / "metadata", tmp_path / "historical"]
    assert seen == {
        "baseline_locations": {},
        "features": [{"id": "metadata"}],
        "locations": [{"id": "USGS-001"}],
        "historical_features": [{"id": "historical"}],
        "retained_series_ids": ("old-series",),
        "retained_locations": ("USGS-001",),
        "retrieved_at": RetrievedAt(datetime(2026, 10, 31, 12, tzinfo=UTC)),
    }
    pl_testing.assert_frame_equal(read_native_table(output).data, native.data)


def test_missing_legacy_enrichment_leaves_publication_destination_untouched(tmp_path):
    from types import SimpleNamespace

    catalogue = SimpleNamespace(source_descriptions=object(), retained_series_ids=())
    output = tmp_path / "catalogue"
    with pytest.raises(FatalContractError, match="explicit legacy enrichment"):
        generator.write_catalogue(
            catalogue, output, build_inputs=object(), native_table=_native_table(), acquisition_provenance=object()
        )
    assert not output.exists()


@pytest.mark.parametrize("corrupt", ["modern", "legacy", "baseline", "missing_legacy", "ambiguous_legacy"])
def test_modern_publication_verifies_adopted_native_bytes_before_writing(tmp_path, monkeypatch, corrupt):
    from types import SimpleNamespace

    from rivretrieve._internal.providers.usgs_nwis.origins import build_acquisition_provenance

    original = build_acquisition_provenance()
    provenance = original.model_copy(
        update={
            "native_table": original.native_table.model_copy(update={"sha256": "a" * 64, "byte_size": 123}),
        }
    )
    native_path = tmp_path / "native.parquet"
    legacy_path = tmp_path / "legacy.parquet"
    _native_table().data.write_parquet(native_path)
    _native_table().data.write_parquet(legacy_path)
    if corrupt == "modern":
        native_path.write_bytes(b"changed adopted bytes")
    else:
        provenance = provenance.model_copy(
            update={
                "native_table": provenance.native_table.model_copy(
                    update={
                        "sha256": hashlib.sha256(native_path.read_bytes()).hexdigest(),
                        "byte_size": native_path.stat().st_size,
                    }
                )
            }
        )
        legacy_path.write_bytes(b"changed legacy bytes")
    source = tmp_path / "provenance.json"
    source.write_text(provenance.model_dump_json())
    build = tmp_path / "build.json"
    build.write_text("{}")
    build_inputs = SimpleNamespace(
        inputs=[
            SimpleNamespace(
                facts=("source.station.legacy_sitefile_attributes",),
                reference=SimpleNamespace(sha256="b" * 64, byte_size=123, role="derived_input"),
                usage="reviewed_support",
            ),
            SimpleNamespace(
                facts=("source.station.baseline_identity",),
                reference=SimpleNamespace(sha256=hashlib.sha256(b"{}").hexdigest(), byte_size=2),
            ),
        ]
    )
    if corrupt == "baseline":
        build_inputs.inputs.pop()
    elif corrupt == "missing_legacy":
        build_inputs.inputs.pop(0)
    elif corrupt == "ambiguous_legacy":
        build_inputs.inputs.append(build_inputs.inputs[0])
    build_inputs.inputs.extend(
        SimpleNamespace(
            facts=("source.station.legacy_sitefile_attributes",),
            usage="recording",
            reference=SimpleNamespace(role="response_recording", sha256=str(index) * 64, byte_size=10),
        )
        for index in (1, 2)
    )
    monkeypatch.setattr(generator.CatalogueBuildInputs, "model_validate_json", lambda _: build_inputs)
    monkeypatch.setattr(
        __import__("rivretrieve._internal.providers.usgs_nwis.origins", fromlist=["selected_role_inputs"]),
        "selected_role_inputs",
        lambda provenance, role: ("source.station.legacy_sitefile_attributes",),
    )
    verified = []
    monkeypatch.setattr(generator, "verify_provenance_recordings", lambda value, root: verified.append(value))
    monkeypatch.setattr(
        generator,
        "read_modern_metadata",
        lambda _: (
            [],
            [{"retrieved_at": "2026-10-31T12:00:00+00:00"}],
        ),
    )
    monkeypatch.setattr(generator, "read_monitoring_locations", lambda _: ([], []))
    monkeypatch.setattr(
        generator,
        "build_modern_catalogue",
        lambda *args, **kwargs: SimpleNamespace(
            source_native=_native_table().data,
        ),
    )
    monkeypatch.setattr(generator, "write_catalogue", lambda *args, **kwargs: pytest.fail("invalid native published"))
    output = tmp_path / "catalogue"
    with pytest.raises(
        FatalContractError,
        match=(
            "baseline identity input"
            if corrupt == "baseline"
            else "one adopted legacy"
            if corrupt in {"missing_legacy", "ambiguous_legacy"}
            else "native table digest mismatch"
        ),
    ):
        generator.main(
            [
                *_modern_cli_arguments(tmp_path),
                "--out",
                str(output),
                "--native",
                str(native_path),
                "--legacy-native",
                str(tmp_path / "legacy.parquet"),
                "--build-inputs",
                str(build),
                "--acquisition-provenance",
                str(source),
                "--evidence-root",
                str(tmp_path),
            ]
        )
    assert verified == [provenance]
    assert not output.exists()


def test_legacy_native_keeps_agencies_distinct_at_shared_number():
    expanded, series = [], []
    for agency, area, claim in (("CA574", "12.5", "other-claim"), ("USGS", "34.5", "usgs-claim")):
        row = dict.fromkeys(EXPANDED_HEADER, "")
        row.update(agency_cd=agency, site_no="001", station_nm=agency, drain_area_va=area)
        expanded.append(row)
        record = {key: row.get(key, "") for key in SERIES_HEADER}
        record.update(data_type_cd="uv", parm_cd="00065", stat_cd="00011", ts_id=claim)
        series.append(record)
    result = generator.refresh_native_table(series, expanded, retrieved_at=ATTESTED_RETRIEVED_AT)
    assert not result.issues
    assert result.value.data.select("agency_cd", "site_no", "drain_area_va", "ts_id").rows() == [
        ("CA574", "001", "12.5", ["other-claim"]),
        ("USGS", "001", "34.5", ["usgs-claim"]),
    ]
    duplicated = generator.refresh_native_table(series, [*expanded, expanded[0]], retrieved_at=ATTESTED_RETRIEVED_AT)
    assert duplicated.value.data["agency_cd"].to_list() == ["CA574", "CA574", "USGS"]
