"""coverage figure : CatalogueIdentities × CountryBoundaries → CountShading."""

import re
import runpy
from pathlib import Path

import polars as pl
import pytest

ROOT = Path(__file__).resolve().parents[1]

_ONES = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}


def _parse_cardinal(token: str) -> int:
    normalized = token.lower()
    if normalized.isdigit():
        return int(normalized)
    if normalized in _ONES:
        return _ONES[normalized]
    if normalized in _TENS:
        return _TENS[normalized]
    tens, sep, ones = normalized.partition("-")
    if sep and tens in _TENS and ones in _ONES and 1 <= _ONES[ones] <= 9:
        return _TENS[tens] + _ONES[ones]
    raise ValueError(f"Unsupported count token: {token!r}")


def _assert_readme_coverage_claims(
    readme: str,
    provider_country: dict[str, str],
    planned_country: dict[str, str],
) -> dict[str, int]:
    assert set(provider_country.values()).isdisjoint(planned_country)

    summary = re.search(
        r"retrieves observations\s+from\s+([\w-]+)\s+different\s+providers\s+in\s+([\w-]+)\s+countries\.",
        readme,
    )
    assert summary is not None
    assert _parse_cardinal(summary.group(1)) == len(provider_country)
    assert _parse_cardinal(summary.group(2)) == len(set(provider_country.values()))

    rows = re.findall(
        r"^\|\s*([^|]+?)\s*\|\s*[^|]+?\s*\|\s*`([^`]+)`\s*\|\s*([\d,]+)\s*\|",
        readme,
        re.MULTILINE,
    )
    table = {provider: int(count.replace(",", "")) for _, provider, count in rows}
    assert len(rows) == len(table)
    assert set(table) == set(provider_country)

    names_by_code: dict[str, set[str]] = {}
    codes_by_name: dict[str, set[str]] = {}
    for country, provider, _ in rows:
        code = provider_country[provider]
        names_by_code.setdefault(code, set()).add(country)
        codes_by_name.setdefault(country, set()).add(code)
    assert all(len(names) == 1 for names in names_by_code.values())
    assert all(len(codes) == 1 for codes in codes_by_name.values())

    coming_soon_match = re.search(
        r"<summary>Countries coming soon</summary>\s+(.+?)\.\s*\n\n",
        readme,
        re.DOTALL,
    )
    assert coming_soon_match is not None
    coming_soon_paragraph = " ".join(coming_soon_match.group(1).split())
    parts = [part.strip() for part in coming_soon_paragraph.split(",") if part.strip()]
    if parts[-1].startswith("and "):
        parts[-1] = parts[-1].removeprefix("and ").strip()
    else:
        before_and, sep, after_and = parts[-1].partition(" and ")
        assert sep, f"Expected final 'and' conjunction in Countries coming soon: {parts[-1]!r}"
        parts[-1:] = [before_and.strip(), after_and.strip()]
    coming_soon = [part.removeprefix("the ") for part in parts]
    expected_planned = sorted(label.split(" (", 1)[0] for label in planned_country.values())
    assert coming_soon == expected_planned
    assert set(codes_by_name).isdisjoint(coming_soon)
    return table


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


@pytest.mark.usefixtures("reuse_packaged_catalogues")
def test_catalogue_counts_match_readme_and_observation_capabilities():
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
    assert supported == set(module["PROVIDER_COUNTRY"])
    assert "za_dws" not in supported
    table = _assert_readme_coverage_claims(
        (ROOT / "README.md").read_text(),
        module["PROVIDER_COUNTRY"],
        module["PLANNED_COUNTRY"],
    )
    assert actual == table
    assert module["country_counts"](frame) == module["country_counts"](stations)


def test_readme_coverage_claims_reject_parallel_merge_drift():
    provider_country = {"fi_syke": "FIN", "fr_hubeau": "FRA", "fr_hydroportail": "FRA"}
    planned_country = {"CHL": "Chile", "GBR": "United Kingdom (EA, NRFA, SEPA)"}
    valid = (
        "Currently, RivRetrieve retrieves observations\n"
        "from three different providers in two countries.\n\n"
        "| Country | Agency | Provider | Stations | Access |\n"
        "|---|---|---|---:|---|\n"
        "| Finland | Syke | `fi_syke` | 2,543 | Open |\n"
        "| France | Hub'Eau | `fr_hubeau` | 7,347 | Open |\n"
        "| France | HydroPortail | `fr_hydroportail` | 6,409 | Open |\n\n"
        "<details>\n"
        "<summary>Countries coming soon</summary>\n\n"
        "Chile and the United Kingdom.\n\n"
        "Context paragraph.\n"
        "</details>\n"
    )
    assert _assert_readme_coverage_claims(valid, provider_country, planned_country) == {
        "fi_syke": 2543,
        "fr_hubeau": 7347,
        "fr_hydroportail": 6409,
    }
    assert _parse_cardinal("twenty-one") == 21
    assert _parse_cardinal("21") == 21

    with pytest.raises(AssertionError):
        _assert_readme_coverage_claims(
            valid.replace("three different providers", "two different providers"),
            provider_country,
            planned_country,
        )
    with pytest.raises(AssertionError):
        _assert_readme_coverage_claims(
            valid.replace("two countries", "one countries"),
            provider_country,
            planned_country,
        )
    with pytest.raises(AssertionError):
        _assert_readme_coverage_claims(
            valid.replace("Chile and the United Kingdom.", "Chile, Finland and the United Kingdom."),
            provider_country,
            planned_country,
        )
    with pytest.raises(AssertionError):
        _assert_readme_coverage_claims(
            valid,
            provider_country,
            planned_country | {"FIN": "Finland"},
        )


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


@pytest.mark.derived("maintenance/catalogue/usgs_nwis")
def test_usgs_station_inventory_preserves_selected_source_scope(retained_evidence_root: Path):
    from polars.testing import assert_frame_equal

    catalogue = ROOT / "src/rivretrieve/_internal/providers/usgs_nwis/catalogue"
    stations = pl.read_parquet(catalogue / "stations.parquet")
    native = pl.read_parquet(retained_evidence_root / "maintenance/catalogue/usgs_nwis/modern-native.parquet")
    # Independently reconciled modern scope includes non-stream and continuous-only locations.
    assert native.height == stations.height == 29_642
    columns = ["station_id", "latitude", "longitude", "crs"]
    assert_frame_equal(native.select(columns).sort("station_id"), stations.select(columns).sort("station_id"))
    assert {"435444087462300", "0167889257", "08041945", "09385701"} <= set(stations["station_id"])
    # Availability follows concrete supported source identities, not historical calendar claims.
    from rivretrieve._internal.catalogues.source_series import decode_source_descriptions

    descriptions = decode_source_descriptions((catalogue / "source_series.json").read_bytes())
    expected_daily = {
        item.station_id for item in descriptions.descriptions if item.product_id == "discharge_daily_mean"
    }
    daily = pl.read_parquet(catalogue / "station_products.parquet").filter(
        (pl.col("product_id") == "discharge_daily_mean") & (pl.col("availability") == "available")
    )
    assert set(daily["station_id"]) == expected_daily
