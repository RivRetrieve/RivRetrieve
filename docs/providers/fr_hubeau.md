# France: Hub'Eau and HydroPortail

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `fr_hubeau` |
| Country | Hydrometry: metropolitan and overseas France; temperature: metropolitan France |
| Published by | Hub'Eau (`hubeau.eaufrance.fr`) and HydroPortail (`hydro.eaufrance.fr`) |
| Variables | Discharge, stage, water temperature |
| Stations in the catalogue | 7,323 locations; availability depends on quantity and period |
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
Source values can change, so a later retrieval need not reproduce this output exactly.

Run the examples below in the same Python session.

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

Select series by physical properties, using `quantity`, `frequency` and `statistic`.
The table gives the established filters and the source fields behind them. A dash means
the fact is unknown; leave that filter unset.

| Quantity | Frequency | Statistic | Source field | Returned unit |
|---|---|---|---|---|
| `discharge` | `daily` | `mean` | Hub'Eau `QmnJ` | m³/s |
| `discharge` | `daily` | `max` | Hub'Eau `QIXnJ` | m³/s |
| `stage` | `daily` | `max` | Hub'Eau `HIXnJ` | m |
| `discharge` | — | `instantaneous` | HydroPortail `Q` | m³/s |
| `stage` | — | `instantaneous` | HydroPortail `H` | m |
| `temperature` | — | — | Hub'Eau `resultat`, parameter `1301` | °C |

Discharge arrives in litres per second and stage in millimetres. RivRetrieve divides
both by 1,000 to return m³/s and m. HydroPortail's discharge unit code is `l`, which
its unit dictionary defines as l/s; it does not mean a volume in litres here.
Temperature is already in °C and appears with returned unit code `degC`.
The daily maxima are maxima of instantaneous values, not maxima of daily means.
No stage datum is established by these conversions.

Inspect the daily discharge candidates at the example station and select the maximum:

```python
daily = rr.find(
    provider="fr_hubeau",
    station="Y251002001",
    quantity="discharge",
    frequency="daily",
)

candidates = rr.series(daily).select("quantity", "frequency", "statistic", "unit")
print(candidates.sort("statistic").rows())

daily_max = rr.pick(daily, statistic="max")
print(rr.series(daily_max).select("statistic").rows())
```

Output:

```text
[('discharge', 'daily', 'max', 'm3/s'), ('discharge', 'daily', 'mean', 'm3/s')]
[('max',)]
```

`find` reads the packaged catalogue without contacting the observation service.
`pick` narrows that selection. This example does not retrieve daily maxima.
RivRetrieve provides the three published daily products above; it does not calculate
other daily statistics from instantaneous records.

### Catalogue candidates and observed availability

| Quantity and statistic | Positive catalogue evidence | Stations listed |
|---|---:|---:|
| Daily mean discharge | 4,942 | 6,454 |
| Daily maximum discharge | 4,206 | 6,454 |
| Daily maximum stage | 5,266 | 6,454 |
| Instantaneous discharge | 2,462 | 6,454 |
| Instantaneous stage | 3,221 | 6,454 |
| Reported water temperature | 869 | 869 |

These counts describe the packaged catalogue, not current availability. Positive evidence
means a positive publisher observation count or an exact historical witness at acquisition.
A positive count alone does not establish non-null numerical values. Instantaneous evidence
includes Hub'Eau's recent observation counts and selected historical HydroPortail checks;
it is not a complete survey of historical HydroPortail records.

The remaining candidates have availability `unknown` and remain selectable. Their evidence
includes empty responses, failed checks and unchecked history. These are different reasons
for uncertainty, not proof that a station never measured the quantity. The acquisitions
were made on different dates. None of the counts establishes continuous records or values
in a particular requested period.

Hub'Eau describes daily hydrometric records reaching back to 1900, but this is a service-wide
historical extent, not a start date for every station. Historical instantaneous access through
HydroPortail also depends on the station and period. The catalogue does not establish
per-series record start and end dates.

## Stations and sites

France distinguishes two things, and the difference matters when you select discharge:

- A **site** is a reach of river where discharge measurements are considered homogeneous and
  comparable. It carries discharge only.
- A **station** is the equipment at one point of that reach. It belongs to one site and measures
  stage, discharge, or both.

One site can hold several stations. HydroPortail states that at most one is active at a time, and
that it is the one producing the site's discharge. Station codes and site codes therefore identify different things.

RivRetrieve selects **station** records. It does not replace a station's discharge with
its site's discharge, or expose the site's station-activation calendar. Use the complete
station identifier rather than deriving a site code from it.

The packaged catalogue contains 869 temperature stations and 6,454 hydrometric stations,
with no shared station identifiers. Temperature candidates belong only to the former;
the five hydrometric candidates belong only to the latter. This describes the packaged
snapshot, not every possible overlap between French monitoring networks.

## Time

Read `time` and `time_zone` together. The datetime column itself is timezone-naive.
Instantaneous HydroPortail values have UTC wall-clock labels and `time_zone="+00:00"`.
Daily values and water temperature have `time_zone="unknown"`.

Hub'Eau's hydrometry documentation states that dates are UTC. However, RivRetrieve has
not established the clock defining the beginning and end of the day represented by each
daily value. It retains daily calendar labels at midnight without assigning a time zone
or assuming a 24-hour support window from that label alone.

Temperature observations carry separate source date and clock fields. RivRetrieve has
not established their zone, frequency, statistic, or whether a value represents an instant
or an interval. It preserves those unknowns rather than deriving them from the spacing
between returned timestamps.

Retrieve historical instantaneous stage from the station's HydroPortail record:

```python
stage = rr.find(
    provider="fr_hubeau",
    station="Y251002001",
    quantity="stage",
    statistic="instantaneous",
    variant="raw",
)

instantaneous = rr.fetch(
    stage,
    start="2020-01-01",
    end="2020-01-02",
    cache="bypass",
    receipts=True,
)

preview = instantaneous.data.select("time", "time_zone", "value", "unit").head(3)
print(preview.write_csv(float_precision=3), end="")

print(rr.series(instantaneous).select("published_id").rows())
print(instantaneous.data.height)
print(instantaneous.issues)
```

Output:

```text
time,time_zone,value,unit
2020-01-01T00:00:00.000000,+00:00,0.347,m
2020-01-01T00:05:00.000000,+00:00,0.345,m
2020-01-01T00:10:00.000000,+00:00,0.343,m
[('raw',)]
576
()
```

The first timestamps are five minutes apart, but the selection does not promise a fixed
sampling frequency or a complete record. This request returned 576 rows and no issues.
`receipts=True` keeps the source response bytes in `instantaneous.receipts`, including
source fields that do not appear in the observation table.

A null `value` is a published missing measurement. An absent row is no observation at
that label. A failed source request is reported through `issues`; it is not an empty
successful record. Check issues alongside the returned data.

## Data status

RivRetrieve requests HydroPortail's `raw` series and verifies that the response identifies
that status. The source identifier appears as `published_id="raw"` in `rr.series(instantaneous)`.
The `variant="raw"` filter accepts this published identifier. Corrected, pre-validated and
validated series are not alternative selections supported by this route. Per-observation
status, quality, method and continuity fields remain in the optional source receipts;
they are not added as columns to the observation table or interpreted as quality judgements.
The same distinction applies to source quality fields in Hub'Eau responses.

HydroPortail uses the following source vocabulary. Its
[glossary](https://hydro.eaufrance.fr/glossaire) defines the four (translations are ours; the
French text is authoritative):

| Status | HydroPortail's definition and unofficial English translation |
|---|---|
| *Donnée brute* | “Statut d'une série de mesures issue des capteurs ou d'un concentrateur, et n’ayant subi aucune correction ni critique.” A series from sensors or a data logger, without correction or review. |
| *Donnée corrigée* | “Statut d'une série de mesures pour laquelle la donnée brute a subi une correction, essentiellement par un prévisionniste et en temps quasi réel, par exemple pour les besoins de la modélisation (élimination d’une valeur aberrante du jeu de données via le Superviseur).” Raw data corrected, mainly by a forecaster in near real time, for example for modelling by removing an outlier through the Superviseur tool. |
| *Donnée pré-validée* | “Statut d'une série de mesure, où la donnée brute (ou éventuellement corrigée), a fait l'objet d’une première étape de critique. Elle est expertisée quotidiennement, hebdomadairement ou mensuellement suivant les services.” Raw or corrected data after an initial review, examined daily, weekly or monthly depending on the service. |
| *Donnée validée* | “Statut d'une série de mesures où la donnée brute (ou éventuellement corrigée), voire la donnée pré-validée, a fait l'objet d’une critique approfondie. Généralement, elle est expertisée annuellement par les services.” Raw, corrected or pre-validated data after a thorough review, generally examined annually by the services. |

An empty raw-series response does not establish that every other status is empty.
RivRetrieve does not substitute another status automatically.

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

No ready-made citation string was identified in the checked Hub'Eau terms. Hub'Eau
distributes data produced by actors in the French water information system, who remain
responsible for those data. Identify the dataset author rather than assuming the API
operator produced every observation. The terms' description of supplied “raw data”
is separate from HydroPortail's sensor-validation status *Donnée brute*.

These Hub'Eau terms govern the Hub'Eau route. HydroPortail's checked legal and FAQ pages
establish public access but do not establish the same licence or a standard citation
for its station-series route. Check the applicable source terms before reusing those
records. Neither retrieval route requires personal credentials in RivRetrieve.

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

Station and availability counts describe the packaged catalogue. Example observations
were retrieved on 2026-09-20.
