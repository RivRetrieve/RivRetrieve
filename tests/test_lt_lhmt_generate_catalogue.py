from __future__ import annotations

import hashlib
import io
import json
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import polars.testing as pl_testing
import pytest

from rivretrieve._internal.catalogues.native import RetrievedAt, read_native_table
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.lt_lhmt import generate_catalogue

FIXTURE_PATH = Path("tests/test_data/lithuania_metadata_stations.json")
CATALOGUE_DATE = date(2026, 5, 31)
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


def _fixture_payload() -> list[dict[str, object]]:
    value = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, list)
    assert all(isinstance(item, dict) for item in value)
    return value


def _expected_native_frame(payload: list[dict[str, object]] | None = None) -> pl.DataFrame:
    rows = _fixture_payload() if payload is None else payload
    return (
        pl.DataFrame(rows, infer_schema_length=None)
        .sort("code")
        .with_columns(
            pl.lit(ATTESTED_DATETIME).cast(pl.Datetime(time_unit="us", time_zone="UTC")).alias("retrieved_at")
        )
    )


class _FixtureResponse(io.BytesIO):
    status = 200


def _fake_urlopen_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, int]]:
    fixture_bytes = FIXTURE_PATH.read_bytes()
    calls: list[tuple[str, int]] = []

    def fake_urlopen(url: str, *, timeout: int) -> _FixtureResponse:
        calls.append((url, timeout))
        return _FixtureResponse(fixture_bytes)

    monkeypatch.setattr(generate_catalogue.urllib.request, "urlopen", fake_urlopen)
    return calls


def test_lt_lhmt_generator_uses_committed_fixture_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_live_json(url: str) -> object:
        raise AssertionError(f"unexpected live request to {url}")

    monkeypatch.setattr(generate_catalogue, "_read_live_json", fail_live_json)

    catalogue = generate_catalogue.generate_catalogue_from_fixture(
        FIXTURE_PATH,
        catalogue_date=CATALOGUE_DATE,
    )

    assert catalogue.stations.height == 97


def test_lt_lhmt_generator_station_count_matches_fixture() -> None:
    catalogue = generate_catalogue.generate_catalogue_from_fixture(
        FIXTURE_PATH,
        catalogue_date=CATALOGUE_DATE,
    )
    assert catalogue.stations.height == 97


def test_lt_lhmt_generator_products_are_two() -> None:
    catalogue = generate_catalogue.generate_catalogue_from_fixture(
        FIXTURE_PATH,
        catalogue_date=CATALOGUE_DATE,
    )
    assert catalogue.products.height == 2
    product_ids = set(catalogue.products["product_id"].to_list())
    assert product_ids == {"discharge_daily_mean", "stage_daily_mean"}


def test_lt_lhmt_generator_station_products_count() -> None:
    catalogue = generate_catalogue.generate_catalogue_from_fixture(
        FIXTURE_PATH,
        catalogue_date=CATALOGUE_DATE,
    )
    assert catalogue.station_products.height == 97 * 2


def test_lt_lhmt_generator_station_products_availability_unknown() -> None:
    catalogue = generate_catalogue.generate_catalogue_from_fixture(
        FIXTURE_PATH,
        catalogue_date=CATALOGUE_DATE,
    )
    availability_values = set(catalogue.station_products["availability"].cast(str).to_list())
    assert availability_values == {"unknown"}


def test_lt_lhmt_generator_first_station_sorted() -> None:
    catalogue = generate_catalogue.generate_catalogue_from_fixture(
        FIXTURE_PATH,
        catalogue_date=CATALOGUE_DATE,
    )
    station_ids = catalogue.stations["station_id"].to_list()
    assert station_ids == sorted(station_ids)


def test_lt_lhmt_generator_station_has_required_common_fields() -> None:
    catalogue = generate_catalogue.generate_catalogue_from_fixture(
        FIXTURE_PATH,
        catalogue_date=CATALOGUE_DATE,
    )
    assert catalogue.stations.columns == ["provider_id", "station_id", "latitude", "longitude", "crs"]
    assert catalogue.stations["crs"].unique().to_list() == ["unknown"]


def test_lt_lhmt_generator_provider_info_fields() -> None:
    catalogue = generate_catalogue.generate_catalogue_from_fixture(
        FIXTURE_PATH,
        catalogue_date=CATALOGUE_DATE,
    )
    info = catalogue.provider_info
    assert info["provider_id"] == "lt_lhmt"
    assert info["catalogue_version"] == "2026-05-31"
    assert info["live_stations"] is False
    assert info["live_products"] is False
    assert info["live_station_products"] is False


def test_lt_lhmt_fixture_matches_attested_digest() -> None:
    payload = _fixture_payload()
    canonical = json.dumps(
        sorted(payload, key=lambda station: station["code"]),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()

    assert len(payload) == 97
    assert hashlib.sha256(canonical).hexdigest() == ATTESTED_DIGEST


def test_refresh_native_table_from_fixture_preserves_exact_source_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_live_json(url: str) -> object:
        raise AssertionError(f"unexpected live request to {url}")

    monkeypatch.setattr(generate_catalogue, "_read_live_json", fail_live_json)

    outcome = generate_catalogue.refresh_native_table_from_fixture(
        FIXTURE_PATH,
        retrieved_at=ATTESTED_RETRIEVED_AT,
    )

    assert outcome.issues == ()
    assert outcome.value.data.schema == NATIVE_SCHEMA
    pl_testing.assert_frame_equal(outcome.value.data, _expected_native_frame())


def test_refresh_native_table_from_live_exercises_transport_seam_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _fake_urlopen_calls(monkeypatch)

    outcome = generate_catalogue.refresh_native_table_from_live(retrieved_at=ATTESTED_RETRIEVED_AT)

    assert calls == [("https://api.meteo.lt/v1/hydro-stations", 30)]
    assert outcome.value.data.height == 97
    assert outcome.issues == ()


def test_native_live_cli_branch_writes_expected_table_offline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls = _fake_urlopen_calls(monkeypatch)
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
    pl_testing.assert_frame_equal(read_native_table(output_path).data, _expected_native_frame())


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


def test_absent_station_is_not_carried_forward(tmp_path: Path) -> None:
    reduced_payload = _fixture_payload()[:-1]
    reduced_fixture = tmp_path / "reduced.json"
    reduced_fixture.write_text(json.dumps(reduced_payload), encoding="utf-8")

    outcome = generate_catalogue.refresh_native_table_from_fixture(
        reduced_fixture,
        retrieved_at=ATTESTED_RETRIEVED_AT,
    )

    assert outcome.value.data.height == len(reduced_payload)
    assert set(outcome.value.data["code"].to_list()) == {station["code"] for station in reduced_payload}


def test_committed_native_table_matches_attested_fixture() -> None:
    path = Path("src/rivretrieve/_internal/providers/lt_lhmt/catalogue/native.parquet")
    table = read_native_table(path)

    pl_testing.assert_frame_equal(table.data, _expected_native_frame())
    assert table.data.height == 97
    assert table.data["retrieved_at"].n_unique() == 1
    assert table.data["retrieved_at"].item(0) == ATTESTED_DATETIME


def test_canonical_cli_still_writes_only_four_canonical_artifacts(tmp_path: Path) -> None:
    result = generate_catalogue.main(
        [
            "--fixture",
            str(FIXTURE_PATH),
            "--out",
            str(tmp_path),
            "--catalogue-date",
            "2026-05-31",
        ]
    )

    assert result == 0
    assert {path.name for path in tmp_path.iterdir()} == {
        "provider.json",
        "products.parquet",
        "stations.parquet",
        "station_products.parquet",
    }
    assert pl.read_parquet(tmp_path / "stations.parquet").height == 97
    assert pl.read_parquet(tmp_path / "products.parquet").height == 2
    assert pl.read_parquet(tmp_path / "station_products.parquet").height == 194


@pytest.mark.parametrize(
    "argv",
    [
        ["--fixture", str(FIXTURE_PATH), "--native-out", "native.parquet"],
        [
            "--fixture",
            str(FIXTURE_PATH),
            "--out",
            "catalogue",
            "--retrieved-at",
            "2026-08-01T18:31:08Z",
        ],
    ],
)
def test_retrieved_at_is_required_only_for_native_mode(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        generate_catalogue.main(argv)

    assert exc_info.value.code != 0
