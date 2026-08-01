from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

from rivretrieve._internal.observations import ObservationRequest
from rivretrieve._internal.providers.br_ana.generate_catalogue import (
    generate_catalogue_from_fixture,
)
from rivretrieve._internal.providers.br_ana.observation_client import (
    AUTH_URL,
    TELEMETRIC_ADOTADA_URL,
    TELEMETRIC_DETALHADA_URL,
    BrAnaObservationClient,
    BrAnaTransportRequest,
    BrAnaTransportResponse,
    is_telemetric_product,
)
from rivretrieve._internal.providers.br_ana.parser import (
    parse_br_ana_json,
    parse_br_ana_telemetric_json,
)
from rivretrieve._internal.providers.br_ana.retrieval import retrieve_observations
from rivretrieve._internal.providers.br_ana.transform import (
    PRODUCT_POLICIES,
    TELEMETRIC_PRODUCT_POLICIES,
)

_TEST_DATA_DIR = Path(__file__).parent / "test_data"
_METADATA_FIXTURE = _TEST_DATA_DIR / "br_ana_metadata.json"
_DISCHARGE_FIXTURE = _TEST_DATA_DIR / "br_ana_12345000_vazao_2020.json"
_STAGE_FIXTURE = _TEST_DATA_DIR / "br_ana_60435000_cotas_2020.json"
_TELEMETRIC_ADOTADA_FIXTURE = _TEST_DATA_DIR / "br_ana_12345000_telemetrica_adotada.json"
_TELEMETRIC_DETALHADA_FIXTURE = _TEST_DATA_DIR / "br_ana_12345000_telemetrica_detalhada.json"


# ---------------------------------------------------------------------------
# Catalogue generation
# ---------------------------------------------------------------------------


def test_generate_catalogue_station_count() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.stations.height == 2


def test_generate_catalogue_product_count() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    # discharge_daily_mean, stage_daily_mean, discharge_instantaneous,
    # stage_instantaneous, water_temperature_instantaneous
    assert cat.products.height == 5


def test_generate_catalogue_station_products_count() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    # 2 stations × 5 products = 10
    assert cat.station_products.height == 10


def test_generate_catalogue_station_fields() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    row = cat.stations.filter(pl.col("station_id") == "12345000")
    assert row.height == 1
    assert row["name"][0] == "RIO XINGU EM ALTAMIRA"
    assert row["country"][0] == "Brazil"
    assert row["elevation_m"][0] == pytest.approx(50.0)
    assert row["drainage_area_km2"][0] == pytest.approx(146080.0)


def test_generate_catalogue_start_end_date_uses_earliest_sub_period() -> None:
    # start_date = min across all sub-period starts (telemetric, discharge, stage, qual_agua)
    # end_date = None if ANY sub-period end is null (station still active for at least one variable)
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)

    # 12345000: discharge/stage both start 1970-01-01, telemetric 2005 — min is 1970.
    # All Fim are null → end_date is None.
    row_12345 = cat.stations.filter(pl.col("station_id") == "12345000")
    assert row_12345["start_date"][0] == datetime(1970, 1, 1).date()
    assert row_12345["end_date"][0] is None

    # 60435000: stage starts 1955-06-01, telemetric 2010 — min is 1955.
    # Stage Fim is null → end_date is None (station still active for stage).
    row_60435 = cat.stations.filter(pl.col("station_id") == "60435000")
    assert row_60435["start_date"][0] == datetime(1955, 6, 1).date()
    assert row_60435["end_date"][0] is None


def test_generate_catalogue_river_name_in_metadata() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    row = cat.stations.filter(pl.col("station_id") == "12345000")
    meta = json.loads(row["metadata"][0])
    assert meta["river_name"] == "RIO XINGU"
    assert meta["basin_name"] == "BACIA AMAZONICA"


def test_generate_catalogue_filters_no_coord_station() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    ids = set(cat.stations["station_id"].to_list())
    assert "99999999" not in ids


def test_generate_catalogue_filters_pure_pluviometric_station() -> None:
    """Stations with no discharge/level/water-quality flag set are out of scope."""
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    ids = set(cat.stations["station_id"].to_list())
    assert "77777000" not in ids


def test_generate_catalogue_keeps_stations_with_any_relevant_type_flag() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    ids = set(cat.stations["station_id"].to_list())
    # 12345000: discharge + level; 60435000: level only — both relevant to our products.
    assert {"12345000", "60435000"} <= ids


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def test_parse_discharge_json_values() -> None:
    with _DISCHARGE_FIXTURE.open("rb") as f:
        content = f.read()
    parsed = parse_br_ana_json(content, station_id="12345000", product_id="discharge_daily_mean")
    assert parsed.records.height == 3
    # Values come through unchanged (m³/s direct)
    values = parsed.records["raw_value"].to_list()
    assert values[0] == pytest.approx(1234.56)
    assert values[1] == pytest.approx(1345.67)
    assert values[2] == pytest.approx(987.89)


def test_parse_discharge_json_timestamps_utc() -> None:
    with _DISCHARGE_FIXTURE.open("rb") as f:
        content = f.read()
    parsed = parse_br_ana_json(content, station_id="12345000", product_id="discharge_daily_mean")
    times = parsed.records["time"].to_list()
    assert times[0] == datetime(2020, 1, 1, tzinfo=UTC)
    assert times[1] == datetime(2020, 1, 2, tzinfo=UTC)
    assert times[2] == datetime(2020, 1, 3, tzinfo=UTC)


def test_parse_discharge_emits_date_only_issue() -> None:
    with _DISCHARGE_FIXTURE.open("rb") as f:
        content = f.read()
    parsed = parse_br_ana_json(content, station_id="12345000", product_id="discharge_daily_mean")
    assert len(parsed.issues) == 1
    assert "date_only_timestamp" in parsed.issues[0].code


def test_parse_stage_json_values() -> None:
    with _STAGE_FIXTURE.open("rb") as f:
        content = f.read()
    parsed = parse_br_ana_json(content, station_id="60435000", product_id="stage_daily_mean")
    assert parsed.records.height == 3
    # Raw values are cm; transform will convert to m
    values = parsed.records["raw_value"].to_list()
    assert values[0] == pytest.approx(1250.0)
    assert values[1] == pytest.approx(1300.0)
    assert values[2] == pytest.approx(1275.0)


def test_parse_empty_json() -> None:
    parsed = parse_br_ana_json(b"[]", station_id="12345000", product_id="discharge_daily_mean")
    assert parsed.records.is_empty()
    assert len(parsed.issues) == 1  # date_only_timestamp always emitted


def test_parse_dict_wrapped_response() -> None:
    content = json.dumps(
        {
            "status": "OK",
            "items": [
                {
                    "Data_Hora_Dado": "2020-06-01T00:00:00",
                    "Vazao_01": "500.0",
                    "Vazao_02": None,
                }
            ],
        }
    ).encode()
    parsed = parse_br_ana_json(content, station_id="12345000", product_id="discharge_daily_mean")
    assert parsed.records.height == 1
    assert parsed.records["raw_value"][0] == pytest.approx(500.0)


# ---------------------------------------------------------------------------
# Transform / product policies
# ---------------------------------------------------------------------------


def test_discharge_policy_no_conversion() -> None:
    policy = PRODUCT_POLICIES["discharge_daily_mean"]
    assert policy.conversion_factor == 1.0
    assert policy.native_unit == "m3/s"
    assert policy.canonical_unit == "m3/s"


def test_stage_policy_cm_to_m() -> None:
    policy = PRODUCT_POLICIES["stage_daily_mean"]
    assert policy.conversion_factor == 100.0
    assert policy.native_unit == "cm"
    assert policy.canonical_unit == "m"


# ---------------------------------------------------------------------------
# Retrieval with fixture transport
# ---------------------------------------------------------------------------


def _make_fixture_transport(
    auth_token: str = "testtoken123",
    discharge_fixture: Path = _DISCHARGE_FIXTURE,
    stage_fixture: Path = _STAGE_FIXTURE,
):
    """Return a transport callable that serves fixture files instead of live HTTP."""

    def transport(request: BrAnaTransportRequest) -> BrAnaTransportResponse:
        if request.url == AUTH_URL:
            body = json.dumps({"status": "OK", "items": {"tokenautenticacao": auth_token, "sucesso": True}}).encode()
            return BrAnaTransportResponse(
                content=body,
                status_code=200,
                retrieved_at=datetime(2026, 6, 3, 12, 0, 0, tzinfo=UTC),
            )
        if "HidroSerieVazao" in request.url:
            content = discharge_fixture.read_bytes()
            return BrAnaTransportResponse(
                content=content,
                status_code=200,
                retrieved_at=datetime(2026, 6, 3, 12, 0, 1, tzinfo=UTC),
            )
        # stage
        content = stage_fixture.read_bytes()
        return BrAnaTransportResponse(
            content=content,
            status_code=200,
            retrieved_at=datetime(2026, 6, 3, 12, 0, 2, tzinfo=UTC),
        )

    return transport


def test_retrieve_discharge_returns_data() -> None:
    transport = _make_fixture_transport()
    client_factory = lambda: BrAnaObservationClient(  # noqa: E731
        username="testuser",
        password="testpass",
        transport=transport,
    )
    request = ObservationRequest(
        provider_id="br_ana",
        stations=["12345000"],
        products=["discharge_daily_mean"],
        start=datetime(2020, 1, 1, tzinfo=UTC),
        end=datetime(2020, 1, 31, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    assert not result.data.is_empty()
    assert result.data.height == 3
    assert set(result.data["product_id"].unique().to_list()) == {"discharge_daily_mean"}
    assert set(result.data["station_id"].unique().to_list()) == {"12345000"}


def test_retrieve_discharge_values_m3s() -> None:
    transport = _make_fixture_transport()
    client_factory = lambda: BrAnaObservationClient(  # noqa: E731
        username="testuser",
        password="testpass",
        transport=transport,
    )
    request = ObservationRequest(
        provider_id="br_ana",
        stations=["12345000"],
        products=["discharge_daily_mean"],
        start=datetime(2020, 1, 1, tzinfo=UTC),
        end=datetime(2020, 1, 31, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    values = result.data["value"].to_list()
    assert values[0] == pytest.approx(1234.56)  # no conversion, m³/s direct
    assert values[1] == pytest.approx(1345.67)
    assert values[2] == pytest.approx(987.89)


def test_retrieve_stage_values_converted_to_m() -> None:
    transport = _make_fixture_transport()
    client_factory = lambda: BrAnaObservationClient(  # noqa: E731
        username="testuser",
        password="testpass",
        transport=transport,
    )
    request = ObservationRequest(
        provider_id="br_ana",
        stations=["60435000"],
        products=["stage_daily_mean"],
        start=datetime(2020, 3, 1, tzinfo=UTC),
        end=datetime(2020, 3, 31, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    assert not result.data.is_empty()
    values = result.data["value"].to_list()
    # 1250 cm → 12.50 m
    assert values[0] == pytest.approx(12.50)
    assert values[1] == pytest.approx(13.00)
    assert values[2] == pytest.approx(12.75)


def test_retrieve_stage_raw_value_annotation_in_cm() -> None:
    transport = _make_fixture_transport()
    client_factory = lambda: BrAnaObservationClient(  # noqa: E731
        username="testuser",
        password="testpass",
        transport=transport,
    )
    request = ObservationRequest(
        provider_id="br_ana",
        stations=["60435000"],
        products=["stage_daily_mean"],
        start=datetime(2020, 3, 1, tzinfo=UTC),
        end=datetime(2020, 3, 31, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    raw_ann = result.row_annotations.data.filter(pl.col("annotation") == "raw_value")
    assert raw_ann.height == 3
    raw_vals = [float(v) for v in raw_ann["value"].to_list()]
    assert raw_vals[0] == pytest.approx(1250.0)  # cm preserved


def test_retrieve_timestamps_utc() -> None:
    transport = _make_fixture_transport()
    client_factory = lambda: BrAnaObservationClient(  # noqa: E731
        username="testuser",
        password="testpass",
        transport=transport,
    )
    request = ObservationRequest(
        provider_id="br_ana",
        stations=["12345000"],
        products=["discharge_daily_mean"],
        start=datetime(2020, 1, 1, tzinfo=UTC),
        end=datetime(2020, 1, 31, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    times = result.data["time"].to_list()
    assert all(t.tzinfo is not None for t in times), "All timestamps must be timezone-aware"
    assert times[0] == datetime(2020, 1, 1, tzinfo=UTC)


def test_retrieve_series_annotation_timezone() -> None:
    transport = _make_fixture_transport()
    client_factory = lambda: BrAnaObservationClient(  # noqa: E731
        username="testuser",
        password="testpass",
        transport=transport,
    )
    request = ObservationRequest(
        provider_id="br_ana",
        stations=["12345000"],
        products=["discharge_daily_mean"],
        start=datetime(2020, 1, 1, tzinfo=UTC),
        end=datetime(2020, 1, 31, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    sa = result.series_annotations.data
    tz_source = sa.filter(pl.col("annotation") == "timezone_source")["value"][0]
    assert tz_source == "date_only_utc_midnight"
    flag = sa.filter(pl.col("annotation") == "date_only_timestamp_flag")["value"][0]
    assert flag == "true"


def test_retrieve_no_credentials_returns_auth_issue() -> None:
    client_factory = lambda: BrAnaObservationClient(  # noqa: E731
        username=None,
        password=None,
        transport=lambda req: (_ for _ in ()).throw(AssertionError("should not be called")),
    )
    request = ObservationRequest(
        provider_id="br_ana",
        stations=["12345000"],
        products=["discharge_daily_mean"],
        start=datetime(2020, 1, 1, tzinfo=UTC),
        end=datetime(2020, 1, 31, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    assert result.data.is_empty()
    codes = [i.code for i in result.issues]
    assert "auth_missing" in codes


def test_retrieve_provenance_no_credentials() -> None:
    client_factory = lambda: BrAnaObservationClient(username=None, password=None)  # noqa: E731
    request = ObservationRequest(
        provider_id="br_ana",
        stations=["12345000"],
        products=["discharge_daily_mean"],
        start=datetime(2020, 1, 1, tzinfo=UTC),
        end=datetime(2020, 1, 31, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    prov_str = str(result.provenance)
    # Credentials must never appear in provenance
    assert "testpass" not in prov_str
    assert "testuser" not in prov_str


# ---------------------------------------------------------------------------
# Telemetric (instantaneous, quality-flagged) products
# ---------------------------------------------------------------------------


def test_is_telemetric_product_classification() -> None:
    assert is_telemetric_product("discharge_instantaneous")
    assert is_telemetric_product("stage_instantaneous")
    assert is_telemetric_product("water_temperature_instantaneous")
    assert not is_telemetric_product("discharge_daily_mean")
    assert not is_telemetric_product("stage_daily_mean")


def test_telemetric_policies_registered() -> None:
    assert TELEMETRIC_PRODUCT_POLICIES["discharge_instantaneous"].native_field == "Vazao_Adotada"
    assert TELEMETRIC_PRODUCT_POLICIES["stage_instantaneous"].native_field == "Cota_Adotada"
    assert TELEMETRIC_PRODUCT_POLICIES["water_temperature_instantaneous"].native_field == "Temperatura_Agua"
    # Stage telemetric series is also cm -> m, like the daily series.
    assert TELEMETRIC_PRODUCT_POLICIES["stage_instantaneous"].conversion_factor == 100.0
    assert TELEMETRIC_PRODUCT_POLICIES["discharge_instantaneous"].conversion_factor == 1.0
    assert TELEMETRIC_PRODUCT_POLICIES["water_temperature_instantaneous"].conversion_factor == 1.0


def test_parse_telemetric_discharge_values_and_quality_flags() -> None:
    with _TELEMETRIC_ADOTADA_FIXTURE.open("rb") as f:
        content = f.read()
    parsed = parse_br_ana_telemetric_json(content, station_id="12345000", product_id="discharge_instantaneous")
    # 4 records, 1 has a null Vazao_Adotada -> dropped during parsing
    assert parsed.records.height == 3
    values = parsed.records["raw_value"].to_list()
    assert values == pytest.approx([1500.25, 1510.75, 1495.00])
    flags = parsed.records["quality_flag"].to_list()
    assert flags == ["0", "1", "2"]


def test_parse_telemetric_emits_naive_local_timestamp_issue() -> None:
    with _TELEMETRIC_ADOTADA_FIXTURE.open("rb") as f:
        content = f.read()
    parsed = parse_br_ana_telemetric_json(content, station_id="12345000", product_id="discharge_instantaneous")
    assert len(parsed.issues) == 1
    assert "naive_local_timestamp" in parsed.issues[0].code
    assert parsed.issues[0].severity == "info"


def test_parse_telemetric_timestamps_carry_time_of_day() -> None:
    with _TELEMETRIC_ADOTADA_FIXTURE.open("rb") as f:
        content = f.read()
    parsed = parse_br_ana_telemetric_json(content, station_id="12345000", product_id="stage_instantaneous")
    times = parsed.records["time"].to_list()
    # naive local times, 15-minute cadence — distinguishing this from the date-only daily series
    assert times[0] == datetime(2024, 6, 1, 0, 0, 0)
    assert times[1] == datetime(2024, 6, 1, 0, 15, 0)
    assert times[2] == datetime(2024, 6, 1, 0, 30, 0)


def test_parse_telemetric_water_temperature_from_detalhada() -> None:
    with _TELEMETRIC_DETALHADA_FIXTURE.open("rb") as f:
        content = f.read()
    parsed = parse_br_ana_telemetric_json(
        content, station_id="12345000", product_id="water_temperature_instantaneous"
    )
    # 3 records, 1 has null Temperatura_Agua -> dropped
    assert parsed.records.height == 2
    values = parsed.records["raw_value"].to_list()
    assert values == pytest.approx([26.4, 26.6])
    assert parsed.records["quality_flag"].to_list() == ["0", "1"]


def _make_telemetric_fixture_transport(
    auth_token: str = "testtoken123",
    adotada_fixture: Path = _TELEMETRIC_ADOTADA_FIXTURE,
    detalhada_fixture: Path = _TELEMETRIC_DETALHADA_FIXTURE,
):
    """Transport callable serving telemetric fixtures instead of live HTTP."""

    def transport(request: BrAnaTransportRequest) -> BrAnaTransportResponse:
        if request.url == AUTH_URL:
            body = json.dumps({"status": "OK", "items": {"tokenautenticacao": auth_token, "sucesso": True}}).encode()
            return BrAnaTransportResponse(
                content=body,
                status_code=200,
                retrieved_at=datetime(2026, 6, 3, 12, 0, 0, tzinfo=UTC),
            )
        if TELEMETRIC_DETALHADA_URL in request.url:
            content = detalhada_fixture.read_bytes()
        else:
            content = adotada_fixture.read_bytes()
        return BrAnaTransportResponse(
            content=content,
            status_code=200,
            retrieved_at=datetime(2026, 6, 3, 12, 0, 1, tzinfo=UTC),
        )

    return transport


def test_retrieve_discharge_instantaneous_returns_data_with_quality_flags() -> None:
    transport = _make_telemetric_fixture_transport()
    client_factory = lambda: BrAnaObservationClient(  # noqa: E731
        username="testuser",
        password="testpass",
        transport=transport,
    )
    request = ObservationRequest(
        provider_id="br_ana",
        stations=["12345000"],
        products=["discharge_instantaneous"],
        start=datetime(2024, 6, 1, tzinfo=UTC),
        end=datetime(2024, 6, 1, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    assert not result.data.is_empty()
    assert result.data.height == 3
    assert set(result.data["product_id"].unique().to_list()) == {"discharge_instantaneous"}

    quality_ann = result.row_annotations.data.filter(pl.col("annotation") == "quality_flag")
    assert quality_ann.height == 3
    assert sorted(quality_ann["value"].to_list()) == ["ok", "poor", "suspect"]


def test_retrieve_stage_instantaneous_converted_to_m_with_raw_cm_preserved() -> None:
    transport = _make_telemetric_fixture_transport()
    client_factory = lambda: BrAnaObservationClient(  # noqa: E731
        username="testuser",
        password="testpass",
        transport=transport,
    )
    request = ObservationRequest(
        provider_id="br_ana",
        stations=["12345000"],
        products=["stage_instantaneous"],
        start=datetime(2024, 6, 1, tzinfo=UTC),
        end=datetime(2024, 6, 1, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    values = result.data["value"].to_list()
    # 1280.50 cm -> 12.8050 m
    assert values[0] == pytest.approx(12.805)
    raw_ann = result.row_annotations.data.filter(pl.col("annotation") == "raw_value")
    raw_vals = sorted(float(v) for v in raw_ann["value"].to_list())
    assert raw_vals[0] == pytest.approx(1278.25)


def test_retrieve_water_temperature_instantaneous_uses_detalhada_endpoint() -> None:
    transport = _make_telemetric_fixture_transport()
    client_factory = lambda: BrAnaObservationClient(  # noqa: E731
        username="testuser",
        password="testpass",
        transport=transport,
    )
    request = ObservationRequest(
        provider_id="br_ana",
        stations=["12345000"],
        products=["water_temperature_instantaneous"],
        start=datetime(2024, 6, 1, tzinfo=UTC),
        end=datetime(2024, 6, 1, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    assert not result.data.is_empty()
    values = result.data["value"].to_list()
    assert values == pytest.approx(sorted([26.4, 26.6]))
    endpoints_ann = result.series_annotations.data.filter(pl.col("annotation") == "provider_endpoints")
    endpoints_json = endpoints_ann["value"][0]
    assert "HidroinfoanaSerieTelemetricaDetalhada" in endpoints_json


def test_retrieve_telemetric_timestamps_converted_brt_to_utc() -> None:
    transport = _make_telemetric_fixture_transport()
    client_factory = lambda: BrAnaObservationClient(  # noqa: E731
        username="testuser",
        password="testpass",
        transport=transport,
    )
    request = ObservationRequest(
        provider_id="br_ana",
        stations=["12345000"],
        products=["discharge_instantaneous"],
        start=datetime(2024, 6, 1, tzinfo=UTC),
        end=datetime(2024, 6, 1, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    times = result.data["time"].to_list()
    assert all(t.tzinfo is not None for t in times)
    # 2024-06-01 00:00 BRT (UTC-3) -> 2024-06-01 03:00 UTC
    assert times[0] == datetime(2024, 6, 1, 3, 0, 0, tzinfo=UTC)


def test_retrieve_telemetric_series_annotation_timezone_source() -> None:
    transport = _make_telemetric_fixture_transport()
    client_factory = lambda: BrAnaObservationClient(  # noqa: E731
        username="testuser",
        password="testpass",
        transport=transport,
    )
    request = ObservationRequest(
        provider_id="br_ana",
        stations=["12345000"],
        products=["stage_instantaneous"],
        start=datetime(2024, 6, 1, tzinfo=UTC),
        end=datetime(2024, 6, 1, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    sa = result.series_annotations.data
    tz_source = sa.filter(pl.col("annotation") == "timezone_source")["value"][0]
    assert tz_source == "naive_local_brt_minus_3"
    flag = sa.filter(pl.col("annotation") == "date_only_timestamp_flag")["value"][0]
    assert flag == "false"


def test_telemetric_provider_endpoints_in_provenance() -> None:
    client_factory = lambda: BrAnaObservationClient(username=None, password=None)  # noqa: E731
    request = ObservationRequest(
        provider_id="br_ana",
        stations=["12345000"],
        products=["discharge_instantaneous"],
        start=datetime(2024, 6, 1, tzinfo=UTC),
        end=datetime(2024, 6, 1, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    assert TELEMETRIC_ADOTADA_URL in result.provenance.endpoints
    assert TELEMETRIC_DETALHADA_URL in result.provenance.endpoints
