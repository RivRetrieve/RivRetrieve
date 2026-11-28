# Slovenia: ARSO

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `si_arso` |
| Country | Slovenia |
| Published by | Agencija Republike Slovenije za okolje (ARSO), Ljubljana |
| Read from | Official ARSO hydrological archive (`pov_arhiv_tab.php`) and operational surface-water pages (`amp/`) |
| Quantities | Discharge, stage, water temperature |
| Stations in the catalogue | 619 river and canal gauges (615 with selectable series). Availability depends on station, quantity, product and period |
| Station metadata | Station name, water-body name and drainage area (when published; see sentinel codes below). See [Fields by provider](../station-metadata.md#fields-by-provider) |
| Credentials | None |
| Licence stated by ARSO | Creative Commons Attribution 4.0 International (CC BY 4.0); mandatory source attribution (`Agencija Republike Slovenije za okolje (ARSO)`) |
| Agency documentation | [ARSO surface-water archive](https://vode.arso.gov.si/hidarhiv/pov_arhiv_tab.php), [ARSO operational monitoring portal](https://www.arso.gov.si/vode/podatki/amp/), [Methodological notes (`HL09 III.Pojasnila_Explanation.pdf`)](https://www.arso.gov.si/vode/poro%c4%8dila%20in%20publikacije/HL09%20III.Pojasnila_Explanation.pdf), [Surface-water monitoring programme (2021)](https://www.arso.gov.si/vode/poro%c4%8dila%20in%20publikacije/Program%20hidrolo%c5%a1kega%20monitoringa%20povr%c5%a1inskih%20voda_od%202021.pdf) |

Retrieve one week of validated daily discharge at station `1060`, Gornja
Radgona I on the Mura:

```python
import rivretrieve as rr

selection = rr.find(
    provider="si_arso",
    station="1060",
    quantity="discharge",
    frequency="P1D",
)

result = rr.fetch(selection, start="2024-01-01", end="2024-01-07", cache="bypass")

preview = result.data.select("time", "time_zone", "value", "unit").head(3)
print(preview.write_csv(), end="")

print(result.data.height)
print(result.issues)
print(rr.series(result, annotations=True)["data_status"].to_list())
```

Output:

```text
time,time_zone,value,unit
2024-01-01T00:00:00.000000,unknown,223.499,m3/s
2024-01-02T00:00:00.000000,unknown,213.818,m3/s
2024-01-03T00:00:00.000000,unknown,195.036,m3/s
7
()
['Verificirani podatki']
```

The request returned seven validated daily discharges in m³/s from ARSO's
historical archive. The preview shows the first three days, and
`rr.series(result, annotations=True)` exposes ARSO's `Verificirani podatki`
status label from `si_arso.series`. `time_zone` is `unknown` on archive
products because the CSV exports omit UTC offsets; see
[Time and data status](#time-and-data-status). The empty tuple `()` indicates no
transport, parsing, or gap issues. Attribution is required whenever using ARSO
data; see [Terms and citation](#terms-and-citation).

`cache="bypass"`, the default for live `rr.fetch` calls, requests ARSO directly
without reading or writing a local cache. Passing `cache="reuse"` stores
downloaded archive intervals locally so subsequent queries inside that year span
reuse cached observations with zero HTTP calls. This output was checked live on
2026-11-24. See [Usage](../usage.md) for selection options and result handling.

## Who measures, and who publishes

The Slovenian Environment Agency (Agencija Republike Slovenije za okolje,
ARSO), part of the Ministry of the Environment, Climate and Energy, operates the
national hydrological monitoring network and publishes surface-water records at
[vode.arso.gov.si/hidarhiv/](https://vode.arso.gov.si/hidarhiv/pov_arhiv_tab.php).
Historical annual validation runs through multi-stage quality control before
series enter the public archive; at the time this catalogue was built, the
validated archive extends through `2024-12-31` and reaches back to `1895` on
long-running gauges such as `3660` (Litija I on the Sava).

No API key or registration is required. RivRetrieve filters the packaged
station and series catalogue offline and fetches data on demand from ARSO's
public CSV and HTML endpoints. Station identifiers are four-digit ARSO station
codes (`sifra`), kept as strings such as `"1060"`.

The packaged `si_arso` catalogue covers `619` flowing surface-water gauges in
ARSO's archive dropdown, spanning natural rivers (including karst-fed rivers
such as the Unica, Hubelj, Rižana, Savica, Soča, and `5040` Ljubljanica at
Kamin) and man-made canals or bypasses (`Mlinščica`, `Kanal HE ...`). Of those
`619` gauges, `615` expose at least one selectable discharge, stage, or water
temperature series; four gauges (`5400`, `5410`, `5420`, and sediment-only
`9060`) have no in-scope series. Karst spring orifices (*Izviri*), lakes and
reservoirs (*Jezera*, *zadrževalniki*), coastal marine gauges (`9350` Koper,
`9400` Piran), and groundwater wells (`pod_arhiv_tab.php`) are excluded.
Suspended sediment, turbidity, and electrical conductivity columns published at
a subset of stations are also outside RivRetrieve's current quantity scope.

## What you can retrieve

ARSO publishes surface-water data through two distinct streams:

1. **Validated historical archive (*Verificirani podatki*):** Annual-year CSV
   exports of quality-controlled daily observations (`b_oddo_CSV`) and monthly
   instantaneous extrema (`b_eks_CSV`).
2. **Operational telemetry (*Začasni podatki*):** Unverified near-real-time
   automatic readings from rolling 1-day (`t_1`), 7-day (`t_7`), and 30-day
   (`t_30`) station HTML tables under `amp/`.

**Validated historical archive (`Verificirani podatki`):**

| Quantity filter | Source column (`published_id`) | Frequency | Statistic | Source unit | Returned unit |
|---|---|---|---|---|---|
| `discharge` | `pretok (m3/s)` | `P1D` | Unknown | m3/s | m³/s |
| `discharge` | `Q_MIN` | `P1M` | Minimum | m3/s | m³/s |
| `discharge` | `Q_MAX` | `P1M` | Maximum | m3/s | m³/s |
| `stage` | `vodostaj (cm)` | `P1D` | Unknown | cm | m |
| `stage` | `H_MIN` | `P1M` | Minimum | cm | m |
| `stage` | `H_MAX` | `P1M` | Maximum | cm | m |
| `temperature` | `temp. vode (°C)` | `P1D` | Unknown | °C | °C |
| `temperature` | `Tv_MIN` | `P1M` | Minimum | °C | °C |
| `temperature` | `Tv_MAX` | `P1M` | Maximum | °C | °C |

In `rr.series(...)`, `variant` is `null` on all nine historical archive series
(so `rr.pick(sel, variant="Q_MIN")` matches nothing); `published_id` carries the
source column or extreme code shown above, and ordinary filters such as
`frequency="P1D"` or `frequency="P1M", statistic="max"` select archive series.

**Operational telemetry (`Začasni podatki`):**

| Quantity filter | Source field / `variant` | Frequency | Statistic | Source unit | Returned unit |
|---|---|---|---|---|---|
| `discharge` | `operational_10min` (`Pretok [m³/s]`) | `PT10M` (`PT5M` at 8 gauges, `PT30M` at 2 gauges) | Unknown | m³/s | m³/s |
| `discharge` | `operational_30min` (`Pretok [m³/s]`) | `PT30M` | Unknown | m³/s | m³/s |
| `discharge` | `operational_hourly` (`Pretok [m³/s]`) | `PT1H` | Unknown | m³/s | m³/s |
| `stage` | `operational_10min` (`Vodostaj [cm]`) | `PT10M` (`PT5M` at 8 gauges, `PT30M` at 2 gauges) | Unknown | cm | m |
| `stage` | `operational_30min` (`Vodostaj [cm]`) | `PT30M` | Unknown | cm | m |
| `stage` | `operational_hourly` (`Vodostaj [cm]`) | `PT1H` | Unknown | cm | m |
| `temperature` | `operational_10min` (`Temperatura vode [°C]`) | `PT10M` (`PT5M` at 8 gauges, `PT30M` at 2 gauges) | Unknown | °C | °C |
| `temperature` | `operational_30min` (`Temperatura vode [°C]`) | `PT30M` | Unknown | °C | °C |
| `temperature` | `operational_hourly` (`Temperatura vode [°C]`) | `PT1H` | Unknown | °C | °C |

Not every station publishes all eighteen series; availability varies across
gauges (`530` gauges carry archive discharge, `601` carry archive stage, `215`
carry archive water temperature, and `179` carry rolling operational telemetry).

Daily archive series leave `statistic` unknown because ARSO's older manual
observation stations recorded once-daily `07:00` staff readings (`tip = O`)
alongside later continuous/hourly averages (`tip = L/P/A`) in the same column.
Monthly archive extrema (`Q_MIN`/`Q_MAX`, `H_MIN`/`H_MAX`, `Tv_MIN`/`Tv_MAX`)
report the minimum or maximum instantaneous reading observed in each month,
stamped with its exact reported occurrence date and time (`YYYY-MM-DD HH:MM:00`).

On rolling 1-day operational pages (`variant="operational_10min"`), most
telemetered gauges report at `PT10M`, eight gauges (`1260`, `2005`, `2110`,
`2830`, `3530`, `4050`, `4270`, `8180`) report at `PT5M`, and two gauges
(`3900`, `6120`) report at `PT30M`. Rolling 7-day (`variant="operational_30min"`,
`PT30M`) and 30-day (`variant="operational_hourly"`, `PT1H`) pages report uniform
30-minute and hourly cadences across telemetered gauges.
All stage quantities (`vodostaj (cm)` / `Vodostaj [cm]`, `H_MIN`, `H_MAX`) are
converted from centimetres to metres (`unit="m"`). Negative stage values (for
example `-0.21` m at `1058`) reflect normal low-water levels below local staff
gauge zero and are preserved as published.

## Selecting and inspecting series

Use `rr.find`, `rr.pick`, `rr.series`, and `rr.metadata` offline before fetching
observations:

```python
import rivretrieve as rr

candidates = rr.series(rr.find(provider="si_arso", station="1060"))
all_discharge = rr.find(provider="si_arso", station="1060", quantity="discharge")

archive_daily = rr.pick(all_discharge, frequency="P1D")
op_10min = rr.pick(all_discharge, variant="operational_10min")
op_30min = rr.pick(all_discharge, variant="operational_30min")
op_hourly = rr.pick(all_discharge, variant="operational_hourly")

metadata = rr.metadata(archive_daily)
```

For multi-stream gauges such as `1060`, pass `frequency`, `statistic`, or
`variant` (`"operational_10min"`, `"operational_30min"`, or
`"operational_hourly"`) to `rr.find` or `rr.pick` so `rr.fetch` retrieves only
the stream and resolution needed. Queries spanning both archived years and
unpublished recent years (such as `start="2020-01-01"` with default today's
end date) return all published archive rows cleanly with unresolved bounds for
unpublished years and no warnings (`result.issues == ()`).

## Station metadata and coordinates

Packaged coordinates are published in `EPSG:4326` (`612` stations) by
transforming ARSO's official Slovenian grid coordinates (`GKY`, `GKX` in
`D48/GK`, `EPSG:3912`), rescuing four stations (`2070`, `6150`, `6380`, `6620`)
from ARSO's periodic discharge tables (`Q*_obdobne_stat.xlsx`) where `Spisek`
omits them. Do not substitute the raw `LON`/`LAT` columns printed in ARSO's
2019 station spreadsheet or 2021 monitoring programme PDF: those columns omit
the Bessel-to-WGS84 datum transformation and sit roughly `370` to `440` m east
of the true gauge locations. Seven stations (`5049`, `6310`, `6570`, `7290`,
`7450`, `9090`, `9290`) lack public grid coordinates and have
`latitude=None`, `longitude=None`, and `crs="unknown"`.

Packaged metadata (`rr.metadata(selection)`) preserves ARSO's published values:

- `station_name`: ARSO station name (*Merilno mesto*, for example `"Gornja Radgona I"`).
- `water_body_name`: watercourse name (*VODOTOK* / *Vodotok*, for example `"Mura"`).
- `drainage_area`: catchment area in `km2` (*ZALEDJE - F (km2)* / *F (km2)*)
  when published, kept verbatim including ARSO's documented sentinel placeholders:
  `88888.88` (`36` packaged stations) denotes unmeasurable karst catchments, and
  `99999.99` (`7` packaged stations such as `4450` on the *Mlinščica* canal)
  denotes canals, bifurcations, or indeterminable divides. Filter
  `drainage_area < 88888` before converting discharge to specific runoff.

Stage datum (`Kota "0"`) is documented in multi-epoch station histories and
periodic tables across `SVS2000` (Trieste datum) and mixed historical leveling
epochs rather than in ARSO's time-series exports. RivRetrieve therefore leaves
`elevation_*` fields null in station metadata and marks stage series as
`vertical_reference="gauge_zero"` with `vertical_datum=None`.

## Time and data status

Archive CSV exports (`b_oddo_CSV` and `b_eks_CSV`) do not embed UTC offsets and
span both manual morning observations and automatic calendar-day records across
over a century of operation. RivRetrieve therefore marks all historical archive
series with `time_zone="unknown"` (`None` in `rr.series`), and `rr.to_utc()`
raises `FatalContractError` rather than guessing an offset. Daily archive
values carry midnight timestamps (`YYYY-MM-DD 00:00:00`); monthly extrema carry
exact reported occurrence timestamps (`YYYY-MM-DD HH:MM:00`).

Operational rolling HTML tables (`amp/`) declare `Datum (CET)` explicitly,
meaning fixed `UTC+01:00` year-round even in summer (no daylight-saving jump).
RivRetrieve stamps operational observations with `time_zone="+01:00"`, and
`rr.to_utc(result)` shifts those timestamps `-1 hour` cleanly to `"+00:00"`.

Every row returned in `rr.series(result, annotations=True)` exposes ARSO's
quality designation in the `si_arso.series` annotation `data_status` (`String`,
series scope):

- `Verificirani podatki`: quality-controlled archive records (extending through
  `2024-12-31` as of `2026-11-23`).
- `Začasni podatki`: provisional near-real-time telemetry from rolling `amp/`
  windows, subject to revision, rating-curve updates, or temporary sensor
  outages (published as `"-"`, omitted as missing rows cleanly).

During `cache="reuse"`, archive requests cache resolved full-year spans cleanly
so later sub-window queries need zero network calls; operational `amp/` fetches
use `coverage="observations"`, accumulating parsed snapshots across calls while
leaving uncollected times outside rolling snapshots unresolved.

## Terms and citation

ARSO publishes all hydrological data on its web portal under the
[Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/)
licence with mandatory source attribution. Both `rr.describe("si_arso")` and
`result.provenance` preserve ARSO's published Slovenian licence and
citation strings verbatim:

- `license`: `Podatki so dostopni pod Creative Commons - Attribution 4.0 International (CC BY 4.0) licenco. (https://creativecommons.org/licenses/by/4.0)`
- `citation`: `Pri objavi, distribuciji ali uporabi podatkov v kakršnekoli namene je potrebno citirati vir podatkov: Agencije Republike Slovenije za okolje (ali skrajšano: ARSO).`

For scientific reproducibility, record the four-digit station identifier, series
name or `variant`, requested period, and retrieval date. Pass `cache="reuse"`
for repeated or multi-station archival workflows so downloaded years and
rolling snapshots are reused locally.

## Sources

Publisher portals, station lists, and hydrological manuals checked on
2026-11-23 through 2026-11-24:

- [ARSO Surface-Water Archive (`pov_arhiv_tab.php`)](https://vode.arso.gov.si/hidarhiv/pov_arhiv_tab.php):
  station river/gauge dropdowns (`646` entries), validated daily archive CSV
  exports (`b_oddo_CSV`), and monthly extrema CSV exports (`b_eks_CSV`).
- [ARSO Operational Surface-Water Monitoring (`amp/`)](https://www.arso.gov.si/vode/podatki/amp/):
  rolling `t_1`, `t_7`, and `t_30` station HTML pages declaring `Datum (CET)`,
  `Začasni podatki` status notice, and ARSO CC BY 4.0 attribution terms.
- ARSO `Spisek vodomernih postaj_okt2019.xlsx`, `Q1000..Q9000_obdobne_stat.xlsx`,
  [Hydrological Yearbook Explanations (`HL09 III.Pojasnila_Explanation.pdf`)](https://www.arso.gov.si/vode/poro%c4%8dila%20in%20publikacije/HL09%20III.Pojasnila_Explanation.pdf),
  [Surface-Water Monitoring Programme (from 2021)](https://www.arso.gov.si/vode/poro%c4%8dila%20in%20publikacije/Program%20hidrolo%c5%a1kega%20monitoringa%20povr%c5%a1inskih%20voda_od%202021.pdf),
  and *Hidrološki monitoring 2023/2024* annual reports: `D48/GK` (`EPSG:3912`)
  reference grid coordinates, chapter classification (`A` rivers, `B` lakes,
  `C` springs), `88888.88` / `99999.99` catchment sentinels, and daily averaging
  rules.
- [Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/):
  attribution terms.

The station (`619` gauges, `615` with selectable series) and series (`5,628`)
counts describe the packaged catalogue snapshot (`2026-11-23`). The practical
example was verified live on `2026-11-24`. The
[private verification archive](https://github.com/RivRetrieve/verification-evidence#readme)
retains the captured inputs, exact WMO/GRDC (`18/18` gauges) and WoKaS (`7/7`
ARSO-ID gauges) hydrograph benchmarks, and verification commands.
