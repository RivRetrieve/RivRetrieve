"""Drainage lookup : PackagedSourceMetadata × Selection → SourceAreaFrame."""

from __future__ import annotations

import json
import socket
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

import rivretrieve as rr
from rivretrieve._internal import discovery
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
    "pl_imgw": ("gauge_id", {"area": "square kilometre"}),
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
    for provider in ("lt_lhmt", "th_thaiwater"):
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
    # The shared catalogue-origin contract rebuilds the full publication. This
    # check independently compares each adopted area field held in native bytes.
    actual = _area_columns(projection)
    identity, fields = SOURCE_FIELDS[provider]
    assert_frame_equal(actual.select("station_id").unique().sort("station_id"), stations.sort("station_id"))
    supplementary = {"ch_foen": {"Catchment size"}, "fr_hubeau": {"surface_bv"}}.get(provider, set())
    assert set(actual["source_field"].drop_nulls()) == set(fields) | supplementary
    if provider == "ch_foen":
        direct = actual.filter(pl.col("source_field") == "Catchment size")
        assert set(direct["source_dtype"]) == {"String"}
        assert set(direct["source_unit"]) == {"km2"}
        assert set(direct["state"]) == {"value"}
    elif provider == "fr_hubeau":
        # The site response owns surface_bv; the separate original-site test
        # compares its values. Native union padding is not field exposure.
        native = native.filter(pl.col("source_endpoint") == "temperature/station")
        for field in fields:
            assert set(projection.filter(pl.col("source_field") == field)["source_scope"]) == {"temperature/station"}
        site = projection.filter(pl.col("source_field") == "surface_bv")
        assert set(site["source_scope"]) == {"hydrometrie/referentiel/sites"}
        assert set(site["source_dtype"]) == {"Float64"}
        assert set(site["source_unit"]) == {"km²"}
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


def test_poland_area_unit_is_aligned_and_supported_by_the_retained_workbook(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests._provenance import legacy_document

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Poland metadata must work without network or credentials")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(discovery, "_resolve_credentials", forbidden)
    monkeypatch.setattr(discovery, "dotenv_values", forbidden)
    selection = rr.find(provider="pl_imgw")
    source = _areas(selection).sort("station_id")
    assert source.height == 1301
    assert set(source["source_field"]) == {"area"}
    assert set(source["source_dtype"]) == {"Float64"}
    assert set(source["source_unit"]) == {"square kilometre"}
    summary = rr.metadata(selection)
    aligned = summary.select(
        "provider_id",
        "station_id",
        "drainage_area_field",
        "drainage_area_value",
        "drainage_area_unit",
    ).explode("drainage_area_field", "drainage_area_value", "drainage_area_unit")
    assert_frame_equal(
        aligned.rename(
            {
                "drainage_area_field": "source_field",
                "drainage_area_value": "source_value",
                "drainage_area_unit": "source_unit",
            }
        ).sort("station_id"),
        source.select("provider_id", "station_id", "source_field", "source_value", "source_unit"),
    )
    catalogue = Path(__file__).parents[1] / "src/rivretrieve/_internal/providers/pl_imgw/catalogue"
    provenance = legacy_document(catalogue / "provenance.json")
    unit_fact = "source.grdc.catchment_area_unit"
    projection = next(
        binding for binding in provenance["fact_bindings"] if "metadata.drainage_area.area" in binding["facts"]
    )
    assert {"source_id": "sr.pl.grdc", "fact": unit_fact} in projection["transformation"]["external_inputs"]
    adopted = [item for item in provenance["build_inputs"]["inputs"] if unit_fact in item["facts"]]
    assert len(adopted) == 1
    assert adopted[0]["usage"] == "reviewed_support"
    assert adopted[0]["reference"]["sha256"] == "dfab6ea7de80fb1570f4a8dded8743ed7c7dcb4eb67fe75e2c0e02e9b964b7bf"
    assert adopted[0]["reference"]["byte_size"] == 116301


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


@pytest.mark.derived("src/rivretrieve/_internal/providers/fr_hubeau/catalogue/native.parquet")
@pytest.mark.governing(
    "maintenance/catalogue/station_metadata/sources/fr_hubeau/sites/documents.json",
    "maintenance/catalogue/station_metadata/sources/fr_hubeau/sites/lineage.json",
    full_verification=("fr_hubeau",),
)
def test_france_site_area_values_match_original_responses_and_native_site_links(
    retained_evidence_root: Path, catalogue_input_receipt
) -> None:
    # This expectation reads original scalar values independently of the production
    # parser/projector. Request and byte integrity are certified before this check.
    from rivretrieve._internal.catalogues.inputs import verify_retained_input_files

    consumer_root = "maintenance/catalogue/station_metadata/sources/fr_hubeau/sites"
    selected = tuple(
        item for item in catalogue_input_receipt.inputs if item.consumer_path.startswith(consumer_root + "/")
    )
    assert selected
    verify_retained_input_files(
        catalogue_input_receipt.model_copy(update={"inputs": selected, "declaration_inputs": (), "support_inputs": ()}),
        retained_evidence_root,
    )
    source_root = retained_evidence_root / consumer_root
    documents = json.loads((source_root / "documents.json").read_bytes())
    values = [
        {"code_site": row["code_site"], "surface_bv": row["surface_bv"]}
        for document in documents
        for row in json.loads((source_root / document["id"] / "body").read_bytes())["data"]
    ]
    sites = pl.DataFrame(values, schema={"code_site": pl.String, "surface_bv": pl.Float64})
    assert sites["code_site"].n_unique() == sites.height
    native = pl.read_parquet(
        retained_evidence_root / "src/rivretrieve/_internal/providers/fr_hubeau/catalogue/native.parquet"
    )
    catalogue = Path(__file__).parents[1] / "src/rivretrieve/_internal/providers/fr_hubeau/catalogue"
    canonical = pl.read_parquet(catalogue / "stations.parquet").select("station_id")
    associations = (
        native.filter(pl.col("source_endpoint") == "hydrometrie/referentiel/stations")
        .select(pl.col("code_station").alias("station_id"), "code_site")
        .join(canonical, on="station_id", how="semi")
    )
    expected = (
        associations.join(sites, on="code_site", how="inner", validate="m:1")
        .select("station_id", "surface_bv")
        .sort("station_id")
    )
    source = pl.read_parquet(catalogue / "station_metadata.parquet")
    actual = source.filter(
        (pl.col("attribute_role") == "drainage_area")
        & (pl.col("source_scope") == "hydrometrie/referentiel/sites")
        & (pl.col("source_field") == "surface_bv")
    ).sort("station_id")
    restored = pl.DataFrame(
        {
            "station_id": actual["station_id"],
            "surface_bv": pl.Series(
                [None if value is None else json.loads(value) for value in actual["source_value"]],
                dtype=pl.Float64,
            ),
        }
    )
    assert_frame_equal(restored, expected)
    assert set(actual["source_dtype"]) == {"Float64"}
    assert set(actual["source_unit"]) == {"km²"}
    assert actual["state"].to_list() == [
        "source_null" if value is None else "value" for value in expected["surface_bv"]
    ]
    missing = associations.join(sites.select("code_site"), on="code_site", how="anti")["station_id"]
    assert source.filter(
        pl.col("station_id").is_in(missing.implode()) & (pl.col("source_scope") == "hydrometrie/referentiel/sites")
    ).is_empty()


@pytest.mark.parametrize("fault", [None, "hydrometry_padding", "wrong_scope", "changed_scalar", "null_as_zero"])
def test_native_area_expectation_respects_france_endpoint_exposure(monkeypatch, tmp_path, fault):
    from rivretrieve._internal.station_metadata import SOURCE_METADATA_SCHEMA

    native = pl.DataFrame(
        {
            "code_station": ["H", "T"],
            "source_endpoint": ["hydrometrie/referentiel/stations", "temperature/station"],
            "superficie_topo": [None, 1.25],
            "superficie_reelle": [None, None],
        },
        schema={
            "code_station": pl.String,
            "source_endpoint": pl.String,
            "superficie_topo": pl.Float64,
            "superficie_reelle": pl.Float64,
        },
    )
    rows = [
        {
            "station_id": "H",
            "source_field": "surface_bv",
            "source_value": "2.5",
            "source_unit": "km²",
            "source_scope": "hydrometrie/referentiel/sites",
            "state": "value",
        },
        {
            "station_id": "T",
            "source_field": "superficie_topo",
            "source_value": "1.25",
            "source_scope": "temperature/station",
            "state": "value",
        },
        {
            "station_id": "T",
            "source_field": "superficie_reelle",
            "source_value": None,
            "source_scope": "temperature/station",
            "state": "source_null",
        },
    ]
    if fault == "hydrometry_padding":
        rows.append(
            {
                **rows[1],
                "station_id": "H",
                "source_value": None,
                "source_scope": "temperature/station",
                "state": "source_null",
            }
        )
    elif fault == "wrong_scope":
        rows[1]["source_scope"] = "hydrometrie/referentiel/stations"
    elif fault == "changed_scalar":
        rows[1]["source_value"] = "1.5"
    elif fault == "null_as_zero":
        rows[2].update(source_value="0.0", state="value")
    projection = pl.DataFrame(
        [
            {**row, "provider_id": "fr_hubeau", "attribute_role": "drainage_area", "source_dtype": "Float64"}
            for row in rows
        ],
        schema=SOURCE_METADATA_SCHEMA,
    )
    tables = {
        "native.parquet": native,
        "stations.parquet": pl.DataFrame({"station_id": ["H", "T"]}),
        "station_metadata.parquet": projection,
    }
    monkeypatch.setattr(pl, "read_parquet", lambda path: tables[Path(path).name].clone())
    if fault is None:
        test_projection_preserves_every_native_scalar("fr_hubeau", tmp_path)
    else:
        with pytest.raises(AssertionError):
            test_projection_preserves_every_native_scalar("fr_hubeau", tmp_path)
