"""Two structurally unrelated bulk publishers share the store query path."""

from __future__ import annotations

import sqlite3
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path

from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
from rivretrieve._internal.providers.ca_eccc.bulk import HYDAT_SOURCE_SCHEMAS, HydatCompileRequest, compile_hydat
from rivretrieve._internal.providers.ca_eccc.config import config as ca_config
from rivretrieve._internal.providers.pl_imgw.bulk import ImgwCompileRequest, compile_imgw
from rivretrieve._internal.providers.pl_imgw.config import config as pl_config
from rivretrieve._internal.registry import ProviderRegistry
from rivretrieve._internal.store import StoreReader, StoreRoot
from tests._catalogue import catalogue_path


def _hydat(path: Path) -> None:
    connection = sqlite3.connect(path)
    for table, schema in HYDAT_SOURCE_SCHEMAS.items():
        connection.execute(f"CREATE TABLE {table} (" + ",".join(f'"{name}" {kind}' for name, kind in schema) + ")")
        row = {name: None for name, _kind in schema}
        prefix = "FLOW" if table == "DLY_FLOWS" else "LEVEL"
        row.update(STATION_NUMBER="02GA010", YEAR=2020, MONTH=1, FULL_MONTH=0, NO_DAYS=1)
        row[f"{prefix}1"] = 12.4 if table == "DLY_FLOWS" else 1.2
        connection.execute(
            f"INSERT INTO {table} VALUES (" + ",".join("?" for _ in schema) + ")",
            tuple(row[name] for name, _kind in schema),
        )
    connection.commit()
    connection.close()


def test_two_sources_one_reader(tmp_path: Path, monkeypatch) -> None:
    hydat_sqlite = tmp_path / "Hydat.sqlite3"
    hydat_artifact = tmp_path / "hydat.zip"
    _hydat(hydat_sqlite)
    with zipfile.ZipFile(hydat_artifact, "w") as archive:
        archive.write(hydat_sqlite, "Hydat.sqlite3")
    hydat_sqlite.unlink()
    imgw_artifact = tmp_path / "codz_2023.zip"
    with zipfile.ZipFile(imgw_artifact, "w") as archive:
        archive.writestr(
            "codz_2023.csv",
            "\ufeff151140030;Przewożniki;Skroda;2023;03;01;225;1.500;2.5;1\r\n".encode(),
        )

    ca_store = StoreRoot(tmp_path / "ca-store")
    pl_store = StoreRoot(tmp_path / "pl-store")
    common = {"built_at": datetime(2026, 8, 11, tzinfo=UTC), "compiler_version": "1.0"}
    compile_hydat(
        HydatCompileRequest(
            hydat_artifact,
            ca_store,
            "https://example.test/hydat.zip",
            date(2024, 6, 1),
            **common,
        )
    )
    compile_imgw(
        ImgwCompileRequest(
            imgw_artifact,
            pl_store,
            "https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/dobowe/2023/codz_2023.zip",
            date(2023, 10, 31),
            built_at=datetime(2026, 8, 11, tzinfo=UTC),
            compiler_version="1.0",
        )
    )

    calls: list[str] = []
    original = StoreReader.query

    def witness(self, query):
        calls.append(str(query.provider_id))
        return original(self, query)

    monkeypatch.setattr(StoreReader, "query", witness)
    registry = ProviderRegistry()
    for provider_id, config, store in (
        ("ca_eccc", ca_config, ca_store),
        ("pl_imgw", pl_config, pl_store),
    ):
        registry.register(
            provider_id,
            load_packaged_catalogue_artifact(catalogue_path(provider_id), on_issue="raise"),
            bulk_config=config,
            observation_store=store,
        )
    ca = registry.get("ca_eccc").observations(
        stations="02GA010", products="discharge_daily_mean", start="2020-01-01", end="2020-12-31", on_issue="ignore"
    )
    pl = registry.get("pl_imgw").observations(
        stations="151140030", products="discharge_daily_mean", start="2023-01-01", end="2023-12-31", on_issue="ignore"
    )

    assert calls == ["ca_eccc", "pl_imgw"]
    assert ca.data["value"].to_list() == [12.4, *([None] * 30)]
    assert pl.data["value"].to_list() == [1.5]
