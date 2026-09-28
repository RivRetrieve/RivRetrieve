# Bosnia source research: live authoritative checks

Access date: 2026-09-28 UTC. Exact request-start timestamps, HTTP status, final URLs,
and raw-body SHA-256 values are in [`source-requests.json`](source-requests.json). All 12 inspected URLs returned
HTTP 200; no outage occurred. Raw captures are retained locally under the ignored `source-checks/authoritative/`
folder. Each saved `.html` is the response body; its `.txt`
companion is visible text extracted with BeautifulSoup. HTTP requests used a
25-second timeout and followed redirects. No local observation cache was used.
This is direct source research, not execution of RivRetrieve examples.

## Institutional context

Bosnia and Herzegovina has river basins draining towards the Black Sea through
the Sava and Danube, and towards the Adriatic Sea. AVP Sava (Agencija za vodno
područje rijeke Save, the Sava River Basin Agency) organises hydrological
monitoring and publishes the Vodostaji Plus portal. Its jurisdiction covers the
Black Sea drainage area within the Federation of Bosnia and Herzegovina, not
all of Bosnia and Herzegovina. In RivRetrieve, `ba_fhmzbih` retrieves AVP Sava
workbooks. FHMZBiH is a separate hydrometeorological institute that also publishes
water levels and points readers to the water agencies for their information-system
data. Do not call the AVP portal a national station network or attribute all its
stations to FHMZBiH.

“Organises hydrological monitoring” is the strongest directly supported general
measurement-role statement. The monitoring page describes automatic stations and
data collection, processing and visual presentation. None of the pages inspected
establishes ownership or the measurement operator for every station returned by
RivRetrieve. Avoid “all stations are owned/operated/measured by AVP Sava” or by
FHMZBiH. Agency jurisdiction is not a checked geographical bounding box for every
station in the portal or packaged catalogue.

## Claim-to-source record and exact extracts

### 1. National hydrological context

URL: https://www.fhmzbih.gov.ba/latinica/HIDRO/Hkarakteristike.php
Saved: `fhmz-geography.html`, `fhmz-geography.txt`.

Exact text (whitespace normalised only):

> Osnovna slivna područja u BiH su:
> a) Crnomorski sliv:
> b) Jadranski sliv:

The page lists the Sava, Una, Vrbas, Bosna and Drina within the first group,
and Neretva, Trebišnjica and Cetina within the second. It states:

> Od ukupne površine BiH, 38.719 km2 ili 75,7% gravitira rijeci Savi, odnosno Dunavu i Crnom moru, a slivu Jadranskog mora 12.410 km2 ili 24,3%, Slika 1.

Use the broad drainage distinction only. This live page cites older publications
(1972, 1993, 1998) and retains obsolete geopolitical names. Fresh access does not
make its quantitative geography or political terminology current. No percentages
or historical geopolitical descriptions are needed for the provider page.

URL: https://www.fhmzbih.gov.ba/
Saved: `fhmz-home.html`, `fhmz-home.txt`.

> Meteorološku djelatnost u Bosni i Hercegovini obavljaju dva entitetska zavoda.

Labels name `Federacija Bosne i Hercegovine` / `Federalni hidrometeorološki zavod BiH`
and `Republika Srpska` / `Republički hidrometeorološki zavod`.
This supports distinguishing the institutes and entities, but says meteorological,
not that these two institutes alone perform all hydrological measurements.

### 2. AVP Sava institutional and geographical scope

URL: https://www.voda.ba/agencija
Saved: `avp-agency.html`, `avp-agency.txt`.

> Konkretno, za područje Federacije BiH koje pripada Crnomorskom slivu nadležna je Agencija za vodno područje rijeke Save u Sarajevu, a za područje koje pripada Jadranskom slivu Agencija za vodno područje Jadranskog mora u Mostaru.

Unofficial translation: Specifically, the Sava River Basin Agency in Sarajevo is
responsible for the part of the Federation of BiH belonging to the Black Sea
basin, and the Adriatic Sea Basin Agency in Mostar for the part belonging to the
Adriatic basin.

Under `Agencija za vodno područje rijeke Save obavlja slijedeće poslove:`:

> - organizira, prikuplja i vrši distribuciju podataka o vodnim resursima u skladu sa odredbama Zakona o vodama, uključujući i uspostavu i održavanje informacionog sistema vodoprivrede (ISV);
> - organizira hidrološki monitoring i monitoring kvaliteta voda, monitoring ekološkog stanja površinskih voda, priprema izvještaj o stanju voda i predlaže potrebne mjere;

These establish the agency's organising, collection and distribution roles.
They do not establish station-specific ownership.

URL: https://www.voda.ba/informacioni-sistem-voda
Saved: `avp-monitoring.html`, `avp-monitoring.txt`.

Extract:

> prikupljanje, obradu i vizualnu prezentaciju podataka, kako iz oblasti Upravjanja vodama (ISV sistema) tako i iz sistema hidrološkog monitoringa površinskih i podzemnih voda sa preko 100 savremenih automatskih stanica postavljenih na gotovo svim vodotocima u slivu rijeke Save u Federaciji BiH koji su u nadležnosti ove Agencije.

This describes an information centre collecting, processing and displaying data
from automatic surface-water and groundwater monitoring stations in the agency's
area. The “over 100” count concerns this source description, not RivRetrieve's
packaged catalogue; do not substitute it for catalogue counts.

### 3. Publisher and FHMZBiH distinction

URL: https://www.voda.ba/
Saved: `avp-home.html`, `avp-home.txt`.
The official agency site links `Vodostaji plus` to `http://vodostaji.voda.ba`.
The information-system page has the same portal link.

URL: https://vodostaji.voda.ba/
Saved: `portal.html`, `portal.txt`.
The HTML title and visible initial loading text both name:

> Agencija za vodno područje rijeke Save

The portal was fetched as initial HTML, not browser-rendered. No claims about
rendered navigation or terms beyond inspected HTML are justified.

URL: https://www.fhmzbih.gov.ba/latinica/HIDRO/index.php
Saved: `fhmz-hydrology.html`, `fhmz-hydrology.txt`.

> Podaci sa vodomjernih stanica koje prikuplja Informacioni sistem voda, mogu se naći na internet stranicama:
> Agencije za vodno područje rijeke Save, Sarajevo
> Agencije za vodno područje Jadranskog mora, Mostar
> Međunarodna komisija za sliv rijeke Save

This is direct evidence that FHMZBiH distinguishes and links the other publishers.
The same page displays its own current water-level table and notes that Sanski
Most and Bihać are not automatic stations, with daily data there. Do not transfer
that note to the AVP portal or presume identity with same-named catalogue records.

The mapping of the RivRetrieve identifier to AVP workbooks is a code claim, not an
external source claim. Current root `src/rivretrieve/_internal/providers/ba_fhmzbih/fetch.py`
uses `_METADATA_URL = "https://vodostaji.voda.ba/data/internet/layers/20/index.json"`
and `_WORKBOOK_ROOT = "https://vodostaji.voda.ba/data/internet/stations"`.
The docs/code owner must recheck that mapping at the tested revision. Do not
invent a historical reason for the identifier.

### 4. Exact Impressum quotation and translation

URL: https://vodostaji.voda.ba/data/html/impressum.html
Saved: `impressum.html`, `impressum.txt`.

Exact source wording (HTML line wrapping normalised to spaces):

> Svi podaci koji se prikazuju i koji se dobiju kao rezultat pretrage su informativnog karaktera i ne mogu služiti kao zvanični podaci.

Recommended explicitly unofficial translation:

> All data displayed and obtained as a result of a search are for information purposes and cannot serve as official data.

The text does not say “provisional,” “quality controlled,” “unvalidated,” or
“approved.” Use its own informational/not-official distinction without supplying
an unreported quality status. Successful retrieval does not alter that status.

### 5. Reuse and citation: bounded finding

The complete Impressum comprises its title and three short paragraphs. It
explains the monitoring system's purpose and informational status. It contains
no explicit reuse licence and no requested citation format.

The agency pages inspected here display this footer:

> Copyright © 2001-2020 - All rights reserved - Agencija za vodno područje rijeke Save

Consequently the original PR statement “No licence or citation request is
published” is too broad. Supported terms summary:

“The portal's Impressum does not specify a reuse licence or a citation format.
AVP Sava's main website carries an ‘All rights reserved’ notice. Check reuse
conditions with the agency before redistributing the data.”

Alternatively retain only the first two sentences plus a contact link. A general
copyright notice does not resolve data-specific rights, but omitting it while
claiming no terms would mislead. Do not claim open licensing or unrestricted
reuse. No exhaustive search of every agency document, script, rendered interface,
or legal instrument was performed. This research does not establish that no
other terms or citation request exist anywhere. A reader-facing attribution
recommendation may name AVP Sava and retrieval date, but label it as RivRetrieve's
recommendation rather than a publisher requirement.

## Remaining limits

- No station ownership or station-specific measurement operators established.
- No source-wide one-year availability or continuity claim established here.
- No source units, time zone, temporal support or frequency inferred here.
- No live RivRetrieve snippets executed in this independent research task.
- All pages above were freshly fetched; yearbook availability is not established
  by its year selector (which even lists future years).
- No production, provider-page, branch, checkout or PR edits made by this worker.
