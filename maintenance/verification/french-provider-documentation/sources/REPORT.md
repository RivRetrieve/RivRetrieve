# French provider source-fact verification

Checked 2026-09-21, 12:26–12:28 UTC, against current repository code and packaged catalogues at the parent-verified target `31bd527169b6fb67f0a7b3b692eed53a7fd190d7`.
Research only. No checkout created. No production, documentation, test, branch, PR, issue or Map edits made by this worker. This report is factual research, not the independent full-diff PR review. Final live page examples belong to the implementation owner's separate verification.

## Acquisition and reproducibility

Exact acquisition files are retained in `authoritative-pages.tar.xz` beside this
report. Archive members preserve the researcher's original bytes. The three
`checks.json` manifests (root, `additional/`, and `hubeau-metadata/`) record URL,
final URL, exact UTC start, HTTP status, body filename and SHA-256. Plain-text
`.txt` extractions are aids, not source substitutes; footers were removed from
those extractions. `SHA256SUMS` identifies the archive.

To repeat an acquisition, extract the archive into a **new evidence directory**,
then run its root `check_sources.py` and the scripts of the same name under
`additional/` and `hubeau-metadata/` with `uv run python`. They write beside
themselves, so preserve the original archive and do not run against the dated
acquisition. These are historical research scripts, not provider runtime code.

- Source-check commands returned exit 0. Catalogue inspection returned exit 0
  after correcting a verifier-only attempted `rr.stations` call (no such public
  function). Initial stdout is `catalogue-initial.txt`; final stdout is
  `catalogue-check.txt`. This is not a product defect. The implementation's
  maintained count check is `../inspect_provider_counts.py`.
- The initial URL extractor included the period after a quoted Etalab URL. Its
  spurious `...open-licence.` request redirected to the data.gouv.fr homepage.
  The exact URL without punctuation was independently rechecked and redirects
  to Licence Ouverte 2.0. The first redirect is not broken licence evidence.
- All twelve links in the prior combined page's Sources table returned HTTP 200.
  The final pages also cite the freshly checked station selector form. No
  reachability gap remains for these references on this check date.

## Checked authoritative URLs

All checks below returned HTTP 200 on 2026-09-21. Body names are relative to the download directory. Full hashes and times are in the manifests.

| URL | Body | Supported use |
|---|---|---|
| https://hubeau.eaufrance.fr/page/api-hydrometrie | `00.html` | PHyC source, DREAL/other producers, fields, source units, broad UTC statement, selected historical records since 1900 |
| https://hubeau.eaufrance.fr/page/api-temperature-continu | `01.html` | Mainland automatic temperature sensors; Naïades source |
| https://hydro.eaufrance.fr/aide/accueil | `02.html` | Help landing page |
| https://hubeau.eaufrance.fr/ | `03.html` | OFB/BRGM collaboration stated in full HTML footer |
| https://hydro.eaufrance.fr/ | `04.html` | Public portal |
| https://hydro.eaufrance.fr/glossaire | `05.html` | Source processing-status vocabulary, site/station definitions |
| https://www.data.gouv.fr/pages/legal/licences/etalab-2.0 | `07.html` | Attribution including source/licensor and last-update date |
| https://hubeau.eaufrance.fr/page/conditions-generales | `08.html` | Section 5.1.3 Etalab reuse and dataset-author citation |
| https://hubeau.eaufrance.fr/mentions-legales-credits | `09.html` | OFB publication director and BRGM technical development/hosting |
| https://hydro.eaufrance.fr/edito/mentions-legales | `10.html` | SCV editor, distinct producers, public access without account |
| https://hydro.eaufrance.fr/edito/a-propos-dhydroportail | `11.html` | PHyC responsibility and replacement of HYDRO 2 interfaces on 2022-01-25 |
| https://hydro.eaufrance.fr/aide/la-station-hydrometrique | `12.html` | Station measures stage and/or discharge; one active site-discharge station at most |
| https://hydro.eaufrance.fr/aide/le-site-hydrometrique | `13.html` | Site is homogeneous discharge reach, carries discharge data |
| https://hydro.eaufrance.fr/aide/les-series-de-mesures | `14.html` | A chosen status may return no data while other statuses exist; help selector list is incomplete |
| https://hydro.eaufrance.fr/faq | `15.html` | No reuse licence or station-record citation established |
| https://hydro.eaufrance.fr/stationhydro/Y251002001/series | `additional/00.html` | Current four-selector form |
| https://hydro.eaufrance.fr/build/4210.e6896d9b.js | `additional/01.html` | Q code `l` maps to `unit.q.l` |
| https://hydro.eaufrance.fr/build/5621.4ab47ec9.js | `additional/02.html` | `common.unit.q.l` is `l/s` |
| https://www.etalab.gouv.fr/licence-ouverte-open-licence | `additional/03.html` | Redirect to exact Licence Ouverte 2.0 page |
| https://hubeau.eaufrance.fr/page/a-propos | `additional/04.html` | General service description; not necessary for operator attribution |

## Substantiated claims and interpretation limits

### Publishers, producers and networks

- Hub'Eau's hydrometry page explicitly identifies PHyC, operated by Service Central Vigicrues (SCV, ex-SCHAPI). It identifies DREAL and other producers such as local authorities. The service operator is not necessarily the original measurement producer.
- Hub'Eau homepage full HTML says: “Hub’Eau est le résultat de la collaboration de l’OFB (Office Français pour la Biodiversité) et du BRGM”. Legal credits support OFB publication and BRGM development/hosting. The terms additionally define the editors as OFB, SCV and BRGM. Describing OFB/BRGM collaboration is supported; do not imply these are the original producers of every observation or that SCV has no role.
- HydroPortail legal page identifies SCV as editor and the VIGICRUES network plus external hydrometric producers as content producers. It covers metropolitan and overseas France and says public data access does not require a user account. Optional accounts add preferences/favourites/full export menus; no claim that every portal function is anonymous.
- HydroPortail about page says it replaced HYDRO 2 interfaces on 25 January 2022 and interacts with PHyC managed by SCV. It does not prove historical measurement authorship for any particular record.
- Hub'Eau temperature page explicitly says automatic sensors in mainland French rivers and Naïades data. Sensor recording frequencies range from one minute to several hours. This broad statement does not establish every returned observation's temporal support or averaging duration. Preserve `unknown` temporal support and zone. Do not present these temperature series as PHyC hydrometry or assume a discharge station also provides temperature.

### Supported products, quantities, units and time

- Hub'Eau hydrometry page defines `QmnJ` as daily mean discharge; `QIXnJ` as daily maximum instantaneous discharge; `HIXnJ` as daily maximum instantaneous stage. The service offers other products, but current RivRetrieve config supports exactly these three hydrometry products plus temperature `resultat` (parameter `1301`). Do not imply RivRetrieve exposes all Hub'Eau products.
- Source hydrometric units are millimetres and litres per second. Current provider mappings preserve that basis and normalize to metres and cubic metres per second. Temperature parser verifies parameter `1301`, unit code `27` and `°C`; normalized unit is `degC`.
- HydroPortail Q unit code `l` is scoped to discharge and means l/s. Fresh scripts have SHA-256 `72571d0bd095d5cf616a1378e799aa5e8f6818330fcca2f5691891463a92cda6` and `ab41e52a4af9b0cec642de98c68cd445f4a9b269f705da45dc43bd5664494823`, exactly matching delivered unit evidence. Do not describe Q as a volume in litres.
- Current HydroPortail parser requires station code, Q/H metric, instantaneous title, correct selector, source unit, root `timezone=UTC`, and timestamps ending `Z`, even for empty responses. Output UTC clock labels use `time_zone=+00:00`; the time column is naive, so both columns matter.
- Hub'Eau page broadly says dates are UTC. Its elaborated daily labels alone do not establish the day boundary or complete 24-hour support. Current config/parser keep zone unknown and label at midnight. Daily mean has interval support with unknown day definition. Daily maxima identify a maximum of instantaneous observations within a day, not a published averaging interval or maximum of daily means. Do not convert the broad UTC sentence into a stronger support claim.
- Temperature source separate date/clock fields lack established zone; current parser preserves unknown zone and temporal support. Do not call it definitively instantaneous merely because sensors sample regularly.
- Hub'Eau documentation says some historical elaborated records go back to 1900. This is not a guarantee for each station, quantity or requested period. Retained HydroPortail bounded witnesses prove historical accessibility, not continuous or complete history.

### Stations, sites and catalogues

- Source station help says one site can contain several stations, at most one active at an instant for producing the site's discharge. A site is a reach with homogeneous/comparable discharge. A station is the measuring installation with stage and/or discharge. Current HydroPortail route is `/stationhydro/ajax/{station}/series`, not a site-combined route.
- `uv` packaged inspection confirms Hub'Eau 7,347 station rows: 6,475 native hydrometry and 872 native temperature. HydroPortail has 6,409 station rows. Counts refer to packaged snapshots, not a complete underlying network census or observation continuity.
- `maintenance/catalogue/fr_hydroportail/REPORT.md` retains native test-inclusive public inventory acquisition and separate Hub'Eau snapshots. Native site relationships come from source nesting. Do not derive site IDs by truncation or merge service catalogues because their codes overlap.
- All 6,409 native HydroPortail station codes overlap Hub'Eau hydrometry in retained reconciliation. Sixty-six Hub'Eau codes were absent from anonymous HydroPortail inventory and returned identity HTTP404. This establishes current publication differences, not nonexistence or lack of historical measurements. Keep service identity, coordinates and terms separate.

### Source selectors and status

- Fresh current Y251002001 station form contains exactly `most_valid`, `validated`, `pre_validated_and_validated`, `raw`. `most_valid` is checked by the website. This website default is not a RivRetrieve preference.
- Current provider `VARIANTS`, source mappings and `fetch.py` implement these four for Q and H. Fetch loops all variants and applies `scope.matches(target)` before the exact request. No preferred selector, substitution, fallback, local ranking or per-observation status filter appears in this path. Current public `rr.series(rr.find(...))` returns all four separately for Y251002001 discharge.
- `most_valid` remains a source selection. Current observations in retained evidence show it can equal raw or validated depending on the station/window. This does not establish an algorithm, mixed-status precedence or a quality ordering. `pre_validated_and_validated` is combined, not pre-validated-only. No corrected-only or pre-validated-only selector is published by this form.
- `tests/test_data/fr_hydroportail_variants/REPORT.md` retains 32 successful Q/H responses and exact source forms/scripts. Native `s`, `q`, `m`, `c` encode processing status, qualification, method and continuity separately. Requested selector and row processing status are different facts. Do not infer row metadata from the request label.
- Current parser preserves null measurements, while acquisition records supported source failures independently. Retained variant regressions cover null versus absent rows, empty successful responses and failed requests; emptiness of one selector/window establishes nothing about another. Do not describe failed requests as empty histories or suppress informational unknown-licence/citation issues in examples.

### Terms and attribution

- Fresh Hub'Eau terms section 5.1.3 retains the reviewed quotation: Etalab open licence, free/commercial reuse and citation of the dataset author. Licence Ouverte 2.0 requires source (at least licensor) and last-update date. Retrieval date is not automatically that update date. No standard citation string was established.
- HydroPortail legal/about/FAQ do not establish an Etalab reuse licence, standard citation for station records or original authorship of every historic measurement. Preserve these unknowns. The legal page's “BASE LEGALE” concerns personal data; public access is not a reuse-licence inference. Hub'Eau's terms do not transfer to HydroPortail.

## Contradictions or cautions reported

1. The current temperature API page still says approximately 760 stations while the packaged/native retained snapshot contains 872. Its update text also says quarterly and later real-time synchronization since July 2022. These are source-page ambiguities, not defects in this documentation implementation. Avoid copying the stale count or asserting an update cadence.
2. HydroPortail measurement-series help lists raw, combined pre-validated/validated, and most-valid, omitting the standalone validated selector. Current form, current delivered code and retained exact responses support four. Use the current form/captures for selector inventory rather than treating the prose help list as exhaustive.
3. The broad Hub'Eau UTC statement is not enough to change the established unknown daily day boundary or temperature zone/support. No new support evidence warrants a stronger claim.
4. No production defect or contradictory current selector behavior was established. No production repair was made or authorized. The final implementation owner must still execute final markdown examples live and preserve any real issues.


## Hub'Eau observation metadata follow-up (12:30 UTC)

The implementation owner requested direct support for source method/qualification metadata. Fresh `https://hubeau.eaufrance.fr/api/v2/hydrometrie/api-docs` and one bounded `obs_elab` request both returned HTTP 200 on 2026-09-21 at 12:30:21 UTC. Exact URLs, response hashes and bodies are under the archive member directory `hubeau-metadata/`; `checks.json` is the manifest. The JSON responses use `.html` filenames because the generic capture script names all bodies that way.

The current `Observation hydrométrique` schema includes `code_statut`, `libelle_statut`, `code_methode`, `libelle_methode`, `code_qualification`, and `libelle_qualification`. Their descriptions still contain untranslated `${doc.modele...}` placeholders. The returned labels themselves provide direct source facts without interpreting the numeric codes.

The exact request was `https://hubeau.eaufrance.fr/api/v2/hydrometrie/obs_elab?code_entite=Y251002001&date_debut_obs_elab=2024-01-01&date_fin_obs_elab=2024-01-01&grandeur_hydro_elab=QmnJ&size=1`.

The first day of the proposed reviewed example returns:

- `date_obs_elab`: `2024-01-01`; `resultat_obs_elab`: `1159.0` l/s.
- `code_statut=12`, `libelle_statut="Donnée pré-validée"`.
- `code_methode=8`, `libelle_methode="Calculée"`.
- `code_qualification=12`, `libelle_qualification="Douteuse"`.
- `date_prod="2026-08-18T10:06:51Z"`; the schema describes this as integration into Hub'Eau, not necessarily the measurement's original last-update date.

This is direct evidence that the numeric returned value and an empty RivRetrieve issue tuple do not establish source validation or qualification. Preserve source wording. Do not characterize the example as quality-approved. A short reader-facing sentence explaining that no retrieval issues is not a source-quality judgment is appropriate; the source supplies its own distinct status/method/qualification facts. The parser does not convert those fields into a ranking and the exact native response remains in the receipt. This source metadata is not a new product defect. The numeric value still agrees with the reviewed example's 1.159 m³/s.

SHA-256: schema `98217f1a8987d44682480dd2325482b81fee08de5311163d6eacc6ac883f92af`; row response `9cda94c803674b6210d8f44d96ec4a645a0430a625ae6dc9b6f218cee705b4b7`.
