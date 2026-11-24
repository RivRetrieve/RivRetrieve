"""Source-independent tests for Belgium - Wallonia (`be_wal`) Step 2 station catalogue, metadata, and origins."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import polars as pl
import pytest

from rivretrieve._internal.acquisition_provenance import (
    AcquisitionRecord,
    FactBinding,
    NativeTableIdentity,
    RecordingReference,
    SourceStatement,
)
from rivretrieve._internal.catalogue_origins import (
    Field,
    NativeColumn,
    enforce_catalogue_origins,
    validate_catalogue_origins,
)
from rivretrieve._internal.catalogues.native import RetrievedAt
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.be_wal.generate_catalogue import (
    STATION_SOURCE_SCHEMA,
    build_catalogue,
    catalogue_tables,
    parse_catchment_size,
    parse_kiwis_table,
    station_native_and_associations,
)
from rivretrieve._internal.providers.be_wal.origins import (
    STATION_CATALOGUE_ORIGINS,
    build_acquisition_provenance,
)
from rivretrieve._internal.providers.be_wal.series import (
    KIWIS_NAMESPACE,
    PRODUCT_BY_ID,
    PRODUCT_SPECS,
    describe_associations,
)
from rivretrieve._internal.providers.be_wal.station_metadata import project_station_metadata

STATION_HEADER = [
    "station_no",
    "station_id",
    "station_name",
    "river_name",
    "CATCHMENT_SIZE",
    "station_latitude",
    "station_longitude",
    "station_local_x",
    "station_local_y",
    "station_georefsystem",
    "TYPE_STATION",
    "ADMINISTRATEUR",
    "PAYS",
    "STA_PUBINT",
    "station_timezone",
    "station_utcoffset",
    "station_gauge_datum",
    "station_gauge_datum_unit",
]


def _st_row(
    station_no: str,
    *,
    name: str = "Station A",
    river: str = "Meuse",
    catchment: str = "125,50 km²",
    lat: str = "50.5",
    lon: str = "4.8",
    lx: str = "185000.0",
    ly: str = "130000.0",
    type_station: str = "Limnimètre",
) -> dict[str, str]:
    return {
        "station_no": station_no,
        "station_id": f"id-{station_no}",
        "station_name": name,
        "river_name": river,
        "CATCHMENT_SIZE": catchment,
        "station_latitude": lat,
        "station_longitude": lon,
        "station_local_x": lx,
        "station_local_y": ly,
        "station_georefsystem": "Lambert 72",
        "TYPE_STATION": type_station,
        "ADMINISTRATEUR": "DCENN",
        "PAYS": "Belgique",
        "STA_PUBINT": "yes",
        "station_timezone": "(UTC+01:00) Generic time zone",
        "station_utcoffset": "-60",
        "station_gauge_datum": "100.0",
        "station_gauge_datum_unit": "DNG",
    }


def _ts_row(
    station_no: str,
    ts_id: str,
    ts_name: str,
    *,
    param: str = "Débit",
    unit: str = "m³/s",
    from_str: str = "2020-01-01T00:00:00.000+01:00",
    to_str: str = "2026-11-23T00:00:00.000+01:00",
) -> dict[str, str]:
    return {
        "station_no": station_no,
        "station_name": f"Name-{station_no}",
        "ts_id": ts_id,
        "ts_name": ts_name,
        "ts_shortname": "Test",
        "ts_path": f"DCENN/{station_no}/{ts_name}",
        "parametertype_name": "Q",
        "stationparameter_name": param,
        "ts_unitsymbol": unit,
        "ts_spacing": "P1D",
        "from": from_str,
        "to": to_str,
    }


def _provenance():
    rec = RecordingReference(
        recording_id="kiwis-getStationList-allfields",
        repository_path="maintenance/catalogue/be_wal/official/web/kiwis-getStationList-allfields.body",
        source_url="https://hydrometrie.wallonie.be/services/KiWIS/KiWIS",
        retrieved_at=datetime(2026, 11, 23, 20, 0, tzinfo=UTC),
        media_type="application/json",
        sha256="a" * 64,
    )
    return build_acquisition_provenance(
        NativeTableIdentity(
            location_kind="retained",
            repository_path="maintenance/catalogue/be_wal/official/native.parquet",
            revision="b" * 40,
            sha256="c" * 64,
            byte_size=1024,
        ),
        (rec,),
        acquisitions=(
            AcquisitionRecord(
                acquisition_id="kiwis-getStationList-allfields",
                description="Synthetic SPW KiWIS capture",
                method="http_request",
                requested_from=("https://hydrometrie.wallonie.be/services/KiWIS/KiWIS",),
                instant_type="retrieval",
                retrieved_at_start=datetime(2026, 11, 23, 20, 0, tzinfo=UTC),
                recording_ids=("kiwis-getStationList-allfields",),
            ),
        ),
        source_bindings=(
            FactBinding(
                fact_group="be_wal_sources",
                facts=(
                    "source.station.kiwis_station_list",
                    "source.station.documented_crs",
                    "source.station.catchment_size_unit",
                    "source.station_product.kiwis_tslist",
                    "source.station_product.empty_coverage_checks",
                    "source.series.fields",
                    "source.series.temporal_semantics",
                    "source.series.stage_vertical_reference",
                    "source.series.annotations",
                    "source.provider.terms",
                    "source.provider.attribution",
                ),
                source_id="be_wal",
                acquisition_id="kiwis-getStationList-allfields",
            ),
        ),
        statements=(
            SourceStatement(
                kind="terms",
                exact_text=(
                    "La reproduction des données figurant sur le site, sur un support quelconque "
                    "(ce qui comprend l'acte de téléchargement), est autorisée sans accord préalable."
                ),
                recording_id="kiwis-getStationList-allfields",
                fact="source.provider.terms",
                verification_status="verified_public_recording",
            ),
            SourceStatement(
                kind="citation",
                exact_text="« Sources des données : Service public de Wallonie » ou « Sources des données : SPW »",
                recording_id="kiwis-getStationList-allfields",
                fact="source.provider.attribution",
                verification_status="verified_public_recording",
            ),
        ),
    )


def test_parse_kiwis_table_and_catchment_size_placeholders() -> None:
    raw = json.dumps([["a", "b"], ["1", None]]).encode("utf-8")
    assert parse_kiwis_table(raw, "sample") == [{"a": "1", "b": ""}]
    assert parse_catchment_size("", station_no="X") is None
    assert parse_catchment_size("0,00 km²", station_no="L8640") is None
    assert parse_catchment_size("221,50 km²", station_no="3643") == pytest.approx(221.5)
    with pytest.raises(FatalContractError, match="unsupported CATCHMENT_SIZE"):
        parse_catchment_size("unknown", station_no="X")


def test_station_native_filters_non_river_and_placeholder_shells() -> None:
    stations = [
        _st_row("3643", catchment="108,20 km²"),
        _st_row("L8640", catchment="0,00 km²", type_station="Debitmètre"),
        _st_row("MET01", type_station="Station météorologique"),
        _st_row("ZONE1", type_station=""),
        _st_row("5997"),  # Reservoir exclusion
        _st_row("640C01", type_station="Ouvrage"),
        _st_row("9109", lat="", lon=""),  # Coordinate-less shell
        _st_row("630201"),  # 0-series station
        _st_row("7326"),  # Débit axe hydraulique only
        _st_row("7406"),  # Débit virtuel only
    ]
    ts_rows = [
        _ts_row("3643", "1001", "20-Debit.Jour.Moyen", param="Débit", unit="m³/s"),
        _ts_row("L8640", "1002", "05-Hauteur.Complet", param="Hauteur sonde", unit="m", from_str="", to_str=""),
        _ts_row("5997", "1003", "20-Hauteur absolue.Jour.Moyen", param="Hauteur sonde", unit="m"),
        _ts_row("7326", "1004", "20-Debit.Jour.Moyen", param="Débit axe hydraulique", unit="m³/s"),
        _ts_row("7406", "1005", "10-Debit.1h.Moyen", param="Débit virtuel", unit="m³/s"),
    ]
    empty_payloads = [
        ("kiwis-empty-nonhourly-L8640", {"mode": "nonhourly"}, [{"ts_id": "1002", "rows": "0", "data": []}]),
    ]
    native, assocs = station_native_and_associations(
        stations,
        ts_rows,
        empty_check_payloads=empty_payloads,
        retrieved_at=RetrievedAt(datetime(2026, 11, 23, 20, 0, tzinfo=UTC)),
    )
    assert native.data.drop("retrieved_at").schema == STATION_SOURCE_SCHEMA
    assert native.data["station_no"].to_list() == ["3643", "L8640"]
    assert native.data["CATCHMENT_SIZE"].to_list() == [108.2, None]
    assert native.data["CATCHMENT_SIZE_raw"].to_list() == ["108,20 km²", "0,00 km²"]
    assert assocs["station_id"].to_list() == ["3643", "L8640"]
    assert assocs["available"].to_list() == [True, False]


def test_catalogue_projects_62_products_wgs84_origins_and_metadata() -> None:
    assert len(PRODUCT_SPECS) == 62
    assert len(PRODUCT_BY_ID) == 62
    native, assocs = station_native_and_associations(
        [_st_row("3643", catchment="108,20 km²"), _st_row("L8640", catchment="0,00 km²")],
        [
            _ts_row("3643", "1001", "20-Debit.Jour.Moyen", param="Débit", unit="m³/s"),
            _ts_row("L8640", "1002", "20-Temperature.Jour.Moyen", param="Temperature Eau", unit="°C"),
        ],
        empty_check_payloads=(),
        retrieved_at=RetrievedAt(datetime(2026, 11, 23, 20, 0, tzinfo=UTC)),
    )
    products, stations, pairs = catalogue_tables(native, assocs, checked_on=date(2026, 11, 23))
    assert products.height == 62
    assert stations.height == 2
    assert stations["crs"].to_list() == ["EPSG:4326", "EPSG:4326"]
    assert pairs.height == 124
    assert pairs.filter(pl.col("availability") == "available").height == 2
    assert pairs.filter(pl.col("availability") == "unavailable").height == 122
    assert validate_catalogue_origins(ProviderId("be_wal"), STATION_CATALOGUE_ORIGINS, native, stations) == []
    with pytest.raises(FatalContractError, match="station_id"):
        enforce_catalogue_origins(
            ProviderId("be_wal"),
            {**STATION_CATALOGUE_ORIGINS, "station_id": Field(NativeColumn("station_name"))},
            native,
            stations,
        )
    descs = describe_associations(assocs)
    assert len(descs.descriptions) == 2
    assert {d.identity.namespace for d in descs.descriptions} == {KIWIS_NAMESPACE}
    meta = project_station_metadata(native, stations)
    areas = meta.filter(pl.col("attribute_role") == "drainage_area").sort("station_id")
    assert areas["state"].to_list() == ["value", "source_null"]
    assert areas["source_dtype"].to_list() == ["Float64", "Float64"]
    assert areas["source_unit"].to_list() == ["km2", "km2"]
    assert meta.filter(pl.col("attribute_role") == "elevation")["state"].unique().to_list() == ["no_metadata"]

    cat = build_catalogue(
        native,
        STATION_CATALOGUE_ORIGINS,
        associations=assocs,
        checked_on=date(2026, 11, 23),
        provenance=_provenance(),
    )
    assert cat.provider_info["license"] is None
    assert cat.provider_info["citation"] == "Service public de Wallonie (SPW) — Hydrométrie"


@pytest.mark.governing(
    "maintenance/catalogue/be_wal/official",
    "maintenance/catalogue/be_wal/official/selection.json",
)
def test_selected_inputs_publish_deterministic_catalogue(
    retained_evidence_root, catalogue_input_receipt, catalogue_build_inputs, tmp_path
) -> None:
    """Build the real be_wal packaged catalogue deterministically from verified originals."""
    import os
    from pathlib import Path

    import polars.testing as pl_testing

    from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
    from rivretrieve._internal.providers.be_wal.generate_catalogue import main, read_catalogue_sources
    from rivretrieve._internal.providers.be_wal.origins import STATION_METADATA_NOTICE

    configured = os.environ.get("RIVRETRIEVE_CATALOGUE_PRODUCT_OUTPUT")
    if not configured:
        pytest.fail("Reviewed catalogue generation requires restricted product output.", pytrace=False)
    product_root = Path(configured).resolve()
    selection = "maintenance/catalogue/be_wal/official/selection.json"
    sources = read_catalogue_sources(
        retained_evidence_root, selection_path=selection, input_receipt=catalogue_input_receipt
    )
    build_inputs = catalogue_build_inputs(sources.provenance)
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(catalogue_input_receipt.model_dump_json())
    build_path = tmp_path / "build-inputs.json"
    build_path.write_text(build_inputs.model_dump_json())
    outputs = [product_root / "be_wal", product_root / "be_wal-repeat"]
    for output in outputs:
        assert (
            main(
                [
                    "--evidence-root",
                    str(retained_evidence_root),
                    "--selection",
                    selection,
                    "--input-receipt",
                    str(receipt_path),
                    "--build-inputs",
                    str(build_path),
                    "--out",
                    str(output),
                ]
            )
            == 0
        )
        load_packaged_catalogue_artifact(output, on_issue="raise")
        stations = pl.read_parquet(output / "stations.parquet")
        assert stations.height == 338
        assert stations["crs"].unique().to_list() == ["EPSG:4326"]
        products = pl.read_parquet(output / "products.parquet")
        assert products.height == 62
        pairs = pl.read_parquet(output / "station_products.parquet")
        assert pairs.height == 20_956
        assert pairs.filter(pl.col("availability") == "available").height == 8_198
        assert pairs.filter(pl.col("availability") == "unavailable").height == 12_758
        assert pairs.filter(pl.col("availability") == "unknown").height == 0
        provider = json.loads((output / "provider.json").read_bytes())
        assert provider["license"] is None
        assert provider["citation"] == "Service public de Wallonie (SPW) — Hydrométrie"
        assert STATION_METADATA_NOTICE in json.dumps(
            json.loads((output / "croissant.json").read_bytes()), ensure_ascii=False
        )
        assert not (output / "native.parquet").exists()
    assert {p.name for p in outputs[0].iterdir()} == {p.name for p in outputs[1].iterdir()}
    for path in outputs[0].iterdir():
        repeated = outputs[1] / path.name
        if path.suffix == ".parquet":
            pl_testing.assert_frame_equal(pl.read_parquet(path), pl.read_parquet(repeated))
