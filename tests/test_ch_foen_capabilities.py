from __future__ import annotations

from rivretrieve._internal.providers.ch_foen import module as ch_foen_module

BULK_OBSERVATIONS_DESCRIPTION = (
    "true: 366-day window decomposition with stitched N x M station-product requests; partial failures reported "
    "as recoverable issues"
)


def test_ch_foen_provider_info_capabilities_are_declared() -> None:
    provider_info = ch_foen_module.info()

    assert provider_info.live_stations is False
    assert provider_info.live_products is False
    assert provider_info.live_station_products is False
    assert provider_info.bulk_observations == BULK_OBSERVATIONS_DESCRIPTION
