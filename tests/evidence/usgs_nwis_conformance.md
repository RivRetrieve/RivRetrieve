# USGS source-series conformance

## Supported access and evidence

The six enrolled routes use `https://waterservices.usgs.gov/nwis/`:

| Product | Endpoint / parameter / statistic | Public replay recording suffix |
| --- | --- | --- |
| discharge daily mean | dv / 00060 / 00003 | dv_00060_00003_2022-12-30_2023-01-03 |
| discharge instantaneous | iv / 00060 / omitted | iv_00060_2023-01-01 |
| stage daily mean | dv / 00065 / 00003 | dv_00065_00003_2022-12-30_2023-01-03 |
| stage daily maximum | dv / 00065 / 00001 | dv_00065_00001_2022-12-30_2023-01-03 |
| stage daily minimum | dv / 00065 / 00002 | dv_00065_00002_2022-12-30_2023-01-03 |
| stage instantaneous | iv / 00065 / omitted | iv_00065_2022-12-30_2023-01-03 |

Recordings are `tests/test_data/usgs_nwis_07374000_<suffix>.recording.json`.
The four padded stage recordings were acquired on 2026-09-20 through the shared
HTTP transport. Their envelopes retain exact response bytes, SHA-256, UTC retrieval
instants, status and non-secret executed request evidence. Existing shorter stage
recordings remain unchanged. No historical envelope was relabelled to fit a new request.

`test_usgs_nwis_public_routes.py` exercises all six via public physical discovery,
actual fetch/parse/conversion, exact-request replay, bypass/reuse/refresh and receipts.
It compares every retained January 1 value with the recorded native value and established
conversion (ft³/s × 0.028316846592; ft × 0.3048). It retains each method ID and its empty
published description, daily unknown zones, and instantaneous source offsets.
The declaration-coverage assertion fails if another route is enrolled without this proof.

## Identity and limitations

`test_catalogue_source_series.py::test_usgs_catalogue_claims_survive_public_discovery_and_bundle`
preserves the native `NWIS.ts_id` catalogue claims and `loc_web_ds` descriptions for
02196000 separately from response-owned `methodID` identities. Numerical coincidence
at that station establishes no global mapping. Catalogue acquisition is the fixed
50-state-plus-DC snapshot, not an exhaustive current or historical inventory.
The [Site Service](https://waterservices.usgs.gov/docs/site-service/site-service-details/)
defines the catalogue fields. Response `methodIds=[ALL]` supports only its acquired
request scope and vintage.

The [WaterML 1.1 schema](https://his.cuahsi.org/documents/cuahsiTimeSeries_v1_1.xsd)
permits optional IDs and multiple methods. Existing `test_source_series_usgs.py`
checks ID zero, optional-ID method codes, explicit per-value ID/code associations,
missing and ambiguous associations, equal/conflicting/disjoint blocks, unsupported
siblings, nulls, and native multiplicity. Authored structural controls are labelled
as derivatives, not additional publisher captures.

The original two-method response remains exactly 1,702,244 bytes, SHA-256
`92c43227ececed5373bc92abc4cbb19035dfc4b0ec7db736f2b4e443d8bf1275`.
Its 15,388 and 7,989 native observations remain separate. Public tests preserve its
exact request, clipped rows, subset-versus-all cache behavior, failed refresh isolation,
exports and receipts. The historical capture's unknown HTTP status and retrieval time
remain unknown; the explicitly authored transport replay does not claim otherwise.

Publisher [instantaneous-values documentation](https://waterservices.usgs.gov/docs/instantaneous-values/instantaneous-values-details/)
is retained as exact HTML with acquisition provenance. Instantaneous support does not
establish sampling frequency. Daily statistics do not establish exact day definition.
Stage units do not establish a vertical datum or gauge-zero reference. No modern API
migration, quality ranking, cross-method deduplication or new hydrological product is added.

## Verification

The initial route-coverage increment needed no production change. A subsequent
physical-fact review identified an unsupported timestamp-anchor claim.
The missing evidence was public replay of the four stage routes with the real padded
request, rather than only direct stage invocation. Targeted test and Ruff results are
recorded in the Effort 286 validation logs (`usgs-conformance-*.log`).

Initial route-only validation: targeted pytest invocation passed 384 test executions in
554.45 seconds (the explicit new module also appears in the USGS glob). Ruff check
passed; Ruff format checked 11 files without changes. That initial route-only increment changed no production code. The corrections
below were subsequently added with regression-first proof.

### Timestamp-anchor correction

All retained DV recordings, including the original two-method response, serialize
naive midnight labels. They do not publish a definition establishing a physical
timestamp anchor. The parser formerly promoted the `dv` route alone to a known
`00:00` anchor with the authored citation `USGS daily value label`. That inference
is removed. The anchor remains `not_established`; native midnight labels, daily
frequency/statistics, `label_time="00:00"` representation and calendar-date clipping
remain unchanged. No nonmidnight support or inferred day definition is added.

The parser and real recorded public workflow regressions first failed on that
claim. Public catalogue discovery also failed because the generic description
builder inferred an anchor from `Daily.label_time`. The separately owned shared
correction removes that inference; USGS metadata is rebuilt from the unchanged
attested native input. Precise anchor predicates no longer match an unestablished
fact. Logs: `usgs-anchor-red.log`, `usgs-anchor-parser-green.log`,
`usgs-anchor-rebuild.log`, and `usgs-anchor-green.log` in the Effort evidence directory.

### Nonmidnight offset-bearing daily structure

An explicitly authored mutation of a real DV recording demonstrated that an
offset-bearing noon label passed parse, then raised `FatalContractError` in native
row validation and discarded an independent valid method. The same midnight
representation guard now applies to naive and offset-bearing daily labels at parse.
The offending method has an identified unsupported outcome; its valid peer survives.
This does not establish or admit a nonmidnight USGS product. Original recordings
and fatal internal contract handling remain unchanged. The public regression and
exact mutated receipt are in `test_usgs_nwis_public_routes.py`; proof logs are
`usgs-offset-daily-red.log` and `usgs-offset-daily-green.log`.

Final validation: the broad USGS and catalogue source-series suite passed 387 tests.
The post-boundary-fix parser/public/multi-method suite passed 70 tests. Ruff check
and format both pass. The original source capture and native catalogue byte hashes
are unchanged (`usgs-anchor-preserved-evidence.json`).
