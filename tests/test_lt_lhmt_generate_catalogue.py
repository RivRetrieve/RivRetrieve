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
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.lt_lhmt import generate_catalogue
from rivretrieve._internal.providers.lt_lhmt.origins import STATION_CATALOGUE_ORIGINS
from tests._catalogue import catalogue_recording_paths

FIXTURE_PATH = Path("tests/test_data/lithuania_metadata_stations.json")
NATIVE_PATH = Path("src/rivretrieve/_internal/providers/lt_lhmt/catalogue/native.parquet")
CATALOGUE_PATH = NATIVE_PATH.parent
ATTESTED_DATETIME = datetime(2026, 8, 1, 18, 31, 8, tzinfo=UTC)
ATTESTED_RETRIEVED_AT = RetrievedAt(ATTESTED_DATETIME)
ATTESTED_DIGEST = "02d16a6e872939b43ee7ae6d1c54e00b6b924f3d9a3f9a7553fc13680edc12d8"
NATIVE_SCHEMA = pl.Schema(
    {
        "code": pl.String,
        "name": pl.String,
        "waterBody": pl.String,
        "coordinates": pl.Struct(
            {
                "latitude": pl.Float64,
                "longitude": pl.Float64,
            }
        ),
        "retrieved_at": pl.Datetime(time_unit="us", time_zone="UTC"),
    }
)


def _fixture_payload(retained_evidence_root) -> list[dict[str, object]]:
    value = json.loads((retained_evidence_root / FIXTURE_PATH).read_text(encoding="utf-8"))
    assert isinstance(value, list)
    assert all(isinstance(item, dict) for item in value)
    return value


def _expected_native_frame(retained_evidence_root, payload: list[dict[str, object]] | None = None) -> pl.DataFrame:
    rows = _fixture_payload(retained_evidence_root) if payload is None else payload
    return (
        pl.DataFrame(rows, infer_schema_length=None)
        .sort("code")
        .with_columns(
            pl.lit(ATTESTED_DATETIME).cast(pl.Datetime(time_unit="us", time_zone="UTC")).alias("retrieved_at")
        )
    )


def _build_committed_catalogue(retained_evidence_root) -> generate_catalogue.GeneratedLtLhmtCatalogue:
    return generate_catalogue.build_catalogue(
        read_native_table(retained_evidence_root / NATIVE_PATH), STATION_CATALOGUE_ORIGINS
    )


class _FixtureResponse(io.BytesIO):
    status = 200


def _fake_urlopen_calls(
    retained_evidence_root,
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, int]]:
    fixture_bytes = (retained_evidence_root / FIXTURE_PATH).read_bytes()
    calls: list[tuple[str, int]] = []

    def fake_urlopen(url: str, *, timeout: int) -> _FixtureResponse:
        calls.append((url, timeout))
        return _FixtureResponse(fixture_bytes)

    monkeypatch.setattr(generate_catalogue.urllib.request, "urlopen", fake_urlopen)
    return calls


@pytest.mark.derived("src/rivretrieve/_internal/providers/lt_lhmt/catalogue/native.parquet")
def test_lt_lhmt_generator_uses_committed_native_table_without_network(
    retained_evidence_root,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_live_json(url: str) -> object:
        raise AssertionError(f"unexpected live request to {url}")

    monkeypatch.setattr(generate_catalogue, "_read_live_json", fail_live_json)

    catalogue = _build_committed_catalogue(retained_evidence_root)

    assert catalogue.stations.height == 97


@pytest.mark.derived("src/rivretrieve/_internal/providers/lt_lhmt/catalogue/native.parquet")
def test_lt_lhmt_generator_station_count_matches_fixture(retained_evidence_root) -> None:
    catalogue = _build_committed_catalogue(retained_evidence_root)
    assert catalogue.stations.height == 97


@pytest.mark.derived("src/rivretrieve/_internal/providers/lt_lhmt/catalogue/native.parquet")
def test_lt_lhmt_generator_products_are_two(retained_evidence_root) -> None:
    catalogue = _build_committed_catalogue(retained_evidence_root)
    assert catalogue.products.height == 2
    product_ids = set(catalogue.products["product_id"].to_list())
    assert product_ids == {"discharge_daily_mean", "stage_daily_mean"}


@pytest.mark.derived("src/rivretrieve/_internal/providers/lt_lhmt/catalogue/native.parquet")
def test_lt_lhmt_generator_station_products_count(retained_evidence_root) -> None:
    catalogue = _build_committed_catalogue(retained_evidence_root)
    assert catalogue.station_products.height == 97 * 2


@pytest.mark.derived("src/rivretrieve/_internal/providers/lt_lhmt/catalogue/native.parquet")
def test_lt_lhmt_generator_station_products_availability_unknown(retained_evidence_root) -> None:
    catalogue = _build_committed_catalogue(retained_evidence_root)
    availability_values = set(catalogue.station_products["availability"].cast(str).to_list())
    assert availability_values == {"unknown"}


@pytest.mark.derived("src/rivretrieve/_internal/providers/lt_lhmt/catalogue/native.parquet")
def test_lt_lhmt_generator_first_station_sorted(retained_evidence_root) -> None:
    catalogue = _build_committed_catalogue(retained_evidence_root)
    station_ids = catalogue.stations["station_id"].to_list()
    assert station_ids == sorted(station_ids)


@pytest.mark.derived("src/rivretrieve/_internal/providers/lt_lhmt/catalogue/native.parquet")
def test_lt_lhmt_generator_station_has_required_common_fields(retained_evidence_root) -> None:
    catalogue = _build_committed_catalogue(retained_evidence_root)
    assert catalogue.stations.columns == ["provider_id", "station_id", "latitude", "longitude", "crs"]
    assert catalogue.stations["crs"].unique().to_list() == ["EPSG:4326"]


@pytest.mark.derived("src/rivretrieve/_internal/providers/lt_lhmt/catalogue/native.parquet")
def test_build_catalogue_is_gated_on_origins(retained_evidence_root) -> None:
    broken = dict(STATION_CATALOGUE_ORIGINS)
    del broken["longitude"]

    with pytest.raises(
        FatalContractError,
        match=r"lt_lhmt\.longitude: canonical column has no origin declaration",
    ):
        generate_catalogue.build_catalogue(read_native_table(retained_evidence_root / NATIVE_PATH), broken)


@pytest.mark.derived("src/rivretrieve/_internal/providers/lt_lhmt/catalogue/native.parquet")
def test_lt_lhmt_generator_provider_info_fields(retained_evidence_root) -> None:
    catalogue = _build_committed_catalogue(retained_evidence_root)
    info = catalogue.provider_info
    assert info["provider_id"] == "lt_lhmt"
    assert info["catalogue_version"] == "2026-08-01"
    assert catalogue.station_products["last_catalogue_check"].unique().to_list() == [date(2026, 8, 1)]
    assert info["live_stations"] is False
    assert info["live_products"] is False
    assert info["live_station_products"] is False


@pytest.mark.recorded("tests/test_data/lithuania_metadata_stations.json")
def test_lt_lhmt_fixture_matches_attested_digest(retained_evidence_root) -> None:
    payload = _fixture_payload(retained_evidence_root)
    canonical = json.dumps(
        sorted(payload, key=lambda station: station["code"]),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()

    assert len(payload) == 97
    assert hashlib.sha256(canonical).hexdigest() == ATTESTED_DIGEST


@pytest.mark.recorded("tests/test_data/lithuania_metadata_stations.json")
def test_refresh_native_table_from_fixture_preserves_exact_source_data(
    retained_evidence_root,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_live_json(url: str) -> object:
        raise AssertionError(f"unexpected live request to {url}")

    monkeypatch.setattr(generate_catalogue, "_read_live_json", fail_live_json)

    outcome = generate_catalogue.refresh_native_table_from_fixture(
        retained_evidence_root / FIXTURE_PATH,
        retrieved_at=ATTESTED_RETRIEVED_AT,
    )

    assert outcome.issues == ()
    assert outcome.value.data.schema == NATIVE_SCHEMA
    pl_testing.assert_frame_equal(
        outcome.value.data,
        _expected_native_frame(retained_evidence_root),
    )


@pytest.mark.recorded("tests/test_data/lithuania_metadata_stations.json")
def test_refresh_native_table_from_live_exercises_transport_seam_offline(
    retained_evidence_root,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _fake_urlopen_calls(retained_evidence_root, monkeypatch)

    outcome = generate_catalogue.refresh_native_table_from_live(retrieved_at=ATTESTED_RETRIEVED_AT)

    assert calls == [("https://api.meteo.lt/v1/hydro-stations", 30)]
    assert outcome.value.data.height == 97
    assert outcome.issues == ()


@pytest.mark.recorded("tests/test_data/lithuania_metadata_stations.json")
def test_native_live_cli_branch_writes_expected_table_offline(
    retained_evidence_root,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls = _fake_urlopen_calls(retained_evidence_root, monkeypatch)
    output_path = tmp_path / "native.parquet"

    result = generate_catalogue.main(
        [
            "--live",
            "--native-out",
            str(output_path),
            "--retrieved-at",
            "2026-08-01T18:31:08Z",
        ]
    )

    assert result == 0
    assert calls == [("https://api.meteo.lt/v1/hydro-stations", 30)]
    pl_testing.assert_frame_equal(
        read_native_table(output_path).data,
        _expected_native_frame(retained_evidence_root),
    )


def test_live_refresh_transport_failure_is_fatal_and_silent(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_urlopen(url: str, *, timeout: int) -> object:
        raise OSError("bulk request failed")

    monkeypatch.setattr(generate_catalogue.urllib.request, "urlopen", fail_urlopen)

    with pytest.raises(FatalContractError, match="Lithuania metadata live request failed"):
        generate_catalogue.refresh_native_table_from_live(retrieved_at=ATTESTED_RETRIEVED_AT)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


@pytest.mark.recorded("tests/test_data/lithuania_metadata_stations.json")
def test_absent_station_is_not_carried_forward(retained_evidence_root, tmp_path: Path) -> None:
    reduced_payload = _fixture_payload(retained_evidence_root)[:-1]
    reduced_fixture = tmp_path / "reduced.json"
    reduced_fixture.write_text(json.dumps(reduced_payload), encoding="utf-8")

    outcome = generate_catalogue.refresh_native_table_from_fixture(
        reduced_fixture,
        retrieved_at=ATTESTED_RETRIEVED_AT,
    )

    assert outcome.value.data.height == len(reduced_payload)
    assert set(outcome.value.data["code"].to_list()) == {station["code"] for station in reduced_payload}


@pytest.mark.recorded(
    "src/rivretrieve/_internal/providers/lt_lhmt/catalogue/native.parquet",
    "tests/test_data/lithuania_metadata_stations.json",
)
def test_committed_native_table_matches_attested_fixture(retained_evidence_root) -> None:
    table = read_native_table(retained_evidence_root / NATIVE_PATH)

    pl_testing.assert_frame_equal(
        table.data,
        _expected_native_frame(retained_evidence_root),
    )
    pl_testing.assert_frame_equal(
        table.data.select("name", "waterBody", "coordinates"),
        _expected_native_frame(retained_evidence_root).select("name", "waterBody", "coordinates"),
    )
    assert table.data.height == 97
    assert table.data["retrieved_at"].n_unique() == 1
    assert table.data["retrieved_at"].item(0) == ATTESTED_DATETIME


@pytest.mark.derived("src/rivretrieve/_internal/providers/lt_lhmt/catalogue/native.parquet")
def test_mixed_retrieval_dates_flow_to_station_products_and_provider_version(retained_evidence_root) -> None:
    source = read_native_table(retained_evidence_root / NATIVE_PATH).data.head(2)
    station_ids = source["code"].to_list()
    mixed = source.with_columns(
        pl.when(pl.col("code") == station_ids[0])
        .then(datetime(2026, 7, 31, 12, tzinfo=UTC))
        .otherwise(datetime(2026, 8, 2, 12, tzinfo=UTC))
        .cast(pl.Datetime(time_unit="us", time_zone="UTC"))
        .alias("retrieved_at")
    )

    catalogue = generate_catalogue.build_catalogue(NativeTable(mixed), STATION_CATALOGUE_ORIGINS)

    first_dates = set(catalogue.station_products.filter(pl.col("station_id") == station_ids[0])["last_catalogue_check"])
    second_dates = set(
        catalogue.station_products.filter(pl.col("station_id") == station_ids[1])["last_catalogue_check"]
    )
    assert first_dates == {date(2026, 7, 31)}
    assert second_dates == {date(2026, 8, 2)}
    assert catalogue.provider_info["catalogue_version"] == "2026-08-02"


@pytest.mark.governing(
    "src/rivretrieve/_internal/providers/lt_lhmt/catalogue/native.parquet",
    "tests/test_data/lt_lhmt_terms_licence.html",
)
@pytest.mark.recorded(*catalogue_recording_paths("lt_lhmt"))
def test_canonical_cli_writes_only_five_canonical_artifacts(
    retained_evidence_root, tmp_path: Path, catalogue_build_inputs_path
) -> None:
    from rivretrieve._internal.providers.lt_lhmt.origins import build_acquisition_provenance

    build_inputs_path = catalogue_build_inputs_path(build_acquisition_provenance())
    result = generate_catalogue.main(
        [
            "--build-inputs",
            str(build_inputs_path),
            "--native",
            str(retained_evidence_root / NATIVE_PATH),
            "--evidence-root",
            str(retained_evidence_root),
            "--out",
            str(tmp_path),
        ]
    )

    assert result == 0
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
        "station_metadata.parquet",
    }
    assert pl.read_parquet(tmp_path / "stations.parquet").height == 97
    assert pl.read_parquet(tmp_path / "products.parquet").height == 2
    stations = pl.read_parquet(tmp_path / "stations.parquet")
    station_products = pl.read_parquet(tmp_path / "station_products.parquet")
    assert station_products.height == 194
    assert set(stations["crs"]) == {"EPSG:4326"}
    assert set(station_products["last_catalogue_check"]) == {date(2026, 8, 1)}


@pytest.mark.parametrize(
    "argv",
    [
        ["--fixture", str(FIXTURE_PATH), "--native-out", "native.parquet"],
        ["--fixture", str(FIXTURE_PATH), "--out", "catalogue"],
        ["--live", "--out", "catalogue"],
        ["--native", str(NATIVE_PATH), "--native-out", "native.parquet", "--retrieved-at", "2026-08-01T18:31:08Z"],
        [
            "--native",
            str(NATIVE_PATH),
            "--out",
            "catalogue",
            "--retrieved-at",
            "2026-08-01T18:31:08Z",
        ],
    ],
)
def test_cli_rejects_cross_mode_combinations(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        generate_catalogue.main(argv)

    assert exc_info.value.code != 0


@pytest.mark.governing(
    "src/rivretrieve/_internal/providers/lt_lhmt/catalogue/native.parquet",
    "tests/test_data/lt_lhmt_terms_licence.html",
)
@pytest.mark.recorded(*catalogue_recording_paths("lt_lhmt"))
def test_native_build_is_network_free_and_byte_deterministic(
    retained_evidence_root, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, catalogue_build_inputs_path
) -> None:
    from rivretrieve._internal.providers.lt_lhmt.origins import build_acquisition_provenance

    build_inputs_path = catalogue_build_inputs_path(build_acquisition_provenance())
    calls: list[str] = []

    def fail_network(*args: object, **kwargs: object) -> object:
        calls.append("network")
        raise AssertionError("network must not be accessed during build")

    monkeypatch.setattr(generate_catalogue, "_read_live_json", fail_network)
    monkeypatch.setattr(generate_catalogue.urllib.request, "urlopen", fail_network)

    result = generate_catalogue.main(
        [
            "--build-inputs",
            str(build_inputs_path),
            "--native",
            str(retained_evidence_root / NATIVE_PATH),
            "--evidence-root",
            str(retained_evidence_root),
            "--out",
            str(tmp_path),
        ]
    )

    assert result == 0
    assert calls == []
    for artifact_name in (
        "provider.json",
        "products.parquet",
        "stations.parquet",
        "station_products.parquet",
    ):
        assert (tmp_path / artifact_name).read_bytes() == (CATALOGUE_PATH / artifact_name).read_bytes()


def test_native_build_requires_explicit_evidence_root(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc_info:
        generate_catalogue.main(["--native", str(tmp_path / "native.parquet"), "--out", str(tmp_path / "catalogue")])

    assert exc_info.value.code == 2
