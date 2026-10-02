from pathlib import Path

import polars as pl
import pytest

from rivretrieve._internal.catalogues.artifact import CorruptCatalogArtifactError, load_packaged_catalogue_artifact
from rivretrieve._internal.catalogues.source_series import catalogue_series
from rivretrieve._internal.source_series import InventoryCompleteness, SeriesScope, admission


def test_old_catalogue_refused_before_parquet_interpretation(tmp_path: Path):
    (tmp_path / "provider.json").write_text("{}")
    for name in ("products", "stations", "station_products"):
        (tmp_path / f"{name}.parquet").write_bytes(b"not parquet")
    with pytest.raises(CorruptCatalogArtifactError, match="format.*rebuild"):
        load_packaged_catalogue_artifact(tmp_path)


BASE = Path("src/rivretrieve/_internal/providers")


@pytest.mark.parametrize("provider", [p.parent.parent.name for p in BASE.glob("*/catalogue/provider.json")])
def test_packaged_descriptions_are_closed_and_supported_inventory_is_not_exhaustive(provider):
    artifact = load_packaged_catalogue_artifact(BASE / provider / "catalogue")
    assert artifact.source_descriptions is not None
    if artifact.stations.is_empty():
        return
    station = artifact.stations["station_id"][0]
    series, inventory = catalogue_series(artifact, scope=SeriesScope(station_ids=(station,)))
    assert all(item.station_id == station for item in series)
    assert all(item.completeness == InventoryCompleteness.INCOMPLETE for item in inventory)
    assert len({item.series_id for item in series}) == len(series)


def test_nve_catalogue_preserves_versions_and_per_resolution_statistic():
    artifact = load_packaged_catalogue_artifact(BASE / "no_nve/catalogue")
    series, inventory = catalogue_series(
        artifact, scope=SeriesScope(station_ids=("1.46.0",), product_ids=("stage_daily_mean",))
    )
    facts = {item.identity.published_id: item.facts[0] for item in series}
    assert facts["1"].statistic.value == "mean"
    assert facts["2"].statistic.value == "instantaneous"
    assert all(admission(item).status == "supported" for item in facts.values())
    assert inventory[0].completeness == InventoryCompleteness.INCOMPLETE


def test_swiss_native_units_and_references_remain_independent():
    artifact = load_packaged_catalogue_artifact(BASE / "ch_foen/catalogue")
    series, _ = catalogue_series(artifact, scope=SeriesScope(station_ids=("2251",)))
    facts = {item.identity.published_id: item.facts[0] for item in series}
    assert facts["flow"].source_unit.value == "m3/s"
    assert facts["flow_ls"].source_unit.value == "l/s"
    assert admission(facts["flow_ls"]).factor == 0.001
    assert facts["height"].vertical_reference.value == "above_sea_level"
    assert facts["height_abs"].vertical_reference.value is None
    assert all(item.frequency.value is None for item in facts.values())


def test_ana_daily_alternatives_both_remain_quantity_matches():
    artifact = load_packaged_catalogue_artifact(BASE / "br_ana/catalogue")
    series, _ = catalogue_series(artifact, scope=SeriesScope(station_ids=("15400000",)))
    daily = [s for s in series if s.facts[0].quantity.value == "discharge" and s.facts[0].frequency.value == "daily"]
    assert {s.variant for s in daily} == {"bruto", "consistido"}
    assert all(s.facts[0].statistic.value == "mean" for s in daily)
    assert all(s.facts[0].day_definition.value is None for s in daily)


def test_scoped_materialization_constructs_only_selected_coordinates(monkeypatch):
    import rivretrieve._internal.catalogues.source_series as materializer

    artifact = load_packaged_catalogue_artifact(BASE / "ch_foen/catalogue")
    original = materializer.SourceSeries
    constructed = []

    def trace_construction(**kwargs):
        constructed.append((kwargs["station_id"], kwargs["product_id"]))
        return original(**kwargs)

    monkeypatch.setattr(materializer, "SourceSeries", trace_construction)
    selected, _ = materializer.catalogue_series(
        artifact, scope=SeriesScope(station_ids=("2251",), product_ids=("discharge_reported",))
    )
    assert constructed == [("2251", "discharge_reported")] * 2
    assert {series.identity.published_id for series in selected} == {"flow", "flow_ls"}


@pytest.mark.parametrize("provider", ["no_nve", "br_ana", "ch_foen", "ca_eccc", "pl_imgw", "usgs_nwis"])
def test_catalogue_fact_identity_includes_exact_facts_and_evidence(provider):
    from rivretrieve._internal.source_series import stable_id

    artifact = load_packaged_catalogue_artifact(BASE / provider / "catalogue")
    assert artifact.source_descriptions is not None
    for description in artifact.source_descriptions.descriptions:
        for facts in description.facts:
            assert facts.facts_id == stable_id(facts.model_dump_json(exclude={"facts_id"}))


def test_physical_predicates_do_not_rewrite_acquired_catalogue_inventory():
    from rivretrieve._internal.source_series import PhysicalPredicate

    artifact = load_packaged_catalogue_artifact(BASE / "no_nve/catalogue")
    routing = SeriesScope(station_ids=("1.46.0",), product_ids=("stage_daily_mean",))
    _, broad = catalogue_series(artifact, scope=routing)
    _, precise = catalogue_series(
        artifact,
        scope=routing.model_copy(
            update={
                "predicates": (PhysicalPredicate(field="statistic", value="mean"),),
            }
        ),
    )
    assert precise == broad


def test_modern_usgs_identities_survive_public_discovery_and_bundle_without_legacy_aliases(
    retained_evidence_root: Path,
):
    import rivretrieve as rr

    selection = rr.find(
        provider="usgs_nwis", station="02196000", quantity="discharge", frequency="daily", statistic="mean"
    )
    restored = rr.from_bundle(rr.to_bundle(selection))
    assert restored.known_series == selection.known_series
    assert {item.identity.published_id for item in restored.series} == {
        "0df18b246e8f48ec8e6547a92070e94a",
        "4d186669708e4dc18f84d271efb953a1",
    }
    assert all(item.identity.description is None for item in restored.series)
    assert all(item.identity.namespace == "USGS.WaterData.time_series_id" for item in restored.series)
    assert not any(inventory.catalogue_claims for inventory in restored.inventories)
    legacy = pl.read_parquet(
        retained_evidence_root / "research/usgs-modern-coverage/legacy-catalogue/series_claims.parquet"
    )
    claims = legacy.filter((pl.col("station_id") == "02196000") & (pl.col("product_id") == "discharge_daily_mean"))
    assert set(claims.select("published_id", "description").iter_rows()) == {("126801", ""), ("126805", "[(2)]")}
    assert set(claims["namespace"]) == {"NWIS.ts_id"}


def test_catalogue_claim_coordinate_names_are_validated_at_artifact_boundary(retained_evidence_root: Path):
    import polars as pl

    from rivretrieve._internal.catalogues.artifact import packaged_catalogue_artifact_from_components

    artifact = load_packaged_catalogue_artifact(BASE / "usgs_nwis/catalogue")
    # Authored corruption of an independently retained historical claim carrier.
    claims = (
        pl.read_parquet(retained_evidence_root / "research/usgs-modern-coverage/legacy-catalogue/series_claims.parquet")
        .head(1)
        .with_columns(
            pl.lit(
                [{"name": "", "value": "00060"}], dtype=pl.List(pl.Struct({"name": pl.String, "value": pl.String}))
            ).alias("native_coordinates")
        )
    )
    with pytest.raises(CorruptCatalogArtifactError, match="coordinate names"):
        packaged_catalogue_artifact_from_components(
            artifact.provider_info,
            artifact.products,
            artifact.stations,
            artifact.station_products,
            acquisition_provenance=artifact.acquisition_provenance,
            source_descriptions=artifact.source_descriptions,
            catalogue_claims=claims,
            withheld_rows_already_applied=True,
        )


def test_changed_catalogue_claims_change_snapshot_identity_at_same_check_date(retained_evidence_root: Path):
    from dataclasses import replace

    import polars as pl

    artifact = load_packaged_catalogue_artifact(BASE / "usgs_nwis/catalogue")
    # Exercise generic independent-claim inventory identity using archived source bytes,
    # not by attaching old numeric claims to modern publisher series IDs.
    artifact = replace(
        artifact,
        catalogue_claims=pl.read_parquet(
            retained_evidence_root / "research/usgs-modern-coverage/legacy-catalogue/series_claims.parquet"
        ),
    )
    scope = SeriesScope(station_ids=("02196000",), product_ids=("discharge_daily_mean",))
    _, original = catalogue_series(artifact, scope=scope)
    changed = replace(artifact, catalogue_claims=artifact.catalogue_claims.filter(pl.col("published_id") != "126805"))
    _, reduced = catalogue_series(changed, scope=scope)
    assert original[0].catalogue_check_date == reduced[0].catalogue_check_date
    assert original[0].members == reduced[0].members == ()
    assert original[0].snapshot_id != reduced[0].snapshot_id


def test_usgs_instantaneous_support_does_not_establish_sampling_frequency():
    artifact = load_packaged_catalogue_artifact(BASE / "usgs_nwis/catalogue")
    series, _ = catalogue_series(
        artifact, scope=SeriesScope(station_ids=("09380000",), product_ids=("discharge_instantaneous",))
    )
    assert len(series) == 1
    assert artifact.products.filter(pl.col("product_id") == "discharge_instantaneous")["frequency"].item() == "unknown"
    assert series[0].facts[0].frequency.value is None
    assert series[0].facts[0].frequency.state.value == "source_silent"
    assert series[0].facts[0].temporal_support.value == "instantaneous"
