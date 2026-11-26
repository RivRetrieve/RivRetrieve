# Germany: PEGELONLINE

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `de_pegelonline` |
| Country | Germany |
| Published by | Wasserstraßen- und Schifffahrtsverwaltung des Bundes (WSV) / Generaldirektion Wasserstraßen und Schifffahrt (GDWS), via PEGELONLINE |
| Read from | PEGELONLINE REST API v2 (`pegelonline.wsv.de`) |
| Quantities | Discharge, stage, water temperature |
| Stations in the catalogue | 787. Availability depends on station and quantity |
| Station metadata | Station name and water-body name. See [Fields by provider](../station-metadata.md#fields-by-provider) |
| Credentials | None |
| Licence stated by PEGELONLINE | [Datenlizenz Deutschland – Zero – Version 2.0](https://www.govdata.de/dl-de/zero-2-0) (`DL-DE->Zero-2.0`) |
| Agency documentation | [PEGELONLINE overview](https://www.pegelonline.wsv.de/webservice/ueberblick), [REST API v2 guide](https://www.pegelonline.wsv.de/webservice/guideRestapi) |

Retrieve three days of discharge at station `616dd98e-816d-4e17-b8cd-57b163dbc8a2`,
HOFKIRCHEN on the Donau:

```python
import rivretrieve as rr

selection = rr.find(
    provider="de_pegelonline",
    station="616dd98e-816d-4e17-b8cd-57b163dbc8a2",
    quantity="discharge",
)

result = rr.fetch(selection, start="2026-11-24", end="2026-11-26", cache="bypass")

preview = result.data.select("time", "time_zone", "value", "unit").head(3)
print(preview.write_csv(), end="")

print(result.data.height)
print([(issue.severity, issue.code) for issue in result.issues])
```

Output:

```text
time,time_zone,value,unit
2026-11-24T00:00:00.000000,+01:00,504.0,m3/s
2026-11-24T00:15:00.000000,+01:00,504.0,m3/s
2026-11-24T00:30:00.000000,+01:00,504.0,m3/s
221
[('info', 'provenance.citation_not_established')]
```

The request returned 221 fifteen-minute readings in m³/s over the three days;
the preview shows the first three. The informational issue
`provenance.citation_not_established` means the packaged provider catalogue has
no configured citation. It does not mean retrieval failed. `cache="bypass"`
requests the PEGELONLINE API rather than a local cache. This output was checked
on 2026-11-26. A window that includes the current day can show more rows on a
later run, as new readings keep publishing; a later retrieval need not
reproduce this output exactly.
See [Usage](../usage.md) for general selection and result handling.

## Who measures, and who publishes

The regional Wasserstraßen- und Schifffahrtsämter (WSAs) of the WSV operate the
gauges along Germany's federal waterways (the Rhine, Elbe, Danube, Weser, Ems,
Mosel and others), supervised by GDWS in Bonn. PEGELONLINE, hosted by ITZBund
and developed by EES GmbH, is WSV/GDWS's near-real-time publication platform for
this network.

PEGELONLINE also mirrors a modest number of gauges it does not itself operate: a
handful of German institutions outside WSV, and a few gauges from neighboring
countries' own agencies along cross-border stretches of the Rhine and Danube.
Licensing does not vary by origin: PEGELONLINE's terms state one licence,
`DL-DE->Zero-2.0`, over everything the site redistributes, with no exception
for this mirrored data. The field that would identify which agency actually
operates a given station is not currently exposed through RivRetrieve, so you
cannot distinguish a WSV gauge from a mirrored one through the API itself. The
[provider research record](https://github.com/RivRetrieve/RivRetrieve/issues/874)
has the full station-level breakdown.

## What you can retrieve

| Quantity filter | Source field / `variant` | Frequency | Statistic | Source unit | Returned unit |
|---|---|---|---|---|---|
| `discharge` | `Q` | Unknown | Unknown | m³/s | m³/s |
| `stage` | `W` | Unknown | Unknown | cm, m+NN, or m+PNP | m |
| `water_temperature` | `WT` | Unknown | Unknown | °C | °C |
| `stage` | `TRM` | Unknown | Unknown | cm | m |
| `water_temperature` | `TRM_WT` | Unknown | Unknown | °C | °C |

These source fields identify the published timeseries; there is no separate
`variant` to choose for de_pegelonline's products. `TRM` and `TRM_WT` are their
own products, not a `variant` of `W`/`WT`: PEGELONLINE never publishes a regular
reporting interval for them, so RivRetrieve leaves their frequency
`not_established` regardless of the equidistant intervals the Catalogue
otherwise reports as `Unknown`. `Frequency` and `Statistic` are `Unknown` for
every row because actual reporting intervals vary by station and PEGELONLINE
does not state a statistic for any of these series.

`W` and `TRM` publish stage in one of three native units, and RivRetrieve keeps
each distinct:

- `cm`: relative to the station's own gauge zero (*Pegelnullpunkt*).
  RivRetrieve converts to metres (÷ 100).
- `m+NN`: already in metres, an absolute elevation above sea level
  (*Normalnull*). RivRetrieve does not rescale it.
- `m+PNP`: already in metres, but still relative to the station's own gauge
  zero, not sea level. RivRetrieve does not rescale it.

`source_unit` keeps the published native unit, so you can tell these apart even
after conversion. A label such as "metres" does not by itself say which of
these a value is relative to; check `source_unit` rather than assuming. The
gauge's own vertical-datum text, when PEGELONLINE publishes one, is retained as
source evidence rather than repeated here for every station.

## How far back, and how recent

PEGELONLINE's REST API v2 serves a rolling window of roughly the last 31 days;
there is no longer historical archive behind this route. A request for dates
older than that window returns `HTTP 200` with an empty result, not a failure —
this reflects the rolling retention, not a dry riverbed or an inactive station.
Check [issues](../usage.md#issues) before interpreting an empty result as
anything else.

## Terms and citation

PEGELONLINE's terms page states:

> Informationen, Produkte oder Dienste, die Sie von dieser Website erhalten,
> dürfen übernommen werden. Dies geschieht auf der Grundlage der Lizenz
> DL-DE->Zero-2.0

In English, unofficially: information, products or services you receive from
this website may be reused, under the licence `DL-DE->Zero-2.0`. [Datenlizenz
Deutschland – Zero – Version 2.0](https://www.govdata.de/dl-de/zero-2-0)
permits unrestricted commercial and non-commercial use, modification and
redistribution, without mandatory attribution.

PEGELONLINE gives no formatted citation. Name WSV/GDWS and PEGELONLINE as the
source, and retain the station, quantity, requested period and access date to
make the retrieved record traceable. This is practical guidance, not a
PEGELONLINE citation template.

## Sources

Publisher pages checked on 2026-11-26:

- [PEGELONLINE overview](https://www.pegelonline.wsv.de/webservice/ueberblick): publisher, network and service description.
- [REST API v2 guide](https://www.pegelonline.wsv.de/webservice/guideRestapi): request shape, fields and the rolling retention window.
- [PEGELONLINE terms of use](https://pegelonline.wsv.de/gast/nutzungsbedingungen): licence and mirrored third-party data.
- [Datenlizenz Deutschland – Zero – Version 2.0](https://www.govdata.de/dl-de/zero-2-0): the licence's own terms.

The station count describes the packaged catalogue. The example was retrieved
live on 2026-11-26. The [private verification archive](https://github.com/RivRetrieve/verification-evidence#readme)
and the [provider research record](https://github.com/RivRetrieve/RivRetrieve/issues/874)
retain commands, source checks, exact output and the limits of these checks.
