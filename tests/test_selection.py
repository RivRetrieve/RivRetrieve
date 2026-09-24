"""Public selection contracts for physical facts, immutable scope and durable evidence."""

from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError

import polars as pl
import polars.testing as pl_testing
import pytest
from pydantic import ValidationError

import rivretrieve as rr
from rivretrieve._internal.registry import UnknownProviderError
from rivretrieve._internal.selection import UnknownStationError, _station_frame
from rivretrieve._internal.source_series import InventoryCompleteness, RestrictionKind


def _keys(selection):
    return {(item.provider_id, item.station_id, item.product_id) for item in selection.series}


def test_selection_is_immutable_and_retains_all_matching_intent() -> None:
    selection = rr.find(provider="usgs_nwis", station="01646500")
    assert _keys(selection) == {
        ("usgs_nwis", "01646500", "discharge_daily_mean"),
        ("usgs_nwis", "01646500", "discharge_instantaneous"),
        ("usgs_nwis", "01646500", "stage_instantaneous"),
    }
    assert selection.scope.restriction is RestrictionKind.ALL
    with pytest.raises(FrozenInstanceError):
        selection.known_series = ()
    with pytest.raises(ValidationError):
        selection.series[0].product_id = "stage_daily_mean"


@pytest.mark.parametrize("extra", [{}, {"provider": "usgs_nwis"}, {"provider": "usgs_nwis", "station": "01646500"}])
def test_find_rejects_removed_product_keyword(extra) -> None:
    with pytest.raises(TypeError, match="product"):
        rr.find(product="stage_daily_mea", **extra)


def test_find_rejects_near_miss_station_without_correction() -> None:
    with pytest.raises(UnknownStationError, match="0164650"):
        rr.find(provider="usgs_nwis", station="0164650")


def test_unlisted_edge_does_not_claim_exhaustive_absence() -> None:
    selection = rr.find(provider="usgs_nwis", station="01646500", quantity="stage", frequency="daily", statistic="mean")
    assert selection.series == ()
    assert selection.empty_reason.code == "unresolved_inventory"
    assert selection.scope.station_ids == ("01646500",)
    assert selection.scope.product_ids == ()
    assert {(item.field, item.value) for item in selection.scope.predicates} == {
        ("quantity", "stage"),
        ("frequency", "daily"),
        ("statistic", "mean"),
    }
    assert rr.series(selection).is_empty()


def test_static_catalogue_inventory_is_not_current_exhaustive_discovery() -> None:
    selected = rr.find(provider="usgs_nwis", station="01646500", quantity="discharge")
    assert selected.series
    assert selected.inventories
    assert all(item.completeness is not InventoryCompleteness.COMPLETE for item in selected.inventories)
    assert all(item.evidence and item.reason for item in selected.inventories)


def test_duplicate_bare_station_ids_keep_provider_scope() -> None:
    all_providers = rr.find(station="01010000")
    assert {item.provider_id for item in all_providers.series} == {"fr_hubeau", "usgs_nwis"}
    for provider in ("fr_hubeau", "usgs_nwis"):
        restricted = rr.find(provider=provider, station="01010000")
        assert {item.provider_id for item in restricted.series} == {provider}
        assert _keys(restricted).issubset(_keys(all_providers))


@pytest.mark.parametrize(
    ("filters", "error"),
    [
        ({"provider": ["usgs_nwis", "missing_provider"]}, UnknownProviderError),
        ({"quantity": 42}, ValidationError),
        ({"provider": "usgs_nwis", "station": ["01646500", "0164650"]}, UnknownStationError),
    ],
)
def test_invalid_pick_lists_fail_without_mutating_original(filters, error) -> None:
    selection = rr.find(provider="usgs_nwis", station="01646500")
    before = rr.to_bundle(selection)
    with pytest.raises(error):
        rr.pick(selection, **filters)
    assert rr.from_bundle(before).scope == selection.scope
    pl_testing.assert_frame_equal(rr.series(rr.from_bundle(before)), rr.series(selection))


def test_inspection_does_not_mutate_or_supply_scientific_import_evidence() -> None:
    selection = rr.find(
        provider="usgs_nwis", station="01646500", quantity="discharge", frequency="daily", statistic="mean"
    )
    first = rr.as_frame(selection)
    second = rr.as_frame(selection)
    pl_testing.assert_frame_equal(first, second)
    assert first is not second
    first = first.with_columns(pl.lit("invented").alias("unit"))
    assert first["unit"].to_list() != rr.as_frame(selection)["unit"].to_list()
    with pytest.raises(ValueError, match="bundle"):
        rr.from_frame(first)
    restored = rr.from_bundle(rr.to_bundle(selection))
    pl_testing.assert_frame_equal(rr.series(restored), second)
    assert restored.scope == selection.scope
    assert restored.known_series == selection.known_series


def test_station_geometry_remains_separate_from_series_physics() -> None:
    selection = rr.find(provider="usgs_nwis", station="01646500")
    frame = _station_frame(selection)
    expected = pl.DataFrame(
        {
            "provider_id": ["usgs_nwis"],
            "station_id": ["01646500"],
            "latitude": [38.94977778],
            "longitude": [-77.12763889],
            "crs": ["EPSG:4269"],
        }
    )
    pl_testing.assert_frame_equal(frame, expected)


@pytest.mark.parametrize(
    "frame",
    [
        pl.DataFrame(),
        pl.DataFrame(
            {"provider_id": ["usgs_nwis"], "station_id": ["01646500"], "product_id": ["discharge_daily_mean"]}
        ),
    ],
)
def test_old_frames_are_refused_before_catalogue_reconstruction(frame) -> None:
    with pytest.raises(ValueError, match="versioned export bundle"):
        rr.from_frame(frame)


def test_selection_signatures_expose_physical_filters_but_no_hidden_live_discovery() -> None:
    find_parameters = inspect.signature(rr.find).parameters
    pick_parameters = inspect.signature(rr.pick).parameters
    assert {"quantity", "frequency", "statistic", "variant", "on_issue"}.issubset(find_parameters)
    assert {"quantity", "frequency", "statistic", "variant", "on_issue"}.issubset(pick_parameters)
    assert all(parameter.kind is inspect.Parameter.KEYWORD_ONLY for parameter in find_parameters.values())
    assert {"product", "access_product", "live", "start", "end", "window", "bbox"}.isdisjoint(
        set(find_parameters) | set(pick_parameters)
    )
