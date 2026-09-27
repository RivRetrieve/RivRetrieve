"""Tests for strict Canada catalogue refresh and deterministic native builds."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import polars.testing as pl_testing
import pytest
import requests

from rivretrieve._internal.catalogues.native import NativeTable, RetrievedAt, read_native_table
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.ca_eccc import generate_catalogue
from rivretrieve._internal.providers.ca_eccc.origins import STATION_CATALOGUE_ORIGINS

FIXTURE_PATH = Path("tests/test_data/ca_eccc_metadata.json")
NATIVE_PATH = Path("src/rivretrieve/_internal/providers/ca_eccc/catalogue/native.parquet")
CATALOGUE_PATH = NATIVE_PATH.parent
ATTESTED_DATETIME = datetime(2026, 8, 2, 1, 9, 10, tzinfo=UTC)
ATTESTED_RETRIEVED_AT = RetrievedAt(ATTESTED_DATETIME)
NATIVE_SCHEMA = pl.Schema(
    {
        **dict(generate_catalogue.NATIVE_SOURCE_SCHEMA),
        "retrieved_at": pl.Datetime(time_unit="us", time_zone="UTC"),
    }
)


def _fixture_payload() -> dict[str, object]:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _features() -> list[dict[str, object]]:
    features = _fixture_payload()["features"]
    assert isinstance(features, list)
    assert all(isinstance(feature, dict) for feature in features)
    return features


def _page(features: list[dict[str, object]], total: int) -> dict[str, object]:
    return {
        "type": "FeatureCollection",
        "numberMatched": total,
        "numberReturned": len(features),
        "features": features,
    }


def test_invalid_station_features_are_not_silently_dropped(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rows = [
        {
            "id": "VALID",
            "STATION_NUMBER": "01AA001",
            "STATION_NAME": "Valid station",
            "LATITUDE": 46.0,
            "LONGITUDE": -70.0,
        },
        {
            "id": "NOLONLAT",
            "STATION_NUMBER": "02BB002",
            "STATION_NAME": "Missing coordinates",
            "LATITUDE": None,
            "LONGITUDE": None,
        },
        {
            "id": "DUPLICATE",
            "STATION_NUMBER": "01AA001",
            "STATION_NAME": "Duplicate station number",
            "LATITUDE": 47.0,
            "LONGITUDE": -71.0,
        },
    ]

    result = generate_catalogue._iter_station_rows(rows)

    assert result.value == [
        {
            "provider_id": ProviderId("ca_eccc"),
            "station_id": "01AA001",
            "latitude": 46.0,
            "longitude": -70.0,
            "crs": "EPSG:4326",
        }
    ]
    assert [issue.model_dump() for issue in result.issues] == [
        {
            "severity": "error",
            "code": "invalid_station_coordinates",
            "message": "ca_eccc station NOLONLAT has missing or null coordinates",
            "details": {"diagnostic_id": "NOLONLAT", "reason": "missing_or_null_coordinates"},
            "provider_id": ProviderId("ca_eccc"),
        },
        {
            "severity": "error",
            "code": "duplicate_station_id",
            "message": "ca_eccc station DUPLICATE duplicates STATION_NUMBER 01AA001",
            "details": {
                "diagnostic_id": "DUPLICATE",
                "reason": "duplicate_station_number",
                "station_id": "01AA001",
            },
            "provider_id": ProviderId("ca_eccc"),
        },
    ]
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


@pytest.mark.parametrize(
    ("row", "code", "reason"),
    [
        (
            {"id": "NOID", "STATION_NUMBER": "", "LATITUDE": 1.0, "LONGITUDE": 2.0},
            "invalid_station_id",
            "missing_or_empty_station_number",
        ),
        (
            {"id": "BADCOORD", "STATION_NUMBER": "01AA001", "LATITUDE": "north", "LONGITUDE": 2.0},
            "invalid_station_coordinates",
            "non_numeric_coordinates",
        ),
    ],
)
def test_station_inventory_names_each_invalid_row(row: dict[str, object], code: str, reason: str) -> None:
    outcome = generate_catalogue._iter_station_rows([row])

    assert outcome.value == []
    assert len(outcome.issues) == 1
    assert outcome.issues[0].code == code
    assert outcome.issues[0].details == {"diagnostic_id": row["id"], "reason": reason}


def test_station_builder_raises_once_with_complete_issue_inventory() -> None:
    rows = [
        {"id": "NOID", "STATION_NUMBER": None, "LATITUDE": 1.0, "LONGITUDE": 2.0},
        {"id": "BADCOORD", "STATION_NUMBER": "01AA001", "LATITUDE": False, "LONGITUDE": 2.0},
    ]

    with pytest.raises(FatalContractError) as exc_info:
        generate_catalogue.build_stations(rows)

    assert [issue.code for issue in exc_info.value.issues] == [
        "invalid_station_id",
        "invalid_station_coordinates",
    ]


def test_tracked_fixture_refresh_preserves_exact_native_values() -> None:
    outcome = generate_catalogue.refresh_native_table_from_fixture(FIXTURE_PATH, retrieved_at=ATTESTED_RETRIEVED_AT)

    assert outcome.issues == ()
    assert outcome.value.data.schema == NATIVE_SCHEMA
    assert outcome.value.data["id"].to_list() == ["01AA002", "05NG003", "11AF005"]
    assert outcome.value.data["DRAINAGE_AREA_EFFECT"].to_list() == [None, 1441.0, 385.8999938964844]
    committed = read_native_table(NATIVE_PATH).data.filter(pl.col("id").is_in(outcome.value.data["id"].to_list()))
    pl_testing.assert_frame_equal(outcome.value.data, committed, check_exact=True)


def test_live_refresh_pages_to_number_matched_and_accepts_terminal_short_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    features = _features()
    calls: list[tuple[int, int]] = []

    def fake_page(*, offset: int, limit: int) -> object:
        calls.append((offset, limit))
        return {0: _page(features[:2], 3), 2: _page(features[2:], 3)}[offset]

    monkeypatch.setattr(generate_catalogue, "_request_station_page", fake_page)

    outcome = generate_catalogue.refresh_native_table_from_live(
        retrieved_at=ATTESTED_RETRIEVED_AT, page_size=2, minimum_stations=0
    )

    assert calls == [(0, 2), (2, 2)]
    assert outcome.issues == ()
    assert outcome.value.data.height == 3


def test_live_refresh_returns_named_request_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_page(*, offset: int, limit: int) -> object:
        raise requests.RequestException("offline")

    monkeypatch.setattr(generate_catalogue, "_request_station_page", fail_page)
    outcome = generate_catalogue.refresh_native_table_from_live(retrieved_at=ATTESTED_RETRIEVED_AT, page_size=2)

    assert [issue.code for issue in outcome.issues] == ["refresh_request_failed"]


@pytest.mark.parametrize(
    ("pages", "expected_code"),
    [
        ({0: {"type": "not-a-feature-collection"}}, "refresh_invalid_page"),
        (
            {0: {"type": "FeatureCollection", "numberMatched": 1, "numberReturned": 2, "features": []}},
            "refresh_invalid_page",
        ),
        ({0: _page(_features()[:2], 3), 2: _page(_features()[2:], 4)}, "refresh_inconsistent_total"),
        ({0: _page(_features()[:1], 3)}, "refresh_short_page"),
        ({0: _page([], 3)}, "refresh_premature_empty_page"),
        ({0: _page(_features()[:2], 1)}, "refresh_count_overflow"),
    ],
)
def test_live_refresh_rejects_invalid_pagination(
    monkeypatch: pytest.MonkeyPatch,
    pages: dict[int, object],
    expected_code: str,
) -> None:
    def fake_page(*, offset: int, limit: int) -> object:
        return pages[offset]

    monkeypatch.setattr(generate_catalogue, "_request_station_page", fake_page)
    outcome = generate_catalogue.refresh_native_table_from_live(
        retrieved_at=ATTESTED_RETRIEVED_AT, page_size=2, minimum_stations=0
    )

    assert [issue.code for issue in outcome.issues] == [expected_code]


def test_live_refresh_rejects_duplicate_feature(monkeypatch: pytest.MonkeyPatch) -> None:
    first, second = _features()[:2]

    def fake_page(*, offset: int, limit: int) -> object:
        return {0: _page([first], 2), 1: _page([first, second], 2)}[offset]

    monkeypatch.setattr(generate_catalogue, "_request_station_page", fake_page)
    outcome = generate_catalogue.refresh_native_table_from_live(
        retrieved_at=ATTESTED_RETRIEVED_AT, page_size=1, minimum_stations=0
    )

    assert [issue.code for issue in outcome.issues] == ["refresh_duplicate_feature"]


def test_live_refresh_rejects_duplicate_page(monkeypatch: pytest.MonkeyPatch) -> None:
    page = _page(_features()[:2], 4)
    monkeypatch.setattr(generate_catalogue, "_request_station_page", lambda *, offset, limit: page)

    outcome = generate_catalogue.refresh_native_table_from_live(
        retrieved_at=ATTESTED_RETRIEVED_AT, page_size=2, minimum_stations=0
    )

    assert [issue.code for issue in outcome.issues] == ["refresh_duplicate_page"]


def test_live_refresh_rejects_missing_page(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = {0: _page(_features()[:2], 3)}
    monkeypatch.setattr(generate_catalogue, "_request_station_page", lambda *, offset, limit: pages[offset])

    outcome = generate_catalogue.refresh_native_table_from_live(
        retrieved_at=ATTESTED_RETRIEVED_AT, page_size=2, minimum_stations=0
    )

    assert [issue.code for issue in outcome.issues] == ["refresh_missing_page"]


@pytest.mark.parametrize(
    ("number_matched", "expected_code"),
    [(4, "refresh_count_underflow"), (2, "refresh_count_overflow")],
)
def test_complete_fixture_rejects_count_underflow_or_overflow(number_matched: int, expected_code: str) -> None:
    payload = _page(_features(), number_matched)

    outcome = generate_catalogue.refresh_native_table(payload, retrieved_at=ATTESTED_RETRIEVED_AT)

    assert [issue.code for issue in outcome.issues] == [expected_code]


@pytest.mark.parametrize(
    ("feature", "reason"),
    [
        (None, "invalid_feature"),
        (
            deepcopy(_features()[0]),
            "missing_source_fields",
        ),
        (deepcopy(_features()[0]), "invalid_geometry"),
        (deepcopy(_features()[0]), "invalid_source_types"),
    ],
)
def test_refresh_returns_named_issue_for_each_invalid_feature_reason(feature: object, reason: str) -> None:
    if reason == "missing_source_fields":
        assert isinstance(feature, dict)
        properties = feature["properties"]
        assert isinstance(properties, dict)
        del properties["VERTICAL_DATUM"]
    elif reason == "invalid_geometry":
        assert isinstance(feature, dict)
        geometry = feature["geometry"]
        assert isinstance(geometry, dict)
        geometry["coordinates"] = [-70.0]
    elif reason == "invalid_source_types":
        assert isinstance(feature, dict)
        properties = feature["properties"]
        assert isinstance(properties, dict)
        properties["REAL_TIME"] = "not-an-integer"

    outcome = generate_catalogue.refresh_native_table(
        _page([feature], 1),
        retrieved_at=ATTESTED_RETRIEVED_AT,
    )

    assert len(outcome.issues) == 1
    assert outcome.issues[0].code == "refresh_invalid_page"
    assert outcome.issues[0].details["reason"] == reason


def test_live_refresh_applies_provider_calibrated_minimum(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        generate_catalogue,
        "_request_station_page",
        lambda *, offset, limit: _page(_features(), 3),
    )

    outcome = generate_catalogue.refresh_native_table_from_live(retrieved_at=ATTESTED_RETRIEVED_AT, page_size=1000)

    assert [issue.code for issue in outcome.issues] == ["refresh_below_minimum"]
    assert outcome.issues[0].details == {"actual": 3, "minimum": 8055}


def test_cli_refresh_boundary_raises_on_returned_error_issue(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        generate_catalogue,
        "_request_station_page",
        lambda *, offset, limit: _page([], 1),
    )

    with pytest.raises(FatalContractError) as exc_info:
        generate_catalogue.main(
            ["--live", "--native-out", str(tmp_path / "native.parquet"), "--retrieved-at", "2026-08-02T01:09:10Z"]
        )

    assert [issue.code for issue in exc_info.value.issues] == ["refresh_premature_empty_page"]


def test_cli_refresh_reports_digest_of_written_native_table(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    output_path = tmp_path / "native.parquet"

    result = generate_catalogue.main(
        [
            "--fixture",
            str(FIXTURE_PATH),
            "--native-out",
            str(output_path),
            "--retrieved-at",
            "2026-08-02T01:09:10Z",
        ]
    )

    digest = generate_catalogue.native_table_content_digest(read_native_table(output_path))
    assert result == 0
    assert capsys.readouterr().out == f"ca_eccc native table content SHA-256: {digest}\n"


def test_committed_native_table_has_exact_schema_population_and_id_digest() -> None:
    native = read_native_table(NATIVE_PATH).data
    encoded_ids = json.dumps(native["id"].to_list(), separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    assert native.schema == NATIVE_SCHEMA
    assert native.height == 8057
    assert native["id"].to_list() == sorted(native["id"].to_list())
    assert native["retrieved_at"].n_unique() == 1
    assert native["retrieved_at"].item(0) == ATTESTED_DATETIME
    assert hashlib.sha256(encoded_ids).hexdigest() == "a55f028a344441cfb7e0d3dbad88366ec3834ff7a62135a6f5ab9faf5b0e1393"
    assert native["DRAINAGE_AREA_GROSS"].null_count() == 344
    assert native["DRAINAGE_AREA_EFFECT"].null_count() == 6396
    assert native["DRAINAGE_AREA_EFFECT"].len() - native["DRAINAGE_AREA_EFFECT"].null_count() == 1661
    assert native["id"].equals(native["IDENTIFIER"])
    assert native["id"].equals(native["STATION_NUMBER"])


def test_committed_native_table_has_attested_whole_table_content_digest() -> None:
    native = read_native_table(NATIVE_PATH)

    assert generate_catalogue.native_table_content_digest(native) == (
        "46780a69f07e9ed8a7eae343929d81b4c78f2330d6268ee1fdc7de701cd6fe48"
    )


def test_committed_native_coordinates_are_inside_declared_collection_bbox() -> None:
    native = read_native_table(NATIVE_PATH).data

    assert native["geometry.coordinates[0]"].is_between(-142, -52).fill_null(False).all()
    assert native["geometry.coordinates[1]"].is_between(42, 84).fill_null(False).all()


@pytest.mark.parametrize(
    ("station_id", "name", "longitude", "latitude", "effective_area"),
    [
        ("01AA002", "DAAQUAM (RIVIERE) EN AVAL DE LA RIVIERE SHIDGEL", -70.08110809326172, 46.557498931884766, None),
        ("05NG003", "PIPESTONE CREEK NEAR PIPESTONE", -100.96286010742188, 49.59603118896485, 1441.0),
        ("11AF005", "BEAVER CREEK AT INTERNATIONAL BOUNDARY", -105.03500366210938, 49.0, 385.8999938964844),
    ],
)
def test_committed_native_table_pins_representative_rows(
    station_id: str, name: str, longitude: float, latitude: float, effective_area: float | None
) -> None:
    row = read_native_table(NATIVE_PATH).data.filter(pl.col("id") == station_id).row(0, named=True)

    assert row["STATION_NAME"] == name
    assert row["geometry.coordinates[0]"] == longitude
    assert row["geometry.coordinates[1]"] == latitude
    assert row["DRAINAGE_AREA_EFFECT"] == effective_area


def test_committed_native_first_middle_and_last_ids_are_pinned() -> None:
    ids = read_native_table(NATIVE_PATH).data["id"]
    assert ids.item(0) == "01AA002"
    assert ids.item(len(ids) // 2) == "05NG003"
    assert ids.item(-1) == "11AF005"


def test_native_build_counts_crs_and_dates() -> None:
    catalogue = generate_catalogue.build_catalogue(read_native_table(NATIVE_PATH), STATION_CATALOGUE_ORIGINS)

    assert catalogue.stations.height == 8057
    assert catalogue.products.height == 2
    assert catalogue.station_products.height == 16114
    assert set(catalogue.stations["crs"]) == {"EPSG:4326"}
    assert catalogue.provider_info["catalogue_version"] == "2026-08-02"
    assert set(catalogue.station_products["last_catalogue_check"]) == {date(2026, 8, 2)}
    assert set(catalogue.products["native_id"]) == {"DLY_FLOWS", "DLY_LEVELS"}


def test_build_catalogue_is_gated_on_origins() -> None:
    broken = dict(STATION_CATALOGUE_ORIGINS)
    del broken["longitude"]

    with pytest.raises(FatalContractError, match=r"ca_eccc\.longitude"):
        generate_catalogue.build_catalogue(read_native_table(NATIVE_PATH), broken)


def test_mixed_retrieval_dates_flow_to_rows_and_provider_version() -> None:
    source = read_native_table(NATIVE_PATH).data.head(2)
    first_id = source["STATION_NUMBER"].item(0)
    mixed = source.with_columns(
        pl.when(pl.col("STATION_NUMBER") == first_id)
        .then(datetime(2026, 7, 31, 12, tzinfo=UTC))
        .otherwise(datetime(2026, 8, 2, 12, tzinfo=UTC))
        .cast(pl.Datetime(time_unit="us", time_zone="UTC"))
        .alias("retrieved_at")
    )

    catalogue = generate_catalogue.build_catalogue(NativeTable(mixed), STATION_CATALOGUE_ORIGINS)

    assert set(catalogue.station_products.filter(pl.col("station_id") == first_id)["last_catalogue_check"]) == {
        date(2026, 7, 31)
    }
    assert catalogue.provider_info["catalogue_version"] == "2026-08-02"


@pytest.mark.parametrize(
    "argv",
    [
        ["--fixture", str(FIXTURE_PATH), "--native-out", "native.parquet"],
        ["--fixture", str(FIXTURE_PATH), "--out", "catalogue"],
        ["--live", "--out", "catalogue"],
        ["--native", str(NATIVE_PATH), "--native-out", "native.parquet", "--retrieved-at", "2026-08-02T01:09:10Z"],
        ["--native", str(NATIVE_PATH), "--out", "catalogue", "--retrieved-at", "2026-08-02T01:09:10Z"],
    ],
)
def test_cli_rejects_cross_mode_combinations(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        generate_catalogue.main(argv)
    assert exc_info.value.code != 0


def test_native_build_is_network_free_and_byte_deterministic(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[str] = []

    def fail_network(*args: object, **kwargs: object) -> object:
        calls.append("network")
        raise AssertionError("network must not be accessed during build")

    monkeypatch.setattr(generate_catalogue, "_request_station_page", fail_network)
    monkeypatch.setattr(generate_catalogue.requests, "get", fail_network)
    before_native = NATIVE_PATH.read_bytes()

    result = generate_catalogue.main(["--native", str(NATIVE_PATH), "--out", str(tmp_path)])

    assert result == 0
    assert calls == []
    assert NATIVE_PATH.read_bytes() == before_native
    assert {path.name for path in tmp_path.iterdir()} == {
        "croissant.json",
        "provider.json",
        "products.parquet",
        "stations.parquet",
        "station_products.parquet",
        "provenance.json",
        "provenance_facts.parquet",
        "provenance_acquisitions.parquet",
        "provenance_bindings.parquet",
        "provenance_binding_facts.parquet",
        "provenance_external_inputs.parquet",
        "format.json",
        "source_series.json",
        "series_claims.parquet",
    }
    for artifact_name in (
        "provider.json",
        "products.parquet",
        "stations.parquet",
        "station_products.parquet",
        "provenance.json",
        "provenance_facts.parquet",
        "provenance_acquisitions.parquet",
        "provenance_bindings.parquet",
        "provenance_binding_facts.parquet",
        "provenance_external_inputs.parquet",
        "format.json",
        "source_series.json",
        "series_claims.parquet",
    ):
        assert (tmp_path / artifact_name).read_bytes() == (CATALOGUE_PATH / artifact_name).read_bytes()
