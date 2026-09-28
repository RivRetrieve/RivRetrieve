# CHMI source research

Independent authoritative-source check on 2026-09-28 (UTC). All source HTTP responses were 200. HTTP GETs used Python requests; PDFs were extracted with `pdftotext -layout`. Source quotations below retain the evidence used for page claims. They do not establish current observation availability. The implementation check also fetched the principal sources with the commands in [README](README.md).

## Institutional roles

Source: https://www.chmi.cz/o-chmu.

- “Český hydrometeorologický ústav (ČHMÚ) jako příspěvková organizace Ministerstva životního prostředí vykonává funkci ústředního státního ústavu České republiky pro obory kvalita ovzduší, hydrologie, jakost vody, klimatologie a meteorologie”. Unofficial translation: CHMI, an organisation funded by the Ministry of the Environment, serves as the Czech central state institute for air quality, hydrology, water quality, climatology and meteorology.
- “Zřizuje a provozuje státní monitorovací a pozorovací sítě pro sledování kvantitativního a kvalitativního stavu atmosféry a hydrosféry.” Translation: it establishes and operates state monitoring and observation networks to monitor the quantitative and qualitative state of the atmosphere and hydrosphere.
- “Odborně zpracovává výsledky pozorování, měření a monitorování.” Translation: it professionally processes observation, measurement and monitoring results.
- “Vytváří a spravuje databáze o vodě, klimatu, ovzduší aj.” Translation: it creates and manages databases on water, climate, air and other subjects.

These explicit duties support identifying CHMI as the state hydrological monitoring-network operator, rather than inferring measurement responsibility from its name. They do NOT prove CHMI alone measures every published station, that there are no external observers/operators, or that every gauge measures every offered quantity. Recommended scope: CHMI operates state hydrological monitoring networks, processes the measurements and publishes hydrological open data.

## Publisher, access and terms

Source: https://www.chmi.cz/o-chmu/produkty-a-sluzby/data-a-vyhodnoceni. This is stronger direct open-data evidence than applying a generic website footer alone.

- “Národní databáze hydrometeorologických údajů a produktů je dostupná na https://opendata.chmi.cz.” Translation: the National Database of Hydrometeorological Data and Products is available at that address.
- “Otevřená data ČHMÚ můžete využívat bezplatně při respektování licence Creative Commons BY 4.0.” Translation: CHMI open data may be used free of charge subject to Creative Commons BY 4.0.

Source: https://www.chmi.cz/vylou%C4%8Den%C3%AD-odpov%C4%9Bdnosti.

- “Produkty Českého hydrometeorologického ústavu dostupné na těchto webových stránkách podléhají licenci Creative Commons 4.0 CC-BY. Dílo smíte sdílet a upravovat za podmínky uvedení původu (zdroje ČHMÚ).” Translation: CHMI products available on these websites are subject to CC BY 4.0; the work may be shared and adapted provided its origin (source ČHMÚ) is credited.
- Links to https://creativecommons.org/licenses/by/4.0/deed.cs . Link to the licence rather than reducing all its requirements to credit alone.
- Disclaimer rejects legal responsibility for possible damage resulting from actual weather and subsequent use of products or information. No need to copy this into a short provider page if linking full terms.

Directory listings, PDFs and metadata were fetched without credentials. No evidence of a special formatted dataset citation was found in these inspected sources. Do NOT turn that bounded finding into “CHMI publishes no formatted citation”. A suggested attribution can identify ČHMÚ, historical hydrology data, source URL and CC BY 4.0, and state conversions/changes where appropriate; do not present a suggestion as CHMI's mandated citation.

## Historical definitions and source units

Source: https://opendata.chmi.cz/hydrology/read_me/Popis_datovych_sad_historical.pdf.

- `daily`, `H_WIGOSID_DQ_RRRR.json`: “průměrné denní hodnoty (vodní stavy, průtoky, teploty vody, plaveniny)”, HD/QD/TD/PD. Translation: mean daily values (water levels, discharges, water temperatures, suspended sediment).
- `hourly`, `H_WIGOSID_HQ_RRRR.json`: “průměrné hodinové hodnoty (vodní stavy, průtoky)”, HH/QH. Translation: mean hourly values (water levels and discharges).
- “RRRR v názvu datové sady označuje kalendářní rok”: RRRR in the dataset name denotes calendar year.

Source: https://opendata.chmi.cz/hydrology/historical/metadata/meta2.json.

| Code | Published Czech name | Meaning | Source unit |
|---|---|---|---|
| HD | Průměrné denní vodní stavy | Daily mean stage | cm |
| QD | Průměrné denní průtoky | Daily mean discharge | m3/s |
| TD | Průměrné denní teploty vody | Daily mean water temperature | °C |
| HH | Průměrné hodinové vodní stavy | Hourly mean stage | cm |
| QH | Průměrné hodinové průtoky | Hourly mean discharge | m3/s |

Metadata carries `datumVytvoreni=2025-02-13T08:10:01Z`; that is the metadata's creation timestamp, not a newly verified data observation time. Returned metres require implementation verification, distinct from source centimetres.

Source: https://opendata.chmi.cz/hydrology/read_me/Popis_kodu_historical.pdf. It defines `objID` as “WIGOS identifikátor objektu v databázi WMO” (object WIGOS identifier in WMO database). It does not explain averaging windows.

## Time, status and coverage limits

None of the historical dataset description, code description or meta2 defines daily averaging boundaries or hourly label anchoring. Do not infer midnight-to-midnight UTC days or preceding/following hours from UTC labels. UTC in `datumVytvoreni` does not establish observation time semantics. The implementation owner's public-API retrieval/source inspection must establish the actual returned UTC labels; this report does not independently verify them from observations. No historical revision/finality guarantee was established from these documents. Do not call the values final or quality-controlled solely because they are historical.

Live directory indexes:
- https://opendata.chmi.cz/hydrology/ distinguishes historical, now and recent among other folders.
- https://opendata.chmi.cz/hydrology/historical/data/daily/.
- https://opendata.chmi.cz/hydrology/historical/data/hourly/.

Both daily and hourly filename listings have latest year 2025, and no 2026 filename, on the check date. This supports a dated description of listed annual files, NOT a fixed implementation cutoff, complete 2025 coverage, or observation availability for a specific station/quantity/date. Avoid an exhaustive unsupported-product table: the historical PDF includes additional publications, but only daily/hourly products are in the implementation scope.

## Scope of the independent check

This source research was separate from the public-API example. The main
[verification record](README.md) reports that example and recorded tests.
The historical hydrology guide PDF yielded only title text during extraction
and was not used for claims. No overall historical revision or finality guarantee
was established. No station-specific earliest year or complete national coverage
was established.
