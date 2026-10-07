# Usage

[Documentation index](README.md) · [API reference](reference.md)

Search for series by what they measure, download their data, and check the results.
Run these examples in order in one Python session. Searches work offline, but
downloads need network access. The displayed observations come from recorded source
responses, which can differ from a current live response.

## Find stations

A **provider** publishes observations. A **station** identifies a monitoring site
within that provider. Keep station identifiers as strings so leading zeros survive.
A **source series** is a separately published record at a station.

Start with discharge, then narrow to established daily means at one USGS gauge:

```python
import rivretrieve as rr

# Start with discharge, then ask for established daily means.
discharge = rr.find(provider="usgs_nwis", quantity="discharge")

daily_gauges = rr.pick(discharge, frequency="daily", statistic="mean")

chosen_gauges = rr.pick(daily_gauges, station=["07374000"])

print(rr.series(chosen_gauges).select("station_id").unique().rows())

# Output:
# [('07374000',)]

print(rr.series(chosen_gauges).select("variant", "description").rows())

# Output:
# [('c9d823a2491f4b639656a11b35a7625d', None)]
```

Quantity, frequency, statistic and other physical facts can be known independently.
An explicit filter matches only established matching facts. For example, Swiss
FOEN discharge has established units but no established frequency or statistic:
a discharge search includes it, while a daily-mean search excludes it.
A service's update cadence does not establish the time span represented by a value.
RivRetrieve uses published daily means rather than calculating them.

`rr.series(selection)` shows known identities and their physical facts. Its
`<fact>_state` and `<fact>_evidence` columns distinguish known facts from source
silence or facts that have not been established. A null description means no
source description was recorded. The USGS variant above is a publisher series ID.

The packaged catalogue is a snapshot, not an exhaustive historical inventory.
Retrieval can discover additional matching identities. Unless narrowed by `variant`
or `series_id`, a selection retains every matching supported identity; RivRetrieve
does not choose a preferred series or infer a quality ranking.

### Inspect station metadata

```python
stations = rr.metadata(chosen_gauges)
print(stations.select("station_id", "station_name").rows())

# Output:
# [('07374000', 'Mississippi River at Baton Rouge, LA')]

source_attributes = rr.metadata(chosen_gauges, view="source")
```

The station table contains names and coordinates with their CRS, plus lists of
water-body, drainage-area and elevation fields. When the provider gives a gauge no
name, or several different names, the summary name is null. The source view
preserves names and separate drainage-area fields with exact values, units where
established, and explicit absence states. Both views work offline. The
[column table](station-metadata.md#columns-at-a-glance) lists what to expect, and
[station metadata](station-metadata.md) explains how to interpret it.

### Save a selection

Use a bundle to retain the selection's filters, identities and catalogue evidence:

```python
from pathlib import Path

selection_path = Path("selection.rrbundle")
selection_path.write_bytes(rr.to_bundle(chosen_gauges))
restored_gauges = rr.from_bundle(selection_path.read_bytes())

print(rr.series(restored_gauges).select("station_id").unique().rows())

# Output:
# [('07374000',)]
```

For custom table filtering, inspect `rr.series(selection)` and pass the selected
identifiers back to `pick`. An observation or selection frame alone is not a
lossless export; `from_frame` refuses bare frames.

## Retrieve and inspect results

```python
result = rr.fetch(chosen_gauges, start="2023-01-01", end="2023-01-01")

print(result.data.select("station_id", "value").rows())

# Output:
# [('07374000', 10562.183778816001)]

print(result.issues)

# Output:
# ()
```

### Series inspection and result views

`result.data` is a Polars table. Discharge uses cubic meters per second, stage metres and water
temperature degrees Celsius. The original unit remains in `source_unit`.
Inspect the source facts and outcomes as well as the numeric values:

```python
print(result.data.select("source_unit", "unit", "time_zone").unique().rows())

# Output:
# [('ft^3/s', 'm3/s', 'unknown')]

returned_series = rr.series(result)

print([(item.station_id, item.status.value) for item in result.outcomes])

# Output:
# [('07374000', 'success')]

# Keep identity and reason when investigating unsuccessful or empty requests.
outcome_details = [
    (item.station_id, item.series_id, item.requested_selector, item.status.value, item.reason)
    for item in result.outcomes
]
```

A null value is a published row without a numeric value. An absent row says nothing
by itself about why data are missing. Outcomes distinguish `success`, `empty`,
`failed`, `unsupported`, `unresolved` and `no_match`. A successful empty series has
no rows; it is different from a failed request. `unresolved` means availability
cannot be established; `no_match` means the evidence establishes that nothing matches.

`rr.series(result)` includes response-discovered identities and outcomes, even for
series with no observations. An outcome without a concrete identity has
`series_id=None`; its requested selector, station, route and reason still matter.
The inspection table includes these outcomes with null identity and fact columns.
Counting observation rows alone misses entirely empty or failed requested gauges.

`result.supporting_outcomes` contains original acquisition records needed to
interpret the returned inventories. For example, an inventory can still refer to
an earlier failed acquisition after a later retrieval succeeds. That earlier
failure remains in `supporting_outcomes`, separate from active `outcomes`, and
does not trigger issue policy. `pick` and bundle exports preserve this evidence.

`pick(result, ...)` filters a result without another request. Original issues,
receipts and provenance remain available and may describe the broader request.
Save the complete result when that context matters:

```python
result_path = Path("result.rrbundle")
result_path.write_bytes(rr.to_bundle(result))
restored_result = rr.from_bundle(result_path.read_bytes())

print(restored_result.data.height, len(restored_result.issues))

# Output:
# 1 0
```

`fetch` accepts one provider. For a selection spanning providers,
`fetch_by_provider` returns separate results keyed by provider.
See the [API reference](reference.md) for returned fields and export methods.

### When an agency publishes more than one version

Brazil's ANA publishes `bruto` (raw) and `consistido` (quality-checked) daily records.
ANA performs that checking, not RivRetrieve. RivRetrieve does not determine which
record suits a study. Inspect both, then optionally narrow the selection:

```python
brazil = rr.find(
    provider="br_ana", station="15400000", quantity="stage", frequency="daily", statistic="mean"
)

print(sorted(rr.series(brazil)["variant"].to_list()))

# Output:
# ['bruto', 'consistido']

consistido = rr.pick(brazil, variant="consistido")
```

Set `ANA_IDENTIFICADOR` and `ANA_SENHA` before these downloads; see
[supplied credentials](#supplied-credentials). A source may not have observations
for both versions in every period.

```python
brazil_result = rr.fetch(brazil, start="2020-01-10", end="2020-01-20")

print(sorted(rr.series(brazil_result)["variant"].to_list()))

# Output:
# ['bruto', 'consistido']

consistido_result = rr.fetch(consistido, start="2020-01-10", end="2020-01-20")

print(sorted(rr.series(consistido_result)["variant"].to_list()))

# Output:
# ['consistido']
```

Requesting an unlisted variant can leave availability unresolved when the inventory
is incomplete. RivRetrieve retains the restriction and reports an issue rather
than substituting a known series. Contradictory restrictions instead establish no match.

### Time labels and request windows

`start` and `end` use source wall-clock labels, not UTC instants. Both endpoints
are included. Use ISO date strings, naive ISO datetime strings or naive Python
`datetime` objects. A date-only end includes the date's final instant. Omitting
`end` uses the caller machine's current local date. `start` is required.

Read `time` together with `time_zone`. An `unknown` zone supplies no basis for UTC
conversion. The function `to_utc(result)` requires established zones for every row and
raises an error otherwise, including for the USGS daily result above. Its returned `time` remains
naive, paired with `time_zone="+00:00"`. Converting labels does not establish a
daily aggregation definition. Equal units do not establish equal day definitions,
a water-level datum or scientific comparability. Source quality judgements remain
uninterpreted.

### Issues

Inspect `result.issues` even when rows return. Independent series can succeed while
another fails. The default `on_issue="warn"` emits warnings and returns the result;
`"ignore"` keeps issues without notifications; `"raise"` raises `IssuePolicyError`
for warning or error issues. Informational issues remain available under every policy.

HTTP 404 normally produces a warning issue. A provider-defined no-observations
response in request padding outside the requested interval can be ignored without
an issue. Other unsuccessful statuses, rejected credentials and exhausted transport
retries produce error issues. An all-failed request can return an empty frame with
issues and outcomes. Broken internal contracts raise regardless of issue policy.
Invalid windows and missing required credentials also raise.

Safe-to-repeat requests get at most three attempts for transient failures, with
one-second spacing between attempts and normal retry waits of one and two seconds.
Valid `Retry-After` guidance can increase each wait to 60 seconds; longer guidance
stops the request. Each attempt has a 60-second connection/read timeout, not a
whole-download deadline. Permanent TLS, protocol and decoding failures are not retried.
GET, HEAD and the established read-only Swiss archive query are safe to repeat;
arbitrary POST requests are not. See the [API reference](reference.md) for
exceptions and retained failure details.

## Supplied credentials

Norway (`no_nve`) requires `NVE_API_KEY`; Brazil (`br_ana`) requires
`ANA_IDENTIFICADOR` and `ANA_SENHA`. Set values in the process environment or a
working-directory `.env` file. Environment values take precedence; a blank value
counts as missing. Keep secrets out of scripts and version control.
[.env.example](../.env.example) lists the required names.

`providers()` reports required variable names and whether they are present; it does
not establish that an agency accepts them. Required credentials are checked even
for cache reads. Mixed-provider requests check all selected providers before any
retrieval starts.

## Cache and bulk downloads

Live retrieval defaults to `cache="bypass"`, which neither reads nor writes the
observation cache. Choose `"reuse"` to reuse covered requests, or `"refresh"` to
replace the requested interval with the source's current successful answer:

```python
cached_result = rr.fetch(chosen_gauges, start="2023-01-01", end="2023-01-01", cache="reuse")
status = rr.cache_status("usgs_nwis")

print(status.exists)

# Output:
# True
```

Reuse is decided separately for each station and access route. A covered route can
be reused while another is fetched. Coverage needs both the matching series inventory
and successful retrieval for the requested interval. Cached `consistido` data alone
cannot answer a request for both Brazilian versions. An uncovered route fetches its
full requested scope with normal source padding, not only the missing dates.

A successful empty answer can cover an interval; a failed request cannot.
Reuse returns the saved answer, which may differ from the source today. Refresh
can return fewer rows or none. If a series fails, older cached observations can
remain alongside new issues, with their original retrieval time. A later successful
answer replaces failures only for the identity, physical facts and interval it
establishes. After full recovery, reuse does not repeat the superseded failure.
Rolling snapshots replace matching observation keys; missing keys in a new snapshot
do not establish an empty historical interval.

Local reads check current metadata and the saved byte identities of candidate
product/year files before using their observations. They decode the row groups
needed for the requested stations, source series, physical facts and dates.
Stations and routes in one request share preparation. This avoids a national
observation audit for each small request. Metadata inspection still depends on
store size, and checking a selected file reads all its bytes. Damage confined to
unselected observation bytes can remain undiscovered until a relevant read or
complete audit.

Set `RIVRETRIEVE_CACHE_DIR` to override the platform's user cache directory.
The following operations make no source request:

- `cache_status(provider)` checks stored metadata and reports committed data,
  interrupted work, cleanup residue and active ownership separately. It does not
  read every observation byte.
- `audit_cache(provider)` checks every saved file and observation. A returned
  `CacheAuditResult` identifies the generation checked and reports partition, row
  and byte counts. Missing or damaged data raises an error. This local check does
  not repeat certification against original publisher artifacts.
- `recover_cache(provider)` validates committed data and finishes recognized
  interrupted work. It returns the resulting status and actions. It refuses an
  active writer or ambiguous state rather than guessing which data to restore.
- `clear_cache(provider)` deletes that provider's store and recognized interrupted
  work, including preserved downloads. This is destructive consent. It leaves the
  small coordination file used to prevent conflicting local operations.

For example, after an interrupted preparation:

```python
recovery_status = rr.cache_status("ca_eccc")
unfinished_paths = recovery_status.interrupted_paths
cleanup_paths = recovery_status.cleanup_paths

recovery = rr.recover_cache("ca_eccc")
actions_taken = recovery.actions
resulting_status = recovery.status
```

A first installation can have unfinished work without any committed observations.
Its status is `interrupted`, not `absent`. Recovery discards that uncommitted stage.
During replacement, the previous committed store remains identifiable. After the
new store is committed, failed cleanup does not undo it. A
`StorePostCommitCleanupError` retains the initiating error, cleanup errors,
authoritative path and remaining paths. Inspect the status before retrying.

The guarantee covers local process interruption while the operating system and
filesystem continue running. Concurrent reading during replacement, distributed
coordination and host or power failure are not covered. The configured cache root
may be a symlink; managed provider directories and store contents must not be.
Clear removes terminal managed symlinks without following their targets and never
removes unrelated siblings.

Canada (`ca_eccc`) and Poland (`pl_imgw`) read compiled stores from bulk downloads.
Without a store, retrieval returns an empty result and an issue. Use
`download(provider)` to authorize the national download, which can require substantial
bandwidth and disk space. Both `bypass` and `reuse` read these stores; `refresh`
raises. Use `download` to replace a store. Polish daily archive series have no
archive-wide statistic, so they do not match an explicit mean-statistic filter.

## Provenance

```python
print(result.provenance.provider_id, result.provenance.source)

# Output:
# usgs_nwis live

# Inspect the resolved scope and original source-call records.
request_scope = result.provenance.request
source_calls = result.provenance.calls_made
```

Provenance records request scope, applicable source calls, source terms and cache
context. Returned calls support observations, successful empty answers, applicable
diagnostics or inventory evidence. An inventory retains its original scope and
members, so its dependencies can include evidence beyond the selected rows.
All calls made during the current fetch remain, including attempts outside the requested dates needed for source access, while calls from earlier acquisitions are limited to evidence relevant to the request.

`requested_at` is the local invocation time. `retrieved_at` is the latest known
original acquisition time among the returned calls, whether the result is fresh,
held or mixed. Reuse does not create a new publisher acquisition. If none of the
returned calls establishes a time, `retrieved_at` remains `None`. Individual calls,
outcomes and `served_intervals` retain their original acquisition times and
unknowns. An acquisition keeps its original window and observation keys even
when only part of it contributes held rows. Older and newer acquisitions can
therefore mention the same key in a mixed result. Use `result.data` for the
selected answer; acquisition records do not define one-to-one row ownership.
A source issue's count still describes its acquisition, not a new count
over selected rows. Failed requests can leave no payload origin.

## Receipts (optional)

Request receipts to inspect source material, such as values before conversion:

```python
receipt_result = rr.fetch(
    chosen_gauges, start="2023-01-01", end="2023-01-01", receipts=True
)

print([entry.authorship.value for entry in receipt_result.receipts.entries])

# Output:
# ['publisher_payload']
```

`publisher_payload` contains bytes handed to the parser. `store_excerpt` contains
cached rows encoded as Parquet by RivRetrieve, not original publisher bytes.
Receipts can include extra rows and native units; they are not a complete
reproducibility archive. Without `receipts=True`, the receipt entries are empty.
See the [receipt reference](reference.md#receipts) for fields and content.

## Maps

For spatial exploration, use the [station map](map.md) or `map(selection)`
with the optional `map` extra. Catalogue descriptions are available offline through
`describe(provider)`; see [catalogue evidence](catalogue-evidence.md).
