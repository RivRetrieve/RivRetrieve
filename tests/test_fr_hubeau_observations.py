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
from rivretrieve._internal.providers.fr_hubeau.parser import (
    parse_fr_hubeau_obs_elab_json,
    parse_fr_hubeau_obs_tr_json,
    parse_fr_hubeau_temperature_json,
)
from rivretrieve._internal.providers.fr_hubeau.retrieval import retrieve_observations
from rivretrieve._internal.providers.fr_hubeau.transform import PRODUCT_POLICIES

_TEST_DATA_DIR = Path(__file__).parent / "test_data"
_HYDRO_FIXTURE = _TEST_DATA_DIR / "fr_hubeau_metadata.json"
_TEMP_FIXTURE = _TEST_DATA_DIR / "fr_hubeau_temp_stations.json"
_OBS_ELAB_FIXTURE = _TEST_DATA_DIR / "fr_hubeau_O0050010_QmnJ_2020.json"
_OBS_TR_FIXTURE = _TEST_DATA_DIR / "fr_hubeau_O0050010_obs_tr_H.json"
_TEMP_CHRONO_FIXTURE = _TEST_DATA_DIR / "fr_hubeau_T123456001_temperature.json"


# ---------------------------------------------------------------------------
# Catalogue generation from fixture
# ---------------------------------------------------------------------------


def test_generate_catalogue_station_count() -> None:
    cat = generate_catalogue_from_fixture(_HYDRO_FIXTURE, _TEMP_FIXTURE)
    # 2 hydro (with valid coords) + 1 temp (with valid coords) = 3
    assert cat.stations.height == 3


def test_generate_catalogue_product_count() -> None:
    cat = generate_catalogue_from_fixture(_HYDRO_FIXTURE, _TEMP_FIXTURE)
    assert cat.products.height == 6


def test_generate_catalogue_station_products_cross() -> None:
    cat = generate_catalogue_from_fixture(_HYDRO_FIXTURE, _TEMP_FIXTURE)
    # 2 hydro × 5 products + 1 temp × 1 product = 11
    assert cat.station_products.height == 11


def test_generate_catalogue_hydro_station_fields() -> None:
    cat = generate_catalogue_from_fixture(_HYDRO_FIXTURE, _TEMP_FIXTURE)
    station = cat.stations.filter(pl.col("station_id") == "O0050010")
    assert station.height == 1
    assert station["name"][0] == "LA BIDOUZE A SAINT-PALAIS"
    assert station["country"][0] == "France"
    assert station["elevation_m"][0] == pytest.approx(42.5)
    assert station["drainage_area_km2"][0] == pytest.approx(830.0)


def test_generate_catalogue_temp_station_fields() -> None:
    import json

    cat = generate_catalogue_from_fixture(_HYDRO_FIXTURE, _TEMP_FIXTURE)
    station = cat.stations.filter(pl.col("station_id") == "T123456001")
    assert station.height == 1
    assert station["name"][0] == "LA DORDOGNE A ARGENTAT"
    assert station["elevation_m"][0] == pytest.approx(148.0)
    assert station["drainage_area_km2"][0] == pytest.approx(6940.0)
    meta = json.loads(station["metadata"][0])
    assert meta["station_type"] == "temperature"


def test_generate_catalogue_filters_no_coord_stations() -> None:
    cat = generate_catalogue_from_fixture(_HYDRO_FIXTURE, _TEMP_FIXTURE)
    station_ids = set(cat.stations["station_id"].to_list())
    assert "K123456001" not in station_ids  # hydro no-coord
    assert "T999999001" not in station_ids  # temp no-coord


def test_generate_catalogue_hydro_station_products() -> None:
    cat = generate_catalogue_from_fixture(_HYDRO_FIXTURE, _TEMP_FIXTURE)
    hydro_sp = cat.station_products.filter(pl.col("station_id") == "O0050010")
    hydro_products = set(hydro_sp["product_id"].to_list())
    assert hydro_products == {
        "discharge_instantaneous",
        "discharge_daily_mean",
        "discharge_daily_max",
        "stage_instantaneous",
        "stage_daily_max",
    }


def test_generate_catalogue_temp_station_products() -> None:
    cat = generate_catalogue_from_fixture(_HYDRO_FIXTURE, _TEMP_FIXTURE)
    temp_sp = cat.station_products.filter(pl.col("station_id") == "T123456001")
    assert temp_sp["product_id"].to_list() == ["water_temperature_instantaneous"]


# ---------------------------------------------------------------------------
# obs_elab parser (discharge_daily_mean)
# ---------------------------------------------------------------------------


def test_parse_obs_elab_discharge_daily_mean() -> None:
    content = _OBS_ELAB_FIXTURE.read_bytes()
    result = parse_fr_hubeau_obs_elab_json(content, station_id="O0050010", grandeur_code="QmnJ")
    assert not result.records.is_empty()
    assert result.records.height == 3
    assert result.records.schema["time"] == pl.Datetime(time_unit="us", time_zone="UTC")


def test_parse_obs_elab_date_only_utc_midnight() -> None:
    content = _OBS_ELAB_FIXTURE.read_bytes()
    result = parse_fr_hubeau_obs_elab_json(content, station_id="O0050010", grandeur_code="QmnJ")
    first = result.records.sort("time")["time"][0]
    assert first.year == 2020 and first.month == 1 and first.day == 1 and first.hour == 0


def test_parse_obs_elab_raw_values() -> None:
    content = _OBS_ELAB_FIXTURE.read_bytes()
    result = parse_fr_hubeau_obs_elab_json(content, station_id="O0050010", grandeur_code="QmnJ")
    sorted_records = result.records.sort("time")
    assert sorted_records["raw_value"][0] == pytest.approx(1500.0)
    assert sorted_records["raw_value"][1] == pytest.approx(2000.0)


def test_parse_obs_elab_date_only_issue() -> None:
    content = _OBS_ELAB_FIXTURE.read_bytes()
    result = parse_fr_hubeau_obs_elab_json(content, station_id="O0050010", grandeur_code="QmnJ")
    assert any("date_only_timestamp" in str(i.code) for i in result.issues)


def test_parse_obs_elab_filters_wrong_grandeur() -> None:
    content = _OBS_ELAB_FIXTURE.read_bytes()
    result = parse_fr_hubeau_obs_elab_json(content, station_id="O0050010", grandeur_code="HmnJ")
    assert result.records.is_empty()


# ---------------------------------------------------------------------------
# obs_tr parser (stage_instantaneous)
# ---------------------------------------------------------------------------


def test_parse_obs_tr_stage_instantaneous() -> None:
    content = _OBS_TR_FIXTURE.read_bytes()
    result = parse_fr_hubeau_obs_tr_json(content, station_id="O0050010", grandeur_code="H")
    assert not result.records.is_empty()
    assert result.records.height == 3
    assert result.records.schema["time"] == pl.Datetime(time_unit="us", time_zone="UTC")


def test_parse_obs_tr_full_utc_timestamps() -> None:
    content = _OBS_TR_FIXTURE.read_bytes()
    result = parse_fr_hubeau_obs_tr_json(content, station_id="O0050010", grandeur_code="H")
    first = result.records.sort("time")["time"][0]
    # 2020-01-01T12:00:00Z
    assert first.year == 2020 and first.month == 1 and first.day == 1 and first.hour == 12


def test_parse_obs_tr_raw_values_mm() -> None:
    content = _OBS_TR_FIXTURE.read_bytes()
    result = parse_fr_hubeau_obs_tr_json(content, station_id="O0050010", grandeur_code="H")
    sorted_records = result.records.sort("time")
    assert sorted_records["raw_value"][0] == pytest.approx(1200.0)  # mm


def test_parse_obs_tr_no_date_only_issue() -> None:
    content = _OBS_TR_FIXTURE.read_bytes()
    result = parse_fr_hubeau_obs_tr_json(content, station_id="O0050010", grandeur_code="H")
    assert not any("date_only_timestamp" in str(i.code) for i in result.issues)


def test_parse_obs_tr_filters_wrong_grandeur() -> None:
    content = _OBS_TR_FIXTURE.read_bytes()
    result = parse_fr_hubeau_obs_tr_json(content, station_id="O0050010", grandeur_code="Q")
    assert result.records.is_empty()


def test_parse_obs_tr_next_url_none() -> None:
    content = _OBS_TR_FIXTURE.read_bytes()
    result = parse_fr_hubeau_obs_tr_json(content, station_id="O0050010", grandeur_code="H")
    assert result.next_url is None


# ---------------------------------------------------------------------------
# temperature parser
# ---------------------------------------------------------------------------


def test_parse_temperature_records() -> None:
    content = _TEMP_CHRONO_FIXTURE.read_bytes()
    result = parse_fr_hubeau_temperature_json(content, station_id="T123456001")
    assert not result.records.is_empty()
    assert result.records.height == 3
    assert result.records.schema["time"] == pl.Datetime(time_unit="us", time_zone="UTC")


def test_parse_temperature_utc_from_date_time_fields() -> None:
    content = _TEMP_CHRONO_FIXTURE.read_bytes()
    result = parse_fr_hubeau_temperature_json(content, station_id="T123456001")
    first = result.records.sort("time")["time"][0]
    # date_mesure_temp=2020-01-01, heure_mesure_temp=08:00:00 → 2020-01-01T08:00:00Z
    assert first.year == 2020 and first.month == 1 and first.day == 1 and first.hour == 8


def test_parse_temperature_values_degc() -> None:
    content = _TEMP_CHRONO_FIXTURE.read_bytes()
    result = parse_fr_hubeau_temperature_json(content, station_id="T123456001")
    sorted_records = result.records.sort("time")
    assert sorted_records["raw_value"][0] == pytest.approx(5.2)
    assert sorted_records["raw_value"][1] == pytest.approx(6.1)


def test_parse_temperature_empty_content() -> None:
    result = parse_fr_hubeau_temperature_json(b"", station_id="T123456001")
    assert result.records.is_empty()
    assert any("missing_data" in str(i.code) for i in result.issues)


# ---------------------------------------------------------------------------
# Product policies
# ---------------------------------------------------------------------------


def test_product_policy_discharge_instantaneous() -> None:
    p = PRODUCT_POLICIES["discharge_instantaneous"]
    assert p.api_type == "obs_tr"
    assert p.grandeur_code == "Q"
    assert p.native_unit == "l/s"
    assert p.canonical_unit == "m3/s"
    assert p.conversion_factor == pytest.approx(1000.0)


def test_product_policy_discharge_daily_mean() -> None:
    p = PRODUCT_POLICIES["discharge_daily_mean"]
    assert p.api_type == "obs_elab"
    assert p.grandeur_code == "QmnJ"
    assert p.canonical_unit == "m3/s"


def test_product_policy_stage_instantaneous() -> None:
    p = PRODUCT_POLICIES["stage_instantaneous"]
    assert p.api_type == "obs_tr"
    assert p.grandeur_code == "H"
    assert p.native_unit == "mm"
    assert p.canonical_unit == "m"
    assert p.conversion_factor == pytest.approx(1000.0)


def test_product_policy_discharge_daily_max() -> None:
    p = PRODUCT_POLICIES["discharge_daily_max"]
    assert p.api_type == "obs_elab"
    assert p.grandeur_code == "QIXnJ"
    assert p.native_unit == "l/s"
    assert p.canonical_unit == "m3/s"
    assert p.conversion_factor == pytest.approx(1000.0)


def test_product_policy_stage_daily_max() -> None:
    p = PRODUCT_POLICIES["stage_daily_max"]
    assert p.api_type == "obs_elab"
    assert p.grandeur_code == "HIXnJ"
    assert p.native_unit == "mm"
    assert p.canonical_unit == "m"
    assert p.conversion_factor == pytest.approx(1000.0)


def test_product_policy_water_temperature_instantaneous() -> None:
    p = PRODUCT_POLICIES["water_temperature_instantaneous"]
    assert p.api_type == "temperature"
    assert p.grandeur_code is None
    assert p.native_unit == "degC"
    assert p.canonical_unit == "degC"
    assert p.conversion_factor == pytest.approx(1.0)


def test_no_stage_daily_mean_product() -> None:
    # HmnJ (daily mean height) does not exist in Hubeau obs_elab.
    assert "stage_daily_mean" not in PRODUCT_POLICIES


# ---------------------------------------------------------------------------
# Fixture-backed retrieval helpers
# ---------------------------------------------------------------------------


def _make_transport(responses_by_key: dict[str, bytes]):  # type: ignore[return]
    """Route requests by URL substring or param content."""

    def transport(request):  # type: ignore[no-untyped-def]
        url = request.url
        params = request.params or {}

        # Temperature endpoint
        if "temperature/chronique" in url or "temperature/chronique" in str(params):
            return FrHubeauTransportResponse(
                content=responses_by_key.get("temperature", b'{"count":0,"data":[],"next":null}'),
                status_code=200,
                retrieved_at=datetime(2026, 6, 3, 12, 0, 0, tzinfo=UTC),
            )
        # obs_tr endpoint
        if "observations_tr" in url:
            grandeur = str(params.get("grandeur_hydro", ""))
            key = f"obs_tr_{grandeur}"
            return FrHubeauTransportResponse(
                content=responses_by_key.get(key, b'{"count":0,"data":[],"next":null}'),
                status_code=200,
                retrieved_at=datetime(2026, 6, 3, 12, 0, 0, tzinfo=UTC),
            )
        # obs_elab (default)
        grandeur = str(params.get("grandeur_hydro", ""))
        key = f"obs_elab_{grandeur}"
        return FrHubeauTransportResponse(
            content=responses_by_key.get(key, b'{"count":0,"data":[],"next":null}'),
            status_code=200,
            retrieved_at=datetime(2026, 6, 3, 12, 0, 0, tzinfo=UTC),
        )

    return transport


# ---------------------------------------------------------------------------
# Retrieval: obs_elab discharge_daily_mean
# ---------------------------------------------------------------------------


def test_retrieve_discharge_daily_mean_conversion() -> None:
    transport = _make_transport({"obs_elab_QmnJ": _OBS_ELAB_FIXTURE.read_bytes()})
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
    sorted_data = result.data.sort("time")
    assert sorted_data["value"][0] == pytest.approx(1.5)  # 1500 l/s ÷ 1000
    assert sorted_data["value"][1] == pytest.approx(2.0)  # 2000 l/s ÷ 1000


def test_retrieve_discharge_daily_mean_utc_schema() -> None:
    transport = _make_transport({"obs_elab_QmnJ": _OBS_ELAB_FIXTURE.read_bytes()})
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


def test_retrieve_discharge_daily_mean_date_only_annotation() -> None:
    transport = _make_transport({"obs_elab_QmnJ": _OBS_ELAB_FIXTURE.read_bytes()})
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
    assert ann_dict.get("timezone_source") == "date_only_utc_midnight"
    assert ann_dict.get("date_only_timestamp_flag") == "true"


# ---------------------------------------------------------------------------
# Retrieval: obs_tr stage_instantaneous
# ---------------------------------------------------------------------------


def test_retrieve_stage_instantaneous_conversion() -> None:
    transport = _make_transport({"obs_tr_H": _OBS_TR_FIXTURE.read_bytes()})
    client_factory = lambda: FrHubeauObservationClient(transport=transport)  # noqa: E731

    request = ObservationRequest.from_inputs(
        provider_id="fr_hubeau",
        stations=("O0050010",),
        products=("stage_instantaneous",),
        start=datetime(2020, 1, 1, tzinfo=UTC),
        end=datetime(2020, 1, 2, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    assert not result.data.is_empty()
    sorted_data = result.data.sort("time")
    assert sorted_data["value"][0] == pytest.approx(1.2)  # 1200 mm ÷ 1000
    assert sorted_data["value"][1] == pytest.approx(1.25)  # 1250 mm ÷ 1000


def test_retrieve_stage_instantaneous_utc_full_timestamps() -> None:
    transport = _make_transport({"obs_tr_H": _OBS_TR_FIXTURE.read_bytes()})
    client_factory = lambda: FrHubeauObservationClient(transport=transport)  # noqa: E731

    request = ObservationRequest.from_inputs(
        provider_id="fr_hubeau",
        stations=("O0050010",),
        products=("stage_instantaneous",),
        start=datetime(2020, 1, 1, tzinfo=UTC),
        end=datetime(2020, 1, 2, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    first = result.data.sort("time")["time"][0]
    assert first.hour == 12  # not midnight — real UTC timestamp


def test_retrieve_stage_instantaneous_timezone_annotation() -> None:
    transport = _make_transport({"obs_tr_H": _OBS_TR_FIXTURE.read_bytes()})
    client_factory = lambda: FrHubeauObservationClient(transport=transport)  # noqa: E731

    request = ObservationRequest.from_inputs(
        provider_id="fr_hubeau",
        stations=("O0050010",),
        products=("stage_instantaneous",),
        start=datetime(2020, 1, 1, tzinfo=UTC),
        end=datetime(2020, 1, 2, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    ann = result.series_annotations.data
    ann_dict = dict(zip(ann["annotation"].to_list(), ann["value"].to_list(), strict=False))
    assert ann_dict.get("timezone_source") == "provider_timestamp_utc"
    assert "date_only_timestamp_flag" not in ann_dict


# ---------------------------------------------------------------------------
# Retrieval: temperature/chronique
# ---------------------------------------------------------------------------


def test_retrieve_water_temperature_values() -> None:
    transport = _make_transport({"temperature": _TEMP_CHRONO_FIXTURE.read_bytes()})
    client_factory = lambda: FrHubeauObservationClient(transport=transport)  # noqa: E731

    request = ObservationRequest.from_inputs(
        provider_id="fr_hubeau",
        stations=("T123456001",),
        products=("water_temperature_instantaneous",),
        start=datetime(2020, 1, 1, tzinfo=UTC),
        end=datetime(2020, 1, 2, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    assert not result.data.is_empty()
    sorted_data = result.data.sort("time")
    assert sorted_data["value"][0] == pytest.approx(5.2)
    assert sorted_data["value"][1] == pytest.approx(6.1)


def test_retrieve_water_temperature_no_conversion() -> None:
    transport = _make_transport({"temperature": _TEMP_CHRONO_FIXTURE.read_bytes()})
    client_factory = lambda: FrHubeauObservationClient(transport=transport)  # noqa: E731

    request = ObservationRequest.from_inputs(
        provider_id="fr_hubeau",
        stations=("T123456001",),
        products=("water_temperature_instantaneous",),
        start=datetime(2020, 1, 1, tzinfo=UTC),
        end=datetime(2020, 1, 2, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    ann = result.series_annotations.data
    ann_dict = dict(zip(ann["annotation"].to_list(), ann["value"].to_list(), strict=False))
    assert ann_dict.get("converted_unit") == "degC"
    assert ann_dict.get("timezone_source") == "provider_timestamp_utc"


def test_retrieve_water_temperature_utc_timestamps() -> None:
    transport = _make_transport({"temperature": _TEMP_CHRONO_FIXTURE.read_bytes()})
    client_factory = lambda: FrHubeauObservationClient(transport=transport)  # noqa: E731

    request = ObservationRequest.from_inputs(
        provider_id="fr_hubeau",
        stations=("T123456001",),
        products=("water_temperature_instantaneous",),
        start=datetime(2020, 1, 1, tzinfo=UTC),
        end=datetime(2020, 1, 2, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    assert result.data.schema["time"] == pl.Datetime(time_unit="us", time_zone="UTC")


# ---------------------------------------------------------------------------
# Retrieval: 404 and error handling
# ---------------------------------------------------------------------------


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
