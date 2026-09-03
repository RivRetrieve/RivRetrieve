# no_nve Provider Port Notes

These notes capture evidence and context from the `no_nve` port of the NVE HydAPI provider onto the
shared observation engine. They are not user documentation and not a new architecture contract;
promote only shared harness commitments to [ADRs](../adr/).

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
| Stop convention | Inclusive on the instant axis | `.../2023-03-27` returned three daily values ending `2023-03-26T11:00:00Z`; `.../2023-03-27T23:59:59Z` returned four, ending `2023-03-27T11:00:00Z` |

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
`method` per series rather than per parameter: station `103.3.0` publishes water temperature at
resolutions 60 and 1440 with `method: "Instantaneous"`, so the check is not decorative.

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
11:00Z that day, while an instant end includes both endpoints. No provider-owned window arithmetic,
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

The maintainer capture script is the composition root that reads the key:

```bash
uv run python scripts/capture_no_nve_recordings.py [ENV_FILE]
```

`ENV_FILE` defaults to `.env` beside the repository and is consulted only when `NVE_API_KEY` is absent
from the environment. The script plans the same padded window the driver plans, calls the provider's
own fetch stage through `AuthenticatedTransport(HttpClient(), …)`, and writes each interaction with
`RecordingEnvelope.from_transport`, so a recorded request is by construction the request the port
issues.

Committed evidence, all captured on 2026-09-03: station `1.200.0` (Lierelv) for all nine series over
`2025-07-08T00:00:00Z/2025-07-14T00:00:00Z`, the padded fetch window for the closed request window
2025-07-10 to 2025-07-12; station `12.210.0` for the missing water-temperature daily series; and
station `1.200.0` stage daily over an 1900 window with no observations.

## Packaged catalogue status

Unchanged by this port. `no_nve` is withheld from certified catalogue generation pending the
credentialed native acquisition owned by
[issue 90](https://github.com/RivRetrieve/RivRetrieve/issues/90), so the packaged catalogue emits
empty product, station, and station-product tables and the provider stays publicly unselectable. The
adapter is nevertheless complete and proven; `rr.find(provider="no_nve", …)` returns an empty
selection and `rr.fetch` reports the reason before any network access. See
[`../catalogue-provenance.md`](../catalogue-provenance.md) for the maintenance command and the
certification boundary.

## Engine friction

None. The source is expressed entirely through existing engine vocabulary: one existing window
granularity, the existing credential transport, and the existing issue and provenance carriers. No
new granularity, provider kind, or escape hatch was needed.

## Retired implementation

`reference/legacy_observations/no_nve/` was deleted once the recorded proofs passed. Its observation
payloads were partly invented and grounded nothing; the retired code converted daily timestamps by
string-slicing a local date and is not an oracle for this port.
