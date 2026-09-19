# Usage

[Documentation index](README.md) · [API reference](reference.md)

Working with RivRetrieve has three main steps: find the stations you want, retrieve their observations,
and check what came back. This page walks through those steps, then through credentials, caching,
provenance and maps.

## What you get back

A **product** names a variable, a statistic and a time step. `discharge_daily_mean` is the mean
discharge over a day, while `stage_instantaneous` is a stage reading at one moment. The current supported variables are
discharge, stage and water temperature.

A **series** is one product at one station of one provider. Retrieval returns a Polars frame with
exactly these columns, including when it is empty:

| Column | Meaning |
|---|---|
| `time` | Source-native, naive wall-clock timestamp |
| `time_zone` | Source-established IANA name, fixed offset, or `unknown` |
| `station_id` | String identifier within the result's provider |
| `product_id` | Canonical product identifier |
| `value` | Float value in the product's canonical unit, or a published null |

Read `time` together with `time_zone`. RivRetrieve keeps the agency's own timestamps instead of
converting everything to UTC, and `unknown` means the agency does not state a zone. It is an answer,
not a gap: you will meet it for zones, for time steps and for a station's availability.

Units are harmonised: discharge uses m³/s and stage uses metres. What is not harmonised is the
measurement itself. Equal units do not establish equal day definitions, stage datums, or scientific
comparability. RivRetrieve does not reconstruct quality flags, infer source judgements, or compute
an unpublished product from another frequency.

## Find stations

`find` reads packaged catalogues without querying observation services. A selection
contains unique `(provider_id, station_id, product_id)` series. Keep station identifiers
as strings so leading zeros survive.

```python
import rivretrieve as rr

print(rr.products("usgs_nwis"))
selection = rr.find(provider="usgs_nwis", product="discharge_daily_mean")
selection = rr.pick(selection, station=["01013500", "01022500", "01030500"])
print(rr.as_frame(selection))
```

`find` accepts one identifier per filter. `pick` narrows an existing selection and
also accepts sequences. It never adds series. Unknown identifiers raise rather than
triggering approximate matching. A valid identifier with no station offering that product
produces an empty selection with an `empty_reason`.

What the catalogue does and does not tell you:

- Availability `unknown` remains selectable.
- An `available` entry does not promise that today's service will return the requested
  observations.
- Published record bounds describe a source-stated envelope, not continuity. They do not prevent
  retrieval.
- The snapshot can contain mixed acquisition dates.

For other predicates, filter the Polars frame and rebuild the selection:

```python
import polars as pl

frame = rr.as_frame(selection)
chosen = frame.filter(pl.col("station_id") == "01013500")
selection = rr.from_frame(chosen)
```

`from_frame` reads the three identity columns in canonical order. They must contain
unique, non-null strings and existing selectable triples. Other columns do not override
catalogue facts. RivRetrieve rebuilds their metadata from the packaged catalogue.
See the [reference](reference.md) for every column of a selection frame.

`describe(provider)` returns a machine-readable description of the packaged catalogue, in Croissant
format, without going online. It identifies catalogue files, where facts came from, and what is
recorded as absent. A `withheld` fact means RivRetrieve has no established record of how the fact
was acquired. It does not mean the source publishes nothing. See
[catalogue evidence](catalogue-evidence.md) for the schema and inspection API.

## Retrieve and inspect results

```python
result = rr.fetch(selection, start="2025-01-01", end="2025-12-31")
print(result.data)
print(result.issues)
print(result.provenance)
```

`fetch` requires a nonempty selection from one provider. `fetch_by_provider` returns a
dictionary keyed by provider identifier for mixed selections. An empty selection gives
`{}` from `fetch_by_provider`, but raises from `fetch`. Results remain separate because
station identifiers and provenance belong to a provider.

An `ObservationResult` carries `data`, `issues`, `provenance` and `receipts`.
`data` is a Polars frame, described in [what you get back](#what-you-get-back). `to_polars()`
returns that frame and `to_pandas()` converts it. Product metadata in the selection states units
and temporal properties.

### Time windows

Both endpoints describe wall-clock time in each source's calendar. The interval is
closed at both ends. `start` is required despite the signature's `None` default.
Use ISO date strings, ISO datetime strings without a zone, or naive `datetime` objects.
Python `date` objects and zone-carrying endpoints raise.

A bare start date begins at midnight. A bare end date includes its final instant.
For daily products, clipping compares dates. For other temporal products, it compares
source time labels. Omitting `end` uses the caller machine's current local date through
its last instant. A future end stays unchanged and adds an informational issue.

To convert a result to UTC, every row must carry an established zone:

```python
# Only use this when every returned row has an established zone.
if not result.data["time_zone"].eq("unknown").any():
    utc_result = rr.to_utc(result)
```

`to_utc` refuses the whole conversion if any row has zone `unknown`.
It does not return a partly converted frame. The returned `time` remains naive and
`time_zone` becomes `+00:00`. Other result fields remain unchanged. This does not
establish an unknown daily aggregation interval.

### Issues

Issues describe what happened without discarding rows from independent successful
series. A failed request is not the same as a successful answer with no observations.
Inspect `issues` as well as row counts before using a result.

| `on_issue` | Handling of `warning` and `error` issues |
|---|---|
| `"warn"` | Emit `RuntimeWarning` and return the result. This is the default. |
| `"raise"` | Raise `IssuePolicyError` carrying the actionable issues. |
| `"ignore"` | Return the result without notifications. Keep its issues. |

`info` never activates this policy. An `error` severity is not necessarily fatal.
The engine isolates source failures for each requested series. HTTP 404 becomes a
warning issue. Other unsuccessful statuses, rejected credentials and exhausted transport
retries become error issues. An all-failed request returns an empty five-column frame
under the default policy.

Broken stage contracts raise independently of `on_issue`. Invalid windows, missing
credentials and catalogue-only observation requests also raise. The exception classes
currently live in internal modules rather than at the package root:

```python
from rivretrieve._internal.issues import IssuePolicyError
```

Use only the three documented policy strings. See [reference](reference.md) for exception
locations and [architecture](architecture.md) for the failure boundary.

## Supplied credentials

Most providers are open. Where an agency requires credentials, you request them yourself and give
them to RivRetrieve through the environment.

`providers()` reports credential variable names and an access indicator. It does not
report observation capability. `ready` means required values are present, not that a
source accepted them. Consult the generated [software declarations](reference.md) for
provider kinds.

Set supplied values in the process environment or a `.env` file in the working directory.
The environment takes precedence. A blank environment value shadows the file and counts
as missing. [.env.example](../.env.example) lists names without usable secrets.
Do not commit credential files or put values into scripts, screenshots or issue reports.
How to obtain credentials from each agency will be covered by the provider pages.

Retrieval checks required credentials before requesting observations, including cache
hits. A mixed-provider request checks all selected providers before retrieval.
The transport confines credential headers to declared origins. Receipt origins exclude
request headers. Authentication traces retain header names and request shape, not secrets.

## Cache and bulk downloads

Live retrieval defaults to `cache="bypass"`. Select another mode explicitly:

| Mode | Live observation behavior |
|---|---|
| `"bypass"` | Fetch from the source without reading or writing the observation cache |
| `"reuse"` | Serve covered intervals and fetch their uncovered remainder |
| `"refresh"` | Replace the requested interval with the source's current successful answer |

```python
result = rr.fetch(selection, start="2025-01-01", end="2025-12-31", cache="reuse")
status = rr.cache_status("usgs_nwis")
print(status)
```

What coverage means:

- It records that the source was successfully asked, not that every expected observation exists.
- A successful empty answer creates coverage too.
- Refresh can replace held values with fewer rows or none.
- Failed series do not gain new coverage.
- RivRetrieve assigns no expiry or freshness verdict. Retrieval instants travel with served
  intervals in provenance.

Bulk providers read compiled stores rather than making per-request downloads.
Without a store, retrieval returns an empty result with an issue. It never starts a
national download implicitly. Calling `download` grants explicit consent to that transfer
and compilation. It can require substantial network traffic and disk space.

```python
# Explicit bulk consent. Do not run merely to inspect the catalogue.
# rr.download("ca_eccc")
```

For bulk providers, `bypass` and `reuse` both read the compiled store.
`refresh` raises before transfer. Call `download(provider)` explicitly to replace the store.
After successful compilation, the publisher artifact is deleted. The manifest retains
its identity. See [storage contracts](architecture.md) for retained native values and formats.

Set `RIVRETRIEVE_CACHE_DIR` to choose a cache root. The same environment-over-working-file
precedence applies. Without an override, RivRetrieve uses the platform's user cache directory.
Each provider uses `<root>/<provider_id>/store`. `cache_status` reports local state without
network access and refuses malformed or unsupported stores.

`clear_cache(provider)` is destructive. It removes that provider's store and pending
recovery inputs, including preserved downloads and write staging directories. It returns
a removal summary. It does not clear unrelated providers.

## Provenance and receipts

Provenance identifies the provider, normalized requested window and available source-call
origins. It can also carry catalogue evidence, license and citation statements, store
queries, served intervals and bulk artifact identities. Inspect these fields rather than
assuming every optional field is populated. RivRetrieve does not interpret source terms
or decide whether redistribution is permitted.

Provenance is not a complete transformation audit. The current result does not necessarily
populate its RivRetrieve version or record conversion factors. Unit conversion does not
currently emit a conversion-info issue. Consult [architecture](architecture.md) and the
linked configuration for the traced conversion.

```python
result = rr.fetch(selection, start="2025-01-01", end="2025-12-31", receipts=True)
for entry in result.receipts.entries:
    print(entry.authorship.value, entry.origin)
    print(len(entry.content))
```

Receipts are opt-in bytes, not parsed quality assessments. Without `receipts=True`,
the result's receipt container exists but has no entries.

- `publisher_payload` contains the publisher-authored bytes passed to parse.
  An extracted archive member can be such a payload.
- `store_excerpt` contains Parquet bytes authored by RivRetrieve from rows read from
  its store. It includes the executed query, path, format version and source vintage
  where applicable. It does not reconstruct the original publisher file.

A receipt can include rows that later clipping removes, including padded bulk queries.
It therefore need not have the same row count as `result.data`. Check authorship before
using it to audit a value. See [catalogue evidence](catalogue-evidence.md) for the separate
acquisition record carried by selections and provenance.

## Maps

Install `uv add "rivretrieve[map]"` in your project before calling `map`.
The function returns a Folium map with one marker per selected station:

```python
station_map = rr.map(selection)
station_map.save("stations.html")
```

Markers show the catalogue's CRS statement. Unknown CRS markers appear orange.
The map renders unknown-frame coordinates as if they used EPSG:4326. This display
assumption does not establish their reference system or change the catalogue. Without Folium, `map`
raises `MissingOptionalDependencyError`. Reading these Markdown pages needs no mapping dependency.
