# SENAMHI provider integration

Make SENAMHI observations available through RivRetrieve's existing selection,
retrieval and cache interfaces under `pe_senamhi`. Deliver the complete agreed
scope for [Effort #607](https://github.com/RivRetrieve/RivRetrieve/issues/607)
and [Program #534](https://github.com/RivRetrieve/RivRetrieve/issues/534).
Completing this integration and its applicable verification completes #607;
publishing this vision does not.

Work targets `port/pe-senamhi`. Keep `main` unchanged until the Program's final
review approves merging. Full-provider verification remains in
[#608](https://github.com/RivRetrieve/RivRetrieve/issues/608), and the provider
page finish remains in [#609](https://github.com/RivRetrieve/RivRetrieve/issues/609).
Those separate Efforts do not defer checks needed to establish correct integration.

## Build on the delivered provider work

At target revision `04200e4bca163d82f2204cf90e1be12b1dd488e8`,
[#604](https://github.com/RivRetrieve/RivRetrieve/issues/604),
[#605](https://github.com/RivRetrieve/RivRetrieve/issues/605) and
[#606](https://github.com/RivRetrieve/RivRetrieve/issues/606) are complete:

- The packaged catalogue supports offline discovery of 771 station identities
  and 15 product candidates. Candidates do not promise data for every period.
- `providers/pe_senamhi/series.py` defines distinct source series and established
  physical facts, with unresolved facts left unknown.
- `providers/pe_senamhi/fetch.py` acquires daily hydrological-year, conservative
  two-day hourly and monthly partitions using engine-rendered windows. It retains
  original bytes, request origins and bounded source failures.
- The provider declaration remains `CatalogueOnly`; public retrieval is disabled
  and the observation parser is still to be implemented.

Use the delivered [catalogue](2026-10-31-senamhi-offline-station-catalogue.md),
[series](2026-11-01-senamhi-series-identity-and-physical-meaning.md) and
[retrieval](2026-11-01-senamhi-retrieval-behavior.md) contracts and their evidence.
Follow [provider-port step 5](../../docs/maintenance/provider-ports.md#5-provider-integration)
and continue the existing private
[SENAMHI research record](https://github.com/RivRetrieve/verification-evidence/blob/main/research/pe-senamhi-source-access.md).
Do not restart completed research or create a parallel evidence record.

## Deliver working public retrieval

Connect configuration, source coordinates, window declarations, fetch/parse stages
and provider registration through the existing public APIs. Use the adopted
unauthenticated `https://servicios.senamhi.gob.pe/api` routes. Reuse shared transport,
conversion, clipping, assembly and storage. Retain at most one request per second
through the established shared transport; no new limiter framework is required.

Start with a representative public end-to-end path, then cover the complete scope:

- PHISIS DAILY discharge and water level, keeping `current`, `minimum` and
  `maximum` separate.
- PHISIS HOURLY discharge and water level `value` series.
- The nine distinct monthly-archive water-level fields defined by the series
  mappings. A monthly request partition does not establish monthly measurement
  frequency.

Keep PHISIS and the monthly archive separate even at the same station. Preserve
canonical station IDs and existing source-series identities. Do not merge fields,
select a preferred series, derive unpublished products, or expose `previous`,
forecasts or historical averages as new products.

Follow the existing `fetch(start=..., end=...)` contract. Do not introduce an
all-history mode, invented record start, period-list restriction or early stop
at an empty window. No new public options, cache policy or cache architecture
is in scope. Registration alone does not complete this work: users must be able
to discover, retrieve and reuse observations through the normal interfaces.

## Preserve source meaning and interval ownership

Parse native rows, series definitions, inventories, outcomes and issues through
the established stage contracts. Preserve source timestamps, published values,
nulls and absent rows as distinct states. Supported source failures retain their
identity, reason and interval alongside independent successes; fatal internal
contract violations still raise. Failed envelopes and malformed responses must
not become successful empty results.

Use the established quantity and response-unit mappings. Keep `m.s.n.m`'s
above-sea-level reference distinct from an unestablished reference for `m`.
Do not infer a named datum, time zone, timestamp meaning, temporal support,
frequency, statistic or row-quality judgement. Do not apply a blanket sentinel
conversion to negative values. Preserve future-dated monthly values unchanged;
normal requested-range clipping still applies. Return to focused research if
parsing exposes a required fact that the existing evidence cannot establish.
Report a resulting capability blocker rather than silently narrowing scope.

Hourly source responses can extend before their planned partition and overlap
another response. `Payload.fetch_window` carries the disjoint interval owned by
each acquisition. Enforce that ownership through the shared integration path
before combining snapshots, including when the source has revised overlapping
values. Clipping only to the caller's overall range is insufficient. Generic
duplicate removal must not substitute for interval ownership or discard
legitimate source duplicates. Keep the original response bytes intact.

## Verification and handoff

Develop focused test-first increments using the [testing guide](../../docs/maintenance/testing.md).
Extend existing contracts instead of duplicating the completed lower-level suites.
Demonstrate observable behavior through public selection and retrieval:

- Each supported route reaches retrieval without credentials and preserves its
  distinct fields, identities, units and explicit unknowns.
- Requested-range clipping and adjacent hourly partitions respect ownership,
  including overlapping responses with revised values.
- Independent results survive supported failures. Published nulls, absent rows,
  successful empty responses and failed requests remain distinguishable.
- Normal cache reuse, bypass and refresh preserve observations, source identity
  and provenance. Failed refreshes do not erase held successful data.

Use representative genuine retained responses and independently established
expectations for source-specific integration claims. Follow the
[evidence process](../../docs/maintenance/evidence.md), review exact revisions
before execution with private evidence, and run affected source-independent tests
and applicable full genuine-input checks. Prior acquisition checks are not proof
of the newly connected public path. Missing mandatory evidence blocks acceptance;
a skipped check is not a pass.

Keep original bodies, restricted receipts and correspondence out of public code,
logs, packages and artifacts. Further source checks must be bounded and politely
paced. The recorded cloud-network access restriction is an access failure, not an
empty response. Agency correspondence requires separate authorization. Retain
SENAMHI attribution and the established responsibility notice.

Keep changed interfaces and access descriptions accurate without expanding this
Effort into the full provider-page work. Report delivered behavior, exact revisions,
checks, evidence limits and the handoff to #608/#609. Reversible code organization,
wiring details and test mechanics remain implementation choices.
