# Complete source-annotation adoption

Complete [Program #809](https://github.com/RivRetrieve/RivRetrieve/issues/809)
for its twelve remaining providers. Users should be able to inspect supported
source-published observation and series annotations without recovering original
responses, while providers with no applicable annotations have an evidence-backed
audit establishing that outcome.

This vision delivers [#815](https://github.com/RivRetrieve/RivRetrieve/issues/815)
and [#818–#828](https://github.com/RivRetrieve/RivRetrieve/issues/809#issuecomment-6860795374).
Implementation completes each Effort only after its supported-route audit and
applicable integration, documentation and genuine-source verification. Completing
all remaining Efforts completes #809. Publishing this vision completes none of
these issues.

The implementing agent decides how to delegate, sequence delivery and divide PRs.
One vision does not require one implementation PR. Keep provider completion and
evidence individually traceable; a blocked provider need not prevent delivery of
another, but remains unfinished.

## Established foundation and boundaries

The shared core (#812) and adoptions for USGS (#813), Canada (#814), Switzerland
(#816) and HydroPortail (#817) are complete. Reuse their implementations and the
[core vision](2026-11-13-source-annotations-core-and-usgs.md). They establish working
patterns, not source meanings for another provider. A bounded code review found
no demonstrated missing shared annotation capability; it did not certify the
remaining sources.

Follow the [approved Program design](https://github.com/RivRetrieve/RivRetrieve/issues/809#issuecomment-6860795374):

- Keep default observation and series schemas unchanged. Use the existing
  `annotations=` convention on `result.to_polars()`, `result.to_pandas()` and
  `rr.series()`, and `rr.annotations()` for discovery and direct schema access.
- Preserve source fields, native types and values in route-appropriate schemas,
  with verified short descriptions and official references. Distinguish explicit
  null, absent fields and route applicability. Do not introduce wrapper structs,
  placeholder descriptions, quality rankings or automatic filtering.
- Keep non-identity series attributes at series grain and stream selectors in
  `SourceSeries.variant`. Preserve deterministic measurements and exact
  measurement/annotation associations, including repeated-delivery handling.
- Preserve annotations through clipping, `pick`, `to_utc`, cache reuse, manual
  refresh, compiled stores where applicable, and bundles. Status-only refreshes
  can update annotations within proven successful coverage or snapshot keys;
  failed requests must preserve held data under the shared rules.
- Distinguish published-null measurements from unmeasured source slots, absent
  rows and failed requests. Do not manufacture measurements or source positions.
- Retire QC-only informational issues when annotations replace them. Preserve
  retrieval, structural, coverage and provenance diagnostics.

Limit adoption to existing supported products and routes. Do not broaden provider
coverage, reinterpret physical facts, change series selection, or reopen the shared
API and storage design without a demonstrated defect. Station metadata remains
under #602. Interval-range annotation tables, automatic refresh, full-source
prefetch and observation flags in packaged catalogues remain excluded. The
Program's exclusions for `za_dws` and new provider ports remain unchanged.

## Remaining provider work

The entries below are audit starting points, not certified field inventories.
Audit supported source responses and documentation for additional observation or
non-identity series fields. Establish each adopted field's grain, native type,
applicability, description and official reference. Record justified inclusions,
exclusions and source limits in the existing private provider research record.

| Effort | Provider | Starting point and specific care |
| --- | --- | --- |
| [#815](https://github.com/RivRetrieve/RivRetrieve/issues/815) | `jp_mlit` | Preserve measured flags and genuine unmeasured-slot markers, including exact `$`, `#` and `-` strings, across supported daily/hourly routes. Keep calendar padding and hour-boundary handling distinct from real slots. Retire superseded marker summaries. |
| [#818](https://github.com/RivRetrieve/RivRetrieve/issues/818) | `fr_hubeau` | Audit `obs_elab` and `temperature/chronique` separately for status, qualification, method, continuity and other applicable fields. Use route-appropriate schemas rather than assuming similarly named fields have the same meaning. |
| [#819](https://github.com/RivRetrieve/RivRetrieve/issues/819) | `fi_syke` | Expose `Lippu_id` on discharge and stage; audit other fields and temperature routes without inventing flags. Retire per-row `source.flag_code` issues. Preserve the source vocabulary without interpreting every code as quality. |
| [#820](https://github.com/RivRetrieve/RivRetrieve/issues/820) | `no_nve` | Preserve independent `quality` and `correction` integer codes and audit other fields. Keep existing version identity and physical distinctions. Retire superseded summary flag issues. |
| [#821](https://github.com/RivRetrieve/RivRetrieve/issues/821) | `br_ana` | Audit daily and telemetry routes, preserving status/quality fields and their day/value associations. Keep daily consistency selectors in series identity and retain existing conflict handling rather than ranking records by status. Retire superseded status summaries. |
| [#822](https://github.com/RivRetrieve/RivRetrieve/issues/822) | `at_ehyd` | Audit route/series quality classifications and non-harmonized headers for series annotations. Establish which timestamped `Lücke` markers are genuine unmeasured positions and which are boundaries. Do not expand gap transitions into invented slots or intervals, or force untimed response markers into observation grain. Retire diagnostics only where annotations faithfully replace them. |
| [#823](https://github.com/RivRetrieve/RivRetrieve/issues/823) | `pl_imgw` | Audit genuine daily CSV archives, including `month_indicator` and non-measurement cells. Adopt supported annotations through the compiled store, or establish their absence. Existing retained native cells and value states alone do not establish annotation semantics. |
| [#824](https://github.com/RivRetrieve/RivRetrieve/issues/824) | `ba_fhmzbih` | Audit genuine supported workbooks and source documentation; adopt applicable fields or record verified absence. |
| [#825](https://github.com/RivRetrieve/RivRetrieve/issues/825) | `cz_chmi` | Audit genuine supported payloads and source documentation; adopt applicable fields or record verified absence. |
| [#826](https://github.com/RivRetrieve/RivRetrieve/issues/826) | `lt_lhmt` | Audit genuine supported API payloads and source documentation; adopt applicable fields or record verified absence. |
| [#827](https://github.com/RivRetrieve/RivRetrieve/issues/827) | `pe_senamhi` | Audit genuine supported payloads and source documentation; adopt applicable fields or record verified absence. |
| [#828](https://github.com/RivRetrieve/RivRetrieve/issues/828) | `th_thaiwater` | Audit genuine supported payloads and source documentation; adopt applicable fields or record verified absence. |

Verified absence is a valid result. Do not add empty placeholder schemas or change
code solely to make every provider look migrated. A parser that currently selects
only measurement fields does not prove the source has no annotations.

Japan's unmeasured slots and Austria's series attributes and gap markers deserve
particular source checks. The shared model supports both annotation grains and
unmeasured slots; unresolved source meaning is not evidence that a new model is
needed. Missing required facts or evidence block the affected capability. Do not
guess meanings or silently omit unresolved candidates to declare completion.

## Evidence of completion

Use the [provider port guide](../../docs/maintenance/provider-ports.md),
[testing guide](../../docs/maintenance/testing.md) and
[evidence guide](../../docs/maintenance/evidence.md). Reuse existing private
research and retained inputs rather than starting parallel records.

For each provider, report the audited routes, adopted fields and schemas,
justified exclusions or verified absence, exact evidence references, completed
checks and remaining limitations. Code inspection and synthetic tests do not
establish source meanings or absence. Every shipped field needs its verified
short description and official reference; exhaustive code dictionaries are not
required.

Protect provider-specific behavior at the simplest sufficient level: native
values and nulls, route applicability, exact associations, unmeasured markers,
series identity, duplicate/conflicting deliveries and superseded issue handling
where relevant. Extend shared contracts instead of copying the full engine suite
for every provider. Demonstrate that adopted annotations reach public inspection
and survive the applicable selection, time conversion, cache/refresh and bundle
paths. For bulk adoption, include compilation, selective reads and download
replacement. Default harmonized schemas must remain unchanged.

Run affected source-independent tests, formatting, lint and type checks through
`uv`, using temporary cache and store roots. Verify adopted source claims and
applicable routes against genuine retained inputs through the private archive,
using reviewed exact code and archive revisions. Run applicable full checks when
source bindings, governing claims, verifiers or collections change. Missing
mandatory evidence blocks acceptance; a skipped check, synthetic fixture or live
probe is not a replacement. Keep controlled material and credentials outside
public code, logs and artifacts.

Update affected provider pages to explain delivered annotations, field meanings
and source-specific limits, with verified practical examples where annotations
are adopted. Link common API usage instead of repeating it. For verified-absence
outcomes, retain the bounded audit result without manufacturing a feature or an
example. Keep unresolved evidence visible and leave the affected Effort open.
