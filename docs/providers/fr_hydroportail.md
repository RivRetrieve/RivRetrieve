# France: HydroPortail

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `fr_hydroportail` |
| Country | Metropolitan and overseas France |
| Published by | HydroPortail (`hydro.eaufrance.fr`), Service Central Vigicrues |
| Variables | Instantaneous discharge and stage |
| Stations in the catalogue | 6,409. Availability depends on quantity, source selection and period |
| Credentials | None |
| Terms | Reuse licence and standard citation not established |
| Agency documentation | [HydroPortail help](https://hydro.eaufrance.fr/aide/accueil) |

Retrieve instantaneous discharge at station `Y251002001`, L'Orb à Bédarieux,
selecting HydroPortail's validated records:

```python
import rivretrieve as rr

selection = rr.find(
    provider="fr_hydroportail",
    station="Y251002001",
    quantity="discharge",
    statistic="instantaneous",
)
validated = rr.pick(selection, variant="validated")

result = rr.fetch(validated, start="2020-01-01", end="2020-01-02", cache="bypass")

preview = result.data.select("time", "time_zone", "value", "unit").head(3)
print(preview.write_csv(float_precision=3), end="")

print(result.data.height)
print([(issue.severity, issue.code) for issue in result.issues])
```

Output:

```text
time,time_zone,value,unit
2020-01-01T00:01:00.000000,+00:00,13.500,m3/s
2020-01-01T00:20:00.000000,+00:00,13.300,m3/s
2020-01-01T00:55:00.000000,+00:00,13.700,m3/s
50
[('info', 'provenance.license_not_established'), ('info', 'provenance.citation_not_established')]
```

The preview shows the first three instantaneous values in m³/s, rounded to three
decimal places. The request returned 50 rows. Their timestamps need not be evenly
spaced; RivRetrieve does not fill gaps or calculate daily means. Bare dates include
the whole first and last day. `cache="bypass"` requests the source rather than a local
cache. Source values can change, so a later retrieval need not reproduce this output
exactly.

The two informational issues mean that RivRetrieve has not established a reuse
licence or standard citation for these records. They do not mean that the observation
request failed. See [Terms and citation](#terms-and-citation) before reusing the data.

Run the examples below in the same Python session. See [Usage](../usage.md) for
general selection options and working with returned data.

## Who measures, and who publishes

France's hydrometric records bring together measurements from regional environmental
authorities (DREAL) and other national and local producers. The Service Central Vigicrues
runs the national hydrometry platform, PHyC. Records cover metropolitan France and overseas
territories; availability and record length vary by station.

**[HydroPortail](https://hydro.eaufrance.fr/)** is the national hydrometry portal,
published by the Service Central Vigicrues. It replaced the former Banque HYDRO
interfaces in January 2022. Its name does not identify the original producer of
every historical measurement.

RivRetrieve reads station-own instantaneous stage and discharge from HydroPortail.
Published daily hydrometry and Naïades water temperature are available through the
separate [Hub'Eau provider](fr_hubeau.md). The services retain separate station
inventories, source identities and terms. Temperature comes from a separate
monitoring network.

## What you can retrieve

| Quantity filter | Source field / `variant` | Source unit | Returned unit |
|---|---|---|---|
| `discharge` | `Q`; four selectors below | l/s | m³/s |
| `stage` | `H`; four selectors below | mm | m |

Both quantities are instantaneous. Each source field supports the same four
`variant` selectors: `raw`, `validated`, `pre_validated_and_validated`, and
`most_valid`. Choose a selector as shown below.

RivRetrieve converts discharge from litres per second to cubic metres per second,
and stage from millimetres to metres. It does not calculate additional daily
statistics from instantaneous records.

A station being listed does not guarantee that it has data for every quantity,
source selection or requested period. Historical instantaneous records are available,
but their length varies by station. A successful short request does not establish
continuous coverage of the station's history.

## Stations and sites

A **site** is a reach of river where discharge measurements are considered homogeneous
and comparable. A **station** is a measuring installation within that site. It can
provide stage, discharge, or both.

One site can hold several stations. HydroPortail states that at most one is active
at a time for producing the site's discharge. RivRetrieve retrieves the selected
station's own record, rather than the site's combined discharge record.

## Time

For instantaneous values retrieved from HydroPortail, `time` contains UTC clock labels
and `time_zone` is `+00:00`. Read the two columns together: the datetime column itself
does not carry a time zone.

## Data status and source selections

HydroPortail exposes four source selections through `variant`:

| Selector | Requested source selection |
|---|---|
| `raw` | Raw records |
| `validated` | Validated records |
| `pre_validated_and_validated` | Pre-validated and validated records together |
| `most_valid` | HydroPortail's most-valid selection |

Inspect the catalogue candidates before choosing:

```python
print(sorted(rr.series(selection)["variant"].to_list()))
print(rr.series(validated).select("station_id", "variant").rows())
```

Output:

```text
['most_valid', 'pre_validated_and_validated', 'raw', 'validated']
[('Y251002001', 'validated')]
```

Use `pick` to choose a selector, then `fetch` to retrieve its observations.
For example, request HydroPortail's most-valid selection:

```python
most_valid = rr.pick(selection, variant="most_valid")

most_valid_result = rr.fetch(
    most_valid, start="2020-01-01", end="2020-01-02", cache="bypass"
)

print(rr.series(most_valid_result).select("station_id", "variant").rows())
print(most_valid_result.data.height)
print([(issue.severity, issue.code) for issue in most_valid_result.issues])
```

Output:

```text
[('Y251002001', 'most_valid')]
50
[('info', 'provenance.license_not_established'), ('info', 'provenance.citation_not_established')]
```

Fetching `selection` without `pick` requests all four selectors and keeps their
records separate. Availability can differ by selector and period. An explicit
choice requests only that selector; RivRetrieve does not substitute another one
when no observations are returned.

`most_valid` is HydroPortail's selection, not a RivRetrieve quality ranking.
Its exact selection algorithm has not been established. The combined selector
includes pre-validated and validated records. This public route does not provide
corrected-only or pre-validated-only histories.

The selector chooses which records HydroPortail returns. Individual observations
can also carry processing-status metadata supplied by HydroPortail. Its
[glossary](https://hydro.eaufrance.fr/glossaire) explains the status vocabulary. See [Usage](../usage.md#series-inspection-and-result-views) to
interpret series outcomes and issues, and [optional receipts](../usage.md#receipts-optional)
to inspect the source metadata.

## Terms and citation

HydroPortail provides public access without personal credentials in RivRetrieve.
Its legal and FAQ pages do not establish a reuse licence or standard citation for
station records. Hub'Eau's Etalab terms apply to the Hub'Eau route and must not be
assumed to cover HydroPortail retrievals.

Publication by HydroPortail does not establish the original author of every
historical measurement. RivRetrieve reports the unknown licence and citation as
informational issues, including when observations are returned successfully.
Check the applicable terms and attribution with the publisher before reusing
these records.

## Sources

| Page | Checked |
|---|---|
| [HydroPortail — Mentions légales](https://hydro.eaufrance.fr/edito/mentions-legales) | 2026-09-21 |
| [HydroPortail — À propos](https://hydro.eaufrance.fr/edito/a-propos-dhydroportail) | 2026-09-21 |
| [HydroPortail — Glossaire](https://hydro.eaufrance.fr/glossaire) | 2026-09-21 |
| [HydroPortail — La station hydrométrique](https://hydro.eaufrance.fr/aide/la-station-hydrometrique) | 2026-09-21 |
| [HydroPortail — Le site hydrométrique](https://hydro.eaufrance.fr/aide/le-site-hydrometrique) | 2026-09-21 |
| [HydroPortail — Les séries de mesures](https://hydro.eaufrance.fr/aide/les-series-de-mesures) | 2026-09-21 |
| [HydroPortail — Séries de mesures, station Y251002001](https://hydro.eaufrance.fr/stationhydro/Y251002001/series) | 2026-09-21 |
| [HydroPortail — FAQ](https://hydro.eaufrance.fr/faq) | 2026-09-21 |

The station count describes the packaged catalogue. The example observations were
retrieved on 2026-09-21.
