# Source terms finding — ca_eccc

Agency: Environment and Climate Change Canada
Country: Canada
Status: complete

Read `../BRIEF.md` first. The one rule: write down what the agency says, never what it
means. Every quote must be copied out of a page you recorded.

## Candidate pages (UNVERIFIED — leads only)

Good agency-authored candidates here. **Record both the Wateroffice pages and the MSC
licence** — which governs depends on which service the data came through, and that is not
yours to decide.

| URL | Title | Lang | Why a candidate |
|---|---|---|---|
| https://eccc-msc.github.io/open-data/licence/readme_en/ | ECCC Data Servers End-use Licence (v2.1, Sept 2022) | en | The named end-use licence for ECCC data servers |
| https://eccc-msc.github.io/open-data/msc-data/obs_hydrometric/readme_hydrometric_en/ | Readme hydrometric | en | Hydrometric-specific readme pointing at that licence — ties it to *this* dataset |
| https://wateroffice.ec.gc.ca/contactus/faq_e.html | Water Level and Flow — FAQ | en | Carries a heading "How should I reference data?" — **this is the citation ask** |
| https://wateroffice.ec.gc.ca/disclaimer_info_e.html | Disclaimer for Hydrometric Information | en | Wateroffice's own disclaimer; links onward to Canada.ca terms |
| https://www.canada.ca/en/transparency/terms.html | Terms and conditions — Canada.ca | en | Government-wide terms, linked from the disclaimer |

French equivalents exist at the `_f.html` / `readme_fr` variants.

## licence

- Page URL: https://eccc-msc.github.io/open-data/licence/readme_en/
- Recording: licence-1
- Retrieved (UTC): 2026-08-20T12:31:14+00:00
- Language: en
- Agency publishes nothing: no

```text
Use of any Information indicates your acceptance of the terms below. The Information Provider grants you a worldwide, royalty-free, perpetual, non-exclusive licence to use the Information, including for commercial purposes, subject to the terms below.
```

## citation

- Page URL: https://wateroffice.ec.gc.ca/contactus/faq_e.html
- Recording: citation-1
- Retrieved (UTC): 2026-08-20T12:31:16+00:00
- Language: en
- Agency publishes nothing: no

```text
For real-time data retrieved from the Wateroffice web site:“Extracted from the Environment and Climate Change Canada Real-time Hydrometric Data web site (https://wateroffice.ec.gc.ca/mainmenu/real_time_data_index_e.html) on [DATE]” For historical data retrieved from the Wateroffice web site:“Extracted from the Environment and Climate Change Canada Historical Hydrometric Data web site (https://wateroffice.ec.gc.ca/mainmenu/historical_data_index_e.html) on [DATE]” For historical data retrieved from the MDB file:“Extracted from Environment and Climate Change Canada’s HYDAT.mdb, released on [DATE]”
```

## Notes

Canada has real, agency-authored documents for both slots, and **two of them apply because we
use two different services**. Which governs which is not decided here. Five pages were
recorded so a later reader can decide with the evidence in hand.

### The two routes we actually use

`origins.py` shows RivRetrieve fetches Canadian data from two places, neither of which is the
Wateroffice website:

```
https://api.weather.gc.ca/collections/hydrometric-stations?f=json
https://collaboration.cmc.ec.gc.ca/cmc/hydrometrics/www/Hydat_sqlite3_{vintage}.zip
```

The first is **MSC GeoMet**, whose landing page describes itself as providing access to MSC and
ECCC data. The second is the **HYDAT** database distribution. Both are ECCC servers, so the
ECCC Data Servers End-use Licence is the document that names them; the Wateroffice pages are
the same programme's public website.

Checked directly and worth recording: **the OGC API declares no licence of its own.** Neither
`https://api.weather.gc.ca/?f=json` nor the `hydrometric-stations` collection carries a
`license` field or any link with a licence/terms/rights relation. The only `about` link points
to the MSC GeoMet readme. So the licence is not machine-discoverable from the service; it has
to be found on the documentation site.

### The licence quoted above

`licence-1` is the *Environment and Climate Change Canada Data Servers End-use Licence*,
**Version 2.1 - September 2022**, as stated on the page itself. The quote is the grant from
its section 1. The document continues with sections headed *You are free to*, *You must, where
you do any of the above*, *Exemptions*, *Non-endorsement*, *No Warranty*, *Governing Law*,
*Definitions* and *Versioning*, all present in the recording and none of them summarised here.

### The attribution statement, from the same licence

Section 3 of the licence requires acknowledgement and, where no specific statement is given by
the provider, specifies this exact wording:

```text
Contains information licenced under the Data Server End-use Licence of Environment and Climate Change Canada.
```

That is a second, differently-scoped credit line from the one in the citation slot: the licence
statement is generic to all ECCC data servers, while the citation slot holds the hydrometric
programme's own answer to "How should I reference data?". Both are the agency's own words. The
citation slot carries the hydrometric one because it is specific to this data and because its
third form — for HYDAT — matches one of our two routes.

Note the citation quote's HYDAT wording says `HYDAT.mdb`, the Access database. We download
`Hydat_sqlite3_<vintage>.zip`, the SQLite distribution of the same database. Recorded as an
observation about the wording, not as a judgement about whether it applies.

### The other three recordings

| Recording | Page | Why kept |
|---|---|---|
| `licence-2` | MSC readme for hydrometric observations | Ties *this dataset* to the licence: *"The end-user licence for Environment and Climate Change Canada's data servers specifies the conditions of use of this data."* |
| `licence-3` | Wateroffice *Disclaimer for Hydrometric Information* | The programme's own disclaimer; liability, not terms of reuse |
| `licence-4` | canada.ca *Terms and conditions* | Government-wide terms, linked onward from the disclaimer |
| `licence-5` | *MSC Open Data Service Usage Policy* | **Not in the candidate table.** Found via a link in `licence-2`. States it *complements the End-use licence* and sets out acceptable use of the services |

### Access notes

- `wateroffice.ec.gc.ca` fails TLS verification under Python's default certificate store
  (`CERTIFICATE_VERIFY_FAILED`). It is not blocking us: the server does not send a complete
  chain for that store. Both pages were recorded by pointing `SSL_CERT_FILE` at the `certifi`
  bundle, with verification still on. Anyone re-running `record.py` for this provider needs the
  same, or the fetch fails.
- `www.canada.ca` timed out on the first attempt and succeeded on a retry.
- French equivalents exist for every page above at the `_f.html` / `readme_fr` variants. Only
  the English were recorded.
