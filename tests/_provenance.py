"""Test provenance inspection : CatalogueEvidence → OrderedLegacyProvenance.

Legacy reconstruction is explicit and test-only. Packaged corruption tests edit
v3 relations directly; they never use a legacy projection to exercise the reader.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

import polars as pl
import polars.testing as pl_testing

from rivretrieve._internal.acquisition_provenance import AcquisitionProvenance
from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
from rivretrieve._internal.catalogues.evidence import CatalogueEvidence

EVIDENCE_FILES = (
    "provenance_facts.parquet",
    "provenance_acquisitions.parquet",
    "provenance_bindings.parquet",
    "provenance_binding_facts.parquet",
    "provenance_external_inputs.parquet",
)


def legacy_provenance(evidence: CatalogueEvidence) -> AcquisitionProvenance:
    """Reconstruct the complete ordered v2 build value for semantic assertions."""
    from rivretrieve._internal.catalogues.evidence_encoding import reconstruct_provenance

    return reconstruct_provenance(evidence)


def legacy_document(path: Path) -> dict[str, Any]:
    """Read genuine packaged evidence, then explicitly reconstruct its v2 value."""
    evidence = load_packaged_catalogue_artifact(path.parent, on_issue="raise").acquisition_provenance
    assert evidence is not None
    return legacy_provenance(evidence).model_dump(mode="json")


def assert_evidence_equal(actual: CatalogueEvidence, expected: CatalogueEvidence) -> None:
    """Compare header and all ordered relations with Polars value assertions."""
    assert actual.header == expected.header
    for name in ("facts", "acquisitions", "bindings", "binding_facts", "external_inputs"):
        pl_testing.assert_frame_equal(getattr(actual, name), getattr(expected, name), check_exact=True)


def write_evidence_table(directory: Path, filename: str, frame: pl.DataFrame) -> None:
    """Write one deliberately mutated v3 table and refresh its byte identity.

    This permits real-reader semantic-corruption tests to pass the digest gate,
    without reconstructing a legacy model or validating the malformed relations.
    """
    assert filename in EVIDENCE_FILES
    path = directory / filename
    frame.write_parquet(path, compression="zstd")
    body = path.read_bytes()
    header_path = directory / "provenance.json"
    header = json.loads(header_path.read_text())
    assert header["schema_version"] == 3
    identity = header["files"][filename]
    identity.update(sha256=hashlib.sha256(body).hexdigest(), byte_count=len(body), row_count=frame.height)
    header_path.write_text(json.dumps(header))


def remove_binding_fact(directory: Path, name: str) -> None:
    """Remove an exact fact membership, retaining contiguous remaining positions."""
    facts = pl.read_parquet(directory / "provenance_facts.parquet")
    fact_id = facts.filter(pl.col("name") == name)["fact_id"].item()
    memberships = pl.read_parquet(directory / "provenance_binding_facts.parquet")
    memberships = memberships.filter(pl.col("fact_id") != fact_id).with_columns(
        (pl.col("position").rank("ordinal").over("binding_id") - 1).cast(pl.UInt32).alias("position")
    )
    write_evidence_table(directory, "provenance_binding_facts.parquet", memberships)


def remove_external_inputs(directory: Path, groups: tuple[str, ...]) -> None:
    """Remove exact bindings' input edges, leaving other acquisition chains intact."""
    bindings = pl.read_parquet(directory / "provenance_bindings.parquet")
    ids = bindings.filter(pl.col("fact_group").is_in(groups))["binding_id"]
    assert len(ids) == len(groups)
    inputs = pl.read_parquet(directory / "provenance_external_inputs.parquet")
    write_evidence_table(
        directory, "provenance_external_inputs.parquet", inputs.filter(~pl.col("binding_id").is_in(ids.implode()))
    )
