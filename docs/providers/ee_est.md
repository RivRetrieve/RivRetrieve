# Estonia: Keskkonnaagentuur

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `ee_est` |
| Country | Estonia |
| Published by | Estonian Environment Agency (*Keskkonnaagentuur*) |
| Read from | EstModel REST API (`estmodel.envir.ee`) and Keskkonnaandmed PostgREST service (`keskkonnaandmed.envir.ee`) |
| Quantities | Discharge, stage, water temperature |
| Stations in the catalogue | 60 inland river gauges. Availability depends on station, quantity, series, and period |
| Station metadata | Station name, water-body name, and catchment drainage area. See [Fields by provider](../station-metadata.md#fields-by-provider) |
| Credentials | None |
| Licence stated by Keskkonnaagentuur | Creative Commons Attribution 4.0 International (CC BY 4.0); statutory citation required under Section 13(4) of the Environmental Monitoring Act (*Keskkonnaseire seadus*) |
| Agency documentation | [Keskkonnaportaal open data](https://keskkonnaportaal.ee/et/avaandmed), [Hydrological monitoring dataset](https://keskkonnaportaal.ee/et/avaandmed/hudroloogilise-seire-andmestik), [EstModel API](https://estmodel.envir.ee/), [Keskkonnaagentuur citation guide](https://keskkonnaagentuur.ee/asutus-uudised-ja-kontakt/organisatsioon/visuaalne-visiitkaart-viitamine) |

Retrieve one week of daily mean discharge at station `SJA8821000`, `Ahja HJ` on
`Ahja jõgi`:

```python
import rivretrieve as rr

selection = rr.find(
    provider="ee_est",
    station="SJA8821000",
    quantity="discharge",
    frequency="P1D",
    statistic="mean",
)

result = rr.fetch(selection, start="2026-01-01", end="2026-01-07", cache="bypass")

preview = result.data.select("time", "time_zone", "value", "unit").head(3)
print(preview.write_csv(), end="")

print(result.data.height)
print(result.issues)
```

Output:

```text
time,time_zone,value,unit
2026-01-01T00:00:00.000000,unknown,5.5,m3/s
2026-01-02T00:00:00.000000,unknown,5.51,m3/s
2026-01-03T00:00:00.000000,unknown,5.51,m3/s
7
()
```

The request returned seven published daily means in m³/s from EstModel's
`Q` `MEAN` series. The preview shows the first three days. `time_zone` is
`unknown` because EstModel daily rows carry calendar dates (`YYYY-MM-DD`) without
a UTC offset; hourly series from `f_hydroseire` carry fixed `+00:00` UTC
timestamps instead. See [Time, missing values, and data status](#time-missing-values-and-data-status).
The empty tuple `()` means this retrieval reported no transport or structural
issues. Cite *Keskkonnaagentuur* when reusing the data; see
[Terms and citation](#terms-and-citation).

`cache="bypass"`, the default for live `rr.fetch` calls, requests the publisher
API directly without reading or writing a local cache. Passing `cache="reuse"`
stores downloaded observations locally so subsequent requests within cached
periods run offline. Passing `cache="refresh"` re-downloads cached windows to
pick up upstream quality-control revisions. This output was checked live on
2026-11-23. Current-year operational values can change during annual quality
control. See [Usage](../usage.md) for selection options and result handling.

## Who measures, and who publishes

The Estonian Environment Agency (*Keskkonnaagentuur*) operates Estonia's
national hydrological monitoring network and publishes both official open-data
APIs exposed under `ee_est`:

- **Daily series (`estmodel.envir.ee`):** EstModel REST API serving historical
  and current-year daily means, maxima, and minima for river discharge, stage,
  and water temperature.
- **Hourly series (`keskkonnaandmed.envir.ee`):** Keskkonnaandmed PostgREST
  view `f_hydroseire` serving 1-hour hydrological telemetry from 2012 onward.

No API key or account is required. RivRetrieve searches the packaged station and
series catalogue offline; `rr.fetch` then queries EstModel or `f_hydroseire` over
HTTPS. Station identifiers are national Environmental Registry
(*Keskkonnaregister*) codes kept as strings, `54` starting with `SJA*` (such as
`"SJA8821000"`) and `6` starting with `SJB*`.

The packaged `ee_est` catalogue retains `60` inland flowing-water hydrological
gauges (`58` rivers classified *Jõgi*, `1` stream *Oja*, and `1` main ditch
*Peakraav*):

- **Active vs. EstModel-only river gauges:** `56` stations publish both daily
  EstModel series and hourly `f_hydroseire` series; `4` closed `SJB*` gauges
  (`SJB4152000` Türi-Alliku, `SJB4433000` Keila jõgi: Ardi, `SJB4487000` Mustjõgi:
  Tulijärve, and `SJB4488000` Linnussaare) publish daily EstModel records only
  and have no hourly `f_hydroseire` series.
- **Excluded standing-water and coastal gauges:** Five inland lake and reservoir
  hydrological gauges (`SJA3914000`, `SJA4875000`, `SJA5000000`, `SJA5411000`,
  `SJA8843000`) and `15` coastal Baltic sea-level stations (*rannikumerejaamad*)
  are excluded so river cohorts stay separated from lakes and tide gauges.
- **Excluded water-chemistry, validation, and model routes:** `60`
  hydrochemical sampling stations, EstModel manual check gaugings
  (`type=VALIDATION`), water velocity (`V`), modeled catchment load `/estimates`,
  and operational hydrological forecast outputs (*KAIA SWAT*) are excluded.

## What you can retrieve

EstModel publishes nine daily series types (`Q`, `H`, `T` across `MEAN`,
`MAXIMUM`, `MINIMUM`), and Keskkonnaandmed `f_hydroseire` publishes nine hourly
series types (`Äravool`, `WL`, `WT` across `avg`, `max`, `min`):

| Quantity filter | Source field / `variant` | Frequency | Statistic | Source unit | Returned unit |
|---|---|---|---|---|---|
| `discharge` | `Q:MEAN` | `P1D` | Mean | m³/s | m³/s |
| `discharge` | `Q:MAXIMUM` | `P1D` | Maximum | m³/s | m³/s |
| `discharge` | `Q:MINIMUM` | `P1D` | Minimum | m³/s | m³/s |
| `discharge` | `Äravool avg` | `PT1H` | Mean | m³/s | m³/s |
| `discharge` | `Äravool max` | `PT1H` | Maximum | m³/s | m³/s |
| `discharge` | `Äravool min` | `PT1H` | Minimum | m³/s | m³/s |
| `stage` | `H:MEAN` | `P1D` | Mean | m | m |
| `stage` | `H:MAXIMUM` | `P1D` | Maximum | m | m |
| `stage` | `H:MINIMUM` | `P1D` | Minimum | m | m |
| `stage` | `WL avg` | `PT1H` | Mean | cm | m |
| `stage` | `WL max` | `PT1H` | Maximum | cm | m |
| `stage` | `WL min` | `PT1H` | Minimum | cm | m |
| `temperature` | `T:MEAN` | `P1D` | Mean | °C | °C |
| `temperature` | `T:MAXIMUM` | `P1D` | Maximum | °C | °C |
| `temperature` | `T:MINIMUM` | `P1D` | Minimum | °C | °C |
| `temperature` | `WT avg` | `PT1H` | Mean | °C | °C |
| `temperature` | `WT max` | `PT1H` | Maximum | °C | °C |
| `temperature` | `WT min` | `PT1H` | Minimum | °C | °C |

In `rr.series(...)`, each `published_id` combines the station or site key with
the native series code shown above (for example `"SJA8821000:Q:MEAN"` on daily
EstModel series and `"41061:Äravool avg"` on hourly `f_hydroseire` series).
RivRetrieve retrieves published daily and hourly aggregates directly; it does
not compute daily summaries from hourly data.

RivRetrieve multiplies hourly stage (`WL avg`, `WL max`, `WL min`) by `0.01` to
convert centimetres (`cm`) to metres (`m`) and preserves `"cm"` in
`source_unit`. Daily stage (`H` in `m`), discharge (`m3/s`), and water
temperature (`degC`) keep their source values without numerical scaling.

The packaged catalogue accounts for `1,032` active station-series pairs across
the `60` river stations (`48` unsupported pairs are omitted):

- `SJA5432000` (*Kuningaküla*) is a water-level and water-temperature gauge
  with no discharge rating curve, so it publishes stage and water temperature
  only (`12` series).
- `SJB4433000` (*Keila jõgi: Ardi*, EstModel-only) lacks stage (`6` EstModel
  series for discharge and operational 2026 water temperature).
- `SJB4488000` (*Linnussaare*, EstModel-only) lacks water temperature (`6`
  EstModel series for discharge and stage).
- `SJB4152000` and `SJB4487000` publish all `9` EstModel daily series without
  hourly `f_hydroseire` records.

A listed series need not span every requested year, and daily `MEAN` series
often extend further back in time than `MAXIMUM` or `MINIMUM`. Inspect available
series offline and pick a specific `series_id` when needed:

```python
import polars as pl

all_discharge = rr.find(provider="ee_est", station="SJA8821000", quantity="discharge")
candidates = rr.series(all_discharge)
metadata = rr.metadata(all_discharge)

hourly_mean_id = candidates.filter(
    pl.col("published_id").str.ends_with(":Äravool avg")
)["series_id"].item()
hourly_mean = rr.pick(all_discharge, series_id=hourly_mean_id)
```

## Stage references, coordinates, and metadata

All six stage series set `vertical_reference="gauge_zero"`. Genuine zero flows
(`0.0 m3/s`), zero stages (`0.0 m`), and negative gauge-zero stages (for example
at `SJA4456000` *Räpina*) are preserved without clamping. Because neither
EstModel nor Keskkonnaandmed `f_seirejaamad` publishes gauge-zero elevations or
datum histories (`f_seirejaamad.merepinnast` is null for all `60` stations),
`vertical_datum` remains unknown on every stage series. Do not add an arbitrary
elevation value to gauge-zero stage readings to estimate water-surface elevation
above sea level.

Station metadata (`rr.metadata(selection)`) maps each field from a single
authoritative source column:

- `nimi` (from `f_seirejaamad`) as `station_name` (`60/60`)
- `veekogu_nimi` (from `f_seirejaamad`) as `water_body_name` (`60/60`)
- `area` (from EstModel) as `drainage_area` in `km2` (`60/60`)
- `elevation` is unpopulated (`null` / `no_metadata`) because `merepinnast` is
  null across the river cohort

Horizontal coordinates (`latitude` and `longitude`) are deterministically
re-projected to `WGS 84` (`EPSG:4326`) from the published *L-EST97* (`EPSG:3301`)
coordinates `(kesk_x, kesk_y)` in `f_seirejaamad`.

## Record depth, operational lag, and API limits

EstModel daily histories reach back to the nineteenth century on long-running
gauges (`1867-04-01` stage and `1922-01-01` discharge at `SJA7331000` Tartu;
`1902-09-22` discharge at `SJA2718000` Vasknarva) and extend into current-year
operational measurements. Keskkonnaandmed `f_hydroseire` hourly records begin
on `2012-01-01T00:00:00Z` and update operationally with an observed lag of
roughly three to four days behind the current date.

- **EstModel chunking and pacing:** Requests query whole calendar years via
  `start-year` and `end-year` in spans of up to `25` calendar years. EstModel is
  fronted by Cloudflare rate protection that returns HTTP `429 Too Many
  Requests` on rapid bursts; RivRetrieve applies polite sequential spacing and
  handles retries safely, and `cache="reuse"` avoids repeated multi-decade calls.
- **`f_hydroseire` row ceiling:** Keskkonnaandmed enforces a `20,000`-row cap
  per response and discourages unindexed `limit`/`offset` paging. RivRetrieve
  splits hourly requests into `365`-day spans (at most `8,784` hourly rows per
  series) and raises a structural issue instead of truncating results if an
  upstream response ever reaches `20,000` rows.

## Time, missing values, and data status

The two APIs follow distinct timestamp conventions:

- **EstModel daily series:** Returned timestamps carry calendar dates at
  `00:00:00` with `time_zone="unknown"`, `temporal_support="interval"`, and
  `day_definition="unknown"`. `rr.fetch` clips daily queries by calendar date
  (`YYYY-MM-DD`), and `rr.to_utc()` refuses `unknown` time zones rather than
  guessing historical EET/EEST local civil day boundaries. Unmeasured dates are
  omitted from EstModel responses.
- **Keskkonnaandmed `f_hydroseire` hourly series:** Upstream publishes
  `timeline_ts_utc` alongside daylight-saving-folded `timeline_ts_local`.
  RivRetrieve queries and parses strictly from `timeline_ts_utc` with
  `time_zone="+00:00"` and `temporal_support="interval"`. Missing hourly
  measurements inside recorded periods appear explicitly as `value=null` rows
  (`"vaartus": null`), whereas unrecorded periods return no rows.

EstModel includes a per-row `qualityFlag` field (`UNCHECKED`, `BELOW_LOQ`,
`OUTLIER` in the EstModel OpenAPI schema). Verified historical calendar years
(`<= 2025`, plus observed 2026 water temperature rows) carry `null`, whereas
current-year operational discharge and stage rows carry `"UNCHECKED"` until
annual hydrological review. RivRetrieve returns all published observations
without filtering by `qualityFlag` and preserves the raw flag under schema
`ee_est.estmodel` (observation scope):

```python
result = rr.fetch(selection, start="2026-01-01", end="2026-01-07")

# Field catalogue
print(rr.annotations(result).select("schema", "name", "dtype").rows())
# [('ee_est.estmodel', 'qualityFlag', 'String')]

# Append to the canonical frame
annotated = result.to_polars(annotations=True)
print(annotated.select("time", "value", "qualityFlag").head(3).rows())
```

Output:

```text
[(datetime.datetime(2026, 1, 1, 0, 0), 5.5, 'UNCHECKED'), (datetime.datetime(2026, 1, 2, 0, 0), 5.51, 'UNCHECKED'), (datetime.datetime(2026, 1, 3, 0, 0), 5.51, 'UNCHECKED')]
```

Both annotation outputs were checked live on 2026-11-23.

## Terms and citation

*Keskkonnaagentuur* publishes Estonia's hydrological High-Value Datasets under
the [Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/)
licence. Under Section 13(4) of the Estonian Environmental Monitoring Act
(*Keskkonnaseire seadus* § 13(4)) and *Keskkonnaportaal* open-data guidance,
reusers must cite *Keskkonnaagentuur* as the data source:

> Estonian Environment Agency (Keskkonnaagentuur)

Both `rr.describe("ee_est")` and `result.provenance` expose `license="CC BY 4.0"`
and `citation="Estonian Environment Agency (Keskkonnaagentuur)"`. For scientific
reproducibility, also record the station code (`SJA*`/`SJB*`), native series
identifier, requested period, and retrieval date.

## Sources

Publisher portals, OpenAPI descriptors, and legislation checked on 2026-11-23:

- [Keskkonnaportaal open data (`keskkonnaportaal.ee/et/avaandmed`)](https://keskkonnaportaal.ee/et/avaandmed)
  and [Hydrological monitoring dataset](https://keskkonnaportaal.ee/et/avaandmed/hudroloogilise-seire-andmestik):
  `CC BY 4.0` licensing, *Keskkonnaagentuur* attribution, hydrological network
  descriptions, and `f_hydroseire` row-cap documentation.
- [Keskkonnaagentuur visual card and citation guide](https://keskkonnaagentuur.ee/asutus-uudised-ja-kontakt/organisatsioon/visuaalne-visiitkaart-viitamine):
  statutory source citation obligation under *Keskkonnaseire seadus* § 13(4).
- [EstModel REST API (`estmodel.envir.ee`)](https://estmodel.envir.ee/) and
  Swagger `1.0.0` specification: `/stations`, `/countries/EE/stations`,
  `/stations/{code}/measurements` (`Q`, `H`, `T` across `MEAN`, `MAXIMUM`,
  `MINIMUM`), `qualityFlag` enum, and `area` (`km²`).
- [Keskkonnaandmed PostgREST OpenAPI `12.0.1` (`keskkonnaandmed.envir.ee`)](https://keskkonnaandmed.envir.ee/):
  `Accept-Profile: apijahiala`, station registry `f_seirejaamad` (`kkr_kood`,
  `kood`, `L-EST97` `EPSG:3301` coordinates, `veekogu_tyyp_selg`, `nimi`,
  `veekogu_nimi`, `merepinnast`), and hourly observations `f_hydroseire`
  (`timeline_ts_utc`, `vaartus`, `Äravool`/`WL`/`WT`).
- [Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/):
  attribution and reuse conditions.

The station count (`60`) and series count (`1,032`) describe the packaged
catalogue snapshot (2026-11-23). Live example output was checked on 2026-11-23.
A successful example retrieval does not guarantee continuous coverage across
other dates, quantities, or stations. The
[private verification archive](https://github.com/RivRetrieve/verification-evidence#readme)
retains the captured inputs, external GRDC-Caravan benchmark comparison, and
exact verification commands.
