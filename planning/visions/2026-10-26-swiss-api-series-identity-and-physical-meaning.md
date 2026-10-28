# Swiss API series identity and physical meaning

Give official Swiss observation series evidence-backed definitions that catalogue
generation and later parsing can share. Preserve each publication's identity and
physical meaning without guessing missing facts or merging distinct measurements.

This vision implements [Effort #561](https://github.com/RivRetrieve/RivRetrieve/issues/561)
in [Program #545](https://github.com/RivRetrieve/RivRetrieve/issues/545). Completing
its definitions, evidence-backed handoff and verification completes #561, not the
whole Swiss port. Publishing this vision alone completes neither. Work targets
`port/swiss-official-api`; keep `main` unchanged until coordinated port integration.

## Outcome and boundaries

Deliver reusable Swiss series definitions, integrate them into catalogue source
descriptions, and leave a verified handoff for observation parsing. Use the official
Q/W/WT publications: archive ten-minute/hourly means, daily/monthly/yearly
mean/minimum/maximum products, and the separate recent feed. Availability remains
source-observed, not every station multiplied by every product. The
[approved scope correction](https://github.com/RivRetrieve/RivRetrieve/issues/545#issuecomment-6296750847)
adopts BAFU products rather than requiring identical replacement of Existenz streams.

Fetching, request subdivision, retention policy, cache behavior, clipping integration
and provider activation remain #562/#563. Do not implement those here. Do not add
LINDAS, runtime API/file fallback, a national-download feature, a new raw-data API,
computed hydrological products or datum transformations. Do not correct implausible
source values or select a preferred variant.

## Preserve identity separately from meaning

Reuse the catalogue's station, route, parameter and raw `tsName` coordinates. Keep
archive and recent products separate even when their timestamps overlap. Preserve
both unsuffixed and `_01` variants at station 2602, without assigning sensor IDs,
preference or quality from their names. No stable publisher series ID or rename
policy has been established.

Catalogue and response definitions must resolve the same source identity. New
physical knowledge must not rename a series. Distinct units within an identity
remain separate physical-fact segments. The catalogue remains an incomplete
inventory of witnessed associations, including null-only series; sample dates are
not record boundaries. Preserve leading zeros in station identifiers.

## Established physical meanings

- Bind archive units to the published archive fields. Bind recent units to the
  authoritative station-page parameter labels, as established by #560 and BAFU.
  Missing recent units remain unknown; never borrow archive units or apply one
  global discharge/water-level unit. Use shared dimensional conversion, keeping
  native unit scale and reference distinct from normalized output units.
- BAFU confirms the historical 2282 example's Q unit m³/s and W unit metres above
  sea level. Its gauge-zero explanation of 890.00 m applies to that example; it is
  not a network-wide offset or proof of historical validity. No offset conversion
  between archive and recent products is required.
- Ordinary archive ten-minute/hourly products are means over their documented
  intervals, with interval-start timestamps. Daily/monthly/yearly products use
  calendar periods beginning at midnight in fixed UTC+1, including summer.
  Months and years are calendar periods, not fixed 30/365-day durations.
- API timestamps are serialized in UTC. Keep that timestamp zone separate from
  the fixed-UTC+1 aggregation calendar. BAFU confirms that the monthly label
  `2025-01-31T23:00:00Z` describes February, with interval
  `[2025-01-31T23:00:00Z, 2025-02-28T23:00:00Z)`. Do not relabel the same clock
  value as UTC+1 or assign the aggregate to January from its UTC date.
- Minimum/maximum products describe the lowest/highest short-term measurement,
  not extrema of daily means. Their aggregate window can be known while the
  underlying measurement's averaging duration remains unknown. The aggregate
  label is not the time at which the extreme occurred. Do not infer an exact
  averaging algorithm or missing-input threshold.
- Recent timestamps mark measurement end. Preserve unknown exact per-series
  averaging durations; observed spacing and general river/lake rules do not
  establish them. Do not turn unknown duration into instantaneous support or
  invent interval starts.
- Above-sea-level unit labels establish the vertical reference. The official FAQ
  names LN02 generally, but the approved per-series named datum remains unknown
  without the applicable binding evidence. Station altitude is not a datum.

These normal product meanings do not override known exceptions. At station 7008,
`MonatsMittel_Orbe_flex` in `data_1day_mean` remains unresolved. Preserve its
identity, units, timestamps and nulls without assigning daily support from the
route, monthly support from the name, or five-minute support from its cadence.
Do not silently drop it or block independent series.

## Nulls, source statuses and unknown facts

Keep null measurements, numeric zero, absent rows and failed requests distinct.
Preserve raw status fields and their original codes/nulls, including the distinction
between archive `releaseState` and recent `releaseStatus`.

Record the publisher vocabulary separately from raw encoding. BAFU explains null
release status as raw/status 0; preserve the published null rather than rewriting
it to 0. Its replies describe 0 as raw, 1 as unreleased/prechecked, 2 as
released/checked and 3 as released/definitive. The latest reply explains status 3
through corrections from status 2 and definitive stage–discharge relations. This
is source judgement, not a RivRetrieve quality ranking or a new filtering policy.
The documentation's word `ersetzt` is still being checked by BAFU; do not infer
replacement lineage or treat the proposed internal misunderstanding as established.

Use independent knowledge states for physical facts. Admission requires established
quantity, native unit and valid conversion. Unknown support, calendar or datum
need not prevent otherwise honest retrieval, but cannot satisfy a physical filter
requiring that fact. Do not present an optional unknown as a blanket unsupported
series. Unknown source facts are not defaults.

## Repository context and implementation discretion

Research inspected Swiss branch revision
`663a74333dd3cbdfbc7eedf7d883a80c854ec4f8`; recheck current code before implementing.

- `src/rivretrieve/_internal/source_series.py` provides `SourceIdentity`,
  `PhysicalFacts`, `SourceSeries`, admission and known-fact filtering. Reuse these
  contracts rather than introduce another series or knowledge-state system.
- `src/rivretrieve/_internal/providers/ch_foen/generate_catalogue.py` already
  groups witnessed station/route/parameter/raw-name associations, separates unit
  segments and binds recent station-page units. Its descriptions currently leave
  temporal meaning unknown. Extend this existing publication path using the shared
  Swiss definitions; do not maintain parallel mappings for catalogue and parsing.
- `SeriesMapping` in `_internal/provider_series.py` is a convenience, not a
  required representation. It automatically selects calendar-date clipping for
  daily frequency. That is unsafe if it classifies a UTC 23:00 label using the
  preceding date. Preserve the timestamp/calendar distinction in #561 and carry
  correct request/clipping behavior into #562/#563. Do not solve retrieval here.
- The provider remains `CatalogueOnly()` until the later integration Effort.
  Legacy Existenz mappings on disk are not official API series identities.

Choose small internal interfaces and the simplest sufficient tests during
implementation. Definitions should accept established source coordinates and
resolved evidence/unit bindings without fetching or discovering application state.
This vision does not prescribe new classes, a rule engine or a public status API.

## Evidence and acceptance

Build on the [correspondence summary](https://github.com/RivRetrieve/RivRetrieve/issues/561#issuecomment-6422928920),
[final research audit](https://github.com/RivRetrieve/RivRetrieve/issues/561#issuecomment-6423152022),
[official product documentation](https://data.bafu.admin.ch/dataproduct-water-observations),
[official FAQ](https://www.hydrodaten.admin.ch/en/questions), and the continuing
[private research record](https://github.com/RivRetrieve/verification-evidence/blob/main/research/swiss-source-access.md).
Do not restart completed source discovery or turn these public summaries into
substitutes for retained originals.

Before accepting changed source bindings, retain the new correspondence using the
private archive's intake process and update the continuing research record. This
authoring session has not archived those originals. Keep correspondence, controlled
responses and credentials out of public source, logs and distribution artifacts.
Follow `docs/maintenance/evidence.md` and the archive's current procedure: review
exact revisions before execution with private evidence, select genuine retained
inputs, and run the applicable full checks. Missing mandatory material blocks
acceptance; synthetic tests or fresh observations do not replace it.

Completion must demonstrate:

- Catalogue and later-parser definition entry points agree on source identity and
  supported physical facts; both 2602 variants and archive/recent separation survive.
- Unit handling preserves native scale/reference and admits only supported
  quantity/unit conversions, including the archive/recent difference at 2282.
- Ordinary archive definitions express documented means/extrema and support;
  calendar examples cover summer and variable month/year length without changing
  UTC timestamp meaning.
- Recent durations and the 7008 exception remain explicit unknowns. Known-fact
  filters cannot match unestablished support, while optional unknowns do not
  defeat otherwise valid admission.
- Null/status handling preserves source encoding and documented meaning without
  ranking quality, erasing values or inventing replacement history.
- Updated catalogue descriptions and provenance pass affected source-independent
  checks and the applicable genuine-input checks for changed bindings. Review
  approved runtime artifacts for disclosure before publication.

Use meaningful behavior assertions at the simplest sufficient level, extending
existing contracts rather than duplicating them. Report exact evidence, checks and
limitations in the completion handoff. Keep documentation accurate for the delivered
definitions; the complete provider user guide remains #565.

BAFU's unresolved 7008 mapping, recent durations and `ersetzt` wording do not block
this scoped outcome. Live retention remains with #562. A later source reply may
refine individual facts without changing preserved identities. No further source
question is required before starting this work; new conflicting evidence must be
investigated rather than hidden by a default.
