"""Chile DGA historical source-series definitions and physical facts."""

from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.provider_series import SeriesMapping
from rivretrieve._internal.source_series import ClippingAxis, SourceSeries

DAILY_ZIP_EVIDENCE = "catalogue:cl_dga:source.product.daily_discharge_zip"
MONTHLY_ZIP_EVIDENCE = "catalogue:cl_dga:source.product.monthly_discharge_zip"

SERIES_MAPPINGS: dict[str, SeriesMapping] = {
    "discharge_daily": SeriesMapping(
        namespace="cl_dga.mapas2.caudal_diario",
        published_id="Caudal_diario",
        quantity="discharge",
        source_unit="m3/s",
        normalized_unit="m3/s",
        frequency="P1D",
        statistic=None,
        evidence=(DAILY_ZIP_EVIDENCE,),
    ),
    "discharge_monthly_mean": SeriesMapping(
        namespace="cl_dga.mapas2.caudal_medio_mensual",
        published_id="Caudal_Medio_mensual",
        quantity="discharge",
        source_unit="m3/s",
        normalized_unit="m3/s",
        frequency="P1M",
        statistic="mean",
        clipping_axis=ClippingAxis.CALENDAR_MONTH,
        evidence=(MONTHLY_ZIP_EVIDENCE,),
    ),
}


def source_series(station_id: str, product_id: str) -> SourceSeries:
    """Return the declared Chile DGA ``SourceSeries`` definition for one station and product."""
    mapping = SERIES_MAPPINGS.get(product_id)
    if mapping is None:
        raise FatalContractError(f"Unsupported cl_dga product {product_id!r}")
    return mapping.source_series("cl_dga", station_id, product_id)
