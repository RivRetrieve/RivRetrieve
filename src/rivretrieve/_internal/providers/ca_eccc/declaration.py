"""provider declaration : PackagedCatalogue × BulkStore → DeclaredProvider."""

from pathlib import Path

from rivretrieve._internal.providers.ca_eccc import bulk
from rivretrieve._internal.providers.ca_eccc.config import config
from rivretrieve._internal.providers.registration import (
    BulkCompileRequest,
    BulkDownloadRequest,
    BulkStore,
    DownloadedBulkArtifact,
    ProviderDeclaration,
)
from rivretrieve._internal.store import ValidatedStore


def _download(request: BulkDownloadRequest) -> tuple[DownloadedBulkArtifact, ...]:
    """Adapt the shared bulk request to the publisher's download vocabulary."""
    downloaded = bulk.download_hydat(
        request.destination,
        today=request.today,
        probe=request.probe,
        transfer=request.transfer,
    )
    return (DownloadedBulkArtifact(downloaded.path, downloaded.url, downloaded.source_vintage),)


def _compile(request: BulkCompileRequest) -> ValidatedStore:
    """Adapt the shared compile request to the publisher's request type."""
    if len(request.publisher_artifacts) != 1:
        raise ValueError("HYDAT compilation requires exactly one publisher artifact")
    return bulk.compile_hydat(
        bulk.HydatCompileRequest(
            publisher_artifact=request.publisher_artifacts[0].path,
            destination=request.destination,
            publisher_url=request.publisher_artifacts[0].url,
            source_vintage=request.publisher_artifacts[0].source_vintage,
            built_at=request.built_at,
            compiler_version=request.compiler_version,
        )
    )


declaration = ProviderDeclaration(
    catalogue=Path(__file__).with_name("catalogue"),
    observations=BulkStore(
        config=config,
        download=_download,
        compile=_compile,
    ),
    required_credentials=(),
)
