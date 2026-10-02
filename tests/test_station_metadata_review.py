"""Restricted retained-input census for reviewing candidate station metadata fields."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import polars as pl
import pytest

from rivretrieve._internal.provider_manifest import BUILTIN_PROVIDER_IDS


@pytest.mark.derived(
    *(f"src/rivretrieve/_internal/providers/{provider}/catalogue/native.parquet" for provider in BUILTIN_PROVIDER_IDS)
)
def test_station_metadata_candidate_review(retained_evidence_root: Path) -> None:
    """Write bounded candidates privately; this does not approve any mapping or disclosure."""
    configured = os.environ.get("RIVRETRIEVE_CATALOGUE_PRODUCT_OUTPUT")
    if not configured:
        pytest.fail("The reviewed catalogue command must supply a restricted output directory.", pytrace=False)
    destination = Path(configured).resolve()
    checkout = Path(__file__).resolve().parents[1]
    if destination.is_relative_to(checkout) or destination.is_relative_to(retained_evidence_root.resolve()):
        pytest.fail("Candidate review output must be outside the checkout and retained inputs.", pytrace=False)
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    report = {}
    for provider in BUILTIN_PROVIDER_IDS:
        native = pl.read_parquet(
            retained_evidence_root / f"src/rivretrieve/_internal/providers/{provider}/catalogue/native.parquet"
        )
        fields = {}
        for field, dtype in native.schema.items():
            # This is a census filter, not a source-role mapping or permission decision.
            if dtype != pl.String or not re.search(
                r"name|nom|river|gauge|station|n[aá]zev|観測|河川|水系|名称", field, re.IGNORECASE
            ):
                continue
            values = native[field]
            fields[field] = {
                "dtype": str(dtype),
                "null_count": values.null_count(),
                "blank_count": (values == "").sum(),
                "examples": values.drop_nulls().unique(maintain_order=True).head(5).to_list(),
            }
        report[provider] = {
            "row_count": native.height,
            "schema": {key: str(value) for key, value in native.schema.items()},
            "candidate_fields": fields,
        }
    output = destination / "station-metadata-candidates.json"
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
