from datetime import datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict

from rivretrieve._internal.acquisition_provenance import AcquisitionProvenance
from rivretrieve._internal.issues import Issue
from rivretrieve._internal.primitives import ProviderId

T = TypeVar("T")


class CatalogProvenance(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: Literal["packaged"]
    provider_id: ProviderId | None = None
    rivretrieve_version: str | None = None
    catalogue_version: str | None = None
    artifact_id: str | None = None
    artifact_path: str | None = None
    artifact_hash: str | None = None
    generated_at: datetime | None = None
    retrieved_at: datetime | None = None
    endpoints: tuple[str, ...] = ()
    query: dict[str, object] | None = None
    response_version: str | None = None
    acquisition_provenance: AcquisitionProvenance | None = None


class CatalogResult(BaseModel, Generic[T]):  # noqa: UP046
    model_config = ConfigDict(frozen=True)

    data: T
    provenance: CatalogProvenance
    issues: tuple[Issue, ...] = ()
