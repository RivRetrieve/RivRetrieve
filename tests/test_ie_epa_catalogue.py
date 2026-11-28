"""Synthetic Ireland EPA HydroNet (`ie_epa`) station universe, availability and metadata checks."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, date, datetime

import polars as pl
import polars.testing as pl_testing
import pytest

from rivretrieve._internal.catalogue_origins import validate_catalogue_origins
from rivretrieve._internal.catalogues.native import RetrievedAt
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.ie_epa.generate_catalogue import (
    catalogue_tables,
    check_series_fields,
    station_native_table,
    station_product_associations,
)
from rivretrieve._internal.providers.ie_epa.origins import STATION_CATALOGUE_ORIGINS
from rivretrieve._internal.providers.ie_epa.station_metadata import project_station_metadata

RETRIEVED_AT = RetrievedAt(datetime(2026, 11, 27, 13, 0, tzinfo=UTC))
ALL_S = ("S/complete_daymean.zip", "S/complete_15min.zip", "S/1year_daymean.zip", "S/3_months.zip")
ALL_Q = ("Q/complete_daymean.zip", "Q/complete_15min.zip", "Q/1year_daymean.zip", "Q/3_months.zip")


def _station(site_no: str, station_no: str, **overrides: str) -> dict[str, str]:
    row = {
        "site_no": site_no,
        "station_no": station_no,
        "site_name": f"{site_no} Region",
        "station_name": f"Gauge {station_no}",
        "station_latitude": "53.2",
        "station_longitude": "-7.5",
        "station_carteasting": "200000.0",
        "station_cartnorthing": "200000.0",
        "station_local_x": "53.2",
        "station_local_y": "-7.5",
        "object_type": "General;Surface water",
        "station_status": "Active",
        "RESPONSIBLE_BODY": "Environmental Protection Agency",
        "STATION_OWNER": "Example County Council",
        "TYPE_OF_GAUGING": "Recorder",
        "catchment_name": "Example",
        "WTO_OBJECT": "EXAMPLE RIVER",
        "river_name": "EXAMPLE RIVER",
        "CATCHMENT_SIZE": "12.50 km²",
        "station_gauge_datum": "10.000",
        "station_gauge_datum_unit": "m OD Malin (OSGM15)",
        "DATA_AVAILABLE": "Water Level and Flow",
        "LTA_RAINFALL_1961_1990": "1000",
        "Web_Desc": "free text",
    }
    row.update(overrides)
    return row


def _file_list(site_no: str, station_no: str, *paths: str) -> dict[str, object]:
    links: list[dict[str, object]] = [{"type": "navigation", "rel": "self", "href": "x"}]
    for path in paths:
        parameter = path.split("/")[0]
        href = f"internet/stations/{site_no}/{station_no}/{path}"
        links.append({"type": "resource", "station_parameter": parameter, "href": href})
        links.append({"type": "resource", "station_parameter": parameter, "href": href.replace(".zip", ".png")})
    return {"site_no": site_no, "station_no": station_no, "_links": links}


def _register() -> tuple[list[dict[str, str]], dict[tuple[str, str], object]]:
    stations = [
        _station("DUB", "10047"),
        # Level-only station whose register text claims flow.
        _station("ATH", "25046", DATA_AVAILABLE="Water Level and Flow"),
        # Lettered identities, blank and zero catchment sizes, generic water body.
        _station(
            "CAS", "34109A", CATCHMENT_SIZE="", WTO_OBJECT="SPRING", river_name="SPRING", station_status="Inactive"
        ),
        _station("MON", "37016", CATCHMENT_SIZE="0.00 km²", DATA_AVAILABLE="Spot flows", station_status="Suspended"),
        _station("LIM", "123", station_gauge_datum_unit=""),
        # Excluded: gaugings only, no files, other agency, lake, spring.
        _station("CAS", "29006"),
        _station("COR", "22049"),
        _station("ATH", "26243", RESPONSIBLE_BODY="Office of Public Works"),
        _station("CAS", "33072", object_type="General;Surface water;Lake or Reservoir"),
        _station("DUB", "14100", object_type="General;Surface water;Spring"),
    ]
    file_lists: dict[tuple[str, str], object] = {
        ("DUB", "10047"): _file_list("DUB", "10047", *ALL_S, *ALL_Q, "Q/complete_gaugings.zip"),
        ("ATH", "25046"): _file_list("ATH", "25046", *ALL_S),
        ("CAS", "34109A"): _file_list("CAS", "34109A", "S/complete_daymean.zip", "S/complete_15min.zip"),
        ("MON", "37016"): _file_list("MON", "37016", "Q/complete_daymean.zip", "Q/complete_15min.zip"),
        ("LIM", "123"): _file_list("LIM", "123", "S/complete_15min.zip"),
        ("CAS", "29006"): _file_list("CAS", "29006", "Q/complete_gaugings.zip"),
        ("COR", "22049"): _file_list("COR", "22049"),
    }
    return stations, file_lists


def _native():
    stations, file_lists = _register()
    return station_native_table(stations, file_lists, retrieved_at=RETRIEVED_AT)


def test_universe_keeps_epa_river_gauges_with_listed_series_and_native_identity() -> None:
    native = _native()

    # Gaugings-only, file-less, non-EPA, lake and spring stations stay out; the
    # lettered and short identities are kept exactly as published.
    assert native.data["station_no"].to_list() == ["10047", "123", "25046", "34109A", "37016"]
    assert native.data.filter(pl.col("station_no") == "34109A")["site_no"].to_list() == ["CAS"]


def test_native_table_keeps_curated_fields_and_listed_file_facts() -> None:
    native = _native().data

    assert "LTA_RAINFALL_1961_1990" not in native.columns
    assert "Web_Desc" not in native.columns
    assert "station_local_x" not in native.columns
    row = native.filter(pl.col("station_no") == "25046").row(0, named=True)
    assert row["DATA_AVAILABLE"] == "Water Level and Flow"
    assert row["station_carteasting"] == "200000.0"
    assert (row["listed_S_1year_daymean"], row["listed_S_3_months"], row["listed_Q_complete_daymean"]) == (
        True,
        True,
        False,
    )
    rolling = native.filter(pl.col("station_no") == "34109A").row(0, named=True)
    assert (rolling["listed_S_1year_daymean"], rolling["listed_S_3_months"]) == (False, False)
    assert native.filter(pl.col("station_no") == "123")["station_gauge_datum_unit"].to_list() == [None]


def test_availability_follows_listed_full_history_files_only() -> None:
    pairs = station_product_associations(_native()).select("station_id", "product_id", "availability")
    expected = pl.DataFrame(
        [
            ("10047", "discharge_15min", "available"),
            ("10047", "discharge_daily", "available"),
            ("10047", "stage_15min", "available"),
            ("10047", "stage_daily", "available"),
            ("123", "discharge_15min", "unknown"),
            ("123", "discharge_daily", "unknown"),
            ("123", "stage_15min", "available"),
            ("123", "stage_daily", "unknown"),
            # DATA_AVAILABLE claims flow, but no Q file is listed.
            ("25046", "discharge_15min", "unknown"),
            ("25046", "discharge_daily", "unknown"),
            ("25046", "stage_15min", "available"),
            ("25046", "stage_daily", "available"),
            ("34109A", "discharge_15min", "unknown"),
            ("34109A", "discharge_daily", "unknown"),
            ("34109A", "stage_15min", "available"),
            ("34109A", "stage_daily", "available"),
            # Listed files are available even when their content is empty.
            ("37016", "discharge_15min", "available"),
            ("37016", "discharge_daily", "available"),
            ("37016", "stage_15min", "unknown"),
            ("37016", "stage_daily", "unknown"),
        ],
        schema=["station_id", "product_id", "availability"],
        orient="row",
    )
    pl_testing.assert_frame_equal(pairs, expected)
    reasons = station_product_associations(_native()).filter(pl.col("station_id") == "25046")
    assert (
        reasons.filter(pl.col("product_id") == "discharge_daily")["availability_reason"]
        .item()
        .startswith("EPA HydroNet station file list omits Q/complete_daymean.zip")
    )


def test_candidate_without_selected_file_list_is_rejected() -> None:
    stations, file_lists = _register()
    del file_lists[("COR", "22049")]
    with pytest.raises(FatalContractError, match="lack a selected file list"):
        station_native_table(stations, file_lists, retrieved_at=RETRIEVED_AT)


def test_unrecognised_hosted_file_is_rejected_rather_than_ignored() -> None:
    stations, file_lists = _register()
    file_lists[("COR", "22049")] = _file_list("COR", "22049", "S/complete_hourly.zip")
    with pytest.raises(FatalContractError, match="Unsupported EPA HydroNet file"):
        station_native_table(stations, file_lists, retrieved_at=RETRIEVED_AT)


def test_catalogue_keeps_coordinates_with_unknown_crs_and_unknown_product_facts() -> None:
    native = _native()
    products, stations, pairs = catalogue_tables(
        native, station_product_associations(native), checked_on=date(2026, 11, 28)
    )

    assert stations["crs"].unique().to_list() == ["unknown"]
    assert stations.filter(pl.col("station_id") == "10047").select("latitude", "longitude").row(0) == (53.2, -7.5)
    assert validate_catalogue_origins(ProviderId("ie_epa"), STATION_CATALOGUE_ORIGINS, native, stations) == []
    assert products.select("product_id", "observed_property", "unit").rows() == [
        ("discharge_15min", "discharge", "m3/s"),
        ("discharge_daily", "discharge", "m3/s"),
        ("stage_15min", "stage", "m"),
        ("stage_daily", "stage", "m"),
    ]
    assert products.select("frequency", "statistic", "period_type", "period_anchor").unique().rows() == [
        ("unknown", "unknown", "unknown", "unknown")
    ]
    assert set(pairs["availability"]) == {"available", "unknown"}
    assert pairs["published_record_start_date"].null_count() == pairs.height
    assert pairs["published_record_end_date"].null_count() == pairs.height


def test_station_metadata_maps_register_names_and_inline_catchment_sizes() -> None:
    native = _native()
    _, stations, _ = catalogue_tables(native, station_product_associations(native), checked_on=date(2026, 11, 28))
    metadata = project_station_metadata(native, stations)

    def value(station: str, role: str) -> tuple[str | None, str]:
        row = metadata.filter((pl.col("station_id") == station) & (pl.col("attribute_role") == role)).row(0, named=True)
        raw = row["source_value"]
        return (None if raw is None else json.loads(raw)), row["state"]

    assert value("34109A", "station_name") == ("Gauge 34109A", "value")
    assert value("34109A", "water_body_name") == ("SPRING", "value")
    assert value("34109A", "drainage_area") == (None, "source_null")
    assert value("37016", "drainage_area") == ("0.00 km²", "value")
    assert metadata.filter(pl.col("attribute_role") == "elevation")["state"].unique().to_list() == ["no_metadata"]


def _hosted_file(name: str, headers: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        text = "".join(f"#{key};{value}\n" for key, value in headers.items()) + "#Timestamp;Value;Quality Code Name\n"
        archive.writestr(name, text)
    return buffer.getvalue()


def test_series_field_witness_requires_published_parameter_and_unit() -> None:
    headers = {
        "Station Name": "EXAMPLE",
        "Station Number": "10050",
        "Station Parameter Name": "River Discharge",
        "Timeseries Name": "Cmd.Base",
        "Unit Symbol": "m³/s",
        "Rows": "0",
    }
    check_series_fields(
        _hosted_file("complete_15min.csv", headers), station_no="10050", parameter="Q", file="complete_15min"
    )
    with pytest.raises(FatalContractError, match="Unit Symbol"):
        check_series_fields(
            _hosted_file("complete_15min.csv", {**headers, "Unit Symbol": "l/s"}),
            station_no="10050",
            parameter="Q",
            file="complete_15min",
        )


@pytest.mark.governing(
    "maintenance/catalogue/ie_epa/official",
    "maintenance/catalogue/ie_epa/official/selection.json",
)
def test_selected_inputs_publish_deterministic_catalogue(
    retained_evidence_root, catalogue_input_receipt, catalogue_build_inputs, tmp_path
) -> None:
    """Build the packaged ie_epa catalogue twice from verified originals and check its counts."""
    import os
    from pathlib import Path

    from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
    from rivretrieve._internal.providers.ie_epa.generate_catalogue import main, read_catalogue_sources

    configured = os.environ.get("RIVRETRIEVE_CATALOGUE_PRODUCT_OUTPUT")
    if not configured:
        pytest.fail("Reviewed catalogue generation requires restricted product output.", pytrace=False)
    product_root = Path(configured).resolve()
    selection = "maintenance/catalogue/ie_epa/official/selection.json"
    sources = read_catalogue_sources(
        retained_evidence_root, selection_path=selection, input_receipt=catalogue_input_receipt
    )
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(catalogue_input_receipt.model_dump_json())
    build_path = tmp_path / "build-inputs.json"
    build_path.write_text(catalogue_build_inputs(sources.provenance).model_dump_json())
    outputs = [product_root / "ie_epa", product_root / "ie_epa-repeat"]
    for output in outputs:
        arguments = ["--evidence-root", str(retained_evidence_root), "--selection", selection]
        arguments += ["--input-receipt", str(receipt_path), "--build-inputs", str(build_path), "--out", str(output)]
        assert main(arguments) == 0
        load_packaged_catalogue_artifact(output, on_issue="raise")
        stations = pl.read_parquet(output / "stations.parquet")
        assert stations.height == 385
        assert {"34109A", "26338A"} <= set(stations["station_id"])
        assert stations["crs"].unique().to_list() == ["unknown"]
        pairs = pl.read_parquet(output / "station_products.parquet")
        counts = dict(pairs.group_by("availability").len().iter_rows())
        assert counts == {"available": 1352, "unknown": 188}
        assert not (output / "native.parquet").exists()
    assert {p.name for p in outputs[0].iterdir()} == {p.name for p in outputs[1].iterdir()}
    for path in outputs[0].iterdir():
        if path.suffix == ".parquet":
            pl_testing.assert_frame_equal(pl.read_parquet(path), pl.read_parquet(outputs[1] / path.name))
