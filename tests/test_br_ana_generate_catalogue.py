"""ANA canonical scope and retired catalogue entry-point contracts."""

from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from rivretrieve._internal.catalogues.native import NativeTable
from rivretrieve._internal.catalogues.schemas import STATION_CATALOG_SCHEMA
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.br_ana.generate_catalogue import (
    build_stations,
    main,
    project_stations,
)


def inventory() -> NativeTable:
    """Authored station carriers test projection, not source observation semantics."""
    return NativeTable(
        pl.DataFrame(
            {
                "codigoestacao": ["002", "001", "003"],
                "Tipo_Estacao": ["Fluviometrica", "Pluviometrica", "Fluviometrica"],
                "Latitude": ["-10.50", "-11", None],
                "Longitude": ["-60.25", "-61", None],
                "Tipo_Estacao_Desc_Liquida": ["Nao", "Sim", "Nao"],
                "retrieved_at": [datetime(2026, 9, 16, tzinfo=UTC)] * 3,
            }
        )
    )


@pytest.mark.parametrize("mode", [["--fixture", "absent.json"], ["--live"], ["--withhold-uncertified"]])
def test_removed_cli_is_unrecognized_and_preserves_files(mode: list[str], tmp_path: Path, capsys) -> None:
    output = tmp_path / "existing"
    output.mkdir()
    marker = output / "unrelated.bin"
    marker.write_bytes(b"preserve existing material")
    with pytest.raises(SystemExit) as caught:
        main(["--native", "absent.parquet", "--evidence-root", str(tmp_path), *mode, "--out", str(output)])
    assert caught.value.code == 2
    assert "unrecognized arguments:" in capsys.readouterr().err
    assert marker.read_bytes() == b"preserve existing material"
    assert list(output.iterdir()) == [marker]


def test_projection_is_exact_partition_and_preserves_native_strings() -> None:
    native = inventory()
    before = native.data.clone()
    selected = project_stations(native)
    expected = native.data.filter(pl.col("codigoestacao").is_in(["002", "003"]))
    assert_frame_equal(selected.data, expected)
    assert_frame_equal(native.data, before)
    assert (
        selected.data.height + native.data.filter(pl.col("Tipo_Estacao") == "Pluviometrica").height
        == native.data.height
    )


def test_stations_use_type_not_flags_and_keep_unknown_coordinates() -> None:
    expected = pl.DataFrame(
        [
            {"provider_id": "br_ana", "station_id": "002", "latitude": -10.5, "longitude": -60.25, "crs": "unknown"},
            {"provider_id": "br_ana", "station_id": "003", "latitude": None, "longitude": None, "crs": "unknown"},
        ],
        schema=STATION_CATALOG_SCHEMA.polars_schema,
    )
    assert_frame_equal(build_stations(inventory()), expected)


@pytest.mark.parametrize("kind", [None, "fluviometrica", "", "Other"])
def test_unexpected_station_type_fails_loudly(kind: str | None) -> None:
    native = NativeTable(inventory().data.with_columns(pl.lit(kind, dtype=pl.String).alias("Tipo_Estacao")))
    with pytest.raises(FatalContractError, match="Tipo_Estacao"):
        build_stations(native)


def test_missing_station_type_fails_loudly() -> None:
    native = NativeTable(inventory().data.drop("Tipo_Estacao"))
    with pytest.raises(FatalContractError, match="Tipo_Estacao"):
        build_stations(native)


def test_bad_coordinate_is_not_silently_discarded() -> None:
    native = NativeTable(inventory().data.with_columns(pl.lit("not-a-number").alias("Latitude")))
    with pytest.raises(FatalContractError, match="coordinates"):
        build_stations(native)


@pytest.mark.derived(
    "src/rivretrieve/_internal/providers/br_ana/catalogue/native.parquet",
    "tests/test_data/br_ana_inventory/capture.json",
)
def test_attested_inventory_build_has_only_evidenced_station_facts(retained_evidence_root, tmp_path: Path) -> None:
    from rivretrieve._internal.catalogues.native import read_native_table
    from rivretrieve._internal.providers.br_ana.capture import read_capture_record, verify_native_identity
    from rivretrieve._internal.providers.br_ana.generate_catalogue import build_catalogue, write_catalogue
    from rivretrieve._internal.providers.br_ana.origins import STATION_CATALOGUE_ORIGINS, build_acquisition_provenance

    repository = retained_evidence_root
    capture = read_capture_record(repository / "tests/test_data/br_ana_inventory/capture.json")
    native_path = repository / capture.native_table.repository_path
    native = read_native_table(native_path)
    verify_native_identity(capture, native_path.read_bytes(), native)
    provenance = build_acquisition_provenance(capture)
    catalogue = build_catalogue(native, STATION_CATALOGUE_ORIGINS, provenance)
    expected_ids = (
        native.data.filter(pl.col("Tipo_Estacao") == "Fluviometrica")
        .select(pl.col("codigoestacao").alias("station_id"))
        .sort("station_id")
    )
    assert_frame_equal(catalogue.stations.select("station_id"), expected_ids)
    assert_frame_equal(catalogue.public_artifact.stations, catalogue.stations)
    assert catalogue.acquired_station_count == capture.distinct_station_count
    assert catalogue.pluviometric_station_count == capture.pluviometric_station_count
    assert catalogue.stations.height == capture.fluviometric_station_count
    assert catalogue.products.is_empty()
    assert catalogue.station_products.is_empty()
    assert catalogue.provider_info["citation"] is None
    latest = native.data["retrieved_at"].max()
    assert isinstance(latest, datetime)
    assert catalogue.provider_info["catalogue_version"] == latest.date().isoformat()
    assert str(catalogue.provider_info["bulk_observations"]).startswith("false:")
    terms = next(record for record in provenance.source_records if record.source_id == "br_ana.terms")
    assert catalogue.provider_info["license"] == terms.statements[0].exact_text
    write_catalogue(catalogue, tmp_path)
    assert_frame_equal(pl.read_parquet(tmp_path / "stations.parquet"), catalogue.stations)
    assert pl.read_parquet(tmp_path / "products.parquet").is_empty()
    assert pl.read_parquet(tmp_path / "station_products.parquet").is_empty()
    assert (tmp_path / "croissant.json").is_file()


def test_catalogue_date_cannot_override_attested_acquisition(tmp_path: Path) -> None:
    # The attested native retrieval instant owns catalogue_version. An obsolete
    # caller date must not be silently accepted or cause input-file I/O.
    with pytest.raises(SystemExit) as caught:
        main(
            [
                "--native",
                "absent.parquet",
                "--out",
                str(tmp_path),
                "--evidence-root",
                str(tmp_path),
                "--catalogue-date",
                "2000-01-01",
            ]
        )
    assert caught.value.code == 2
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("source", [["--native", "absent.parquet"], ["--materialize-record", "absent.json"]])
def test_cli_requires_explicit_evidence_root(source, tmp_path):
    with pytest.raises(SystemExit) as caught:
        main([*source, "--out", str(tmp_path / "catalogue")])
    assert caught.value.code == 2
    assert list(tmp_path.iterdir()) == []
