from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError
from datetime import date
from typing import Any

import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve as rr
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.registry import UnknownProviderError
from rivretrieve._internal.selection import (
    SELECTION_FRAME_SCHEMA,
    UnknownProductError,
    UnknownStationError,
)


def _keys(selection: object) -> tuple[tuple[str, str, str], ...]:
    return tuple((row.provider_id, row.station_id, row.product_id) for row in selection.series)  # type: ignore[attr-defined]


def _expected_one_row_frame() -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "provider_id": "usgs_nwis",
                "station_id": "01646500",
                "product_id": "discharge_daily_mean",
                "latitude": 38.94977778,
                "longitude": -77.12763889,
                "crs": "EPSG:4269",
                "observed_property": "discharge",
                "frequency": "daily",
                "statistic": "mean",
                "period_type": "interval",
                "period_anchor": "start",
                "unit": "m3/s",
                "native_id": "00060:00003",
                "availability": "available",
                "availability_reason": None,
                "published_record_start_date": date(1930, 3, 1),
                "published_record_end_date": date(2026, 7, 31),
                "last_catalogue_check": date(2026, 8, 2),
            }
        ],
        schema=SELECTION_FRAME_SCHEMA,
    )


def test_selection_is_immutable_method_free_and_series_grained() -> None:
    selection = rr.find(provider="usgs_nwis", station="01646500")
    assert _keys(selection) == (
        ("usgs_nwis", "01646500", "discharge_daily_mean"),
        ("usgs_nwis", "01646500", "discharge_instantaneous"),
        ("usgs_nwis", "01646500", "stage_instantaneous"),
    )
    with pytest.raises(FrozenInstanceError):
        selection.series = ()
    with pytest.raises(FrozenInstanceError):
        selection.series[0].product_id = "stage_daily_mean"
    assert {name for name in dir(selection) if not name.startswith("_") and callable(getattr(selection, name))} == set()


def test_find_validates_unknown_vocabulary_independent_of_argument_count() -> None:
    calls = (
        lambda: rr.find(product="stage_daily_mea"),
        lambda: rr.find(provider="usgs_nwis", product="stage_daily_mea"),
        lambda: rr.find(provider="usgs_nwis", station="01646500", product="stage_daily_mea"),
    )
    for call in calls:
        with pytest.raises(UnknownProductError) as exc_info:
            call()
        assert str(exc_info.value) == "Canonical product is not registered: 'stage_daily_mea'"


def test_find_near_miss_station_raises_without_correction() -> None:
    with pytest.raises(UnknownStationError) as exc_info:
        rr.find(provider="usgs_nwis", station="0164650")
    assert str(exc_info.value) == "Station is not registered for provider 'usgs_nwis': '0164650'"


def test_find_unavailable_edge_returns_reason_listing_published_products() -> None:
    selection = rr.find(provider="usgs_nwis", station="01646500", product="stage_daily_mean")
    assert selection.series == ()
    assert selection.empty_reason.code == "no_catalogue_edge"
    assert selection.empty_reason.provider_ids == ("usgs_nwis",)
    assert selection.empty_reason.station_ids == ("01646500",)
    assert selection.empty_reason.product_ids == ("stage_daily_mean",)
    assert selection.empty_reason.published_products == (
        "discharge_daily_mean",
        "discharge_instantaneous",
        "stage_instantaneous",
    )
    assert rr.as_frame(selection).height == 0
    assert rr.as_frame(selection).schema == SELECTION_FRAME_SCHEMA
    assert str(selection) == (
        "provider_id | station_id | product_id\n"
        "<empty>\n"
        "empty_reason.code=no_catalogue_edge\n"
        "empty_reason.provider_ids=usgs_nwis\n"
        "empty_reason.station_ids=01646500\n"
        "empty_reason.product_ids=stage_daily_mean\n"
        "empty_reason.published_products="
        "discharge_daily_mean,discharge_instantaneous,stage_instantaneous"
    )
    assert repr(selection) == str(selection)


def test_find_includes_unknown_edges_for_czech_and_excludes_unavailable_usgs_rows() -> None:
    czech = rr.as_frame(rr.find(provider="cz_chmi", product="discharge_daily_mean"))
    usgs = rr.as_frame(rr.find(provider="usgs_nwis", product="discharge_daily_mean"))
    assert czech.height == 831
    assert czech.height > 0
    assert czech["availability"].cast(pl.Utf8).unique().sort().to_list() == ["unknown"]
    assert usgs.height == 24_447
    assert usgs.height > 0
    assert usgs["availability"].cast(pl.Utf8).unique().sort().to_list() == ["available"]


def test_find_scopes_duplicate_bare_station_ids_by_provider() -> None:
    assert _keys(rr.find(station="01010000")) == (
        ("usgs_nwis", "01010000", "discharge_daily_mean"),
        ("usgs_nwis", "01010000", "discharge_instantaneous"),
        ("usgs_nwis", "01010000", "stage_instantaneous"),
    )
    with pytest.raises(UnknownStationError, match="Station is not registered"):
        rr.find(provider="fr_hubeau", station="01010000")
    assert _keys(rr.find(provider="usgs_nwis", station="01010000")) == (
        ("usgs_nwis", "01010000", "discharge_daily_mean"),
        ("usgs_nwis", "01010000", "discharge_instantaneous"),
        ("usgs_nwis", "01010000", "stage_instantaneous"),
    )


def test_pick_validates_catalogue_scope_not_input_rows() -> None:
    base = rr.find(provider="usgs_nwis", product="stage_daily_mean")
    result = rr.pick(base, station="01646500")
    assert base.series
    assert result.series == ()
    assert result.empty_reason.code == "not_in_selection"
    assert result.empty_reason.provider_ids == ()
    assert result.empty_reason.station_ids == ("01646500",)
    assert result.empty_reason.product_ids == ()
    assert result.empty_reason.published_products == ()


def test_pick_preserves_an_existing_empty_reason() -> None:
    selection = rr.find(provider="usgs_nwis", station="01646500", product="stage_daily_mean")
    picked = rr.pick(selection, provider="usgs_nwis")
    assert picked.empty_reason is selection.empty_reason
    assert str(picked) == str(selection)


@pytest.mark.parametrize(
    ("kwargs", "error_type", "message"),
    [
        (
            {"provider": ["usgs_nwis", "missing_provider"]},
            UnknownProviderError,
            "Provider is not registered: missing_provider",
        ),
        (
            {"product": ["discharge_daily_mean", "stage_daily_mea"]},
            UnknownProductError,
            "Canonical product is not registered: 'stage_daily_mea'",
        ),
        (
            {"provider": "usgs_nwis", "station": ["01646500", "0164650"]},
            UnknownStationError,
            "Station is not registered for provider 'usgs_nwis': '0164650'",
        ),
    ],
)
def test_pick_rejects_vocabulary_lists_atomically(
    kwargs: dict[str, Any], error_type: type[Exception], message: str
) -> None:
    base = rr.find(provider="usgs_nwis")
    before = base
    before_keys = _keys(base)
    with pytest.raises(error_type) as exc_info:
        rr.pick(base, **kwargs)
    assert str(exc_info.value) == message
    assert base == before
    assert _keys(base) == before_keys


def test_as_frame_is_deterministic_and_from_frame_round_trips() -> None:
    selection = rr.find(provider="usgs_nwis", station="01646500", product="discharge_daily_mean")
    expected = _expected_one_row_frame()
    first = rr.as_frame(selection)
    second = rr.as_frame(selection)
    pl_testing.assert_frame_equal(first, second, check_exact=True)
    pl_testing.assert_frame_equal(first, expected, check_exact=True)
    pl_testing.assert_frame_equal(second, expected, check_exact=True)
    assert first is not second
    assert rr.from_frame(first) == selection
    assert str(selection) == ("provider_id | station_id | product_id\nusgs_nwis | 01646500 | discharge_daily_mean")
    assert repr(selection) == str(selection)
    first = first.drop("unit")
    assert "unit" not in first.columns
    pl_testing.assert_frame_equal(rr.as_frame(selection), expected, check_exact=True)


def test_from_frame_parses_identity_and_rebuilds_catalogue_metadata() -> None:
    frame = pl.DataFrame(
        {
            "provider_id": ["usgs_nwis"],
            "station_id": ["01646500"],
            "product_id": ["discharge_daily_mean"],
            "ignored": ["caller value"],
        }
    )
    actual = rr.as_frame(rr.from_frame(frame))
    pl_testing.assert_frame_equal(actual, _expected_one_row_frame(), check_exact=True)
    assert "ignored" not in actual.columns


def test_from_frame_rejects_malformed_or_absent_edges() -> None:
    with pytest.raises(FatalContractError) as missing_exc:
        rr.from_frame(pl.DataFrame())
    assert str(missing_exc.value) == (
        "Selection frame is missing required columns: provider_id, station_id, product_id"
    )

    valid_identity = pl.DataFrame(
        {
            "provider_id": ["usgs_nwis"],
            "station_id": ["01646500"],
            "product_id": ["discharge_daily_mean"],
        }
    )
    with pytest.raises(FatalContractError) as duplicate_exc:
        rr.from_frame(pl.concat([valid_identity, valid_identity]))
    assert str(duplicate_exc.value) == (
        "Selection frame contains duplicate series keys: provider_id, station_id, product_id"
    )

    absent_identity = valid_identity.with_columns(product_id=pl.lit("stage_daily_mean"))
    with pytest.raises(FatalContractError) as absent_exc:
        rr.from_frame(absent_identity)
    assert str(absent_exc.value) == (
        "Selection frame contains no catalogue edge: ('usgs_nwis', '01646500', 'stage_daily_mean')"
    )

    empty = rr.from_frame(pl.DataFrame(schema={"provider_id": pl.Utf8, "station_id": pl.Utf8, "product_id": pl.Utf8}))
    assert empty.series == ()
    assert empty.empty_reason.code == "empty_frame"
    assert empty.empty_reason.provider_ids == ()
    assert empty.empty_reason.station_ids == ()
    assert empty.empty_reason.product_ids == ()
    assert empty.empty_reason.published_products == ()


def test_selection_function_signatures_exclude_unshipped_capabilities() -> None:
    find_parameters = inspect.signature(rr.find).parameters
    pick_parameters = inspect.signature(rr.pick).parameters
    as_frame_parameters = inspect.signature(rr.as_frame).parameters
    from_frame_parameters = inspect.signature(rr.from_frame).parameters
    assert tuple(find_parameters) == ("provider", "station", "product")
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY and parameter.default is None
        for parameter in find_parameters.values()
    )
    assert tuple(pick_parameters) == ("selection", "provider", "station", "product")
    assert pick_parameters["selection"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert pick_parameters["selection"].default is inspect.Parameter.empty
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY and parameter.default is None
        for parameter in tuple(pick_parameters.values())[1:]
    )
    assert tuple(as_frame_parameters) == ("selection",)
    assert tuple(from_frame_parameters) == ("frame",)
    forbidden = {
        "source",
        "live",
        "bbox",
        "bounding_box",
        "record_covers",
        "start",
        "end",
        "window",
        "query",
        "predicate",
    }
    all_parameters = set(find_parameters) | set(pick_parameters) | set(as_frame_parameters) | set(from_frame_parameters)
    assert forbidden.isdisjoint(all_parameters)
