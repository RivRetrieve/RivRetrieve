"""Inspect provider declarations and catalogue counts without contacting services."""

from collections import Counter
from pathlib import Path

import polars as pl

from rivretrieve._internal.provider_manifest import BUILTIN_PROVIDER_IDS
from rivretrieve._internal.providers.registration import BulkStore, LiveStages, load_manifest

providers = load_manifest(BUILTIN_PROVIDER_IDS)
counts = Counter(type(item.declaration.observations).__name__ for item in providers)
print(dict(counts))
print("registered:", len(providers))
print(
    "observation access:", sum(isinstance(item.declaration.observations, LiveStages | BulkStore) for item in providers)
)
root = Path(__file__).resolve().parents[3]
for provider in ("fr_hubeau", "fr_hydroportail"):
    print(
        provider,
        pl.read_parquet(root / f"src/rivretrieve/_internal/providers/{provider}/catalogue/stations.parquet").height,
    )
