# Switzerland — FOEN, through Existenz.ch

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `ch_foen` |
| Country | Switzerland |
| Data owner | Bundesamt für Umwelt / Federal Office for the Environment (BAFU/FOEN) |
| Read from | `api.existenz.ch` and its InfluxDB archive, an unofficial third-party service |
| Variables | Discharge, stage, water temperature |
| Stations in the catalogue | 246 |
| Credentials | None |
| Terms | BAFU: data can be used freely, citation recommended; Existenz.ch: public and non-commercial use |
| Agency documentation | [hydrodaten.admin.ch](https://www.hydrodaten.admin.ch/en), [Existenz.ch API](https://api.existenz.ch/) |

```python
import rivretrieve as rr

selection = rr.find(provider="ch_foen", product="discharge_reported")
selection = rr.pick(selection, station="2018")
result = rr.fetch(selection, start="2024-01-01", end="2024-01-31")
```

## Who measures, and who publishes

The measurements are BAFU's: the Federal Office for the Environment runs Switzerland's
hydrological network and publishes current values on
[hydrodaten.admin.ch](https://www.hydrodaten.admin.ch/en).

RivRetrieve does not read BAFU directly. It reads **Existenz.ch**, a service built by Christian
Studer (Bureau für digitale Existenz) that republishes BAFU's hydrology data through an API, with
a long-term archive in InfluxDB. This is the only provider in RivRetrieve that goes through a
third party, and it is worth knowing for three reasons.

**It is unofficial.** Existenz.ch says so itself:

> These APIs are unofficial. There is no guarantee of availability or top performance. They are
> actively monitored though.

**It states a non-commercial condition of its own**, separate from anything BAFU says:

> These APIs with weather and water data for Switzerland are free for public and non-commercial
> use, lovingly handcrafted by Christian Studer (Bureau für digitale Existenz). […] Additional
> licencing restrictions may apply by the original data owner (For example MeteoSwiss or the
> BAFU).

**It asks for credit to BAFU.** Existenz.ch states, for its BAFU hydrology API:

> BAFU data needs to be credited and linked to the BAFU.

BAFU's own terms differ from the route's (see [Terms](#terms)): they allow commercial use. If Existenz.ch's conditions do not suit your work, take the data from BAFU
instead. RivRetrieve does not decide that for you.

## What you can retrieve

| Product | Source field | Unit | Stations |
|---|---|---|---:|
| `discharge_reported` | `flow` | m³/s | 246 |
| `stage_reported` | `height_abs`, `height` | m | 246 |
| `water_temperature_reported` | `temperature` | °C | 246 |

The products are named `_reported` because the source states no aggregation: it publishes a value
at a time, without saying whether it is an instantaneous reading or a mean over some interval. The
catalogue therefore records frequency, statistic and period as `unknown`, and RivRetrieve does not
invent a daily mean from them.

Existenz.ch documents a periodicity of 10 minutes for the BAFU hydrology feed.

Availability is `unknown` for every station and product: nothing in the source states which of the
three a given station serves.

## Recent and older values

Existenz.ch's time-series API serves date ranges up to 32 days back; older values live in its
InfluxDB archive. RivRetrieve reads both.

## Data status

BAFU's terms describe the current measurements as provisional:

> Da es sich bei den Messdaten um provisorische Daten handelt, sind Abweichungen gegenüber den
> definitiven Daten nicht auszuschliessen.

In English, unofficially: because the measurements are provisional data, differences from the
definitive data cannot be ruled out.

## Time

Values come back with `time_zone` `+00:00`. The source publishes UTC timestamps and RivRetrieve
keeps them.

## Terms

Two layers apply, and they differ.

**BAFU, the data owner.** Its
[general conditions for downloading current hydrological data](https://www.bafu.admin.ch/dam/en/sd-web/5NAitqNKub6m/allgemeine_bedingungenfuerdasherunterladenaktuellerhydrologische.pdf) (16 September 2019),
section 8, state:

> Der Leistungsbezüger darf die Daten zu kommerziellen und nicht kommerziellen Zwecken verwenden.
> Die Angabe der Quelle wird empfohlen.

In English, unofficially: the user may use the data for commercial and non-commercial purposes;
citing the source is recommended. The same conditions ask users not to download more often than
every 10 minutes.

BAFU's [terms of use and source citation](https://www.hydrodaten.admin.ch/en/questions#faq-7) put it in English:

> Data can be used freely; we recommend citing the source.

and suggest the citation for surface-water data:

> Hydrology Division, Federal Office for the Environment FOEN (reference date).

Replace *reference date* with the date you retrieved the data.

**Existenz.ch, the route RivRetrieve reads.** Public and non-commercial use, unofficial, with no
guarantee of availability, and it asks that BAFU data be credited and linked to BAFU. It also asks
callers to identify themselves for statistics, by adding an application name to requests.

So BAFU allows commercial use and recommends attribution, while the route states non-commercial
use and asks for attribution. RivRetrieve records both and does not decide which governs your use.

## Sources

| Page | Retrieved |
|---|---|
| [Existenz.ch Data APIs](https://api.existenz.ch/) | 2026-09-19 |
| [hydrodaten.admin.ch](https://www.hydrodaten.admin.ch/en) | 2026-09-19 |
| [FOEN — Terms of use and source citation](https://www.hydrodaten.admin.ch/en/questions#faq-7) | 2026-09-19 |
| [BAFU — Allgemeine Bedingungen für das Herunterladen aktueller hydrologischer Daten](https://www.bafu.admin.ch/dam/en/sd-web/5NAitqNKub6m/allgemeine_bedingungenfuerdasherunterladenaktuellerhydrologische.pdf) | 2026-09-19 |

Station counts come from the packaged catalogue.
