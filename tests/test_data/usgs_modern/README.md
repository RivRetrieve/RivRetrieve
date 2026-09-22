# USGS Water Data source recordings

These committed files retain exact publisher responses and acquisition receipts
used by the provider tests. Original legacy evidence remains independent.
National metadata is retained separately in `research/usgs-modern-coverage`;
this directory does not duplicate that acquisition.

## Recorded contract

Recorded requests use GET on explicit
`https://api.waterdata.usgs.gov/ogcapi/v1/collections/{daily,continuous}/items`.
Parameters: `f=json`, native `monitoring_location_id`, `parameter_code`, daily
`statistic_id`, `datetime`, `limit=10000`. Explicit picks add `time_series_id`.
Continuous requests omit `statistic_id`; the service collection can publish null
statistics, which must not be silently replaced with instantaneous facts.
No key was supplied. No sorting was requested. Requests ran sequentially.

Public daily Jan 1–7 requests include engine padding Dec 30–Jan 9. Historical
continuous public bounds 2010-06-01T05:00:00 through 2010-06-02T04:59:59 use exact
padded request bounds `2010-05-30T05:00:00Z/2010-06-04T04:59:59Z`.
These are request labels, not inferred station time zones.

## Files and provenance

- `new/*.body`: 22 exact new publisher response bodies. All returned HTTP 200.
- `new-manifest.jsonl`: each original/final URL, method, nonsecret request headers,
  request-start and completed UTC instants, response headers, body length/SHA256,
  and returned next links. `Accept-Encoding: identity` requested publisher bytes.
  Bodies were not parsed/reserialized before storage.
- `summary.json`: authored counts, ranges, identities, null/vocabulary summaries,
  coordinates and hashes. This is analysis, not a publisher response.
- `*-completion.json`: authored per-job cursor exhaustion/count reports.
- `prior-daily/*` plus `curated-manifest.json`: 14 untouched earlier captures with
  original/final URL, UTC and verified SHA256. Includes explicit-v1 daily and
  metadata schemas, both sibling metadata responses, direct daily selections,
  ended-empty, the original bounded null probe and publisher migration HTML.
- `prior-history/*` plus `historical-manifest.json`: 11 independently preserved
  earlier bodies. SHA256/UTC/original URL are known; **final URL was not recorded**
  and remains explicit null. Includes legacy and modern aligned 2010 bodies.
  Do not claim full redirect provenance or relabel their v0 requests as v1.
- `metadata-index.json`: authored index into 53 selected records in the existing
  committed `research/usgs-modern-coverage/metadata-*.json.gz` pages. Full page
  bytes, receipts and completion reports already exist there; no national data
  was reacquired or duplicated. Index entries give file, receipt, uncompressed
  body SHA256 and zero-based feature index. Extracted properties are not original
  publisher bodies. Includes the example stations, six Unknown cases and agency
  examples. A native agency is not always USGS.

## Finite observation checks

| Recording | Publisher rows | Public-window rows |
|---|---:|---:|
| 07374000 daily discharge mean | 11 | 7 |
| 07374000 daily stage mean/maximum/minimum | 11 each | 7 each |
| 02196000 daily mean discharge, 2000 broad | 22 | 14 |
| 02196000 each opaque sibling pick, 2000 | 11 each | 7 each |
| 02196000 ended sibling, 2024 | 0 | 0 |
| 11465200 daily null probe | 11 present-null | 7 present-null |
| 07374000 continuous discharge/stage, 2010 | 480 each | 96 each |

The null station recording publishes null for every padded day, including
2024-01-05, with `Provisional` and `["DISCONTINUED"]`. This is not an absent row or
request failure and does not expand catalogue station scope.

The explicit-v1 padded sibling cursor chain is **5 + 5 + 5 + 5 + 2 = 22**.
All five requests target v1. Its final page has no next link. Logical
`(time_series_id,time,value,unit_of_measure,statistic_id)` multisets equal the
limit10000 unrestricted response. This differs from earlier unpadded research
5+5+4; neither response nor coordinates were relabeled. Use a test-local page
limit of 5 and strict request matching. Keep each body as a separate receipt.
The historical continuous last returned timestamp is 2010-06-04T04:45:00+00:00;
there is no invented row at the requested 04:59:59 endpoint.

## Publisher contract sources

New captures include explicit-v1 continuous queryables and collection, v1 OpenAPI,
September 4 version announcement, September 18 retirement/degradation notice,
and optional API key documentation. Prior full-provenance captures include daily
and time-series-metadata v1 schemas and migration HTML. Use schemas plus actual
records: qualifier arrays/null and value null can contradict declared scalar
schema types. Metadata `id` joins observation `time_series_id`; observation
feature IDs are unstable record-version identities, not series IDs.
The new continuous collection request itself is v1; the independent old
`prior-history/continuous-collection.body` request was v0 and stays labeled v0.

## Limits and integration

All body hashes and lengths were checked. No source bodies were altered. The files here are publisher recordings, not negative controls. Tests label
authored contradictions and failures separately. Strict replay must
match complete original coordinates, including padding and selected series.
HTML/schema acquisitions are documentation, not observation replay responses.
These finite checks do not prove national or complete historical parity. The
committed audit and recorded owner decision govern the five metadata gaps and
six Unknown-statistic cases. No fallback or precise-statistic inference is
introduced by these recordings. Optional credentials/quotas were not tested live.
No new modern-2024 continuous query was needed: the historical pair covers both
continuous routes. Existing national metadata remains the catalogue input.

## Replay envelope integration warning

The new actual request User-Agent was `RivRetrieve-source-evidence`, with
`Accept-Encoding: identity`. The repository's standard RecordingEnvelope v2
only permits engine User-Agent `RivRetrieve` and does not allow Accept-Encoding
as ordinary execution metadata. Therefore these captures cannot truthfully be
wrapped as standard v2 executed requests. Do not substitute invented engine
headers. `tests/usgs_modern_recordings.py` matches exact original URL/query coordinates,
checks the manifest SHA256, and returns original body/status/acquisition/content
type without manufactured `executed_request` evidence. Preserve full manifests.
Historical v1 envelopes deliberately lack request-execution metadata; selecting
that lossy envelope format would need an explicit explanation, not silent
promotion or relabeling. This limitation is about the local envelope contract,
not a source access failure or changed publisher body.
