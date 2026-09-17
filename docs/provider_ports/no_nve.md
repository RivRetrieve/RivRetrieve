# no_nve Provider Port Notes

These notes capture evidence and context from the `no_nve` port of the NVE HydAPI provider onto the
shared observation engine. They are not user documentation and not a new architecture contract.
See [Architecture](../architecture.md) for shared harness contracts.

## Source

`GET https://hydapi.nve.no/api/v1/Observations` with query parameters `StationId`, `Parameter`,
`ResolutionTime` and `ReferenceTime`. Documentation:
[https://hydapi.nve.no/UserDocumentation/](https://hydapi.nve.no/UserDocumentation/). The data is
published under the [Norwegian License for Open Government Data](https://data.norge.no/nlod/en).

One request carries one station, one parameter and one resolution. Two products never share a
parameter/resolution pair, so nothing is coalesced and no identical call is issued twice.

Observed source behaviour, verified against the live API on 2026-09-03:

| Question | Answer | Evidence |
| --- | --- | --- |
| Missing series | HTTP 404 with an RFC 7807 problem body | `no_nve_12.210.0_1003_1440_2025-07-08_2025-07-14.recording.json` |
| Existing series, no observation in window | HTTP 200, `observationCount: 0`, empty `observations` | `no_nve_1.200.0_1000_1440_1900-01-01_1900-01-07.recording.json` |
| ISO instants with a `Z` suffix in `ReferenceTime` | Accepted | every committed recording |
| Stop convention | Inclusive on the instant axis | `no_nve_1.200.0_1000_1440_2023-03-23_2023-03-27.recording.json` (end `2023-03-27T00:00:00Z`) holds four daily values ending `2023-03-26T11:00:00Z`; `no_nve_1.200.0_1000_1440_2023-03-23_2023-03-27-eod.recording.json` (end `2023-03-27T23:59:59.999999Z`) holds five, ending `2023-03-27T11:00:00Z` |
| Fractional-second end, the form a bare-date public request renders | Accepted | `no_nve_1.200.0_1000_1440_2025-07-08_2025-07-14-eod.recording.json`, end `2025-07-14T23:59:59.999999Z`, seven daily values ending `2025-07-14T11:00:00Z` |
| Null values | Published as JSON `null` with a quality code | the two 2023 stage recordings above: every value is `null` with `quality` 2 |

## Products

Nine products are claimed, one per parameter and resolution. Each is the canonical id from
[`../product_dictionary.md`](../product_dictionary.md); `water_temperature_hourly_mean` was added to
that dictionary by this port, because HydAPI publishes an hourly water-temperature series whose
`method` is `Mean` and no canonical entry existed.

| Product | `Parameter` | `ResolutionTime` | Published `method` | Published `unit` | Canonical unit | Semantics |
| --- | --- | --- | --- | --- | --- | --- |
| `discharge_daily_mean` | 1001 | 1440 | Mean | `m³/s` | `m3/s` | Daily, day definition unknown, label 11:00 |
| `discharge_hourly_mean` | 1001 | 60 | Mean | `m³/s` | `m3/s` | Hourly, interval definition unknown |
| `discharge_instantaneous` | 1001 | 0 | Instantaneous | `m³/s` | `m3/s` | Instant |
| `stage_daily_mean` | 1000 | 1440 | Mean | `m` | `m` | Daily, day definition unknown, label 11:00 |
| `stage_hourly_mean` | 1000 | 60 | Mean | `m` | `m` | Hourly, interval definition unknown |
| `stage_instantaneous` | 1000 | 0 | Instantaneous | `m` | `m` | Instant |
| `water_temperature_daily_mean` | 1003 | 1440 | Mean | `°C` | `degC` | Daily, day definition unknown, label 11:00 |
| `water_temperature_hourly_mean` | 1003 | 60 | Mean | `°C` | `degC` | Hourly, interval definition unknown |
| `water_temperature_instantaneous` | 1003 | 0 | Instantaneous | `°C` | `degC` | Instant |

No product is unclaimed. Every one of the nine carries a real recording and an independently authored
boundary probe.

`method` and `unit` are published per series and are checked by parse against the declared product
statistic and source unit; a mismatch fails loudly rather than being reconciled. HydAPI publishes
`method` per series rather than per parameter: `no_nve_103.3.0_1003_60_2025-07-08_2025-07-14.recording.json`
records station `103.3.0` publishing water temperature at resolution 60 with `method: "Instantaneous"`
(the active station list of 2026-09-03 says the same of its resolution 1440 series), so the check is
not decorative. The guard is deliberate: a request that includes such a series fails the whole result
rather than returning the other products with an issue. That is the doctrine (a module dies rather
than guess), and there is no per-provider isolation point. Catalogue availability is narrower:
the certified native-table build records whether the published parameter-resolution pair exists. It
does not reinterpret a method or unit contradiction as pair unavailability; the observation parser
retains authority over that separate response contract.

## Station catalogue acquisition

The certified station catalogue comes from one authorized campaign on 2026-09-04. It issued exactly
`Stations?Active=1` and `Stations?Active=0`. The complete response bytes are retained as repository audit
evidence outside the wheel. `Active=1` is the all-station mode. `Active=0` is the active-only mode: every
returned row is marked `Aktiv`, and every one is also present byte-semantically unchanged in the
all-station response. The two responses contained 4,902 and 1,893 rows, leaving 4,902 distinct station
identities with no within-response duplicates. These counts describe this capture. They are not acceptance
thresholds for a future refresh.

Materialization verifies both envelopes, their `itemCount`, every 98-field station object, every nested
`seriesList` and `resolutionList` member, raw byte identities, and the attested counts. Identical overlap is
collapsed. Rows are sorted by exact `stationId`. Each row uses the earliest retrieval instant of a response
that contained it. Any differing overlap, duplicate identity, malformed member, missing coordinate, or
unaccounted row refuses the materialization.

The public OpenAPI schema was captured separately and reviewed. It documents `latitude` and `longitude`
but no coordinate reference system for them. The canonical CRS therefore remains `unknown`; it is not
inferred from Norway or from the UTM zone-33 fields that the same station object also publishes.

HydAPI publishes `serieFrom` and `serieTo` per series version and `dataFromTime` and `dataToTime` per
resolution member. A station-product edge can have several such members. The source does not publish one
edge-level period, and choosing a minimum, maximum, or version would add RivRetrieve judgement. These
fields remain intact in the native table. Canonical `published_record_start_date` and
`published_record_end_date` therefore remain null rather than presenting an inferred coverage period.

## Time semantics

All timestamps are published in UTC, so every row carries `time_zone` `+00:00` and a naive wall-clock
`time` equal to the published label.

The documentation contradicts itself about the day definition:

> All the timestamps returned from the API are given in the timezone UTC-0 (Zulu-time). Time series
> with resolutiontime day, is timestamped with 11:00Z. The data for a day observation is calculted
> using "Norwegian normal time" UTC-1.

Norwegian normal time is Central European Time, which is UTC+1, not UTC-1. The source therefore does
not establish which 24 hours a daily value covers. The day definition stays `unknown` and the daily
label time is the published `11:00`. It is never inferred from the country, the coordinates, or the
retired implementation.

Hourly interval anchoring is not published either, so `IntervalDefinition("unknown")` is declared.

## Window declaration

`iso-instant` granularity, `iso-instant` rendering, inclusive stop. `ReferenceTime` is the rendered
start and stop joined with `/`. The inclusive stop is proven by the live probe recorded in the table
above, not assumed: a date-only end truncates to midnight and silently drops a daily value stamped
11:00Z that day, while an instant end includes both endpoints. A bare-date public request ends at
`23:59:59.999999`, which the renderer emits with microseconds; the source accepts that form, as the
end-of-day recording shows, so the whole public request shape is exercised. No provider-owned window arithmetic,
clipping, timezone conversion, unit conversion, retry loop, or result assembly exists; all of it stays
in the engine.

## Source judgement codes

`quality` and `correction` are HydAPI's own judgement codes. Parse never interprets them and never
drops a reading because of them. It surfaces one `info` issue per distinct code, carrying the code,
the number of readings that bear it, and the first and last source timestamps that do. A null `value`
is carried as a null reading.

## Credentials

HydAPI requires an `X-API-Key` request header. Provider code reads no environment variable, no `.env`
file, and no other file. At runtime the engine supplies the credential through
`AuthenticatedTransport` with a `CredentialHeader` scoped to `https://hydapi.nve.no`; the provider
issues a plain request and the transport applies the header below it. Recordings, receipts,
provenance, issues, and reprs therefore keep the header name and never a value.

## Capturing recordings

Recordings are made with the shared maintainer entry point, the composition root that reads the key
from `NVE_API_KEY` in the environment or, failing that, from a dotenv-style file:

```bash
uv run python -m rivretrieve._internal.record_observations --provider no_nve --station 1.200.0 \
    --product stage_daily_mean --start 2025-07-10T00:00:00 --end 2025-07-12T00:00:00 \
    --credential-header X-API-Key --credential-env NVE_API_KEY --credential-origin https://hydapi.nve.no \
    --env-file .env --out-dir tests/test_data --name no_nve_1.200.0_1000_1440_2025-07-08_2025-07-14
```

The tool drives the provider through `drive()` with the engine's own padding and window planning,
sends through `AuthenticatedTransport(HttpClient(), …)` wrapped in `RecordingTransport`, and writes
each exchange with `RecordingEnvelope.from_transport`, so a recorded request is by construction the
request the port issues for that public window. Recording names are
`no_nve_<station>_<parameter>_<resolution>_<fetch start date>_<fetch stop date>`. One invocation
per product produced the committed evidence; the two other recordings use station `12.210.0` with
`water_temperature_daily_mean` and the same window, and station `1.200.0` with `stage_daily_mean`
over `--start 1900-01-03T00:00:00 --end 1900-01-05T00:00:00`.

Committed evidence: station `1.200.0` (Lierelv) for all nine series over
`2025-07-08T00:00:00Z/2025-07-14T00:00:00Z`, the padded fetch window for the closed request window
2025-07-10 to 2025-07-12 (captured 2026-09-03); station `12.210.0` for the missing water-temperature
daily series (2026-09-03); station `1.200.0` stage daily over an 1900 window with no observations
(2026-09-03); the end-of-day stage daily window for the bare-date public request
`--start 2025-07-10 --end 2025-07-12` (2026-09-04); the two 2023 stop-convention stage daily windows
for `--start 2023-03-25T00:00:00 --end 2023-03-25T00:00:00` and `--start 2023-03-25 --end 2023-03-25`
(2026-09-04); and station `103.3.0` water temperature hourly over the July window (2026-09-04), whose
capture ends in the parse refusal the recording exists to prove.

## Packaged catalogue status

The packaged catalogue is certified from the committed complete station capture. It exposes NVE
stations, the nine declared products, and every station-product edge through public discovery. A
matching published `(parameter, resTime)` pair establishes catalogue availability. A complete
`seriesList` without that pair establishes unavailability.

Availability at this layer does not certify every observation response. HydAPI also publishes method
and unit on the selected series. The observation parser checks those values against the canonical
product and refuses a contradiction rather than relabelling the source response. Thus a pair-compatible
edge remains publicly selectable even when a later response supplies a method or unit that cannot be
parsed as that canonical product.

`rr.find(provider="no_nve", …)` returns matching certified edges. `rr.fetch` then requires the scoped
credential and applies the observation-path contract. See
[`../catalogue-provenance.md`](../catalogue-provenance.md) for catalogue evidence and maintenance.

## Engine friction

None. The source is expressed entirely through existing engine vocabulary: one existing window
granularity, the existing credential transport, and the existing issue and provenance carriers. No
new granularity, provider kind, or escape hatch was needed.

## Retired implementation

`reference/legacy_observations/no_nve/` was deleted once the recorded proofs passed. Its observation
payloads were partly invented and grounded nothing; the retired code converted daily timestamps by
string-slicing a local date and is not an oracle for this port.
