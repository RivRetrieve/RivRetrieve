# Usage

[Documentation index](README.md) · [API reference](reference.md)

Working with RivRetrieve has three main steps: find source series by physical facts, retrieve
their observations, then inspect the data and issues. This page follows that order, then introduces
credentials, caching, provenance and maps.

Run the Python examples in page order in one session. They build on earlier variables.
The first retrieval uses the same USGS gauge and one-day window as the README. Later examples
save selections and results, and convert established time zones to UTC. The Brazil download
example needs ANA credentials; the USGS and Lithuanian examples do not.

## Find stations

A **provider** supplies observations, such as the US Geological Survey (`usgs_nwis`).
A **station** is a monitoring site, such as USGS gauge `07374000`.
A **quantity** is discharge, stage or water temperature (`temperature`). A **source series**
is a separately published record at a station. Several source series can share quantity,
frequency and statistic. Finding daily mean discharge can therefore select more than one record.
Two records that match these filters can still differ in ways that matter for your study.

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

print(rr.series(chosen_gauges).select("variant", "description").rows())

# Output:
# [('c9d823a2491f4b639656a11b35a7625d', None)]
```

USGS variants use publisher time-series identifiers. A `None` description means the source
publishes no description; RivRetrieve does not replace it with parameter prose.

The same physical filters work directly in `find`. Quantity says **what** was measured;
frequency and statistic describe **how it was published**, such as a daily mean. RivRetrieve
uses published daily means rather than calculating them from sub-daily observations.
A service's update cadence does not establish the time span represented by a value.

For example, RivRetrieve knows the units of the Swiss discharge values, but not whether they
represent a daily mean. In other words, you can find those values by asking for discharge,
but not by asking specifically for daily mean discharge. A value updated every ten minutes
is not necessarily an average over ten minutes.

`rr.series(selection)` shows the source records known before retrieval. `rr.series(result)`
also shows identities found in the response. The packaged catalogue is a snapshot, not an
exhaustive census of current or historical series. An unrestricted selection includes later
matching discoveries; it does not freeze retrieval to the catalogue's known members.

### Inspect station metadata

```python
stations = rr.metadata(chosen_gauges)
print(stations)

source_attributes = rr.metadata(chosen_gauges, view="source")
```

The station table contains names and coordinates with their CRS. Unresolved name
alternatives leave the summary name null and set its alternatives indicator.
The source view preserves names and separate drainage-area fields with exact
values, units where established, and explicit absence states. Both views work
offline. See [station metadata](station-metadata.md) for interpretation.

### Narrow and save selections

Use `pick` to narrow a selection by physical facts or by `variant` and `series_id`.
A variant is a separately published version of a series, using the agency's own name.
`pick` accepts a list of station, provider or source identifiers. It keeps only what you ask for;
it does not substitute another version.

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
The USGS result preserves `ft^3/s` in `source_unit` while returning `m3/s` in `unit`.
Source-series facts describe units and temporal properties. Equal units do not establish
equal day definitions, stage datums or scientific comparability. RivRetrieve leaves source
quality judgements uninterpreted and does not compute unpublished products at another frequency.

### Series inspection and result views

`rr.series(result)` inspects response-discovered identities and physical facts, with outcomes even
for known series that returned no rows. `result.outcomes` also retains limitations that could not
be assigned a concrete identity. Statuses distinguish `success`, `empty`, `failed`, `unsupported`,
`unresolved` and `no_match`. A null observation remains a row, not a failed request.

You can narrow a selection before retrieval or filter a result afterwards with `pick`.
Filtering a result makes no new source request. Original provenance, receipts and issues remain
available, so they can still describe the broader request.

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

### When the time step is unknown

This Swiss gauge provides discharge values, but their exact time span and statistic are not
established. The first search includes them. Adding daily-mean filters excludes them.
Both searches use the packaged catalogue without contacting the source.

```python
swiss = rr.find(provider="ch_foen", station="2251", quantity="discharge")
swiss_daily = rr.pick(swiss, frequency="daily", statistic="mean")

print(rr.series(swiss_daily).height)

# Output:
# 0
```

### When an agency publishes more than one version

Brazil's ANA publishes **Bruto** (raw) and **Consistido** (quality-checked) daily records.
ANA performs that checking, not RivRetrieve. Both are available: RivRetrieve requests both
unless you explicitly choose one. A source may not have observations for both in every period.
The labels do not tell you which record suits your study.
Provider-specific observation quality flags are not added to the returned table.

Find the two daily mean water-level series (`quantity="stage"`), then optionally choose Consistido:

```python
brazil = rr.find(
    provider="br_ana", station="15400000", quantity="stage", frequency="daily", statistic="mean"
)

print(sorted(rr.series(brazil)["variant"].to_list()))

# Output:
# ['bruto', 'consistido']

consistido = rr.pick(brazil, variant="consistido")
```

The search above works offline. To run the downloads below, first set `ANA_IDENTIFICADOR` and
`ANA_SENHA` in your environment or working-directory `.env` file. See
[supplied credentials](#supplied-credentials). Do not put credential values in the code.

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

### When only one series is available

For Lithuania's Anykščiai gauge, this request returns one daily discharge series.
There is no extra version to choose in this example:

```python
lithuania = rr.find(
    provider="lt_lhmt", station="anyksciu-vms", quantity="discharge", frequency="daily", statistic="mean"
)

lithuanian_result = rr.fetch(lithuania, start="2023-01-01", end="2023-01-01")

print(lithuanian_result.data["series_id"].n_unique())

# Output:
# 1
```

### When a requested variant is not found

The catalogue does not always list every variant a source may provide. Asking for a name that
is not listed can therefore mean **“I cannot tell whether that variant is available.”**
RivRetrieve reports this as `selection.unresolved_inventory`:

```python
no_variant = rr.pick(lithuania, variant="nonexistent", on_issue="ignore")

print(rr.series(no_variant).height, [issue.code for issue in no_variant.issues])

# Output:
# 0 ['selection.unresolved_inventory']
```

The empty table means no known series matches. RivRetrieve keeps your requested name for
retrieval; it does not replace it with the one known series.

Sometimes RivRetrieve can tell that nothing matches. The selection `consistido` already allows
only that variant, so filtering it again for `"nonexistent"` leaves nothing:

```python
no_match = rr.pick(consistido, variant="nonexistent", on_issue="ignore")

print(rr.series(no_match).height, [issue.code for issue in no_match.issues])

# Output:
# 0 ['selection.no_match']
```

`selection.no_match` means **“I can tell, and the answer is no: nothing matches these filters.”**
A complete source inventory can also establish that a requested variant is absent.

Both examples use `on_issue="ignore"` to keep the issue without a notification. With `"warn"`,
you also get a warning; with `"raise"`, the call raises `IssuePolicyError`. None of these choices
substitutes a different series.

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
USGS instantaneous observations publish UTC timestamps. Retrieve two readings
from the same gauge and apply UTC conversion; these timestamps already use UTC:

```python
instant_gauge = rr.find(
    provider="usgs_nwis", station="07374000", quantity="discharge", statistic="instantaneous"
)

instant_result = rr.fetch(
    instant_gauge, start="2023-01-01T00:00", end="2023-01-01T00:15"
)

print(instant_result.data.select("time", "time_zone").rows())

# Output:
# [(datetime.datetime(2023, 1, 1, 0, 0), '+00:00'), (datetime.datetime(2023, 1, 1, 0, 15), '+00:00')]

utc_result = rr.to_utc(instant_result)

print(utc_result.data.select("time", "time_zone").rows())

# Output:
# [(datetime.datetime(2023, 1, 1, 0, 0), '+00:00'), (datetime.datetime(2023, 1, 1, 0, 15), '+00:00')]
```

The returned `time` remains naive and `time_zone` is `+00:00`. Other result fields remain
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

HTTP requests that are safe to repeat get at most three attempts for transient timeouts,
connection interruptions, incomplete responses, and retryable statuses. GET and HEAD are
safe to repeat. The Swiss archive query also has established read-only semantics; arbitrary
POST requests do not, and do not automatically follow redirects. Each retry starts the
request again and discards incomplete bytes.
Permanent TLS, protocol, and decoding failures are not retried.

Attempts on one client start at least one second apart. Retry waits are normally one and
two seconds. Valid `Retry-After` guidance can increase a wait, up to 60 seconds per retry.
A longer server delay stops the request rather than retrying too early. Invalid or past
guidance uses the normal wait. Each attempt has a 60-second connection/read timeout,
not a whole-download deadline. Failure details retain the request URL, attempt count,
final available status, and a safe failure category without raw credential-bearing errors.

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
| `"reuse"` | Use cached observations when the complete request is covered; otherwise fetch again |
| `"refresh"` | Replace the requested interval with the source's current successful answer |

To reuse this one-day request later:

```python
cached_result = rr.fetch(chosen_gauges, start="2023-01-01", end="2023-01-01", cache="reuse")
status = rr.cache_status("usgs_nwis")

print(status.exists)

# Output:
# True
```

Reuse needs enough cached information to answer the whole request: which series belong to it,
and whether each was successfully retrieved for the requested interval. For example, cached
Consistido data alone cannot answer a request for both Brazilian series. If coverage is incomplete,
RivRetrieve fetches the full requested scope again, with the provider's normal padded windows.
It does not request only the missing dates.

A successful answer with no rows can still cover an interval. A failed request cannot.
Reuse returns the saved answer, which may differ from what the source publishes now. Use
`refresh` to request a current answer. Refresh can return fewer rows, or none. If a series fails,
RivRetrieve can retain its previously cached observations alongside the new issues. Those rows
keep their original retrieval time; they are not presented as a fresh successful download.

Set `RIVRETRIEVE_CACHE_DIR` to choose a cache location. Without an override, RivRetrieve uses
the platform's user cache directory. `cache_status` inspects local state without network access
and refuses malformed or unsupported stores without deleting them. `clear_cache(provider)`
deletes that provider's store and pending recovery inputs, including preserved downloads. It returns a removal summary and leaves other providers
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

- `publisher_payload` holds the bytes handed to the parser.
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
