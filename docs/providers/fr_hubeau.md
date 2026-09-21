# France: Hub'Eau

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `fr_hubeau` |
| Country | Hydrometry: metropolitan and overseas France; temperature: metropolitan France |
| Published by | Hub'Eau (`hubeau.eaufrance.fr`) |
| Variables | Discharge, stage, water temperature |
| Stations in the catalogue | 7,347 (6,475 hydrometry and 872 temperature). Availability depends on quantity and period |
| Credentials | None |
| Licence stated by Hub'Eau | Licence ouverte Etalab |
| Agency documentation | [Hub'Eau hydrometry API](https://hubeau.eaufrance.fr/page/api-hydrometrie), [Hub'Eau river temperature API](https://hubeau.eaufrance.fr/page/api-temperature-continu) |

Retrieve published daily mean discharge at station `Y251002001`, L'Orb à Bédarieux:

```python
import rivretrieve as rr

selection = rr.find(
    provider="fr_hubeau",
    station="Y251002001",
    quantity="discharge",
    frequency="daily",
    statistic="mean",
)

result = rr.fetch(selection, start="2024-01-01", end="2024-01-07", cache="bypass")

preview = result.data.select("time", "time_zone", "value", "unit").head(3)
print(preview.write_csv(float_precision=3), end="")

print(result.data.height)
print(result.issues)
```

Output:

```text
time,time_zone,value,unit
2024-01-01T00:00:00.000000,unknown,1.159,m3/s
2024-01-02T00:00:00.000000,unknown,1.144,m3/s
2024-01-03T00:00:00.000000,unknown,1.159,m3/s
7
()
```

The request returned seven daily values and no retrieval issues (the empty tuple `()`).
An empty issue tuple does not mean the source has approved the quality of the values.
The values are source-published daily means, returned in m³/s. RivRetrieve does not
calculate them from instantaneous observations. Bare dates include the whole first
and last day. `cache="bypass"` requests the source rather than a local cache.
The preview shows the first three values, rounded to three decimal places. `unknown`
means RivRetrieve has not established the time zone of these daily labels. Source values
can change, so a later retrieval need not reproduce this output exactly.
See [Usage](../usage.md) for selection options and working with returned data.

## Who measures, and who publishes

France's hydrometric records bring together measurements from regional environmental
authorities (DREAL) and other national and local producers. The Service Central Vigicrues
runs the national hydrometry platform, PHyC. Records cover metropolitan France and overseas
territories; availability and record length vary by station.

**[Hub'Eau](https://hubeau.eaufrance.fr/)** provides open APIs for French water data.
It is a collaboration between the French biodiversity agency (OFB) and BRGM,
the French geological survey.

RivRetrieve reads published daily discharge and stage from Hub'Eau's hydrometry API.
Water temperature follows a separate route: Hub'Eau's river-temperature API distributes
records from Naïades for metropolitan France. It is not part of the PHyC hydrometric network.

Hub'Eau's name does not identify the original producer of every measurement. This
matters when citing a dataset (see [Terms and citation](#terms-and-citation)).

## What you can retrieve

Select `provider="fr_hubeau"` for daily hydrometry and temperature.
For station-own instantaneous discharge and stage, use the separate
[HydroPortail provider](fr_hydroportail.md). The services retain separate station
inventories, source identities and terms.

| Quantity filter | Source field / `variant` | Published statistic | Source unit | Returned unit |
|---|---|---|---|---|
| `discharge` | `QmnJ` | Daily mean | l/s | m³/s |
| `discharge` | `QIXnJ` | Daily maximum | l/s | m³/s |
| `stage` | `HIXnJ` | Daily maximum | mm | m |
| `temperature` | `resultat`, parameter `1301` | Not established | °C | °C |

These source fields identify the published observations; there is no separate
`variant` to choose for these Hub'Eau products.

RivRetrieve converts discharge from litres per second to cubic metres per second, and stage from millimetres to metres.
Temperature is already in °C. The daily maxima are maxima of instantaneous values,
not maxima of daily means. RivRetrieve does not calculate additional daily statistics
from instantaneous records.

A station being listed does not guarantee that it has data for every quantity or requested period.
Hub'Eau describes daily hydrometric records reaching back to 1900 at some stations.

## Stations and sites

A **site** is a reach of river where discharge measurements are considered homogeneous
and comparable. A **station** is a measuring installation within that site. It can
provide stage, discharge, or both.

One site can hold several stations. Keep the station identifier when selecting
observations; a site and a station are different source identities.

Temperature comes from a separate monitoring network. Do not assume that a station selected for discharge also provides temperature.

## Time

The example's `time` column contains daily dates represented at midnight. Its
`time_zone="unknown"` means that RivRetrieve has not established the clock defining
the start and end of those days. Hub'Eau describes its hydrometric dates as UTC,
but that statement alone does not establish which 24 hours a daily value covers.

Temperature observations have separate source date and clock fields. Their time zone
is also `unknown`. RivRetrieve has not established whether each value represents an
instant or an interval, or what sampling or averaging period applies.

## Data status

The source publishes qualification and method metadata alongside hydrometric values.
RivRetrieve does not turn those fields into a quality ranking or add observation
quality flags to the returned table. A returned value alone does not establish
its validation status. See [Usage](../usage.md#receipts-optional) to retain source
material when that metadata matters to the analysis.

## Terms and citation

Hub'Eau's terms of use, section 5.1.3, state:

> La réutilisation des Jeux de données est régie par la licence ouverte Etalab,
> https://www.etalab.gouv.fr/licence-ouverte-open-licence. Les Jeux de données sont donc librement
> et gratuitement utilisables et réutilisables, y compris dans un but commercial. L'utilisateur de
> ces données doit néanmoins veiller à citer l'auteur des Jeux de données.

In English, unofficially: reuse is governed by the Etalab open licence, including
commercial reuse, and requires citation of the dataset author. The linked
[Licence Ouverte 2.0](https://www.data.gouv.fr/pages/legal/licences/etalab-2.0) requires
the source (at least the licensor) and the last-update date of the reused information.
A retrieval date does not necessarily establish that last-update date.

Hub'Eau distributes data from several producers. Cite the dataset author rather than
assuming the API operator produced every observation. No ready-made citation string
was identified in its terms.

These terms apply to the Hub'Eau route. They do not establish the terms of the
separate HydroPortail service. Hub'Eau retrieval requires no personal credentials
in RivRetrieve.

## Sources

| Page | Checked |
|---|---|
| [Hub'Eau — API Hydrométrie](https://hubeau.eaufrance.fr/page/api-hydrometrie) | 2026-09-21 |
| [Hub'Eau — API Température des cours d'eau](https://hubeau.eaufrance.fr/page/api-temperature-continu) | 2026-09-21 |
| [Hub'Eau — Conditions générales d'utilisation](https://hubeau.eaufrance.fr/page/conditions-generales) | 2026-09-21 |
| [Hub'Eau — Mentions légales / Crédits](https://hubeau.eaufrance.fr/mentions-legales-credits) | 2026-09-21 |
| [Licence Ouverte 2.0](https://www.data.gouv.fr/pages/legal/licences/etalab-2.0) | 2026-09-21 |
| [HydroPortail — La station hydrométrique](https://hydro.eaufrance.fr/aide/la-station-hydrometrique) | 2026-09-21 |
| [HydroPortail — Le site hydrométrique](https://hydro.eaufrance.fr/aide/le-site-hydrometrique) | 2026-09-21 |

The station count describes the packaged catalogue. The example observations were
retrieved on 2026-09-21.
