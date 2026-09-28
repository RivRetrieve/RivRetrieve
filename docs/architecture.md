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
Annual, monthly, capped-span and fixed-backward renderings carry engine-established
closed acquisition bounds. Providers attach these bounds to independently
exhaustive payloads and failed requests. A dependent cursor transaction remains one
acquisition: an individual page does not establish exhaustive coverage.

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
result = rr.fetch(selection, start="2024-01-01", end="2024-01-07", receipts=True)
```

`find` reads the packaged catalogue without contacting USGS. It exposes the
publisher's opaque series ID before retrieval. `pick(selection, variant=...)`
limits the request to that ID. An unrestricted selection also admits matching
series discovered in the observation response.

1. **Plan the window.** The engine pads the daily calendar request by two days,
   rendering `2023-12-30/2024-01-09`.
2. **Fetch source bytes.** USGS declares the modern v1 `daily` collection,
   parameter `00060`, statistic `00003`, and the acquired monitoring-location
   identity `USGS-07374000`. Fetch follows every publisher cursor and keeps
   each original response page.
3. **Parse native rows.** Parse checks returned station, parameter, statistic,
   units and selected series against the request. Observation `time_series_id`
   joins the metadata `id`; the feature record ID is not a series identity.
   The recording publishes 11 date-only values in `ft^3/s`. These become
   midnight labels with an unknown time zone, not inferred daily support bounds.
4. **Convert and clip.** The engine multiplies discharge by `0.028316846592`
   and returns seven values in m³/s. Daily clipping uses calendar dates.
5. **Assemble the result.** Provenance records source calls. Requested receipts
   retain exact publisher bytes, including the four days removed by clipping.
   Exhausted finite observation windows establish cache coverage, not a complete
   historical inventory.

This is a publisher-computed daily mean, not a mean calculated by RivRetrieve.
The [recording and acquisition manifest](../tests/test_data/usgs_modern/README.md)
retain the September 22, 2026 source evidence. Modern continuous observations
retain their published UTC offsets. No station time zone is inferred.
See [USGS discovery](usgs-discovery.md) for variants, unknown statistics and limits.

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
This keeps one source-call failure from discarding independent series or independently
exhaustive source intervals. Failures retain their request identity, interval, reason, and
available response metadata. Lithuania historical-month HTTP 404 means that no
station observations are stored for that month. When its engine-established bounds
fall wholly outside the requested dates, that padding-only absence remains in
provenance without a requested-data warning or failed outcome. Other failures,
including malformed responses and authentication errors in padding, remain diagnostic.
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
erasing siblings. During reuse and refresh, failed or unsupported intervals retain
held successful observations at their original retrieval vintage, alongside the new
diagnostics, not as fresh successes. Independently successful acquisitions replace only
their own requested intervals; failed acquisitions establish no successful coverage.
The driver assesses all pages before combining fresh rows with held fallback, so
a late page failure has the same effect as an early failure.
Coverage does not assert continuous observations.
Bosnia's rolling workbooks establish only the observations they contain. Their
rows update matching series, physical facts, timestamps and time zones in the
cache. Rows absent from a later workbook remain held at their earlier acquisition
vintage. These snapshots establish no reusable temporal coverage, even when empty;
retrieval must contact the source again.
Served intervals carry their retrieval instants in provenance, without an automatic freshness verdict.

Compiled stores use revision `5` and retain declared source columns and native value states.
An explicit `download` prepares them.
Compilation preserves published values, nulls, and blanks, while accumulated parse output cannot recover a blank already collapsed to null.
Bulk retrieval never silently starts a download, and replacing a compiled store requires `download`, not `cache="refresh"`.

Certified compilation writes a staged store and compares it with a second decoding of the publisher artifact before publication.
The artifact is deleted after successful publication.
Its URLs, checksums, and source vintage survive in the manifest, but its identity cannot reconstruct unavailable publisher bytes.
Readers refuse unsupported manifest revisions before opening observation files.
Packaged catalogue format revision `2`, source-series definition encodings `1` and `2`, and export bundle
version `2` are explicit contracts.
The second source-series encoding stores each physical-fact segment once and validates
every series reference; the in-memory definitions are unchanged.
Readers validate these formats before use. Hub’Eau catalogues, live stores and export
bundles also declare their publication service. Readers refuse superseded combined
French artifacts and legacy USGS artifacts without reinterpreting their source identity. Refusal leaves unsupported files intact.
`cache_status` inspects local state, and `clear_cache` is the explicit destructive boundary.

### Provenance and receipts

The driver derives source-call provenance from payload origins independently of receipt retention.
Callers can therefore identify retrieval operations without keeping response bytes.
Acquisition identity distinguishes repeated equal responses, including equal bytes
and timestamps. Mapped outcomes link to those calls. Shared products retain one
call and receipt for each acquired payload.
Receipts expose the parse boundary or selected store rows, rather than promising to reproduce every enclosing network transfer.
Their authorship distinguishes publisher bytes from RivRetrieve's encoding of stored rows, which cannot reconstruct discarded publisher content.
Receipt origins exclude request headers, and shared credential transport binds supplied secrets to declared source origins.
See [usage](usage.md) for provenance fields, optional receipts, and credential configuration.

Swiss public retrieval uses Existenz's recent REST service when the engine-padded window stays
within its 32-day horizon. Older and horizon-crossing windows use the archive with the publisher's
shared read-only credential, bundled internally and restricted to the archive origin.
Users do not supply this credential. Publisher credential rotation requires a library update.

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
