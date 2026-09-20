"""Build Swiss field candidates without claiming station-specific availability."""

from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.providers.ch_foen.config import config
from rivretrieve._internal.providers.ch_foen.series import field_candidates
from rivretrieve._internal.source_series import SourceSeries


def source_inventory(artifact: PackagedCatalogArtifact) -> tuple[SourceSeries, ...]:
    declarations = config()
    return tuple(
        item
        for row in artifact.station_products.iter_rows(named=True)
        if row["availability"] != "unavailable"
        for item in field_candidates((row["station_id"],), (row["product_id"],), declarations)
    )
