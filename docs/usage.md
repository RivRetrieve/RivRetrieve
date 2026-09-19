# Usage

[Documentation index](README.md) · [API reference](reference.md)

Working with RivRetrieve has three main steps: first you find the stations and variables you want,
then you retrieve their observations, and finally you check what came back. This page walks through
those steps, then through credentials, caching,
provenance and maps.

## What you get back

A **product** names a variable, a statistic and a time step. `discharge_daily_mean` is the mean
discharge over a day, while `stage_instantaneous` is a stage reading at a given moment. The
current supported variables are discharge, stage and water temperature.

A **series** is one product at one station of one provider. Retrieval returns a Polars frame with
exactly these columns, even when it is empty:

| Column | Meaning |
|---|---|
| `time` | Source-native, naive wall-clock timestamp |
| `time_zone` | Source-established IANA time zone, fixed offset, or `unknown` |
| `station_id` | String identifier within the result's provider |
| `product_id` | Canonical product identifier |
| `value` | Float value in the product's canonical unit, or a published null |

Read `time` together with `time_zone`. RivRetrieve keeps the agency's own timestamps instead of
converting everything to UTC, and `unknown` is not a missing value. It simply records that the
agency does not state the time zone. You will see it in three places: the time zone of a
timestamp, the time step of a product, and whether a station has data for a product.

Units are harmonised: discharge uses m³/s, stage uses metres and water temperature uses degrees
Celsius. What is not harmonised is the measurement itself. Equal units do not establish equal day
definitions, stage datums, or scientific comparability. Importantly, RivRetrieve does not
reconstruct quality flags, infer source judgements, or compute an unpublished product from another
frequency.

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

`as_frame` turns the selection into a table with one row per series and these columns:

| Group | Columns |
|---|---|
| Identity | `provider_id`, `station_id`, `product_id` |
| Position | `latitude`, `longitude`, `crs` (`unknown` where the agency states none) |
| What the product is | `observed_property`, `frequency`, `statistic`, `period_type`, `period_anchor`, `unit`, `native_id` |
| What the catalogue knows | `availability`, `availability_reason`, `published_record_start_date`, `published_record_end_date`, `last_catalogue_check` |

`native_id` is the agency's own code for that product. USGS names daily mean discharge
`00060:00003`, where `00060` is discharge and `00003` is the daily mean; France names it `QmnJ`.

`find` accepts one identifier per filter. `pick` narrows an existing selection and
also accepts sequences. It never adds series. Unknown identifiers raise rather than
triggering approximate matching. A valid identifier with no station offering that product
produces an empty selection with an `empty_reason`.

What the catalogue does and does not tell you:

- You can select a station whose availability is `unknown`.
- `available` means the agency listed data for that station, not that today's request will return
  any.
- Record start and end dates come from the agency. They do not mean the record is complete, and
  they do not stop you requesting other dates.
- Entries were captured on different dates, so the catalogue is not a single snapshot.

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
returns that frame and `to_pandas()` converts it to a pandas dataframe. Product metadata
in the selection states units and temporal properties.

### Time windows

`start` and `end` are read on the source's own clock, and both ends are included. Give them as ISO
date strings (`"2025-01-01"`), ISO datetime strings without a zone (`"2025-01-01T06:00"`), or naive
`datetime` objects. A `date` object, or any value that carries a time zone, raises rather than being
converted. `start` is required, even though the signature shows a default of `None`.

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

Two providers ask for them today:

| Provider | Variables | How to get them |
|---|---|---|
| `no_nve` (Norway) | `NVE_API_KEY` | A free key, issued on the spot at [hydapi.nve.no](https://hydapi.nve.no/Users) |
| `br_ana` (Brazil) | `ANA_IDENTIFICADOR`, `ANA_SENHA` | Granted on request by ANA; see [hidroweb/acesso-api](https://www.snirh.gov.br/hidroweb/acesso-api) for where to write |

Set them in your shell or in a `.env` file beside your project, then check that RivRetrieve sees
them:

```bash
export NVE_API_KEY="your-key"
```

```python
rr.providers()  # the access column reads "open", "ready", or "missing <variable names>"
```

`providers()` reports credential variable names and an access indicator. It does not
report observation capability. `ready` means required values are present, not that a
source accepted them. Consult the generated [software declarations](reference.md) for
provider kinds.

Set supplied values in the process environment or a `.env` file in the working directory.
The environment takes precedence. A blank environment value shadows the file and counts
as missing. [.env.example](../.env.example) lists names without usable secrets.
Do not commit credential files or put values into scripts, screenshots or issue reports.
How to obtain credentials from each agency is covered in more detail by the provider pages.

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

Coverage records that RivRetrieve asked the source for a window and got an answer. It does not
promise that every observation you expect is there:

- an answer with no rows still counts as coverage;
- refreshing can leave you with fewer rows than before, or none;
- a failed request adds no coverage.

RivRetrieve never decides that what it holds has gone stale. It records when each interval was
retrieved, in the provenance, and leaves that judgement to you.

Some agencies publish their record as one large file instead of answering station by station.
Today that is Canada (`ca_eccc`) and Poland (`pl_imgw`). RivRetrieve reads those from a compiled
store on your own disk. Without that store, retrieval returns an empty result and an issue: it
never starts a country-sized download on its own. `download(provider)` is how you consent to one,
and it can take considerable bandwidth and disk space.

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

Provenance answers "where did this come from". It always names the provider, the window as
RivRetrieve understood it, and the addresses it called. Depending on the provider, it can also
carry the catalogue's own evidence, the licence and citation the agency states, the queries put to
a bulk store, the intervals served from cache, and the identity of a bulk file. Not every field is
filled for every request, so read what is there rather than assuming. RivRetrieve records the
agency's terms. Importantly, it does not interpret them or decide whether you may redistribute
the data.

It is not a full audit of what happened to the values. A result does not necessarily record which
version of RivRetrieve produced it, or the factor used to convert units, and a unit conversion
raises no issue of its own. See [architecture](architecture.md) and the provider's configuration
for the conversion actually applied.

```python
result = rr.fetch(selection, start="2025-01-01", end="2025-12-31", receipts=True)
for entry in result.receipts.entries:
    print(entry.authorship.value, entry.origin)
    print(len(entry.content))
```

Receipts are the bytes themselves, kept only when you ask for them. They are raw material for
checking a value, not a quality assessment. Without `receipts=True` the container is there but
empty. Each entry says who wrote it:

- `publisher_payload` is what the agency sent, exactly as it reached the parser. For an archive,
  that can be one extracted member.
- `store_excerpt` is written by RivRetrieve, not the agency: Parquet rows read from a bulk store,
  with the query, path, format version and source vintage where they apply. It does not
  reconstruct the agency's original file.

A receipt can hold rows that the requested window later removed, and bulk queries are padded, so
its row count need not match `result.data`. Check the authorship before you use one to audit a
value. See [catalogue evidence](catalogue-evidence.md) for the separate record of where catalogue
facts came from, carried by selections and provenance.

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
