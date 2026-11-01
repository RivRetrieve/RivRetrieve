"""Published SENAMHI fields and independently established physical facts."""

from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.provider_series import SeriesMapping

MONTHLY_LEVEL_FIELDS = frozenset(
    {
        "NIVEL_DEL_RIO_06H",
        "NIVEL_DEL_RIO_10H",
        "NIVEL_DEL_RIO_14H",
        "NIVEL_DEL_RIO_18H",
        "NIVEL_DEL_RIO_PROMEDIO",
        "N_NIVELAGUA",
        "N_NIVELMEDIO",
        "N_NIV_INST_00",
        "N_NIV_INST_10",
    }
)


def series_mappings(subsystem: str, resolution: str | None, variable: str, unit: str) -> dict[str, SeriesMapping]:
    """Map each supported response field without inferring temporal meaning.

    Products retain route, resolution, variable and unit associations. Daily
    PHISIS products contain three separate published fields. Monthly archive
    fields remain separate even when their names suggest similar readings.
    Units identify the published representation, not a named vertical datum.
    """
    if subsystem == "phisis":
        if resolution not in {"DAILY", "HOURLY"} or unit not in {"FLOW": {"m3/s"}, "LEVEL": {"m", "m.s.n.m"}}.get(
            variable, set()
        ):
            raise FatalContractError("Unsupported PHISIS series association")
        fields = ("current", "minimum", "maximum") if resolution == "DAILY" else ("value",)
        namespace = f"senamhi.phisis.{resolution}.{variable}.{unit}"
    elif subsystem == "monthly_archive" and resolution is None and variable in MONTHLY_LEVEL_FIELDS and unit == "m":
        fields = (variable,)
        namespace = "senamhi.monthly_archive"
    else:
        raise FatalContractError("Unsupported SENAMHI series association")
    evidence = ("catalogue:pe_senamhi:source.station_product.associations",)
    return {
        field: SeriesMapping(
            namespace=namespace,
            published_id=field,
            quantity="discharge" if variable == "FLOW" else "stage",
            source_unit=unit,
            normalized_unit="m3/s" if variable == "FLOW" else "m",
            vertical_reference="above_sea_level" if unit == "m.s.n.m" else None,
            evidence=evidence,
            identity_evidence=("catalogue:pe_senamhi:source.series.fields",),
        )
        for field in fields
    }
