# Austria: eHYD

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `at_ehyd` |
| Country | Austria |
| Published by | Federal Ministry of Agriculture and Forestry, Climate and Environmental Protection, Regions and Water Management (BMLUK), Department I/3 Water Balance (HZB), with provincial hydrographic services |
| Read from | Official eHYD web services (`ehyd.gv.at`) |
| Quantities | Discharge, stage, water temperature |
| Stations in the catalogue | 746 river gauges (744 with selectable series). Availability depends on station, quantity, product and period |
| Station metadata | Station name, water-body name and drainage area. See [Fields by provider](../station-metadata.md#fields-by-provider) |
| Credentials | None |
| Licence stated by BMLUK | Creative Commons Attribution 4.0 (CC BY 4.0); source attribution required (`Datenquelle: ehyd.gv.at`) |
| Agency documentation | [eHYD portal](https://ehyd.gv.at/), [General guide](https://ehyd.gv.at/assets/documents/eHYD_Allgemein.pdf), [Current telemetry guide](https://ehyd.gv.at/assets/documents/Aktuelle_Daten.pdf) |

Retrieve one week of validated daily mean discharge at station `209486`,
Böheimkirchen on the Perschling:

```python
import rivretrieve as rr

selection = rr.find(
    provider="at_ehyd",
    station="209486",
    quantity="discharge",
    frequency="daily",
    statistic="mean",
)

result = rr.fetch(selection, start="2023-01-01", end="2023-01-07", cache="bypass")

preview = result.data.select("time", "time_zone", "value", "unit").head(3)
print(preview.write_csv(), end="")

print(result.data.height)
print(result.issues)
```

Output:

```text
time,time_zone,value,unit
2023-01-01T00:00:00.000000,unknown,0.112,m3/s
2023-01-02T00:00:00.000000,unknown,0.107,m3/s
2023-01-03T00:00:00.000000,unknown,0.109,m3/s
7
()
```

The request returned seven published daily means in m³/s from eHYD's validated
historical archive (`owf_abfl_tagesmittel`). The preview shows the first three
days. `time_zone` is `unknown` because the exported CSV files do not state a UTC
offset; see [Time and data status](#time-and-data-status). The empty tuple `()`
means this retrieval reported no transport, parsing, or gap-marker issues.
Attribution is still required when using the data; see
[Terms and citation](#terms-and-citation).

`cache="bypass"`, the default for live `rr.fetch` calls, requests eHYD directly
without reading or writing a local cache. Passing `cache="reuse"` stores the
station's downloaded archive series locally so later historical queries for the
same gauge and product reuse the cached series without downloading the full CSV
file again. This output was checked live on 2026-11-03. Published values can
change across hydrographic yearbook revisions. See [Usage](../usage.md) for
selection options and result handling.

## Who measures, and who publishes

Austria's Federal Ministry of Agriculture and Forestry, Climate and
Environmental Protection, Regions and Water Management (Bundesministerium für
Land- und Forstwirtschaft, Klima- und Umweltschutz, Regionen und
Wasserwirtschaft, BMLUK), Department I/3 Water Balance (*Wasserhaushalt*,
formerly the Hydrographic Central Office, HZB), publishes national hydrographic
data through [eHYD](https://ehyd.gv.at/). Measurements are collected and
validated in cooperation with the nine provincial hydrographic services
(*Hydrographische Landesdienste*), the waterway operator `viadonau` on the
Danube, and municipal water services. Appearance on eHYD does not mean that
BMLUK operates every station itself.

No API key or account is required. RivRetrieve searches the packaged station and
series catalogue offline; `rr.fetch` then requests data directly from eHYD's
public web services. Station identifiers are six-digit HZB numbers (`hzbnr`),
kept as strings such as `"209486"`.

The packaged `at_ehyd` catalogue covers flowing surface waters only: `746` river
gauges in `EPSG:4326`, of which `744` expose at least one selectable discharge,
stage, or water temperature series (`2` river gauges, `207480` and `230102`,
publish only sediment series). Standing-water lake gauges (*Seepegel*, `59`
stations in eHYD's surface-water layer on lakes such as Bodensee, Neusiedler
See, and Attersee), subsurface spring gauges (*Quellen*), groundwater wells, and
precipitation or evaporation stations are excluded. Validated daily suspended
sediment load (*Schwebstoff-Tagesfracht*) and daily bedload transport
(*Geschiebe-Tagesfracht*) published at a subset of river gauges are also outside
RivRetrieve's current quantity scope.

## What you can retrieve

eHYD publishes river observations through two separate streams:

1. **Validated historical archive (*Geprüfte Daten*, `owf_*`):** Quality-checked
   CSV series reviewed for Austria's Hydrographic Yearbook (*Hydrographisches
   Jahrbuch*).
2. **Operational telemetry (*Pegel Aktuell*, `pegel_bgis_*` and
   `pegel_longterm_*`):** Unchecked near-real-time sub-hourly series
   (`pegel_bgis_*`) and current-year daily comparison series
   (`pegel_longterm_*`) published at telemetered gauges.

| Quantity filter | Product (`product_id`) | Stream | Frequency | Statistic | Source unit | Returned unit |
|---|---|---|---|---|---|---|
| `discharge` | `owf_abfl_tagesmittel` | Validated archive | Daily | Mean | m³/s | m³/s (`m3/s`) |
| `discharge` | `owf_abfl_monatsminima` | Validated archive | Monthly | Min | m³/s | m³/s (`m3/s`) |
| `discharge` | `owf_abfl_monatsmaxima` | Validated archive | Monthly | Max | m³/s | m³/s (`m3/s`) |
| `stage` | `owf_wasserst_tagesmittel` | Validated archive | Daily | Mean | cm | m (`m`) |
| `stage` | `owf_wasserst_monatsminima` | Validated archive | Monthly (Unknown at `207340`) | Min | cm | m (`m`) |
| `stage` | `owf_wasserst_monatsmaxima` | Validated archive | Monthly | Max | cm | m (`m`) |
| `temperature` | `owf_wassertemp_monatsmittel` | Validated archive | Monthly | Mean | °C | °C (`degC`) |
| `discharge` | `pegel_bgis_abfluss` | Operational telemetry | Unknown | Unknown | m³/s | m³/s (`m3/s`) |
| `stage` | `pegel_bgis_wasserstand` | Operational telemetry | Unknown | Unknown | cm or m ü.A | m (`m`) |
| `discharge` | `pegel_longterm_abfluss` | Operational telemetry | Daily | Unknown | m³/s | m³/s (`m3/s`) |
| `stage` | `pegel_longterm_wasserstand` | Operational telemetry | Daily | Unknown | cm or m ü.A | m (`m`) |

A station may publish only a subset of these eleven products. Federal eHYD
publishes validated river water temperature only as monthly means
(`owf_wassertemp_monatsmittel`); daily and near-real-time river water
temperature are not published on this federal service.

In the validated archive, monthly minimum and maximum products
(`*_monatsminima`, `*_monatsmaxima`) report the lowest or highest instantaneous
measurement recorded within each calendar month, stamped with its exact
occurrence date and time, rather than the lowest or highest daily mean.

RivRetrieve keeps validated archive series and operational telemetry strictly
separate. It does not append unchecked telemetry onto validated yearbook records
or calculate daily means from sub-hourly readings. Inspect all candidate series
and station metadata at a gauge offline before fetching:

```python
all_discharge = rr.find(provider="at_ehyd", station="209486", quantity="discharge")
candidates = rr.series(all_discharge)
metadata = rr.metadata(all_discharge)
```

Filtering with `frequency="daily"` and `statistic="mean"` selects only the
validated `owf_abfl_tagesmittel` series because `pegel_longterm_abfluss` has no
established statistic and `pegel_bgis_abfluss` has no established frequency or
statistic. To retrieve an operational telemetry series without also requesting
archive products, pass its `series_id` from `candidates` to `rr.pick(all_discharge,
series_id=...)`.

In `pegel_bgis_*` responses, RivRetrieve reads only the observation time series
and omits static warning-level lines (*Niedrigwasser*, *Mittelwasser*, and
*Hochwasser* thresholds). In `pegel_longterm_*` responses, RivRetrieve reads
only the current calendar year's `current_value` series; it omits the prior-year
overlay (`last_year_value`, which is aligned onto the current year's 365- or
366-day axis without its own calendar dates) and the 30-year climatological
summary curves (`min_data`, `max_data`, `mit_data`, `p5_data`, `p95_data`).

## Stage references and moving gauge zeros

River stage (*Wasserstand*) in both *Geprüfte Daten* and *Pegel Aktuell* is
published in centimetres relative to the station's local gauge zero
(*Pegelnullpunkt*). RivRetrieve multiplies `cm` values by `0.01` to return
metres (`m`), keeps `"cm"` in `source_unit`, and sets
`vertical_reference="gauge_zero"` on the series. Genuine water levels below
gauge zero remain negative (for example down to `-2.27 m` at Danube station
`207068`, Linz), and published negative values in water-temperature exports
(down to `-2.8 °C` in `owf_wassertemp_monatsmittel` at `200352`, Unterhochsteg)
are likewise preserved without clamping.

Use care when interpreting multi-year stage records or comparing water levels
across periods. At most Austrian river gauges (`543` of `739` historical river
gauges in the packaged snapshot, `537` with more than one distinct height), the
local gauge zero has been reset or resurveyed over time. eHYD's station master
sheets (*Stammdaten*) and stage CSV preambles list dated *Pegelnullpunkt*
heights in metres above the Adriatic datum (`m ü.A.`, *Meter über Adria*),
without stating whether historical stage observations prior to a reset were
adjusted to the latest datum or left relative to the datum active at the time of
measurement.

Because no single scalar elevation applies across a station's full history,
the `elevation_*` columns are `null` in `rr.metadata(selection)`
(`state="no_metadata"` in `rr.metadata(selection, view="source")`) and
`vertical_datum` remains unknown on stage series. Do not add a single
*Pegelnullpunkt* height to a long stage record without checking the station's
dated datum table on eHYD. Where an eHYD stage response declares `m ü.A` or
`m ü.A.` (*Meter über Adria*, water-surface elevation above sea level),
RivRetrieve returns metres (`m`) without scaling, with
`vertical_reference="above_sea_level"` and `vertical_datum` unknown; all river
stage series in the packaged snapshot currently publish `cm` above gauge zero.

Station metadata exposes station names (`name` from the historical registry and
`messstelle` from *Pegel Aktuell*), water-body names (`gewaesser` and
`gewasser`), and orographic catchment area (`orogr.Einzugsgebiet [km²]` with
unit `km²` for gauges in the historical registry). When `name` and `messstelle`
spell a gauge's name differently (`51` overlapping gauges), summary
`station_name` is `null` and both spellings remain visible in
`rr.metadata(selection, view="source")`. Catchment areas retain eHYD's German
decimal comma as JSON text, such as `'"55,3"'` at station `209486`; see
[Station metadata](../station-metadata.md) for decoding details.

## Archive vintage and recent coverage

The three endpoint families cover separate periods and leave an unpublished gap
between the latest yearbook and the current calendar year:

- **Validated historical archive (`owf_*`):** Covers multi-decade histories up
  to the close of the latest published Hydrographic Yearbook. In the catalogue
  snapshot (2026-10-31) and live checks on 2026-11-03, validated river exports
  end at `2023-12-31` (marked by a closing boundary at `2024-01-01 00:00`). Start
  years vary widely by gauge and quantity, and decommissioned gauges end earlier.
- **Current-year daily comparison (`pegel_longterm_*`):** Covers only the
  current calendar year (`2026` during 2026) up to the latest reported day.
  Trailing `null` padding for future dates later in the year is trimmed. The
  endpoint ignores query parameters requesting earlier calendar years.
- **Near-real-time sub-hourly telemetry (`pegel_bgis_*`):** Covers a rolling
  window of roughly seven to eight days at variable sub-hourly intervals
  (commonly 5, 10, 15, or 30 minutes, sometimes varying within a single week).
  Older readings age out as new telemetry arrives. Local caching (`cache="reuse"`)
  accumulates readings already fetched across repeated runs, while readings that
  left the rolling window before being fetched cannot be recovered from this
  service.

Because validated `owf_*` files end at the latest published yearbook (`2023`)
and `pegel_longterm_*` serves only the current year's `current_value` series,
intermediate post-yearbook years (such as `2024` and `2025` before their
yearbook release) are not yet available through federal `ehyd.gv.at` exports.
When a request on `owf_*` spans into those unpublished years, `result.outcomes`
marks the post-yearbook span as `unresolved` rather than `empty`, reflecting
that the yearbook export has not yet reached those dates rather than confirming
an absence of river measurements.

## Time and data status

Time-zone handling differs between sub-hourly telemetry and the daily or monthly
files:

- **Sub-hourly telemetry (`pegel_bgis_*`):** eHYD documents these timestamps as
  fixed Central European Time (*Mitteleuropäische Zeit*, `MEZ`, `UTC+01:00`
  throughout the year without daylight-saving transitions). `rr.fetch` preserves
  the published `MEZ` wall-clock timestamps with `time_zone="+01:00"`
  (`time_zone="UTC+01:00"` in `rr.series(...)`), and `rr.to_utc(result)` shifts
  them to UTC (`time_zone="+00:00"`). Whether each sub-hourly value represents
  an instantaneous reading or a short interval average is not established.
- **Validated archive (`owf_*`) and current-year daily series
  (`pegel_longterm_*`):** Neither format states an explicit UTC offset in its
  machine-readable header or payload. Although BMLUK's [*Pegelordnung
  2014*](https://data.hydrographie.gv.at/Vorschriften_und_Anleitungen/30b%20Pegelordnung-2014.pdf)
  recommends `MEZ` (`UTC+01:00`), it also notes historical `SOZ/MEZ` summer-time
  practices, and older epochs in `owf_*` CSV files contain daily timestamps at
  `07:00` or `01:00` before shifting to `00:00` (at historical manual staff
  gauges, *Lattenpegel*, a scheduled morning reading counted as the daily
  value). RivRetrieve therefore keeps `time_zone="unknown"` and leaves
  `day_definition` unknown on `owf_*` and `pegel_longterm_*`; `rr.to_utc()`
  refuses `unknown` time zones rather than assuming `UTC+01:00` across all
  historical years.

On validated interval-mean products (`owf_*_tagesmittel` and
`owf_wassertemp_monatsmittel`), each timestamp marks the start of its validity
interval (`timestamp_anchor="start"`), in accordance with the CSV preamble rule
(*"Der Intervallwert gilt bis zum nächsten Zeitpunkt mit einem Wert oder
Lücke"*). At Danube station `207340` (Wilhering), the `W-Monatsminima` CSV file
declares and contains daily (`T,1`) stage minima rather than monthly minima;
RivRetrieve withholds `frequency="monthly"` on that station's
`owf_wasserst_monatsminima` series so monthly filters do not return daily rows.

eHYD labels its historical CSV downloads *Geprüfte Daten* (checked data) and
displays `"ungeprüfte Rohdaten!"` (unchecked raw data) on *Pegel Aktuell*
exports, noting that live telemetry can contain sensor faults, ice or weed
effects, backwater, or transmission gaps. Neither stream carries
per-observation quality flags, and RivRetrieve makes no quality judgement of
its own.

Keep missing-data representations distinct when inspecting results:

- In `owf_*` CSV files, missing spans are encoded as timestamped `Lücke` (gap)
  transition lines rather than one null row per missing day, and interval files
  end with a closing `Lücke` boundary line at the end of the export window.
  RivRetrieve omits `Lücke` lines without fabricating rows, suppresses the
  closing-boundary marker, and records an informational `source.gap_marker`
  issue in `result.issues` when interior gaps occur.
- In `pegel_bgis_*` and `pegel_longterm_*` JSON responses, interior missing
  entries published as `null` remain rows with `value=null`.
- Empty `0`-byte HTTP `200` responses or empty JSON payloads on *Pegel Aktuell*
  for stations currently offline report `unresolved` outcomes in
  `result.outcomes` (and when a specific telemetry series is requested by
  `series_id`, also record a `source.inventory_unresolved` warning in
  `result.issues`). By contrast, `0`-byte or malformed responses on advertised
  `owf_*` files report `failed` outcomes and error or warning issues in
  `result.issues`.

## Terms and citation

Official INSPIRE Austria metadata records for the [hydrographic surface-water
station network](https://data.inspire.gv.at/55e494dd-e0af-4806-95d6-86e30dde0504)
and the [current hydrographic measurement
service](https://geoportal.inspire.gv.at/metadatensuche/srv/api/records/6a67faa7-3ad7-4faf-91e9-17a518d10685/formatters/xml)
state that the data are licensed for private and commercial reuse free of charge
under [Creative Commons Attribution 4.0 International (CC BY
4.0)](https://creativecommons.org/licenses/by/4.0/), with mandatory source
attribution:

> Datenquelle: [ehyd.gv.at](https://ehyd.gv.at)

In German, the INSPIRE attribution clause requires *"Datenquelle: ehyd.gv.at",
wobei "ehyd.gv.at" als Link auf https://ehyd.gv.at auszuführen ist* (linking
`ehyd.gv.at` to `https://ehyd.gv.at`). Both `rr.describe("at_ehyd")` and
`result.provenance` expose `license="CC BY 4.0"` and
`citation="Datenquelle: ehyd.gv.at"`. For scientific traceability, also record
the station HZB number, product, requested period, and retrieval date.

The [eHYD portal](https://ehyd.gv.at/) notes that data are published pursuant to
§ 55o (2) *Wasserrechtsgesetz* and § 4 (1)(2) *Umweltinformationsgesetz* without
warranty for completeness, continuity, or accuracy, and prohibits automated
extraction outside content expressly offered for download (both per-station
*Geprüfte Daten* CSV files and *Pegel Aktuell* chart CSV exports are offered for
download on the portal). An older 2022 [general user
guide](https://ehyd.gv.at/assets/documents/eHYD_Allgemein.pdf) (page 14) also
contains an own-use and no-paid-resale statement alongside the CC BY 4.0 INSPIRE
licence declarations. RivRetrieve paces live requests politely (at most one
request per second) and caches downloaded archive series locally when
`cache="reuse"` is passed.

## Sources

Publisher documents and metadata checked on 2026-10-31 and verified reachable on
2026-11-03:

- [eHYD portal (`ehyd.gv.at`)](https://ehyd.gv.at/): national hydrographic map, station downloads, *Pegel Aktuell* telemetry charts, and portal legal notices.
- [BMLUK: *eHYD Allgemein* (general user guide, PDF)](https://ehyd.gv.at/assets/documents/eHYD_Allgemein.pdf): HZB numbering, monitoring domains, *Stammdaten* sheets, CSV exports, and usage notes.
- [BMLUK: *Aktuelle Daten in eHYD* (current telemetry guide, PDF)](https://ehyd.gv.at/assets/documents/Aktuelle_Daten.pdf): *Pegel Aktuell* transfer intervals and unchecked raw-telemetry caveats.
- [BMLUK: *Pegelordnung 2014* (PDF)](https://data.hydrographie.gv.at/Vorschriften_und_Anleitungen/30b%20Pegelordnung-2014.pdf): gauge-zero (*Pegelnullpunkt*) definitions, time-zone recommendations (`MEZ`), daily interval means, and monthly instantaneous extrema.
- [LFRZ OGC API Features (`i000501`)](https://gis.lfrz.gv.at/api/geodata/i000501/ogc/features/v1/collections?f=application%2Fjson): WGS84 (`EPSG:4326`) station collections for `messstellen_owf` and `pegel_aktuell`.
- [INSPIRE Austria metadata: hydrographic station network](https://data.inspire.gv.at/55e494dd-e0af-4806-95d6-86e30dde0504) and [*Pegel Aktuell* service](https://geoportal.inspire.gv.at/metadatensuche/srv/api/records/6a67faa7-3ad7-4faf-91e9-17a518d10685/formatters/xml): CC BY 4.0 licensing and mandatory `Datenquelle: ehyd.gv.at` attribution.

The station counts describe the packaged catalogue snapshot (2026-10-31). The
example observations were checked live on 2026-11-03. The [private verification
archive](https://github.com/RivRetrieve/verification-evidence#readme) retains
source captures, verification commands, exact outputs, and scope checks.
