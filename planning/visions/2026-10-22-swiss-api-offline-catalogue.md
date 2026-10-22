# Swiss API offline catalogue

Deliver a reproducible, source-backed offline catalogue for the official Swiss API under `ch_foen`. Users can discover stations and established historical and recent products without contacting a source. Completing and verifying this catalogue completes [Effort #560](https://github.com/RivRetrieve/RivRetrieve/issues/560), part of [Program #545](https://github.com/RivRetrieve/RivRetrieve/issues/545). Publishing this vision does not complete the Effort or the provider port.

## Scope

Keep one provider for anonymous official GraphQL historical access and the separate recent raw feed. The agreed quantities are discharge, water level and water temperature. Archive products are ten-minute/hourly means and daily/monthly/yearly means, minima and maxima. Historical and recent station coverage may differ. The later scope decision in #545 supersedes strict Existenz parity.

Build the catalogue from official API station metadata, retained observation evidence for station-product associations, and official station pages for live units and supplementary metadata. Do not create a separate provider, bulk-download feature, runtime file fallback or LINDAS integration. Prepared official observation CSVs can support catalogue construction and verification.

The separate Hydrological Data Service and its historical Excel directory are deferred. Preserve the research and explain the service under [#565](https://github.com/RivRetrieve/RivRetrieve/issues/565); do not make that ordering service or workbook an adopted input or dependency of this implementation.

Observation retrieval behavior belongs to #562 and provider integration to #563. Physical meaning and response-series identity belong to #561. Coordinate the catalogue's product descriptions and live-unit bindings with those contracts rather than inventing physical interpretations to populate fields. Catalogue delivery must not route official catalogue identities to the old Existenz implementation. Keep port work on a dedicated branch until coordinated integration is ready.

## Build from evidence

Use `stations.no`, archive `station.no` and recent `stationNo` as source identifiers, preserving strings and leading zeros. Validate adopted joins. Embedded archive station IDs are separate source facts, not replacements for station numbers or stable series identifiers.

Retain official names, source coordinates, status and supported descriptive metadata. Official documentation identifies API latitude/longitude as WGS84 and local coordinates as LV95. Current operational status must not exclude historical stations. Station-level coverage dates do not establish parameter or product coverage. Preserve published blanks, placeholders and unknowns without manufacturing metadata.

Preserve useful existing official station-page enrichment, including catchment area and altitude, where supported. New name mappings require genuine-input verification and the established disclosure approval. Missing optional fields need not block independent catalogue rows. Investigate missing-coordinate cases and represent them honestly; do not copy another station's coordinates or silently discard a station. Identify any necessary narrow shared-contract change explicitly.

Assemble product associations from observed route, station, parameter, raw series name and source units. National queries over narrow periods efficiently collect many associations. Retain exact successful windows and empty, failed and overflowing outcomes separately. Omit explicit response limits when completeness matters; subdivide or partition overflowing acquisition rather than accept a capped prefix. Collection windows and partition mechanics remain implementation choices, guided by uncovered stations and products rather than an arbitrary history cutoff. Do not filter out null-valued rows.

Do not turn all stations multiplied by all products into known series. Keep known associations separate from unknown availability and supported negative claims. An empty sampled window, absent page, missing file or withdrawn station does not prove general unavailability. Null-only series remain published associations. Earliest/latest sampled timestamps are not certified record boundaries. A useful catalogue can retain unresolved inventory while unrestricted retrieval discovers further series.

Use BAFU-endorsed station-page parameter/unit labels for recent observations. Validate the page's station identity and redirects. Live discharge can be l/s or m³/s, and water-level reference labels differ. Do not borrow archive units for live or vice versa. Preserve coexisting archive raw names without choosing a preferred variant or inferring sensors from suffixes.

API timestamps are UTC. Swiss civil time is UTC+1 in winter and UTC+2 in summer; general historical hydrological conventions include fixed UTC+1. These are different facts. Product-specific calendar bindings remain #561 work. The recent feed lacks per-series frequency/duration metadata: generic five-, two- or ten-minute descriptions do not establish each series' interval. Unknown facts must not satisfy physical filters that require established values.

## Research to reuse

Start with [#559's verified handoff](https://github.com/RivRetrieve/RivRetrieve/issues/559#issuecomment-6297270012) and the continuing [private research record](https://github.com/RivRetrieve/verification-evidence/blob/main/research/swiss-source-access.md). Credit the earlier research and correspondence in #545. Extend that record rather than create a competing research history.

Exploratory checks on 22 October 2026 found:

- 1,341 unique API station numbers, including 32 with leading zeros. Station `0085` lacks coordinates; other Hagneck stations are not established substitutes. Most API elevations are null, so the API alone cannot replace existing page enrichment.
- Sixteen small requests, about 2.6 MB of response bodies, established 7,204 observed station/parameter/route/raw-name/unit combinations across 558 stations. All encountered station numbers joined the station snapshot. All eleven archive routes were witnessed; annual routes returned data in sampled 1970, 1980 and 1990 windows despite empty recent-year samples. No annual cutoff was established.
- Sixty-five observed combinations were null-only in those samples. Station 7008's unusual daily-route series had 391 distinct timestamps in one sampled UTC day, all null. Preserve the source facts and the pending interpretation, not a guessed daily interval.
- Two small monthly CSVs were downloaded; July 2025 association sets matched the corresponding API selection. This does not certify every CSV/API value, temporal meaning or file family.
- Portal tables repeat the same station population and include placeholder rows. Table membership alone is not parameter availability. Page sensor labels, historical availability spans and statistical reference periods make different claims.

These counts describe research snapshots, not acceptance constants or target totals. Fresh captures have not yet passed archive intake or source certification. The associated discussion retains the research handoff and capture locations; temporary files are recovery leads, not build dependencies. Preserve originals through reviewed private-archive intake before adopting them, or make new acquisitions with new identities. Never reconstruct missing originals from derived tables.

## Repository fit and acceptance

Use the current catalogue schemas, publication path and evidence-aware source descriptions. At researched main `e486dcf50f7e7b15e64e6cf76788edca5b593168`, station-product availability supports available/unavailable/unknown; physical facts distinguish source silence from facts not established here. Catalogue materialization uses incomplete inventory snapshots and permits station-scoped source descriptions. Physical unknowns do not match established-fact filters. Recheck current contracts before implementation. In particular, current station coordinates are non-null, so station 0085 exposes a real representation issue.

Success means:

- A deterministic offline rebuild from explicitly selected retained inputs produces approved packaged catalogue artifacts, metadata and provenance through the shared publication path.
- Public offline discovery exposes established stations, products and raw variants without network access or credentials. Useful evidence covers the agreed product families; uncertainty is explicit rather than hidden behind fabricated combinations or completeness claims.
- Leading-zero joins, historical/recent differences, mixed live units, null-only associations, redirects, missing coordinates and source variants receive focused behavior coverage at the simplest sufficient level.
- Genuine-input checks verify adopted mappings, observations supporting associations, source joins and supplementary metadata. Compare existing approved metadata before replacement. Independent review and distribution checks prevent private source bodies, correspondence and restricted receipts from entering the public package.
- The research record explains collection coverage, remaining gaps and coordination with #561–#565. No per-series API history span is promised without evidence supporting that exact claim.

Follow the [provider-port guide](../../docs/maintenance/provider-ports.md), [testing guide](../../docs/maintenance/testing.md) and [evidence guide](../../docs/maintenance/evidence.md). Missing mandatory evidence blocks acceptance; synthetic tests and exploratory access checks do not replace it. Leave reversible collection and implementation mechanics to the implementing agent. This vision authorizes the catalogue outcome, not unrelated provider redesign.
