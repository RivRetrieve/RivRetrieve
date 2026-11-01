# SENAMHI series identity and physical meaning

Deliver evidence-backed, tested series mappings for `pe_senamhi` under
[Effort #605](https://github.com/RivRetrieve/RivRetrieve/issues/605) and
[Program #534](https://github.com/RivRetrieve/RivRetrieve/issues/534). Users and
later retrieval code must be able to distinguish published records and interpret
established physical facts without inheriting unsupported meanings.

Completing the research, mappings and verification described here completes #605.
Publishing this vision does not complete the Effort. Work targets
`port/pe-senamhi`; keep `main` unchanged pending the Program's final review.
Observation acquisition, parsing integration and request planning remain in
[#606](https://github.com/RivRetrieve/RivRetrieve/issues/606) and
[#607](https://github.com/RivRetrieve/RivRetrieve/issues/607). This work does not
enable observation retrieval or complete provider acceptance.

## Preserve published distinctions

Build on the [offline catalogue](2026-10-31-senamhi-offline-station-catalogue.md).
Keep PHISIS monitoring and the monthly station archive separate, even at the same
station. Preserve existing canonical station identities and established product
associations, including associations witnessed in empty hourly windows.

Define separate PHISIS daily `current`, `minimum` and `maximum` series for each
supported variable, and separate hourly `value` series. Equality of values does
not make the records interchangeable. Keep discharge and water level distinct.
Do not adopt forecasts or historical averages. The `previous` array remains a
retrieval question, not authority to invent another physical product.

Keep all nine monthly water-level fields distinct:

- `NIVEL_DEL_RIO_06H`, `NIVEL_DEL_RIO_10H`, `NIVEL_DEL_RIO_14H`,
  `NIVEL_DEL_RIO_18H`, `NIVEL_DEL_RIO_PROMEDIO`;
- `N_NIVELAGUA`, `N_NIVELMEDIO`, `N_NIV_INST_00`, `N_NIV_INST_10`.

A monthly response partition does not establish monthly measurement frequency.
Do not combine synoptic readings, derive unpublished averages, or equate similarly
named fields. Meteorological fields remain outside scope. Catalogue candidates
do not promise observations for every station or period.

## Physical facts and explicit unknowns

Map established discharge and water-level quantities and response units. Preserve
source spellings `m3/s`, `m` and `m.s.n.m`, using the existing normalized units.
For water level, `m.s.n.m` establishes an above-sea-level reference, not a named
vertical datum. Normalizing it to metres does not convert it to relative gauge
stage. `m` alone does not establish the reference. Station altitude and conflicting
`levelType` labels must not supply observation datum facts.

Deliver useful mappings with unresolved facts explicitly unknown. Agency response
is not an acceptance prerequisite for independently supported mappings. Do not
claim a time zone, temporal support, day boundary, timestamp anchor, statistic or
frequency from geography, regular spacing or a field identifier alone. Unknown
facts cannot satisfy filters requiring those facts. Preserve the existing
distinction between unestablished facts and facts the source explicitly leaves
unspecified.

The bounded investigation found these limits:

- The official frontend labels DAILY `current` as the current year, not explicitly
  a daily mean. `minimum` and `maximum` do not establish their aggregation period.
  Preserve the fields without assigning unsupported standardized statistics.
- The official 2018 [Manual de Hidrometría](https://www.senamhi.gob.pe/load/file/00701SENA-924.pdf),
  printed page 16, describes conventional readings at 06, 10, 14 and 18 hours and
  their arithmetic average as an estimate of daily level. It does not bind that
  procedure to every API field or historical record, establish a time zone, or
  specify missing-reading handling. Do not infer a continuous daily mean.
- The less-common `N_NIV*` identifiers do not establish their processing or support.
  In particular, `00` and `10` must not become inferred clock times.
- Frontend handling of offset-free dates and times does not establish UTC or
  America/Lima. UTC-5 text for other views is not evidence for these routes.
- A frontend helper treats values `<= -999` as missing in some displays and
  exports, but the hydrogram chart passes values through. Do not apply a blanket
  sentinel conversion without applicable field/route evidence. Preserve published
  values, including negative values; distinguish nulls, absent rows and failures.
- Near-real-time revision notices describe the product. Station operation codes,
  alert colors and response-envelope status are not observation-quality flags.
  Preserve any actually established source statuses without assigning a ranking.
  Do not invent row-status machinery for codes not witnessed in observations.
- Four retained monthly responses contain December 2026 dates and non-null values
  despite October acquisition. Their cause is unknown. Do not correct dates,
  discard values or label them forecasts. Carry this into retrieval research;
  sampled dates are not certified coverage boundaries.

## Implementation boundaries

Use existing `SourceIdentity`, `PhysicalFacts` and admission contracts. They already
support numeric admission with unknown time zone, support and datum when quantity,
source unit and conversion are established. Keep source identity separate from
physical interpretation and align catalogue descriptions with the new definitions.
Any changes to packaged catalogue products require their normal rebuild and review.

The present PHISIS catalogue describes route/resolution/variable/unit associations;
it does not distinguish the three daily fields. `SeriesMapping` identity hashing
excludes the product, and its parsing helper emits one identity per product.
Do not mechanically reuse the same namespace and published ID across daily fields
or resolutions. Choose the smallest mapping structure that preserves all source
identities and can be consumed by later parsing. A shared helper redesign or
row-status extension is not a required outcome. Leave reversible code organization
and product representation choices to implementation, while preserving distinct
records and existing discovery coverage.

## Evidence, correspondence and verification

Follow [provider-port step 3](../../docs/maintenance/provider-ports.md), the
[evidence process](../../docs/maintenance/evidence.md), and the
[testing guide](../../docs/maintenance/testing.md). Continue the existing private
[SENAMHI research record](https://github.com/RivRetrieve/verification-evidence/blob/main/research/pe-senamhi-source-access.md).
Use its exact retained access and catalogue collections; do not substitute derived
metadata for original observation evidence.

The new frontend and manual inspection supplies research leads, not completed
source certification. Retain applicable originals through the established private
archive process and bind adopted claims to reviewed evidence. Record corrections
to older suggestions of daily means, Lima time and blanket missing-value rules.
Keep raw bodies, correspondence and restricted receipts outside the public package,
issues and logs. Any further source requests must be bounded and at most one per
second. Do not require a full historical scan to deliver these mappings.

Pursue focused agency clarification in parallel. The official monitoring page
lists `atencionalciudadano@senamhi.gob.pe` for enquiries; request routing to the
hydrology or Observatorio team. A short Spanish draft was prepared, but no message
was sent. Sending requires explicit authorization. Ask about field meanings,
aggregation periods, time conventions, missing-value codes and observation-quality
indicators. Retain any reply privately, establish its scope, then update mappings,
tests and documentation as needed. A reply can correct an assumption as well as
fill an unknown. Lack of a reply does not justify a guessed meaning.

Protect the named behavior with focused tests: distinct identities across routes,
resolutions and fields; correct quantity/unit conversion and reference retention;
unknown facts remaining unknown and failing incompatible physical filters; and
no unsupported statistical, time or missing-value interpretation. Use genuine
retained inputs to verify adopted source claims and the real source exceptions.
Synthetic cases establish code behavior, not source meaning.

Run affected source-independent checks and applicable full genuine-input checks
at reviewed revisions. Missing mandatory evidence blocks the affected claim or
capability, not unrelated supported mappings. It is not a passing or skipped
acceptance check. Complete #605 only when the mappings, aligned discovery metadata,
evidence and tests are reviewed and verified. Report exact revisions, checks,
remaining unknowns and the handoff to retrieval and integration. No observation
retrieval implementation is required to complete this Effort.
