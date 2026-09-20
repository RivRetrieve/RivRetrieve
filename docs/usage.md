# Usage

[Documentation index](README.md) · [API reference](reference.md)

Working with RivRetrieve has three main steps: find source series by physical facts, retrieve
their observations, then inspect the data and issues. This page follows that order, then introduces
credentials, caching, provenance and maps.

Run the Python examples in page order in one session. They build on earlier variables.
The first retrieval uses the same USGS gauge and one-day window as the README. Later examples
save selections and results, and convert established time zones to UTC.

## Find stations

A **provider** supplies observations, such as the US Geological Survey (`usgs_nwis`).
A **station** is a monitoring site, such as USGS gauge `07374000`.
A **quantity** is discharge, stage or water temperature (`temperature`). A **source series**
is a separately published record at a station. Several source series can share quantity,
frequency and statistic. Finding daily mean discharge can therefore select more than one record.
Equal physical filters do not establish scientific interchangeability.

`find` searches packaged evidence without contacting observation services. Keep station identifiers
as strings so leading zeros survive. Start broadly, then narrow by established facts:

```python
import rivretrieve as rr

# Start with discharge, then ask for established daily means.
discharge = rr.find(provider="usgs_nwis", quantity="discharge")
daily_gauges = rr.pick(discharge, frequency="daily", statistic="mean")
chosen_gauges = rr.pick(daily_gauges, station=["07374000"])

print(rr.series(chosen_gauges).select("station_id").unique().rows())
# Output:
# [('07374000',)]
```

The same physical filters work directly in `find`. Quantity says **what** was measured;
frequency and statistic describe **how it was published**, such as a daily mean. RivRetrieve
uses published daily means rather than calculating them from sub-daily observations.
A service's update cadence does not establish the time span represented by a value.

Known facts are independent. For example, Swiss discharge has established units but incomplete
temporal knowledge. It matches a broad discharge search, not an established daily-mean search.
A daily mean elsewhere can still have an unknown day definition. More specific filters are
not information tiers or quality rankings.

`rr.series(selection)` shows the source records known before retrieval. `rr.series(result)`
also shows identities found in the response. The packaged catalogue is a snapshot, not an
exhaustive census of current or historical series. An unrestricted selection includes later
matching discoveries; it does not freeze retrieval to the catalogue's known members.

### Narrow and save selections

Use `pick` for physical filters or explicit `variant` and `series_id` restrictions. Source variant
vocabulary belongs to each publisher, not a harmonised ranking. No policy substitutes a sibling.
`pick` accepts a list of station, provider or source identifiers.

Save the complete selection as a versioned bundle:

```python
from pathlib import Path

selection_path = Path("selection.rrbundle")
selection_path.write_bytes(rr.to_bundle(chosen_gauges))
restored_gauges = rr.from_bundle(selection_path.read_bytes())
```

Bundle version `2` preserves intent, identities, physical evidence and inventory state. Import validates
the bundle without rebuilding identities from today's catalogue. Bare frame imports through
`from_frame` are refused. For custom Polars filtering, inspect a frame and pass selected identifiers
back to `pick`; a frame is not a lossless selection export.

`describe(provider)` returns an offline, machine-readable catalogue description in
[Croissant](https://github.com/mlcommons/croissant) format. It identifies files and the evidence
for catalogue facts. A `withheld` fact means RivRetrieve lacks an established acquisition record. See [catalogue evidence](catalogue-evidence.md).

## Retrieve and inspect results

Retrieve observations for the gauge in `chosen_gauges`:

```python
result = rr.fetch(chosen_gauges, start="2023-01-01", end="2023-01-01")

print(result.data.select("station_id", "value").rows())
# Output:
# [('07374000', 10562.183778816001)]

print(result.issues)
# Output:
# ()
```

The empty tuple means this retrieval reported no issues. An `ObservationResult` carries
`data`, `issues`, `provenance`, `receipts`, `source_series`, `inventories` and `outcomes`.
`data` is a Polars frame. `to_polars()` returns
that frame; `to_pandas()` converts it to a pandas dataframe.

### What you get back

The observation frame has exactly these columns, even when empty:

| Column | Meaning |
|---|---|
| `time` | Naive source wall-clock timestamp, read together with `time_zone` |
| `time_zone` | Established IANA zone, fixed offset, or `unknown` |
| `station_id` | String identifier within the result's provider |
| `product_id` | Source access coordinate, not authority for physical facts |
| `series_id` | Internal source-series identifier |
| `facts_id` | Physical-fact segment identifier |
| `quantity` | Established physical quantity |
| `source_unit` | Exact established source-unit vocabulary |
| `unit` | Harmonised unit of `value` |
| `value` | Float in `unit`, or a published null |

The agency's timestamp is retained. `unknown` means there is no established time zone to use
for conversion to UTC. A null value, an absent row and a failed request
are different states.

Discharge uses m³/s, stage uses metres, and water temperature uses degrees Celsius.
Source-series facts describe units and temporal properties. Equal units do not establish
equal day definitions, stage datums or scientific comparability. RivRetrieve leaves source
quality judgements uninterpreted and does not compute unpublished products at another frequency.

### Series inspection and result views

`rr.series(result)` inspects response-discovered identities and physical facts, with outcomes even
for known series that returned no rows. `result.outcomes` also retains limitations that could not
be assigned a concrete identity. Statuses distinguish `success`, `empty`, `failed`, `unsupported`,
`unresolved` and `no_match`. A null observation remains a row, not a failed request.

An explicit restriction works before or after retrieval. For example, use
`rr.pick(selection, variant="consistido")` before an ANA daily request, or
`rr.pick(result, variant="consistido")` on that request's result. This is publisher identity,
not a quality preference. Post-fetch narrowing creates a view, not another source request.
Original provenance, receipts and diagnostics remain available; they can describe a broader request.

```python
result_path = Path("result.rrbundle")
result_path.write_bytes(rr.to_bundle(result))
restored_result = rr.from_bundle(result_path.read_bytes())
```

You can also narrow a retrieved result by an inspected internal identifier:

```python
returned_series = rr.series(result)
series_id = returned_series["series_id"][0]
series_view = rr.pick(result, series_id=series_id)
```

Result bundles retain observations, late identities, facts, outcomes, inventory, provenance and
any retained receipts. Observation frames alone do not contain all this context.

`fetch` requires one provider. For selections spanning providers, `fetch_by_provider` returns a
dictionary of separate results. Each retains its provider identity, source terms and outcomes.

### Known facts and source alternatives

The Swiss gauge below illustrates unknown temporal meaning. The Brazilian gauge illustrates
a different property: two separately published series with the same established physical facts.
Neither case implies a quality ranking. These searches do not require credentials or network access.

```python
swiss = rr.find(provider="ch_foen", station="2251", quantity="discharge")
swiss_daily = rr.pick(swiss, frequency="daily", statistic="mean")
print(rr.series(swiss_daily).height)
# Output:
# 0

brazil = rr.find(
    provider="br_ana", station="15400000", quantity="discharge", frequency="daily", statistic="mean"
)
print(sorted(rr.series(brazil)["variant"].to_list()))
# Output:
# ['bruto', 'consistido']
consistido = rr.pick(brazil, variant="consistido")
```

Fetching `brazil` requests both Bruto and Consistido. Fetching `consistido` explicitly requests
only that source alternative. Brazil requires the credentials described below. There is no
library preference between the two. Source vocabulary is preserved, not converted into a
harmonised quality score. Provider-specific observation quality flags are not added to the output.

For a supported singleton, no variant choice is needed. Lithuania's Anykščiai gauge uses the
same workflow:

```python
lithuania = rr.find(
    provider="lt_lhmt", station="anyksciu-vms", quantity="discharge", frequency="daily", statistic="mean"
)
lithuanian_result = rr.fetch(lithuania, start="2023-01-01", end="2023-01-01")
print(lithuanian_result.data["series_id"].n_unique())
# Output:
# 1
```

An unknown variant never falls back to the singleton. `on_issue="ignore"` keeps the diagnostic
without a notification; `"warn"` also emits a warning, and `"raise"` raises `IssuePolicyError`.
Lithuania's supported singleton does not establish an exhaustive source inventory:

```python
no_variant = rr.pick(lithuania, variant="nonexistent", on_issue="ignore")
print(rr.series(no_variant).height, [issue.code for issue in no_variant.issues])
# Output:
# 0 ['selection.unresolved_inventory']
```

This empty inspection table does not prove that the requested source identity does not exist.
The restriction remains unresolved and is retained for retrieval, rather than replaced by a known
series. By contrast, contradictory restrictions establish no match. Asking for `"nonexistent"`
within the already restricted Consistido selection cannot match:

```python
no_match = rr.pick(consistido, variant="nonexistent", on_issue="ignore")
print(rr.series(no_match).height, [issue.code for issue in no_match.issues])
# Output:
# 0 ['selection.no_match']
```

A complete acquired inventory can also establish no match. No issue policy substitutes another
series. Inspect selection issues and retrieved outcomes to distinguish no-match from uncertainty.

### Request windows and UTC

`start` and `end` use the source's wall-clock time: the labels on its own clock, rather than UTC
instants. Both endpoints are included. Use ISO date strings (`"2023-01-01"`), ISO datetime strings
without a zone (`"2023-01-01T06:00"`), or naive Python `datetime` objects.
Python `date` objects and values carrying time zones raise errors. `start` is required.

A date-only start means midnight. A date-only end includes the date's final instant.
Daily products are clipped by calendar date; other products are clipped by their source time
labels. Omit `end` to use the caller machine's current local date through its final instant.
A future end stays unchanged and adds an `info` issue. See the [reference](reference.md) for
request and conversion details.

UTC conversion uses each row's established time zone to put its timestamp on a common clock.
USGS instantaneous observations include an offset in their timestamps. Retrieve two readings
from the same gauge and convert them:

```python
instant_gauge = rr.find(
    provider="usgs_nwis", station="07374000", quantity="discharge", statistic="instantaneous"
)
instant_result = rr.fetch(
    instant_gauge, start="2023-01-01T00:00", end="2023-01-01T00:15"
)

print(instant_result.data.select("time", "time_zone").rows())
# Output:
# [(datetime.datetime(2023, 1, 1, 0, 0), '-06:00'), (datetime.datetime(2023, 1, 1, 0, 15), '-06:00')]

utc_result = rr.to_utc(instant_result)

print(utc_result.data.select("time", "time_zone").rows())
# Output:
# [(datetime.datetime(2023, 1, 1, 6, 0), '+00:00'), (datetime.datetime(2023, 1, 1, 6, 15), '+00:00')]
```

The returned `time` remains naive and `time_zone` becomes `+00:00`. Other result fields remain
unchanged. If any row has an unknown time zone, as in the USGS daily result, `to_utc` raises
because it cannot determine the offset needed to convert that timestamp.
Converting timestamps preserves the source's daily aggregation definition, including unknowns.

### Issues

Issues describe what happened during retrieval. Each has a severity: `info`, `warning` or
`error`. Independent successful series can still return rows when another series fails.
Choose `on_issue` to warn and continue, stop on an issue, or handle notifications yourself.
A failed request differs from a successful answer with no observations. Inspect issues alongside row counts.

| `on_issue` | Handling of `warning` and `error` issues |
|---|---|
| `"warn"` | Emit `RuntimeWarning` and return the result. This is the default. |
| `"raise"` | Raise `IssuePolicyError` carrying the actionable issues. |
| `"ignore"` | Return the result without notifications. Keep its issues. |

`info` issues remain available without triggering a warning or exception. To stop when a
retrieval reports warning or error issues, choose `raise`:

```python
checked_result = rr.fetch(
    chosen_gauges, start="2023-01-01", end="2023-01-01", on_issue="raise"
)

print(checked_result.issues)
# Output:
# ()
```

If an issue triggers this policy, the call raises `IssuePolicyError`. You can catch it with
`from rivretrieve._internal.issues import IssuePolicyError` and inspect its `issues`.

To handle notifications yourself, use `ignore` and inspect the retained issues:

```python
quiet_result = rr.fetch(
    chosen_gauges, start="2023-01-01", end="2023-01-01", on_issue="ignore"
)

print([(issue.severity, issue.code) for issue in quiet_result.issues])
# Output:
# []
```

The first retrieval example uses the default `warn` policy. Both `warn` and `ignore` return
issues with their severity, code, message and available failure details. HTTP 404 produces a warning issue. Other
unsuccessful statuses, rejected credentials and exhausted transport retries produce error
issues. An all-failed request can return an empty observation frame with issues and outcomes.

Broken stage contracts raise independently of `on_issue`. Invalid windows, missing credentials
and catalogue-only observation requests also raise. See [reference](reference.md) for
exception locations and [architecture](architecture.md) for failure isolation.

## Supplied credentials

Most providers are open. Norway (`no_nve`) requires `NVE_API_KEY`; Brazil (`br_ana`) requires
`ANA_IDENTIFICADOR` and `ANA_SENHA`. Supply the required values in your process environment or a
`.env` file in your working directory. [.env.example](../.env.example) lists the names without
usable secrets. Keep credential files out of version control.

`providers()` reports credential variable names and an `access` indicator: `open`, `ready`,
or `missing <variable names>`. `ready` means the values are present, not that the agency has
accepted them. It does not describe observation capability; see the
[software declarations](reference.md) for provider kinds.

Environment values take precedence over `.env`. A blank environment value shadows the file
and counts as missing. Required credentials are checked even for cache reads, so keep them
configured when reusing data. All selected providers are checked before mixed-provider retrieval
starts: missing credentials stop that request before any provider retrieves observations.
Credentials are sent only to configured agency addresses; retained request metadata excludes
credential values. Do not put secrets into scripts, screenshots or issue reports.

## Cache and bulk downloads

Live retrieval defaults to `cache="bypass"`. Choose another mode explicitly:

| Mode | Live observation behavior |
|---|---|
| `"bypass"` | Fetch without reading or writing the observation cache |
| `"reuse"` | Serve a fully covered scoped inventory locally; otherwise reacquire the requested scope |
| `"refresh"` | Replace the requested interval with the source's current successful answer |

To reuse this one-day request later:

```python
cached_result = rr.fetch(chosen_gauges, start="2023-01-01", end="2023-01-01", cache="reuse")
status = rr.cache_status("usgs_nwis")

print(status.exists)
# Output:
# True
```

Reuse checks the requested source scope against held inventory and successful coverage.
If that proof is insufficient, it reacquires the full requested scope with the provider's
normal padded fetch windows, not only uncovered intervals.
Coverage is tracked per concrete source series and time interval, separately from inventory.
An all-series request needs a complete scoped inventory and coverage of every required member;
a cached subset is not enough. A successful empty series can establish interval coverage.
Reuse serves the recorded inventory vintage, not a promise of current-source freshness.
Refreshing can leave fewer rows, or none. Failed or unsupported acquisition can retain held
successful observations at their original retrieval vintage, alongside the new diagnostics.
Those held observations are not a new successful source answer. Failed requests add no
successful coverage. RivRetrieve records retrieval times but leaves freshness judgements to you.

Set `RIVRETRIEVE_CACHE_DIR` to choose a cache location. Without an override, RivRetrieve uses
the platform's user cache directory. `cache_status` inspects local state without network access
and refuses malformed or unsupported stores. Current compiled stores use revision `5`; live
accumulated stores use revision `7`. Incompatible old files remain intact until explicit cleanup
or rebuild; old collapsed observations are not assigned invented identities. `clear_cache(provider)` deletes that provider's store and pending recovery
inputs, including preserved downloads. It returns a removal summary and leaves other providers
alone. See [architecture](architecture.md#storage-and-reuse) for storage details.

Canada (`ca_eccc`) and Poland (`pl_imgw`) use compiled stores prepared from bulk downloads.
Polish archive series have established daily frequency but no archive-wide statistic.
They match daily quantity filters, not a `statistic="mean"` filter.
Without a store, retrieval returns an empty result and an issue. It does not start a national
download. Calling `download(provider)` gives explicit consent to that transfer, which can use
substantial bandwidth and disk space:

```python
# Optional national download, deliberately disabled in this walkthrough.
# rr.download("ca_eccc")
```

For bulk providers, `bypass` and `reuse` both read the compiled store; `refresh` raises before
transfer. Use `download(provider)` to replace it. After successful compilation the publisher
artifact is deleted, while its identity remains recorded.

## Provenance

`result.data` contains harmonised observations. `result.provenance` records request and
origin information, which helps you check where those observations came from:

```python
print(result.provenance.provider_id, result.provenance.source)
# Output:
# usgs_nwis live

# Inspect the resolved scope and original source-call records.
request_scope = result.provenance.request
source_calls = result.provenance.calls_made
```

Provenance includes available source-call records, source terms and cache context.
Failed requests can leave no recorded payload origin. On a cache-only read, `retrieved_at`
can be `None`; retrieval times for cached intervals are in `served_intervals`.
See the [reference](reference.md) for the provenance fields.

## Receipts (optional)

Request receipts when you want inspectable source material, for example to check values before
unit conversion:

```python
receipt_result = rr.fetch(
    chosen_gauges, start="2023-01-01", end="2023-01-01", receipts=True
)

print([entry.authorship.value for entry in receipt_result.receipts.entries])
# Output:
# ['publisher_payload']
```

- `publisher_payload` holds the bytes handed to the parser, such as an extracted archive member.
- `store_excerpt` holds cached rows encoded as Parquet by RivRetrieve, rather than the original
  publisher bytes. Both live caches and compiled bulk stores can return these excerpts.

Receipts can contain extra rows and values in native units. They help inspect source material;
they are not a full reproducibility archive. Without `receipts=True`, `receipts.entries` is empty.
See the [receipt reference](reference.md#receipts) for receipt fields and content.

## Maps

Maps let you inspect station coverage. Install `uv add "rivretrieve[map]"` before running this
example. It saves a Folium map with one marker per selected station, here the same gauge used
for retrieval:

```python
station_map = rr.map(chosen_gauges)
station_map.save("stations.html")
```

Open `stations.html` in a browser. Markers show the catalogue's CRS statement. Unknown-CRS markers
are orange; their coordinates are rendered as if they used EPSG:4326. That display assumption
does not establish their reference system or change the catalogue. Without Folium, `map` raises
`MissingOptionalDependencyError`.

## Moving from the old interface

Replace `product="discharge_daily_mean"` in `find` or `pick` with
`quantity="discharge", frequency="daily", statistic="mean"`. The `product=` input was removed;
it is not an alias. Do not translate a source-specific suffix into a physical statistic.
For ANA's former Consistido product, use the physical filters plus `variant="consistido"`.
Without that restriction, both matching daily series are requested.

Results are no longer five-column, station/product-only tables. Preserve `series_id` and
`facts_id` when saving observations, and use `rr.series(result)` for their meaning. Joining only
on station and time can combine distinct source records. The output `product_id` remains an
access coordinate, not authority for physical facts. Use version-2 bundles to retain the full
selection or result; bare frames and version-1 bundles are not lossless imports.

Old accumulated caches (including revision 6) and incompatible compiled stores are refused,
not silently upgraded. Current revisions are 7 for accumulated caches and 5 for compiled stores.
Preserve any needed old files before explicit cleanup with `rr.clear_cache(provider)`, which
also deletes pending downloads. For live sources, fetch again with `cache="reuse"` to rebuild.
For Canada or Poland, call `rr.download(provider)` to download and rebuild the compiled store.
Refusal alone leaves old files intact; no source identities are invented for collapsed old rows.

For less common filters (`temporal_support`, `day_definition`, `timestamp_anchor`, `time_zone`,
`vertical_reference`, `vertical_datum`) and inspection evidence states, see the
[API reference](reference.md). Unknown facts cannot satisfy precise predicates. Established
quantity, source unit and conversion are required; `on_issue` cannot bypass that requirement.
