# Finland: Syke

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `fi_syke` |
| Country | Finland |
| Published by | Suomen ympäristökeskus (Syke), the Finnish Environment Institute |
| Read from | Syke's Hydrologiarajapinta OData hydrology interface (`rajapinnat.ymparisto.fi`) |
| Quantities | Daily discharge, stage and surface water temperature |
| Stations in the catalogue | 2,543. Availability depends on quantity |
| Station metadata | Station name and water-body name. See [Fields by provider](../station-metadata.md#fields-by-provider) |
| Credentials | None |
| Licence stated by Syke | Creative Commons Attribution 4.0 (CC BY 4.0) |
| Agency documentation | [Syke open data and web services](https://www.syke.fi/en-US/Open_information/Open_web_services) |

RivRetrieve reads Syke's Hydrologiarajapinta OData service. Retrieve one week of
published daily discharge at station `894`, Ruskeakoski on the Jänisjoki:

```python
import rivretrieve as rr

selection = rr.find(
    provider="fi_syke",
    station="894",
    quantity="discharge",
)

result = rr.fetch(selection, start="2020-01-01", end="2020-01-07", cache="bypass")

preview = result.data.select("time", "time_zone", "value", "unit").head(3)
print(preview.write_csv(), end="")

print(result.data.height)
print(result.issues)
```

Output:

```text
time,time_zone,value,unit
2020-01-01T00:00:00.000000,unknown,16.73,m3/s
2020-01-02T00:00:00.000000,unknown,17.79,m3/s
2020-01-03T00:00:00.000000,unknown,19.02,m3/s
7
()
```

The request returned seven daily values in m³/s, one for each date from January 1
to 7. The preview shows the first three. The empty tuple `()` means retrieval
reported no issues; it does not establish the quality of the values. Syke's
service does not state whether a daily value is a mean, an instantaneous
reading, or something else, so `time_zone` is `unknown` and the request did not
restrict by `statistic` or `frequency`.

`cache="bypass"` requests Syke's service rather than a local cache. This output
was checked live on 2026-11-08. Published values can change, so a later
retrieval need not reproduce this output exactly. See [Usage](../usage.md) for
general selection and result handling.

## Who measures, and who publishes

Syke operates Finland's national hydrology API and publishes station and
observation data through it. Some of the stations in the catalogue are
measured by Syke directly; others are measured by regional ELY-centres
(Centres for Economic Development, Transport and the Environment) or other
bodies that report into Syke's systems. The API does not publish an operator
field per station, so RivRetrieve cannot state who measures a particular
station; it publishes what Syke publishes.

Station identifiers are Syke's own per-installation site identifier
(`Paikka_Id`), confirmed against Syke's public map service and against the
independently published CAMELS-FI dataset, both of which key on the same
identifier. A station publishes at most one of the three admitted quantities:
a river gauge with both discharge and stage readings appears as two separate
stations in the catalogue, one per quantity, not one station with two
available products.

## What you can retrieve

| Quantity filter | Source field / `variant` | Frequency | Statistic | Source unit | Returned unit |
|---|---|---|---|---|---|
| `discharge` | Virtaama | Daily | Unknown | m³/s | m³/s |
| `stage` | Vedenkorkeus | Daily | Unknown | cm | m |
| `temperature` | LampoPintavesi | Daily | Unknown | °C | °C |

RivRetrieve converts stage from centimetres to metres. Discharge and water
temperature need no unit conversion. Syke's own documentation never states
whether a published daily value is a mean, an instantaneous reading, or
something else, so RivRetrieve leaves frequency and statistic unknown rather
than guessing from the roughly daily spacing of the values.

Stage is an absolute water-surface elevation relative to a Finnish national
height datum, not a small reading relative to a local gauge zero: published
stage values range from about -2 m to +245 m, consistent with Finland's
coast-to-inland relief. Which of Finland's several historical national height
systems (such as N2000 or N60) a given station's own reading is expressed in
has not been established.

The catalogue lists each station under exactly one of these three quantities,
because the source itself associates one quantity with each station
identifier. A station being listed does not guarantee data for every
requested period.

## How far back, and how recent

Coverage varies by station. The example station, `894`, has published
discharge back to January 1, 1959. Some stations hold decades of history;
others have shorter or more recent records. RivRetrieve reads whatever range
Syke currently publishes for a station; there is no fixed earliest or latest
date imposed by RivRetrieve. Checked live on 2026-11-08, several active
stations had daily values published within the preceding one to two days.

A request for a period with no published observation returns no rows for
that period rather than an issue. It does not establish that the station
never had data in that period.

## Time and data status

Syke's timestamps carry no time zone marker, and the agency's documentation
does not state one. RivRetrieve returns the published wall-clock label in
`time` paired with `time_zone="unknown"`. Do not assume these timestamps are
UTC, Finnish local time, or any other specific zone.

Some discharge and stage readings carry one of Syke's own flag codes
(`Lippu`), covering a mix of meanings: data-quality notes (for example,
interpolated or reduced values), statistical summaries, and model-simulated
values. RivRetrieve reports a non-null flag as an `info`-severity
`source.flag_code` issue alongside the value; it does not drop the value or
rank one flag above another. Surface water temperature carries no flag field
at all.

Some older discharge and stage readings also carry a published minimum and
maximum alongside the daily value; current readings do not. RivRetrieve does
not return these minimum and maximum fields, since Syke does not state what
they represent.

A published null remains a row with `value=null`. A date without a published
observation supplies no row. A failed request remains an issue alongside any
successful records. Check [issues](../usage.md#issues) before interpreting an
empty result.

## Terms and citation

Syke's [open-data terms](https://www.syke.fi/en/environmental-data/use-license-and-responsibilities)
state:

> Open data distributed by the Finnish Environment Institute (Syke) is
> licenced under Creative Commons Attribution 4.0 International licence. The
> data covered by the license can be freely used in any way, provided that
> the source of the data is mentioned: the name of the licensor and the name
> of the data.

Syke's worked example of attribution reads "Source: Finnish Environment
Institute (Syke)". Retrieval requires no personal credentials.

## Sources

Publisher pages checked on 2026-11-07 and 2026-11-08:

- [Syke open data and web services](https://www.syke.fi/en-US/Open_information/Open_web_services): the Hydrologiarajapinta OData interface.
- [Syke open-data use license and responsibilities](https://www.syke.fi/en/environmental-data/use-license-and-responsibilities): licence and attribution.
- Syke's public map service (`paikkatiedot.ymparisto.fi`): independent confirmation of `Paikka_Id` as the per-station identifier.
- Seppä et al. (2026), CAMELS-FI, *Earth System Science Data* 18, 4745–4769 (`doi:10.5194/essd-18-4745-2026`): independent confirmation of station identity and a hydrological cross-check (10-station sample, Q4 2023, matching to the exact published decimal).

The station count describes the packaged catalogue. The example was retrieved
live on 2026-11-08. The [private verification archive](https://github.com/RivRetrieve/verification-evidence#readme)
retains commands, source checks, exact output and limitations.
