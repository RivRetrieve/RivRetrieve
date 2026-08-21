# Source terms finding — za_dws

Agency: Department of Water and Sanitation DWS
Country: South Africa
Status: complete

Read `../BRIEF.md` first. The one rule: write down what the agency says, never what it
means. Every quote must be copied out of a page you recorded.

## Candidate pages (UNVERIFIED — leads only)

**NOT FOUND, and nothing could be confirmed.** Every `dws.gov.za` URL returned **HTTP 403** to
the lead-finder — via two different tools, including one sending a browser user-agent. The
site appears to block non-South-African or non-browser traffic. The Internet Archive was also
down that session, so there was no snapshot fallback.

**Important: non-existence is NOT established.** These pages may be perfectly normal to
someone who can load the site. Nothing below is a located terms page.

| URL | Lang | Note |
|---|---|---|
| https://www.dws.gov.za/Hydrology/Verified/ | en | Landing page of the Verified Hydrology section this provider reads — a disclaimer would most likely sit here. 403 |
| https://www.dws.gov.za/Hydrology/Verified/hymain.aspx | en | The section's main frame page. 403 |
| https://www.dws.gov.za/Groundwater/data.aspx | en | Search attaches conditions-style language here, but this is **groundwater**, a different programme from Verified Hydrology. 403 |
| https://niwis.dws.gov.za/niwis2/Info/... | en | NIWIS info pages surfaced with conditions-style language; a different system again. 403 |

Guessed paths `/Hydrology/HyDisclaim.aspx` and `/disclaimer.aspx` also 403'd. Host
`hydro.dws.gov.za` does not resolve.

**Caution:** some DWS conditions-style wording circulating online may come from a
data-request form PDF rather than a published terms page. Do not record it unless you find it
on a page you can save.

**If you also cannot load `dws.gov.za`, say so and stop.** A VPN or a South African colleague
may be needed. "Unreachable from here on <date>, tried X and Y" is the correct finding — do
not substitute something from a search result.

## licence

- Page URL: https://www.dws.gov.za/hydrology/Verified/
- Recording: licence-1
- Retrieved (UTC): 2026-08-21T08:01:44+00:00
- Language: en
- Agency publishes nothing: yes

No terms of use, licence or citation request was found for the Verified Hydrology programme.
`dws.gov.za` cannot be reached from here at all; the recording is an Internet Archive snapshot
of the programme's own landing page, kept as evidence of absence. DWS terms wording that does
exist belongs to **other** DWS systems and is quoted in Notes, where it cannot be mistaken for
this programme's terms.

```text
```

## citation

- Page URL: https://www.dws.gov.za/hydrology/Verified/
- Recording: licence-1
- Retrieved (UTC): 2026-08-21T08:01:44+00:00
- Language: en
- Agency publishes nothing: yes

```text
```

## Notes

### The block reproduces, from two clients

The candidate table's finding is confirmed, not merely inherited. On 2026-08-20, from
Switzerland:

| Attempt | Result |
|---|---|
| DNS `www.dws.gov.za` | resolves, `164.151.129.108` |
| `record.py` / urllib, browser User-Agent | **HTTP 403** on `/`, `/hydrology/Verified/`, `/hydrology/Verified/HyCatalogue.aspx`, `/disclaimer.aspx` |
| A real Chrome browser | **403 Forbidden — "You don't have permission to access this resource."** |

DNS resolves and the host answers, so this is an application-level block and **not** a
user-agent problem: a genuine browser is refused exactly as the script is. Nothing on
`dws.gov.za` can be read from here.

### The route the candidate table could not try

The table noted the Internet Archive was down when the leads were gathered, so there was no
snapshot fallback. **It is up now, and it works.** This is not a workaround invented for the
survey: `za_dws` already ships archive URLs among its own origins, so the provider itself
depends on the Archive for several Verified Hydrology PDFs and for `HyCatalogue.aspx`.

Everything below was read through `web.archive.org`.

### The programme we use publishes nothing — evidenced

`licence-1` is a snapshot of `https://www.dws.gov.za/hydrology/Verified/` taken 2024-11-29,
the landing page of the exact programme RivRetrieve reads. Its links are Home, Contact Us,
Drainage Regions and Station Catalogue, plus the drainage-region and station-type selectors.
**There is no disclaimer, copyright, terms or conditions link anywhere on it.** Checked by
scanning every anchor on the page, not by eye.

A CDX search of the whole `dws.gov.za` domain — 40,000 archived URLs — was filtered for
`disclaim`, `copyright`, `terms`, `legal`, `conditions` and `policy`. No such page exists
anywhere under `hydrology/Verified/`.

**The two pages the provider actually scrapes were then checked directly, not just the landing
page.** `za_dws` reads `HyCatalogue.aspx` for the station catalogue and `HyData.aspx` for
observations:

| Recording | Page | Content | Rights notice |
|---|---|---|---|
| `licence-4` | `HyCatalogue.aspx`, snapshot 2026-03-11 | 1,066 characters of visible text: the word *Home* and 30-odd WMA PDF filenames | **none** |
| `licence-5` | `HyData.aspx?Station=A2H023100.00&DataType=Monthly&…&SiteType=RIV`, snapshot 2023-05-25 | A real river-data response in the exact request shape this provider uses: a fixed-format description, the monthly volumes, a `ZZZZZZZZZZ` terminator and the station id | **none** |

A second data response was checked as well — `V1R005100.00`, daily, 183,672 bytes — with the
same result. Scanned for `copyright`, `disclaim`, `licen`, `terms`, `conditions` and
`all rights`: **zero occurrences in either.**

So the absence is established at the level that matters. It is not merely that a landing page
lacks a link — the catalogue page and the data payloads themselves carry no notice of any kind.

### The system behind Verified Hydrology

Established from the service's own output rather than from general knowledge. One archived
`HyData.aspx` response is a backend error that names the vendor:

```text
ERROR [28000] [Kisters][ScriptServerODBC Driver]Client unable to establish connection. Can't connect to ScriptServer at cenwhyd101:8085.
```

**Kisters** is the vendor whose hydrological database product is Hydstra, and `cenwhyd101`
reads as a hydrology server name. DWS's own `/Hydrology/` page describes the section we read as
*"Verified Data — Data from the Hydrological Information System and Peak Flows"*, and archived
internal paths take the form `Hydrology/Verified/CGI-BIN/HIS/…`.

So the data we read is DWS's **Hydrological Information System (HIS)** — surface water — served
from a Kisters backend. Recorded because it separates our source cleanly from the CHART system
below, which is **geo**hydrological: groundwater, a different sub-directorate and a different
database.

### DWS does publish data terms — but for other systems

The same search found a recurring DWS data-terms boilerplate on two other systems. It is
quoted here **because it exists and a reader should know it exists**, and it is kept out of the
slots **because it is not this programme's**.

`licence-2` is the CHART system's *Data Disclaimer*, snapshot 2021-06-27. Its own heading
states its scope:

```text
DIRECTORATE: HYDROLOGICAL SERVICES, SUB-DIRECTORATE: GEOHYDROLOGICAL INFORMATION DEPARTMENT: WATER & SANITATION
```

Note *GEOHYDROLOGICAL INFORMATION* — groundwater. The candidate table warned that DWS
groundwater pages are a different programme from Verified Hydrology, and that warning holds.
The text itself:

```text
Copyright The copyright of the data remains with the Department: Water & Sanitation. This approval to use the data cannot be construed as a transfer of copyright. Usage The use of data is restricted to use for academic, research or personal purposes Data may not be sold (value added or not) The recipient of the data does not have the right to distribute any portion of the data to any third party. The Department: Water & Sanitation retains all rights to distribute the data to third parties, and the data remains the property of the Department: Water & Sanitation. Access to this data is limited solely to the registered user Data may be distributed within your organisation only, provided that your organisation accepts and complies with the terms and conditions laid out in this document. The exploitation of the data for commercial purposes is not included in this permission to use the data. All requests for additional right of use must be requested in writing to the Director: Hydrological Services, Department: Water & Sanitation, Private Bag x313, Pretoria, 0001.
```

`licence-3` is `ws.dws.gov.za/cdl/copyright.aspx`, snapshot 2022-07-28, carrying materially the
same wording under a third directorate, *Macro Planning*.

**What this does and does not show.** It shows DWS has standard wording it applies to data
services, and that the wording is restrictive. It does **not** show that this wording governs
Verified Hydrology surface-water data, and nothing found says that it does. Two different
directorates, two different systems, neither of them ours. Whether it extends to the data
RivRetrieve reads is exactly the judgement this survey does not make.

### What would settle it

Someone who can load `dws.gov.za` — a South African colleague, or a VPN — should check whether
`hydrology/Verified/` carries a disclaimer today that the 2024 snapshot did not. Failing that,
a written enquiry to the Director: Hydrological Services, whose postal address appears in the
`licence-2` text above, is the route DWS's own boilerplate names for questions about rights of
use.

No enquiry had been sent as of this recording.
