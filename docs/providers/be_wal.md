# Belgium (Wallonia): SPW Hydrométrie

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `be_wal` |
| Country | Belgium (Wallonia, plus four cross-border gauges in northern France) |
| Published by | Service public de Wallonie (SPW), Hydrométrie (`SPW MI` `DGH` and `SPW ARNE` `DCENN`) |
| Read from | Official SPW KiWIS REST service (`hydrometrie.wallonie.be/services/KiWIS/KiWIS`) |
| Quantities | Discharge, stage, water temperature |
| Stations in the catalogue | 338 flowing-water gauges. Availability depends on station, series, and period |
| Station metadata | Station name, water-body name, and catchment drainage area. See [Fields by provider](../station-metadata.md#fields-by-provider) |
| Credentials | None |
| Terms | End-user read and download permitted free of charge; third-party redistribution and commercial diffusion require prior SPW authorization; source attribution required (`Sources des données : Service public de Wallonie` or `SPW`) |
| Agency documentation | [SPW Hydrométrie portal](https://hydrometrie.wallonie.be/), [Legal notice (*Mentions légales*)](https://hydrometrie.wallonie.be/mentions-legales.html), [KiWIS `queryServices` (`datasource=0`)](https://hydrometrie.wallonie.be/services/KiWIS/KiWIS?service=kisters&type=queryServices&datasource=0) |

Retrieve one week of daily mean discharge at station `6228`, `CHAUDFONTAINE Pisc`
on the Vesdre during the July 2021 flood:

```python
import rivretrieve as rr

selection = rr.find(
    provider="be_wal",
    station="6228",
    quantity="discharge",
    frequency="P1D",
    statistic="mean",
)

result = rr.fetch(selection, start="2021-07-12", end="2021-07-18", cache="bypass")

preview = result.data.select("time", "time_zone", "value", "unit").head(3)
print(preview.write_csv(), end="")

print(result.data.height)
print([(issue.severity, issue.code) for issue in result.issues])
```

Output:

```text
time,time_zone,value,unit
2021-07-12T00:00:00.000000,+01:00,6.795,m3/s
2021-07-13T00:00:00.000000,+01:00,10.134,m3/s
2021-07-14T00:00:00.000000,+01:00,288.923,m3/s
7
[('info', 'provenance.license_not_established')]
```

The request returned seven daily means in m³/s from SPW's `20-Debit.Jour.Moyen`
series. The preview shows the first three days. `time_zone` stays `+01:00` even
in July because SPW KiWIS stores every river series on fixed Central European Time
(`UTC+01:00`) throughout the year; see
[Time, missing values, and data status](#time-missing-values-and-data-status).

The informational issue `provenance.license_not_established` means the packaged
provider catalogue leaves the software licence unset (`None`) because SPW permits
free end-user download while restricting third-party redistribution and commercial
diffusion. It does not indicate a retrieval failure or mean attribution is
optional; see [Terms and citation](#terms-and-citation).

`cache="bypass"`, the default for live `rr.fetch` calls, queries SPW KiWIS
directly without reading or writing a local cache. Passing `cache="reuse"`
stores retrieved observations locally so repeated requests for covered periods
run offline. Passing `cache="refresh"` re-downloads cached intervals to pick up
upstream quality-control updates. This output was checked live on 2026-11-24.
Published values and quality codes can change during quality review. See
[Usage](../usage.md) for selection options and result handling.

## Who measures, and who publishes

Service public de Wallonie (SPW) publishes Wallonia's regional hydrometric
observations through the [SPW Hydrométrie portal](https://hydrometrie.wallonie.be/)
and its public KISTERS KiWIS `queryServices` endpoint (`datasource=0`). The portal
brings together two SPW monitoring divisions:

- **SPW Mobilité et Infrastructures (`SPW MI`), Direction de la Gestion
  hydrologique (`DGH`):** navigable waterways, using numeric station codes such
  as `"6228"` and `"1046"` (`145` stations).
- **SPW Agriculture, Ressources naturelles et Environnement (`SPW ARNE`), Direction
  des Cours d'eau non navigables (`DCENN` / AQUALIM):** non-navigable watercourses,
  using `L`-prefixed alphanumeric codes kept as strings such as `"L8220"` (`193`
  stations).

Both divisions are served from the same `datasource=0` KiWIS catalogue. Coverage
is regional to Wallonia plus four cross-border gauges operated in northern
France (`8702` Chooz on the Upper Meuse, `L7260` Gussignies, `L7940`
Eppe-Sauvage, and `L7950` Moustier-en-Fagne); Flemish and Brussels hydrometric
networks are separate jurisdictions outside `be_wal`. Thirteen included gauges
marked `STA_PUBINT="no"` in SPW metadata (such as `"L8470"` Dinant) still publish
anonymous HTTP 200 observations on KiWIS and remain selectable.

No API key or account is required. RivRetrieve searches the packaged station and
series catalogue offline, and `rr.fetch` requests observations over HTTPS while
limiting requests to one call per second across the shared HTTP client.

The packaged `be_wal` catalogue includes `338` geolocated flowing-water gauges
(`327` `Limnimètre` and `11` `Debitmètre` stations) with at least one supported
discharge, stage, or water-temperature series. Meteorological stations (`95`),
sub-basin zone shells without station types (`59`), five standing-water lakes
and reservoirs (`5997`, `640601`, `656601`, `7836`, and `9216`), turbine outflow
station `640C01` (*Eupen Centrale*), zero-series station `630201`,
coordinate-less staging entry `9109`, and stations publishing only specialized
computed discharge parameters (`7326` and `7406`) are excluded, together with air
temperature and relative stage series. Navigable river elevation stations
`3270` (*Pecq*), `7102` (*Liège*), and `8001` (*Namur*) are included.

## What you can retrieve

SPW KiWIS organizes each monitored river parameter into five aggregate steps
across five hydrological parameter families, giving `62` distinct series types in
total (`50/51/52` annual series do not exist for water temperature):

| Quantity filter | Source field / `variant` | Frequency | Statistic | Source unit | Returned unit |
|---|---|---|---|---|---|
| `discharge` | `05-Debit.Complet` | Unknown | Unknown | m³/s | m³/s |
| `discharge` | `10-Debit.1h.Moyen` | `PT1H` | Mean | m³/s | m³/s |
| `discharge` | `11-Debit.1h.Minimum` | `PT1H` | Minimum | m³/s | m³/s |
| `discharge` | `12-Debit.1h.Maximum` | `PT1H` | Maximum | m³/s | m³/s |
| `discharge` | `20-Debit.Jour.Moyen` | `P1D` | Mean | m³/s | m³/s |
| `discharge` | `21-Debit.Jour.Minimum` | `P1D` | Minimum | m³/s | m³/s |
| `discharge` | `22-Debit.Jour.Maximum` | `P1D` | Maximum | m³/s | m³/s |
| `discharge` | `40-Debit.Mois.Moyen` | `P1M` | Mean | m³/s | m³/s |
| `discharge` | `41-Debit.Mois.Minimum` | `P1M` | Minimum | m³/s | m³/s |
| `discharge` | `42-Debit.Mois.Maximum` | `P1M` | Maximum | m³/s | m³/s |
| `discharge` | `50-Debit.An.Moyen` | `P1Y` | Mean | m³/s | m³/s |
| `discharge` | `51-Debit.An.Minimum` | `P1Y` | Minimum | m³/s | m³/s |
| `discharge` | `52-Debit.An.Maximum` | `P1Y` | Maximum | m³/s | m³/s |
| `discharge` | `05-Debit ultrason.Complet` | Unknown | Unknown | m³/s | m³/s |
| `discharge` | `10-Debit ultrason.1h.Moyen` | `PT1H` | Mean | m³/s | m³/s |
| `discharge` | `11-Debit ultrason.1h.Minimum` | `PT1H` | Minimum | m³/s | m³/s |
| `discharge` | `12-Debit ultrason.1h.Maximum` | `PT1H` | Maximum | m³/s | m³/s |
| `discharge` | `20-Debit ultrason.Jour.Moyen` | `P1D` | Mean | m³/s | m³/s |
| `discharge` | `21-Debit ultrason.Jour.Minimum` | `P1D` | Minimum | m³/s | m³/s |
| `discharge` | `22-Debit ultrason.Jour.Maximum` | `P1D` | Maximum | m³/s | m³/s |
| `discharge` | `40-Debit ultrason.Mois.Moyen` | `P1M` | Mean | m³/s | m³/s |
| `discharge` | `41-Debit ultrason.Mois.Minimum` | `P1M` | Minimum | m³/s | m³/s |
| `discharge` | `42-Debit ultrason.Mois.Maximum` | `P1M` | Maximum | m³/s | m³/s |
| `discharge` | `50-Debit ultrason.An.Moyen` | `P1Y` | Mean | m³/s | m³/s |
| `discharge` | `51-Debit ultrason.An.Minimum` | `P1Y` | Minimum | m³/s | m³/s |
| `discharge` | `52-Debit ultrason.An.Maximum` | `P1Y` | Maximum | m³/s | m³/s |
| `stage` | `05-Hauteur.Complet` | Unknown | Unknown | m | m |
| `stage` | `10-Hauteur.1h.Moyen` | `PT1H` | Mean | m | m |
| `stage` | `11-Hauteur.1h.Minimum` | `PT1H` | Minimum | m | m |
| `stage` | `12-Hauteur.1h.Maximum` | `PT1H` | Maximum | m | m |
| `stage` | `20-Hauteur.Jour.Moyen` | `P1D` | Mean | m | m |
| `stage` | `21-Hauteur.Jour.Minimum` | `P1D` | Minimum | m | m |
| `stage` | `22-Hauteur.Jour.Maximum` | `P1D` | Maximum | m | m |
| `stage` | `40-Hauteur.Mois.Moyen` | `P1M` | Mean | m | m |
| `stage` | `41-Hauteur.Mois.Minimum` | `P1M` | Minimum | m | m |
| `stage` | `42-Hauteur.Mois.Maximum` | `P1M` | Maximum | m | m |
| `stage` | `50-Hauteur.An.Moyen` | `P1Y` | Mean | m | m |
| `stage` | `51-Hauteur.An.Minimum` | `P1Y` | Minimum | m | m |
| `stage` | `52-Hauteur.An.Maximum` | `P1Y` | Maximum | m | m |
| `stage` | `05-Hauteur absolue.Complet` | Unknown | Unknown | m | m |
| `stage` | `10-Hauteur absolue.1h.Moyen` | `PT1H` | Mean | m | m |
| `stage` | `11-Hauteur absolue.1h.Minimum` | `PT1H` | Minimum | m | m |
| `stage` | `12-Hauteur absolue.1h.Maximum` | `PT1H` | Maximum | m | m |
| `stage` | `20-Hauteur absolue.Jour.Moyen` | `P1D` | Mean | m | m |
| `stage` | `21-Hauteur absolue.Jour.Minimum` | `P1D` | Minimum | m | m |
| `stage` | `22-Hauteur absolue.Jour.Maximum` | `P1D` | Maximum | m | m |
| `stage` | `40-Hauteur absolue.Mois.Moyen` | `P1M` | Mean | m | m |
| `stage` | `41-Hauteur absolue.Mois.Minimum` | `P1M` | Minimum | m | m |
| `stage` | `42-Hauteur absolue.Mois.Maximum` | `P1M` | Maximum | m | m |
| `stage` | `50-Hauteur absolue.An.Moyen` | `P1Y` | Mean | m | m |
| `stage` | `51-Hauteur absolue.An.Minimum` | `P1Y` | Minimum | m | m |
| `stage` | `52-Hauteur absolue.An.Maximum` | `P1Y` | Maximum | m | m |
| `temperature` | `05-Temperature.Complet` | Unknown | Unknown | °C | °C |
| `temperature` | `10-Temperature.1h.Moyen` | `PT1H` | Mean | °C | °C |
| `temperature` | `11-Temperature.1h.Minimum` | `PT1H` | Minimum | °C | °C |
| `temperature` | `12-Temperature.1h.Maximum` | `PT1H` | Maximum | °C | °C |
| `temperature` | `20-Temperature.Jour.Moyen` | `P1D` | Mean | °C | °C |
| `temperature` | `21-Temperature.Jour.Minimum` | `P1D` | Minimum | °C | °C |
| `temperature` | `22-Temperature.Jour.Maximum` | `P1D` | Maximum | °C | °C |
| `temperature` | `40-Temperature.Mois.Moyen` | `P1M` | Mean | °C | °C |
| `temperature` | `41-Temperature.Mois.Minimum` | `P1M` | Minimum | °C | °C |
| `temperature` | `42-Temperature.Mois.Maximum` | `P1M` | Maximum | °C | °C |

All source values are already in canonical SI units (`m³/s`, `m`, and `°C`), so
RivRetrieve applies no numerical scaling. In `rr.series(...)`, `published_id`
and `variant` hold the numeric KiWIS time-series identifier (`ts_id`, such as
`"298610010"` for daily mean discharge at station `6228`). RivRetrieve retrieves
SPW's published `"PT1H"`, `"P1D"`, `"P1M"`, and `"P1Y"` aggregate series directly and
leaves frequency and statistic unknown (`None`) on `05-*.Complet` high-resolution
series, whose raw sampling interval varies across stations (from 5 minutes to
1 hour).

The packaged catalogue accounts for `8,198` active station-series pairs across
the `338` stations (`89` empty-coverage series verified over `1900..2027` are
marked unavailable):

- **Discharge (`294` gauges total):** `283` gauges publish standard
  rating-curve discharge (`Débit`, `267` to `278` active depending on cadence),
  and `11` gauges publish ultrasonic flowmeter discharge (`Débit ultrason`, all
  `11` active). No station publishes both discharge families.
- **Stage (`317` gauges total):** `314` gauges publish gauge-zero water level
  (`Hauteur` or `Hauteur sonde`, merged cleanly because both share identical
  cadences and never coexist at one gauge), and `3` navigable river gauges
  (`3270` Pecq, `7102` Liège, and `8001` Namur) publish elevation stage above
  sea level (`Hauteur absolue`). No station publishes both stage references.
- **Water temperature (`41` gauges total):** `38` to `41` gauges publish active
  sub-daily, `"PT1H"`, `"P1D"`, and `"P1M"` water temperature across `Température Eau`
  (`DGH`) and `Temperature Eau` (`DCENN`).

A listed series need not cover every year in a station's history. Inspect
available series and station metadata offline before narrowing a selection:

```python
import polars as pl

all_discharge = rr.find(provider="be_wal", station="6228", quantity="discharge")
candidates = rr.series(all_discharge)
metadata = rr.metadata(all_discharge)

hourly_mean_id = candidates.filter(
    (pl.col("frequency") == "PT1H") & (pl.col("statistic") == "mean")
)["series_id"].item()
hourly_mean = rr.pick(all_discharge, series_id=hourly_mean_id)
```

## Stage references, coordinates, and metadata

Stage series separate into two vertical-reference sets across the catalogue:

- **Gauge-zero stage (`05..52-Hauteur.*`, `314` gauges):** sets
  `vertical_reference="gauge_zero"` and `vertical_datum=None`. Genuine zero and
  negative readings (for example down to `-0.096 m` at `L8910` Clermont and
  `-0.01 m` at `L8470` Dinant) are preserved without clamping. Do not infer an
  above-sea-level elevation by adding raw KiWIS `station_gauge_datum` figures,
  which include negative-reading gauges and sentinel placeholders (`9999.0`).
- **Elevation stage (`05..52-Hauteur absolue.*`, `3` gauges):** sets
  `vertical_reference="above_sea_level"` and `vertical_datum=None`. `3270`
  (Pecq) reports `DNG`, whereas `7102` (Liège) and `8001` (Namur) leave the
  datum unit blank (`"---"`), so vertical datum remains unknown across this
  group.

Station metadata (`rr.metadata(selection)`) exposes three native KiWIS fields:

- `station_name` from `station_name` (`338/338`)
- `water_body_name` from `river_name` (`338/338`)
- `drainage_area` from `CATCHMENT_SIZE` in `km2` (`257/338` positive numeric
  values; the remaining `81/338` gauges, including `7102` Liège, preserve
  `source_null` where SPW omits `CATCHMENT_SIZE` or writes `"0,00 km²"`)
- `elevation` is omitted (`no_metadata` across all `338` gauges) because KiWIS
  leaves `station_elevation` unpopulated on `336/338` flowing-water gauges

Coordinates (`latitude` and `longitude`) come verbatim from KiWIS WGS 84 columns
(`crs="EPSG:4326"`).

## Record depth and query windowing

Long-running SPW gauges reach back decades across all five parameter families:
daily discharge and stage from `1929-01-01` at `9434` (*Membre Pont*) and
`1968-01-01` at `8221` (*Gendron*, with sub-daily hourly stage from `1968`),
ultrasonic discharge from `1983-01-01` at `8078` (*Waulsort*), and water
temperature from `1994-06-22` at `9541` (*Chiny*). Manual spot discharge
gaugings published as `00-Hauteur.Jaugeages` are outside RivRetrieve's
time-series scope and are omitted.

SPW KiWIS fails with HTTP `500 DatasourceError` when multi-decade high-resolution
`05-*.Complet` requests exceed KiWIS's response limits. RivRetrieve splits
`05-*.Complet` requests automatically into `365`-day spans and hourly
(`10/11/12`) requests into `3,650`-day (`10`-year) spans, while retrieving daily,
monthly, and yearly aggregates in single spans. Use `cache="reuse"` when
fetching multi-decade high-resolution records so repeated runs read locally.

## Time, missing values, and data status

SPW Hydrométrie uses a single fixed-timezone interval convention across all
cadences:

- **Fixed CET `+01:00` timestamps:** Although KiWIS's default endpoint display
  switches between `+01:00` and summer `+02:00` (repeating `02:00` on autumn
  clock changes and shifting summer daily timestamps to `01:00+02:00`), SPW
  series run on fixed `UTC+01:00` (`station_utcoffset="-60"`). RivRetrieve
  queries KiWIS with `timezone=UTC` for monotonic timestamps and expresses all
  `62` products cleanly on `+01:00` (`time_zone="+01:00"`), so daily boundaries
  always land at `00:00:00+01:00` (`23:00:00Z` the preceding UTC day).
- **Interval-start anchoring:** Per SPW's *Guide d'utilisation* (`constant
  jusqu'au suivant`), aggregate `10..52` timestamps mark the inclusive start of
  each hour, day (`+01:00` calendar day), month (`YYYY-MM-01T00:00:00`), or
  year (`YYYY-01-01T00:00:00`), with `temporal_support="interval"` and
  `timestamp_anchor="start"`. Daily selections (`20/21/22`) match bare calendar
  dates (`"2021-07-12"` to `"2021-07-18"`) inclusively. Because fixed `+01:00`
  is always one hour ahead of UTC, `rr.to_utc(result)` shifts timestamps back
  one hour cleanly.
- **Missing slots:** Inside a recorded window, SPW emits explicit missing-value
  rows (`Value=null` with `Quality Code=-1` and `Quality Code Name=null`);
  RivRetrieve keeps those rows with `value=null` rather than dropping them.
  Intervals with no stored records emit zero rows.

SPW publishes KISTERS KiWIS `Quality Code` and `Quality Code Name` pairs on
every row: `0` (`Excellent`), `40` (`Good`), `80` (`Fair`), `120` (`Suspect`),
`160` (`Poor`), `161`/`162` (`S` Manuel), `163` (`S` Manuel pris en compte pour
les stat), `165` (`L` Limnimétrie), `200` (`Unknown`), `205` (`Douteux (publié)`),
`210` (`Douteux (non publié)`), `253` (`VF` Valeurs fantomes), and `-1` (`null`,
paired with `Value=null`). Operational recent peaks and high-flow flood peaks
(such as July 2021 at `6228` Chaudfontaine) often retain code `200` (`Unknown`).
RivRetrieve returns all published observations without filtering or ranking by
quality code and preserves both raw columns under observation schema
`be_wal.quality`:

```python
result = rr.fetch(selection, start="2021-07-12", end="2021-07-18")

# Field catalogue
print(rr.annotations(result).select("schema", "name", "dtype").rows())
# [('be_wal.quality', 'quality_code', 'Int64'), ('be_wal.quality', 'quality_code_name', 'String')]

# Append to the canonical frame
annotated = result.to_polars(annotations=True)
print(annotated.select("time", "value", "quality_code", "quality_code_name").rows())
```

Output:

```text
[(datetime.datetime(2021, 7, 12, 0, 0), 6.795, 40, 'Good'), (datetime.datetime(2021, 7, 13, 0, 0), 10.134, 40, 'Good'), (datetime.datetime(2021, 7, 14, 0, 0), 288.923, 200, 'Unknown'), (datetime.datetime(2021, 7, 15, 0, 0), 402.9, 200, 'Unknown'), (datetime.datetime(2021, 7, 16, 0, 0), 138.395, 200, 'Unknown'), (datetime.datetime(2021, 7, 17, 0, 0), 72.476, 40, 'Good'), (datetime.datetime(2021, 7, 18, 0, 0), 42.858, 40, 'Good')]
```

Both annotation outputs were checked live on 2026-11-24.

## Terms and citation

SPW's [legal notice (*Mentions légales*)](https://hydrometrie.wallonie.be/mentions-legales.html)
and regional data conditions (`DataSPW-CGA.pdf` / `DataSPW-CGU.pdf`) allow free
public download and reproduction by end users without prior agreement, while
prohibiting third-party distribution (via files, websites, or web services) and
commercial or advertising diffusion without prior written SPW authorization.
RivRetrieve reads SPW KiWIS directly on demand during `rr.fetch` and does not
redistribute observation archives; its MIT licence applies to RivRetrieve code
only, while packaged station metadata remains subject to SPW's own notice in
`rr.describe("be_wal")`.

Source attribution is required whenever data are reproduced or published:

> Sources des données : Service public de Wallonie (or `Sources des données : SPW`), linking `https://hydrometrie.wallonie.be/` where possible.

In code, `result.provenance.citation` and `rr.describe("be_wal")["citation"]`
carry `« Sources des données : Service public de Wallonie » ou « Sources des
données : SPW »`, while `result.provenance.license` stays `None` (omitted from
the Croissant descriptor returned by `rr.describe("be_wal")` and triggering the
informational `provenance.license_not_established` issue). For scientific
reproducibility, record the SPW station code (`station_id`), KiWIS `ts_id`
(`published_id`), requested period, and access date.

## Sources

Publisher portals, KiWIS API descriptors, and legal terms checked in November 2026:

- [SPW Hydrométrie portal (`hydrometrie.wallonie.be`)](https://hydrometrie.wallonie.be/):
  unified Walloon `DGH` and `DCENN` hydrometric monitoring network, user guide
  (*Guide d'utilisation* defining `constant jusqu'au suivant` interval-start
  semantics), and portal station groupings (`ESurf_Debit`, `ESurf_Hauteur`).
- [SPW Mentions légales](https://hydrometrie.wallonie.be/mentions-legales.html):
  mandatory source attribution (`Sources des données : Service public de Wallonie`
  / `SPW`), free end-user download permission, and restrictions on third-party
  redistribution and commercial diffusion.
- [SPW KiWIS `queryServices` (`datasource=0`)](https://hydrometrie.wallonie.be/services/KiWIS/KiWIS?service=kisters&type=queryServices&datasource=0):
  `getStationList` (`ca_sta` attributes, `station_utcoffset="-60"`, WGS 84
  coordinates), `getTimeseriesList` (`62`-product cadence ladder across
  `Débit`, `Débit ultrason`, `Hauteur`, `Hauteur sonde`, `Hauteur absolue`,
  `Température Eau`, and `Temperature Eau`), and `getTimeseriesValues` UTC query
  semantics.
- [SPW KiWIS `getQualityCodes`](https://hydrometrie.wallonie.be/services/KiWIS/KiWIS?service=kisters&type=queryServices&datasource=0&request=getQualityCodes&format=json):
  numeric and textual definitions for KiWIS quality codes `0` through `253`.

The station count (`338`) and active series count (`8,198`) describe the
packaged catalogue snapshot (2026-11-23). Live example outputs were checked on
2026-11-24. A successful example retrieval does not establish continuous
coverage across other dates, stations, or series. The
[private verification archive](https://github.com/RivRetrieve/verification-evidence#readme)
retains the captured inputs, external GRDC-Caravan benchmark comparison, and
verification commands.
