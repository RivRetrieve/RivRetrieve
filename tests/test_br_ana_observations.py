from __future__ import annotations

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
    BrAnaObservationClient,
    BrAnaTransportRequest,
    BrAnaTransportResponse,
)
from rivretrieve._internal.providers.br_ana.parser import parse_br_ana_json
from rivretrieve._internal.providers.br_ana.retrieval import retrieve_observations
from rivretrieve._internal.providers.br_ana.transform import PRODUCT_POLICIES

_TEST_DATA_DIR = Path(__file__).parent / "test_data"
_METADATA_FIXTURE = _TEST_DATA_DIR / "br_ana_metadata.json"
_DISCHARGE_FIXTURE = _TEST_DATA_DIR / "br_ana_12345000_vazao_2020.json"
_STAGE_FIXTURE = _TEST_DATA_DIR / "br_ana_60435000_cotas_2020.json"


# ---------------------------------------------------------------------------
# Catalogue generation
# ---------------------------------------------------------------------------


def test_generate_catalogue_station_count() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.stations.height == 2


def test_generate_catalogue_product_count() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.products.height == 2


def test_generate_catalogue_station_products_count() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    # 2 stations × 2 products = 4
    assert cat.station_products.height == 4


def test_generate_catalogue_station_fields() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    row = cat.stations.filter(pl.col("station_id") == "12345000")
    assert row.height == 1
    assert row["name"][0] == "RIO XINGU EM ALTAMIRA"
    assert row["country"][0] == "Brazil"
    assert row["elevation_m"][0] == pytest.approx(50.0)
    assert row["drainage_area_km2"][0] == pytest.approx(146080.0)


def test_generate_catalogue_filters_no_coord_station() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    ids = set(cat.stations["station_id"].to_list())
    assert "99999999" not in ids


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
    import json

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
            import json

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
