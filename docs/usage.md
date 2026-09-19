# Usage

[Documentation index](README.md) · [API reference](reference.md)

Working with RivRetrieve has three main steps: find stations and products, retrieve their
observations, then inspect the data and issues. This page follows that order, then introduces
credentials, caching, provenance and maps.

Run the Python examples in page order in one session. They build on earlier variables.
The retrieval examples use the same USGS gauge and one-day window as the README. Discovery
outputs use the installed catalogue. Observation outputs were checked live on 2026-09-19;
source responses can change. Synthetic and fixture-only outputs are labelled separately.

## Find stations

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

`find` accepts one identifier per filter. `pick` keeps matching entries from its input.
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
for catalogue facts. A `withheld` fact means RivRetrieve lacks an established acquisition record;
it does not mean the source publishes nothing. See [catalogue evidence](catalogue-evidence.md).

## Retrieve and inspect results

Retrieve observations for the one gauge in `chosen_gauges`, not the regional filtering example:

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

The agency's timestamp is retained. `unknown` records that a zone has not been established;
it is not a guess based on station coordinates. A null value, an absent row and a failed request
are different states.

Discharge uses m³/s, stage uses metres, and water temperature uses degrees Celsius. Product
metadata in the selection describes units and temporal properties. Equal units do not establish
equal day definitions, stage datums or scientific comparability. RivRetrieve leaves source
quality judgements uninterpreted and does not compute unpublished products at another frequency.

### Results by provider

`fetch` requires a nonempty selection from one provider. `fetch_by_provider` accepts selections
with several providers and returns a dictionary keyed by provider identifier. This small example
uses just USGS, so it requires no credentials or national downloads:

```python
provider_results = rr.fetch_by_provider(chosen_gauges, start="2023-01-01", end="2023-01-01")
print({provider: item.data.select("station_id", "value").rows() for provider, item in provider_results.items()})
# Output:
# {'usgs_nwis': [('07374000', 10562.183778816001)]}
```

A mixed selection produces a separate entry for each provider. Station identifiers, source terms
and provenance belong to that provider. An empty selection returns `{}` from `fetch_by_provider`
and raises from `fetch`.

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

UTC conversion uses each row's established zone to put its label on a common clock.
An unknown zone gives no offset to apply, so `to_utc` refuses the whole conversion when any row
has `unknown`. The USGS daily result above has unknown zones:

```python
if not result.data["time_zone"].eq("unknown").any():
    utc_result = rr.to_utc(result)
else:
    print("UTC conversion skipped: unknown time zone.")
    # Output:
    # UTC conversion skipped: unknown time zone.
```

This example skips conversion and does not create `utc_result`. For a separate, explicitly
**synthetic** demonstration, construct a row whose fixed offset is given as `+02:00`.
This row is not USGS data and establishes no zone for USGS:

```python
from datetime import datetime

from rivretrieve._internal.observations import ObservationProvenance, ObservationResult, Receipts
from rivretrieve._internal.primitives import ProviderId

synthetic_result = ObservationResult(
    data=pl.DataFrame({
        "time": [datetime(2023, 1, 1, 12)],
        "time_zone": ["+02:00"],
        "station_id": ["example"],
        "product_id": ["stage_instantaneous"],
        "value": [1.0],
    }),
    provenance=ObservationProvenance(source="synthetic", provider_id=ProviderId("example")),
    receipts=Receipts(provider_id=ProviderId("example"), entries=()),
)
synthetic_utc = rr.to_utc(synthetic_result)
print(synthetic_utc.data.select("time", "time_zone").rows())
# Output:
# [(datetime.datetime(2023, 1, 1, 10, 0), '+00:00')]
```

The returned `time` remains naive and `time_zone` becomes `+00:00`. Other result fields remain
unchanged. Converting a label does not establish an unknown daily aggregation interval.

### Issues

RivRetrieve assigns issue severity: `info`, `warning` or `error`. The caller's `on_issue` choice
controls notification, not severity. Issues describe what happened while independent successful
series can still return rows. A failed request differs from a successful answer with no
observations. Inspect issues alongside row counts.

| `on_issue` | Handling of `warning` and `error` issues |
|---|---|
| `"warn"` | Emit `RuntimeWarning` and return the result. This is the default. |
| `"raise"` | Raise `IssuePolicyError` carrying the actionable issues. |
| `"ignore"` | Return the result without notifications. Keep its issues. |

`info` never activates this policy. Here is how to stop on warning or error issues and inspect
the exception. The success output was checked live. The exception output was checked separately
with an authored HTTP 503 test response, not an observed USGS outage:

```python
from rivretrieve._internal.issues import IssuePolicyError

try:
    checked_result = rr.fetch(
        chosen_gauges, start="2023-01-01", end="2023-01-01", on_issue="raise"
    )
    print("No warning or error issues.")
    # Output:
    # No warning or error issues.
except IssuePolicyError as error:
    print("Retrieval raised:", len(error.issues))
    # Output:
    # Retrieval raised: 1
```

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
and catalogue-only observation requests also raise. The current exception import is shown above;
exception classes are not exported at the package root. See [reference](reference.md) for
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

This output comes from a successful cache write. Coverage records a successful answer for an
interval, including an answer with no rows. It does not promise continuous observations.
Refreshing can leave fewer rows, or none. A failed request adds no coverage. RivRetrieve records
retrieval times but leaves freshness judgements to you.

Set `RIVRETRIEVE_CACHE_DIR` to choose a cache location. Environment values take precedence over
the working-directory `.env` file. Without an override, RivRetrieve uses the platform's user
cache directory. `cache_status` inspects local state without network access and refuses malformed
or unsupported stores. `clear_cache(provider)` deletes that provider's store and pending recovery
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

## Provenance and receipts

Use provenance to investigate where a result came from: its provider, request and cache context.
Print a few fields rather than the entire object:

```python
print(result.provenance.provider_id, result.provenance.source)
# Output:
# usgs_nwis live
print(result.provenance.request)
# Output:
# {'series': [{'station_id': '07374000', 'product_id': 'discharge_daily_mean'}], 'start': '2023-01-01T00:00:00', 'end': '2023-01-01T23:59:59.999999'}
```

`calls_made` holds available source-call records, including request parameters and available
response facts. `endpoints` lists distinct URLs from those records. Failed requests can leave
no recorded payload origin, so these fields do not list every attempted address.

`requested_at` records the request instant. `retrieved_at` records the latest known newly fetched
source retrieval instant. On a cache-only read it can be `None`; the retrieval times of already
cached intervals are in `served_intervals`. A newly fetched interval is not also listed as a
served cached interval in that call.

Other fields can hold catalogue evidence, source licence and citation, local queries, and bulk
artifact identity. Read the populated fields for your result. This is not a complete request or
transformation audit: software version and conversion factors are not necessarily recorded.
Source terms are retained without interpreting permission to redistribute data.

Receipts provide source bytes or stored rows for closer inspection of a value. Request them with
`receipts=True`; otherwise `receipts.entries` is empty. This fresh request keeps publisher bytes:

```python
receipt_result = rr.fetch(
    chosen_gauges, start="2023-01-01", end="2023-01-01", receipts=True
)
print([entry.authorship.value for entry in receipt_result.receipts.entries])
# Output:
# ['publisher_payload']
```

- `publisher_payload` contains the exact bytes handed to the parser. For an archive, this can
  be an extracted member rather than the archive itself.
- `store_excerpt` contains stored rows encoded as Parquet by RivRetrieve. Both compiled bulk
  stores and live-provider accumulated caches can return these excerpts. They include query,
  path and format information, with source vintage where applicable. They cannot reconstruct
  the publisher's original bytes.

The earlier `cache="reuse"` call saved this interval. Reading it again with receipts returns a
RivRetrieve-authored excerpt:

```python
cached_receipts = rr.fetch(
    chosen_gauges, start="2023-01-01", end="2023-01-01", cache="reuse", receipts=True
)
print([entry.authorship.value for entry in cached_receipts.receipts.entries])
# Output:
# ['store_excerpt']
```

Receipt rows can extend beyond the final clipped result, and stored values can still be in
native units. Receipt row counts therefore need not equal `result.data` row counts.
See [catalogue evidence](catalogue-evidence.md) for the separate record of catalogue facts.

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
