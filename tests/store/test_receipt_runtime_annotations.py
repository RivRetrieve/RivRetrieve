"""receipt annotations : StoreExcerptReceipt → RuntimeDomainTypes."""

from pathlib import Path
from typing import get_type_hints

from rivretrieve._internal.observations import StoreExcerptReceipt
from rivretrieve._internal.store.reader import ExecutedStoreQuery
from rivretrieve._internal.store.validation import StoreRoot


def test_store_excerpt_receipt_runtime_annotations_resolve_to_domain_types() -> None:
    hints = get_type_hints(StoreExcerptReceipt)

    assert hints["store_path"] is StoreRoot
    assert hints["executed_query"] is ExecutedStoreQuery
    assert hints["store_path"] is not Path
    assert hints["executed_query"] is not object
