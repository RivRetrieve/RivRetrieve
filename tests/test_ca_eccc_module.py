import rivretrieve as rr
from tests._catalogue import catalogue_reader, provider_info


def test_ca_eccc_catalogue_has_no_live_request_stages() -> None:
    assert "ca_eccc" in rr.providers()
    assert provider_info("ca_eccc").catalogue_version == "2026-08-02"
    assert len(catalogue_reader("ca_eccc").read_stations().data) == 8057
