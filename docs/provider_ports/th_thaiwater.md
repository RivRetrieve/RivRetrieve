# th_thaiwater Provider Port Notes

These notes capture evidence and handoff context from the `th_thaiwater` provider port. They are not user documentation and not an architecture contract; promote shared harness commitments to [ADRs](../adr/) only with concrete evidence.

## Source Endpoints

| Endpoint | Role | Credential | Notes |
| --- | --- | --- | --- |
| `https://api-v3.thaiwater.net/api/v1/thaiwater30/public/waterlevel_load` | Maintainer-side native-table refresh input; returns all telemetered stations in one response. | None. Public ThaiWater Open API. | Canonical artefacts are built offline from committed `native.parquet` plus origins. |
| `https://api-v3.thaiwater.net/api/v1/thaiwater30/public/waterlevel_graph` | Runtime observation retrieval. Query params: `station_type=tele_waterlevel`, `station_id`, `start_date` (YYYY-MM-DD), `end_date` (YYYY-MM-DD). | None. | Returns a `data.graph_data` list with `datetime`, `value` (stage in m), and `discharge` (m³/s) fields per row. |

## Observation Time and Zone

The recorded `graph_data[].datetime` values use `YYYY-MM-DD HH:MM` with no UTC designator,
numeric offset, or timezone field. No captured official source establishes a zone. The parser therefore
preserves each value as a naive source wall clock and sets `time_zone="unknown"`. It does not infer
`Asia/Bangkok` from the country, station coordinates, or retired code. `to_utc` refuses these rows
atomically.

## Native Catalogue Attestation

The complete `waterlevel_load` response was retrieved at `2026-08-02T12:42:03Z` and contained 825
rows with 825 unique integer `station.id` values. Canonicalizing the parsed response with sorted keys,
compact separators, `ensure_ascii=False`, and UTF-8 produces SHA-256
`d42fdac929ddf87f348ed8cd9a6732768fb9775a47fff2bc54f4e0e74ee8bdee`. The four-row fixture is a
verbatim parser subset, not a native-table source. The native table preserves 61 lexicographically
ordered dotted source columns and widens only values needed for a lossless scalar dtype. The source
population has changed relative to the legacy catalogue: 87 new IDs are present and 16 legacy IDs are
absent, so the 825-row result is source churn rather than a missing filter. The committed native-frame
digest and semantic comparison are held by `catalogue/provenance.json`, origins, and generator tests.

The publisher coordinate-standard page was captured at `2026-08-02T13:51:44Z` as
`tests/test_data/th_thaiwater_coordinate_standard.html`. Its byte identity and SHA-256 are pinned by
the origin-evidence receipt; it documents coordinate semantics and contributes no native rows.

## Catalogue Mapping

| Legacy / source field | Canonical target | Provider metadata | Decision |
| --- | --- | --- | --- |
| `station.id` | `station_id` | Native table | Exact identity copy of the committed String value; `station.tele_station_oldcode` is not identity. `provider_id` is authored by RivRetrieve. |
| `station.tele_station_name.*` | No canonical column | Native table | Multilingual source values remain readable in `native.parquet`. |
| `station.tele_station_lat`, `station.tele_station_long` | `latitude`, `longitude` | Native table | Exact decimal values, cast only to canonical schema dtypes. Null values fail the build. |
| `river_name`, `geocode.*`, `basin.*`, `agency.*` | No canonical columns | Native table | Source vocabulary remains readable in `native.parquet`; RivRetrieve does not adjudicate these labels. |
| `station.tele_station_oldcode` | No canonical column | Native table | Preserved source station code; never substituted for `station.id`. |
| CRS | `crs = "unknown"` | Origin evidence | ThaiWater's captured coordinate-standard page specifies ISO 6709 formatting but no datum, CRS, EPSG code, or projection. |
| `station_type` | Build contract | Native table | Every native row must equal `tele_waterlevel`; any other value fails loudly. |

## Product Dictionary

The packaged catalogue advertises two source-published reported-value products. Their temporal support is unknown. Their `frequency`, `statistic`, `period_type`, and `period_anchor` fields are therefore all `unknown`. It does not advertise daily means; those were derived by the retired observation implementation.

| Native field | Canonical `product_id` | Unit |
| --- | --- | --- |
| `value` | `stage_reported` | m |
| `discharge` | `discharge_reported` | m³/s |

No unit conversion is required.

## Observation Retrieval

- **Windowing**: both products declare engine-owned `capped-span`, DATE rendering, inclusive
  stop and a conservative size of **365 inclusive source dates**. The engine adds two days
  to each user endpoint before planning. A 365-date user request can therefore require two
  source requests per product. Each sub-window has its own bounds; the provider performs
  no padding, splitting or stop arithmetic. Direct normal and leap-containing captures
  honour this size; it is not the exact maximum or a universal leap-year rule.
- **Request**: `station_type=tele_waterlevel`, `station_id`, `start_date`, and `end_date` are sent to
  `waterlevel_graph` through the shared `HttpClient` transport seam.
- **Co-published fields**: one graph response contains both `value` and `discharge`. The provider
  fetch stage can group both fields if supplied together. The public engine deliberately
  calls each product separately; each selected product receives its own source calls and receipts.
- **Parsing**: `value` and `discharge` are projected directly into source-labeled rows without claiming an instant or interval. Nulls
  remain null. `value_out` remains uninterpreted. There is no provider clipping, aggregation, unit
  conversion, retry loop, or result assembly. A valid source `result: "NO"` with its non-empty
  message returns an error issue and empty typed rows. Malformed JSON, invalid envelopes or
  missing required fields in an `OK` graph remain contract errors. No broad exception isolation
  was added.

## Station Count

825 stations at catalogue version `2026-08-02`, built offline from committed `native.parquet` plus the five station origins. Every native row is required to have `station_type == "tele_waterlevel"`, non-null latitude and longitude, and a unique String `station.id`; violations fail the build rather than being filtered, dropped, or deduplicated.

The packaged station-product carrier now contains all **1,650 source-evidenced pairs**
over the original 825 station IDs. Positive availability is 813 stage and 283 discharge;
unknown availability is 12 stage and 542 discharge. Unknown pairs remain selectable.
Every pair has an actual governing graph acquisition; none remains withheld merely
because the tested response carried no numerical value. Published record bounds remain
null. Each `last_catalogue_check` is that pair's actual September 11 or September 13
acquisition date, not the native metadata capture date or a fabricated common instant.

| Coverage | Before | After |
| --- | ---: | ---: |
| Selectable baseline stations | 1 | 825 |
| Selectable station/product pairs | 2 | 1,650 |
| Positive availability pairs | 2 | 1,096 |
| Selectable unknown pairs | 0 | 554 |

The 25 original IDs absent from the later 1,405-row snapshot remain. The 605 newly
observed IDs are not added. The machine-readable source account is
`research/station-coverage/th_thaiwater/inventory/governing_summary.json`; the exact
per-pair acquisition/material ledger sits beside it. The capture corpus remains private,
not an observation archive published with these catalogues. A current caller can ask
windows beyond the recorded research dates; the source may return measurements,
timestamped nulls, an empty answer or an explicit issue.

## Shared Architecture Impact

The existing engine remains responsible for padding, sub-window planning, clipping,
cache reuse/refresh and source-call isolation. This expansion does not change driver
coalescing or add a provider-specific date planner. Available and unknown relation rows
are admitted from their own source acquisitions, not an inferred Cartesian product.

Catalogue builds take reviewed ledger bytes as an explicit typed input. Only the build
entry point opens its `--availability-evidence` path; public discovery/retrieval reads
packaged catalogues and never opens the repository research tree. Accepted body material
identities use the existing acquisition provenance contract without fake public recording
URIs. A separate explicit-root offline verifier must read all private bodies at acceptance
and final integration; public CI checks metadata/binding consistency only.

Supplying agencies retain their verified native per-station bindings. HII's platform and
product-semantics publication roles are distinct from unestablished original measurement
producers or historical sensor operators. Source terms and citation words are not classified.

Recorded tests use an independently authored normal-window boundary expectation over two
exact runtime-v2 interactions, with original/new retrieval dates kept explicit. A historical
82-byte database-error response is exercised directly at the real parser boundary; it is
not presented as a new public HTTP replay with invented execution headers. Existing engine
WithIssues tests cover issue propagation and cache-write suppression. The leap-containing
null capture establishes honoured source dates, not historical observations.

## Pain Points

| Issue | Status | Action |
| --- | --- | --- |
| Naive graph timestamps | Source zone is not established. | Preserve wall clock with `time_zone="unknown"`; never infer UTC or Bangkok. |
| Response publishes two products together | Provider fetch supports a two-product payload; public calls remain product-wise. | Preserve each actual call and receipt. |
| Elevation and drainage area | Not canonical station columns under the identity/geometry contract. | Preserve source facts in the native table; do not infer values. |
| Multilingual station names | Preserved in flattened native columns. | Keep source language values unchanged. |
