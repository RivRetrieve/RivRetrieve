from __future__ import annotations

from tests._catalogue import provider_info

BULK_OBSERVATIONS_DESCRIPTION = "true: uncapped coalesced live requests; source and contract failures fail loud"


def test_ch_foen_provider_info_capabilities_are_declared() -> None:
    info = provider_info("ch_foen")

    assert info.live_stations is False
    assert info.live_products is False
    assert info.live_station_products is False
    assert info.bulk_observations == BULK_OBSERVATIONS_DESCRIPTION
