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
built directly below (the heavier `SourceIdentity`/`PhysicalFacts` pattern,
`stage_identity`/`stage_facts`), not through this module's `series_mappings`.
Discharge and water temperature stay on `SeriesMapping`: each has exactly one
admitted field and no competing vertical-reference claim, so the heavier
pattern would buy nothing for them.

This module (not a separate `catalogue_series.py`) holds stage's heavier
pattern because both `generate_catalogue.py` (build time) and `parse.py`
(runtime, Effort #799/#800) need `stage_identity`/`stage_facts`/`STAGE_FIELDS`;
a `catalogue_series.py`-named module is a build-time-only maintainer role
(`tests/test_provider_architecture_contracts.py`'s
`test_runtime_declarations_transitively_do_not_import_maintainer_roles`), so
`parse.py` cannot import one.

Step 3's full DVR90 cross-check evidence (two independent stations, two
historical benchmark epochs at one of them) and the datum-silence check
against `swagger.json`/`/config/examination-types` are detailed in
`research/dk-vanda-source-access.md`'s step 3 section, not repeated here.
"""

from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.provider_series import SeriesMapping
from rivretrieve._internal.source_series import (
    EvidenceFact,
    EvidenceState,
    PhysicalFacts,
    SourceIdentity,
    known,
    stable_id,
)

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
    docstring): `stage_identity`/`stage_facts` below build both of stage's
    fields directly, so this still returns only raw `result` for
    examinationTypeSc 25. Callers needing stage's full field set
    (`generate_catalogue.describe_associations`) use `STAGE_FIELDS` instead;
    callers needing only stage's shared quantity/unit for the product-level
    catalogue row (`catalogue_tables`) can keep using this function, since raw
    and corrected share both.

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


STAGE_NAMESPACE = "dk_vanda.water_levels"
STAGE_QUANTITY = "stage"
STAGE_UNIT = "cm"
_IDENTITY_EVIDENCE = ("catalogue:dk_vanda:source.series.fields",)
_ASSOCIATION_EVIDENCE = "catalogue:dk_vanda:source.station_product.associations"

# Numeric cross-check retained and registered as the evidence collection
# dk_vanda-series-identity-2026-11-10-v1 (research/dk-vanda-source-access.md, step 3):
# resultElevationCorrected == result + the station's current Kotemåling ("Vandstand
# DVR90", examinationTypeSc 21) benchmark, confirmed at two stations and, at one of
# them, two different historical benchmark epochs.
_DVR90_CROSS_CHECK_EVIDENCE = (
    "maintenance/catalogue/dk_vanda/official/series-identity/web/waterlevels-19000468-2026-06-03.body",
    "maintenance/catalogue/dk_vanda/official/series-identity/web/kote-19000468.body",
    "maintenance/catalogue/dk_vanda/official/series-identity/web/waterlevels-19000468-2022-06-07.body",
    "maintenance/catalogue/dk_vanda/official/series-identity/web/waterlevels-46000721-2026-01-08.body",
    "maintenance/catalogue/dk_vanda/official/series-identity/web/kote-46000721.body",
)
# Checked and found silent on any datum name for the raw reading or the sc25
# examination itself (step 3): neither the full OpenAPI field description nor
# the examination-type configuration names a reference for the uncorrected value.
_RAW_DATUM_SILENCE_EVIDENCE = (
    "maintenance/catalogue/dk_vanda/official/series-identity/web/swagger.body",
    "maintenance/catalogue/dk_vanda/official/series-identity/web/examination-types.body",
)

STAGE_FIELDS: tuple[str, ...] = ("result", "resultElevationCorrected")


def stage_identity(field: str) -> SourceIdentity:
    """Published selector for one stage field; a catalogue-authored mapping, not a response read."""
    if field not in STAGE_FIELDS:
        raise FatalContractError(f"Unsupported dk_vanda stage field {field!r}")
    return SourceIdentity(
        namespace=STAGE_NAMESPACE,
        published_id=field,
        origin="mapping",
        evidence=_IDENTITY_EVIDENCE,
    )


def stage_facts(field: str) -> PhysicalFacts:
    """Independently evidenced physical facts for one stage field.

    Frequency, statistic and the other temporal facts stay unestablished,
    matching `SeriesMapping`'s existing stage mapping: VandA publishes no
    named aggregation for either field.
    """
    if field == "result":
        vertical_reference = EvidenceFact(
            value="gauge_zero", state=EvidenceState.KNOWN, evidence=_DVR90_CROSS_CHECK_EVIDENCE
        )
        vertical_datum = EvidenceFact(state=EvidenceState.SOURCE_SILENT, evidence=_RAW_DATUM_SILENCE_EVIDENCE)
    elif field == "resultElevationCorrected":
        vertical_reference = EvidenceFact(
            value="above_sea_level", state=EvidenceState.KNOWN, evidence=_DVR90_CROSS_CHECK_EVIDENCE
        )
        vertical_datum = EvidenceFact(value="DVR90", state=EvidenceState.KNOWN, evidence=_DVR90_CROSS_CHECK_EVIDENCE)
    else:
        raise FatalContractError(f"Unsupported dk_vanda stage field {field!r}")
    facts = PhysicalFacts(
        facts_id="unidentified",
        quantity=known(STAGE_QUANTITY, _ASSOCIATION_EVIDENCE),
        source_unit=known(STAGE_UNIT, _ASSOCIATION_EVIDENCE),
        normalized_unit=STAGE_UNIT,
        vertical_reference=vertical_reference,
        vertical_datum=vertical_datum,
    )
    return facts.model_copy(update={"facts_id": stable_id(facts.model_dump_json(exclude={"facts_id"}))})
