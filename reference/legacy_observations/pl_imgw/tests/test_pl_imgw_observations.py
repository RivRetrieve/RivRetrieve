"""Fixture-backed tests for pl_imgw IMGW observation parsing, transform, and retrieval."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

import rivretrieve as rr
from rivretrieve._internal.observations import ObservationRequest
from rivretrieve._internal.providers.pl_imgw.generate_catalogue import (
    generate_catalogue_from_fixture,
)
from rivretrieve._internal.providers.pl_imgw.observation_client import ImgwCacheClient
from rivretrieve._internal.providers.pl_imgw.parser import (
    parse_imgw_csv_bytes,
    parse_imgw_zip,
)
from rivretrieve._internal.providers.pl_imgw.retrieval import retrieve_observations
from rivretrieve._internal.providers.pl_imgw.transform import PRODUCT_POLICIES

_TEST_DATA_DIR = Path(__file__).parent / "test_data"
_FIXTURE_ZIP = _TEST_DATA_DIR / "pl_imgw_151140030_annual_2023.zip"
_FIXTURE_PARQUET = _TEST_DATA_DIR / "pl_imgw_cache_fixture.parquet"
_METADATA_FIXTURE = _TEST_DATA_DIR / "pl_imgw_metadata.csv"

_STATION_ID = "151140030"


# ---------------------------------------------------------------------------
# Catalogue generation
# ---------------------------------------------------------------------------


def test_generate_catalogue_station_count_fixture() -> None:
    """Fixture has 3 stations with valid coordinates."""
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.stations.height == 3


def test_generate_catalogue_product_count() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.products.height == 3


def test_generate_catalogue_station_products_cross() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.station_products.height == 3 * 3


def test_generate_catalogue_station_fields() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    row = cat.stations.filter(pl.col("station_id") == _STATION_ID)
    assert row.height == 1
    assert row["name"][0] == "PRZEWOŹNIKI"
    assert row["country"][0] == "Poland"
    assert row["latitude"][0] == pytest.approx(51.5252, abs=1e-3)
    assert row["longitude"][0] == pytest.approx(14.8218, abs=1e-3)


def test_generate_catalogue_elevation_set() -> None:
    """CSV source provides gauge_altitude in metres."""
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    row = cat.stations.filter(pl.col("station_id") == _STATION_ID)
    assert row["elevation_m"][0] == pytest.approx(114.049)


def test_generate_catalogue_product_ids() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    ids = set(cat.products["product_id"].to_list())
    assert ids == {"discharge_daily_mean", "stage_daily_mean", "water_temperature_daily_mean"}


def test_generate_catalogue_all_availability_unknown() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.station_products["availability"].cast(pl.Utf8).to_list() == ["unknown"] * 9


# ---------------------------------------------------------------------------
# CSV parser — raw bytes (unit tests, format-independent)
# ---------------------------------------------------------------------------


def _make_csv_2023(rows: list[str]) -> bytes:
    return ("﻿" + "\r\n".join(rows) + "\r\n").encode("utf-8")


def _make_csv_legacy(rows: list[str]) -> bytes:
    return ("\r\n".join(rows) + "\r\n").encode("cp1250")


_CSV_2023_ROWS = [
    "151140030;Przewożniki;Skroda;2023;03;01;225;1.500;2.5;1",
    "151140030;Przewożniki;Skroda;2023;03;02;220;1.450;99.9;1",   # missing temp
    "151140030;Przewożniki;Skroda;2023;03;03;9999;1.420;3.1;1",   # missing level
    "999000000;Other;Vistula;2023;03;01;100;2.000;10.0;1",         # other station
]


def test_parse_csv_2023_row_count() -> None:
    raw = _make_csv_2023(_CSV_2023_ROWS)
    result = parse_imgw_csv_bytes(raw, station_ids=frozenset({_STATION_ID}))
    assert result.records.height == 3


def test_parse_csv_station_filter() -> None:
    raw = _make_csv_2023(_CSV_2023_ROWS)
    result = parse_imgw_csv_bytes(raw, station_ids=frozenset({_STATION_ID}))
    assert set(result.records["station_id"].to_list()) == {_STATION_ID}


def test_parse_csv_all_stations_when_empty_filter() -> None:
    """Empty station_ids = all stations (cache-build mode)."""
    raw = _make_csv_2023(_CSV_2023_ROWS)
    result = parse_imgw_csv_bytes(raw, station_ids=frozenset())
    assert result.records.height == 4


def test_parse_csv_timestamps_utc() -> None:
    raw = _make_csv_2023(_CSV_2023_ROWS)
    result = parse_imgw_csv_bytes(raw, station_ids=frozenset({_STATION_ID}))
    assert result.records.schema["time"] == pl.Datetime(time_unit="us", time_zone="UTC")


def test_parse_csv_first_date_is_2023_01_01() -> None:
    raw = _make_csv_2023(_CSV_2023_ROWS)
    result = parse_imgw_csv_bytes(raw, station_ids=frozenset({_STATION_ID}))
    assert result.records["time"][0] == datetime(2023, 1, 1, tzinfo=UTC)


def test_parse_csv_sentinel_level_replaced() -> None:
    raw = _make_csv_2023(_CSV_2023_ROWS)
    result = parse_imgw_csv_bytes(raw, station_ids=frozenset({_STATION_ID}))
    row3 = result.records.filter(result.records["time"] == datetime(2023, 1, 3, tzinfo=UTC))
    assert row3["level_cm"][0] is None


def test_parse_csv_sentinel_temp_replaced() -> None:
    raw = _make_csv_2023(_CSV_2023_ROWS)
    result = parse_imgw_csv_bytes(raw, station_ids=frozenset({_STATION_ID}))
    row2 = result.records.filter(result.records["time"] == datetime(2023, 1, 2, tzinfo=UTC))
    assert row2["temp_c"][0] is None


def test_parse_csv_flow_value() -> None:
    raw = _make_csv_2023(_CSV_2023_ROWS)
    result = parse_imgw_csv_bytes(raw, station_ids=frozenset({_STATION_ID}))
    row1 = result.records.filter(result.records["time"] == datetime(2023, 1, 1, tzinfo=UTC))
    assert row1["flow_m3s"][0] == pytest.approx(1.5)


def test_parse_csv_date_only_issue_emitted() -> None:
    raw = _make_csv_2023(_CSV_2023_ROWS)
    result = parse_imgw_csv_bytes(raw, station_ids=frozenset({_STATION_ID}))
    assert any("date_only_timestamp" in str(i.code) for i in result.issues)


def test_parse_csv_legacy_cp1250() -> None:
    legacy = [
        '" 149180020","CHAŁUPKI","Odra (1)","2015","03","01",127,30.000,99.9,"1"',
        '" 149180020","CHAŁUPKI","Odra (1)","2015","03","02",130,29.500,3.5,"1"',
    ]
    raw = _make_csv_legacy(legacy)
    result = parse_imgw_csv_bytes(raw, station_ids=frozenset({"149180020"}))
    assert result.records.height == 2
    assert result.records["time"][0] == datetime(2015, 1, 1, tzinfo=UTC)
    assert result.records["temp_c"][0] is None  # 99.9 → sentinel


def test_parse_csv_november_hydro_year() -> None:
    """Month indicator 01 = November; hydro_year - 1 is calendar year for Nov/Dec."""
    rows = ["151140030;Przewożniki;Skroda;2023;01;15;200;1.200;5.0;11"]
    raw = _make_csv_2023(rows)
    result = parse_imgw_csv_bytes(raw, station_ids=frozenset({_STATION_ID}))
    assert result.records.height == 1
    assert result.records["time"][0] == datetime(2022, 11, 15, tzinfo=UTC)


# ---------------------------------------------------------------------------
# ZIP parser
# ---------------------------------------------------------------------------


def test_parse_zip_fixture_row_count() -> None:
    zip_bytes = _FIXTURE_ZIP.read_bytes()
    result = parse_imgw_zip(zip_bytes, station_ids=frozenset({_STATION_ID}))
    assert result.records.height == 3


def test_parse_zip_bad_bytes_raises() -> None:
    from rivretrieve._internal.providers.pl_imgw.parser import PlImgwParserError

    with pytest.raises(PlImgwParserError, match="not a valid ZIP"):
        parse_imgw_zip(b"not a zip", station_ids=frozenset({_STATION_ID}))


# ---------------------------------------------------------------------------
# Product policies
# ---------------------------------------------------------------------------


def test_stage_policy_conversion() -> None:
    policy = PRODUCT_POLICIES["stage_daily_mean"]
    assert policy.unit_conversion == "divide_by_100"
    assert policy.source_column == "level_cm"
    assert policy.native_unit == "cm"
    assert policy.canonical_unit == "m"


def test_discharge_policy_no_conversion() -> None:
    policy = PRODUCT_POLICIES["discharge_daily_mean"]
    assert policy.unit_conversion is None
    assert policy.source_column == "flow_m3s"


# ---------------------------------------------------------------------------
# Cache client — cache_path_override (mirrors ca_eccc db_path_override)
# ---------------------------------------------------------------------------


def _client() -> ImgwCacheClient:
    return ImgwCacheClient(cache_path_override=_FIXTURE_PARQUET)


def test_cache_status_with_fixture() -> None:
    status = _client().cache_status()
    assert status.exists is True
    assert status.path == _FIXTURE_PARQUET
    assert status.format == "parquet"


def test_cache_ensure_returns_fixture_path() -> None:
    path, issues = _client().ensure_cache()
    assert path == _FIXTURE_PARQUET
    assert issues == []


def test_cache_query_station_filter() -> None:
    path, _ = _client().ensure_cache()
    assert path is not None
    df = _client().query(
        path,
        frozenset({_STATION_ID}),
        datetime(2023, 1, 1, tzinfo=UTC),
        datetime(2023, 1, 31, tzinfo=UTC),
    )
    assert set(df["station_id"].to_list()) == {_STATION_ID}
    assert df.height == 3


def test_cache_query_date_range() -> None:
    path, _ = _client().ensure_cache()
    assert path is not None
    df = _client().query(
        path,
        frozenset({_STATION_ID}),
        datetime(2023, 1, 2, tzinfo=UTC),
        datetime(2023, 1, 2, tzinfo=UTC),
    )
    assert df.height == 1
    assert df["time"][0] == datetime(2023, 1, 2, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Retrieval via cache_path_override
# ---------------------------------------------------------------------------


def _request(products: list[str]) -> ObservationRequest:
    return ObservationRequest(
        provider_id="pl_imgw",
        stations=[_STATION_ID],
        products=products,
        start=datetime(2023, 1, 1, tzinfo=UTC),
        end=datetime(2023, 1, 31, tzinfo=UTC),
    )


def test_retrieve_discharge_daily_mean() -> None:
    result = retrieve_observations(
        _request(["discharge_daily_mean"]),
        on_issue="ignore",
        client_factory=_client,
    )
    assert not result.data.is_empty()
    assert set(result.data["product_id"].to_list()) == {"discharge_daily_mean"}
    # All 3 rows have non-null flow_m3s
    assert result.data.height == 3
    row1 = result.data.filter(result.data["time"] == datetime(2023, 1, 1, tzinfo=UTC))
    assert row1["value"][0] == pytest.approx(1.5)


def test_retrieve_stage_cm_to_m() -> None:
    result = retrieve_observations(
        _request(["stage_daily_mean"]),
        on_issue="ignore",
        client_factory=_client,
    )
    # Row 3 has level_cm=None → excluded; only 2 rows
    assert result.data.height == 2
    row1 = result.data.filter(result.data["time"] == datetime(2023, 1, 1, tzinfo=UTC))
    assert row1["value"][0] == pytest.approx(2.25)  # 225 cm → 2.25 m


def test_retrieve_temperature_sentinel_excluded() -> None:
    result = retrieve_observations(
        _request(["water_temperature_daily_mean"]),
        on_issue="ignore",
        client_factory=_client,
    )
    # Row 2 has temp_c=None → excluded; only 2 rows
    assert result.data.height == 2


def test_retrieve_timestamps_utc() -> None:
    result = retrieve_observations(
        _request(["discharge_daily_mean"]),
        on_issue="ignore",
        client_factory=_client,
    )
    assert result.data.schema["time"] == pl.Datetime(time_unit="us", time_zone="UTC")


def test_retrieve_date_only_issue() -> None:
    result = retrieve_observations(
        _request(["discharge_daily_mean"]),
        on_issue="ignore",
        client_factory=_client,
    )
    # date_only_timestamp issue comes from parser (emitted during cache build),
    # but in cache-query mode it's not re-emitted; provenance is "local".
    assert result.provenance.source == "local"


def test_retrieve_raw_value_row_annotation() -> None:
    result = retrieve_observations(
        _request(["stage_daily_mean"]),
        on_issue="ignore",
        client_factory=_client,
    )
    raw_ann = result.row_annotations.data.filter(pl.col("annotation") == "raw_value")
    assert raw_ann.height > 0
    row1_raw = raw_ann.filter(raw_ann["time"] == datetime(2023, 1, 1))
    assert "225" in row1_raw["value"][0]


def test_retrieve_series_annotation_timezone_source() -> None:
    result = retrieve_observations(
        _request(["discharge_daily_mean"]),
        on_issue="ignore",
        client_factory=_client,
    )
    tz_ann = result.series_annotations.data.filter(pl.col("annotation") == "timezone_source")
    assert tz_ann.height == 1
    assert tz_ann["value"][0] == "date_only_utc_midnight"



def test_retrieve_bulk_stations_and_products() -> None:
    request = ObservationRequest(
        provider_id="pl_imgw",
        stations=[_STATION_ID, "153190040"],
        products=["discharge_daily_mean", "stage_daily_mean"],
        start=datetime(2023, 1, 1, tzinfo=UTC),
        end=datetime(2023, 1, 31, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=_client)
    # Station 151140030: 3 discharge rows, 2 stage rows
    # Station 153190040: 1 discharge row, 1 stage row
    assert result.data.height > 0
    stations_in_result = set(result.data["station_id"].to_list())
    assert _STATION_ID in stations_in_result
    assert "153190040" in stations_in_result


# ---------------------------------------------------------------------------
# rr.provider("pl_imgw") integration
# ---------------------------------------------------------------------------


def test_provider_registered() -> None:
    assert "pl_imgw" in rr.providers()


def test_provider_stations_returns_catalog_result() -> None:
    from rivretrieve._internal.results import CatalogResult

    result = rr.provider("pl_imgw").stations()
    assert isinstance(result, CatalogResult)
    # Packaged catalogue: 1301 stations from poland_sites.csv (legacy Python repo, 2026-06-04).
    assert result.data.height == 1301


def test_provider_products_returns_three_products() -> None:
    result = rr.provider("pl_imgw").products()
    assert result.data.height == 3


def test_provider_cache_status_callable() -> None:
    """cache_status() is reachable through the provider handle (no download)."""
    import rivretrieve._internal.providers.pl_imgw.module as mod

    # Monkeypatch the factory to use the fixture so no download happens.
    original = mod._observation_client_factory
    mod._observation_client_factory = _client  # type: ignore[assignment]
    try:
        status = rr.provider("pl_imgw").cache_status()
        assert status.exists is True
    finally:
        mod._observation_client_factory = original


def test_provider_observations_reaches_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """rr.provider('pl_imgw').observations(...) delegates to retrieve_observations."""
    import rivretrieve._internal.providers.pl_imgw.module as mod

    calls: list[str] = []

    def _fake_factory() -> ImgwCacheClient:
        calls.append("called")
        return _client()

    monkeypatch.setattr(mod, "_observation_client_factory", _fake_factory)
    rr.provider("pl_imgw").observations(
        stations=_STATION_ID,
        products="discharge_daily_mean",
        start="2023-01-01",
        end="2023-01-31",
    )
    assert calls == ["called"]
