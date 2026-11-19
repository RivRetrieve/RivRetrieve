"""provider declaration : PackagedCatalogue × BulkStore → DeclaredProvider."""

from pathlib import Path

from rivretrieve._internal.providers.cl_dga import bulk
from rivretrieve._internal.providers.cl_dga.config import config
from rivretrieve._internal.providers.registration import (
    BulkCompileRequest,
    BulkDownloadRequest,
    BulkStore,
    DownloadedBulkArtifact,
    ProviderDeclaration,
)
from rivretrieve._internal.store import ValidatedStore


def _download(request: BulkDownloadRequest) -> tuple[DownloadedBulkArtifact, ...]:
    """Adapt the shared bulk request to Chile DGA's undated pair of historical archives."""
    return bulk.download_dga_history(
        request.destination,
        today=request.today,
        probe=request.probe,
        transfer=request.transfer,
        previous_source_vintage=request.previous_source_vintage,
    )


def _compile(request: BulkCompileRequest) -> ValidatedStore:
    """Adapt the shared compile request to Chile DGA's compile request."""
    if request.source_vintage is not None:
        raise ValueError("Chile DGA compilation does not support dated source_vintage values")
    return bulk.compile_cl_dga(
        bulk.ClDgaCompileRequest(
            publisher_artifacts=request.publisher_artifacts,
            destination=request.destination,
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
