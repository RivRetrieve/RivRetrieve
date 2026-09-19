# Usage

[Documentation index](README.md) · [API reference](reference.md)

Working with RivRetrieve has three main steps: find stations and products, retrieve their
observations, then inspect the data and issues. This page follows that order, then introduces
credentials, caching, provenance and maps.

Run the Python examples in page order in one session. They build on earlier variables.
The first retrieval uses the same USGS gauge and one-day window as the README. Later examples
add a second provider and convert established time zones to UTC.

## Find stations

A **provider** supplies observations, such as the US Geological Survey (`usgs_nwis`).
A **station** is a monitoring site, such as USGS gauge `07374000`.
A **product** names a variable, a statistic and a time step. `discharge_daily_mean` is
source-published daily mean discharge; `stage_instantaneous` is a stage reading at a given
moment. Supported variables are discharge, stage and water temperature.
A **series** is one product at one station of one provider.

`find` searches the packaged catalogue: station and product lists included with the installed
package. This does not contact the agencies. Keep station identifiers as strings so leading
zeros survive.

```python
import rivretrieve as rr

print(rr.products("usgs_nwis"))
# Output:
# ['discharge_daily_mean', 'discharge_instantaneous', 'stage_daily_max', 'stage_daily_mean', 'stage_daily_min', 'stage_instantaneous']

daily_gauges = rr.find(provider="usgs_nwis", product="discharge_daily_mean")
chosen_gauges = rr.pick(daily_gauges, station=["07374000"])

print(rr.as_frame(chosen_gauges).select("provider_id", "station_id", "product_id").rows())
# Output:
# [('usgs_nwis', '07374000', 'discharge_daily_mean')]
```

`find` returns a selection object. `as_frame` turns it into a Polars table, with one row per
series. The example prints only the three identity columns as a list of rows.

| Group | Columns |
|---|---|
| Identity | `provider_id`, `station_id`, `product_id` |
| Position | `latitude`, `longitude`, `crs` (`unknown` when not established) |
| Product | `observed_property`, `frequency`, `statistic`, `period_type`, `period_anchor`, `unit`, `native_id` |
| Catalogue | `availability`, `availability_reason`, `published_record_start_date`, `published_record_end_date`, `last_catalogue_check` |

`native_id` is the agency's own product code. For USGS, `00060:00003` combines discharge
(`00060`) and daily mean (`00003`).

`find` accepts one provider, station or product per filter. For example,
`provider="usgs_nwis"` selects USGS and `product="discharge_daily_mean"` selects daily mean discharge.
`pick` keeps matching entries from its input.
The square brackets in `station=["07374000"]` make a Python list; add more station strings
to select several at once. `pick` cannot introduce a station or product absent from its input.
Unknown identifiers raise errors. When recognised identifiers have no matching selectable
combination, the selection is empty. Its `empty_reason` explains why.

The catalogue helps you choose series:

- `available` means the agency listed data for that station and product. Today's request can
  still return no observations.
- Entries with `unknown` availability can be selected.
- Published record dates do not establish complete records or limit the dates you can request.
- Entries were captured on different dates.

### Filter with Polars

To keep stations north of a latitude, use a Polars expression. This separate regional example
leaves `chosen_gauges` unchanged for later retrieval.

```python
import polars as pl

regional_gauges = rr.pick(daily_gauges, station=["01013500", "01022500", "07374000"])
frame = rr.as_frame(regional_gauges)
northern_frame = frame.filter(pl.col("latitude") > 45)
northern_gauges = rr.from_frame(northern_frame)

print(rr.as_frame(northern_gauges).select("station_id", "latitude").rows())
# Output:
# [('01013500', 47.2375)]
```

`from_frame` rebuilds a selection after custom filtering. The columns `provider_id`,
`station_id` and `product_id` must appear in that relative order. They must contain strings
with no missing values. Each three-column combination must be unique and correspond to a
selectable catalogue entry. Individual strings can repeat: several stations can share the
same provider and product. Filtering an unchanged `as_frame` table preserves its column structure.
Other columns do not override catalogue metadata; RivRetrieve rebuilds it from the catalogue.
See the [reference](reference.md) for the full selection interface.

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
`data`, `issues`, `provenance` and `receipts`. `data` is a Polars frame. `to_polars()` returns
that frame; `to_pandas()` converts it to a pandas dataframe.

### What you get back

The observation frame has exactly these columns, even when empty:

| Column | Meaning |
|---|---|
| `time` | Naive source wall-clock timestamp, read together with `time_zone` |
| `time_zone` | Established IANA zone, fixed offset, or `unknown` |
| `station_id` | String identifier within the result's provider |
| `product_id` | Canonical product identifier |
| `value` | Float in the product's canonical unit, or a published null |

The agency's timestamp is retained. `unknown` means there is no established time zone to use
for conversion to UTC. A null value, an absent row and a failed request
are different states.

Discharge uses m³/s, stage uses metres, and water temperature uses degrees Celsius. Product
metadata in the selection describes units and temporal properties. Equal units do not establish
equal day definitions, stage datums or scientific comparability. RivRetrieve leaves source
quality judgements uninterpreted and does not compute unpublished products at another frequency.

### Results by provider

`fetch_by_provider` retrieves observations from several providers and returns a dictionary
with one result per provider. Here, combine the USGS gauge with a gauge from Lithuania's
Hydrometeorological Service (`lt_lhmt`). Both provide this daily discharge data without credentials:

```python
lithuanian_gauge = rr.find(
    provider="lt_lhmt", station="anyksciu-vms", product="discharge_daily_mean"
)
mixed_gauges = rr.from_frame(pl.concat([
    rr.as_frame(chosen_gauges), rr.as_frame(lithuanian_gauge)
]))
provider_results = rr.fetch_by_provider(mixed_gauges, start="2023-01-01", end="2023-01-01")
usgs_result = provider_results["usgs_nwis"]
lithuanian_result = provider_results["lt_lhmt"]

print(usgs_result.data.select("station_id", "value").rows())
# Output:
# [('07374000', 10562.183778816001)]

print(lithuanian_result.data.select("station_id", "value").rows())
# Output:
# [('anyksciu-vms', 81.8)]
```

Each result has its own data, issues and provenance. Station codes belong to their provider.
Use `fetch` for a nonempty selection from one provider.

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
    provider="usgs_nwis", station="07374000", product="discharge_instantaneous"
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
issues. An all-failed request can return an empty five-column frame with issues.

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
| `"reuse"` | Serve covered intervals and fetch their uncovered remainder |
| `"refresh"` | Replace the requested interval with the source's current successful answer |

To reuse this one-day request later:

```python
cached_result = rr.fetch(chosen_gauges, start="2023-01-01", end="2023-01-01", cache="reuse")
status = rr.cache_status("usgs_nwis")

print(status.exists)
# Output:
# True
```

For example, request ten stations with `cache="reuse"`. If four stations have full coverage
for the requested product and time interval, RivRetrieve serves those four from cache and
fetches the other six. If a station is partially covered, it fetches only the missing interval.
Coverage is tracked for each station, product and time interval. A successful answer counts as
coverage even when it contains no rows.
Refreshing can leave fewer rows, or none. A failed request adds no coverage. RivRetrieve records
retrieval times but leaves freshness judgements to you.

Set `RIVRETRIEVE_CACHE_DIR` to choose a cache location. Without an override, RivRetrieve uses
the platform's user cache directory. `cache_status` inspects local state without network access
and refuses malformed or unsupported stores. `clear_cache(provider)` deletes that provider's store and pending recovery
inputs, including preserved downloads. It returns a removal summary and leaves other providers
alone. See [architecture](architecture.md#storage-and-reuse) for storage details.

Canada (`ca_eccc`) and Poland (`pl_imgw`) use compiled stores prepared from bulk downloads.
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

print(result.provenance.request)
# Output:
# {'series': [{'station_id': '07374000', 'product_id': 'discharge_daily_mean'}], 'start': '2023-01-01T00:00:00', 'end': '2023-01-01T23:59:59.999999'}
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
