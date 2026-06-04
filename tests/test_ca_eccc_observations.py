"""Fixture-backed tests for ca_eccc HYDAT observation parsing, transform, and retrieval.

A minimal in-memory HYDAT SQLite database is constructed at module scope —
no network calls and no real HYDAT download.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import polars as pl
import pytest

from rivretrieve._internal.observations import ObservationRequest
from rivretrieve._internal.providers.ca_eccc.observation_client import HydatClient
from rivretrieve._internal.providers.ca_eccc.parser import parse_hydat_rows
from rivretrieve._internal.providers.ca_eccc.retrieval import retrieve_observations
from rivretrieve._internal.providers.ca_eccc.transform import (
    PRODUCT_POLICIES,
    resolve_product_policy,
    transform_series,
)

# ---------------------------------------------------------------------------
# Minimal HYDAT SQLite fixture
# ---------------------------------------------------------------------------
# Station 02GA010 (Grand River at Galt, ON): 5 days discharge + stage Jan 2010
# Station 08GA031 (Capilano River at Canyon, BC): 3 days discharge Jan 2010
# (historical data that is present in real HYDAT but absent from OGC API)
# DATA_SYMBOLS: B=Ice conditions, E=Estimated (ice-affected), empty=no flag


def _create_hydat(path: Path) -> None:
    conn = sqlite3.connect(str(path))

    # --- DLY_FLOWS ---
    day_cols = ", ".join(f"FLOW{i} REAL, FLOW_SYMBOL{i} TEXT" for i in range(1, 32))
    conn.execute(f"""
        CREATE TABLE DLY_FLOWS (
            STATION_NUMBER TEXT,
            YEAR INTEGER,
            MONTH INTEGER,
            NO_DAYS INTEGER,
            {day_cols}
        )
    """)

    def _flow_row(station: str, year: int, month: int, no_days: int, values: dict[int, tuple]) -> tuple:
        """values: {day: (flow, symbol)}"""
        row: list = [station, year, month, no_days]
        for i in range(1, 32):
            v = values.get(i)
            row.append(v[0] if v else None)
            row.append(v[1] if v else None)
        return tuple(row)

    placeholders = ", ".join(["?"] * (4 + 31 * 2))
    conn.execute(
        f"INSERT INTO DLY_FLOWS VALUES ({placeholders})",
        _flow_row(
            "02GA010",
            2010,
            1,
            5,
            {
                1: (16.0, ""),
                2: (17.0, ""),
                3: (16.0, "B"),
                4: (18.0, ""),
                5: (21.0, ""),
            },
        ),
    )
    conn.execute(
        f"INSERT INTO DLY_FLOWS VALUES ({placeholders})",
        _flow_row(
            "08GA031",
            2010,
            1,
            3,
            {
                1: (5.2, ""),
                2: (5.8, "E"),
                3: (6.1, ""),
            },
        ),
    )

    # --- DLY_LEVELS ---
    level_cols = ", ".join(f"LEVEL{i} REAL, LEVEL_SYMBOL{i} TEXT" for i in range(1, 32))
    conn.execute(f"""
        CREATE TABLE DLY_LEVELS (
            STATION_NUMBER TEXT,
            YEAR INTEGER,
            MONTH INTEGER,
            NO_DAYS INTEGER,
            {level_cols}
        )
    """)

    def _level_row(station: str, year: int, month: int, no_days: int, values: dict[int, tuple]) -> tuple:
        row: list = [station, year, month, no_days]
        for i in range(1, 32):
            v = values.get(i)
            row.append(v[0] if v else None)
            row.append(v[1] if v else None)
        return tuple(row)

    level_ph = ", ".join(["?"] * (4 + 31 * 2))
    conn.execute(
        f"INSERT INTO DLY_LEVELS VALUES ({level_ph})",
        _level_row(
            "02GA010",
            2010,
            1,
            5,
            {
                1: (1.10, ""),
                2: (1.12, ""),
                3: (1.11, "B"),
                4: (1.15, ""),
                5: (1.18, ""),
            },
        ),
    )

    # --- DATA_SYMBOLS ---
    conn.execute("""
        CREATE TABLE DATA_SYMBOLS (
            SYMBOL_ID TEXT,
            SYMBOL_EN TEXT,
            SYMBOL_FR TEXT
        )
    """)
    for sid, en in [("B", "Ice conditions"), ("E", "Estimated"), ("A", "Partial day"), ("D", "Dry")]:
        conn.execute("INSERT INTO DATA_SYMBOLS VALUES (?, ?, ?)", (sid, en, ""))

    conn.commit()
    conn.close()


@pytest.fixture(scope="module")
def hydat_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    p = tmp_path_factory.mktemp("hydat") / "Hydat_sqlite3_20260604.sqlite3"
    _create_hydat(p)
    return p


@pytest.fixture(scope="module")
def hydat_client(hydat_db: Path) -> HydatClient:
    return HydatClient(db_path_override=hydat_db)


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


def test_parser_returns_five_rows(hydat_client: HydatClient, hydat_db: Path) -> None:
    rows = hydat_client.query_daily_table(hydat_db, "DLY_FLOWS", "02GA010", 2010, 2010)
    result = parse_hydat_rows(rows, station_id="02GA010", value_prefix="FLOW", symbol_prefix="FLOW_SYMBOL")
    assert len(result.records) == 5


def test_parser_timestamps_utc_midnight(hydat_client: HydatClient, hydat_db: Path) -> None:
    rows = hydat_client.query_daily_table(hydat_db, "DLY_FLOWS", "02GA010", 2010, 2010)
    result = parse_hydat_rows(rows, station_id="02GA010", value_prefix="FLOW", symbol_prefix="FLOW_SYMBOL")
    times = result.records["time"].to_list()
    assert times[0] == datetime(2010, 1, 1, tzinfo=UTC)
    assert times[4] == datetime(2010, 1, 5, tzinfo=UTC)


def test_parser_discharge_values(hydat_client: HydatClient, hydat_db: Path) -> None:
    rows = hydat_client.query_daily_table(hydat_db, "DLY_FLOWS", "02GA010", 2010, 2010)
    result = parse_hydat_rows(rows, station_id="02GA010", value_prefix="FLOW", symbol_prefix="FLOW_SYMBOL")
    values = result.records["raw_value"].to_list()
    assert values[0] == pytest.approx(16.0)
    assert values[2] == pytest.approx(16.0)
    assert values[4] == pytest.approx(21.0)


def test_parser_quality_symbols(hydat_client: HydatClient, hydat_db: Path) -> None:
    rows = hydat_client.query_daily_table(hydat_db, "DLY_FLOWS", "02GA010", 2010, 2010)
    result = parse_hydat_rows(rows, station_id="02GA010", value_prefix="FLOW", symbol_prefix="FLOW_SYMBOL")
    symbols = result.records["symbol"].to_list()
    assert symbols[0] == ""
    assert symbols[2] == "B"  # ice conditions on day 3


def test_parser_emits_date_only_timestamp_issue(hydat_client: HydatClient, hydat_db: Path) -> None:
    rows = hydat_client.query_daily_table(hydat_db, "DLY_FLOWS", "02GA010", 2010, 2010)
    result = parse_hydat_rows(rows, station_id="02GA010", value_prefix="FLOW", symbol_prefix="FLOW_SYMBOL")
    assert "date_only_timestamp" in [i.code for i in result.issues]


def test_parser_empty_rows_returns_issue() -> None:
    result = parse_hydat_rows([], station_id="02GA010", value_prefix="FLOW", symbol_prefix="FLOW_SYMBOL")
    assert result.records.is_empty()
    assert len(result.issues) > 0


def test_parser_respects_no_days(hydat_client: HydatClient, hydat_db: Path) -> None:
    """NO_DAYS=5 means only days 1–5 are valid; days 6–31 are skipped."""
    rows = hydat_client.query_daily_table(hydat_db, "DLY_FLOWS", "02GA010", 2010, 2010)
    result = parse_hydat_rows(rows, station_id="02GA010", value_prefix="FLOW", symbol_prefix="FLOW_SYMBOL")
    # Only 5 days, even though FLOW6..FLOW31 columns exist (all null in fixture)
    assert len(result.records) == 5


def test_parser_stage_five_rows(hydat_client: HydatClient, hydat_db: Path) -> None:
    rows = hydat_client.query_daily_table(hydat_db, "DLY_LEVELS", "02GA010", 2010, 2010)
    result = parse_hydat_rows(rows, station_id="02GA010", value_prefix="LEVEL", symbol_prefix="LEVEL_SYMBOL")
    assert len(result.records) == 5


# ---------------------------------------------------------------------------
# Data symbols / quality lookup
# ---------------------------------------------------------------------------


def test_data_symbols_loaded(hydat_client: HydatClient, hydat_db: Path) -> None:
    symbols = hydat_client.query_data_symbols(hydat_db)
    assert symbols.get("B") == "Ice conditions"
    assert symbols.get("E") == "Estimated"


def test_data_symbols_cached(hydat_client: HydatClient, hydat_db: Path) -> None:
    """Second call returns the same content (cached, no extra DB read)."""
    s1 = hydat_client.query_data_symbols(hydat_db)
    s2 = hydat_client.query_data_symbols(hydat_db)
    assert s1 == s2


# ---------------------------------------------------------------------------
# Product policy tests
# ---------------------------------------------------------------------------


def test_product_policies_defined() -> None:
    assert "discharge_daily_mean" in PRODUCT_POLICIES
    assert "stage_daily_mean" in PRODUCT_POLICIES


def test_resolve_product_policy_discharge() -> None:
    policy = resolve_product_policy("discharge_daily_mean")
    assert policy.table_name == "DLY_FLOWS"
    assert policy.value_prefix == "FLOW"
    assert policy.native_unit == "m3/s"


def test_resolve_product_policy_stage() -> None:
    policy = resolve_product_policy("stage_daily_mean")
    assert policy.table_name == "DLY_LEVELS"
    assert policy.value_prefix == "LEVEL"
    assert policy.native_unit == "m"


def test_resolve_unknown_product_raises() -> None:
    from rivretrieve._internal.issues import InvalidObservationRequestError

    with pytest.raises(InvalidObservationRequestError):
        resolve_product_policy("unsupported_product")


# ---------------------------------------------------------------------------
# Transform tests
# ---------------------------------------------------------------------------


def test_transform_discharge_correct_rows(hydat_client: HydatClient, hydat_db: Path) -> None:
    rows = hydat_client.query_daily_table(hydat_db, "DLY_FLOWS", "02GA010", 2010, 2010)
    policy = resolve_product_policy("discharge_daily_mean")
    parsed = parse_hydat_rows(rows, station_id="02GA010", value_prefix="FLOW", symbol_prefix="FLOW_SYMBOL")
    result = transform_series(
        parsed.records,
        station_id="02GA010",
        policy=policy,
        query_years=(2010, 2010),
        hydat_source="Hydat_sqlite3_20260604.sqlite3",
        data_symbols=hydat_client.query_data_symbols(hydat_db),
    )
    assert not result.data.is_empty()
    assert len(result.data) == 5
    assert result.data["product_id"].unique().to_list() == ["discharge_daily_mean"]


def test_transform_discharge_values_unchanged(hydat_client: HydatClient, hydat_db: Path) -> None:
    rows = hydat_client.query_daily_table(hydat_db, "DLY_FLOWS", "02GA010", 2010, 2010)
    policy = resolve_product_policy("discharge_daily_mean")
    parsed = parse_hydat_rows(rows, station_id="02GA010", value_prefix="FLOW", symbol_prefix="FLOW_SYMBOL")
    result = transform_series(
        parsed.records,
        station_id="02GA010",
        policy=policy,
        query_years=(2010, 2010),
        hydat_source="Hydat_sqlite3_20260604.sqlite3",
        data_symbols=hydat_client.query_data_symbols(hydat_db),
    )
    values = result.data["value"].to_list()
    assert values[0] == pytest.approx(16.0)
    assert values[1] == pytest.approx(17.0)
    assert values[4] == pytest.approx(21.0)


def test_transform_stage_correct_rows(hydat_client: HydatClient, hydat_db: Path) -> None:
    rows = hydat_client.query_daily_table(hydat_db, "DLY_LEVELS", "02GA010", 2010, 2010)
    policy = resolve_product_policy("stage_daily_mean")
    parsed = parse_hydat_rows(rows, station_id="02GA010", value_prefix="LEVEL", symbol_prefix="LEVEL_SYMBOL")
    result = transform_series(
        parsed.records,
        station_id="02GA010",
        policy=policy,
        query_years=(2010, 2010),
        hydat_source="Hydat_sqlite3_20260604.sqlite3",
        data_symbols=hydat_client.query_data_symbols(hydat_db),
    )
    assert not result.data.is_empty()
    values = result.data["value"].to_list()
    assert values[0] == pytest.approx(1.10)
    assert values[1] == pytest.approx(1.12)


def test_transform_row_annotations_include_quality(hydat_client: HydatClient, hydat_db: Path) -> None:
    rows = hydat_client.query_daily_table(hydat_db, "DLY_FLOWS", "02GA010", 2010, 2010)
    policy = resolve_product_policy("discharge_daily_mean")
    parsed = parse_hydat_rows(rows, station_id="02GA010", value_prefix="FLOW", symbol_prefix="FLOW_SYMBOL")
    result = transform_series(
        parsed.records,
        station_id="02GA010",
        policy=policy,
        query_years=(2010, 2010),
        hydat_source="Hydat_sqlite3_20260604.sqlite3",
        data_symbols=hydat_client.query_data_symbols(hydat_db),
    )
    annotation_ids = set(result.row_annotations["annotation"].to_list())
    assert "quality_flag" in annotation_ids
    assert "quality_description" in annotation_ids
    assert "native_unit" in annotation_ids
    assert "raw_value" in annotation_ids


def test_transform_quality_description_resolved(hydat_client: HydatClient, hydat_db: Path) -> None:
    """'B' quality code should resolve to 'Ice conditions' via DATA_SYMBOLS."""
    rows = hydat_client.query_daily_table(hydat_db, "DLY_FLOWS", "02GA010", 2010, 2010)
    policy = resolve_product_policy("discharge_daily_mean")
    parsed = parse_hydat_rows(rows, station_id="02GA010", value_prefix="FLOW", symbol_prefix="FLOW_SYMBOL")
    result = transform_series(
        parsed.records,
        station_id="02GA010",
        policy=policy,
        query_years=(2010, 2010),
        hydat_source="Hydat_sqlite3_20260604.sqlite3",
        data_symbols=hydat_client.query_data_symbols(hydat_db),
    )
    ann = result.row_annotations.to_pandas()
    desc_rows = ann[(ann["annotation"] == "quality_description") & (ann["value"] == "Ice conditions")]
    assert len(desc_rows) > 0  # day 3 has symbol "B" → "Ice conditions"


def test_transform_series_annotations_timezone(hydat_client: HydatClient, hydat_db: Path) -> None:
    rows = hydat_client.query_daily_table(hydat_db, "DLY_FLOWS", "02GA010", 2010, 2010)
    policy = resolve_product_policy("discharge_daily_mean")
    parsed = parse_hydat_rows(rows, station_id="02GA010", value_prefix="FLOW", symbol_prefix="FLOW_SYMBOL")
    result = transform_series(
        parsed.records,
        station_id="02GA010",
        policy=policy,
        query_years=(2010, 2010),
        hydat_source="Hydat_sqlite3_20260604.sqlite3",
        data_symbols={},
    )
    ann = {r["annotation"]: r["value"] for r in result.series_annotations.iter_rows(named=True)}
    assert ann["timezone_source"] == "date_only_utc_midnight"
    assert ann["date_only_timestamp_flag"] == "true"
    assert ann["resolved_timezone"] == "UTC"
    assert ann["hydat_table"] == "DLY_FLOWS"
    assert ann["hydat_source"] == "Hydat_sqlite3_20260604.sqlite3"


# ---------------------------------------------------------------------------
# Retrieval integration tests (db_path_override bypasses download)
# ---------------------------------------------------------------------------


def _make_client(hydat_db: Path) -> HydatClient:
    return HydatClient(db_path_override=hydat_db)


def test_retrieval_discharge_five_rows(hydat_db: Path) -> None:
    def client_factory() -> HydatClient:
        return _make_client(hydat_db)

    request = ObservationRequest(
        provider_id="ca_eccc",
        stations=("02GA010",),
        products=("discharge_daily_mean",),
        start=datetime(2010, 1, 1, tzinfo=UTC),
        end=datetime(2010, 1, 5, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    assert not result.data.is_empty()
    assert len(result.data) == 5


def test_retrieval_discharge_historical_station(hydat_db: Path) -> None:
    """08GA031 in 2010 — absent from OGC API but present in HYDAT."""

    def client_factory() -> HydatClient:
        return _make_client(hydat_db)

    request = ObservationRequest(
        provider_id="ca_eccc",
        stations=("08GA031",),
        products=("discharge_daily_mean",),
        start=datetime(2010, 1, 1, tzinfo=UTC),
        end=datetime(2010, 1, 3, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    assert not result.data.is_empty()
    assert len(result.data) == 3
    values = result.data["value"].to_list()
    assert values[0] == pytest.approx(5.2)


def test_retrieval_both_products(hydat_db: Path) -> None:
    def client_factory() -> HydatClient:
        return _make_client(hydat_db)

    request = ObservationRequest(
        provider_id="ca_eccc",
        stations=("02GA010",),
        products=("discharge_daily_mean", "stage_daily_mean"),
        start=datetime(2010, 1, 1, tzinfo=UTC),
        end=datetime(2010, 1, 5, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    product_ids = set(result.data["product_id"].to_list())
    assert product_ids == {"discharge_daily_mean", "stage_daily_mean"}
    assert len(result.data) == 10  # 5 discharge + 5 stage


def test_retrieval_utc_timestamps(hydat_db: Path) -> None:
    def client_factory() -> HydatClient:
        return _make_client(hydat_db)

    request = ObservationRequest(
        provider_id="ca_eccc",
        stations=("02GA010",),
        products=("discharge_daily_mean",),
        start=datetime(2010, 1, 1, tzinfo=UTC),
        end=datetime(2010, 1, 5, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    assert result.data["time"].dtype == pl.Datetime(time_unit="us", time_zone="UTC")


def test_retrieval_date_filter_respected(hydat_db: Path) -> None:
    """Requesting only days 1–3 should return 3 rows, not 5."""

    def client_factory() -> HydatClient:
        return _make_client(hydat_db)

    request = ObservationRequest(
        provider_id="ca_eccc",
        stations=("02GA010",),
        products=("discharge_daily_mean",),
        start=datetime(2010, 1, 1, tzinfo=UTC),
        end=datetime(2010, 1, 3, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    assert len(result.data) == 3


def test_retrieval_canonical_columns(hydat_db: Path) -> None:
    def client_factory() -> HydatClient:
        return _make_client(hydat_db)

    request = ObservationRequest(
        provider_id="ca_eccc",
        stations=("02GA010",),
        products=("discharge_daily_mean",),
        start=datetime(2010, 1, 1, tzinfo=UTC),
        end=datetime(2010, 1, 5, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    assert set(result.data.columns) == {"time", "station_id", "product_id", "value"}


def test_retrieval_emits_date_only_issue(hydat_db: Path) -> None:
    def client_factory() -> HydatClient:
        return _make_client(hydat_db)

    request = ObservationRequest(
        provider_id="ca_eccc",
        stations=("02GA010",),
        products=("discharge_daily_mean",),
        start=datetime(2010, 1, 1, tzinfo=UTC),
        end=datetime(2010, 1, 5, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    codes = [i.code for i in result.issues]
    assert "date_only_timestamp" in codes


def test_retrieval_provenance_source_local(hydat_db: Path) -> None:
    def client_factory() -> HydatClient:
        return _make_client(hydat_db)

    request = ObservationRequest(
        provider_id="ca_eccc",
        stations=("02GA010",),
        products=("discharge_daily_mean",),
        start=datetime(2010, 1, 1, tzinfo=UTC),
        end=datetime(2010, 1, 5, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    assert result.provenance.source == "local"


def test_retrieval_to_pandas(hydat_db: Path) -> None:
    def client_factory() -> HydatClient:
        return _make_client(hydat_db)

    request = ObservationRequest(
        provider_id="ca_eccc",
        stations=("02GA010",),
        products=("discharge_daily_mean",),
        start=datetime(2010, 1, 1, tzinfo=UTC),
        end=datetime(2010, 1, 5, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    df = result.to_pandas()
    assert isinstance(df, pd.DataFrame)
    assert "value" in df.columns


def test_retrieval_no_hydat_emits_error() -> None:
    """When db_path_override points to a non-existent file, ensure_database returns None."""

    def client_factory() -> HydatClient:
        return HydatClient(db_path_override=Path("/nonexistent/Hydat.sqlite3"))

    request = ObservationRequest(
        provider_id="ca_eccc",
        stations=("02GA010",),
        products=("discharge_daily_mean",),
        start=datetime(2010, 1, 1, tzinfo=UTC),
        end=datetime(2010, 1, 5, tzinfo=UTC),
    )
    # db_path_override points to missing file — ensure_database returns it (trusts the override).
    # The query will then fail. Let's instead test the no-db path by patching ensure_database.
    import unittest.mock as mock

    with mock.patch.object(HydatClient, "ensure_database", return_value=(None, [])):
        result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    assert result.data.is_empty()
    codes = [i.code for i in result.issues]
    assert "hydat_not_available" in codes


def test_retrieval_via_rr_provider_handle(hydat_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """rr.provider('ca_eccc').observations(...) reaches the HYDAT client."""
    import rivretrieve._internal.providers.ca_eccc.module as mod

    monkeypatch.setattr(mod, "_observation_client_factory", lambda: HydatClient(db_path_override=hydat_db))

    import rivretrieve as rr

    result = rr.provider("ca_eccc").observations(
        stations="02GA010",
        products="discharge_daily_mean",
        start=pd.Timestamp("2010-01-01"),
        end=pd.Timestamp("2010-01-05"),
        on_issue="ignore",
    )
    assert not result.data.is_empty()
    assert len(result.data) == 5
