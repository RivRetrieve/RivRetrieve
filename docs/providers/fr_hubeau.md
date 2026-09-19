# France — Hub'Eau and HydroPortail

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `fr_hubeau` |
| Country | France, metropolitan and overseas |
| Published by | Hub'Eau (`hubeau.eaufrance.fr`) and HydroPortail (`hydro.eaufrance.fr`) |
| Variables | Discharge, stage, water temperature |
| Stations in the catalogue | 7,323 |
| Credentials | None |
| Licence stated by Hub'Eau | Licence ouverte Etalab |

```python
import rivretrieve as rr

selection = rr.find(provider="fr_hubeau", product="discharge_daily_mean")
selection = rr.pick(selection, station="Y251002001")  # L'Orb à Bédarieux
result = rr.fetch(selection, start="2024-01-01", end="2024-12-31")
```

## Who measures, and who publishes

Rivers in France are measured by different national and local authorities. The measurements are
gathered on a national platform run by the Service Central Vigicrues, and published through two
services:

- **[Hub'Eau](https://hubeau.eaufrance.fr/)**, a platform of open APIs for French water data;
- **[HydroPortail](https://hydro.eaufrance.fr/)**, the national hydrometry portal, published by the
  Service Central Vigicrues, which replaced the former Banque HYDRO interfaces in January 2022.

RivRetrieve reads daily discharge and stage, and water temperature, from Hub'Eau, and
instantaneous stage and discharge from HydroPortail.

## What you can retrieve

| Product | Agency code | Unit | Stations with data | Stations listed |
|---|---|---|---:|---:|
| `discharge_daily_mean` | `QmnJ` | m³/s | 4,942 | 6,454 |
| `discharge_daily_max` | `QIXnJ` | m³/s | 4,206 | 6,454 |
| `stage_daily_max` | `HIXnJ` | m | 5,266 | 6,454 |
| `discharge_instantaneous` | `Q` | m³/s | 2,462 | 6,454 |
| `stage_instantaneous` | `H` | m | 3,221 | 6,454 |
| `water_temperature_reported` | `temperature` | °C | 869 | 869 |

Hub'Eau publishes stage in millimetres and discharge in litres per second; RivRetrieve converts
both. "Stations with data" is what RivRetrieve established when it built the catalogue; the rest
are listed with availability `unknown`, and remain selectable.

Daily values go back to 1900 at some stations. For instantaneous stage and discharge, how far back
the record reaches varies by station.

## Stations and sites

France distinguishes two things, and the difference matters when you select discharge:

- A **site** is a reach of river where discharge measurements are considered homogeneous and
  comparable. It carries discharge only.
- A **station** is the equipment at one point of that reach. It belongs to one site and measures
  stage, discharge, or both.

One site can hold several stations. HydroPortail states that at most one is active at a time, and
that it is the one producing the site's discharge; its activation table records which station
supplied the data when. Station codes and site codes therefore identify different things.

Water temperature is a separate network: 869 stations, no overlap with the 6,454 hydrometric ones,
and none of the hydrometric products apply to them.

## Time

Instantaneous values come back with `time_zone` `+00:00`: HydroPortail publishes UTC. Daily values
and water temperature come back with `time_zone` `unknown`. Hub'Eau states that its dates are UTC,
but it does not say which clock defines the start and end of the day a daily value covers, so
RivRetrieve does not fill one in. For water temperature the service also does not say whether a
value is an instant or an interval, which the catalogue records as `unknown` as well.

## Data status

HydroPortail gives each series a status and RivRetrieve passes it through. Its
[glossary](https://hydro.eaufrance.fr/glossaire) defines the four (translations are ours; the
French text is authoritative):

| Status | HydroPortail's definition |
|---|---|
| *Donnée brute* | "Statut d'une série de mesures issue des capteurs ou d'un concentrateur, et n'ayant subi aucune correction ni critique." — status of a series of measurements from the sensors or a data logger, having undergone no correction or review. |
| *Donnée corrigée* | "Statut d'une série de mesures pour laquelle la donnée brute a subi une correction, essentiellement par un prévisionniste et en temps quasi réel." — status of a series whose raw data has been corrected, mainly by a forecaster and in near real time. |
| *Donnée pré-validée* | "…la donnée brute (ou éventuellement corrigée), a fait l'objet d'une première étape de critique. Elle est expertisée quotidiennement, hebdomadairement ou mensuellement suivant les services." — the raw (or corrected) data has had a first review stage, examined daily, weekly or monthly depending on the service. |
| *Donnée validée* | "…a fait l'objet d'une critique approfondie. Généralement, elle est expertisée annuellement par les services." — has had a thorough review, generally examined annually by the services. |

## Terms and citation

Hub'Eau's terms of use, section 5.1.3, state:

> La réutilisation des Jeux de données est régie par la licence ouverte Etalab,
> https://www.etalab.gouv.fr/licence-ouverte-open-licence. Les Jeux de données sont donc librement
> et gratuitement utilisables et réutilisables, y compris dans un but commercial. L'utilisateur de
> ces données doit néanmoins veiller à citer l'auteur des Jeux de données.

In short: reuse is governed by the Etalab open licence, including commercially, and you are asked
to cite the author of the datasets. Hub'Eau publishes no ready-made citation string. It describes
itself as distributing raw data produced by the actors of the French water information system, who
remain responsible for it.

## Sources

| Page | Retrieved |
|---|---|
| [Hub'Eau — API Hydrométrie](https://hubeau.eaufrance.fr/page/api-hydrometrie) | 2026-09-15 |
| [Hub'Eau — API Température des cours d'eau](https://hubeau.eaufrance.fr/page/api-temperature-continu) | 2026-09-15 |
| [Hub'Eau — Conditions générales d'utilisation](https://hubeau.eaufrance.fr/page/conditions-generales) | 2026-09-15 |
| [Hub'Eau — Mentions légales / Crédits](https://hubeau.eaufrance.fr/mentions-legales-credits) | 2026-09-15 |
| [HydroPortail — Mentions légales](https://hydro.eaufrance.fr/edito/mentions-legales) | 2026-09-15 |
| [HydroPortail — À propos](https://hydro.eaufrance.fr/edito/a-propos-dhydroportail) | 2026-09-15 |
| [HydroPortail — Glossaire](https://hydro.eaufrance.fr/glossaire) | 2026-09-15 |
| [HydroPortail — La station hydrométrique](https://hydro.eaufrance.fr/aide/la-station-hydrometrique) | 2026-09-11 |
| [Sandre — Station hydrométrique (HYD 2.3)](https://www.sandre.eaufrance.fr/definition/HYD/2.3/StationHydro) | 2026-09-11 |

Station counts come from the packaged catalogue, checked against the sources on 2026-09-12 and
2026-09-13.
