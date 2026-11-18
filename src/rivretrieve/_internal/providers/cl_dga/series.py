"""Chile DGA historical source-series definitions and physical facts."""

from rivretrieve._internal.provider_series import SeriesMapping

DAILY_ZIP_EVIDENCE = "catalogue:cl_dga:source.product.daily_discharge_zip"
MONTHLY_ZIP_EVIDENCE = "catalogue:cl_dga:source.product.monthly_discharge_zip"

SERIES_MAPPINGS: dict[str, SeriesMapping] = {
    "discharge_daily": SeriesMapping(
        namespace="cl_dga.mapas2.caudal_diario",
        published_id="Caudal_diario",
        quantity="discharge",
        source_unit="m3/s",
        normalized_unit="m3/s",
        frequency="daily",
        statistic=None,
        evidence=(DAILY_ZIP_EVIDENCE,),
    ),
    "discharge_monthly_mean": SeriesMapping(
        namespace="cl_dga.mapas2.caudal_medio_mensual",
        published_id="Caudal_Medio_mensual",
        quantity="discharge",
        source_unit="m3/s",
        normalized_unit="m3/s",
        frequency="monthly",
        statistic="mean",
        evidence=(MONTHLY_ZIP_EVIDENCE,),
    ),
}
