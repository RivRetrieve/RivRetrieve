"""Verify packaged Slovenia ARSO catalogue tables, coordinate rescues, and sentinel retention."""

from __future__ import annotations

from pathlib import Path

import pytest

import rivretrieve as rr
from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact

_CATALOGUE_DIR = Path(__file__).resolve().parents[1] / "src/rivretrieve/_internal/providers/si_arso/catalogue"


def test_si_arso_packaged_catalogue_counts_and_coordinate_rescues() -> None:
    artifact = load_packaged_catalogue_artifact(_CATALOGUE_DIR, on_issue="raise")
    stations = artifact.stations
    products = artifact.products
    pairs = artifact.station_products
    find_rows = rr.as_frame(rr.find(provider="si_arso"))

    assert stations.height == 619
    assert products.height == 18
    assert pairs.height == 619 * 18

    assert stations.filter(stations["crs"] == "EPSG:4326").height == 612
    assert stations.filter(stations["crs"] == "unknown").height == 7
    assert pairs.filter(pairs["availability"] == "available").height == 5_628
    assert find_rows.height == 5_628
    assert find_rows["station_id"].n_unique() == 615

    for excluded in ("3280", "4360", "5290", "9350", "9400"):
        assert stations.filter(stations["station_id"] == excluded).height == 0

    for sid in ("2070", "6150", "6380", "6620"):
        row = stations.filter(stations["station_id"] == sid).row(0, named=True)
        assert row["crs"] == "EPSG:4326"
        assert row["latitude"] is not None and row["longitude"] is not None

    row_1060 = stations.filter(stations["station_id"] == "1060").row(0, named=True)
    assert row_1060["latitude"] == pytest.approx(46.681243, abs=1e-4)
    assert row_1060["longitude"] == pytest.approx(15.995303, abs=1e-4)

    for sid in ("5049", "6310", "6570", "7290", "7450", "9090", "9290"):
        row = stations.filter(stations["station_id"] == sid).row(0, named=True)
        assert row["crs"] == "unknown"
        assert row["latitude"] is None and row["longitude"] is None

    for sid in ("3105", "3370"):
        assert stations.filter(stations["station_id"] == sid).height == 1
        assert pairs.filter((pairs["station_id"] == sid) & (pairs["availability"] == "available")).height > 0

    for empty_arch in ("5400", "5410", "5420", "9060"):
        assert pairs.filter((pairs["station_id"] == empty_arch) & (pairs["availability"] == "available")).height == 0
        assert find_rows.filter(find_rows["station_id"] == empty_arch).height == 0


def test_si_arso_station_metadata_sentinels_and_partitions() -> None:
    sel = rr.find(provider="si_arso", station=["1060", "2070", "3105", "4450", "6310"])
    meta = rr.metadata(sel)
    source = rr.metadata(sel, view="source")

    row_1060 = meta.filter(meta["station_id"] == "1060").row(0, named=True)
    assert float(row_1060["drainage_area_value"][0]) == pytest.approx(10197.2)

    row_2070 = meta.filter(meta["station_id"] == "2070").row(0, named=True)
    assert row_2070["drainage_area_field"] == ["F (km2)"]
    assert float(row_2070["drainage_area_value"][0]) == pytest.approx(13423.02)

    row_4450 = meta.filter(meta["station_id"] == "4450").row(0, named=True)
    assert float(row_4450["drainage_area_value"][0]) == pytest.approx(99999.99)

    row_3105 = meta.filter(meta["station_id"] == "3105").row(0, named=True)
    assert row_3105["drainage_area_value"] == [None]

    row_6310 = meta.filter(meta["station_id"] == "6310").row(0, named=True)
    assert row_6310["station_name"] == "Šmartno I"
    assert row_6310["water_body_name_value"] == ["Paka"]
    assert row_6310["drainage_area_field"] is None
    assert row_6310["drainage_area_value"] is None

    assert meta.filter(meta["elevation_value"].is_not_null()).height == 0

    src_6310_area = source.filter((source["station_id"] == "6310") & (source["attribute_role"] == "drainage_area")).row(
        0, named=True
    )
    assert src_6310_area["state"] == "no_metadata"
    src_3105_area = source.filter((source["station_id"] == "3105") & (source["attribute_role"] == "drainage_area")).row(
        0, named=True
    )
    assert src_3105_area["state"] == "source_null"


def test_si_arso_canonical_iso_frequencies_and_legacy_refusal() -> None:
    pt5m = rr.series(rr.find(provider="si_arso", frequency="PT5M"))
    assert pt5m["station_id"].n_unique() == 8
    assert (
        rr.series(rr.find(provider="si_arso", frequency="PT300S"))["series_id"].to_list() == pt5m["series_id"].to_list()
    )

    pt30m_t1 = rr.series(rr.find(provider="si_arso", station="3900", frequency="PT30M"))
    assert sorted(pt30m_t1["product_id"].to_list()) == [
        "operational_discharge_10min",
        "operational_discharge_30min",
        "operational_stage_10min",
        "operational_stage_30min",
        "operational_temperature_10min",
        "operational_temperature_30min",
    ]
    assert (
        rr.series(rr.find(provider="si_arso", station="3900", frequency="PT1800S"))["series_id"].to_list()
        == pt30m_t1["series_id"].to_list()
    )

    pt1h = rr.series(rr.find(provider="si_arso", station="1060", frequency="PT1H"))
    assert rr.series(rr.find(provider="si_arso", station="1060", frequency="PT60M"))["series_id"].to_list() == (
        pt1h["series_id"].to_list()
    )

    for legacy in ("daily", "monthly", "10min", "hourly"):
        with pytest.raises(ValueError, match="ISO 8601 duration"):
            rr.find(provider="si_arso", frequency=legacy)
        with pytest.raises(ValueError, match="ISO 8601 duration"):
            rr.pick(rr.find(provider="si_arso", station="1060"), frequency=legacy)
