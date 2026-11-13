"""Published VandA fields and independently established physical facts.

Scope settled in planning/visions/2026-11-09-dk-vanda-source-scope-and-access.md:
discharge (`Vandføring`, examinationTypeSc 27), stage (`Vandstand`, sc 25) and
water temperature (sc 29).

Step 3 (Effort #798, research/dk-vanda-source-access.md) resolved stage's
raw-vs-corrected question: `resultElevationCorrected` is now admitted as a
second, distinct source field alongside raw `result`, each independently
identified with its own evidenced vertical-reference facts, never collapsed
into one assumed "the" stage value. Because that distinction needs a
source-silent vertical datum and field-specific evidence citations that
`SeriesMapping` cannot express, stage's identities and physical facts are
built directly in `catalogue_series.py` (the heavier `SourceIdentity`/
`PhysicalFacts` pattern), not through this module's `series_mappings`.
Discharge and water temperature stay on `SeriesMapping` below: each has
exactly one admitted field and no competing vertical-reference claim, so the
heavier pattern would buy nothing for them. See `catalogue_series.py`'s module
docstring for the full evidence and the retrieval-wiring plan step 4 still owes.
"""

from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.provider_series import SeriesMapping

EXAMINATION_PRODUCTS: dict[int, str] = {27: "discharge", 25: "stage", 29: "temperature"}
"""VandA `examinationTypeSc` codes admitted for this port, mapped to product_id."""

_SOURCE_UNIT = {"discharge": "l/s", "stage": "cm", "temperature": "degC"}
# "temperature" here is the admission-table quantity (`source_series.py`'s
# `_UNIT_DIMENSIONS`/`_TARGET_UNITS`, matching every other provider's water-
# temperature SeriesMapping: fr_hubeau, cz_chmi, no_nve, ch_foen all pass
# "temperature" as this physical quantity and keep "water_temperature" only
# as a product_id-style label. A prior "water_temperature" value here made
# `admission()` reject dk_vanda temperature facts as dimensionally
# incompatible, which made `conversion.convert` raise `FatalContractError`
# for any live temperature retrieval (reproduced end-to-end through
# `drive()` before this fix, Effort #800 step 5).
_QUANTITY = {"discharge": "discharge", "stage": "stage", "temperature": "temperature"}
_NAMESPACE = {
    "discharge": "dk_vanda.water_flows",
    "stage": "dk_vanda.water_levels",
    "temperature": "dk_vanda.measurements",
}


def series_mappings(examination_type_sc: int) -> dict[str, SeriesMapping]:
    """Map the one `SeriesMapping`-admitted field for discharge and water temperature.

    Stage's own fields are deliberately not added here (see the module
    docstring): `catalogue_series.py` builds both of stage's fields directly,
    so this still returns only raw `result` for examinationTypeSc 25. Callers
    needing stage's full field set (`generate_catalogue.describe_associations`)
    use `catalogue_series.STAGE_FIELDS` instead; callers needing only stage's
    shared quantity/unit for the product-level catalogue row (`catalogue_tables`)
    can keep using this function, since raw and corrected share both.

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
