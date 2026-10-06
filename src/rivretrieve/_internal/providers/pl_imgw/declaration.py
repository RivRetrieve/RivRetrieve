"""provider declaration : PackagedCatalogue × BulkStore → DeclaredProvider."""

from pathlib import Path

from rivretrieve._internal.providers.pl_imgw import bulk
from rivretrieve._internal.providers.pl_imgw.config import config
from rivretrieve._internal.providers.registration import (
    BulkCompileRequest,
    BulkDownloadRequest,
    BulkStore,
    DownloadedBulkArtifact,
    ProviderDeclaration,
)
from rivretrieve._internal.store import ValidatedStore


def _download(request: BulkDownloadRequest) -> tuple[DownloadedBulkArtifact, ...]:
    """Adapt the shared bulk request to the publisher's multi-artifact history."""
    downloaded = bulk.download_imgw_history(
        request.destination,
        today=request.today,
        transfer=request.transfer,
    )
    return tuple(DownloadedBulkArtifact(item.path, item.url, item.source_vintage) for item in downloaded)


def _compile(request: BulkCompileRequest) -> ValidatedStore:
    """Adapt the shared compile request to the publisher's request type."""
    return bulk.compile_imgw(
        bulk.ImgwCompileRequest(
            publisher_artifact=request.publisher_artifact,
            destination=request.destination,
            publisher_url=request.publisher_url,
            source_vintage=request.source_vintage,
            publisher_artifacts=request.publisher_artifacts,
            built_at=request.built_at,
            compiler_version=request.compiler_version,
            transaction=request.transaction,
            free_space_probe=request.free_space_probe,
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
