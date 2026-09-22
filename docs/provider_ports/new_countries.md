# New Countries: Research and Porting Guide

Status as of **2026-09-22**.

This file gathers everything learned so far about river-gauge sources that RivRetrieve does not
serve yet. It covers what is implemented and what is still missing. It gives each candidate
source with its endpoints and the result of a real download, and lists the sources that cannot be
used and why. It ends with the steps for turning a candidate into a RivRetrieve provider.

The research was done in four rounds:

| Date | Round | Compared against |
|---|---|---|
| 2026-07-29 to 2026-08-11 | CSFS connectors, South America sweep, Russia and Ukraine | [DarriEy/CSFS](https://github.com/DarriEy/CSFS/tree/main/src/csfs/connectors) (81 connector files) |
| 2026-09-21 | Coverage audit | [kratzert/RivRetrieve-Python](https://github.com/kratzert/RivRetrieve-Python) `main` and its pull requests, checked live |
| 2026-09-22 | hydrodownloadR comparison | [bafg-bund/hydrodownloadR](https://github.com/bafg-bund/hydrodownloadR/tree/main/R) (38 adapters, BfG's R package) |
| 2026-09-22 | Africa and Asia download tests | A preliminary web sweep of African and Asian sources dated 2026-09-21 (`rivretrieve-provider-candidates-africa-asia.md`). Every source in it with a public route was tested for a real download |

Each finding keeps the date on which it was observed. Services change, so re-run the test request
in a candidate's section before starting a port.

---

## 1. How candidates are judged

A source is a candidate only if a real download of observed values succeeded during the research.
Beyond that, it must pass four gates:

1. **Provenance.** The national or regional authority that runs the gauges publishes the data
   itself. Data mirrored by a university, a research project or an aggregator fails this gate.
2. **Retrievable observations.** Real gauge values can be fetched by a program, without a login,
   a CAPTCHA, or a form asking for personal details.
3. **Observed data.** The values are in-situ discharge or stage. Modelled or simulated output, such
   as GEOGLOWS, fails this gate.
4. **Coordinates.** A station list with coordinates exists, either from the same source or from a
   sibling source of the same authority.

The length of the available record is not a gate. A source that serves only a rolling window of a
few days or months, or only the latest value, is still a candidate. The limitation is documented
for users, as `ba_fhmzbih` already does for its rolling window of about one year.

The verdicts used below are:

| Verdict | Meaning |
|---|---|
| **Ready** | Passes all gates through a stable, structured interface (API, static files, open-data portal) |
| **Limited** | Passes the gates, but with a documented limitation: short or rolling record, HTML scraping, stage only, sparse data, or a missing coordinate source |
| **Blocked** | Fails a gate for a reason other than record length |

---

## 2. What RivRetrieve already covers

### 2.1 Implemented in this repository

Fourteen providers on `main`, covering thirteen countries.

| Country | Provider ID | Agency | Provider kind |
|---|---|---|---|
| Bosnia and Herzegovina | `ba_fhmzbih` | AVP Sava | LiveStages |
| Brazil | `br_ana` | ANA | LiveStages |
| Canada | `ca_eccc` | Environment and Climate Change Canada | BulkStore |
| Czechia | `cz_chmi` | CHMI | LiveStages |
| France | `fr_hubeau` | Hub'Eau | LiveStages |
| France | `fr_hydroportail` | HydroPortail | LiveStages |
| Japan | `jp_mlit` | MLIT | LiveStages |
| Lithuania | `lt_lhmt` | LHMT | LiveStages |
| Norway | `no_nve` | NVE | LiveStages |
| Poland | `pl_imgw` | IMGW-PIB | BulkStore |
| Switzerland | `ch_foen` | FOEN, through Existenz.ch | LiveStages |
| Thailand | `th_thaiwater` | ThaiWater | LiveStages |
| United States | `usgs_nwis` | USGS | LiveStages |
| South Africa | `za_dws` | DWS | CatalogueOnly (no observations yet) |

### 2.2 In the legacy repository, not yet ported

These sources already have working fetchers in `kratzert/RivRetrieve-Python`. Porting them means
rewriting a known fetcher for the current architecture, which is a separate task from researching
new countries.

Fetchers merged on legacy `main`:

| Country or region | Legacy fetcher | Notes |
|---|---|---|
| Australia | `australia.py` | |
| Chile | `chile.py` | DGA / CR2. The source may need fixes when ported; the specifics are not yet pinned down |
| Germany, Berlin | `germany_berlin.py` | |
| Portugal | `portugal.py` | |
| Slovenia | `slovenia.py` | |
| Spain | `spain.py` | MITECO anuario and `sig.mapama.gob.es` ROAN service |
| United Kingdom, EA | `uk_ea.py` | `environment.data.gov.uk/hydrology`. Instantaneous discharge was added in legacy PR #105 |
| United Kingdom, NRFA | `uk_nrfa.py` | |

South Africa observations are also outstanding: `za_dws` has the catalogue only.

Open legacy pull requests:

| Country or region | Legacy PR |
|---|---|
| Argentina | [#90](https://github.com/kratzert/RivRetrieve-Python/pull/90) |
| Belgium, Flanders | [#94](https://github.com/kratzert/RivRetrieve-Python/pull/94) |
| Belgium, Wallonia | [#100](https://github.com/kratzert/RivRetrieve-Python/pull/100) |
| Denmark | [#88](https://github.com/kratzert/RivRetrieve-Python/pull/88) |
| Estonia | [#113](https://github.com/kratzert/RivRetrieve-Python/pull/113) |
| Finland | [#112](https://github.com/kratzert/RivRetrieve-Python/pull/112) |
| Greece, OHI | [#107](https://github.com/kratzert/RivRetrieve-Python/pull/107) |
| Ireland, OPW | [#96](https://github.com/kratzert/RivRetrieve-Python/pull/96) |
| Italy, Tuscany | [#102](https://github.com/kratzert/RivRetrieve-Python/pull/102) |
| Netherlands | [#98](https://github.com/kratzert/RivRetrieve-Python/pull/98) |
| Scotland, SEPA | [#108](https://github.com/kratzert/RivRetrieve-Python/pull/108) |
| South Korea | [#80](https://github.com/kratzert/RivRetrieve-Python/pull/80) |
| Sweden | [#111](https://github.com/kratzert/RivRetrieve-Python/pull/111) |
| Taiwan | [#115](https://github.com/kratzert/RivRetrieve-Python/pull/115) |

Austria ([#84](https://github.com/kratzert/RivRetrieve-Python/pull/84)) was closed without merging
on 2026-09-04. Its fetcher code is still in the PR.

### 2.3 Other packages that were compared

- **hydrodownloadR** (`bafg-bund/hydrodownloadR`, last push 2026-09-14). Of its 38 adapters, four
  cover countries that neither repository had considered: Afghanistan, Israel, Mexico and Rwanda.
  Two gave working discharge routes for candidates we already had: Colombia and Peru. Its other
  adapters duplicate coverage we already have:
  - `ES_ROAN` and `ES_CEDEX` use the same MITECO sources as legacy `spain.py`.
  - `UK_CEH` uses the same `environment.data.gov.uk/hydrology` API as legacy `uk_ea.py`.
  - `CH_BAFU_NAWA` serves water quality, not discharge.
  - The rest are implemented here or exist in the legacy repository.
  - Commented-out entries (`BO_SENAMHI`, Argentina SNIH, DanubeHIS) are not active.
  - hydrodownloadR's `provider_usage.R` holds its own licence label for every adapter. Those labels
    are quoted below as hydrodownloadR's classification and have not been checked by us.
- **Africa and Asia sweep** (2026-09-21, a list of about 90 sources with links but no downloads).
  Every listed source that has a public route was tested on 2026-09-22.
  - Eighteen gave a real download. They are in section 3, some as additions to countries we
    already had.
  - The rest are listed briefly in section 6.4 with the reason no download was made.
  - Its Taiwan WRA and South Korea WAMIS entries are already covered by legacy PRs #115 and #80.
    Its Israel and Rwanda entries were already covered by the hydrodownloadR round.

---

## 3. Candidate overview

"Tested" is the date of the latest successful download of real values. Every row was re-tested on
2026-09-22 against several stations. Section 3.1 lists what was downloaded and what the tests
changed.

| Country or region | Proposed ID | Source and mechanism | Variables | Record seen | Stations | Coordinates | Verdict | Tested |
|---|---|---|---|---|---|---|---|---|
| Mexico | `mx_conagua` | CONAGUA SIH, one static CSV per station (host screens clients, see 5.1) | Daily Q and stage | 1922 to 2026-09 | 1,189 listed; 1,172 files | WGS84 | Ready | 2026-09-22 |
| Israel | `il_iwa` | Water Authority, data.gov.il CKAN API | Daily mean Q, daily volume | 1943 to 2024-09 | 458 listed; 185 with discharge | Israeli TM Grid, reproject | Ready | 2026-09-22 |
| Colombia | `co_ideam` | IDEAM AQUARIUS WebPortal (Q, stage); datos.gov.co Socrata (hourly stage) | Daily Q, daily stage, hourly stage | 1973 to 2026, varies by station | 982 locations with a daily-Q dataset (some empty); 393 with hourly stage | WGS84 | Ready | 2026-09-22 |
| New Zealand | `nz_hilltop` | Regional councils, Hilltop protocol | Q at 5 min | Up to decades; varies by council and site | 604 flow sites on 8 councils | NZTM or NZMG, reproject (Otago: 19 of 67) | Ready | 2026-09-22 |
| Germany, NRW | `de_nrw` | LANUV open data, decade CSV-in-ZIP | Q, event-based | 1910 to 2026 | 281 | UTM32N, reproject | Ready | 2026-09-22 |
| Germany, federal waterways | `de_pegelonline` | WSV PEGELONLINE REST API | Q at 15 min | Rolling 31 days | 786 (94 with Q) | WGS84 (729) | Ready, short window | 2026-09-22 |
| Germany, Bavaria | `de_bayern` | GKD HTML table pages | Q at 15 min | Arbitrary ranges, 2005 checked | 611 | UTM32N, reproject | Limited (scraping) | 2026-09-22 |
| Peru | `pe_senamhi` | SENAMHI WFS plus hydrological chart endpoint | Daily Q and stage | Hydrological year 2019/20 to present | 139 (95 with Q) | WGS84 | Limited | 2026-09-22 |
| Afghanistan | `af_usaid` or a `usgs_nwis` extension | USGS Water Data API, agency `USAID` | Daily Q | 1949 to 1980 | 151 sites, 149 daily Q series | Decoded from site number | Limited | 2026-09-22 |
| Ireland, local authorities via EPA | `ie_epa` | EPA HydroNet, JSON index plus ZIP/CSV | Daily mean Q (15-min also offered) | 1995 to 2026 in the files found | 331 continuous non-OPW, non-NI stations; 1 EPA-owned | WGS84 | Limited (download path unresolved for some) | 2026-09-22 |
| Croatia | `hr_dhmz` | DHMZ `hisbaza.py` | Stage (no Q in live feed) | Latest value | 394 (211 with a value) | WGS84 | Limited | 2026-09-22 |
| Italy, Emilia-Romagna | `it_arpae` | ARPAE rolling JSON | Q at 15 or 30 min | Rolling 10 days | 7 Po gauges | WGS84 (÷1e5) | Limited | 2026-09-22 |
| Bulgaria, NIMH | `bg_nimh` | NIMH openData, one POST per day | Daily Q | About 100 days (from 2026-06-15) | 68 | Missing | Limited | 2026-09-22 |
| Germany, Baden-Württemberg | `de_bw` | LUBW HVZ station JavaScript | Q and stage | Latest value | 334 (251 with Q, 305 with stage) | WGS84 (also Gauss-Krüger, UTM32) | Limited | 2026-09-22 |
| Bulgaria, Danube | `bg_appd` | EAEMDR/APPD HTML table | Q, stage, water temperature | Latest value | 21 rows, 6 with Q | River km only | Limited | 2026-09-22 |
| Rwanda | `rw_rwb` | RWB Water Portal: HTML field visits; telemetry POST JSON | Field-visit Q and stage; 15-min telemetry stage | Field visits 1955 to 2024; telemetry rolling 4 days | 90 (field visits, many empty); 40 telemetry series (35 with data) | WGS84 | Limited | 2026-09-22 |
| Türkiye | `tr_dsi` | DSİ flow-observation yearbooks, PDF | Daily Q | Born-digital text 1997 to 2021; 1959 to 1972 and 1996 are scans | 948 station pages in 2020 | DMS on each station page | Limited (PDF parsing) | 2026-09-22 |
| Indonesia, East Java | `id_jatim` | Provincial water agency (Dinas PU SDA) SIH3 portal, form POST with session token | Hourly Q; hourly stage | Arbitrary ranges; 2024 to 2026 checked | 3 of 22 Q stations with data; stage at many more | WGS84 | Limited | 2026-09-22 |
| Somalia | `so_swalim` | FAO SWALIM flow archive, series embedded in station pages | Daily stage; daily Q at 4 stations | 1951 to 2026 | 11 (6 current) | Listed, columns transposed | Limited (provenance to confirm) | 2026-09-22 |
| South Africa, Inkomati-Usuthu | `za_iucma` | IUCMA river-operations web API (DHI) | Q at 12 min (IUCMA); daily Q (DWS stations) | Latest 4,000 points per series | 31 current (62 series); 83 historical (175 of 237 series with values) | From the `za_dws` catalogue (DWS station numbers) | Limited | 2026-09-22 |
| Armenia | `am_hmc` | Hydrometeorology and Monitoring Center daily bulletins, PDF | Q at 08:00 and 20:00 | March to December 2025 (nothing for 2026 on the page) | About 46 | Missing | Limited (PDF parsing; some bulletins scanned) | 2026-09-22 |
| Georgia | `ge_nea` | National Environmental Agency JSON pins plus station pages | Daily stage (cm) | February 2022 to present | 19 | WGS84 | Limited (stage only) | 2026-09-22 |
| Côte d'Ivoire | `ci_dh` | Direction de l'Hydrologie JSON API | Daily and instantaneous Q and stage | Rolling about 4 weeks | 35 (25 with daily rows, 11 with Q) | WGS84 | Limited | 2026-09-22 |
| Niger basin | `ne_abn_sath` | Niger Basin Authority SATH per-station CSV | Daily Q and stage | 2026 season only (June to August) | 91 listed, 12 with data | WGS84 | Limited | 2026-09-22 |
| Niger | `ne_slapis` | SLAPIS web service (Direction de l'Hydrologie with CNR-IBE) | Hourly Q and stage | Per calendar year, 2020 to 2026 | 8 listed; 3 ever with data; only Niamey after 2024 | WGS84 | Limited (provenance to confirm) | 2026-09-22 |
| Sri Lanka | `lk_irrigation` | Irrigation Department ArcGIS feature service | Stage | Rolling about 7 days | 40 gauges; 42 stations | WGS84 | Limited (stage only) | 2026-09-22 |
| Malaysia | `my_jps` | Department of Irrigation and Drainage, Public InfoBanjir | Stage (raw, clean and final values) | Rolling 7 days | 576 across 15 states | Missing | Limited (stage only) | 2026-09-22 |
| Philippines | `ph_philsensors` | DOST-ASTI PhilSensors monitoring JSON | Hourly stage | Rolling 24 hours | 53 | Missing | Limited (terms restrict reuse) | 2026-09-22 |
| Namibia, Okavango basin | `okacom` | OKACOM decision-support system API | Stage (logged, daily and monthly views) | 2022-11 to 2023-11 | 2 | WGS84 | Limited | 2026-09-22 |
| Zambia and Zimbabwe, Zambezi | `zra` | Zambezi River Authority HTML tables | Daily Q | Two weeks, plus the same weeks a year earlier | 3 | Missing | Limited | 2026-09-22 |
| Eswatini and South Africa, Komati | `kobwa` | Komati Basin Water Authority page | 24-hour mean Q | Latest value | 10 weirs | Missing (1 via `za_dws`) | Limited | 2026-09-22 |
| Indonesia, Jakarta | `id_jakarta` | Jakarta water agency flood-post table | Stage (cm) | Latest value | 38 | Missing | Limited (stage only) | 2026-09-22 |
| China, Lancang | `lmc` | Lancang-Mekong cooperation platform JSON, data credited to China's Ministry of Water Resources | Stage | Latest value | 2 | Missing | Limited (stage only) | 2026-09-22 |
| Cambodia | `kh_nffc` | National Flood Forecasting Centre per-station CSV | Stage at 15 min | Frozen on 2023-02-27 | 7 (4 with data) | Missing | Limited (feed stopped) | 2026-09-22 |

### 3.1 Verification on 2026-09-22

Each source was downloaded again on 2026-09-22. Where a source has a station list, stations were
picked at random (seeded) rather than hand-picked. "Sample" is what was downloaded. "Found" is the
result, including the points where earlier entries in this file were wrong. Nothing was kept in
the repository; the scripts and their JSON results stayed in a temporary session directory.

| Source | Sample | Found |
|---|---|---|
| Mexico | Full catalogue; 30 random station files in full; the first 700 bytes of all 1,189 files | 30 of 30 downloaded; 28 have Q, 13 have stage; only 9 have Q after 2020. 1,172 files exist (1,119 old layout, 53 new layout), 15 return 404, 1 timed out. All 1,189 coordinates fall inside Mexico. One `Clave` (`B24215`) appears twice. **Corrections:** the catalogue is Latin-1, not UTF-8. The host now answers through Imperva Incapsula: Python's `urllib` gets HTTP 403, while `curl` with a cookie jar gets through after one redirect. There are two file layouts (see 5.1). |
| Israel | All 8 discharge resources (row and station counts); 6 random active stations across all resources | 1.9 million daily rows. 185 of the 458 catalogue stations have discharge; 114 of those are active. All 6 stations downloaded, with 7,671 to 29,586 rows, no duplicate dates and records ending in 2024. **Corrections:** only 185 stations have discharge, not 458. The 1960 to 1980 resource names its columns `(מטר קוב/שניה)` instead of `(מ''ק/שניה)`. |
| Colombia | Full AQUARIUS dataset index; 6 random daily-Q datasets in full; Socrata counts and one station-year | 4 of 6 datasets returned 948 to 18,373 values; 2 returned nothing (both lack start and end dates in the index, as do 61 of 1,140). Most historical datasets end around 2015; 60 run into 2026. Grades include `-3 - SIN DATO`; approvals include `900 - Preliminar` and `1200 - Definitivo`. Socrata: 21.6 million rows, 393 stations, 2001 to 2026. |
| New Zealand | 11 council servers; 2 random flow sites per council for the last 30 days; 5 random sites each at 4 councils over each site's own record | 8 councils answered: Wellington 139 flow sites, Tasman 107, Horizons 102, Taranaki 71, Otago 67, Marlborough 53, Gisborne 45, West Coast 20. Hawke's Bay returned HTTP 522, Northland timed out, and ECan listed no flow sites. All 20 follow-up sites returned data within their own record. **Corrections:** units differ by council (`l/s` at Horizons; `m³/sec`, `m3/sec` or `cumecs` elsewhere). Many listed sites are closed. The public Otago and West Coast servers stop in 2024 (all 5 Otago sites end on 2024-11-06). Otago gives coordinates for only 19 of 67 flow sites. |
| Germany, NRW | Index, station master, 3 decade archives (two 2020s, one 1960s) | 130 files in 12 decades (1910 to 2029); 281 stations. Ahrhütte-Neuhof: 132,269 rows from 2020-01-01; Westheim (1960s): 21,686 rows. The newest rows end in `NA`. |
| PEGELONLINE | Station list; 3 random Q stations over 31 days and over January 2025 | 786 stations, 94 with Q, 729 with coordinates. About 2,950 to 2,975 values each over 31 days. January 2025 returned 0, which confirms the window. |
| Bavaria | Catalogue; 4 random stations for May 2024 and January 2005 | 611 station pages. 3 of 4 returned full months: 2,976 values at 15 minutes for both 2005 and 2024. The fourth returned nothing in either period. **Correction:** the earlier parser problem is solved. `…/messwerte/tabelle?beginn=&ende=` returns the complete table. Coordinates and catchment area are on every sampled page. |
| Afghanistan | All 151 sites; 6 random stream sites in full | All 151 decode to positions inside Afghanistan. All 6 sites downloaded, with 1,067 to 6,573 daily values between 1949 and 1980. Codes are `A`, `A:e` and `A:<`. |
| Peru | Full WFS; 6 random discharge stations, 5 hydrological years each | All 6 stations returned daily Q for 2020/21 to 2026 (259 to 366 days per year); one also for 2019/20. Units `m3/s`. |
| Ireland | Full index; 4 OPW or NI stations; 5 random local-authority stations | **Correction:** only 1 of 242 EPA-owned stations has continuous flow. The rest are spot gaugings. Continuous series belong to OPW (239), Rivers Agency NI (134) and local authorities and ESB (331). OPW and NI files were not found under the tested path. 2 of 5 local-authority stations downloaded daily means with quality codes: Castleisland, 9,030 rows from 2002; Timolin, 11,577 rows from 1995. The other 3 were not found under any region code. |
| Croatia | Station list and latest values | 394 stations, all with coordinates; 211 latest values, all in cm. |
| Italy, ARPAE | Whole file | 4,787 records for 7 named Po gauges (Boretto, Pontelagoscuro, Piacenza, Sermide and others) over 10 days. Discharge is BUFR variable `B13226`. |
| Bulgaria, NIMH | 15 dates from June to September 2026 | 68 rows per date with 64 to 68 numeric Q values from 2026-06-15; empty on 2026-06-10 and earlier. **Correction:** the window is about 100 days. |
| Baden-Württemberg | Whole station file | 334 rows: 251 with Q and 305 with stage. WGS84 for 331, plus Gauss-Krüger and UTM32 fields. |
| Bulgaria, APPD | Whole table | 21 rows; 6 with Q (for example Novo Selo 1,514 m³/s). |
| Rwanda | 8 random field-visit stations; all 40 telemetry series | Field visits: 3 of 8 had none, 2 had 1 or 2 stage visits, and 3 had 10 to 216 visits (1955 to 2024). Telemetry: 35 of 40 had 107 to 1,291 values over 4 days. 87 of 90 station coordinates fall inside Rwanda. |
| Türkiye | Whole 2020 volume parsed; 2021 PDF; the 1959 to 1972, 1996 to 2000, 2001 to 2010 and 2011 to 2015 archives | 2020: 948 station pages; a simple parser reads 736 complete tables (366 values each). The rest contain the flags `KURU` (dry) and `------`. 1997 to 2021 are born-digital text. **Correction:** 1959, 1972 and 1996 are scans; 1959 and 1972 carry an OCR text layer with visible recognition errors. 1973 to 1995 and the EİE archives were not checked. |
| East Java | 8 data types × 3 random stations × 2 periods; all 22 discharge stations × 3 periods | **Correction:** only 3 of 22 discharge stations return data, all on the Welang river (Dhompo, Selowongko, Purwodadi). Stage coverage is uneven: some stations have only 2024 data, others only 2026. AWLR Lahor reads about 270 in March 2024 and about 2.67 in September 2026, which looks like a unit change. |
| Somalia | All 11 stations in full | All 11 have daily stage; **only 4 have discharge** (Luuq, Bardheere, Belet Weyne, Bulo Burti). 6 stations have data in 2026; the others end between 1979 and 2024. The coordinate columns are transposed for all 11. |
| IUCMA | All 62 current and 237 historical series | Current: 62 of 62 have values, 61 ending in 2026. Every response is exactly 4,000 points. Historical (DWS): 175 of 237 have values, ending between 2013 and 2023. |
| Armenia | 266 links; 10 random bulletins | Links date mainly from March to December 2025, with 49 undated names; none from 2026. 8 of 10 bulletins parsed, with 41 to 43 station rows each. **Correction:** 2 are scans with no text layer. |
| Georgia | JSON; station pages 1 to 60 | All 60 pages resolve to the 19 JSON stations, several page IDs per station. Each has about 1,600 daily values since 2022, with 9 to 24 dates repeated. Mashavera – Kazreti ends on 2025-11-10. |
| Côte d'Ivoire | All 35 stations, daily and instantaneous | 25 with daily rows, **11 with daily Q**, 26 with instantaneous rows; the daily window runs from 2026-08-26 to 2026-09-22. |
| Niger basin SATH | All 91 Q files | 12 with rows, from June to August 2026. |
| SLAPIS | All 8 listed stations, 5 years each | Only Niamey, Garbey Kourou and Bossey Bangou ever had data. Only Niamey has data after 2024 (8,651 hours in 2025, 5,258 so far in 2026). |
| Sri Lanka | All readings; station layer | 6,455 readings from 40 gauges, 84 to 180 each, over 2026-09-15 to 2026-09-22. All 40 gauge names match a station in the 42-station layer, which includes a `Unit` field. |
| Malaysia | All 16 state tables; 6 random 7-day series | 576 stations (Putrajaya 0). **Correction:** the 7-day route needs the ID from the graph link, which differs from the table's station ID. With it, all 6 returned a 2,243-slot grid. Much of it is `-9999` (missing), and one station has 1,454 slots flagged `ERROR`. |
| Philippines | Whole response | 53 stations, each with 2 to 25 hourly values. |
| OKACOM | All level views | Two sites. Logged level view: 74,709 rows; daily: 782; monthly: 26. |
| ZRA, KOBWA, Jakarta, Lancang | Whole pages | ZRA: 42 daily rows (3 stations × 14 days). KOBWA: 10 weirs. Jakarta: 38 stations, all current. Lancang: 2 stations. |
| Cambodia | All 7 station files | See 5.34. |

Sources that were examined but gave no download are in section 6, with the reason.

---

## 4. Porting guide

This section describes how to add a candidate as a provider in the current architecture. The
architecture is explained in [architecture.md](../architecture.md). The project rules are in the
repository's `AGENTS.md`, and documentation style is in [docs/AGENTS.md](../AGENTS.md).

### 4.1 Before writing code

1. **Re-test the source.** Run the test request from the candidate's section. Record the date,
   station count and first and last values again. If the result differs from this file, update
   this file first.
2. **Record the terms.** Add the agency to the source-terms survey (branch
   `research/source-terms-survey`, one branch per agency). Record what the agency says about
   reuse, redistribution and citation, quoting from its recorded pages. Do not rely on
   hydrodownloadR's licence labels.
3. **Keep observation values out of the repository.** Evidence for a response that carries
   measurements is limited to these items:
   - the exact request URL
   - the HTTP status and media type
   - the UTC acquisition instant
   - the byte size and the SHA-256 of the full response
   - derived readings, such as counts, first and last labels, and null states

   Responses with no observation value may be kept whole: empty results, all-null grids and error
   bodies. A test must fail the build if a measurement value is stored.
4. **Write down the unknowns.** List what the source does not state:
   - the time zone
   - the definition of the day for daily values
   - whether a daily value is a mean
   - the stage datum
   - the meaning of any flags

   RivRetrieve keeps these as unknown rather than inferring them.

### 4.2 Choose the provider kind

Every provider declares one of three kinds in its `declaration.py`:

| Kind | Use when | Examples |
|---|---|---|
| `LiveStages` | The source answers per station and per time window, or per station with a small response | `jp_mlit`, `usgs_nwis`, `cz_chmi` |
| `BulkStore` | The source publishes large archive files that are downloaded once, compiled into a local store and read from there | `pl_imgw`, `ca_eccc` |
| `CatalogueOnly` | Only the station list can be served for now | `za_dws` |

A `LiveStages` provider supplies `config.py` (products and window declarations), `fetch.py` and
`parse.py`. The shared engine splits the requested window, converts units, clips the result and
assembles it. A provider must not shift the window bounds that the engine renders.

A `BulkStore` provider supplies download and compile operations in `bulk.py`. The shared store
reader serves observations after an explicit `download`.

### 4.3 Files to create

Create a package `src/rivretrieve/_internal/providers/<id>/`. Existing providers show the
expected structure:

| File | Content |
|---|---|
| `__init__.py` | Empty |
| `declaration.py` | The provider kind, the catalogue path and any required credentials |
| `config.py` | One `ProductConfig` per product: source coordinates, unit, frequency and daily-label facts. Also window declarations (granularity, rendering, inclusive or exclusive stop) and `SERIES_MAPPINGS` with the evidence for each product |
| `fetch.py` | Builds requests from rendered windows. Returns immutable payload bytes with their source-call origin |
| `parse.py` | Turns payloads into native rows, source-series definitions and issues. Checks that the returned station and variable match the request |
| `bulk.py` | BulkStore only: download and compile |
| `origins.py` | Declares where each catalogue column comes from, and the acquisition provenance |
| `generate_catalogue.py` | Maintainer-only script. It refreshes the native table from the live source and builds the packaged catalogue. Existing scripts accept `--live`, `--fixture` or `--native` as input and `--out` / `--native-out` as outputs |
| `catalogue/` | Generated artifacts: `provider.json`, `stations.parquet`, `products.parquet`, `station_products.parquet`, `native.parquet`, the provenance files and `croissant.json` |

Then add the provider ID to `BUILTIN_PROVIDER_IDS` in
`src/rivretrieve/_internal/provider_manifest.py`. The test `tests/test_fourteenth_provider.py`
shows that a catalogue-only provider needs only its directory and that one manifest line.

### 4.4 Implementation order

1. **Catalogue first.** Write `origins.py` and `generate_catalogue.py`, generate the catalogue from
   the live source, and register the provider as `CatalogueOnly`. This makes stations discoverable
   with `rr.find` before any observation code exists.
2. If the live catalogue refresh needs a minimum-station guard, calibrate it from that provider's
   own station count. Never copy another provider's threshold.
3. **Products.** Define one product per published series. Name only what the source establishes.
   If the source does not say that a daily value is a mean, the statistic is `unknown`.
4. **Fetch and parse.** Implement them against saved real responses, and switch the declaration to
   `LiveStages` (or `BulkStore`).
5. **Tests.** Add catalogue, observation and boundary-probe tests that replay saved interactions
   through the transport seam. Recordings live under `tests/recordings/<id>/` or `tests/test_data/`.
   Replay refuses a request without a matching recording. Recordings that contain measurement
   values must follow the evidence rule in 4.1.
6. **Checks.** Run `uv run ruff format`, `uv run ruff check --fix`, `uv run ty check src` and
   `uv run pytest`.
7. **Documentation.** Write two documents:
   - `docs/provider_ports/<id>.md`, maintainer notes: source chain, products, source labels and
     flags, catalogue.
   - `docs/providers/<id>.md`, the user-facing provider page: who measures and publishes, what
     RivRetrieve returns, units, time, coverage and terms.

   Then move the candidate's row in this file to section 2.1.

### 4.5 Shared prerequisites

- **pyproj.** New Zealand, Germany NRW, Germany Bavaria and Israel publish projected coordinates.
  `pyproj` is not a dependency yet. Add it with `uv add pyproj` in the first port that needs it.
  Record the source CRS as a catalogue fact.
- **Reusable clients.** Several candidates share a protocol. Writing the client once serves all of
  them:
  - Hilltop: New Zealand councils.
  - AQUARIUS WebPortal: Colombia, and Auckland in New Zealand.
  - KiWIS: Waikato in New Zealand.
  - CKAN DataStore: Israel.
  - Socrata SODA: Colombia stage.
  - ArcGIS feature services: Sri Lanka, and the Colombian station catalogue.
- **PDF text extraction.** Türkiye and Armenia publish daily values in PDFs with a text layer.
  A PDF library would be a new dependency, and parsed tables need per-volume layout checks.
- **DWS station numbers.** The IUCMA and KOBWA sources use DWS station numbers, so they can reuse
  the coordinates in the `za_dws` catalogue.

### 4.6 Suggested order

This order reflects the verification of 2026-09-22 (section 3.1).

1. **Israel** (`il_iwa`): clean public API, 185 stations with daily discharge back to 1943. The
   first port that needs pyproj.
2. **Mexico** (`mx_conagua`): long records at more than 1,100 stations, but two file layouts, and
   the host now screens clients. Confirm with CONAGUA that automated access is acceptable first.
3. **Colombia** (`co_ideam`): large network with grade and approval codes. Skip datasets that the
   index lists without dates, and note that most series end around 2015.
4. **Germany NRW** (`de_nrw`): century-long records. The BulkStore pattern, like `pl_imgw`.
5. **New Zealand** (`nz_hilltop`): large federated network with sub-daily data. Unit spellings
   differ by council, and two councils stop in 2024.
6. **Germany, Bavaria** (`de_bayern`): 611 stations with 15-minute discharge over arbitrary ranges,
   now that the full table route is known.
7. **Türkiye** (`tr_dsi`): the largest new network (948 stations in one year). Limit it to the
   born-digital volumes, 1997 to 2021.
8. **Peru**, **Afghanistan**, **Somalia**, **South Africa (IUCMA)** and **Ireland (local
   authorities)**.
9. The short-window and latest-value sources. East Java belongs here too: only 3 of its 22
   discharge stations have data.

---

## 5. Candidate details

### 5.1 Mexico: CONAGUA SIH (`mx_conagua`), Ready

**Source.** Comisión Nacional del Agua publishes the hydrometric database of its Sistema de
Información Hidrológica as static files. The landing page is `https://sih.conagua.gob.mx/hidros.html`.
The files are under `https://sih.conagua.gob.mx/basedatos/Hidros/`.

**Catalogue.** `0_Catalogo%20de%20estaciones%20hidrometricas.csv` is a 93 kB file with 1,189
stations, encoded in Latin-1 (not UTF-8). One `Clave`, `B24215`, appears twice. It has these columns:

- `Clave`, the station code
- the station name
- `Latitud` and `Longitud`, in decimal degrees
- `Altitud`, `Estado`, `Municipio`
- `R.H.`, the hydrological region
- `Cuenca`

**Observations.** One file per station, `<Clave>.csv`. It starts with seven header lines naming
the agency, station, code, state and municipality. Two table layouts exist:

- **Old layout** (1,119 files): header `Fecha, Nivel(m), Gasto(m³/s)`, dates as `YYYY/MM/DD`,
  missing values as `-`.
- **New layout** (53 files): header `Estacion,Fecha,Nivel(m),Gasto en Rio(m3/s)`, ISO dates,
  missing values left blank. These files run to the day before the download (2026-09-21).

Of the 1,189 catalogue stations, 1,172 have a file, 15 return HTTP 404 and 1 timed out.

**Access.** Since 2026-09-22 the host answers through Imperva Incapsula. The first request gets an
HTTP 302 back to the same URL with session cookies. `curl` with a cookie jar then receives the
file, while Python's `urllib` receives HTTP 403 even with the cookies. The response looks like
client screening. A port must confirm with CONAGUA that automated access is acceptable, and must
not disguise its client.

**Test (2026-09-22).**

- `ABSTP` (Abasolo, Tamaulipas) runs from 2004-08-07 to 2025-09-03. It has 3,295 non-missing daily
  Q values from 2014-09-17, with a maximum of 1,187.12 m³/s. Stage starts in 2004.
- `B12358` has 26,328 daily Q values from 1939-12-02 to 2014-12-31.
- 20 stations spread through the catalogue all returned HTTP 200, with files of 130 to 525 kB.
- A seeded random sample of 30 stations downloaded in full:
  - 28 have discharge values and 13 have stage values.
  - Only 9 have discharge after 2020. Most of the `B…` stations end between 1942 and 2014, although
    their files are padded with empty rows to 2021-06-07.
  - No negative discharge was found.
  - The longest record starts in 1922.
- `BOQCP` reports stage near 1.4 in 2004 and 481.39 in 2026. The file does not explain the
  change, so it must be kept as published.

**Porting notes.**

- There is no API, date filter or authentication. Every request returns the whole station file.
  - As `LiveStages`, fetch downloads the file once per station for any window, and the engine
    clips.
  - Check that the window declarations can express "one request per station, whatever the window".
    That is a design question.
  - As `BulkStore`, all 1,172 files add up to roughly 300 MB.
- The parser must handle both layouts.
- The files do not state a time zone or whether values are daily means. Keep both unknown.
- Stage and discharge share one file, so they form two products from one fetch.
- hydrodownloadR's licence label: CC BY 4.0, linking the datos.gob.mx dataset
  `estaciones_sistema_informacion_hidrologica`.

### 5.2 Israel: Israel Water Authority, Hydrological Service (`il_iwa`), Ready

**Source.** The Government Authority for Water and Sewage publishes on the national open-data
portal through the CKAN Action API, `https://data.gov.il/api/3/action`.

**Catalogue.** Package `hydro_station`, resource `a0522b41-00ad-4367-a00a-2d97b050ec1d` (CSV,
DataStore active). The package licence is Creative Commons Attribution.

- `datastore_search?resource_id=…&limit=500` returned 458 stations: 127 `פעילה` (active),
  330 `לא פעילה` (inactive) and one with a blank status.
- Field names are in Hebrew. They cover:
  - the station ID
  - Hebrew and English names
  - the founding date
  - the catchment area in km²
  - a shared-catchment flag
  - X and Y
  - a group number
  - the main drainage basin
  - the status
- X and Y are on the Israeli Transverse Mercator grid, EPSG:2039. Reprojected with pyproj, 457 of
  the 458 fall between 34.40 and 35.79 °E and 29.53 and 33.28 °N. Station 2105 (KEZIV) maps to
  35.107 °E, 33.051 °N. One station has no coordinates.

**Observations.** Package `level_discharge`, listed licence "Other (Open)", split into eight
period resources. All have the DataStore active and were last modified between 2026-09-01 and
2026-09-07.

| Resource | Period |
|---|---|
| `bb596622-12f3-43bb-8730-cf7d5fb734e2` | Up to 1960 (58,003 rows) |
| `0cffea1d-3213-4345-9dcc-0bd97820f3b7` | 1960 to 1980 |
| `b2247803-ab8b-4103-a456-2508add0fe08` | 1980 to 1990 |
| `9062dc89-bd72-4602-88b8-3f236e5ce6a5` | 1990 to 2000 |
| `e9da4c4c-7b21-461e-ae0e-03cea1abc05a` | 2000 to 2010 |
| `1deb7974-d811-4391-9d79-ba454a8ad9d1` | 2010 to 2015 |
| `bbfa5a4f-a310-4733-9509-6ba31058631d` | 2015 to 2020 |
| `62cd157d-766d-4648-897d-50526f45abf9` | 2020 onward (171,192 rows) |

The columns are:

- station ID
- Hebrew and English names
- date, as `DD/MM/YYYY`
- daily volume, in m³
- daily mean discharge, in m³/s
- hydrological year

Filter by station on the server with
`filters={"זיהוי תחנה הידרומטרית": <id>}`, passed as JSON.

**Test (2026-09-22).**

- Station 2105 (KEZIV – HAZIV BRIDGE) in the 2020+ resource returned 1,461 daily rows, from
  01/10/2020 to 30/09/2024, with a maximum of 7.19 m³/s.
- The earliest row seen in the pre-1960 resource is station 2106 on 09/03/1953, at 0.51 m³/s.
- **Re-test (2026-09-22).**
  - The eight resources hold about 1.9 million rows in total:
    - up to 1960: 58,003 rows, 22 stations
    - 1960 to 1980: 317,285 rows, 60 stations
    - 1980 to 1990: 259,240 rows, 89 stations
    - 1990 to 2000: 322,504 rows, 105 stations
    - 2000 to 2010: 336,981 rows, 109 stations
    - 2010 to 2015: 211,745 rows, 135 stations
    - 2015 to 2020: 224,862 rows, 137 stations
    - 2020 onward: 171,192 rows, 121 stations
  - Only **185 of the 458 catalogue stations have discharge**; 114 of them are active. Every
    discharge station ID is in the catalogue.
  - Six random active stations downloaded in full, with 7,671 to 29,586 rows each, no duplicate
    dates and no negative values. Five end on 2024-09-30 and one on 2024-01-17. HILLAZON – YAS-UR
    starts on 1943-10-01.
  - Some rows have a null discharge. At ASHALIM CANAL, 4,104 of 9,855 are null.
- The 1960 to 1980 resource names its columns `נפח יומי (מטר קוב)` and
  `ספיקה יומית ממוצעת (מטר קוב/שניה)`. The others use `(מ''ק)` and `(מ''ק/שניה)`. A parser must
  accept both.

**Porting notes.**

- Look up the period resources with `package_show` rather than hard-coding their IDs, as
  hydrodownloadR does. Fetch the resources that overlap the window, filtered by station, and
  paginate with `limit` and `offset`.
- The source names the value a daily mean ("ספיקה יומית ממוצעת"), so the statistic is established
  as mean. The day definition and time zone are not stated.
- Send one request per second. hydrodownloadR reports that CKAN sometimes answers HTTP 409 to rapid
  requests.
- A water-quality package, `qual_per_hydro_station`, is out of scope.
- hydrodownloadR's licence label: Custom/Terms of Service, `https://data.gov.il/he/terms-of-use`.
  CKAN itself shows CC BY for the stations package and "Other (Open)" for the discharge package.

### 5.3 Colombia: IDEAM (`co_ideam`), Ready

IDEAM data can be reached by two routes.

#### Discharge and daily stage: AQUARIUS WebPortal (from hydrodownloadR, tested 2026-09-22)

The base URL is `https://aquariuswebportal.ideam.gov.co`. No login, cookie or disclaimer step was
needed.

1. **Parameter list.** `POST /Data/List/` with an empty body returns HTML. Each `<option>` carries
   a numeric `value` and a `data-code`. Live IDs were `CAUDAL` = 48 and `NIVEL` = 34. Look them up
   by `data-code` instead of hard-coding the numbers.
2. **Dataset index.** `POST /Data/Data_List`, sending `page`, `pageSize=5000` and
   `parameters[0]=48` both as form fields and in the query string. The response is JSON
   `{Data, Total}`. Each row has these fields:
   - `LocationIdentifier` and `Location`
   - `DatasetId` and `DatasetIdentifier`
   - `LocX` and `LocY`, in WGS84
   - `LocType`
   - `StartOfRecord` and `EndOfRecord`

   Live there were 10,813 CAUDAL datasets:
   - Daily mean discharge is `CAUDAL.HIS_Q_MEDIA_D` (931 datasets, historical) and
     `CAUDAL.Q_MEDIA_D` (211, operational). Together they make 1,142 datasets at 983 locations,
     all with coordinates.
   - Other labels include hourly `CAUDAL.CAUDAL_H` (582), daily maximum and minimum `Q_MX_D` and
     `Q_MN_D`, and monthly and annual aggregates.
   - One location is `ESTACION FICTICIA [10000000]`, a fictitious station, and has to be excluded.
3. **Values.** `GET /Data/DatasetGrid?dataset=<DatasetId>&sort=TimeStamp-asc&page=1&pageSize=50000&interval=Latest&timezone=-300&alldata=true&virtual=true`
   returns JSON `{Data, Total}`. Each point has these fields:
   - `TimeStamp`, `Value` and `DisplayValue`
   - `Grade` and `Approval`
   - `InterpolationType` and `Comment`

   This JSON route avoids the portal's ZIP/CSV export, which needs a short-lived token.

**Test.** Dataset 38820, `CAUDAL.HIS_Q_MEDIA_D@24037430` (SAN RAFAEL, −73.0, 5.783), returned
7,691 daily values from 1978-01-01 to 2000-02-29. The first point is 0.401 m³/s, with grade
`4 - INCOMPLETO`, approval `900 - Preliminar` and interpolation `8 - Succeeding Avg.`

**Re-test (2026-09-22).** The index gave 1,140 daily-mean discharge datasets at 982 locations,
once the fictitious station was excluded. 1,139 have coordinates inside Colombia. Six random
datasets were downloaded in full:

| Dataset | Values | Period |
|---|---|---|
| `CAUDAL.HIS_Q_MEDIA_D@13027010` (La Esmeralda) | 2,936 | 1991-01-01 to 2000-01-21 |
| `CAUDAL.HIS_Q_MEDIA_D@25027370` (Santa Ana) | 13,747 | 1973-07-01 to 2015-12-31 |
| `CAUDAL.Q_MEDIA_D@2403700232` (Puente Satoba) | 948 | 2022-09-10 to 2025-09-04 |
| `CAUDAL.Q_MEDIA_D@21137050` (Angostura) | 18,373 | 1975-01-01 to 2026-07-31 |
| `CAUDAL.Q_MEDIA_D@2108700182` | 0 | |
| `CAUDAL.HIS_Q_MEDIA_D@23205040` | 0 | |

- The two empty datasets have no start or end in the index. The same is true of 61 of the 1,140,
  which can be used to skip them.
- By end year, most datasets stop around 2015 (349 end in 2015). Only 60 run into 2026.
- Grades seen: `4 - INCOMPLETO`, `50 - INDEFINIDO` and `-3 - SIN DATO`, where `-3 - SIN DATO`
  (no data) rows carry no usable value.
- Approvals seen: `900 - Preliminar`, `1100 - En revisión` and `1200 - Definitivo`.
- Socrata answered with 21.6 million rows at 393 stations, from 2001-01-01 to 2026-09-21.
  Station `0022057010` returned 8,612 rows for 2015.
- The datos.gov.co station catalogue `hp9r-jxuu` has 29,166 rows.

**Porting notes for this route.**

- The historical (`HIS_*`) and operational series are separate source series. hydrodownloadR
  merges them and lets the operational one win where they overlap. RivRetrieve should keep them
  as separate series, with the published grade and approval codes left uninterpreted.
- The `timezone=-300` parameter makes the portal render timestamps at UTC−05:00. Record exactly
  what the returned `TimeStamp` values represent before declaring a time zone.
- This route also serves the daily stage labels `NIVEL.HIS_NV_MEDIA_D` and `NIVEL.NV_MEDIA_D`.
- The same WebPortal software runs at Auckland Council in New Zealand, so the client can be shared.

#### Hourly stage: datos.gov.co Socrata API (tested 2026-08-10)

IDEAM publishes raw series as Socrata tables on the national open-data portal.

| Dataset | Socrata ID | Variable | Rows |
|---|---|---|---|
| Nivel Instantáneo del Río | `bdmn-sqnh` | River stage, m | 21,463,320 |
| Nivel Máximo del Río | `vfth-yucv` | Daily maximum stage | |
| Nivel Mínimo del Río | `pt9a-aamx` | Daily minimum stage | |

- Base URL: `https://www.datos.gov.co/resource/<id>.json`. It takes SoQL parameters: `$where`,
  `$order`, `$limit`, `$offset`, `$select=count(*)` and `codigoestacion=<code>`.
- Columns:
  - `codigoestacion`, `codigosensor`
  - `fechaobservacion`, `valorobservado`
  - `nombreestacion`, `departamento`, `municipio`, `zonahidrografica`
  - `latitud`, `longitud`
  - `descripcionsensor`, `unidadmedida`
- `bdmn-sqnh` has 393 distinct stations.
- **Test.** Station `0022057010` (PIEDRAS DE COBRE, río Saldaña, Tolima; 3.9084 °N, −75.1033 °E)
  returned 8,613 hourly stage values for 2015, between 0.00 and 4.37 m.
- **Datum.** The value is stage relative to each station's gauge zero (cero de la mira), in
  metres. It is not an elevation above sea level. Station PALMALARGA has `altitud` 435 m but reads
  about 2.7 m. The gauge-zero elevation is not in the open data. Dataset `ia8x-22em`
  ("Nivel del Mar") is sea level and unrelated.
- Discharge is not published through Socrata.

#### Station catalogue alternatives

- ArcGIS layer
  `https://dhime.ideam.gov.co/server/rest/services/Cartografia_Basica/CatalogoNacionalEstaciones2017/MapServer/0/query`.
  It has 4,514 stations, of which 1,327 are hydrological (`where=clase='HID'`), with WGS84 points.
  Its fields are:
  - `codigo_cat_` and `nombre`
  - `corriente`
  - `categ_`: LM is limnimétrica (staff gauge), LG is limnigráfica (recording gauge)
  - `depto`, `estado`, `altitud`, `fecha_inst_`
- datos.gov.co `hp9r-jxuu.json`, IDEAM's national station catalogue. hydrodownloadR uses it for
  elevation and as a fallback for names and coordinates.
- The DHIME portal (`http://dhime.ideam.gov.co/atencionciudadano/`) needs browser automation
  (Selenium). The AQUARIUS route makes it unnecessary.

hydrodownloadR's licence label: CC BY-SA 4.0, linking datos.gov.co dataset `jxnq-r3i9`.

### 5.4 New Zealand: regional councils, Hilltop (`nz_hilltop`), Ready

**Source.** New Zealand has no national river-flow portal. About 16 regional councils run the
gauges, and most publish through a Hilltop server that speaks the same query protocol. A provider
is therefore federated: one Hilltop client and a list of council servers.

**Council servers (checked 2026-08-10).**

| Council | Base URL | Flow sites | Status |
|---|---|---|---|
| Greater Wellington | `https://hilltop.gw.govt.nz/Data.hts` | 138 | Working (3,341 sites in total) |
| Tasman | `http://envdata.tasman.govt.nz/data.hts` | 107 | Working |
| Horizons (Manawatū-Whanganui) | `https://hilltopserver.horizons.govt.nz/boo.hts` | 101 | Working (1,066 sites in total; NZMG) |
| Taranaki | `https://extranet.trc.govt.nz/getdata/boo.hts` | 71 | Working |
| Otago | `https://gisdata.orc.govt.nz/hilltop/data.hts` | 67 | Working (NZTM) |
| Marlborough | `https://hydro.marlborough.govt.nz/data.hts` | 53 | Working |
| Gisborne | `http://hilltop.gdc.govt.nz/data.hts` | 45 | Working |
| West Coast | `https://hilltop.wcrc.govt.nz/data.hts` | 19 | Working |
| Canterbury (ECan) | `http://data.ecan.govt.nz/data.hts` | 0 | Answers XML; needs the correct `.hts` collection |
| Hawke's Bay | `http://data.hbrc.govt.nz/EnviroData/Emar.hts` | | Known server; timed out from the test network |
| Northland | `https://hilltop.nrc.govt.nz/data.hts` | | Known server; timed out from the test network |
| Southland | `envdata.es.govt.nz` | | `data.hts` returned 404; path unknown |
| Nelson | | | Served through Tasman's server |

On 2026-09-22 the eight working councils listed 604 flow sites: Wellington 139, Tasman 107,
Horizons 102, Taranaki 71, Otago 67, Marlborough 53, Gisborne 45 and West Coast 20. Many listed
sites are closed, and Otago gives coordinates for only 19 of its 67. Three councils use other systems:

| System | Council | Notes |
|---|---|---|
| KiWIS (KISTERS) | Waikato, `riverlevelsandrainfall.waikatoregion.govt.nz` | Standard REST/JSON: `getStationList`, `getTimeseriesList`, `getTimeseriesValues`. A generic KiWIS client would also serve other KiWIS agencies |
| AQUARIUS WebPortal | Auckland, `environmentauckland.org.nz` | `/Data/*` and `/Export/*` answer HTTP 200; needs a disclaimer-cookie session. Same software as Colombia |
| Unknown | Bay of Plenty (about 1,700 sites) | System not confirmed; guessed URLs timed out |

A map of the councils is in `docs/provider_ports/nz_council_map.html`.

**Hilltop protocol.** All requests are GET and all responses are XML. The query form is
`{base}?Service=Hilltop&Request=<request>&<parameters>`.

| Request | Parameters | Returns |
|---|---|---|
| `SiteList` | `&Location=Yes` | All sites, with `<Easting>` and `<Northing>` |
| `SiteList` | `&Measurement=Flow` | Sites with a Flow measurement |
| `MeasurementList` | `&Site=<name>` | Measurements at a site, with `<Units>` and date range |
| `GetData` | `&Site=<name>&Measurement=Flow&From=YYYY-MM-DD&To=YYYY-MM-DD` | Series as `<E><T>time</T><I1>value</I1></E>` |

- The discharge measurement is named `Flow`. In `MeasurementList` it appears under the
  `Water Level` data source, because flow is rated from level.
- **Units differ by council.** Horizons gives `l/s`, Taranaki and Wellington `m³/sec` (sent as
  `m&#179;/sec`), Tasman, Marlborough and West Coast `m3/sec`, and Gisborne and Otago `cumecs`.
  Read `<Units>` for each response and map every spelling explicitly.
- Derived measurements (`Flow Mean (1 Day)` and others) exist but are not always stored. Prefer
  the raw `Flow`.
- The site name is the station identifier. It is a string, often with spaces and macrons, for
  example `Manawatū at Teachers College`.

**Encoding spaces.** Hilltop needs spaces in site names encoded as `%20`. A `+` is taken
literally, so the server answers "No data for site Hutt+River+at+Kaitoke". The Python `requests`
`params=` argument produces `+`, so build the query string by hand:

```python
from urllib.parse import quote

query = "&".join(f"{key}={quote(str(value), safe='')}" for key, value in parameters.items())
url = f"{base}?{query}"
```

**Coordinates.** Coordinates are projected, and the grid differs between councils:

- Horizons uses NZMG (EPSG:27200), with eastings of about 2.6 to 3.0 million.
- Wellington and Otago use NZTM2000 (EPSG:2193), with eastings of about 1.0 to 2.1 million.

Map the CRS per council, or detect it by easting size. All sample sites reprojected to plausible
New Zealand positions.

```python
from pyproj import Transformer

nztm = Transformer.from_crs(2193, 4326, always_xy=True)
nzmg = Transformer.from_crs(27200, 4326, always_xy=True)

transformer = nzmg if easting > 2_400_000 else nztm
lon, lat = transformer.transform(easting, northing)
```

**Record length.** Each council caps the history it serves. Horizons answers "The server is set
to only send data 12 years back from today". Site start and end dates also vary, so read them from
`MeasurementList`.

- Wellington serves records from 1976 and 1979 (for example Hutt River at Taita Gorge from
  1979).
- The public Otago server ends on 2024-11-06 for all five sampled sites. The West Coast server
  ends between July and October 2024. Those two councils therefore serve no recent data through
  this route.

**Rate limits.** Rapid requests produced dropped connections. Use low concurrency, pacing and
retries. One council being unreachable must not fail the others. In RivRetrieve terms, it becomes
an issue for the affected series.

**Test (2026-08-10).** `Manawatū at Teachers College`, `Flow`, 2025-07-01 to 2026-07-01, returned
105,113 values at 5-minute resolution with no gaps. The minimum was 14.57 m³/s, the mean 104.46
and the maximum 1,521.34.

```bash
curl "https://hilltopserver.horizons.govt.nz/boo.hts?Service=Hilltop&Request=GetData&Site=Manawatu%20at%20Teachers%20College&Measurement=Flow&From=2026-07-23&To=2026-07-25"
```

**Re-test (2026-09-22).**

- For each working council, two random flow sites were asked for the last 30 days. Values came
  back at Horizons, Taranaki, Marlborough (1 of 2) and Gisborne (1 of 2), with 8,180 to 8,641
  values each. The other sites returned nothing for that window.
- A follow-up took 5 random sites each at Wellington, Tasman, Otago and West Coast, asking for the
  last 30 days of each site's own record. All 20 returned data (1 to 8,756 values). So the empty
  results were closed sites, not failures.
- Hawke's Bay answered HTTP 522 and Northland timed out. ECan listed no flow sites under
  `data.hts`.

**Porting notes.**

1. Keep a council registry mapping each council to its base URL and CRS.
2. Write one Hilltop client with the `%20` query builder, pacing and retries.
3. Build the catalogue by combining `SiteList&Location=Yes` and `SiteList&Measurement=Flow` across
   councils. Keep flow sites that have coordinates, and record the council and native CRS.
4. Fetch observations with `GetData`, and parse `<E><T>` and `<I1>`, taking the unit from
   `<Units>`.
5. Site names are not guaranteed unique across councils, so the station identifier may need the
   council as a prefix.

### 5.5 Germany, North Rhine-Westphalia: LANUV (`de_nrw`), Ready

**Discharge index.** 16 catchments, 130 files:
`https://www.opengeodata.nrw.de/produkte/umwelt_klima/wasser/oberflaechengewaesser/hydro/q/index.json`

**Data files.** One CSV-in-ZIP per catchment and decade, from 1910-1919 to 2020-2029. An example is
`.../hydro/q/Ahreinzugsgebiet-NRW-Q_2020-2029_EPSG25832_CSV.zip`.

- Inside is one UTF-8 CSV per station, named `<station_id>_<Name>_<range>_Abfluss_m3s.csv`.
- The columns are `station_name;station_no;dateTime;value[m³/s]`.
- Timestamps are ISO 8601 with `+01:00`. They follow events or thresholds, so the spacing is
  irregular, not a fixed 15 minutes.

**Station list.**
`https://www.opengeodata.nrw.de/produkte/umwelt_klima/wasser/oberflaechengewaesser/hydro/Hydrologische-Stationen-NRW_EPSG25832_CSV.zip`
contains `Hydrologische-Stationen-NRW_EPSG25832.csv`, with 281 stations separated by `;`.

- The header is `station_name;station_id;Meldepegel;Datenpfleger;Mittelwert;Zweck;Betreiber;KOORDX;KOORDYY;UTMZone;Errichtung;GewS;EZG;Nullpunkt;Kommune;Kreis;Name`.
- `station_id` joins to `station_no` in the data files.
- `KOORDX` and `KOORDYY` are UTM zone 32N (EPSG:25832).
- `EZG` is the catchment area in km², `Errichtung` the establishment date, and `Nullpunkt` the
  gauge zero.
- Shapefile variants with `Abfluss_MetaDaten_Pegel` also exist.

**Test (2026-08-10).** Station `2718193000100` (Ahrhütte-Neuhof), decade ZIP 2020-2029, returned
132,240 values from 2020 to 2024-08, between 0 and 74.5 m³/s. Its coordinates reproject to
50.383 °N, 6.749 °E.

**Re-test (2026-09-22).**

- The index lists 130 files covering 12 decades, from 1910-1919 to 2020-2029.
- Ahrhütte-Neuhof now has 132,269 rows (2020-01-01 to 2026-07-01).
- The Diemel 2020s archive holds 3 station files. Bredelar alone has 167,200 rows.
- The Diemel 1960s archive holds Westheim, with 21,686 rows for 1960 to 1969.
- The newest rows end in the value `NA`.
- Every timestamp seen, summer and winter, carries `+01:00`.

**Porting notes.** This is the `BulkStore` pattern of `pl_imgw`. Build the catalogue from the
station list, reprojected from EPSG:25832 to WGS84. Download the decade archives that overlap the
request and compile them. It needs pyproj.

### 5.6 Ireland: EPA HydroNet (`ie_epa`), Limited

It was reported in 2026-08 as being implemented elsewhere, so check that before starting.

- The EPA's HydroNet (WISKI) platform publishes stations from several owners, not only the EPA.
- **Re-test (2026-09-22).** The index has 2,010 rows:
  - 1,196 rows are "Spot flow measurements only". That includes 241 of the 242 EPA-owned
    stations, so only 1 EPA-owned station has continuous level and flow.
  - 704 rows have continuous level and flow. Their owners are OPW (239), Rivers Agency NI (134),
    and county councils and ESB (331).
  - For 4 random OPW and NI stations, no file was found under the path below. OPW's own data is
    legacy PR #96.
  - For 5 random local-authority stations, 2 files were found by trying each region code:
    - Castleisland (22014, `COR`): 9,030 daily rows from 2002 to 2026-09-21
    - Timolin (14057, `DUB`): 11,577 daily rows from 1995

    The files carry the header lines `#Station Name`, `#Station Number`,
    `#Station Parameter Name;River Discharge`, `#Timeseries Name;Day.Mean` and
    `#Unit Symbol;m³/s`, and a quality code per row, such as `Good` or `Unchecked`.
  - The other 3 stations were not found under any region code. The correct file path must be
    derived before porting; the index's `L1_Web_Link` field was empty for the stations checked.
- Station index (JSON, about 5 MB, 2,010 rows):
  `https://epawebapp.epa.ie/Hydronet/output/internet/layers/20/index.json`. Its fields include:
  - `metadata_station_name`
  - `metadata_station_longitude` and `metadata_station_latitude`, in WGS84
  - `L1_DATA_AVAILABLE`, for example "Water Level and Flow"
  - `L1_STATION_OWNER`
  - the river name and catchment area
- Series come as ZIP files of semicolon-separated CSV:
  - 15-minute discharge: `{base}/output/internet/stations/{region}/{no}/Q/complete_15min.zip`
  - Daily mean discharge: `{base}/output/internet/stations/{region}/{no}/Q/complete_daymean.zip`
  - The region codes are `DUB`, `ATH`, `COR`, `KIL`, `CAS`, `MON`, `LIM`, `GAL` and `SLI`.
- Porting notes: the provider would serve local-authority stations published by the EPA, not EPA
  stations. Provenance and attribution must name the owner of each station. The structure
  resembles `ba_fhmzbih`.

### 5.7 Germany, federal waterways: PEGELONLINE (`de_pegelonline`), Ready with a short window

- The Waterways and Shipping Administration (WSV) runs a clean REST API with WGS84 coordinates.
- Stations: `https://www.pegelonline.wsv.de/webservices/rest-api/v2/stations.json`, with 786
  stations, 94 of them with Q on 2026-09-22 (729 with coordinates).
- Values: `.../stations/{uuid}/Q/measurements.json?start=&end=`.
- The API serves only a rolling window of about 31 days. A 730-day request returned 31 days, and a
  request for 2015 returned `[]`.
- **Test (2026-08-10).** HELMINGHAUSEN `Q` returned 929 values from 31 July to 10 August, between
  0.9 and 1.52 m³/s.
- **Re-test (2026-09-22).** Three random Q stations returned the full 31-day window:
  - TROTHA UP on the Saale: 2,975 values
  - AKEN on the Elbe: 2,955 values
  - PFELLING on the Danube: 2,974 values

  Each also returned 0 values for January 2025.

### 5.8 Peru: SENAMHI (`pe_senamhi`), Limited

**Catalogue.** SENAMHI's GeoServer WFS:
`https://idesep.senamhi.gob.pe/geoserver/g_dbphisis/ows?service=WFS&version=1.0.0&request=GetFeature&typeName=g_dbphisis:estaciones_monitoreo&outputFormat=application/json`

- It returned 139 stations on 2026-09-22.
- By `variable`, they are `C` (caudal, 78), `N` (nivel, 44) and `A` (both, 17).
- Each has WGS84 `latitud` and `longitud`, basin, hydrographic region, department, province and
  district, the time of the last observation and a status.
- The station code is the suffix of the feature ID. For example `estaciones_monitoreo.4724A3F6`
  gives `4724A3F6`.

**Observations.** `POST https://www.senamhi.gob.pe/mapas/mapa-monitoreohidro/include/mnt-grafica-new.php`
with these form fields:

- `fecha_hora=<YYYY-MM-DD 23:59:59>`
- `btnTipo=D`
- `variable_opcion=<C|N|A>`
- `id=<code>`
- `rbtVariable=<CAUDAL|NIVEL>`

The response is HTML that embeds a JSON object with these keys:

- `codEstacion`, `nomEstacion`, `nomRio`, `variable`, `unidad`
- `fechaHora`
- `datoActual`, `datoAnterior`, `promHistorico`, `minimo`, `maximo`
- `rojo`, `naranja`, `amarillo` (alert thresholds)

The object feeds a hydrological-year chart running from 1 September to 31 August around the
`fecha_hora` anchor:

- `datoActual` holds the observed daily values of the anchor's hydrological year, up to the anchor
  date. It is the only series to use.
- `datoAnterior` holds the previous hydrological year, drawn on the current year's time axis, so
  its timestamps are shifted by one year.
- `promHistorico`, `minimo` and `maximo` are chart statistics, not observations.

A client therefore walks the anchor back one hydrological year at a time and reads `datoActual`.

**Test (2026-09-22).** Station 4724A3F6 (EL TIGRE, Río Tumbes), CAUDAL, in m³/s:

| Anchor | `datoActual` |
|---|---|
| 2026-09-21 | 21 values, September 2026 |
| 2023-03-15 | 196 values, 2022-09-01 to 2023-03-15, 12.3 to 738.6 m³/s |
| 2020-12-15 | 90 values from 2020-09-01; `datoAnterior` held 259 values of 2019/20 |
| 2019-03-15 | Empty |

The reachable record therefore begins in hydrological year 2019/20. hydrodownloadR uses
2020-09-01 as its first date.

**Re-test (2026-09-22).** The WFS returned 139 stations: 78 `C`, 44 `N` and 17 `A`, all with
coordinates inside Peru. Six random discharge stations were asked for five hydrological years
each:

- Paucartambo, Namora Bocatoma, Pte. Simón Rodríguez, Pte. Carretera Ilave, Vichaycocha and
  Chosica.
- All six returned 191 to 366 daily values per year for 2020/21, 2022/23 and 2024/25, and values
  for September 2026.
- Only Paucartambo also returned 2019/20 (366 days).
- The returned `codEstacion` always matched the request, and the unit was always `m3/s`.
- Chosica's 2020/21 year starts on 2020-12-16. Pte. Simón Rodríguez's 2020/21 year ends on
  2021-07-23.

**Earlier finding (2026-08-11), for context.** The historical portal
`https://web2.senamhi.gob.pe/descarga/?cod=<codigo>` embeds full daily series in a Highcharts
configuration without a login. For example, station 152204 returned 18,750 daily values from
1963 to 2014. All 293 stations on that map (`/maps/map_hist_data.php`) are meteorological,
however. Its CSV button requires a login with a CAPTCHA. The open-data portal entry
`datosabiertos.gob.pe` `f3c5e8e8-73bd-49dc-bb22-37c61ad40a04` was not checked.

**Porting notes.**

- The endpoint is public but undocumented, and it carries no quality fields. Send at most one
  request per second.
- The shared engine offers `year` and `year-month` window granularities. A September-to-August
  hydrological year may need a new window declaration, or year windows mapped onto anchors. That is
  a design question.
- The timestamps are epoch milliseconds on a chart axis. Their time zone and day definition are
  not stated.
- hydrodownloadR's licence label: Custom/Terms of Service (`restricted_terms`), at
  `https://www.senamhi.gob.pe/?p=terminos-condiciones`. hydrodownloadR's code comments quote a
  required source notice.

### 5.9 Afghanistan: USGS and USAID historical network (`af_usaid`), Limited

**Source.** USGS publishes historical Afghan gauge records, collected under USAID, through the same
Water Data API that `usgs_nwis` uses. They carry `agency_code=USAID` and `country_code=AF`.

**Catalogue.**
`https://api.waterdata.usgs.gov/ogcapi/v0/collections/monitoring-locations/items?agency_code=USAID&country_code=AF`
returned 151 sites: 149 `Stream` and 2 `Lake, Reservoir, Impoundment`.

- All 151 have `geometry: null`.
- hydrodownloadR decodes coordinates from the 15-digit site number, read as `DDMMSS DDDMMSS NN`
  (latitude, longitude, sequence). For example, `301700062020000` decodes to 30.283 °N,
  62.033 °E, which is the Helmand River at Char Burjak.
- These positions follow a numbering convention rather than a survey, and are at best precise to
  an arc-second. Record them as derived from the site number.

**Series.** `collections/time-series-metadata` with `parameter_code=30208` lists 149 daily Q series,
one per stream site.

- 39 series have begin and end dates. They start between the 1940s and the 1970s and end between
  the 1940s and the 1980s.
- 110 have no begin or end in the metadata.
- None ends after 1999.

**Test (2026-09-22).**

- The modern route,
  `collections/daily/items?monitoring_location_id=USAID-301700062020000&parameter_code=30208`,
  returned a first page of 5,000 rows starting 1948-09-30.
- The legacy route,
  `https://waterservices.usgs.gov/nwis/dv/?format=rdb&sites=301700062020000&agencyCd=USAID&parameterCd=30208&startDT=1940-01-01`,
  returned 11,190 daily values in m³/s, from 1948-10-01 to 1979-05-21, with approval codes `A`
  and `A:e`.
- **Re-test (2026-09-22).** All 151 site numbers decode to positions inside Afghanistan. Six
  random stream sites were downloaded in full, for example Arghastan River near Kandahar (6,573
  values, 1952 to 1979) and Paltu River near Sarafsar (1,067 values, 1949 to 1952). They held
  1,067 to 6,573 daily values between 1949 and 1980. The codes seen were `A`, `A:e` and `A:<`,
  where `A:<` marks values reported as less than the stated figure.

**Porting notes.**

- The packaged `usgs_nwis` catalogue (26,258 stations) contains none of these sites.
- The fetch path is the same as `usgs_nwis`. Serving Afghanistan could therefore be:
  - a catalogue extension of `usgs_nwis`, with the agency-qualified site IDs, or
  - a separate provider for clearer country attribution.

  This is a design decision.
- Parameter 30208 is already in m³/s, unlike the usual US parameter 00060 in ft³/s.
- hydrodownloadR's licence label: Public Domain (USGS policy).

### 5.10 Germany, Bavaria: GKD (`de_bayern`), Limited

- The Gewässerkundlicher Dienst Bayern lists 611 discharge station pages (2026-09-22). The 460
  counted on 2026-08-10 came from a narrower link pattern.
- **Catalogue.** `https://www.gkd.bayern.de/de/fluesse/abfluss/tabellen` (HTML, about 340 kB).
  Station links have the form `/de/fluesse/abfluss/{region}/{slug}-{id}`.
- **Observations.** 15-minute discharge in m³/s:
  `.../{region}/{slug}-{id}/messwerte/tabelle?beginn=DD.MM.YYYY&ende=DD.MM.YYYY`. The response is
  an HTML table with the columns `Datum` (`DD.MM.YYYY HH:MM Uhr`) and `Abfluss [m³/s]`, newest
  first. Arbitrary historical ranges work. Numbers use a decimal comma.
- **Coordinates.** Each station page shows `Ostwert` and `Nordwert` (UTM32N, for example `635008`
  and `5372619`) and `Einzugsgebiet`, the catchment area, for example `359,10`.
- **Test (2026-08-10).** Station achsheim-11944004 reprojects to 48.492 °N, 10.827 °E.
- **Re-test (2026-09-22).** The parser problem found on 2026-08-10 is solved: the
  `/messwerte/tabelle` path returns the complete table. Four random stations were tested.
  - Three returned complete months of 2,976 values for both May 2024 and January 2005:
    - Kempten: 46.9 to 331 m³/s in May 2024
    - Geschwend: 0.47 to 1.6 m³/s in May 2024
    - Weilheim: 11.4 to 68.9 m³/s in May 2024
  - Schmerold returned no rows for either period.
  - All four pages carried `Ostwert`, `Nordwert` and the catchment area.
  - The May 2024 request returned 01.05.2024 01:00 to 01.06.2024 00:45. The January 2005 request
    returned 01.01.2005 00:00 to 31.01.2005 23:45. The page does not state its time reference, so
    the one-hour offset in summer must be clarified before choosing window rendering.
  - A per-station `…/download` page and a download centre also exist and were not examined.
- Scraping breaks when the page layout changes, so keep polite pacing and parser tests.

### 5.11 Croatia: DHMZ (`hr_dhmz`), Limited, stage only

- **Source.** `https://hidro.dhz.hr/hidroweb/skripte/hisbaza.py`
- **Stations.** `?funkc=markeri&kkor=0&stip=1` returns 394 stations under the key `postaje`. Each
  has `sifra`, `gsirina` (latitude) and `gduzina` (longitude) in WGS84, and `ttip` (HTML with name
  and river).
- **Latest values.** `?funkc=zadnjipodaci&kkor=0` returns the fields `sifra`, `ime`, `sliv`, `vod`,
  `zterm` (`DD. MM. YYYY. HH:mm`) and `zpod`. `zpod` carries the value and unit, for example
  `263&nbsp;cm`.
- The response is a Python dictionary literal, not JSON. Parse it with `ast.literal_eval`.
- **Test (2026-08-10).** 211 stations reported stage in cm and none reported discharge. Treat the
  source as a stage provider.
- **Re-test (2026-09-22).** Same result: 394 stations, all with coordinates, and 211 latest values,
  all in cm.
- It serves the latest value only.

### 5.12 Italy, Emilia-Romagna: ARPAE (`it_arpae`), Limited

- **Source.**
  `https://dati-simc.arpae.it/opendata/osservati/portata_istantanea/portata_istantanea.json`.
  This region differs from the legacy Tuscany PR.
- The file is newline-delimited JSON records of the form
  `{version, network, ident, lon, lat, date, data:[{vars:{...}}]}`.
- Coordinates are integers divided by 100,000; `lon 1055893` is 10.55893 °E.
- It covers a rolling window of about 10 days. On 2026-08-10 the file was 2.1 MB with 4,784
  records.
- **Test (2026-08-10).** A Po gauge at 44.906 °N, 10.559 °E returned 959 values, between 196 and
  227 m³/s.
- **Re-test (2026-09-22).** 4,787 records from 2026-09-12 09:45 to 2026-09-22 09:15, for 7 gauges.
  Each record names its station (`B01019`, for example Boretto, Pontelagoscuro, Piacenza, Sermide)
  and gives discharge as `B13226`.
  - Three gauges have 959 records (15-minute) and four about 478 (30-minute).
  - Boretto ranged from 688 to 1,079 m³/s.

### 5.13 Bulgaria: NIMH (`bg_nimh`), Limited

- **Source.** `https://info.meteo.bg/openData/river-runoff/`, one POST per day with
  `mydate=YYYY-MM-DD`.
- The response is an HTML table with columns `№ | Река | Местност | Qmin | Qср | Qmax | H(cm) | Q(m³/s) | ΔH`.
  Numbers use a decimal comma.
- **Re-test (2026-09-22).** 15 dates were tested. Every date from 2026-06-15 to 2026-09-21 gave 68
  rows, with 64 to 68 numeric discharge values. 2026-06-10 and earlier were empty, so the window is
  about 100 days. On 2026-08-01 the rows existed, but the H, Q and ΔH cells read `n.a.`.
- There are no coordinates. The port needs a separate station-coordinate source.
- **Test (2026-08-10).** Station 14840 (Лом) returned 3 daily values of 0.249 m³/s.

### 5.14 Germany, Baden-Württemberg: LUBW HVZ (`de_bw`), Limited

- **Source.** The state flood-forecast centre publishes the station list and latest values as a
  JavaScript file: `https://www.hvz.baden-wuerttemberg.de/js/hvz_peg_stmn.js` (about 200 kB).
- The file defines the array `HVZ_Site.PEG_DB`, with one array of 72 fields per station.
  - Fields 4 and 5 are stage and its unit; 7 and 8 are discharge and its unit.
  - Fields 18 and 19 are Gauss-Krüger coordinates, 20 and 21 WGS84 longitude and latitude, and 22
    and 23 UTM32.
  - Times carry `MESZ`. The file's text is UTF-8.
- It holds the latest value only. A series has to be built by repeated polling. History exists
  only as GIF plots.
- **Test (2026-08-10).** 334 stations, 250 with a live Q, for example Diepoldsau at 71.6 m³/s.
- **Re-test (2026-09-22).** 334 rows: 251 with a current Q, 305 with a current stage, and WGS84
  coordinates for 331 inside a 7 to 11 °E, 47 to 50 °N box.

### 5.15 Bulgaria, Danube: EAEMDR/APPD (`bg_appd`), Limited

- **Source.** The Danube Exploration and Maintenance Agency publishes an HTML table at
  `https://appd-bg.org/hidrology-en`. Its columns are station, km, water level (cm), discharge
  (m³/s), 24-hour change and water temperature.
- It holds current values only. The table had 22 rows on 2026-08-10 and 21 on 2026-09-22, of which
  6 had a discharge value.
- Stations are located by river kilometre, not coordinates, so a coordinate source is needed.
- **Test (2026-08-10).** 6 gauges returned discharge between 1,429 and 1,586 m³/s. For example,
  Novo Selo reported 1,429 m³/s at 26.6 °C.

### 5.16 Rwanda: Rwanda Water Resources Board (`rw_rwb`), Limited

- **Source.** `https://waterportal.rwb.rw`, a Drupal 8 site.
- **Catalogue.** `/data/surface_water` has an HTML table with 90 `Hydrology Station` rows. The
  columns are location name, identifier, type, longitude, latitude and SRID (4326).
- **Observations.** `/location_ng_info/<Identifier>` shows a field-visit table with the columns
  Date, Parameter (`Discharge` in m³/s, or `Stage` in m), Unit and Value. Timestamps carry a
  +02:00 offset.
- **Test (2026-09-22).**
  - `196101` (Gisenyi-Sebeya) returned 23 discharge and 23 stage visits, starting 1950-05-07 with
    3.22 m³/s and 0.555 m.
  - `221001` (Kagitumba) returned 98 of each, from 1970-12-17 to 2023-08-30.
- **Limitation.** The continuous series are behind "Download data" links (`/location/<hash>`),
  which lead to a form asking for:
  - start and end dates
  - full name, email and telephone
  - organisation and intended use

  The form also has an anti-bot guard. It was not submitted, and hydrodownloadR does not use it
  either.
- **Telemetry (found 2026-09-22 from the Africa and Asia sweep).** The real-time page
  `/data/real_time_data` lists 40 series as radio buttons, with values such as
  `HG.Telemetry@SW29@246ad77e16cf44d6a95ddd277a8bcf4d`. `HG` is stage, `SW29` the location
  identifier, and the last part an AQUARIUS time-series ID.
  - `POST https://waterportal.rwb.rw/index%2ephp/getDataTimeSerieAjaxNg/<value>` with an empty body
    returns JSON with three keys:
    - `info`: location name, identifier, WGS84 latitude and longitude, and UTC offset (+2)
    - `data1`: the last 24 hours
    - `data2`: the last 4 days
  - **Test.** SW29 (Kinamba) returned 138 values in `data1` and 426 in `data2`, at 15-minute
    spacing, from 2026-09-18 00:00 to 2026-09-22 10:15. The first value was 0.477 m.
  - 35 of the 40 series returned data.
- **Re-test (2026-09-22).**
  - Telemetry: again 35 of 40 series returned data, with 107 to 1,291 values each over 4 days.
  - Field visits at 8 random stations were uneven:
    - SW27, SHELL and Shyembe had none.
    - Gashora and Gisenyi-Kivu had only 2 and 1 stage visits.
    - Rusumo had 10 visits (1987 to 1998), Ruliba 151 (1955 to 2020) and Nyundo 216 (1972 to
      2024).
  - 87 of the 90 station coordinates fall inside Rwanda.
- **Porting notes.** Field visits are irregular spot measurements. They must be declared as such,
  not as a continuous daily or sub-daily series. The telemetry is a separate product: 15-minute
  stage in a rolling 4-day window. hydrodownloadR classifies access as `public_clickthrough`, with
  the portal disclaimer at `https://waterportal.rwb.rw/about_us`.

### 5.17 Türkiye: DSİ flow-observation yearbooks (`tr_dsi`), Limited

- **Source.** The State Hydraulic Works (DSİ) publishes its flow-observation yearbooks
  (*Akım Gözlem Yıllıkları*) at `https://www.dsi.gov.tr/Sayfa/Detay/744`. The files are served from
  `cdniys.tarimorman.gov.tr`.
  - 28 RAR archives cover DSİ 1959 to 2015 and former EİE 1935 to 2011.
  - One ZIP covers 2016 to 2020.
  - One PDF covers 2021.
- **Test (2026-09-22).** `20162020_akim_gozlem_yilliklari.zip` (42.6 MB) contains `DSI_2016.pdf` to
  `DSI_2020.pdf`. `DSI_2020.pdf` has 1,006 pages, and 948 of them are station pages.
  - The PDFs have a text layer, so no OCR is needed.
  - A station page gives the station code (for example `D02A088`), river and site, location with
    coordinates in degrees, minutes and seconds, and catchment area.
  - It also gives the observation period, mean and extreme flows, and a rating table (stage in cm
    to discharge in m³/s).
  - It ends with a table of daily discharge in m³/s for the water year (1 October to 30 September),
    one row per day and one column per month.
- **Porting notes.**
  - This is a `BulkStore` source: download each yearbook, extract the text and parse the daily
    tables.
  - **Re-test (2026-09-22).** Page images were sampled in each volume to tell scans from
    born-digital text:
    - 1997 to 2021 are born-digital text, with at most 2 image pages in about 21 sampled pages.
    - 1996 is a scan (21 of 21 sampled pages are images).
    - 1959 and 1972 are scans with an OCR text layer. The OCR has visible errors, such as
      `KPLLAHILABİLİR rtASAT SURESİ` and garbled coordinates, so those volumes cannot be trusted
      without checking.
    - 1973 to 1995 and the EİE archives were not checked.
  - In the 2020 volume a simple row parser read 736 of 948 station tables completely (366 daily
    values each, correct for the leap year).
  - The other tables contain two source flags that a parser must keep: `KURU` (dry, 17,003 cells
    in the volume) and `------` (9,122 cells).
  - The 2011 to 2015 archive contains `dsi_2011.pdf` to `dsi_2013.pdf` and `DSİ_2014.pdf` and
    `DSİ_2015.pdf`. The file names contain a dotted capital İ, so archive extraction must be
    Unicode-safe.
  - The table layout must be validated per volume, because a parsing error would silently shift
    values between days.
  - Real-time data and requests go through e-Devlet, which requires a Turkish identity login. That
    route is out of scope.

### 5.18 Indonesia, East Java: SIH3 (`id_jatim`), Limited

- **Source.** The East Java provincial water-resources agency (Dinas PU Sumber Daya Air) runs the
  SIH3 hydrological information system at
  `https://sih3.dpuair.jatimprov.go.id/main/data_telemetri`. It also relays data from the Brantas
  and Bengawan Solo river-basin agencies (BBWS) and the state operator PJT 1.
- **Catalogue.** These routes need the header `X-Requested-With: XMLHttpRequest`:
  - `GET /main/get_jenis/1` lists the data types for master type 1 (hydrology). Examples: 89
    `Data Debit Sungai PU SDA` (river discharge, m³/s), 21 `Pos Duga Air WS Brantas PJT 1` (stage,
    m) and 45 `Pos Duga Air Jam-jam an PU SDA` (hourly stage).
  - Types 84 and 85 are forecasts (*prediksi*). They are model output and must be excluded.
  - `GET /main/get_data_pos/<type>` lists stations, with `lat`, `long`, `kode` and `judul` (name).
    Type 89 has 22 stations and type 21 has 24.
  - Other stage types include 20 (3 stations), 31 (71), 45 (24), 15 (24, in cm), 17 (36, in `mdpl`,
    metres above sea level) and 80 (4). All coordinates fall inside East Java.
- **Values.** `POST /main/data_telemetri_store` takes a form with these fields:
  - the page's `_token` (a session-bound CSRF token)
  - `master_id=1`, `jenis_data_id=<type>` and `data_id=<station>`
  - `awal[jam]` and `akhir[jam]` (dates), plus `tgl1[jam]=0` and `tgl2[jam]=23` (hours)

  The response is JSON with `hasil.labels` (for example `21/09/2026 Jam : 0`) and
  `hasil.datasets[].data`.
- **Test (2026-09-22).** Station 4745 (Dhompo, S. Welang), discharge:
  - 21 September 2026 returned 24 hourly values.
  - July to August 2026 returned 1,475.
  - January 2024 returned 624, starting at 8.39 m³/s.
  - Station 1233 (AWLR Sengguruh), stage, returned 225 hourly values for January 2023.
- **Re-test (2026-09-22).**
  - **Only 3 of the 22 discharge stations return data:** Dhompo, Selowongko and Purwodadi, all on
    the Welang river. Each of the three returned 480 or 129 hourly values for September 2026 and
    619 to 744 for January 2025 and January 2024. The other 19 returned nothing in all three
    periods.
  - Stage coverage is uneven. Of 21 random stage stations across 7 types:
    - some returned data only for 2024 (Nambangan, the BBWS Brantas stations, Dam Jati);
    - some only for 2026 (Gadang, Gunungsari, J. Winongan);
    - some for both (Selowongko, Dhompo, Ngrembang).
  - AWLR Lahor (type 21, unit `m`) read 270.0 to 272.9 in March 2024 and 2.67 to 2.68 in
    September 2026. The values change by a factor of about 100 without a change of stated unit.
  - Type 31 returns daily labels (`01/09/2026`), not hourly ones.
- **Porting notes.**
  - Fetch must first load the page to get a session cookie and token.
  - Timestamps are hour labels with no stated time zone.
  - Label time zone and daily definitions as unknown.

### 5.19 Somalia: FAO SWALIM flow archive (`so_swalim`), Limited

- **Source.** FAO's Somalia Water and Land Information Management project (SWALIM) publishes the
  Somalia National River Flow Archive at `https://snrfa.faoswalim.org/`, with a live river-level
  page at `https://frrims.faoswalim.org/rivers/levels`.
- **Catalogue.** The archive home page has a table of 11 stations on the Juba (JB) and Shabelle
  (SH) rivers. Columns: station number, name, river, status, first date, last update, level,
  flood-risk thresholds, maximum depth, width and flow, elevation, latitude and longitude.
  - For JB001 (Luuq) the column labelled Latitude holds 42.54 and the one labelled Longitude holds
    3.79.
  - Luuq lies at about 3.8 °N and 42.5 °E, so the two columns appear transposed.
- **Values.** `/stations/<id>/` (for example `/stations/jb001/`) embeds the whole record as
  JavaScript arrays of `[epoch_ms, value]` pairs. The page is about 16 MB.
  - The arrays are `level_daily`, `flow_daily`, `level_mean`, `level_max`, `level_min`, `flow_pot`
    and three flood thresholds.
  - Only `level_daily` and `flow_daily` are observations. The others are statistics or thresholds.
- **Test (2026-09-22).** JB001 (Luuq) had:
  - `level_daily`: 19,515 values from 1951-03-25 to 2026-09-22, in 64 distinct years, with a
    maximum of 7.0 m
  - `flow_daily`: 19,473 values over the same span, with a maximum of 1,824.6 m³/s
- **Re-test of all 11 stations (2026-09-22).**

  | Station | Status | Daily stage | Daily Q |
  |---|---|---|---|
  | JB001 Luuq | Functional | 19,515, 1951 to 2026 | 19,473, 1951 to 2026 |
  | JB002 Bardheere | Non Functional | 13,739, 1963 to 2023-11 | 13,739, 1963 to 2023-11 |
  | JB004 Kaitoi | Non Functional | 3,002, 1963 to 1979 | none |
  | JB009 Dollow | Functional | 3,773, 2015 to 2026 | none |
  | JB010 Bualle | Non Functional | 5,757, 2008 to 2024-03 | none |
  | SH001 Belet Weyne | Functional | 17,940, 1963 to 2026 | 17,147, 1963 to 2026 |
  | SH002 Bulo Burti | Functional | 14,926, 1963 to 2026 | 13,210, 1963 to 2021 |
  | SH003 Mahadey Weyne | Non Functional | 7,059, 1963 to 1990 | none |
  | SH004 Jowhar | Functional | 9,710, 1999 to 2026 | none |
  | SH006 Afgoi | Non Functional | 8,973, 1963 to 1990 | none |
  | SH007 Audegle | Non Functional | 5,140, 1963 to 1990 | none |

  **Discharge exists at 4 stations only.** The latitude and longitude columns are transposed for
  all 11.
- **Porting notes.**
  - Provenance needs confirming. SWALIM is an FAO project, not the national ministry.
  - The archive states the stations' status (for example "Non Functional" for JB002), which should
    be kept as a source fact.

### 5.20 South Africa, Inkomati-Usuthu: IUCMA river operations (`za_iucma`), Limited

- **Source.** The Inkomati-Usuthu Catchment Management Agency runs
  `https://riverops.iucma.co.za/`, built by DHI. The host is not `dws.gov.za`, whose paths returned
  403 in the sweep.
- **Catalogue.** `POST /api/Service/ListChartSites` with the JSON body
  `{"parameters":"flow|current"}` or `{"parameters":"flow|historical"}`:
  - `current` returned 62 series at 31 stations. The provider is IUCMA, and the series are
    `<station>_Flow_FW_Primary` and `_Level_FW_Primary`.
  - `historical` returned 237 series at 83 stations. The provider is `DWA`, with names such as
    `W5H001_Flow_Daily` and `_Flow_Primary`.
  - Station IDs are DWS station numbers such as `W5H022` and `X1H001`.
  - The service returns no coordinates. The `za_dws` catalogue in this repository has them, for
    example W5H022 at −27.065, 30.994.
- **Values.** `POST /api/Service/GetTimeseriesDataForChart` with the body
  `{"parameters":"<timeseries_id>"}` returns `[[epoch_ms, value], …]`. The route
  `GetTimeseriesDataForTable` returns the same values as records.
- **Test (2026-09-22).**
  - `W5H022_Flow_FW_Primary` returned 4,000 values at 12-minute spacing, from 2026-03-15 to
    2026-08-31, between 0.417 and 9.154 m³/s.
  - The daily DWS series `W5H005`, `W5H006` and `W5H008` returned 3,277 to 3,492 valid values each
    within 4,000 points from 2012 to 2023.
  - Five of eight DWS daily series returned only nulls or −999.
  - Every response held exactly 4,000 points. That looks like a fixed limit, but it is not
    established.
- **Re-test of every series (2026-09-22).**
  - Current: all 62 series (31 discharge, 22 water depth, 9 water level) returned values; 61 end
    in 2026. All 62 responses held exactly 4,000 points.
  - Historical (provider `DWA`): 175 of 237 series returned values (154 discharge, 21 water
    depth). They end between 2013 and 2023, most in 2022 or 2023.
  - `POST /api/Service/GetTimeSpanDataForChart` with `{"TimeSeriesId": …, "TimeSpan": 5}` returned
    346 values from 2024-04-01, spaced daily or wider. It is not a way to get more than 4,000
    fine-resolution points.
- **Porting notes.**
  - This is a possible route to observations for part of South Africa, where `za_dws` currently
    serves the catalogue only.
  - Treat −999 as the source's missing-value marker, as a published fact, not a guess.

### 5.21 Armenia: daily hydrological bulletins (`am_hmc`), Limited

- **Source.** The Hydrometeorology and Monitoring Center publishes daily bulletins at
  `https://armmonitoring.am/page/79`. The page links 266 PDFs, for example
  `/public/admin/ckfinder/userfiles/files/hydro-2025/hydro-02_10_2025.pdf`. File names are
  irregular.
- **Test (2026-09-22).** `hydro-02_10_2025.pdf` has 2 pages with a text layer.
  - Its table gives river, gauge, dangerous discharge and the long-term monthly mean, maximum and
    minimum.
  - It also gives discharge in m³/s at 08:00 and 20:00 on the previous day and at 08:00 on the
    bulletin day.
  - It has 44 numbered rows, up to number 46. The first is Pambak at Vanadzor, 3.18 m³/s.
  - Reservoir volumes are also listed.
- **Re-test (2026-09-22).**
  - Of the 266 links, 217 carry a date in the file name, and 49 do not (for example
    `2025-12-05 - 2025-12-10.pdf`, `hydro-07_08_025.pdf`).
  - The dated ones fall almost entirely in March to December 2025, with 13 to 31 per month. There
    is one each for November 2015 and January 2024. None are from 2026.
  - Ten random bulletins downloaded, all HTTP 200. Eight have a text layer with 41 to 43 numbered
    station rows, up to number 46. Two (`Hydro 29_06_2025.pdf`, `hydro-11_09_2025.pdf`) are scans
    with no text.
  - Each bulletin also gives the same date a year earlier, for comparison.
- **Porting notes.** There are no coordinates, so a station source is needed. The long-term
  statistics in the table are not observations. Scanned bulletins would need OCR, which is out of
  scope.

### 5.22 Georgia: National Environmental Agency (`ge_nea`), Limited, stage only

- **Stations.** `https://meteo.gov.ge/Ge/Hydrology/GetRiversPin` returns JSON for 19 stations. Each
  record has the station ID and name (with warning thresholds in the name), river, WGS84
  coordinates, elevation, date of the last measurement and warning state.
- **Values.** Station pages at `https://meteo.gov.ge/Ge/River/<n>` list one row per day: station,
  date, water level in cm and state.
  - **Test (2026-09-22).** Page 22 held 1,614 daily values from 2022-03-03 to 2026-09-22. It
    belongs to Tskhenistskali – Luji, and the last value was 298 cm.
  - Other pages held 1,611 to 1,621 values.
- **Page numbers and station IDs.** Page numbers do not match the JSON station IDs. JSON ID 22 is
  Mtkvari – Tbilisi, but page 22 shows Tskhenistskali – Luji.
- **Re-test (2026-09-22).** Pages 1 to 60 were fetched:
  - All 60 returned data, and together they show exactly the 19 stations of the JSON, each under
    two to four page numbers. For example Pshavis Aragvi appears on pages 1, 2, 3 and 50.
  - A port can therefore key stations by the name printed on the page and join to the JSON by name.
    Page 55 holds a single stray row for Acharistsqali – Keda; page 57 holds the full series.
  - Each station has about 1,580 to 1,620 daily rows from February to May 2022 onward, and 9 to 24
    dates that appear twice.
  - Mashavera – Kazreti ends on 2025-11-10.
  - According to the sweep, longer archives are a paid service.

### 5.23 Côte d'Ivoire: Direction de l'Hydrologie (`ci_dh`), Limited

- **Stations.** `GET https://api.hydrologie-ci.org/report/stations/all` returns 35 stations. Each
  has a station number and reference, name, river, catchment area, WGS84 latitude and longitude,
  and flood and low-water thresholds.
- **Values.**
  - `GET /report/daily/<stationNumber>` returns daily records.
  - `GET /report/instant/<stationNumber>` returns instantaneous records.
  - Each record has `stationCode` (for example `1093501010`), `valueDate`, `initialValue`,
    `currentValue`, `validityCode` and `measureName`.
- **Test (2026-09-22).** 25 of the 35 stations returned daily rows, covering 2026-08-26 to
  2026-09-21. Only **11 stations have daily discharge** (`Débit PCD`); the others have stage, rain
  or temperature only. 26 stations returned instantaneous rows for the last day.
  - The measure types were `Hauteur Eau PCD` (stage, 501 rows), `Débit PCD` (discharge, 283 rows),
    `Pluie` (rain), `Température Eau` and `Température Air RLS`.
  - Station 287 (Agboville Barrage) had 54 daily rows and 65 instantaneous rows, the latter from
    2026-09-21 09:00 to 2026-09-22 07:00.
- **Porting notes.**
  - Units are not given in the records, so they must come from a published source before porting.
  - Several routes (`/report/daily`, `/report/stations/latest`) returned HTTP 500 without a station
    number.
  - The portal's archive downloads need a login and payment and are out of scope.

### 5.24 Niger basin: Niger Basin Authority SATH (`ne_abn_sath`), Limited

- **Source.** The Niger Basin Authority's satellite monitoring and forecasting site,
  `http://www.sath.abn.ne/Hydrology_EN.html` (HTTP only).
- **Stations.** `http://www.sath.abn.ne/VectorLayers_Hydro.js` embeds 91 points with `X`, `Y`
  (WGS84), `Station` and `Station_ID`. The IDs are 10-digit ORSTOM codes, such as `1271500142`.
- **Values.** Observed series are `Hydromet/Q_<Station_ID>.csv` (`date,discharge`) and
  `Hydromet/H_<Station_ID>.csv` (`date,waterLevel`). The `LSHM/Q_<id>.csv` files hold model output
  and must be excluded.
- **Test (2026-09-22).** All 90 Q and 90 H files answered. 12 stations had data rows, and the rest
  held only a header.
  - Examples: Koulikoro (1 June to 19 July 2026, Q from 84.1 to 737.7 m³/s) and Niamey (1 June to
    11 August 2026, Q from 123 to 687 m³/s).
  - Also Makurdi (21 June to 10 August 2026, Q up to 7,317.58 m³/s).
- **Re-test (2026-09-22).** All 91 station IDs are unique. The same 12 Q files hold rows (30 to 72
  each), all starting between 2026-06-01 and 2026-06-25.
- **Porting notes.** The files cover only the current season, and the latest dates were between 12
  July and 11 August. The Niger-HYCOS system of the same authority is described in section 6.4.

### 5.25 Niger: SLAPIS (`ne_slapis`), Limited

- **Source.** SLAPIS, the flood early-warning system of Niger's Direction de l'Hydrologie, run with
  CNR-IBE (Italy). Its API documentation is at `https://slapis-niger.org/fr/pag_geoservices`.
  - The API is hosted on `http://slapis.fi.ibimet.cnr.it:8080/SlapisWS/api`, a CNR server.
  - Provenance needs confirming for that reason.
- **Stations.** `/vector/j_get_stations_geojson` returns 8 GeoJSON points with `_id_station`,
  `stat_name` and `stat_id_str`. They include Niamey (ID 8, `PLL05418`), Garbey Kourou (ID 1),
  Bossey Bangou (ID 2), and five more numbered 1. to 5., such as `1. Tallé`.
- **Values.** `/data/j_get_stations_data/csv/<id_station>/<label>/<year>` returns
  `date, hour, depth, Q` for one calendar year. `-999.0` marks missing values.
- **Test (2026-09-22).**
  - Niamey 2025: 8,760 hourly rows, 8,651 of them not −999. The first row was 597 (depth) and
    1,880.2 (Q).
  - Garbey Kourou and Bossey Bangou had data in 2020 and 2022 but none in 2025 or 2026.
- **Re-test (2026-09-22).** Non-missing hours per year for all 8 stations:
  - Niamey: 5,878 (2020), 7,346 (2022), 8,774 (2024), 8,651 (2025) and 5,258 (2026 so far).
  - Garbey Kourou: 5,678, 7,632 and 1,712 for 2020, 2022 and 2024.
  - Bossey Bangou: 7,560 and 5,958 for 2020 and 2022.
  - The five other listed stations: none in any year.
- **Porting notes.** Units of `depth` are not stated in the response. The values look like
  centimetres, but that must be confirmed from the documentation.

### 5.26 Sri Lanka: Irrigation Department (`lk_irrigation`), Limited, stage only

- **Source.** A public ArcGIS feature service behind the Irrigation Department's flood dashboard:
  `https://services3.arcgis.com/J7ZFXmR8rSmQ3FGf/arcgis/rest/services`.
- **Stations.** `hydrostations/FeatureServer/0` has 42 features, with station name, latitude and
  longitude.
- **Values.** `gauges_2_view/FeatureServer/0/query` has these fields: `basin`, `gauge`,
  `water_level`, `rain_fall`, `CreationDate`, and the alert, minor and major flood levels.
- **Test (2026-09-22).** 6,454 rows. A page of 1,000 rows covered 40 gauges from 2026-09-15 09:30
  to 2026-09-16 11:30. Siyambalanduwa read 0.13; the reading table does not state the unit.
- **Re-test (2026-09-22).** Paging through the whole layer gave 6,455 readings from 40 gauges, 84
  to 180 each, between 2026-09-15 10:30 and 2026-09-22 09:41. None were null. All 40 gauge names
  match a station name in `hydrostations`, whose fields include `Unit`, the alert and flood levels
  and `Elivation_m_MSL`.
- **Porting notes.**
  - The window is about 7 days.
  - Paginate with `resultOffset`.
  - Gauges are matched to stations by name.

### 5.27 Malaysia: Public InfoBanjir (`my_jps`), Limited, stage only

- **Source.** The Department of Irrigation and Drainage (JPS) at
  `https://publicinfobanjir.water.gov.my`.
- **Stations and latest values.**
  `/index.php/aras-air/data-paras-air/aras-air-data/?state=<code>&district=ALL&station=ALL&lang=en`
  returns an HTML table with these columns:
  - station ID, name, district, main basin, sub-basin
  - last update, water level in m
  - the normal, alert, warning and danger thresholds

  The 16 state tables listed 576 stations on 2026-09-22 (Putrajaya 0, Sarawak 107, Johor 84,
  Selangor 63).
- **Values.**
  `/wp-content/themes/enlighten/query/getwaterlevellast7dayslead.php?extra=&station=<graph id>`
  returns JSON: `info` (name, thresholds, count) and `values[]` with `dt`, `clean`, `raw`, `ecm`,
  `final` and `severity`.
  - **The station parameter is the ID from the row's graph link** (`/index.php/wl-graph/?stationid=…`),
    not the table's station ID. For example, table ID `3516423` has graph ID `3516026_`, and table
    ID `1536413` has graph ID `KGLAUT`. Only 22 of 350 checked rows use the same ID in both. The
    table IDs return "No result".
  - **Test (2026-09-22).** Station 3516026 returned 2,224 values from 2026-09-15 00:00 onwards.
  - **Re-test (2026-09-22).** Six random stations, using graph IDs, each returned a grid of 2,243
    slots at 5-minute spacing over 7 days. Many slots hold `-9999`:
    - Sg. Langat at Dengkil: 684 slots with severity `SL_NML` and 1,558 with none.
    - Sg. Skudai at Kg. Laut: 242 slots with `SL_NML`.
    - Sg. Sembrong: 1,454 slots with severity `ERROR`.
    - Sg. Triang: 2,176 slots with `SL_NML`.

    `-9999` and `ERROR` are source states and must be kept as such.
  - The date-range route `searchresultwaterleveldtlead.php` returned "No result" for January 2024.
- **Porting notes.**
  - The window is 7 days, and the table has no coordinates.
  - The four value columns are source versions of the same reading. Keep them distinct, and use
    none as a substitute for another.
  - About 17 state portals (for example Sarawak iHydro) were not examined.

### 5.28 Philippines: DOST-ASTI PhilSensors (`ph_philsensors`), Limited

- **Values.** `https://philsensors.asti.dost.gov.ph/station/monitoring` returns JSON with
  `data_water` and `data_rain`.
  - `data_water` has 53 stations with station ID, region, province, location, type and alert
    thresholds.
  - Hourly values sit under keys `0` to `24`.
  - **Test (2026-09-22).** 1,197 non-empty hourly cells across the 53 stations. On re-test every
    station had at least 2 and at most 25 hourly values.
- **Terms.** The PhilSensors data-request page says that released data are for non-commercial
  research, academic and disaster-management use. It also says the data may not be sold,
  sublicensed or redistributed, and that release is under a signed end-user licence. Check this
  against RivRetrieve's model before porting.
- **Porting notes.** There are no coordinates in the response. The window is 24 hours.

### 5.29 Namibia, Okavango basin: OKACOM decision-support system (`okacom`), Limited

- **Source.** `http://dss.okacom.org`, run by the Permanent Okavango River Basin Water Commission.
- **Routes.**
  - `GET /api/surveyviewer/getsurveys?adminView=false&isAnalysisAndImpact=false` lists the surveys.
    Survey 13 is "Verified monitoring station time series".
  - Its views include 31 `vw_ts_verified_level_daily` and 43 `vw_ts_verified_level`.
  - `GET /api/surveyviewer/GetSurveyViewLocationData?surveyViewId=31&filters=&mapSeriesColorColumn=`
    returns the site locations.
  - `GET /api/surveyviewer/GetSurveyViewData?surveyViewId=31&filters="siteid"='5180'&columns=*`
    returns the daily records.
- **Test (2026-09-22).** Two sites in Namibia:
  - Rundu (5180) had 391 daily rows from 2022-11-01 to 2023-11-28, each with `max`, `min` and
    `average`. The average ranged from 3.46 to 6.09 m.
  - Nkurenkuru (5172) covered the same period.
- **Re-test (2026-09-22).** The level views hold the same two sites: 74,709 rows in the logged
  view (`vw_ts_verified_level`), 782 in the daily view and 26 in the monthly view.
- **Porting notes.** The daily average is a source-computed statistic of the logged values, and
  should be recorded as such. The network is very small.

### 5.30 Zambia and Zimbabwe: Zambezi River Authority (`zra`), Limited

- `https://www.zambezira.org/hydrology/river-flows` has three HTML tables for Chavuma, Ngonye and
  Victoria Falls (Nana's Farm). Each gives daily flow in m³/s for the current and previous
  hydrological year.
- **Test (2026-09-22).** 14 days, 3 to 16 September 2026, for example Chavuma 129 m³/s on
  3 September. On re-test the three tables held 42 daily rows in total (3 stations × 14 days).
- The page states no coordinates, and each table covers only two weeks.

### 5.31 Eswatini and South Africa, Komati: KOBWA (`kobwa`), Limited

- `https://www.kobwa.co.za/water/reports/` shows "River gauging stations information (24hr
  Average)" for 10 weirs, for example `0000X1H001 Hooggenoeg Weir 29.909 m3/s`.
- **Test (2026-09-22).** 10 values, latest only. On re-test, later the same day, several values
  had changed (Hooggenoeg 29.909 to 25.095 m³/s), which confirms the page is updated.
- Codes such as `X1H001` are DWS station numbers, and the `za_dws` catalogue gives their
  coordinates. `KOB…` codes need another source.

### 5.32 Indonesia, Jakarta: flood posts (`id_jakarta`), Limited, stage only

- `https://poskobanjir.dsdadki.web.id/` shows an HTML table with location, river, water height in
  cm, change, date, time and alert status.
- **Test (2026-09-22).** 38 stations, for example Posko SDA Palmerah on Kali Grogol, 67 cm at
  15:40. On re-test all 38 rows carried the current date, with a new time (17:20).
- It shows the latest value only and has no coordinates.

### 5.33 China, Lancang: Lancang-Mekong cooperation platform (`lmc`), Limited, stage only

- `https://lm-sjzyml-p.oss-cn-hongkong.aliyuncs.com/lmdata/station.json` is loaded by
  `https://www.lmcwater.org.cn/water_information/hydrological_data/`.
- **Test (2026-09-22).** Two stations:
  - Yunjinghong (90201600): 536.060 m
  - Manan (90215600): 533.240 m
- Each record has hourly rain, and the flow field is `-`. The data source field reads 中国水利部
  (Ministry of Water Resources).
- It holds the latest value only and has no coordinates.

### 5.34 Cambodia: National Flood Forecasting Centre (`kh_nffc`), Limited, feed stopped

- `https://www.nffc.dhrw-cam.org/stations/<STATION>.csv`, for example `stations/PEAM.csv`, has the
  columns `STATION_ID`, `TIME_TAG`, `date_time`, `rf`, `wl`, `alarm` and `flood`.
- **Test (2026-09-22).** The page lists seven stations in the Pursat basin. All seven files
  downloaded:
  - DAP BAT, KANDEING, PEAM and VEAL VENG each hold 62 to 64 rows at 15-minute spacing, all on
    27 February 2023. PEAM's stage runs from 1.57 to 0.17.
  - KBAL HONG, PREY KHLONG and SANG TRE hold a header and no rows.
  - The server reports `Last-Modified: Mon, 27 Feb 2023 08:47:55 GMT` for `PEAM.csv`.
- Each file holds a single day, so earlier days are not retrievable either. As a provider, this
  source would serve the same day indefinitely. Keep it as a lead in case the feed restarts. It is
  not worth porting as it stands.

---

## 6. Sources that cannot be used now

### 6.1 Summary

| Country | Source | Gate failed | Reason |
|---|---|---|---|
| Ukraine | UHMC automatic posts | Retrieval | No data endpoint found; stage only |
| Russia | АИС ГМВО and successors | Retrieval, provenance | Decommissioned, login-gated, then moved behind Russian-certificate TLS (see 6.3) |
| Bolivia | INE NADA catalogue | Retrieval | `catalog/209?format=json` returns HTML; `/download/<id>` returns HTTP 500 |
| Ecuador | INAMHI | Retrieval, observed data | Observations only in PDF yearbooks; the CSFS connector serves GEOGLOWS model output (19 virtual stations flagged ESTIMATED) |
| Venezuela | INAMEH | Retrieval | PDF bulletins and an interactive map (`ajax/ajax_aguas.php`); no historical API |
| Panama | ACP data via Smithsonian STRI | Provenance | Static ZIP redistributed by STRI. Check whether ACP publishes directly |
| Vietnam | UK CEH/EIDC study | Provenance | Research archive of 4 stations |
| Pakistan | IRSA/WAPDA | Observed data | About 15 dam inflow and outflow points, not river gauges |

### 6.2 Ukraine

- **Automatic hydrological posts** of the Ukrainian Hydrometeorological Center. The page is
  `https://www.meteo.gov.ua/en/Dani-avtomatichnikh-hidrolohichnikh-postiv`.
  - The station list is usable: `https://www.meteo.gov.ua/en/_hydro-autoposts.js` defines
    `HYDRO_AUTOPOSTS`, with 80 posts, their coordinates, rivers and basins.
  - The data are hourly water level, not discharge.
  - The data table is filled by a JavaScript widget. Direct requests (`?P=<id>&dt=<hour>&date=<…>`)
    returned only the empty table.
  - `/_/m/<id>.js` is the meteorological widget, not water level.
  - To revisit this source, capture the widget's request in a browser after selecting a post and
    a date.
- **Other Ukrainian sources.**
  - The discharge archive at the Central Geophysical Observatory (CGO) Sreznevskyi has 328 river
    posts with records back to 1808. It is available only on paid request.
  - The daily hydrological page on `meteo.gov.ua` is operational only.
  - The Osypov 2025 "Land & Water" dataset is SWAT model output.

### 6.3 Russia (assessed 2026-08-10)

The assessment started from Zenodo [10.5281/zenodo.8432070](https://zenodo.org/records/8432070)
(Abramov and Kurochkina, *Hydro-meteorological database for watersheds across the CIS*, v1.3,
CC BY 4.0). Its paper is [10.3103/S1068373926030052](https://doi.org/10.3103/S1068373926030052).
Both name **АИС ГМВО**, the monitoring system of the Federal Agency for Water Resources
(Rosvodresursy), as the source of daily discharge, stage and coordinates.

**Why the authoritative source cannot be used.**

1. `https://gmvo.skniivh.ru` now serves only a notice that the resource has been withdrawn from
   service («Данный ресурс выведен из эксплуатации»), on every path. `https://gvr.rwec.ru`, the
   State Water Register, shows the same page.
2. The system moved into ГИС ЦП «Вода». Access needs a formal request letter, the Континент TLS
   client, КриптоПро and a Russian certificate.
3. The successor host `gis.favr.ru` refused connections from outside Russia. Archived copies of its
   `/opendata` and `/external-api` pages contain no gauge observations.
4. Archived copies from 2022 show that `gmvo.skniivh.ru` was always behind a login: `?id=1` is a
   login form and `?id=513` answered HTTP 401.

**Other sources checked.**

| Source | Result |
|---|---|
| `meteo.ru` (RIHMI-WDC) | Open data is meteorological only; hydrological data is a paid service |
| `meteorf.gov.ru/opendata` | 8 administrative datasets, no observations |
| `hydrology.ru` (State Hydrological Institute) | Library holdings of printed yearbooks, no data |
| `allrivers.info`, `meteoweb.ru` | Third-party aggregators; fail provenance |
| Regional hydrometeorological offices (e.g. `meteorb.ru`) | HTTP 403 from abroad; HTML flood bulletins, stage only |
| `voda.mnr.gov.ru`, `gis.vodinfo.ru`, `emercit.com` | Unreachable or empty |
| `russia_arcticnet` (CSFS) | University of New Hampshire archive of monthly means; fails provenance |

**ESIMO «Гидрология рек».** `http://portal.esimo.ru/portal/portal/esimo-user/services/hydro` is
HTTP only. It is backed by
`POST http://portal.esimo.ru/dataview/getresourcetable` with
`resourceId=<RU_RIHMI-WDC_NNNN>&iDisplayStart=0&iDisplayLength=<n>`.

| Resource | Content | Rows | Stations | Period |
|---|---|---|---|---|
| `RU_RIHMI-WDC_2665` | Active Roshydromet gauging posts | 2,204 | 2,204 | Catalogue with coordinates, river, office, national and WMO codes |
| `RU_RIHMI-WDC_2655` | Daily discharge | 17,130 | 2 | 1986 to 2012 |
| `RU_RIHMI-WDC_2656` | Daily mean stage | 88,460 | 10 | 1985 to 2012 |
| `RU_RIHMI-WDC_2662` | Monthly mean discharge | 1,607 | 2 | From 1949 |
| `RU_RIHMI-WDC_2658` / `_2660` | Long-term characteristic stage and discharge | 749 / 136 | 10 / 2 | |
| `RU_RIHMI-WDC_1325` / `_1329` | Operational discharge (KN-15), 7 days | 0 | | |

The observation resources form an Amur basin pilot that ends in 2012. The pages that wrap these
resources state that access is for registered users with the owner's permission. The endpoint
answering without a login is not an open interface, so no provider should be built on it. If a
Russian provider ever becomes possible, `RU_RIHMI-WDC_2665` is the station catalogue to use.

**The Zenodo dataset as a user fallback.**

- `Russia_HydroMeteo_Database_v04.zip` is 3.5 GB, licensed CC BY 4.0, version 1.3 of 2023-10-11.
- It covers about 1,886 gauges from 2008 to 2020.
- It holds daily Q in m³/s and mm/day, and H in cm and in m above the Baltic datum, as one netCDF
  per gauge.
- It also includes gauge points, MERIT-Hydro catchments and HydroATLAS attributes.
- It fails provenance and retrieval, but it is the most complete openly licensed Russian discharge
  archive found.

**Recheck when** Rosvodresursy opens a ГИС ЦП «Вода» portal reachable from abroad, or RIHMI-WDC
extends ESIMO beyond the Amur pilot.

### 6.4 Africa and Asia: examined on 2026-09-22 without a download

These sources are not candidates. They are listed so that nobody repeats the same test.

**Explicit refusal or access control. Do not work around these:**

| Source | What happened |
|---|---|
| Zambezi basin, ZAMCOM ZAMWIS (`zamwis.zambezicommission.org/INFO`) | Station metadata and series lists are public. The API lists daily Q back to 1950 for some stations. Exporting a series opens a notice: ZAMCOM says it has no legal right to provide time-series records and refers users to the national agencies, whose contacts it lists |
| Mongolia, NAMEM (`weather.gov.mn/api/get/obs/rivers`) | `{"error":"Access denied. External access is not allowed."}` |
| China, Ministry of Water Resources (`xxfb.mwr.cn`) | According to the sweep, values are deliberately font-obfuscated. Not decoded |
| Pakistan, Flood Forecasting Division | According to the sweep, the feed is token-gated and a plain GET returns Forbidden |
| Bangladesh FFWC API; Nepal DHM observations; South Korea HRFCO | Registration or API key required |
| Mekong River Commission | According to the sweep, raw data goes through a paid licence request |
| Türkiye e-Devlet data request; Uganda WEIS; Lake Chad LIS; CICOS; Volta basin | Login required |
| Philippines PAGASA flood tables | POST-only in the sweep. Not tested, because PhilSensors (5.28) covers the Philippines |

**No numeric values reachable:**

| Source | What happened |
|---|---|
| Niger basin, Niger-HYCOS (`nigerhycos.abn.ne/user-anon`) | The anonymous interface lists 155 stations with coordinates and an inventory of daily Q back to 1914 (Niger at Jebba). The only output is a PNG hydrograph (`/user-anon/png/graphMesureDailyYear.php`). Guessed CSV, text and HTML variants returned 404 |
| Hong Kong, DSD (`waterlevel.dsd.gov.hk/api/dashboard`) | 11 locations with an alert mode and a camera image. No water-level values |
| Azerbaijan, National Hydrometeorological Service | No numeric table found on the hydrology page |
| Kazakhstan, Kazhydromet yearbooks | The yearbook pages load, but no file link was found in the page HTML. `meteo.kazhydromet.kz` and `ecodata.kz` timed out after 60 s |

**No response from this network on 2026-09-22:**
India-WRIS, the India CWC flood portal, and Thailand RID telemetry (`telerid.rid.go.th`).
Re-test from another network.

**Only PDF bulletins or yearbooks without a tested text layer, or nothing online, according to the
sweep:** Tunisia, Burkina Faso, Ghana, Mali, Senegal, OMVS, Algeria, Benin, Tanzania, Zambia WARMA,
Burundi, Kenya, Mozambique, Namibia, Zimbabwe, Nigeria, Myanmar, Lao PDR, Viet Nam, Iran, Cyprus
and Palestine. Türkiye (5.17) and Armenia (5.21) show that a PDF with a text layer can still
qualify, so these can be re-checked for a text layer if a PDF is found.

**Not in-situ or not a provider, according to the sweep:** ORASECOM (model hydrology), Singapore
PUB (urban drainage), `api.rivernet.lk` (operator not identified; the API root returned 404), and
the research compilations and global brokers listed in the sweep.

### 6.5 Leads not yet tested

- **Uruguay, DINAGUA** (Ministry of Environment), `ambiente.gub.uy/informacion_hidrica/`. A
  station catalogue is published. It is not known whether series come through an API or only as
  PDF reports.
- **Paraguay, DINAC** (meteorology and hydrology). The DINAC database is institutional. The
  trinational Pilcomayo commission offers downloads for its basin at
  `pilcomayo.net/hidrometeorologia/descargas`.
- **CDR2, China Daily River Discharge Records** (Zenodo `10.5281/zenodo.22231453`, published
  2026-09-01). It claims daily in-situ data from 1,196 gauges for 1990 to 2024, and the source
  agency is not stated. It would fail provenance as a research compilation, but it may name the
  agency.
- Guyana and Suriname were not searched.

---

## 7. Evidence kept

No observation data from these tests is stored in the repository. Sample files from the 2026-08
round were saved in a temporary session directory and are gone. Every result above can be
reproduced from the request URL and parameters given in its section. The R code behind the
hydrodownloadR routes is in `hydrodownloadR/R/adapter_<ID>.R`. The Africa and Asia tests of
2026-09-22 kept their downloads only in a temporary session directory.
