# USGS series discovery

USGS Water Data API v1 supplies daily discharge mean; daily stage mean, maximum
and minimum; and continuous discharge and stage. RivRetrieve keeps the public
provider name `usgs_nwis`. Observation retrieval uses only the modern service.

## Inspect a series before fetching

```python
import rivretrieve as rr

selection = rr.find(
    provider="usgs_nwis",
    station="02196000",
    quantity="discharge",
    frequency="daily",
    statistic="mean",
)
print(rr.series(selection))

chosen = rr.pick(selection, variant="4d186669708e4dc18f84d271efb953a1")
result = rr.fetch(chosen, start="2000-01-01", end="2000-01-07", cache="bypass")
```

`find` and `series` work offline. The dated catalogue contains both publisher IDs
at this station, including the sibling whose metadata ends in September 2005.
Picking an ID requests only that series. Without a pick, retrieval retains all
matching intent, including identities not yet in the catalogue. Equal values do
not make two source series the same.

Variants are opaque metadata `id` values, joined to observation `time_series_id`.
Descriptions preserve source strings exactly; an empty string is different from
null. These example descriptions are null. Neither old numeric method IDs nor
legacy catalogue `ts_id` values are aliases for modern IDs.

## Unknown statistics remain unknown

Some continuous records publish a null statistic and computation `Unknown`.
Their quantity and units can still support numeric observations:

```python
broad = rr.find(provider="usgs_nwis", station="02246518", quantity="discharge")
print(rr.series(broad))

precise = rr.find(
    provider="usgs_nwis",
    station="02246518",
    quantity="discharge",
    statistic="instantaneous",
)
```

`broad` includes the continuous series with unknown statistic, as well as daily
series. `precise` does not match that unknown fact. Sparse or frequent readings
do not establish a statistic. The six recorded cases are discharge at `02246518`,
`05414213`, `06129000`, `09423560`, and stage at `03291585`, `09429070`.

## Catalogue scope and coverage

The September 22, 2026 metadata snapshot retains the established 26,258 stream
station scope from the 50 states plus DC. It includes discontinued records.
Native agency prefixes are retained; they are not always `USGS`.

The [full-baseline audit](../research/usgs-modern-coverage/REPORT.md) compared
57,961 previously supported station/product pairs: 57,950 metadata matches,
five metadata gaps, and six continuous records with unknown precise statistic.
The owner approved modern-only service with these limits on
[September 22](https://github.com/RivRetrieve/RivRetrieve/issues/331#issuecomment-5778571205).
The historical audit report remains unchanged.

The five metadata gaps are:

| Station | Product |
| --- | --- |
| `04208504` | continuous stage |
| `09385701` | daily mean discharge |
| `10079500` | continuous discharge |
| `13297380` | continuous discharge |
| `13297380` | continuous stage |

These products have no executable series in this snapshot. Bounded checks found
empty answers from both modern and legacy services; they do not prove that all
historical windows are empty. No station identity was entirely missing.
There is no legacy fallback. Catalogue ranges, finite observation answers and
complete historical availability are different claims.

## Source representation and service limits

- Daily observations retain date-only labels and an unknown day definition/time
  zone. Metadata UTC range endpoints do not define their physical day support.
- Continuous observations retain their published offsets, including UTC labels.
  Request timestamps refer to that source-label axis, not a guessed local zone.
- Values retain present nulls. Empty windows and failed requests remain distinct.
  Receipts retain source terms such as `Approved`, `Provisional`, `ESTIMATED`
  and `DISCONTINUED` without translating them into quality judgments.
- Retrieval exhausts cursor pages. Continuous requests are split into bounded
  windows within the demonstrated 1,100-day envelope limit. Pagination/access
  failures prevent claims of complete coverage while independent results survive.
- `USGS_API_KEY` is optional. Composition sends a supplied key only to the USGS
  API origin in `X-Api-Key`. No key is needed for the recorded modest requests;
  rate limits depend on source policy. Authentication/rate-limit errors are
  failures, not missing observations.
- Legacy USGS caches and bundles are refused explicitly, without deleting files
  or reinterpreting their identities. Re-fetch or re-export modern selections.
  `clear_cache` remains the explicit destructive action.

The recordings in the private [source archive](maintenance/evidence.md) include all six routes,
historical daily and continuous samples, an ended empty series, present nulls,
and an explicit v1 cursor chain. These finite samples do not prove historical
parity. USGS schedules WaterServices retirement for February 22, 2027, with
delays beginning November 16, 2026; this implementation does not depend on it.
