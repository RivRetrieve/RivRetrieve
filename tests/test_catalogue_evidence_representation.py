"""National evidence representation budgets on real discovery and build paths."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
CATALOGUE = ROOT / "src/rivretrieve/_internal/providers/fr_hubeau/catalogue"


def test_france_public_evidence_and_descriptor_fit_normalized_budget() -> None:
    files = [CATALOGUE / "provenance.json", CATALOGUE / "croissant.json", *CATALOGUE.glob("provenance_*.parquet")]
    sizes = {path.name: path.stat().st_size for path in files}
    assert sum(sizes.values()) <= 8_000_000, sizes
    assert sizes["croissant.json"] <= 262_144, sizes
