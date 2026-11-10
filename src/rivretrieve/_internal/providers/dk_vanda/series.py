"""Published VandA fields and independently established physical facts.

Scope settled in planning/visions/2026-11-09-dk-vanda-source-scope-and-access.md:
discharge (`Vandføring`, examinationTypeSc 27), stage (`Vandstand`, sc 25) and
water temperature (sc 29). The catalogue currently describes only the raw
`result` field for stage; `resultElevationCorrected`'s unit and vertical datum
are unestablished (research/dk-vanda-source-access.md), so it is deliberately
left out of this mapping until Effort #798 resolves them, rather than guessing.
"""

from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.provider_series import SeriesMapping

EXAMINATION_PRODUCTS: dict[int, str] = {27: "discharge", 25: "stage", 29: "temperature"}
"""VandA `examinationTypeSc` codes admitted for this port, mapped to product_id."""

_SOURCE_UNIT = {"discharge": "l/s", "stage": "cm", "temperature": "degC"}
_QUANTITY = {"discharge": "discharge", "stage": "stage", "temperature": "water_temperature"}
_NAMESPACE = {
    "discharge": "dk_vanda.water_flows",
    "stage": "dk_vanda.water_levels",
    "temperature": "dk_vanda.measurements",
}


def series_mappings(examination_type_sc: int) -> dict[str, SeriesMapping]:
    """Map the one admitted field per examination type without inferring cadence.

    Frequency and statistic stay unestablished: VandA publishes no named
    aggregation, and both prior reference adapters compute their own daily
    mean from the native readings rather than reading one from the source.
    ``normalized_unit`` names the same recognized spelling as ``source_unit``
    (matching `br_ana`'s ``normalized_unit=source_unit`` precedent); the
    shared engine's unit-dimension table, not this mapping, converts l/s to
    m3/s and cm to m when assembling returned values.
    """
    if examination_type_sc not in EXAMINATION_PRODUCTS:
        raise FatalContractError("Unsupported dk_vanda examination type")
    product = EXAMINATION_PRODUCTS[examination_type_sc]
    evidence = ("catalogue:dk_vanda:source.station_product.associations",)
    source_unit = _SOURCE_UNIT[product]
    return {
        "result": SeriesMapping(
            namespace=_NAMESPACE[product],
            published_id="result",
            quantity=_QUANTITY[product],
            source_unit=source_unit,
            normalized_unit=source_unit,
            evidence=evidence,
            identity_evidence=("catalogue:dk_vanda:source.series.fields",),
        )
    }
