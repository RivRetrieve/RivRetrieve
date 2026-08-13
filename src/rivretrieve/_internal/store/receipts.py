"""store_excerpt : StoreReadResult → StoreExcerptReceipt (faithful)."""

from __future__ import annotations

from io import BytesIO

from rivretrieve._internal.engine import SourceCallOrigin, SourceQuery, UnknownOriginFact
from rivretrieve._internal.observations import ReceiptAuthorship, StoreExcerptReceipt
from rivretrieve._internal.store.reader import StoreReadResult


def encode_store_excerpt(read: StoreReadResult) -> StoreExcerptReceipt:
    """Faithfully re-encode exactly the physical rows selected by the reader."""
    content = BytesIO()
    read.physical_rows.write_parquet(content)
    return StoreExcerptReceipt(
        content=content.getvalue(),
        origin=SourceCallOrigin(
            url=UnknownOriginFact(),
            request_parameters=UnknownOriginFact(),
            status_code=UnknownOriginFact(),
            retrieved_at=UnknownOriginFact(),
            content_type="application/vnd.apache.parquet",
            source_path=str(read.store),
            query=SourceQuery(
                statement=read.optimized_plan,
                parameters=(),
            ),
        ),
        authorship=ReceiptAuthorship.STORE_EXCERPT,
        store_path=read.store,
        executed_query=read.executed_query,
        format_version=read.manifest.format_version,
        source_vintage=read.manifest.source_vintage,
    )
