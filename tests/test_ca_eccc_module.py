import rivretrieve as rr
from rivretrieve._internal.providers.ca_eccc import module


def test_ca_eccc_catalogue_facade_has_no_provider_request_stages() -> None:
    assert "ca_eccc" in rr.providers()
    assert module.info().catalogue_version == "2026-08-02"
    assert len(module.stations().data) == 8057
    assert not hasattr(module, "fetch")
    assert not hasattr(module, "parse")
    assert not hasattr(module, "cache_status")
    assert not hasattr(module, "refresh_cache")
