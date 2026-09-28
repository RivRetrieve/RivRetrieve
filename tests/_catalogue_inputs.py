"""Detached, validated packaged inputs for explicitly enrolled behavior tests.

Loading and corruption tests must use the real artifact boundary. This pool is
owned by a pytest session, accepts an explicit path allowlist, and checks file
content before reuse. It never caches registry handles, declarations or paths
resolved from the environment.
"""

from collections.abc import Callable, Iterable
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from rivretrieve._internal.catalogues.artifact import (
    REQUIRED_ARTIFACT_FILES,
    PackagedCatalogArtifact,
)
from rivretrieve._internal.catalogues.evidence import EVIDENCE_FILENAMES

# These are the files read by load_packaged_catalogue_artifact, including its
# source-definition and provenance readers. Native build inputs are not read.
_INPUT_FILES = (
    *REQUIRED_ARTIFACT_FILES,
    "format.json",
    "source_series.json",
    "series_claims.parquet",
    "provenance.json",
    *EVIDENCE_FILENAMES.values(),
)
type Fingerprint = tuple[tuple[str, bytes], ...]


def _fingerprint(path: Path) -> Fingerprint | None:
    try:
        if path.is_symlink():
            return None
        values = []
        for name in _INPUT_FILES:
            file = path / name
            if file.is_symlink():
                return None
            values.append((name, sha256(file.read_bytes()).digest()))
        return tuple(values)
    except OSError:
        # The real loader owns missing-file and unreadable-input diagnostics.
        return None


class PackagedCatalogueInputs:
    """Keep pristine inputs, returning a fully detached value on every borrow."""

    def __init__(
        self,
        paths: Iterable[Path],
        loader: Callable[[Path], PackagedCatalogArtifact],
    ) -> None:
        self._paths = frozenset(path.absolute() for path in paths)
        self._loader = loader
        self._validated: dict[Path, tuple[Fingerprint, PackagedCatalogArtifact]] = {}

    def load(self, path: Path) -> PackagedCatalogArtifact:
        path = path.absolute()
        if path not in self._paths:
            return self._loader(path)
        fingerprint = _fingerprint(path)
        previous = self._validated.get(path)
        if fingerprint is not None and previous is not None and previous[0] == fingerprint:
            return deepcopy(previous[1])
        artifact = self._loader(path)
        if fingerprint is not None and _fingerprint(path) == fingerprint:
            self._validated[path] = (fingerprint, artifact)
            return deepcopy(artifact)
        return artifact
