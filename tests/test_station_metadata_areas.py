"""Drainage lookup : PackagedSourceMetadata × Selection → SourceAreaFrame."""

from __future__ import annotations

import json
import socket
from importlib import import_module
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

import rivretrieve as rr
from rivretrieve._internal import discovery
from rivretrieve._internal.catalogues.native import NativeTable
from rivretrieve._internal.catalogues.station_metadata import build_station_metadata
from rivretrieve._internal.provider_manifest import BUILTIN_PROVIDER_IDS

AREA_SCHEMA = pl.Schema(
    {
        "provider_id": pl.String,
        "station_id": pl.String,
        "source_field": pl.String,
        "source_value": pl.String,
        "source_dtype": pl.String,
        "source_unit": pl.String,
        "state": pl.Enum(["value", "source_null", "no_metadata"]),
    }
)


def _area_columns(source: pl.DataFrame) -> pl.DataFrame:
    return source.filter(pl.col("attribute_role") == "drainage_area").select(AREA_SCHEMA.names())


def _areas(selection) -> pl.DataFrame:
    return _area_columns(rr.metadata(selection, view="source"))


# Independent source-column expectations, including established units only.
SOURCE_FIELDS = {
    "ba_fhmzbih": ("metadata_station_no", {"metadata_CATCHMENT_SIZE": None}),
    "br_ana": ("codigoestacao", {"Area_Drenagem": None}),
    "ca_eccc": ("STATION_NUMBER", {"DRAINAGE_AREA_GROSS": "km2", "DRAINAGE_AREA_EFFECT": "km2"}),
    "ch_foen": ("name", {}),
    "cz_chmi": ("objID", {"PLO_STA": "km²"}),
    "fr_hubeau": ("code_station", {"superficie_topo": None, "superficie_reelle": None}),
    "fr_hydroportail": ("bookmarkCode", {}),
    "jp_mlit": ("観測所記号", {"流域面積": None}),
    "lt_lhmt": ("code", {}),
    "no_nve": (
        "stationId",
        {
            "drainageBasinArea": "km2",
            "drainageBasinAreaNorway": "km2",
            "transferAreaIn": "km2",
            "transferAreaOut": "km2",
        },
    ),
    "pl_imgw": ("gauge_id", {"area": None}),
    "th_thaiwater": ("station.id", {}),
    "usgs_nwis": ("site_no", {"drain_area_va": "sq mi", "contrib_drain_area_va": "sq mi"}),
    "za_dws": ("Station", {"Catchment Area km**2": "km**2"}),
}


def test_canadian_example_and_product_deduplication() -> None:
    gauges = rr.find(provider="ca_eccc", station="02GA010", quantity="discharge", frequency="daily", statistic="mean")
    gauge = rr.pick(gauges, station="02GA010")
    expected = pl.DataFrame(
        [
            ("ca_eccc", "02GA010", "DRAINAGE_AREA_EFFECT", None, "Float64", "km2", "source_null"),
            ("ca_eccc", "02GA010", "DRAINAGE_AREA_GROSS", "1035.0", "Float64", "km2", "value"),
        ],
        schema=AREA_SCHEMA,
        orient="row",
    )
    assert_frame_equal(_areas(gauge), expected)
    all_products = rr.find(provider="ca_eccc", station="02GA010")
    assert len(all_products.series) > 1
    assert_frame_equal(_areas(all_products), expected)


def test_all_selected_gauges_remain_visible_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Drainage lookup must not use network or credentials")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(discovery, "_resolve_credentials", forbidden)
    monkeypatch.setattr(discovery, "dotenv_values", forbidden)
    selection = rr.find()
    before = rr.as_frame(selection)
    result = _areas(selection)
    keys = ["provider_id", "station_id"]
    assert_frame_equal(result.select(keys).unique().sort(keys), before.select(keys).unique().sort(keys))
    assert result.select(*keys, "source_field").is_duplicated().sum() == 0
    assert result["provider_id"].n_unique() == 14
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


@pytest.mark.parametrize(
    "provider",
    [
        pytest.param(
            provider,
            marks=pytest.mark.derived(f"src/rivretrieve/_internal/providers/{provider}/catalogue/native.parquet"),
        )
        for provider in BUILTIN_PROVIDER_IDS
    ],
)
def test_projection_preserves_every_native_scalar(provider: str, retained_evidence_root: Path) -> None:
    repository = Path(__file__).parents[1]
    catalogue = repository / "src/rivretrieve/_internal/providers" / provider / "catalogue"
    native = pl.read_parquet(
        retained_evidence_root / "src/rivretrieve/_internal/providers" / provider / "catalogue/native.parquet"
    )
    stations = pl.read_parquet(catalogue / "stations.parquet").select("station_id")
    projection = pl.read_parquet(catalogue / "station_metadata.parquet")
    origins = import_module(f"rivretrieve._internal.providers.{provider}.origins")
    if provider == "fr_hubeau":
        origin = origins.HYDROMETRY_STATION_CATALOGUE_ORIGINS["station_id"]
        assert origin == origins.TEMPERATURE_STATION_CATALOGUE_ORIGINS["station_id"]
    else:
        origin = origins.STATION_CATALOGUE_ORIGINS["station_id"]
    # Reuse this retained input for both rebuild equality and independent scalar
    # assertions, instead of reading all providers again in a subprocess test.
    if provider == "usgs_nwis":
        from rivretrieve._internal.providers.usgs_nwis.station_metadata import project_station_metadata

        rebuilt = project_station_metadata(NativeTable(native), stations, origin, origins.STATION_METADATA_FIELDS)
    else:
        rebuilt = build_station_metadata(
            provider, NativeTable(native), stations, origin, origins.STATION_METADATA_FIELDS
        )
    assert_frame_equal(rebuilt, projection)
    actual = _area_columns(projection)
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
    result = _areas(rr.find(provider="ba_fhmzbih", station="4510"))
    assert result["source_value"].item() == '"633.00 km²"'
    assert result["source_dtype"].item() == "String"
    assert result["source_unit"].item() is None


def test_nonbreaking_space_and_blank_are_values() -> None:
    nonbreaking = _areas(rr.find(provider="jp_mlit", station="301011281104310"))
    assert json.loads(nonbreaking["source_value"].item()) == "\u00a0"
    assert nonbreaking["state"].item() == "value"
    bosnia = _areas(rr.find(provider="ba_fhmzbih"))
    blanks = bosnia.filter(pl.col("source_value") == '""')
    assert blanks.height == 10
    assert set(blanks["state"]) == {"value"}


def test_station_metadata_does_not_require_numeric_source_unit_admission() -> None:
    selection = rr.find(provider="za_dws")
    inspected = rr.as_frame(selection)
    assert inspected["station_id"].n_unique() == 2905
    keys = ["provider_id", "station_id"]
    assert_frame_equal(
        _areas(selection).select(keys).unique().sort(keys),
        inspected.select(keys).unique().sort(keys),
    )


def test_station_metadata_is_independent_of_retained_map_coordinates() -> None:
    from dataclasses import replace

    selected = rr.find(provider="ca_eccc", station="02GA010", quantity="discharge", frequency="daily", statistic="mean")
    expected = _areas(selected)
    assert expected.height == 2
    summary = rr.metadata(selected)
    without_coordinates = replace(selected, locations=())
    assert_frame_equal(_areas(without_coordinates), expected)
    assert_frame_equal(rr.metadata(without_coordinates), summary)


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
    projection = _area_columns(
        pl.read_parquet(
            Path(__file__).parents[1] / "src/rivretrieve/_internal/providers/za_dws/catalogue/station_metadata.parquet"
        )
    )
    expected = projection.filter((pl.col("provider_id") == "za_dws") & (pl.col("station_id") == "A1H001"))
    assert expected.height > 0
    assert_frame_equal(_areas(selected), expected)
    without_geometry = replace(selected, locations=())
    assert_frame_equal(_areas(without_geometry), expected)
    assert_frame_equal(_areas(rr.pick(selected, quantity="discharge")), expected)
    for narrowed in (
        rr.pick(selected, quantity="temperature"),
        rr.pick(selected, variant="unestablished", on_issue="ignore"),
        rr.pick(selected, series_id=[], on_issue="ignore"),
        rr.pick(selected, provider="ch_foen"),
    ):
        assert_frame_equal(_areas(narrowed), pl.DataFrame(schema=AREA_SCHEMA))
