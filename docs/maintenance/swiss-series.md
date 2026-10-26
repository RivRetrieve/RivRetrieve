# Swiss observation series definitions

`ch_foen.official_series.source_series` resolves official API coordinates and
already established unit bindings. Catalogue generation uses this entry point;
observation parsing can use it without fetching data or loading configuration.
The provider uses these definitions for official discovery and retrieval.

Identity uses the station string, route, parameter and raw `tsName`. Keep leading
zeros, unsuffixed and `_01` names, and archive/recent publications separate. The
recent feed has no raw series name. Distinct native units produce separate physical
fact segments, not new series identities. Changed knowledge does not rename a
series. A catalogue association is a witness, not a complete inventory or record
boundary, including when its observed values are all null.

## Physical facts

Archive unit bindings come from the published unit fields. Recent bindings come
from station-page parameter labels; missing labels remain unknown. Shared admission
converts native scales dimensionally. Above-sea-level labels establish a reference,
not a named per-series datum. The historical 2282 archive Q/W units are m³/s and
metres above sea level; its recent labels are independently bound. No 890 m offset
or network-wide unit assumption is applied.

Ordinary ten-minute/hourly archive products are interval means. Daily, monthly
and yearly products describe calendar windows beginning at midnight in fixed UTC+1.
Minimum/maximum statistics describe extrema of short-term measurements, not daily
means. Their `temporal_support` describes the aggregate window; the underlying
measurement's averaging duration and the time of the extreme remain unknown.
No averaging algorithm or missing-input threshold is assumed.

Timestamp serialization remains UTC. `day_definition="UTC+01:00"` describes the
aggregation calendar, and `timestamp_anchor="start"` describes the aggregate label.
The definitions keep source-timestamp clipping, not calendar-date clipping of a
UTC label. Calendar periods are not fixed 30-day months or 365-day years:

| Aggregate | UTC interval (start included, end excluded) |
| --- | --- |
| February 2025 | 2025-01-31 23:00 to 2025-02-28 23:00 |
| February 2024 | 2024-01-31 23:00 to 2024-02-29 23:00 |
| Year 2024 | 2023-12-31 23:00 to 2024-12-31 23:00 |
| 1 July 2025 | 2025-06-30 23:00 to 2025-07-01 23:00 |

Shared request planning, subdivision, clipping and cache handling preserve these
calendar boundaries.
Do not classify February's label as January from its UTC date or relabel its clock
value as UTC+1.

Recent timestamps mark measurement end. Exact per-series averaging durations remain
unknown; cadence does not establish them. At station 7008, `MonatsMittel_Orbe_flex`
in `data_1day_mean` retains unknown statistic, frequency, support and anchor. Neither
its route, name nor cadence supplies those facts. Its units and UTC timestamps can
still be preserved. Optional unknowns do not prevent admission, but cannot satisfy
filters requiring established facts.

## Parser handoff

Keep null values, zero, absent rows and failed requests distinct. These definitions
do not parse or replace observation values. Preserve archive `releaseState` and
recent `releaseStatus` under their own field names, including original nulls.
`RELEASE_STATUS_MEANINGS` records publisher vocabulary separately: null and 0 mean
raw, 1 unreleased/prechecked, 2 released/checked and 3 released/definitive. Status 3
includes corrections from status 2 and definitive stage–discharge relations. This
is not a quality ranking or filtering policy. The unresolved word `ersetzt` does
not establish replacement lineage.

Catalogue temporal facts require `source.product.temporal_meaning` in the selected
provenance. The private archive owns the supporting originals and reviewed source
checks. Synthetic tests protect the definitions' behavior; genuine-input checks
and disclosure review are required before publishing rebuilt catalogue products.
