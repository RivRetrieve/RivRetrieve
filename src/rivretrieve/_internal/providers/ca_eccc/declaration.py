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


def _download(request: BulkDownloadRequest) -> DownloadedBulkArtifact:
    """Adapt the shared bulk request to the publisher's download vocabulary."""
    downloaded = bulk.download(
        request.destination,
        today=request.today,
        probe=request.probe,
        transfer=request.transfer,
    )
    return DownloadedBulkArtifact(downloaded.path, downloaded.url, downloaded.source_vintage)


def _compile(request: BulkCompileRequest) -> ValidatedStore:
    """Adapt the shared compile request to the publisher's request type."""
    return bulk.compile(
        bulk.HydatCompileRequest(
            publisher_artifact=request.publisher_artifact,
            destination=request.destination,
            publisher_url=request.publisher_url,
            source_vintage=request.source_vintage,
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
)
