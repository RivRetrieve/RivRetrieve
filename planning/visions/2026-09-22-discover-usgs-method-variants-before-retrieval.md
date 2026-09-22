# Migrate USGS to the modern API with offline variant discovery

Related issues:
- https://github.com/RivRetrieve/RivRetrieve/issues/279
- https://github.com/RivRetrieve/RivRetrieve/issues/327

## Outcome and authority

Migrate the USGS provider to the modern Water Data API v1 and deliver concrete,
publisher-backed series discovery before observation retrieval. Successful
implementation and verified delivery are intended to resolve both issues. An
endpoint change alone is not delivery, and publication of this vision leaves both
issues open.

This revision explicitly supersedes this file's earlier legacy-focused mechanism:
joining Site Service numeric identifiers to legacy JSON method identities is no
longer the implementation direction. Retain its offline-discovery outcome,
source-fidelity constraints, and historical evidence. Never infer a daily
`NWIS.ts_id == methodID` rule or alias either to modern opaque identifiers.

The owner confirmed this scope after a fresh capability assessment on 2026-09-22.
The repository is private and has no users. Coherent provider responsibilities
and faithful source handling take priority over implementation cost or preserving
development-only internals. Internal refactoring and explicit development-artifact
incompatibility are permitted. Silent reinterpretation of retained evidence is not.

## Caller-visible behavior

The public workflow remains:

```python
import rivretrieve as rr

selection = rr.find(
    provider="usgs_nwis",
    station="07374000",
    quantity="discharge",
    frequency="daily",
    statistic="mean",
)

variants = rr.series(selection)
print(variants)

# Use an actual publisher ID exposed by this dated catalogue snapshot.
chosen = rr.pick(selection, variant="c9d823a2491f4b639656a11b35a7625d")
result = rr.fetch(chosen, start="2024-01-01", end="2024-01-07", cache="bypass")
```

The example ID is recorded source evidence, not an identifier to hard-code.
At catalogue preparation, acquire publisher series identities, descriptions,
physical facts and acquisition provenance. Package a dated snapshot. `find` and
`series(selection)` must remain offline; no hidden observation acquisition and no
new online discovery API are required.

Concrete variants must be inspectable and selectable before retrieval. Use the
publisher-documented metadata `id` to observation `time_series_id` relationship.
Selecting one series must not select its siblings. An unrestricted selection must
retain all-matching intent, including legitimate identities encountered during
retrieval that were absent from the packaged snapshot.

## Scope and settled choices

Retain the existing station/product scope: the present catalogue acquisition is
stream sites with daily-data filters across the 50 states plus DC, not every USGS
monitoring location. Do not broaden that scope incidentally during migration.
The six products are:

- discharge daily mean;
- stage daily mean, maximum and minimum;
- instantaneous discharge and stage.

Prefer modern-only v1 retrieval for these products. The earlier instantaneous
history blocker was not reproduced. Do not build a legacy hybrid without a
concrete unmet requirement. If implementation discovers an actual historical
coverage loss, bring the specific case and scope trade-off back to the owner;
do not silently drop history or invent cross-service aliases.

Preserve modern descriptions exactly, including empty strings when published and
null when unknown. The modern examples below publish null, not the legacy empty
strings or `[(2)]`. This difference is accepted. Do not substitute parameter prose,
parse meanings from identifiers, rank variants, or collapse equal-valued series.
Retain independent legacy evidence without attaching it to a modern identity
through coincident values or date ranges.

Temperature expansion (#265) and provider documentation PR #266 remain excluded.
A focused explanation of the delivered discovery contract and actual service
limits is in scope, not a provider-page rewrite. Resume #266 separately after
delivery and revalidation of the resulting API behavior.

## Fresh capability evidence

The following are bounded observations, not a complete national inventory or a
proof of universal historical parity.

### Version and historical access

USGS's September 4, 2026 announcement confirms v1 and explains automatic migration
of unaffected v0 requests. Explicit v1 requests succeeded with `Api-Version: 1.2.0`.
Some older documentation still says only v0 exists; do not use that stale statement
or mixed v0 response links to choose version semantics.

At `07374000`, modern instantaneous discharge and stage each returned 96 readings
for the same instants as legacy local day 2010-06-01. All timestamps and numeric
values matched after normalizing the legacy published `-05:00` offset and parsing
decimal values. The modern comparison window was
`2010-06-01T05:00:00Z/2010-06-02T04:59:59Z`. No station time zone was guessed.
Explicit v0 old-window requests also succeeded. An undated ascending query began
in September 2025; it did not establish the earliest available observation.

A deliberately oversized continuous query returned HTTP 400 with a maximum time
envelope of 1100 days. This is a request-size constraint, not missing history.
Plan bounded windows and exhaust pagination for the claimed scope. Do not use a
small sorted page as inventory proof; captured OpenAPI documentation warns of
single-page behavior with sorting.

USGS's September 18 announcement schedules WaterServices retirement for February
22, 2027, with delays beginning November 16, 2026 and earlier scheduled outages.
A long-lived legacy dependency is therefore not a safe default.

### Daily discovery and selection

All four daily products at `07374000` returned seven observations for January
1–7, 2024 through explicit v1 series-ID filters:

| Product | Recorded modern series ID |
| --- | --- |
| Discharge mean | `c9d823a2491f4b639656a11b35a7625d` |
| Stage mean | `bfeb7499f6534c28a55bd5233be77dee` |
| Stage maximum | `c528776d79a2450691596aeed52a0256` |
| Stage minimum | `549680d3ae704283bc5c68850198038d` |

At `02196000`, metadata publishes two daily mean discharge series:
`0df18b246e8f48ec8e6547a92070e94a` and
`4d186669708e4dc18f84d271efb953a1`. The latter ends in September 2005.
Each individually returned seven observations for January 1–7, 2000. The
unrestricted query returned both, with 14 rows. The ended series returned zero
rows in checked later windows. A publisher cursor chain returned 5 + 5 + 4 rows,
then no next link, matching the unrestricted result. Its initial request was v0;
publisher next links targeted v1. Test the chosen v1 path explicitly in delivery.

Both siblings and the `07374000` discharge mean example publish null
`web_description` and `sublocation_identifier`. The migration guide's conceptual
field mapping is not a per-record crosswalk from old numeric IDs to modern IDs.
Observation feature `id` is an unstable record-version identifier; it is not the
series identity. Publisher schemas identify observations by series and time.

### Physical representation and source vocabulary

Recorded daily observations use date-only labels, decimal strings and units
`ft^3/s` or `ft`. Modern continuous observations publish offset-bearing UTC times.
Preserve the new source representation explicitly rather than pretending it is
the legacy local representation. Do not use UTC metadata range boundaries as
physical support bounds for date-only daily observations. Never infer day
boundaries, time zones, temporal support or unpublished hydrological products.

Recorded modern vocabulary includes `Approved`, `Provisional`, `ESTIMATED`, and
`DISCONTINUED`. Preserve source terms without translating them into legacy A/e
codes or scientific judgments. A bounded query recorded a present null daily
value at `USGS-11465200` on 2024-01-05, distinct from an absent row or failed
request. That evidence probe does not expand implementation station scope.

Schema declarations are not always accurate: qualifier is declared a string but
published as arrays or null, and value is declared a string but can be null.
V1 metadata begin/end include UTC offsets, unlike the old v0 local-looking fields.
Validate actual boundary inputs using publisher documentation and recordings
together, not generated schema assumptions alone.

## Fidelity, completeness and compatibility

- Establish returned station, parameter, statistic and units from source facts;
  reject contradictions without silently substituting configured defaults.
- Preserve dates/times, zone facts, descriptions, vocabulary and null/absent states.
  Keep exact source receipts and acquisition provenance. Do not promise a new
  normalized quality interpretation or unrelated public quality API.
- Keep catalogue inventory vintage, period-of-record claims, successful finite
  observation windows and exhaustive historical availability distinct. Source
  metadata can lag observations and its date ranges may contain gaps.
- Exhaust metadata and observation pagination for every claimed acquisition scope.
  Preserve explicit completeness limits and identified failures. A partially
  acquired inventory must not masquerade as complete all-series coverage.
- Keep independent series usable when supported source failures occur. Retain
  failure identity and reason. Fatal internal contract errors must still raise
  regardless of caller issue policy.
- Use an explicit modern source-identity namespace and deliberate cache/export
  compatibility behavior. Existing numeric variants and hashed series IDs must
  not silently become modern IDs. Unsupported development caches and bundles may
  be refused or invalidated explicitly, leaving retained files/evidence intact.
  No automatic destructive migration or cross-service aliasing is authorized.
- Resolve optional credentials, paths and transport wiring at composition
  boundaries. Modest live probes worked without a key; key documentation permits
  higher limits. Do not treat example quotas as universal limits. Preserve rate
  limit and access failures as failures, not missing data.

## Repository context

Read `AGENTS.md` and `docs/architecture.md`. Use stable domain responsibilities,
not issue-shaped architecture, and retain typed fetch/parse/convert contracts.
Reversible module layout and acquisition details belong to the implementing agent.

Under `src/rivretrieve/_internal/`:

- `providers/usgs_nwis/generate_catalogue.py` currently acquires legacy Site RDB
  metadata and maps the six routes. Modern acquisition must preserve intended
  station scope and provenance rather than simply replacing URLs.
- `providers/usgs_nwis/catalogue_series.py` currently retains `NWIS.ts_id` claims
  separately from executable identities. `parse.py` builds legacy `methodID` or
  `methodCode` identities. Replace the mechanism, not the source evidence's meaning.
- `catalogues/source_series.py` materializes packaged descriptions and currently
  clears inventory members when separate catalogue claims exist. Reconcile this
  with modern executable identities without upgrading completeness by accident.
- `selection.py`, `discovery.py`, the shared driver and store preserve selection
  intent, inventories, outcomes and cache coverage. Inspect these contracts when
  changing identity or all-series acquisition behavior.
- `providers/no_nve/catalogue_series.py` demonstrates concrete offline variants,
  but its provider semantics are not a USGS contract.

## Acceptance and delivery

1. Demonstrate offline `find` and `series(selection)` with concrete variants and
   exact modern descriptions for the two example stations, including the ended
   sibling. Assert that inspection does not contact a source.
2. Demonstrate public discovery → pick → fetch selecting only the intended modern
   series. Unrestricted retrieval must retain newly encountered identities.
3. Validate all six product routes, physical conversions and time semantics.
   Retain bounded historical daily/instantaneous checks, discontinued-series and
   empty-window cases, present nulls, and complete multi-page acquisition.
   Do not describe samples as a complete historical inventory or parity proof.
4. Test source-boundary contradictions, malformed responses, pagination failures
   and independent-series partial results. Label authored negative controls
   separately from untouched publisher recordings.
5. Test explicit subsets versus all-series cache reuse, successful and failed
   refresh, identity incompatibility, selection/result bundle round-trips,
   provenance and receipts. No false completeness or silent reuse of legacy IDs.
6. Commit the publisher evidence needed by implementation: exact response bytes,
   request coordinates, UTC acquisition times and hashes. Local ignored research
   is not a durable dependency. Preserve independent earlier evidence.
7. Run focused tests and relevant regressions, formatting/lint, and
   `uv run ty check src`, using the project environment. Obtain independent review
   and validate actual target-branch effects before claiming delivery.
8. Report the delivered scope and service limits. Both #279 and #327 remain open
   until migration and the offline selection workflow are demonstrated. Report
   any undelivered scope instead of claiming success from endpoint replacement.

## Research handoff and authoritative sources

Local ignored research, available in the originating checkout, contains reports,
request manifests and exact captures:

- `.worktrees/usgs-modern-daily-assessment/REPORT.md` and `manifest.jsonl`;
- `.worktrees/usgs-modern-history-assessment/REPORT.md` and `manifest.json`;
- the older research locations enumerated in #279, including
  `.worktrees/usgs-daily-rdb-evidence/REPORT.md` and
  `.worktrees/usgs-daily-rdb-feasibility/REPORT.md`.

These are optional starting evidence, not required files in a fresh checkout.
Reacquire or commit appropriate recordings during implementation; this vision
publishes requirements and bounded findings, not a production implementation.
Earlier baseline test counts in the issues do not validate the migration.

Publisher references:

- https://api.waterdata.usgs.gov/ogcapi/v1/
- https://api.waterdata.usgs.gov/ogcapi/v1/collections/time-series-metadata/schema
- https://api.waterdata.usgs.gov/ogcapi/v1/collections/daily/schema
- https://api.waterdata.usgs.gov/ogcapi/v1/collections/continuous/queryables
- https://api.waterdata.usgs.gov/docs/ogcapi/migration/
- https://waterdata.usgs.gov/blog/api-v1-release/
- https://waterdata.usgs.gov/blog/wdfn-waterservices-degradation/
