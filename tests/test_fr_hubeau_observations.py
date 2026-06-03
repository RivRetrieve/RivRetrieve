from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

from rivretrieve._internal.observations import ObservationRequest
from rivretrieve._internal.providers.fr_hubeau.generate_catalogue import (
    generate_catalogue_from_fixture,
)
from rivretrieve._internal.providers.fr_hubeau.observation_client import (
    FrHubeauObservationClient,
    FrHubeauTransportResponse,
)
from rivretrieve._internal.providers.fr_hubeau.parser import parse_fr_hubeau_observation_json
from rivretrieve._internal.providers.fr_hubeau.retrieval import retrieve_observations
from rivretrieve._internal.providers.fr_hubeau.transform import PRODUCT_POLICIES

_TEST_DATA_DIR = Path(__file__).parent / "test_data"
_METADATA_FIXTURE = _TEST_DATA_DIR / "fr_hubeau_metadata.json"
_OBS_FIXTURE = _TEST_DATA_DIR / "fr_hubeau_O0050010_QmnJ_2020.json"


# ---------------------------------------------------------------------------
# Catalogue generation from fixture
# ---------------------------------------------------------------------------


def test_generate_catalogue_from_fixture_station_count() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    # fixture has 3 entries but only 2 have valid coordinates
    assert cat.stations.height == 2


def test_generate_catalogue_from_fixture_product_count() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.products.height == 2


def test_generate_catalogue_from_fixture_station_products_cross() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.station_products.height == 2 * 2


def test_generate_catalogue_station_fields() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    station = cat.stations.filter(pl.col("station_id") == "O0050010")
    assert station.height == 1
    assert station["name"][0] == "LA BIDOUZE A SAINT-PALAIS"
    assert station["country"][0] == "France"
    assert station["elevation_m"][0] == pytest.approx(42.5)
    assert station["drainage_area_km2"][0] == pytest.approx(830.0)


def test_generate_catalogue_filters_no_coordinate_stations() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    station_ids = set(cat.stations["station_id"].to_list())
    assert "K123456001" not in station_ids


def test_generate_catalogue_product_ids() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    product_ids = set(cat.products["product_id"].to_list())
    assert product_ids == {"discharge_daily_mean", "stage_daily_max"}


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def test_parse_discharge_daily_mean() -> None:
    content = _OBS_FIXTURE.read_bytes()
    result = parse_fr_hubeau_observation_json(content, station_id="O0050010", grandeur_code="QmnJ")
    assert not result.records.is_empty()
    assert result.records.height == 3


def test_parse_timestamps_are_utc() -> None:
    content = _OBS_FIXTURE.read_bytes()
    result = parse_fr_hubeau_observation_json(content, station_id="O0050010", grandeur_code="QmnJ")
    assert result.records.schema["time"] == pl.Datetime(time_unit="us", time_zone="UTC")


def test_parse_date_only_timestamp_utc_midnight() -> None:
    content = _OBS_FIXTURE.read_bytes()
    result = parse_fr_hubeau_observation_json(content, station_id="O0050010", grandeur_code="QmnJ")
    first_utc = result.records.sort("time")["time"][0]
    # 2020-01-01 date-only → 2020-01-01T00:00:00Z
    assert first_utc.year == 2020
    assert first_utc.month == 1
    assert first_utc.day == 1
    assert first_utc.hour == 0


def test_parse_raw_values_correct() -> None:
    content = _OBS_FIXTURE.read_bytes()
    result = parse_fr_hubeau_observation_json(content, station_id="O0050010", grandeur_code="QmnJ")
    sorted_records = result.records.sort("time")
    # resultat_obs_elab values in fixture
    assert sorted_records["raw_value"][0] == pytest.approx(1500.0)
    assert sorted_records["raw_value"][1] == pytest.approx(2000.0)
    assert sorted_records["raw_value"][2] == pytest.approx(1000.0)


def test_parse_date_only_issue_emitted() -> None:
    content = _OBS_FIXTURE.read_bytes()
    result = parse_fr_hubeau_observation_json(content, station_id="O0050010", grandeur_code="QmnJ")
    assert any("date_only_timestamp" in str(i.code) for i in result.issues)


def test_parse_empty_content_returns_missing_data_issue() -> None:
    result = parse_fr_hubeau_observation_json(b"", station_id="O0050010", grandeur_code="QmnJ")
    assert result.records.is_empty()
    assert any("missing_data" in str(i.code) for i in result.issues)


def test_parse_filters_wrong_grandeur() -> None:
    content = _OBS_FIXTURE.read_bytes()
    result = parse_fr_hubeau_observation_json(content, station_id="O0050010", grandeur_code="HIXnJ")
    # fixture only has QmnJ entries, so HIXnJ filter produces no rows
    assert result.records.is_empty()


def test_parse_next_url_is_none_for_single_page() -> None:
    content = _OBS_FIXTURE.read_bytes()
    result = parse_fr_hubeau_observation_json(content, station_id="O0050010", grandeur_code="QmnJ")
    assert result.next_url is None


# ---------------------------------------------------------------------------
# Product policies
# ---------------------------------------------------------------------------


def test_product_policy_discharge_daily_mean() -> None:
    policy = PRODUCT_POLICIES["discharge_daily_mean"]
    assert policy.grandeur_code == "QmnJ"
    assert policy.native_unit == "l/s"
    assert policy.canonical_unit == "m3/s"
    assert policy.conversion_factor == pytest.approx(1000.0)


def test_product_policy_stage_daily_max() -> None:
    policy = PRODUCT_POLICIES["stage_daily_max"]
    assert policy.grandeur_code == "HIXnJ"
    assert policy.native_unit == "mm"
    assert policy.canonical_unit == "m"
    assert policy.conversion_factor == pytest.approx(1000.0)


# ---------------------------------------------------------------------------
# Fixture-backed retrieval
# ---------------------------------------------------------------------------


def _make_transport(station_id: str, response_bytes: bytes):  # type: ignore[return]
    def transport(request):  # type: ignore[no-untyped-def]
        if station_id in (request.params or {}).get("code_entite", "") or station_id in request.url:
            return FrHubeauTransportResponse(
                content=response_bytes,
                status_code=200,
                retrieved_at=datetime(2026, 6, 3, 12, 0, 0, tzinfo=UTC),
            )
        return FrHubeauTransportResponse(
            content=b'{"count":0,"data":[],"next":null}',
            status_code=200,
            retrieved_at=datetime(2026, 6, 3, tzinfo=UTC),
        )

    return transport


def test_retrieve_discharge_daily_mean() -> None:
    content = _OBS_FIXTURE.read_bytes()
    transport = _make_transport("O0050010", content)
    client_factory = lambda: FrHubeauObservationClient(transport=transport)  # noqa: E731

    request = ObservationRequest.from_inputs(
        provider_id="fr_hubeau",
        stations=("O0050010",),
        products=("discharge_daily_mean",),
        start=datetime(2020, 1, 1, tzinfo=UTC),
        end=datetime(2020, 1, 3, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    assert not result.data.is_empty()
    assert result.data["product_id"].unique().to_list() == ["discharge_daily_mean"]
    assert result.data.schema["time"] == pl.Datetime(time_unit="us", time_zone="UTC")


def test_retrieve_conversion_ls_to_m3s() -> None:
    content = _OBS_FIXTURE.read_bytes()
    transport = _make_transport("O0050010", content)
    client_factory = lambda: FrHubeauObservationClient(transport=transport)  # noqa: E731

    request = ObservationRequest.from_inputs(
        provider_id="fr_hubeau",
        stations=("O0050010",),
        products=("discharge_daily_mean",),
        start=datetime(2020, 1, 1, tzinfo=UTC),
        end=datetime(2020, 1, 3, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    sorted_data = result.data.sort("time")
    # 1500 l/s ÷ 1000 = 1.5 m³/s
    assert sorted_data["value"][0] == pytest.approx(1.5)
    # 2000 l/s ÷ 1000 = 2.0 m³/s
    assert sorted_data["value"][1] == pytest.approx(2.0)


def test_retrieve_result_data_utc_schema() -> None:
    content = _OBS_FIXTURE.read_bytes()
    transport = _make_transport("O0050010", content)
    client_factory = lambda: FrHubeauObservationClient(transport=transport)  # noqa: E731

    request = ObservationRequest.from_inputs(
        provider_id="fr_hubeau",
        stations=("O0050010",),
        products=("discharge_daily_mean",),
        start=datetime(2020, 1, 1, tzinfo=UTC),
        end=datetime(2020, 1, 3, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    assert result.data.schema["time"] == pl.Datetime(time_unit="us", time_zone="UTC")
    assert "station_id" in result.data.columns
    assert "product_id" in result.data.columns
    assert "value" in result.data.columns


def test_retrieve_series_annotations_timezone() -> None:
    content = _OBS_FIXTURE.read_bytes()
    transport = _make_transport("O0050010", content)
    client_factory = lambda: FrHubeauObservationClient(transport=transport)  # noqa: E731

    request = ObservationRequest.from_inputs(
        provider_id="fr_hubeau",
        stations=("O0050010",),
        products=("discharge_daily_mean",),
        start=datetime(2020, 1, 1, tzinfo=UTC),
        end=datetime(2020, 1, 3, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    ann = result.series_annotations.data
    ann_dict = dict(zip(ann["annotation"].to_list(), ann["value"].to_list(), strict=False))
    assert ann_dict.get("resolved_timezone") == "UTC"
    assert ann_dict.get("timezone_source") == "date_only_utc_midnight"
    assert ann_dict.get("date_only_timestamp_flag") == "true"


def test_retrieve_date_only_timestamp_issue_emitted() -> None:
    content = _OBS_FIXTURE.read_bytes()
    transport = _make_transport("O0050010", content)
    client_factory = lambda: FrHubeauObservationClient(transport=transport)  # noqa: E731

    request = ObservationRequest.from_inputs(
        provider_id="fr_hubeau",
        stations=("O0050010",),
        products=("discharge_daily_mean",),
        start=datetime(2020, 1, 1, tzinfo=UTC),
        end=datetime(2020, 1, 3, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    assert any("date_only_timestamp" in str(i.code) for i in result.issues)


def test_retrieve_404_emits_issue_not_fatal() -> None:
    import requests

    def transport_404(request):  # type: ignore[no-untyped-def]
        mock_resp = type("R", (), {"status_code": 404})()
        raise requests.HTTPError(response=mock_resp)

    client_factory = lambda: FrHubeauObservationClient(transport=transport_404)  # noqa: E731
    request = ObservationRequest.from_inputs(
        provider_id="fr_hubeau",
        stations=("O0050010",),
        products=("discharge_daily_mean",),
        start=datetime(2020, 1, 1, tzinfo=UTC),
        end=datetime(2020, 1, 3, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    assert result.data.is_empty()
    assert any("http_not_found" in str(i.code) for i in result.issues)
