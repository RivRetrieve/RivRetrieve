from __future__ import annotations

import sqlite3
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path

from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
from rivretrieve._internal.providers.ca_eccc.bulk import (
    HYDAT_SOURCE_SCHEMAS,
    HydatCompileRequest,
    compile_hydat,
    download_hydat,
)
from rivretrieve._internal.providers.ca_eccc.config import config
from rivretrieve._internal.registry import ProviderRegistry
from rivretrieve._internal.store import StoreRoot
from rivretrieve._internal.store.validation import StoreManifest
from tests._catalogue import catalogue_path


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


def test_ca_eccc_value_provenance_names_compiled_release(tmp_path: Path) -> None:
    sqlite_artifact = tmp_path / "Hydat.sqlite3"
    artifact = tmp_path / "Hydat_sqlite3_20240601.zip"
    store = StoreRoot(tmp_path / "store")
    _hydat(sqlite_artifact)
    with zipfile.ZipFile(artifact, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(sqlite_artifact, "Hydat.sqlite3")
    sqlite_artifact.unlink()
    validated = compile_hydat(
        HydatCompileRequest(
            publisher_artifact=artifact,
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
        load_packaged_catalogue_artifact(catalogue_path("ca_eccc"), on_issue="raise"),
        bulk_config=config,
        observation_store=store,
    )
    result = registry.get("ca_eccc").observations(
        stations="02GA010",
        products="discharge_daily_mean",
        start="2020-01-01",
        end="2020-01-01",
        on_issue="ignore",
    )
    assert result.data["value"].to_list() == [12.4]
    assert result.provenance.source_vintage == date(2024, 6, 1)
    assert isinstance(validated.manifest, StoreManifest)
    assert result.provenance.publisher_artifact_checksum == str(validated.manifest.publisher_artifact.sha256)
    assert result.provenance.publisher_artifact_checksum.startswith("sha256:")
    assert not artifact.exists()


def test_hydat_download_resolves_publisher_dated_release(tmp_path: Path) -> None:
    destination = tmp_path / "publisher.zip"
    probes: list[str] = []

    def probe(url: str) -> int:
        probes.append(url)
        return 200 if url.endswith("20240601.zip") else 404

    def transfer(url: str, path: Path) -> None:
        assert url == probes[-1]
        path.write_bytes(b"publisher bytes")

    result = download_hydat(
        destination,
        today=date(2024, 6, 3),
        probe=probe,
        transfer=transfer,
    )

    assert result.path == destination
    assert result.source_vintage == date(2024, 6, 1)
    assert result.url.endswith("Hydat_sqlite3_20240601.zip")
    assert destination.read_bytes() == b"publisher bytes"
