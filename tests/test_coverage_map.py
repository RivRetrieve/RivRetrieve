"""coverage figure : CatalogueIdentities × CountryBoundaries → CountShading."""

import runpy
from pathlib import Path

import polars as pl
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_draw_needs_only_station_identity_not_unestablished_coordinates(tmp_path):
    gpd = pytest.importorskip("geopandas")
    pytest.importorskip("matplotlib")
    from shapely.geometry import box

    module = runpy.run_path(str(ROOT / "docs/scripts/coverage_map.py"))
    world = gpd.GeoDataFrame(
        {"ADM0_A3": ["USA", "PRI", "ATA"]},
        geometry=[box(-120, 30, -80, 50), box(-67, 18, -65, 19), box(-180, -90, 180, -60)],
        crs="EPSG:4326",
    )
    stations = pl.DataFrame({"provider_id": ["usgs_nwis"] * 60, "station_id": [str(i) for i in range(60)]})
    output = tmp_path / "coverage.png"
    module["draw"](world, stations, output)
    assert output.read_bytes().startswith(b"\x89PNG")


def test_catalogue_counts_match_readme_and_observation_capabilities():
    import re

    import rivretrieve as rr
    from rivretrieve._internal.provider_manifest import BUILTIN_PROVIDER_IDS
    from rivretrieve._internal.providers.registration import CatalogueOnly, load_manifest

    module = runpy.run_path(str(ROOT / "docs/scripts/coverage_map.py"))
    supported = {
        item.provider_id
        for item in load_manifest(BUILTIN_PROVIDER_IDS)
        if not isinstance(item.declaration.observations, CatalogueOnly)
    }
    frame = rr.as_frame(rr.find()).filter(pl.col("provider_id").is_in(supported))
    stations = frame.select("provider_id", "station_id").unique()
    actual = dict(stations.group_by("provider_id").len().iter_rows())
    table = {
        provider: int(count.replace(",", ""))
        for provider, count in re.findall(r"\| `([^`]+)` \| ([\d,]+) \|", (ROOT / "README.md").read_text())
    }
    assert actual == table
    assert supported == set(module["PROVIDER_COUNTRY"])
    assert "za_dws" not in supported
    assert sum(actual.values()) == 74114
    assert module["country_counts"](frame) == module["country_counts"](stations)


def test_boundaries_must_match_country_not_sovereign_and_must_include_supported_country(tmp_path, monkeypatch):
    gpd = pytest.importorskip("geopandas")
    pytest.importorskip("matplotlib")
    from shapely.geometry import box

    module = runpy.run_path(str(ROOT / "docs/scripts/coverage_map.py"))
    world = gpd.GeoDataFrame(
        {"ADM0_A3": ["USA", "PRI", "ATA"], "SOV_A3": ["US1", "US1", "ATA"]},
        geometry=[box(-120, 30, -80, 50), box(-67, 18, -65, 19), box(-180, -90, 180, -60)],
        crs="EPSG:4326",
    )
    stations = pl.DataFrame({"provider_id": ["usgs_nwis"] * 60, "station_id": [str(i) for i in range(60)]})
    plotted = []
    original = gpd.plotting.GeoplotAccessor.__call__

    def capture(accessor, *args, **kwargs):
        plotted.append(accessor._parent.copy())
        return original(accessor, *args, **kwargs)

    monkeypatch.setattr(gpd.plotting.GeoplotAccessor, "__call__", capture)
    module["draw"](world, stations, tmp_path / "map.png")
    assert set(plotted[0]["ADM0_A3"]) == {"USA", "PRI"}
    assert set(plotted[1]["ADM0_A3"]) == {"USA"}
    assert plotted[1]["gauges"].tolist() == [60]
    with pytest.raises(ValueError, match="Boundary source lacks ADM0_A3"):
        module["draw"](world.loc[world["ADM0_A3"] != "USA"], stations, tmp_path / "missing.png")
