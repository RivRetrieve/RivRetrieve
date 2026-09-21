# France: Hub'Eau and HydroPortail

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Providers | `fr_hubeau` (Hub'Eau), `fr_hydroportail` (HydroPortail) |
| Country | Hydrometry: metropolitan and overseas France; temperature: metropolitan France |
| Published by | Hub'Eau (`hubeau.eaufrance.fr`) and HydroPortail (`hydro.eaufrance.fr`) |
| Variables | Discharge, stage, water temperature |
| Stations in the catalogue | Hub'Eau: 7,347 (6,475 hydrometry and 872 temperature); HydroPortail: 6,409. Availability depends on quantity and period |
| Credentials | None |
| Licence stated by Hub'Eau | Licence ouverte Etalab |
| Agency documentation | [Hub'Eau hydrometry API](https://hubeau.eaufrance.fr/page/api-hydrometrie), [Hub'Eau river temperature API](https://hubeau.eaufrance.fr/page/api-temperature-continu), [HydroPortail help](https://hydro.eaufrance.fr/aide/accueil) |

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

The request returned seven daily values and no issues (the empty tuple `()`).
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

Two services publish the hydrometric data used here:

- **[Hub'Eau](https://hubeau.eaufrance.fr/)** provides open APIs for French water data.
  It is a collaboration between the French biodiversity agency (OFB) and BRGM,
  the French geological survey.
- **[HydroPortail](https://hydro.eaufrance.fr/)** is the national hydrometry portal,
  published by the Service Central Vigicrues. It replaced the former Banque HYDRO
  interfaces in January 2022.

RivRetrieve reads published daily discharge and stage from Hub'Eau's hydrometry API,
and instantaneous stage and discharge from HydroPortail. Water temperature follows a
separate route: Hub'Eau's river-temperature API distributes records from Naïades for
metropolitan France. It is not part of the PHyC hydrometric network.

Neither service's name identifies the original producer of every measurement. This
matters when citing a dataset (see [Terms and citation](#terms-and-citation)).

## What you can retrieve

Select `provider="fr_hubeau"` for Hub'Eau daily hydrometry and temperature.
Select `provider="fr_hydroportail"` for HydroPortail station-own instantaneous records.
The two services retain separate station inventories, source identities and terms.


| Data | Source field | Returned unit |
|---|---|---|
| Daily mean discharge | Hub'Eau `QmnJ` | m³/s |
| Daily maximum discharge | Hub'Eau `QIXnJ` | m³/s |
| Daily maximum stage | Hub'Eau `HIXnJ` | m |
| Instantaneous discharge | HydroPortail `Q` | m³/s |
| Instantaneous stage | HydroPortail `H` | m |
| Water temperature | Hub'Eau `resultat`, parameter `1301` | °C |

RivRetrieve converts discharge from litres per second to cubic metres per second, and stage from millimetres to metres.
Temperature is already in °C. The daily maxima are maxima of instantaneous values,
not maxima of daily means. RivRetrieve does not calculate additional daily statistics
from instantaneous records.

A station being listed does not guarantee that it has data for every quantity or requested period.
Hub'Eau describes daily hydrometric records reaching back to 1900 at some stations.
Historical instantaneous records are also available through HydroPortail, but their
length varies by station.

## Stations and sites

A **site** is a reach of river where discharge measurements are considered homogeneous
and comparable. A **station** is a measuring installation within that site. It can
provide stage, discharge, or both.

One site can hold several stations. HydroPortail states that at most one is active
at a time for producing the site's discharge. RivRetrieve retrieves the selected
station's own record, rather than the site's combined discharge record.

Temperature comes from a separate monitoring network. Do not assume that a station selected for discharge also provides temperature.

## Time

The example's `time` column contains daily dates represented at midnight. Its
`time_zone="unknown"` means that RivRetrieve has not established the clock defining
the start and end of those days. Hub'Eau describes its hydrometric dates as UTC,
but that statement alone does not establish which 24 hours a daily value covers.

For instantaneous values retrieved from HydroPortail, `time` contains UTC clock labels
and `time_zone` is `+00:00`. Read the two columns together: the datetime column itself
does not carry a time zone.

Temperature observations have separate source date and clock fields. Their time zone
is also `unknown`. RivRetrieve has not established whether each value represents an
instant or an interval, or what sampling or averaging period applies.

## Data status

HydroPortail instantaneous discharge and stage expose four source selections:
`raw`, `validated`, `pre_validated_and_validated`, and `most_valid`.
Use `rr.pick(selection, variant="validated")` to request one selection. Without an
explicit selection, retrieval requests all four and keeps their identities separate.
`most_valid` is HydroPortail's selection, not a RivRetrieve ranking or fallback.
The combined selector is not pre-validated-only. Corrected-only and
pre-validated-only histories are not available through this public route.

HydroPortail's [glossary](https://hydro.eaufrance.fr/glossaire) explains its processing
statuses. Requested selectors and each observation's processing status are separate
source facts. Receipts preserve the native metadata. An empty response for one
selector does not establish that another selector or another window is empty.

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

These Hub'Eau terms apply to the Hub'Eau route. HydroPortail provides public access,
but its legal and FAQ pages do not specify the same licence or a standard citation
for station records. Check the applicable terms before reusing those records.
Neither retrieval route requires personal credentials in RivRetrieve.

## Sources

| Page | Checked |
|---|---|
| [Hub'Eau — API Hydrométrie](https://hubeau.eaufrance.fr/page/api-hydrometrie) | 2026-09-20 |
| [Hub'Eau — API Température des cours d'eau](https://hubeau.eaufrance.fr/page/api-temperature-continu) | 2026-09-20 |
| [Hub'Eau — Conditions générales d'utilisation](https://hubeau.eaufrance.fr/page/conditions-generales) | 2026-09-20 |
| [Hub'Eau — Mentions légales / Crédits](https://hubeau.eaufrance.fr/mentions-legales-credits) | 2026-09-20 |
| [Licence Ouverte 2.0](https://www.data.gouv.fr/pages/legal/licences/etalab-2.0) | 2026-09-20 |
| [HydroPortail — Mentions légales](https://hydro.eaufrance.fr/edito/mentions-legales) | 2026-09-20 |
| [HydroPortail — À propos](https://hydro.eaufrance.fr/edito/a-propos-dhydroportail) | 2026-09-20 |
| [HydroPortail — Glossaire](https://hydro.eaufrance.fr/glossaire) | 2026-09-20 |
| [HydroPortail — La station hydrométrique](https://hydro.eaufrance.fr/aide/la-station-hydrometrique) | 2026-09-20 |
| [HydroPortail — Le site hydrométrique](https://hydro.eaufrance.fr/aide/le-site-hydrometrique) | 2026-09-20 |
| [HydroPortail — Les séries de mesures](https://hydro.eaufrance.fr/aide/les-series-de-mesures) | 2026-09-20 |
| [HydroPortail — FAQ](https://hydro.eaufrance.fr/faq) | 2026-09-20 |

The station count describes the packaged catalogue. The example observations were
retrieved on 2026-09-20.
