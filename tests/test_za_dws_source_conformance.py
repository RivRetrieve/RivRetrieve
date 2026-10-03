"""DWS catalogue-only conformance against retained publisher evidence."""

from datetime import date

import pytest

import rivretrieve as rr
from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
from rivretrieve._internal.providers.za_dws.declaration import declaration
from rivretrieve._internal.providers.za_dws.generate_catalogue import build_provider_info
from rivretrieve._internal.source_series import EvidenceState


def test_generated_metadata_does_not_advertise_observation_access() -> None:
    assert build_provider_info(date(2026, 8, 2))["bulk_observations"] == (
        "false: catalogue-only station discovery; observation retrieval is unavailable"
    )


def test_provenance_does_not_claim_runtime_observation_acquisition() -> None:
    from rivretrieve._internal.providers.za_dws.origins import build_acquisition_provenance

    provenance = build_acquisition_provenance()
    assert all(
        acquisition.instant_type != "runtime"
        for source in provenance.source_records
        for acquisition in source.acquisitions
    )


def test_catalogue_physics_follow_publisher_field_definitions() -> None:
    artifact = load_packaged_catalogue_artifact(declaration.catalogue)
    assert artifact.source_descriptions is not None
    expected = {
        "discharge_daily_mean": ("D AVG F/R", "discharge", "cubic metres/sec", "daily", "mean"),
        "discharge_instantaneous": ("COR.FLOW", "discharge", "cubic metres/sec", None, None),
        "stage_instantaneous": ("COR.LEVEL", "stage", "m", None, None),
    }
    for item in artifact.source_descriptions.descriptions:
        column, quantity, unit, frequency, statistic = expected[item.product_id]
        facts = item.facts[0]
        assert item.native_coordinate == column
        assert item.identity.published_id is None
        assert facts.quantity.value == quantity
        assert facts.source_unit.value == unit
        assert facts.frequency.value == frequency
        assert facts.statistic.value == statistic
        assert facts.time_zone.state is EvidenceState.NOT_ESTABLISHED
        assert facts.vertical_reference.state is EvidenceState.NOT_ESTABLISHED
        assert facts.day_definition.state is EvidenceState.NOT_ESTABLISHED


def test_variable_claims_are_scoped_to_recorded_station_and_route() -> None:
    artifact = load_packaged_catalogue_artifact(declaration.catalogue)
    claims = artifact.catalogue_claims
    assert claims is not None and claims.height == 3
    assert claims["station_id"].unique().to_list() == ["X3H001"]
    assert claims["published_id"].unique().to_list() == ["100.00"]
    assert claims["description"].unique().to_list() == ["Surface Water Level"]


@pytest.mark.parametrize("policy", ["raise", "warn", "ignore"])
@pytest.mark.parametrize("cache", ["bypass", "reuse", "refresh"])
def test_public_discovery_pick_and_fetch_refusal_are_offline(policy, cache, monkeypatch) -> None:
    import socket

    import polars.testing as pl_testing

    from rivretrieve._internal.issues import ObservationsUnavailableError

    def refuse_network(*args, **kwargs):
        pytest.fail("CatalogueOnly workflow attempted network access")

    monkeypatch.setattr(socket.socket, "connect", refuse_network)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse_network)
    selection = rr.find(provider="za_dws", station="X3H001", on_issue=policy)
    table = rr.series(selection)
    assert table.height == 3
    assert table["admission"].unique().to_list() == ["supported"]
    assert all(inventory.completeness.value == "incomplete" for inventory in selection.inventories)
    assert all(len(inventory.catalogue_claims) == 1 for inventory in selection.inventories)
    discharge = rr.pick(selection, quantity="discharge", on_issue=policy)
    assert rr.series(discharge).height == 2
    daily = rr.pick(discharge, frequency="daily", statistic="mean", on_issue=policy)
    assert rr.series(daily)["product_id"].to_list() == ["discharge_daily_mean"]
    direct = rr.find(
        provider="za_dws", station="X3H001", quantity="discharge", frequency="daily", statistic="mean", on_issue=policy
    )
    pl_testing.assert_frame_equal(rr.series(daily), rr.series(direct))
    assert rr.series(selection).height == 3
    for chosen in (selection, discharge, daily):
        with pytest.raises(ObservationsUnavailableError, match="za_dws"):
            rr.fetch(chosen, start="2020-01-01", end="2020-01-02", cache=cache, receipts=True, on_issue=policy)
