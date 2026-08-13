"""store receipt : StoreFetch × ReceiptRequest → FaithfulStoreExcerpt."""

from __future__ import annotations

import sqlite3
import zipfile
from datetime import UTC, date, datetime
from io import BytesIO
from pathlib import Path

import polars as pl

from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
from rivretrieve._internal.observations import ReceiptAuthorship, ReceiptMode, StoreExcerptReceipt
from rivretrieve._internal.providers.ca_eccc import module
from rivretrieve._internal.providers.ca_eccc.bulk import HYDAT_SOURCE_SCHEMAS, HydatCompileRequest, compile_hydat
from rivretrieve._internal.registry import ProviderRegistry
from rivretrieve._internal.store import StoreRoot


def _hydat(path: Path) -> None:
    connection = sqlite3.connect(path)
    for table, schema in HYDAT_SOURCE_SCHEMAS.items():
        connection.execute(f"CREATE TABLE {table} (" + ",".join(f'"{name}" {kind}' for name, kind in schema) + ")")
        row = {name: None for name, _kind in schema}
        row.update(STATION_NUMBER="02GA010", YEAR=2020, MONTH=1, FULL_MONTH=0, NO_DAYS=1)
        prefix = "FLOW" if table == "DLY_FLOWS" else "LEVEL"
        row[f"{prefix}1"] = 12.4 if table == "DLY_FLOWS" else 1.2
        row[f"{prefix}_SYMBOL1"] = "E"
        connection.execute(
            f"INSERT INTO {table} VALUES (" + ",".join("?" for _ in schema) + ")",
            tuple(row[name] for name, _kind in schema),
        )
    connection.commit()
    connection.close()


def test_ca_eccc_fetch_retains_a_faithful_store_excerpt(tmp_path: Path) -> None:
    sqlite_artifact = tmp_path / "Hydat.sqlite3"
    publisher_artifact = tmp_path / "Hydat_sqlite3_20240601.zip"
    store = StoreRoot(tmp_path / "store")
    _hydat(sqlite_artifact)
    with zipfile.ZipFile(publisher_artifact, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(sqlite_artifact, "Hydat.sqlite3")
    sqlite_artifact.unlink()
    compile_hydat(
        HydatCompileRequest(
            publisher_artifact=publisher_artifact,
            destination=store,
            publisher_url="https://collaboration.cmc.ec.gc.ca/Hydat.sqlite3",
            source_vintage=date(2024, 6, 1),
            built_at=datetime(2026, 8, 11, tzinfo=UTC),
            compiler_version="0.1.49",
        )
    )
    registry = ProviderRegistry()
    registry.register(
        "ca_eccc",
        load_packaged_catalogue_artifact(module._CATALOGUE_PATH, on_issue="raise"),
        provider_module=module,
        bulk_config=module.config,
        observation_store=store,
    )

    result = registry.get("ca_eccc").observations(
        stations="02GA010",
        products="discharge_daily_mean",
        start="2020-01-01",
        end="2020-01-01",
        on_issue="ignore",
        receipts=ReceiptMode.INCLUDE,
    )

    assert len(result.receipts.entries) == 1
    receipt = result.receipts.entries[0]
    assert isinstance(receipt, StoreExcerptReceipt)
    assert receipt.authorship is ReceiptAuthorship.STORE_EXCERPT
    assert receipt.authorship.value == "store_excerpt"
    assert receipt.store_path == store
    assert receipt.origin.source_path == str(store)
    assert receipt.executed_query.stations == ("02GA010",)
    assert receipt.executed_query.products == ("discharge_daily_mean",)
    assert receipt.format_version == 1
    assert receipt.source_vintage == date(2024, 6, 1)
    excerpt = pl.read_parquet(BytesIO(receipt.content))
    assert excerpt["value"].to_list() == [12.4]
    assert excerpt["DLY_FLOWS.FLOW_SYMBOL1"].to_list() == ["E"]
