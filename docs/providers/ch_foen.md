# Switzerland: FOEN, through Existenz.ch

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `ch_foen` |
| Country | Switzerland |
| Data owner | Bundesamt für Umwelt / Federal Office for the Environment (BAFU/FOEN) |
| Read from | Existenz.ch's API and InfluxDB archive, an unofficial third-party service |
| Quantities | Discharge, stage, water temperature |
| Stations in the catalogue | 246 locations, not confirmed availability for every quantity |
| Credentials | No personal credentials required |
| Terms | FOEN: free use, citation recommended; Existenz.ch: public and non-commercial use, FOEN credit and link requested |
| Agency documentation | [hydrodaten.admin.ch](https://www.hydrodaten.admin.ch/en), [Existenz.ch API](https://api.existenz.ch/) |

Retrieve January 2024 discharge at station `2018`, selecting the source's `flow` field:

```python
import rivretrieve as rr

selection = rr.find(provider="ch_foen", station="2018", quantity="discharge")
flow = rr.pick(selection, variant="flow")

result = rr.fetch(flow, start="2024-01-01", end="2024-01-31", cache="bypass")

preview = result.data.select("time", "time_zone", "value", "unit").head(3)
print(preview.write_csv(), end="")

print(result.data.height)
print(result.issues)
```

Output:

```text
time,time_zone,value,unit
2024-01-01T00:00:00.000000,+00:00,108.045,m3/s
2024-01-01T00:40:00.000000,+00:00,108.045,m3/s
2024-01-01T00:50:00.000000,+00:00,108.182,m3/s
4402
()
```

The first three rows show discharge in m³/s. The request returned 4,402 rows and no issues
(the empty tuple `()`). The gaps between these first timestamps are present in the returned
record; RivRetrieve does not fill them. Bare dates include the whole first and last day.
`cache="bypass"` requests the source rather than a local cache. Archive values can change,
so a later request need not reproduce this output exactly.

Run the examples below in the same Python session.

## Who measures, and who publishes

The measurements are FOEN's: the Federal Office for the Environment runs Switzerland's
national hydrological monitoring network and publishes current values on
[hydrodaten.admin.ch](https://www.hydrodaten.admin.ch/en).

RivRetrieve does not read FOEN directly. It reads **Existenz.ch**, a service built by Christian
Studer (Bureau für digitale Existenz) that republishes FOEN's hydrology data through an API,
with a long-term archive in InfluxDB.

**It is unofficial.** Existenz.ch says:

> These APIs are unofficial. There is no guarantee of availability or top performance. They are
> actively monitored though.

**It states a non-commercial condition of its own**, separate from FOEN's data terms:

> These APIs with weather and water data for Switzerland are free for public and non-commercial
> use, lovingly handcrafted by Christian Studer (Bureau für digitale Existenz).

**It asks for credit to FOEN:**

> BAFU data needs to be credited and linked to the BAFU.

FOEN's own terms allow commercial use (see [Terms](#terms)). If Existenz.ch's conditions do
not suit your work, obtain data directly from FOEN instead. RivRetrieve does not decide that
for you.

## What you can retrieve

| Quantity filter | Source field / `variant` | Source unit | Returned unit |
|---|---|---|---|
| `discharge` | `flow` | m³/s | m³/s |
| `discharge` | `flow_ls` | l/s | m³/s |
| `stage` | `height` | m | m |
| `stage` | `height_abs` | m | m |
| `temperature` | `temperature` | °C | °C |

Swiss variants identify **source fields**, not processing or consistency statuses.
Existenz publishes discharge in two fields: `flow` in m³/s and `flow_ls` in litres per second.
RivRetrieve returns both in m³/s, dividing `flow_ls` values by 1,000. The original field names
remain visible so you can identify the source. A station may provide only one of these fields.

The parameter dictionary labels `height` as **Pegel m ü. M.**, establishing a reference above
sea level but not a specific vertical datum. It labels `height_abs` as **Pegel m**, without
establishing its reference. Do not infer a reference from `_abs` or treat the two fields as
interchangeable.

Inspect the discharge candidates before deciding which field to request:

```python
candidates = rr.series(selection).select(
    "station_id", "variant", "quantity", "source_unit", "unit", "frequency", "statistic"
)

print(candidates.rows())
```

Output:

```text
[('2018', 'flow', 'discharge', 'm3/s', 'm3/s', None, None), ('2018', 'flow_ls', 'discharge', 'l/s', 'm3/s', None, None)]
```

These are two **catalogue candidates**, not two observed discharge records. The locations
catalogue does not list per-variable availability. Finding 246 stations therefore does not
establish 246 available series for each quantity, or prove that station `2018` supplies both
discharge fields. Returned fields provide evidence for the requested window, not an exhaustive
historical inventory.

The example above selects `flow`. To select the other candidate:

```python
flow_ls = rr.pick(selection, variant="flow_ls")

print(rr.series(flow).select("variant").rows())
print(rr.series(flow_ls).select("variant").rows())
```

Output:

```text
[('flow',)]
[('flow_ls',)]
```

This only narrows the selection; it does not retrieve `flow_ls` observations or promise that
they exist at this station.

RivRetrieve does not yet know the averaging period of these fields, so frequency and statistic
appear as `None`. Existenz updates its feed every ten minutes. FOEN describes its measurements
as usually five- or ten-minute averages, occasionally two-minute averages. However, we have not
established which averaging period applies to each Existenz field.

FOEN also labels exported values at the beginning of the measurement interval. RivRetrieve has
not established whether that convention applies to each Existenz field. It does not calculate
daily means from these values.

## Recent and older values

Existenz.ch's REST API serves the last 32 days; older values are available through its
InfluxDB archive. To retrieve observations, RivRetrieve requests a slightly wider period than
the dates supplied, then removes values outside the requested dates. It uses REST when that
wider period stays within the last 32 days. Otherwise, it uses the archive. A request near the
32-day cutoff can therefore use the archive even when the supplied dates are more recent.

Neither route requires you to supply personal credentials. Archive access uses Existenz.ch's
published shared read-only credential, supplied internally by RivRetrieve. If the publisher
rotates it, RivRetrieve needs an update. The January 2024 example above reads the archive.
Availability still depends on what the intermediary has retained for the station and field.

## Data status

FOEN's conditions for downloading **current measurements** describe them as provisional:

> Da es sich bei den Messdaten um provisorische Daten handelt, sind Abweichungen gegenüber den
> definitiven Daten nicht auszuschliessen.

In English, unofficially: because the measurements are provisional data, differences from the
final data cannot be ruled out. This statement about current measurements does not establish
the validation status of every value retained in Existenz.ch's archive. RivRetrieve does not
assign a quality judgement to the archived values.

## Time

For this intermediary route, returned `time` values are UTC wall-clock labels accompanied by
`time_zone="+00:00"`. Read those columns together: the datetime column itself is timezone-naive.
This describes Existenz.ch's timestamps, not every FOEN product or export. In particular,
FOEN's FAQ describes historical agency data in year-round winter time (UTC+1), while current
raw data and forecasts use local time with seasonal offsets.

## Terms

**FOEN, the data owner.** Its
[general conditions for obtaining, downloading and using current hydrological raw data and forecasts](https://www.bafu.admin.ch/dam/en/sd-web/5NAitqNKub6m/allgemeine_bedingungenfuerdasherunterladenaktuellerhydrologische.pdf)
(16 September 2019), section 8, state:

> Der Leistungsbezüger darf die Daten zu kommerziellen und nicht kommerziellen Zwecken verwenden.
> Die Angabe der Quelle wird empfohlen.

In English, unofficially: the user may use the data for commercial and non-commercial purposes;
citing the source is recommended. The same conditions ask users not to download more often
than every ten minutes.

FOEN's [terms of use and source citation](https://www.hydrodaten.admin.ch/en/questions#faq-7)
put it in English:

> Data can be used freely; we recommend citing the source.

They suggest this citation for surface-water data:

> Hydrology Division, Federal Office for the Environment FOEN (reference date).

**Existenz.ch, the route RivRetrieve reads.** The service states public and non-commercial use,
asks for FOEN credit and a link, and gives no availability guarantee. It also asks callers to
identify their application for statistics; RivRetrieve sends its name on REST requests.
These service conditions are separate from FOEN's data-use terms. Check both before using the
data; RivRetrieve does not resolve their legal effect for your use.

## Sources

| Page | Checked |
|---|---|
| [Existenz.ch Data APIs](https://api.existenz.ch/) | 2026-09-20 |
| [Existenz.ch hydrology parameters](https://api.existenz.ch/apiv1/hydro/parameters) | 2026-09-20 |
| [hydrodaten.admin.ch](https://www.hydrodaten.admin.ch/en) | 2026-09-20 |
| [FOEN — Frequently asked questions](https://www.hydrodaten.admin.ch/en/questions) | 2026-09-20 |
| [BAFU — Allgemeine Bedingungen für das Herunterladen aktueller hydrologischer Daten](https://www.bafu.admin.ch/dam/en/sd-web/5NAitqNKub6m/allgemeine_bedingungenfuerdasherunterladenaktuellerhydrologische.pdf) | 2026-09-20 |

The station count comes from the packaged catalogue. The example output was retrieved on
2026-09-20.
