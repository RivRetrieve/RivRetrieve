# Architecture

RivRetrieve gives river-gauge data a common access path and an explicit account of its source.
It harmonises identity, units, and established physical representations.
It does not assess scientific quality, interpret source quality codes, or decide whether series suit a study.
A common product name and unit do not establish scientific comparability.

[Usage](usage.md) explains the caller workflow.
The [API reference](reference.md) documents the public functions and returned types.
This page explains the responsibilities behind those interfaces.

## Responsibilities

Discovery reads packaged catalogues without contacting observation services.
`find` returns immutable physical and source-identity scope with acquired catalogue evidence.
`pick` narrows a selection or a retrieved result. `series` and `as_frame` expose inspection tables;
`to_bundle` and `from_bundle` preserve selections and results as versioned exports.
An unrestricted selection retains all-matching intent, including identities discovered during retrieval.
The catalogue is a recorded snapshot, not a promise that every selected series remains retrievable.

Retrieval resolves the request and delegates source-specific access to a provider.
The engine owns stage ordering, window arithmetic, unit conversion, clipping, and assembly.
A provider declares source facts and supplies only the operations that depend on its source.
This separation prevents each provider from implementing a different interpretation of the requested window.

| Responsibility | Current implementation |
| --- | --- |
| Public composition, credential and cache-location resolution, result grouping | [`discovery.py`](../src/rivretrieve/_internal/discovery.py) |
| Selection scope and evidence | [`selection.py`](../src/rivretrieve/_internal/selection.py) |
| Explicit built-in inventory and declared provider kinds | [`provider_manifest.py`](../src/rivretrieve/_internal/provider_manifest.py), [`providers/registration.py`](../src/rivretrieve/_internal/providers/registration.py) |
| Typed stage contracts and pipeline execution | [`engine.py`](../src/rivretrieve/_internal/engine.py), [`driver.py`](../src/rivretrieve/_internal/driver.py) |
| Source request bounds | [`window_planning.py`](../src/rivretrieve/_internal/window_planning.py) |
| Shared physical conversion and final clipping | [`conversion.py`](../src/rivretrieve/_internal/conversion.py) |
| Native observations at rest | [`store/`](../src/rivretrieve/_internal/store/) |

Registration reads an explicit manifest rather than discovering arbitrary directories.
Each provider declares one of three kinds: `LiveStages`, `BulkStore`, or `CatalogueOnly`.
A live provider supplies fetch and parse stages, with product facts in `config.py`.
A bulk provider supplies download and compile operations, then uses the shared store reader for retrieval.
A catalogue-only provider supports discovery but raises when asked for observations.

Source-series definitions separate published identity from independently established physical facts.
Admission requires quantity, source unit and a dimensionally valid conversion. Optional temporal
and vertical-reference facts can remain unknown. Precise predicates match only established facts.
Product declarations supply source access routes; product names do not select a preferred alternative.
Source coordinates identify such things as an endpoint, parameter code, or value column.
Window declarations tell the engine how to split and render the fetch window.
Providers consume those renderings without shifting their bounds.

## A recorded USGS request

The [retrieval entry point](../src/rivretrieve/_internal/discovery.py) sends this request
through the [shared driver](../src/rivretrieve/_internal/driver.py):

```python
import rivretrieve as rr

selection = rr.find(
    provider="usgs_nwis",
    station="07374000",
    quantity="discharge",
    frequency="daily",
    statistic="mean",
)
result = rr.fetch(
    selection,
    start="2023-01-01",
    end="2023-01-01",
    receipts=True,
)
```

Running these calls contacts USGS. The trace below follows the saved source response
for this request.

1. **Select physical scope.** `find` checks the provider and station, then matches established quantity,
   frequency and statistic against packaged source-series facts.
   The station identifier remains a string, including its leading zero.
2. **Resolve the requested window.** The bare dates become `2023-01-01 00:00:00` through `2023-01-01 23:59:59.999999`.
   These are source-calendar wall-clock bounds, not UTC instants.
3. **Plan the fetch window.** The engine adds two days at each end.
   USGS declares inclusive date parameters, so the engine renders `2022-12-30` through `2023-01-03`.
4. **Fetch source bytes.** The USGS declaration selects the `dv` endpoint, parameter `00060`, and statistic `00003`.
   Fetch sends `sites=07374000`, `startDT=2022-12-30`, and `endDT=2023-01-03`, with `format=json`.
   The recording matches that complete request at `https://waterservices.usgs.gov/nwis/dv/`.
5. **Parse native rows.** Parse checks returned station, parameter and statistic against the request.
   It establishes unit conversion from response metadata and preserves published method identity.
   Representable method blocks remain separate. Unsupported structures retain identified outcomes.
   The recording publishes five daily values in `ft3/s`, with naive midnight labels.
   Parse retains those labels and sets `time_zone` to `unknown` rather than deriving a zone from station metadata.
6. **Convert and clip.** The shared convert stage multiplies discharge by `0.028316846592` to return m³/s.
   It clips daily products by their calendar dates and removes the four extra days.
   The retained source value is `373000 ft3/s` on `2023-01-01`.
7. **Assemble the result.** The engine retains rows, provenance, issues, and the requested receipt.
   The receipt contains the exact publisher bytes handed to parse, including the days removed by clipping.

This is source-published daily mean discharge, not a mean calculated from instantaneous observations.
The product declares a midnight label but an unknown day definition.
A label alone does not establish which 24 hours the daily value represents.
The recording was retrieved on `2026-09-02` and identifies the Mississippi River at Baton Rouge, Louisiana.

The trace connects the [USGS declaration](../src/rivretrieve/_internal/providers/usgs_nwis/config.py),
[fetch](../src/rivretrieve/_internal/providers/usgs_nwis/fetch.py), and
[parse](../src/rivretrieve/_internal/providers/usgs_nwis/parse.py) to the shared driver and convert stage.

## Contracts between stages

Fetch returns immutable payload bytes with a source-call origin.
Parse returns native rows, source-series definitions, scoped inventories, typed outcomes and issues.
Convert checks the row contract, applies declared unit conversion, and clips to the requested window.
Assemble combines the canonical rows with provenance, issues, and receipts.
The driver checks that each fetch window contains its request and that converted rows stay within the requested bounds.

The observation frame always has these columns, in this order:

```text
time | time_zone | station_id | product_id | series_id | facts_id | quantity | source_unit | unit | value
```

`time` is a naive source wall-clock timestamp.
`time_zone` carries the row's established IANA identifier, fixed offset, or `unknown`.
These columns must travel together.
A null `value`, an absent row, and a failed request are distinct states.
`series_id` identifies the source series; `facts_id` identifies its physical-fact segment.
`source_unit` preserves publisher vocabulary. `unit` describes the harmonised `value`.
Result definitions, inventory snapshots and outcomes retain context even without observation rows.

Requested windows are closed at both ends.
Daily products clip on calendar dates, while instantaneous and other source time labels clip on their timestamp axis.
Zone-bearing request endpoints raise rather than being silently reinterpreted.
`to_utc` is a separate operation over returned time and zone information, not a retrieval guarantee.

Unknown source facts remain unknown.
The engine does not infer zones from coordinates, infer daily support from a midnight label, or compute unpublished hydrological products.
Catalogue evidence also distinguishes source silence from facts withheld because RivRetrieve lacks an established acquisition record.
Those are different reasons for absent information.

### Failures and partial results

The driver isolates source-call failures for each requested series and carries them as issues alongside any returned rows.
This keeps one source-call failure from discarding independent series.
Caller policy controls how those issues are reported, not their classification or retention.
Fatal contract errors bypass that policy because invalid stage output cannot form a valid result.
See [usage](usage.md) for severity, caller-policy choices, and interpretation of empty results.

`fetch` requires one provider because an observation result has one provider identity, license, and citation.
Station identifiers can also overlap between providers.
`fetch_by_provider` therefore returns separate results rather than merging ambiguous rows or source terms.

## Storage and reuse

The cache holds native values and native wall-clock timestamps.
Both compiled and accumulated stores feed the same convert stage, so reuse does not convert values twice.
They share a reader and format family but preserve different information.

| Path | Stored information | Retrieval behavior |
| --- | --- | --- |
| Live `cache="bypass"` | No cache update | Fetch, parse, convert, assemble |
| Live `cache="reuse"` | Native rows, scoped inventory and successful per-series interval coverage | Serve locally when the complete scope is covered; otherwise reacquire the full requested scope, convert, assemble |
| Live `cache="refresh"` | Replacement answer for the successfully retrieved requested interval | Fetch and parse again, convert, update storage, assemble |
| Bulk | Certified compiled publisher observations | Read store, convert, assemble without provider fetch or parse |

Accumulated stores use format revision `7`.
Their coverage records which closed intervals were successfully retrieved and when, including successful empty answers.
Coverage is per concrete series and interval, separate from inventory knowledge. All-series reuse
requires a complete inventory for the recorded scope and vintage, plus coverage of every required
member. Subset success cannot satisfy that request. When this proof is insufficient, retrieval
reacquires the full requested scope through the provider's normal padded fetch windows, rather
than fetching only uncovered intervals. Refresh replaces successful series intervals without
erasing siblings. Failed or unsupported acquisition can retain held successful observations
at their original retrieval vintage, alongside the new diagnostics, not as fresh successes.
Coverage does not assert continuous observations.
Served intervals carry their retrieval instants in provenance, without an automatic freshness verdict.

Compiled stores use revision `5` and retain declared source columns and native value states.
An explicit `download` prepares them.
Compilation preserves published values, nulls, and blanks, while accumulated parse output cannot recover a blank already collapsed to null.
Bulk retrieval never silently starts a download, and replacing a compiled store requires `download`, not `cache="refresh"`.

Certified compilation writes a staged store and compares it with a second decoding of the publisher artifact before publication.
The artifact is deleted after successful publication.
Its URLs, checksums, and source vintage survive in the manifest, but its identity cannot reconstruct unavailable publisher bytes.
Readers refuse unsupported manifest revisions before opening observation files.
Packaged catalogue format revision `2`, source-series definition schema `1` and export bundle
version `2` are explicit contracts.
Old collapsed rows, triple-only frame imports and incompatible stores are refused, not assigned
invented identities. Rebuild or refetch explicitly; refusal leaves old files intact.
`cache_status` inspects local state, and `clear_cache` is the explicit destructive boundary.

### Provenance and receipts

The driver derives source-call provenance from payload origins independently of receipt retention.
Callers can therefore identify retrieval operations without keeping response bytes.
Receipts expose the parse boundary or selected store rows, rather than promising to reproduce every enclosing network transfer.
Their authorship distinguishes publisher bytes from RivRetrieve's encoding of stored rows, which cannot reconstruct discarded publisher content.
Receipt origins exclude request headers, and shared credential transport binds supplied secrets to declared source origins.
See [usage](usage.md) for provenance fields, optional receipts, and credential configuration.

## Evidence and verification

Catalogue builds check canonical columns against declared origins and acquisition evidence.
Canonical station columns describe identity and geometry, not harmonised names, river labels, or quality judgements.
Native tables remain repository build inputs rather than a public wheel API.
`drainage_areas` reads a small packaged projection of established drainage-area
fields at provider-station grain. It preserves source vocabulary and values,
including explicit null and no-metadata states, without changing canonical facts.
See [drainage-area metadata](drainage-areas.md) for the output and offline build.
`describe` reads the packaged Croissant descriptor offline.
The current evidence representation uses a typed header and five normalized relations, with explicit resolution of individual fact lineage.

Observation tests replay saved real interactions through the transport seam.
Replay refuses a request that has no matching recording, so changed request bounds cannot receive an unrelated answer.
Boundary probes assert source-checkable counts and first and last native labels.
These checks establish behavior against recorded interactions, not current service availability.

### Verification tests

These links open tests rather than implementation modules:

- [Publisher-receipt tests](../tests/test_receipts_publisher_payload.py) replay the USGS request traced above.
- [Engine-contract tests](../tests/test_internal_engine_contracts.py) check typed windows, payloads, and row shapes.
- [Window-planning tests](../tests/test_internal_window_planning.py) check shared splitting and rendering.
- [Source-failure tests](../tests/test_source_failure_isolation.py) check partial results and retained diagnostics.
- [Live-cache tests](../tests/test_live_cache.py) check reuse, refresh, coverage, and receipts.
- [Store-conformance tests](../tests/test_observation_store_conformance.py) check native storage and shared reads.
- [Catalogue-evidence tests](../tests/test_catalogue_evidence.py) check the normalized evidence contract.
