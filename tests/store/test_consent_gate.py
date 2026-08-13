from collections.abc import Callable
from pathlib import Path

from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.observations import ReceiptMode
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.ca_eccc import module as ca_module
from rivretrieve._internal.providers.ca_eccc.config import config
from rivretrieve._internal.registry import ProviderRegistry
from rivretrieve._internal.store import StoreRoot


def test_absent_store_fetch_returns_download_issue_without_creating_cache(
    tmp_path: Path,
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    registry = ProviderRegistry()
    store = StoreRoot(tmp_path / "cache" / "ca_eccc" / "store")
    handle = registry.register(
        "ca_eccc",
        stub_packaged_catalogue_artifact("ca_eccc"),
        provider_module=ca_module,
        bulk_config=config,
        observation_store=store,
    )

    result = handle.observations(
        stations="01AA001",
        products=ProductId("discharge_daily_mean"),
        start="2020-01-01",
        end="2020-01-02",
        on_issue="ignore",
        receipts=ReceiptMode.OMIT,
    )

    assert result.data.is_empty()
    assert [issue.code for issue in result.issues] == ["bulk.store_missing"]
    assert 'rivretrieve.download("ca_eccc")' in result.issues[0].message
    assert not (tmp_path / "cache").exists()
