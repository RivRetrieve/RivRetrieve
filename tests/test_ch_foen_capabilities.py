from __future__ import annotations

import pytest

import rivretrieve as rr
from rivretrieve._internal.issues import IssuePolicyError


def test_ch_foen_provider_info_capabilities_are_declared_false() -> None:
    provider_info = rr.provider("ch_foen").info()

    assert provider_info.live_stations is False
    assert provider_info.live_products is False
    assert provider_info.live_station_products is False
    assert provider_info.bulk_observations == "false"


def test_ch_foen_live_products_unsupported_uses_m2_routing() -> None:
    handle = rr.provider("ch_foen")

    with pytest.warns(RuntimeWarning, match="does not support live catalogue"):
        warn_result = handle.products(source="live", on_issue="warn")
    assert warn_result.data.is_empty()
    assert warn_result.issues[0].code == "live_catalogue_unsupported"

    with pytest.raises(IssuePolicyError):
        handle.products(source="live", on_issue="raise")

    ignore_result = handle.products(source="live", on_issue="ignore")
    assert ignore_result.data.is_empty()
    assert ignore_result.issues[0].code == "live_catalogue_unsupported"


def test_ch_foen_live_stations_unsupported_uses_m2_routing() -> None:
    handle = rr.provider("ch_foen")

    with pytest.warns(RuntimeWarning, match="does not support live catalogue"):
        warn_result = handle.stations(source="live", on_issue="warn")
    assert warn_result.data.is_empty()
    assert warn_result.issues[0].code == "live_catalogue_unsupported"

    with pytest.raises(IssuePolicyError):
        handle.stations(source="live", on_issue="raise")

    ignore_result = handle.stations(source="live", on_issue="ignore")
    assert ignore_result.data.is_empty()
    assert ignore_result.issues[0].code == "live_catalogue_unsupported"


def test_ch_foen_live_station_products_unsupported_uses_m2_routing() -> None:
    handle = rr.provider("ch_foen")

    with pytest.warns(RuntimeWarning, match="does not support live catalogue"):
        warn_result = handle.station_products(source="live", on_issue="warn")
    assert warn_result.data.is_empty()
    assert warn_result.issues[0].code == "live_catalogue_unsupported"

    with pytest.raises(IssuePolicyError):
        handle.station_products(source="live", on_issue="raise")

    ignore_result = handle.station_products(source="live", on_issue="ignore")
    assert ignore_result.data.is_empty()
    assert ignore_result.issues[0].code == "live_catalogue_unsupported"
