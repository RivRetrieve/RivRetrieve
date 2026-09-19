from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl

from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.source_series import PhysicalFacts, SourceIdentity, SourceSeries, known, stable_id
from rivretrieve._internal.store import (
    ArtifactChecksum,
    DecodedPublisherArtifact,
    Disposition,
    PublisherArtifact,
    SourceColumn,
    SourceColumnDisposition,
    SourceUnitCount,
    StoreCompileRequest,
    StoreRoot,
)

COLUMNS = (SourceColumn("raw_value", "text"),)
DISPOSITIONS = (SourceColumnDisposition("raw_value", Disposition.RETAINED, reconstruction_rule=None, rationale=None),)


def fixture_series(
    station: str = "station-1", provider: str = "fixture_bulk", product: str = "discharge"
) -> SourceSeries:
    facts = PhysicalFacts(
        facts_id="fixture-discharge-m3s",
        quantity=known("discharge", "controlled compiler fixture"),
        source_unit=known("m3/s", "controlled compiler fixture"),
        normalized_unit="m3/s",
    )
    return SourceSeries(
        series_id=stable_id(provider, station, product),
        provider_id=provider,
        station_id=station,
        product_id=product,
        identity=SourceIdentity(
            namespace="controlled compiler fixture", origin="mapping", evidence=("controlled compiler fixture",)
        ),
        facts=(facts,),
    )


def rows(*, year: int = 1998, value: float = 12.4, station: str = "station-1") -> pl.DataFrame:
    return pl.DataFrame(
        {
            "product": ["discharge"],
            "station_id": [station],
            "time": [datetime(year, 1, 2)],
            "time_zone": ["Europe/Warsaw"],
            "value": [value],
            "value_state": ["published_value"],
            "series_id": [fixture_series(station).series_id],
            "facts_id": [fixture_series(station).facts[0].facts_id],
            "source_unit": ["m3/s"],
            "raw_value": [str(value)],
        },
        schema={
            "product": pl.String,
            "station_id": pl.String,
            "time": pl.Datetime("us"),
            "time_zone": pl.String,
            "value": pl.Float64,
            "value_state": pl.String,
            "series_id": pl.String,
            "facts_id": pl.String,
            "source_unit": pl.String,
            "raw_value": pl.String,
        },
    )


def artifact_and_request(tmp_path: Path, *, columns: tuple[SourceColumn, ...] = COLUMNS):
    artifact = tmp_path / "publisher.zip"
    artifact.write_bytes(b"publisher fixture bytes")
    digest = ArtifactChecksum(f"sha256:{hashlib.sha256(artifact.read_bytes()).hexdigest()}")
    request = StoreCompileRequest(
        destination=StoreRoot(tmp_path / "store"),
        provider_id=ProviderId("fixture_bulk"),
        compiler_version="0.1.0",
        built_at=datetime(2026, 8, 11, tzinfo=UTC),
        source_vintage=date(1998, 12, 31),
        publisher_artifact=PublisherArtifact("https://example.test/publisher.zip", digest),
        source_columns=columns,
        source_column_dispositions=DISPOSITIONS,
        series=(fixture_series(),),
    )
    return artifact, request


def complete(decoded_rows: pl.DataFrame, *, columns: tuple[SourceColumn, ...] = COLUMNS):
    return DecodedPublisherArtifact(
        decoded_rows,
        columns,
        (SourceUnitCount("1998.csv", 1, decoded_rows.height),),
    )
