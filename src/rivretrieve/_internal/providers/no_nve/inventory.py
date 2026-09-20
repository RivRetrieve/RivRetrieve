"""Read persisted HydAPI source-version descriptions without source access."""

from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.catalogues.source_series import materialize_series
from rivretrieve._internal.source_series import SourceSeries


def source_inventory(artifact: PackagedCatalogArtifact) -> tuple[SourceSeries, ...]:
    return materialize_series(artifact)[0]
