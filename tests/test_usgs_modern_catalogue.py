"""Modern catalogue tests; mutations below are authored negative controls."""

import gzip
import json
from pathlib import Path

import pytest

from rivretrieve._internal.catalogues.source_series import decode_source_descriptions
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.usgs_nwis.catalogue_series import modern_source_descriptions
from rivretrieve._internal.providers.usgs_nwis.generate_catalogue import read_modern_metadata

CATALOGUE = Path("src/rivretrieve/_internal/providers/usgs_nwis/catalogue")


def test_modern_concrete_snapshot_retains_siblings_unknowns_and_selected_station_scope():
    descriptions = decode_source_descriptions((CATALOGUE / "source_series.json").read_bytes())
    locations = json.loads((CATALOGUE / "monitoring_locations.json").read_text())
    assert len(locations) == 27934
    # Independently reconciled current source metadata plus 22 unchanged historical series.
    assert len(descriptions.descriptions) == 62046
    assert len({id(fact) for item in descriptions.descriptions for fact in item.facts}) == 8
    assert {item.station_id for item in descriptions.descriptions} <= locations.keys()
    siblings = [
        item
        for item in descriptions.descriptions
        if item.station_id == "02196000" and item.product_id == "discharge_daily_mean"
    ]
    assert {item.variant for item in siblings} == {
        "0df18b246e8f48ec8e6547a92070e94a",
        "4d186669708e4dc18f84d271efb953a1",
    }
    assert all(item.identity.description is None for item in siblings)
    unknowns = [item for item in descriptions.descriptions if item.facts[0].statistic.value is None]
    assert len(unknowns) == 6
    assert all(item.facts[0].temporal_support.value is None for item in unknowns)
    assert (CATALOGUE / "source_series.json").stat().st_size < 100_000_000


@pytest.mark.recorded("research/usgs-modern-coverage")
def test_description_preserves_empty_and_null_without_parameter_prose(
    retained_evidence_root,
):
    page = json.loads(
        gzip.decompress(
            (retained_evidence_root / "research/usgs-modern-coverage" / "metadata-00060-0000.json.gz").read_bytes()
        )
    )
    properties = page["features"][0]["properties"]
    locations = {"10172640": "USGS-10172640"}
    for description in (None, "", "publisher text"):
        # Authored description variations on otherwise untouched publisher metadata.
        altered = {**properties, "web_description": description}
        result = modern_source_descriptions([altered], locations)
        assert result.descriptions[0].identity.description == description


@pytest.mark.recorded("research/usgs-modern-coverage")
def test_saved_pagination_rejects_incomplete_chain(retained_evidence_root, tmp_path):
    completion = json.loads(
        (retained_evidence_root / "research/usgs-modern-coverage" / "metadata-00060-completion.json").read_text()
    )
    completion["status"] = "incomplete"  # Authored negative control.
    (tmp_path / "metadata-00060-completion.json").write_text(json.dumps(completion))
    with pytest.raises(FatalContractError, match="complete unsorted"):
        read_modern_metadata(tmp_path)


def test_materialization_preserves_shared_immutable_physical_facts():
    from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
    from rivretrieve._internal.catalogues.source_series import materialize_series
    from rivretrieve._internal.source_series import SeriesScope

    artifact = load_packaged_catalogue_artifact(CATALOGUE)
    series, _ = materialize_series(artifact, scope=SeriesScope(station_ids=("02196000",)))
    siblings = [item for item in series if item.product_id == "discharge_daily_mean"]
    assert len(siblings) == 2
    assert siblings[0].facts[0] is siblings[1].facts[0]
    assert artifact.source_descriptions is not None
    description = next(
        item for item in artifact.source_descriptions.descriptions if item.series_id == siblings[0].series_id
    )
    assert siblings[0].facts[0] is description.facts[0]


def test_modern_observation_provenance_keeps_legacy_calls_independent():
    from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact

    artifact = load_packaged_catalogue_artifact(CATALOGUE)
    evidence = artifact.acquisition_provenance
    assert evidence is not None
    acquisitions = evidence.acquisitions
    identifiers = set(acquisitions["acquisition_id"].to_list())
    assert {"observation_request", "modern_observation_request"} <= identifiers
    assert "source.observation.modern_values_qualifiers_and_timestamps" in evidence.facts["name"].to_list()


def test_explicit_historical_sibling_retains_identity_and_physical_cache_facts():
    from rivretrieve._internal.providers.usgs_nwis.catalogue_series import retain_source_descriptions

    def feature(identifier):
        return {
            "id": identifier,
            "monitoring_location_id": "USGS-001",
            "parameter_code": "00060",
            "computation_period_identifier": "Daily",
            "statistic_id": "00003",
            "unit_of_measure": "ft^3/s",
            "computation_identifier": "Mean",
            "web_description": None,
            "sublocation_identifier": None,
        }

    locations = {"001": "USGS-001"}
    current = modern_source_descriptions([feature("current")], locations)
    historical = modern_source_descriptions([feature("old"), feature("unselected")], locations)
    old = historical.descriptions[0]
    result = retain_source_descriptions(current, historical, ("old",), locations)
    retained = next(item for item in result.descriptions if item.variant == "old")
    assert {item.variant for item in result.descriptions} == {"current", "old"}
    assert retained.series_id == old.series_id
    assert retained.facts == old.facts
    assert retained.identity.published_id == old.identity.published_id
    assert retained == old
    assert next(item for item in result.descriptions if item.variant == "current") == current.descriptions[0]
    for ids in (("missing",), ("old", "old")):
        with pytest.raises(ValueError):
            retain_source_descriptions(current, historical, ids, locations)
    with pytest.raises(ValueError):
        retain_source_descriptions(current, current, ("current",), locations)
    with pytest.raises(ValueError):
        retain_source_descriptions(current, historical, ("old",), {})


def test_modern_station_universe_includes_continuous_nonstream_and_unlocated():
    from datetime import UTC, datetime

    import polars as pl
    import polars.testing as plt

    from rivretrieve._internal.catalogues.native import RetrievedAt
    from rivretrieve._internal.providers.usgs_nwis.generate_catalogue import build_modern_stations

    def location(number, geometry, state="55"):
        return {
            "type": "Feature",
            "id": f"USGS-{number}",
            "geometry": geometry,
            "properties": {
                "agency_code": "USGS",
                "monitoring_location_number": number,
                "monitoring_location_name": f"Canal {number}",
                "state_code": state,
                "country_code": "US",
            },
        }

    locations = [
        location("001", {"type": "Point", "coordinates": [-89.0, 43.0]}),
        location("002", None),
        location("003", None, "72"),
    ]
    native, stations = build_modern_stations(
        locations,
        {"USGS-001", "USGS-002", "USGS-003"},
        retrieved_at=RetrievedAt(datetime(2026, 11, 1, tzinfo=UTC)),
        baseline_locations={},
    )
    expected = pl.DataFrame(
        {
            "provider_id": ["usgs_nwis", "usgs_nwis"],
            "station_id": ["001", "002"],
            "latitude": [43.0, None],
            "longitude": [-89.0, None],
            "crs": ["EPSG:4326", "unknown"],
        }
    )
    plt.assert_frame_equal(stations, expected)
    assert native.data["monitoring_location_name"].to_list() == ["Canal 001", "Canal 002"]


def test_modern_station_universe_refuses_missing_or_conflicting_identity():
    from datetime import UTC, datetime

    from rivretrieve._internal.catalogues.native import RetrievedAt
    from rivretrieve._internal.providers.usgs_nwis.generate_catalogue import build_modern_stations

    instant = RetrievedAt(datetime(2026, 11, 1, tzinfo=UTC))
    with pytest.raises(FatalContractError, match="missing"):
        build_modern_stations([], {"USGS-001"}, retrieved_at=instant, baseline_locations={})
    feature = {
        "type": "Feature",
        "id": "USGS-001",
        "geometry": None,
        "properties": {
            "agency_code": "OTHER",
            "monitoring_location_number": "001",
            "monitoring_location_name": "Name",
            "state_code": "55",
            "country_code": "US",
        },
    }
    with pytest.raises(FatalContractError, match="identity"):
        build_modern_stations([feature], {"USGS-001"}, retrieved_at=instant, baseline_locations={})


def test_modern_catalogue_builds_all_six_products_without_legacy_availability():
    from datetime import UTC, datetime

    from rivretrieve._internal.catalogues.native import RetrievedAt
    from rivretrieve._internal.providers.usgs_nwis.generate_catalogue import build_modern_catalogue

    location = {
        "type": "Feature",
        "id": "USGS-001",
        "geometry": None,
        "properties": {
            "agency_code": "USGS",
            "monitoring_location_number": "001",
            "monitoring_location_name": "Reservoir",
            "state_code": "55",
            "country_code": "US",
        },
    }
    features = []
    for index, (parameter, period, statistic) in enumerate(
        [
            ("00060", "Daily", "00003"),
            ("00060", "Points", "00011"),
            ("00065", "Daily", "00003"),
            ("00065", "Daily", "00001"),
            ("00065", "Daily", "00002"),
            ("00065", "Points", "00011"),
        ]
    ):
        features.append(
            {
                "id": str(index),
                "monitoring_location_id": "USGS-001",
                "parameter_code": parameter,
                "computation_period_identifier": period,
                "statistic_id": statistic,
                "unit_of_measure": "ft^3/s" if parameter == "00060" else "ft",
                "computation_identifier": {"00003": "Mean", "00001": "Max", "00002": "Min", "00011": "Instantaneous"}[
                    statistic
                ],
                "web_description": None,
                "sublocation_identifier": None,
            }
        )
    catalogue = build_modern_catalogue(
        features, [location], retrieved_at=RetrievedAt(datetime(2026, 11, 1, tzinfo=UTC)), baseline_locations={}
    )
    assert catalogue.stations["station_id"].to_list() == ["001"]
    assert catalogue.station_products.height == 6
    assert set(catalogue.station_products["availability"].to_list()) == {"available"}
    assert len(catalogue.source_descriptions.descriptions) == 6
    assert catalogue.station_products["published_record_start_date"].null_count() == 6


def test_location_recordings_validate_exact_batch_and_bytes(tmp_path):
    import hashlib

    from rivretrieve._internal.providers.usgs_nwis.generate_catalogue import read_monitoring_locations

    feature = {"type": "Feature", "id": "USGS-001", "properties": {}, "geometry": None}
    body = json.dumps({"type": "FeatureCollection", "features": [feature], "numberReturned": 1, "links": []}).encode()
    url = "https://api.waterdata.usgs.gov/ogcapi/v1/collections/monitoring-locations/items?f=json&id=USGS-001&limit=1"
    receipt = {
        "url": url,
        "final_url": url,
        "status": 200,
        "sha256": hashlib.sha256(body).hexdigest(),
        "bytes": len(body),
        "retrieved_at": "2026-11-01T00:00:00Z",
    }
    (tmp_path / "body.gz").write_bytes(gzip.compress(body))
    (tmp_path / "receipt.json").write_text(json.dumps(receipt))
    manifest = [{"body": "body.gz", "receipt": "receipt.json"}]
    path = tmp_path / "locations.json"
    path.write_text(json.dumps(manifest))
    assert read_monitoring_locations(path)[0] == [feature]
    receipt["url"] = receipt["final_url"] = url.replace("USGS-001", "USGS-missing")
    (tmp_path / "receipt.json").write_text(json.dumps(receipt))
    with pytest.raises(FatalContractError, match="identities"):
        read_monitoring_locations(path)
    receipt["url"] = receipt["final_url"] = url
    (tmp_path / "receipt.json").write_text(json.dumps(receipt))
    (tmp_path / "body.gz").write_bytes(gzip.compress(body + b" "))
    with pytest.raises(FatalContractError, match="receipt"):
        read_monitoring_locations(path)


def test_modern_catalogue_keeps_continuous_only_and_retained_canadian_series():
    from datetime import UTC, datetime

    from rivretrieve._internal.catalogues.native import RetrievedAt
    from rivretrieve._internal.providers.usgs_nwis.generate_catalogue import build_modern_catalogue

    def feature(identifier, number, period, statistic, computation):
        return {
            "id": identifier,
            "monitoring_location_id": f"USGS-{number}",
            "parameter_code": "00060",
            "computation_period_identifier": period,
            "statistic_id": statistic,
            "computation_identifier": computation,
            "unit_of_measure": "ft^3/s",
            "web_description": None,
            "sublocation_identifier": None,
        }

    def location(number, state):
        return {
            "type": "Feature",
            "id": f"USGS-{number}",
            "geometry": None,
            "properties": {
                "agency_code": "USGS",
                "monitoring_location_number": number,
                "monitoring_location_name": number,
                "state_code": state,
                "country_code": "US",
            },
        }

    current = [feature("continuous", "001", "Points", "00011", "Instantaneous")]
    historical = [feature("retained", "002", "Daily", "00003", "Mean")]
    result = build_modern_catalogue(
        current,
        [location("001", "55"), location("002", "ON")],
        retrieved_at=RetrievedAt(datetime(2026, 11, 1, tzinfo=UTC)),
        historical_features=historical,
        retained_series_ids=("retained",),
        retained_locations=("USGS-002",),
        baseline_locations={},
    )
    assert result.stations["station_id"].to_list() == ["001", "002"]
    available = result.station_products.filter(__import__("polars").col("availability") == "available")
    assert set(available.select("station_id", "product_id").iter_rows()) == {
        ("001", "discharge_instantaneous"),
        ("002", "discharge_daily_mean"),
    }
    assert {item.identity.published_id for item in result.source_descriptions.descriptions} == {
        "continuous",
        "retained",
    }


@pytest.mark.parametrize(
    "geometry",
    [
        {"type": "Point", "coordinates": [181, 45]},
        {"type": "Point", "coordinates": ["west", 45]},
    ],
)
def test_modern_location_rejects_invalid_published_geometry(geometry):
    from datetime import UTC, datetime

    from rivretrieve._internal.catalogues.native import RetrievedAt
    from rivretrieve._internal.providers.usgs_nwis.generate_catalogue import build_modern_stations

    feature = {
        "type": "Feature",
        "id": "USGS-001",
        "geometry": geometry,
        "properties": {
            "agency_code": "USGS",
            "monitoring_location_number": "001",
            "monitoring_location_name": "Canal",
            "state_code": "55",
            "country_code": "US",
        },
    }
    with pytest.raises(FatalContractError, match="coordinates"):
        build_modern_stations(
            [feature], {"USGS-001"}, retrieved_at=RetrievedAt(datetime(2026, 11, 1, tzinfo=UTC)), baseline_locations={}
        )


def test_legacy_enrichment_preserves_expanded_locations_without_legacy_series():
    from datetime import UTC, datetime

    from rivretrieve._internal.catalogues.native import RetrievedAt
    from rivretrieve._internal.providers.usgs_nwis import generate_catalogue as generator

    expanded = dict.fromkeys(generator.EXPANDED_HEADER, "")
    expanded.update(agency_cd="USGS", site_no="001", drain_area_va="12.0")
    result = generator.refresh_native_table(
        [],
        [expanded],
        retrieved_at=RetrievedAt(datetime(2026, 11, 1, tzinfo=UTC)),
    ).value.data
    assert result["site_no"].to_list() == ["001"]
    assert result["drain_area_va"].to_list() == ["12.0"]
    assert result["ts_id"].to_list() == [[]]


def test_legacy_claims_match_modern_agency_and_number():
    import polars as pl

    from rivretrieve._internal.providers.usgs_nwis.catalogue_series import catalogue_claims

    legacy = pl.DataFrame(
        {
            "agency_cd": ["OTHER", "USGS"],
            "site_no": ["001", "002"],
            "data_type_cd": [["dv"], ["dv"]],
            "parm_cd": [["00060"], ["00060"]],
            "stat_cd": [["00003"], ["00003"]],
            "ts_id": [["other-ts"], ["usgs-ts"]],
            "loc_web_ds": [["Other agency"], ["USGS claim"]],
        }
    )
    modern = pl.DataFrame(
        {
            "agency_code": ["USGS", "USGS"],
            "monitoring_location_number": ["001", "002"],
            "station_id": ["001", "USGS-002"],
        }
    )
    claims = catalogue_claims(
        legacy,
        {("dv", "00060", "00003"): "discharge_daily_mean"},
        modern,
        evidence=("catalogue:usgs_nwis:source.legacy_series_claims.input_0",),
    )
    assert claims.select("station_id", "published_id").rows() == [("USGS-002", "usgs-ts")]


@pytest.mark.parametrize("next_suffix", ["&offset=1", "&offset=0", "&offset=1&state_code=55"])
def test_location_recordings_follow_exact_publisher_chain_to_terminal_page(tmp_path, next_suffix):
    import hashlib

    from rivretrieve._internal.providers.usgs_nwis.generate_catalogue import read_monitoring_locations

    first = "https://api.waterdata.usgs.gov/ogcapi/v1/collections/monitoring-locations/items?f=json&id=USGS-001%2CUSGS-002&limit=2"
    second = first + next_suffix
    selection = []
    for index, (url, identifier, links) in enumerate(
        [
            (first, "USGS-001", [{"rel": "next", "href": second}]),
            (second, "USGS-002", [{"rel": "next", "href": first + "&offset=2"}]),
            (first + "&offset=2", None, []),
        ]
    ):
        feature = {"type": "Feature", "id": identifier, "properties": {}, "geometry": None}
        page_features = [] if identifier is None else [feature]
        raw = json.dumps(
            {
                "type": "FeatureCollection",
                "features": page_features,
                "numberReturned": len(page_features),
                "links": links,
            }
        ).encode()
        body, receipt = f"page-{index}.gz", f"page-{index}.receipt.json"
        (tmp_path / body).write_bytes(gzip.compress(raw))
        (tmp_path / receipt).write_text(
            json.dumps(
                {
                    "url": url,
                    "final_url": url,
                    "status": 200,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "bytes": len(raw),
                    "retrieved_at": "2026-11-01T00:00:00Z",
                }
            )
        )
        selection.append({"body": body, "receipt": receipt})
    manifest = tmp_path / "locations.json"
    manifest.write_text(json.dumps(selection))
    if next_suffix != "&offset=1":
        with pytest.raises(FatalContractError, match="changes identity|fails to advance"):
            read_monitoring_locations(manifest)
        return
    assert [item["id"] for item in read_monitoring_locations(manifest)[0]] == ["USGS-001", "USGS-002"]
    manifest.write_text(json.dumps(selection[:1]))
    with pytest.raises(FatalContractError, match="incomplete"):
        read_monitoring_locations(manifest)
    manifest.write_text(json.dumps(selection[::-1]))
    with pytest.raises(FatalContractError, match="offset|chain"):
        read_monitoring_locations(manifest)


@pytest.mark.parametrize(
    "country,state,included", [("CA", "94", False), ("CA", "01", False), ("JP", "00", False), ("US", "55", True)]
)
def test_modern_station_scope_uses_country_before_state(country, state, included):
    from datetime import UTC, datetime

    from rivretrieve._internal.catalogues.native import RetrievedAt
    from rivretrieve._internal.providers.usgs_nwis.generate_catalogue import build_modern_stations

    location = {
        "type": "Feature",
        "id": "USGS-001",
        "geometry": None,
        "properties": {
            "agency_code": "USGS",
            "monitoring_location_number": "001",
            "country_code": country,
            "state_code": state,
        },
    }
    _, stations = build_modern_stations(
        [location], {"USGS-001"}, retrieved_at=RetrievedAt(datetime(2026, 11, 1, tzinfo=UTC)), baseline_locations={}
    )
    assert stations["station_id"].to_list() == (["001"] if included else [])


@pytest.mark.parametrize("country,state", [(None, "55"), ("", "55"), (55, "55"), ("US", None), ("US", "unknown")])
def test_modern_station_scope_refuses_unresolved_geography(country, state):
    from datetime import UTC, datetime

    from rivretrieve._internal.catalogues.native import RetrievedAt
    from rivretrieve._internal.providers.usgs_nwis.generate_catalogue import build_modern_stations

    location = {
        "type": "Feature",
        "id": "USGS-001",
        "geometry": None,
        "properties": {
            "agency_code": "USGS",
            "monitoring_location_number": "001",
            "country_code": country,
            "state_code": state,
        },
    }
    with pytest.raises(FatalContractError):
        build_modern_stations(
            [location], {"USGS-001"}, retrieved_at=RetrievedAt(datetime(2026, 11, 1, tzinfo=UTC)), baseline_locations={}
        )


@pytest.mark.parametrize(
    "baseline,expected", [({"001": "CA574-001"}, ["001", "USGS-001"]), ({}, ["CA574-001", "USGS-001"])]
)
def test_modern_collision_preserves_explicit_baseline(baseline, expected):
    from datetime import UTC, datetime

    from rivretrieve._internal.catalogues.native import RetrievedAt
    from rivretrieve._internal.providers.usgs_nwis.generate_catalogue import build_modern_stations

    features = [
        {
            "type": "Feature",
            "id": agency + "-001",
            "geometry": None,
            "properties": {
                "agency_code": agency,
                "monitoring_location_number": "001",
                "country_code": "US",
                "state_code": "06",
            },
        }
        for agency in ("USGS", "CA574")
    ]
    native, stations = build_modern_stations(
        features,
        {f["id"] for f in features},
        retrieved_at=RetrievedAt(datetime(2026, 11, 1, tzinfo=UTC)),
        baseline_locations=baseline,
    )
    assert stations["station_id"].to_list() == expected
    assert native.data["monitoring_location_number"].to_list() == ["001", "001"]
    from rivretrieve._internal.providers.usgs_nwis.generate_catalogue import build_modern_catalogue

    series = [
        {
            "id": "daily",
            "monitoring_location_id": "CA574-001",
            "parameter_code": "00060",
            "computation_period_identifier": "Daily",
            "statistic_id": "00003",
            "computation_identifier": "Mean",
            "unit_of_measure": "ft^3/s",
            "begin": "2000-01-01T00:00:00Z",
            "end": "2001-01-01T00:00:00Z",
        },
        {
            "id": "stage",
            "monitoring_location_id": "USGS-001",
            "parameter_code": "00065",
            "computation_period_identifier": "Points",
            "statistic_id": "00011",
            "computation_identifier": "Instantaneous",
            "unit_of_measure": "ft",
            "begin": "2000-01-01T00:00:00Z",
            "end": "2001-01-01T00:00:00Z",
        },
    ]
    for item in series:
        item.update(web_description=None, sublocation_identifier=None)
    catalogue = build_modern_catalogue(
        series, features, baseline_locations=baseline, retrieved_at=RetrievedAt(datetime(2026, 11, 1, tzinfo=UTC))
    )
    assert {(item.station_id, item.product_id) for item in catalogue.source_descriptions.descriptions} == {
        (expected[0], "discharge_daily_mean"),
        ("USGS-001", "stage_instantaneous"),
    }

    assert dict(native.data.select("station_id", "monitoring_location_id").iter_rows()) == dict(
        zip(expected, ["CA574-001", "USGS-001"], strict=True)
    )


def test_baseline_station_without_supported_series_remains_registered():
    from datetime import UTC, datetime

    from rivretrieve._internal.catalogues.native import RetrievedAt
    from rivretrieve._internal.providers.usgs_nwis.generate_catalogue import build_modern_catalogue

    location = {
        "type": "Feature",
        "id": "USGS-001",
        "geometry": None,
        "properties": {
            "agency_code": "USGS",
            "monitoring_location_number": "001",
            "country_code": "US",
            "state_code": "55",
        },
    }
    result = build_modern_catalogue(
        [],
        [location],
        baseline_locations={"001": "USGS-001"},
        retrieved_at=RetrievedAt(datetime(2026, 11, 1, tzinfo=UTC)),
    )
    assert result.stations["station_id"].to_list() == ["001"]
    assert result.station_products.height == 6
    assert result.station_products["availability"].to_list() == ["unavailable"] * 6
    with pytest.raises(FatalContractError, match="missing"):
        build_modern_catalogue(
            [], [], baseline_locations={"001": "USGS-001"}, retrieved_at=RetrievedAt(datetime(2026, 11, 1, tzinfo=UTC))
        )


def test_legacy_alternative_rows_preserve_exact_fields_and_matching_series():
    from datetime import UTC, datetime

    from rivretrieve._internal.catalogues.native import RetrievedAt
    from rivretrieve._internal.providers.usgs_nwis import generate_catalogue as generator

    first = dict.fromkeys(generator.EXPANDED_HEADER, "")
    first.update(agency_cd="USGS", site_no="09372200", drain_area_va="720.00", dec_lat_va="1")
    second = {**first, "drain_area_va": "720.0", "dec_lat_va": "2"}
    series = dict.fromkeys(generator.SERIES_HEADER, "")
    series.update({name: second[name] for name in generator.SHARED_STATION_FIELDS})
    series.update(data_type_cd="dv", parm_cd="00060", stat_cd="00003", ts_id="claim")
    other_series = {**series, "dec_lat_va": "1", "ts_id": "other"}
    result = generator.refresh_native_table(
        [series, other_series], [first, second], retrieved_at=RetrievedAt(datetime(2026, 11, 1, tzinfo=UTC))
    ).value.data
    assert result.select("drain_area_va", "dec_lat_va", "ts_id").rows() == [
        ("720.00", "1", ["other"]),
        ("720.0", "2", ["claim"]),
    ]
    with pytest.raises(FatalContractError, match="passes conflict"):
        generator.refresh_native_table(
            [{**series, "dec_lat_va": "3"}],
            [first, second],
            retrieved_at=RetrievedAt(datetime(2026, 11, 1, tzinfo=UTC)),
        )
