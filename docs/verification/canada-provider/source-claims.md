# Canada authoritative-source claim matrix

Fresh publisher-page checks were made on 2026-09-22 UTC. URLs, timestamps and
response hashes are in `sources/INDEX.json` in the private source archive.
The [verification instructions](README.md) describe external input selection.
Evidence names below identify retained historical captures. These checks are
distinct from the national archive acquisition and public-API execution.

## Claim matrix

| Claim | Evidence | Finding and qualification |
| --- | --- | --- |
| WSC belongs to ECCC; measures and publishes in partnership | `faq`, `overview`, `partners`, `partnership` | WSC is within National Hydrologic Services, ECCC. Federal body collects, interprets and disseminates standardized water quantity data. It operates for most provinces/territories under agreements; Quebec operates its stations. Program includes provincial, territorial and other partners. Do not imply WSC alone operates every station. |
| Who publishes HYDAT | `hydat`, `release` | WSC compiles national hydrometric data and offers Access and SQLite files. HYDAT includes daily/monthly mean flow and water level, plus sediment and some peaks/extremes. RivRetrieve support is a separate code claim. |
| Meaning of discharge and stage | `faq`, `definition.pdf.txt` | Streamflow is discharge; stage is water level. Discharge can be derived from stage-discharge relationships. `DLY_FLOWS` values are m³/s; `DLY_LEVELS` values are m. Gauge height is not water depth or automatically elevation above sea level. Schema document is headed HYDAT.mdb: use it as table documentation, not SQLite-specific legal evidence. |
| Daily symbols | `faq`, `definition.pdf.txt` | A partial day; B ice conditions; D dry (water-level only); E estimate; R revised. B indicates discharge estimated considering ice; R means revision/correction/addition to historical discharge database after 1989-01-01. Table fields link to DATA_SYMBOLS. Do not interpret blank as an assurance of quality or assert canonical per-row flags from storage retention alone. |
| Time definition | `faq`, `definition.pdf.txt` | FAQ explicitly describes time-weighted averages of 5-minute data between 0:00 and 24:00, subject to gaps/grades. Daily tables contain year/month/day cells, without a daily time-zone field; other tables such as instantaneous peaks do have TIME_ZONE. No basis here for assigning a particular zone or extending today's general FAQ algorithm to every historical value. Prefer “RivRetrieve represents the daily calendar date as midnight, with unknown time zone and unestablished interval bounds” after code verification. Avoid “HYDAT does not define the day” as a blanket publisher claim. |
| Reviewed versus provisional | `faq`, `disclaimer`, `hydat` | FAQ says technologists review/finalize records under quality management before national database dissemination. Near-real-time website data can change. Archived daily means may still be estimated/revised. Avoid implying all archived values are error-free or uniform FINAL public statuses. |
| Publication cadence and freshness | `hydat`, `release.pdf.txt`, `listing` | Publisher says quarterly updates; fresh directory lists Hydat_sqlite3_20260717.zip and release notes dated July 17 2026. Directory last modified July 20. Edition date, file modification time, latest observations and retrieval date are distinct. No fixed week/month publication lag established. |
| Download size | `listing` | Current compressed SQLite ZIP displayed as 266M. This is directory approximation, not working disk requirement. Owner should use actual transferred byte count and measured disk footprint, avoiding obsolete approximately 1 GB download assertion. |
| Real-time timeliness | `faq`, `disclaimer` | FAQ aims within 6 hours, often sooner; disclaimer says normally within 2 hours. No need to quantify this unused route. “Minutes to a couple of hours” is too categorical. |
| Applicable OGL evidence for HYDAT archive | `portal-historical-record`, `portal-historical-html`, `ogl` | Official Historical Hydrometric Data record `1ee9e14d-0814-5201-a3be-705809d8ee0e` names Open Government Licence - Canada and explicitly links archive directory as SQL resource `9781f71c-7747-4484-99d6-8f0cc3bc42f8`. This establishes an archive-route link absent from generic search results. OGL version 2.0 requires source/specified attribution and, where possible, licence link. |
| ECCC Data Services terms | `hydrometric-open-correct`, `licence`; inspected `origins.py` | Current MSC hydrometric documentation explicitly points to ECCC end-user licence for its data-server access. Header says Version 2.1.1 - August 2026; section 9 still says version 2.1. Repository provenance records this licence URL and general licence grant. It is not textually identical to OGL. Preserve distinct publisher contexts; do not assert one replaces the other or infer a code defect from their coexistence. |
| Water Office resale language | `disclaimer` | Restriction says “Information presented on this web site” and raw resale prohibition. Do not transplant it as an additional archive licence condition. Website citations/conditions apply to that route. |
| Citation instructions | `faq`; inspected `origins.py` | FAQ provides separate real-time website, historical website, and MDB-file citation instructions. The MDB quote explicitly names HYDAT.mdb. No prescribed SQLite citation found in checked FAQ, archive listing, release notes, database definition, portal record or licence. Cite ECCC/WSC, actual SQLite edition, source URL and access date as an explicitly suggested practical reference, not mandated wording. |

## Exact attribution distinctions

Open Government Licence version 2.0 fallback, subject to its stated conditions:

> Contains information licensed under the Open Government Licence – Canada.

ECCC Data Services End-use Licence fallback, subject to its stated conditions:

> Contains information licenced under the Data Server End-use Licence of Environment and Climate Change Canada.

ECCC terms additionally say to attribute originators, including outside ECCC, and give “Data Source: Environment and Climate Change Canada” as an example. They require any specified Information Provider and/or Third Party Information Contributor statement. Both licences include exemptions, non-endorsement and no warranty; neither is an unconditional guarantee of reuse rights for excluded material.

FAQ MDB-specific wording:

> Extracted from Environment and Climate Change Canada’s HYDAT.mdb, released on [DATE]

Do not replace “HYDAT.mdb” with SQLite and label the resulting wording prescribed.

## Suggested reader-facing terms structure

Say the official Historical Hydrometric Data catalogue entry lists Open Government Licence – Canada and links the HYDAT SQL download. Link the actual dataset record and OGL. Also link the ECCC Data Services End-use Licence that RivRetrieve records and MSC hydrometric documentation cites, rather than claiming these are one identical licence. Explain attribution and link the FAQ while stating its file-specific wording is for MDB. A short suggested SQLite reference should identify the actual file/edition and retrieval date without claiming official wording. Avoid carrying over website-only resale restrictions.

## Access failures and limitations

- Guessed path `https://eccc-msc.github.io/open-data/msc-data/hydrometric/readme_hydrometric_en/` returned HTTP 404 (`hydrometric-open`). This was resolved by following the publisher index to the actual `msc-data/obs_hydrometric/readme_hydrometric_en/`, which returned HTTP 200 (`hydrometric-open-correct`). It is not an acceptance blocker for the resolved claim.
- The broad portal HYDAT search returns unrelated derived datasets; it is not sufficient licence evidence. Direct Historical Hydrometric Data metadata is the decisive route evidence.
- Archive directory and release notes themselves contain no licence or SQLite-specific prescribed citation. Do not invent one. No assertion is made that every conceivable publisher document has been searched.
- This research does not verify archive contents, practical example output, public status fields, station counts, cache behavior or disk needs. Those require the owner's repository/API verification.
- No confirmed production-code defect was encountered. Older port notes contain documentation statements needing caution (five-column canonical result and possible HTTP 404 at bulk station retrieval), not established runtime defects. Do not copy those claims into the provider page.
- No checkout/copy of the repository created. Only this evidence directory was written. Original PR diff and metadata are retained alongside source responses.
