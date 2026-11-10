"""Direct ``SourceIdentity``/``PhysicalFacts`` for VandA stage's two distinct fields.

Step 3 (Effort #798, research/dk-vanda-source-access.md in the private evidence
repository) found that raw `result` and `resultElevationCorrected` on the
continuous stage examination (`examinationTypeSc` 25) need independently
evidenced vertical-reference facts, not one assumed "the" stage value:

* A numeric cross-check compared `resultElevationCorrected` against the
  separate, named `examinationTypeSc` 21 ("Kotemåling", `parameter` "Vandstand
  DVR90") levelling examination for the same stations. At two independent
  stations (19000468, 46000721) and, at the first, two different historical
  benchmark epochs (0.572 m in 2022 and 0.577 m in 2026), every retained row
  satisfies ``resultElevationCorrected == result + <that station's current
  Kotemåling benchmark>`` to the published decimal precision. This establishes
  `resultElevationCorrected`'s vertical datum as DVR90 directly from VandA's
  own published examination (not from the hydrodownloadR R adapter, which only
  names the datum in comments). The same arithmetic shows raw `result` is
  measured relative to each station's own local zero point, not DVR90 or any
  other named datum: VandA's `swagger.json` and `/config/examination-types`
  responses were both checked and neither names a datum for the raw field or
  examination, so that absence is recorded as source-silent, not merely
  unestablished.

This module builds `PhysicalFacts`/`SourceIdentity` directly instead of going
through `series.SeriesMapping` for stage, for two reasons `SeriesMapping`
cannot accommodate: it needs to record `vertical_datum` as source-silent
(not just known-or-unestablished) for the raw field, and it needs a narrower,
field-specific evidence citation for the vertical facts than the one shared
evidence tuple `SeriesMapping.physical_facts` applies to every fact it builds.
`fi_syke`'s step-3 implementation (`catalogue_series.py` on
`effort-755-fi-syke-series-identity-implementation`, not merged) is the worked
example this follows: a provider's series.py keeps the lighter `SeriesMapping`
for products with no such nuance, and a separate `catalogue_series.py` builds
the heavier pattern only for the product that needs it. `dk_vanda`'s discharge
and water-temperature stay on `SeriesMapping` (`series.py`): each has exactly
one admitted field and no competing vertical-reference claim, so the heavier
pattern would buy nothing there.

Both stage fields stay catalogued under the single "stage" product (same
quantity, same `cm` unit); `generate_catalogue.describe_associations` emits one
`SourceDescription` per field here, so the packaged catalogue's
`series_claims.parquet` retains both as distinct, separately identified source
series (`published_id="result"` vs `"resultElevationCorrected"`), never
collapsed into one.

Retrieval (`fetch.py`/`parse.py`, Effort #799) still owes the actual wiring:
which field a plain "stage" request returns without an explicit selector is an
open retrieval-design question for that step, not resolved here. Quality marks
(`/quality-assurance/quality-marks`, confirmed reachable in step 1) and VandA's
per-row `reasonSc`/`reason` flags are native-response signals that step 4's
parser should translate into `info`/`warning`-severity `Issue`s (see
`fi_syke`/`lt_lhmt` `parse.py` precedent); no retrieval exists yet to carry
them, so no `Issue`-emission is wired here. The multi-version-results question
(`/measurements/results/all`, program issue #351) was tried again in step 3 at
a station and product (stage, `examinationTypeSc` 25, station 19000468, both a
historic and a recent window) not used in step 1's attempt (discharge at
station 19000467); it still did not reproduce row-doubling or a station/
timestamp carrying more than one result version. Two negative reproductions do
not prove VandA never versions a result, so `parse.py` must still tolerate
more than one result per timestamp defensively, not assume either count holds
universally.
"""

from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.source_series import (
    EvidenceFact,
    EvidenceState,
    PhysicalFacts,
    SourceIdentity,
    known,
    stable_id,
)

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
