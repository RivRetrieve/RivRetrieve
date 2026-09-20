"""Drainage lookup : PackagedSourceMetadata × Selection → SourceAreaFrame."""

from __future__ import annotations

import json
import socket
import subprocess
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

import rivretrieve as rr
from rivretrieve._internal import discovery
from rivretrieve._internal.drainage_areas import DRAINAGE_AREA_SCHEMA, drainage_area_frame
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.provider_manifest import BUILTIN_PROVIDER_IDS

# Independent source-column expectations, including established units only.
SOURCE_FIELDS = {
    "ba_fhmzbih": ("metadata_station_no", {"metadata_CATCHMENT_SIZE": None}),
    "br_ana": ("codigoestacao", {"Area_Drenagem": None}),
    "ca_eccc": ("STATION_NUMBER", {"DRAINAGE_AREA_GROSS": None, "DRAINAGE_AREA_EFFECT": None}),
    "ch_foen": ("name", {}),
    "cz_chmi": ("objID", {"PLO_STA": "km²"}),
    "fr_hubeau": ("code_station", {"superficie_topo": None, "superficie_reelle": None}),
    "jp_mlit": ("観測所記号", {"流域面積": None}),
    "lt_lhmt": ("code", {}),
    "no_nve": ("stationId", {"drainageBasinArea": "km2", "drainageBasinAreaNorway": "km2"}),
    "pl_imgw": ("gauge_id", {"area": None}),
    "th_thaiwater": ("station.id", {}),
    "usgs_nwis": ("site_no", {"drain_area_va": "sq mi", "contrib_drain_area_va": None}),
    "za_dws": ("Station", {"Catchment Area km**2": "km**2"}),
}


def test_canadian_example_and_product_deduplication() -> None:
    gauges = rr.find(provider="ca_eccc", station="02GA010", quantity="discharge", frequency="daily", statistic="mean")
    gauge = rr.pick(gauges, station="02GA010")
    expected = pl.DataFrame(
        [
            ("ca_eccc", "02GA010", "DRAINAGE_AREA_EFFECT", None, "Float64", None, "source_null"),
            ("ca_eccc", "02GA010", "DRAINAGE_AREA_GROSS", "1035.0", "Float64", None, "value"),
        ],
        schema=DRAINAGE_AREA_SCHEMA,
        orient="row",
    )
    assert_frame_equal(rr.drainage_areas(gauge), expected)
    all_products = rr.find(provider="ca_eccc", station="02GA010")
    assert len(all_products.series) > 1
    assert_frame_equal(rr.drainage_areas(all_products), expected)


def test_all_selected_gauges_remain_visible_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Drainage lookup must not use network or credentials")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(discovery, "_resolve_credentials", forbidden)
    monkeypatch.setattr(discovery, "dotenv_values", forbidden)
    selection = rr.find()
    before = rr.as_frame(selection)
    result = rr.drainage_areas(selection)
    keys = ["provider_id", "station_id"]
    assert_frame_equal(result.select(keys).unique().sort(keys), before.select(keys).unique().sort(keys))
    assert result.select(*keys, "source_field").is_duplicated().sum() == 0
    assert result["provider_id"].n_unique() == 13
    assert_frame_equal(rr.as_frame(selection), before)
    # Same station strings in different providers must not collapse.
    overlapping = before.select(keys).unique().group_by("station_id").len().filter(pl.col("len") > 1)
    assert overlapping.height > 0
    for provider in ("ch_foen", "lt_lhmt", "th_thaiwater"):
        absent = result.filter(pl.col("provider_id") == provider)
        assert set(absent["state"]) == {"no_metadata"}
        assert (
            absent.select("source_field", "source_value", "source_dtype", "source_unit").null_count().row(0)
            == (absent.height,) * 4
        )
    assert "lakeArea" not in result["source_field"]
    assert "regulationArea" not in result["source_field"]


def test_empty_and_invalid_selection() -> None:
    empty = rr.pick(
        rr.find(provider="ca_eccc", station="02GA010", quantity="stage"),
        quantity="discharge",
    )
    assert_frame_equal(rr.drainage_areas(empty), pl.DataFrame(schema=DRAINAGE_AREA_SCHEMA))
    with pytest.raises(TypeError, match="RivRetrieve selection"):
        rr.drainage_areas(pl.DataFrame())  # ty: ignore[invalid-argument-type]


@pytest.mark.parametrize("provider", BUILTIN_PROVIDER_IDS)
def test_projection_preserves_every_native_scalar(provider: str) -> None:
    repository = Path(__file__).parents[1]
    catalogue = repository / "src/rivretrieve/_internal/providers" / provider / "catalogue"
    native = pl.read_parquet(catalogue / "native.parquet")
    stations = pl.read_parquet(catalogue / "stations.parquet").select("station_id")
    projection = pl.read_parquet(repository / "src/rivretrieve/_internal/catalogues/drainage_areas.parquet")
    actual = projection.filter(pl.col("provider_id") == provider)
    identity, fields = SOURCE_FIELDS[provider]
    assert_frame_equal(actual.select("station_id").unique().sort("station_id"), stations.sort("station_id"))
    assert set(actual["source_field"].drop_nulls()) == set(fields)
    # Canonical scope excludes native-only gauges (notably Brazil).
    native = native.join(stations, left_on=identity, right_on="station_id", how="semi").sort(identity)
    for field, unit in fields.items():
        rows = actual.filter(pl.col("source_field") == field).sort("station_id")
        decoded = [None if value is None else json.loads(value) for value in rows["source_value"]]
        restored = pl.DataFrame(
            {identity: rows["station_id"], field: pl.Series(field, decoded, dtype=native.schema[field])}
        )
        assert_frame_equal(restored, native.select(identity, field))
        assert set(rows["source_dtype"]) == {str(native.schema[field])}
        assert set(rows["source_unit"]) == {unit}
        expected_states = ["source_null" if value is None else "value" for value in native[field]]
        assert rows["state"].to_list() == expected_states


def test_formatted_string_is_not_parsed() -> None:
    result = rr.drainage_areas(rr.find(provider="ba_fhmzbih", station="4510"))
    assert result["source_value"].item() == '"633.00 km²"'
    assert result["source_dtype"].item() == "String"
    assert result["source_unit"].item() is None


def test_nonbreaking_space_and_blank_are_values() -> None:
    nonbreaking = rr.drainage_areas(rr.find(provider="jp_mlit", station="301011281104310"))
    assert json.loads(nonbreaking["source_value"].item()) == "\u00a0"
    assert nonbreaking["state"].item() == "value"
    bosnia = rr.drainage_areas(rr.find(provider="ba_fhmzbih"))
    blanks = bosnia.filter(pl.col("source_value") == '""')
    assert blanks.height == 10
    assert set(blanks["state"]) == {"value"}


def test_projection_build_is_current() -> None:
    result = subprocess.run(
        ["uv", "run", "python", "scripts/build_drainage_areas.py", "--check"],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_broken_projection_does_not_become_absence() -> None:
    stations = pl.DataFrame({"provider_id": ["ca_eccc"], "station_id": ["02GA010"]})
    with pytest.raises(FatalContractError, match="absent"):
        drainage_area_frame(stations, pl.DataFrame(schema=DRAINAGE_AREA_SCHEMA))
    with pytest.raises(FatalContractError, match="schema"):
        drainage_area_frame(stations, pl.DataFrame())


def test_station_metadata_does_not_require_numeric_source_unit_admission() -> None:
    selection = rr.find(provider="za_dws")
    inspected = rr.as_frame(selection)
    assert inspected["station_id"].n_unique() == 2905
    keys = ["provider_id", "station_id"]
    assert_frame_equal(
        rr.drainage_areas(selection).select(keys).unique().sort(keys),
        inspected.select(keys).unique().sort(keys),
    )


def test_station_metadata_is_independent_of_retained_map_coordinates() -> None:
    from dataclasses import replace

    selected = rr.find(provider="ca_eccc", station="02GA010", quantity="discharge", frequency="daily", statistic="mean")
    expected = rr.drainage_areas(selected)
    assert expected.height == 2
    without_coordinates = replace(selected, locations=())
    assert_frame_equal(rr.drainage_areas(without_coordinates), expected)


def test_catalogue_only_station_metadata_without_numeric_admission(monkeypatch: pytest.MonkeyPatch) -> None:
    from dataclasses import replace

    from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
    from rivretrieve._internal.providers.ch_foen.declaration import declaration as swiss_declaration
    from rivretrieve._internal.providers.za_dws.declaration import declaration
    from rivretrieve._internal.registry import ProviderRegistry
    from rivretrieve._internal.source_series import EvidenceFact, PhysicalFacts, admission, stable_id

    # Controlled missing-unit catalogue, not a claim about current DWS evidence.
    # Keep real station metadata and pass unadmitted facts through public discovery.
    artifact = load_packaged_catalogue_artifact(declaration.catalogue)
    assert artifact.source_descriptions is not None
    descriptions = []
    for description in artifact.source_descriptions.descriptions:
        facts = []
        for original in description.facts:
            unknown_unit = PhysicalFacts.model_validate(
                original.model_dump() | {"source_unit": EvidenceFact(), "normalized_unit": None}
            )
            unknown_unit = unknown_unit.model_copy(
                update={"facts_id": stable_id(unknown_unit.model_dump_json(exclude={"facts_id"}))}
            )
            assert admission(unknown_unit).status == "unsupported"
            facts.append(unknown_unit)
        descriptions.append(description.model_copy(update={"facts": tuple(facts)}))
    unsupported = replace(
        artifact,
        source_descriptions=artifact.source_descriptions.model_copy(update={"descriptions": tuple(descriptions)}),
    )
    registry = ProviderRegistry()
    registry.register("za_dws", unsupported)
    registry.register("ch_foen", load_packaged_catalogue_artifact(swiss_declaration.catalogue))
    monkeypatch.setattr(discovery, "_registry", registry)
    monkeypatch.setattr(discovery, "_ensure_default_providers_registered", lambda: None)
    selected = rr.find(provider="za_dws", station="A1H001")
    assert not selected.series
    assert len(selected.locations) == 1
    projection = pl.read_parquet(
        Path(__file__).parents[1] / "src/rivretrieve/_internal/catalogues/drainage_areas.parquet"
    )
    expected = projection.filter((pl.col("provider_id") == "za_dws") & (pl.col("station_id") == "A1H001"))
    assert expected.height > 0
    assert_frame_equal(rr.drainage_areas(selected), expected)
    without_geometry = replace(selected, locations=())
    assert_frame_equal(rr.drainage_areas(without_geometry), expected)
    assert_frame_equal(rr.drainage_areas(rr.pick(selected, quantity="discharge")), expected)
    for narrowed in (
        rr.pick(selected, quantity="temperature"),
        rr.pick(selected, variant="unestablished", on_issue="ignore"),
        rr.pick(selected, series_id=[], on_issue="ignore"),
        rr.pick(selected, provider="ch_foen"),
    ):
        assert_frame_equal(rr.drainage_areas(narrowed), pl.DataFrame(schema=DRAINAGE_AREA_SCHEMA))
