from datetime import UTC, datetime
from typing import Any, cast

import pytest
from pydantic import ValidationError

from rivretrieve._internal.issues import Issue
from rivretrieve._internal.primitives import CatalogSource, ProviderId
from rivretrieve._internal.results import CatalogProvenance, CatalogResult


@pytest.mark.parametrize("source", ["packaged", "live"])
def test_catalog_source_accepts_packaged_and_live(source: CatalogSource) -> None:
    provenance = CatalogProvenance(source=source)

    assert provenance.source == source


def test_catalog_source_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        CatalogProvenance(source=cast(Any, "cached"))


def test_catalog_provenance_packaged_roundtrip() -> None:
    generated_at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    provider_id = ProviderId("ch_foen")

    provenance = CatalogProvenance(
        source="packaged",
        provider_id=provider_id,
        rivretrieve_version="0.1.2",
        catalogue_version="2026.01",
        artifact_id="ch_foen-stations",
        artifact_path="catalogues/ch_foen/stations.parquet",
        artifact_hash="sha256:abc123",
        generated_at=generated_at,
    )

    assert provenance.source == "packaged"
    assert provenance.provider_id == provider_id
    assert provenance.rivretrieve_version == "0.1.2"
    assert provenance.catalogue_version == "2026.01"
    assert provenance.artifact_id == "ch_foen-stations"
    assert provenance.artifact_path == "catalogues/ch_foen/stations.parquet"
    assert provenance.artifact_hash == "sha256:abc123"
    assert provenance.generated_at == generated_at


def test_catalog_provenance_live_roundtrip() -> None:
    retrieved_at = datetime(2026, 2, 3, 4, 5, 6, tzinfo=UTC)
    query: dict[str, object] = {"station_id": "1234", "product_id": "discharge"}

    provenance = CatalogProvenance(
        source="live",
        retrieved_at=retrieved_at,
        endpoints=("https://example.test/stations", "https://example.test/products"),
        query=query,
        response_version="v2",
    )

    assert provenance.source == "live"
    assert provenance.retrieved_at == retrieved_at
    assert provenance.endpoints == ("https://example.test/stations", "https://example.test/products")
    assert provenance.query == query
    assert provenance.response_version == "v2"


def test_catalog_result_roundtrip() -> None:
    data: list[dict[str, object]] = [{"station_id": "1234", "name": "Example"}]
    provenance = CatalogProvenance(source="packaged", provider_id=ProviderId("ch_foen"))
    issue = Issue(severity="warning", code="partial_catalogue", message="Partial catalogue")

    result = CatalogResult[list[dict[str, object]]](data=data, provenance=provenance, issues=(issue,))

    assert result.data == data
    assert result.provenance == provenance
    assert result.issues == (issue,)
