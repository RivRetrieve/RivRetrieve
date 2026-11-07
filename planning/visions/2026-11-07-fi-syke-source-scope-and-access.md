# Finland SYKE source, scope and access

Complete [Effort #753](https://github.com/RivRetrieve/RivRetrieve/issues/753) with an
evidence-backed source-and-access handoff for the Finnish hydrology provider
(`fi_syke`). This Effort covers source consolidation, scope definition, and bounded
access verification, not provider implementation. Verified completion of this vision
completes #753; publishing this vision alone does not.

The port belongs to [Program #353](https://github.com/RivRetrieve/RivRetrieve/issues/353).
Follow [provider-port step 1](../../docs/maintenance/provider-ports.md) and the
[evidence process](../../docs/maintenance/evidence.md). Keep all provider port work on
the dedicated `port/fi-syke` branch until the full port is complete and approved in
[final review #760](https://github.com/RivRetrieve/RivRetrieve/issues/760).

## Settled scope

Publish `fi_syke` using direct, unauthenticated `LiveStages` retrieval from the Finnish
Environment Institute's (Suomen ympäristökeskus, Syke) hydrology **OData** service,
`https://rajapinnat.ymparisto.fi/api/Hydrologiarajapinta/1.1/odata`. Every selected
entity set answers per site, paged through `odata.nextLink`, matching the shape of other
`LiveStages` providers (`au_bom`, `cz_chmi`, `jp_mlit`) rather than a bulk archive
download.

This scope supersedes legacy [PR #112](https://github.com/kratzert/RivRetrieve-Python/pull/112)
and hydrodownloadR's `adapter_FI_SYKE.R`, re-verified live on 2026-11-07 (full detail in
the private research record, `research/fi-syke-source-access.md`). Both references agree
on three variables, confirmed again today via the service's own `Suure` quantity
catalogue and `TauluKuvaus` table descriptions:

1. **Discharge (`discharge`, native `m3/s`, entity set `Virtaama`, `Suure_Id=2`):** 711
   sites (462 marked `Jatkuva`/continuing, `Tila_Id=1`).
2. **Stage (`stage`, native `cm`, entity set `Vedenkorkeus`, `Suure_Id=1`):** 1,753 sites
   (809 continuing). RivRetrieve converts stage from centimetres to metres, as it does
   for other providers that publish stage in cm.
3. **Surface water temperature (`temperature`, native `°C`, entity set `LampoPintavesi`,
   `Suure_Id=11`):** 79 sites (36 continuing).

All counts were re-queried today against the live `Paikka` site list, filtered by
`Suure_Id`, and are consistent with issue #353's 2026-09-23 counts (711/462, 1,752/810,
79/36) to within one site on stage, a plausible six-week drift rather than a
re-verification failure. The full site list (`Paikka`, all quantities) stands at 3,978
sites with no catchment-area field; coordinates are available both in a packed
degrees-minutes-seconds form (`KoordLat`/`KoordLong`) and in ETRS-TM35FIN
(`KoordErTmIta`/`KoordErTmPohj`, EPSG:3067).

### Documented upstream options excluded from `fi_syke`

- **Water temperature profile (`LampoLuotaus`, `Suure_Id=12`, deferred):** 11 sites,
  confirmed live today. hydrodownloadR reads this; the legacy PR does not. It reports
  temperature at a named depth (`Syvyys`) rather than one surface value per day, a
  different shape from the single-series `temperature` product used elsewhere in
  RivRetrieve. Defer rather than fold into the surface `temperature` product, while
  keeping its availability documented in the research record and provider
  documentation.
- **Runoff (`Valuma`, `Suure_Id=3`, deferred):** 107 sites, confirmed live today, unit
  `l/s/km2`. hydrodownloadR reads this; the legacy PR does not. Runoff is not one of
  RivRetrieve's three supported quantities (`discharge`, `stage`, `temperature`) across
  providers; defer in line with that existing scope rather than introducing a fourth
  quantity for this one source, while recording its availability.
- **Everything else the service publishes** (evaporation, areal and point precipitation,
  snow water equivalent, snow course measurements, ice thickness, ice freeze/break-up
  dates, areal precipitation) is out of scope as non-river-gauge hydrology, matching
  RivRetrieve's existing scope boundary.

## Access conditions and operational boundaries

- **Anonymous global HTTPS access:** Every endpoint above responds over standard HTTPS
  `GET` with no credentials, cookies, session token, or API key, and no `robots.txt`
  exists at `rajapinnat.ymparisto.fi` (confirmed `HTTP 404` today).
- **Follow `odata.nextLink`; never send `$top` on a paged request.** Confirmed live
  today on both request shapes:
  - **List requests** (`Paikka`, filtered by `Suure_Id`): without `$top`, the server
    returns 500 rows and an `odata.nextLink`; the identical request with `$top=500`
    returns exactly 500 rows and **no** `nextLink`, silently stopping at the first page.
  - **Value requests, a new finding beyond issue #353's research:** the same default-500
    page size and `nextLink` requirement apply to per-site value requests
    (`Virtaama?$filter=Paikka_Id eq 894` returned 500 rows and a `nextLink` on its first
    page; the complete paged history is 24,781 rows, 1959-01-01 through 2026-11-05).
    hydrodownloadR's description ("one request per site, following `nextLink`") already
    assumed this; the legacy PR's fixed 365-day/`$top=500` windows happen to stay under
    the page limit per request, which is why its own `$top` usage never visibly
    truncated anything, but would silently truncate a longer window if one were ever
    requested without re-checking this cap.
- **No documented rate limit.** Checked the live service and Syke's terms pages;
  hydrodownloadR's self-imposed 3 requests/second is the adapter author's own choice,
  not a source-stated limit. Carry forward as an unconfirmed default, not a verified
  rule.
- **Data currency:** the discharge series checked today (site 894) runs through
  2026-11-05, two days before this research pass, consistent with near-daily publication
  rather than a archival lag of months or years.

## Terms and attribution

Checked live on 2026-11-07, not assumed from hydrodownloadR's licence labels or issue
#353's deferred "source-terms survey" placeholder:

1. **Syke's current terms page** (`syke.fi/en/environmental-data/use-license-and-responsibilities`):
   states Syke's open data, including its APIs, is licensed under **Creative Commons
   Attribution 4.0 International (CC BY 4.0)**, conditioned on mentioning "the name of
   the licensor and the name of the data," with a worked example ("Groundwater bodies /
   Source: Finnish Environment Institute (Syke)"). The same page states that some
   Syke-distributed data carries specific restrictions, documented per dataset rather
   than on this general page; no restriction specific to `Hydrologiarajapinta` was
   found.
2. **`avoindata.fi`'s open-data catalogue entry** for the `Hydrologiarajapinta` dataset
   group independently lists the same CC BY 4.0 license and names Syke as publisher,
   agreeing with (1).
3. **An unreconciled, apparently older page**
   (`syke.fi/en/projects/hydrological-data-services`) lists "Information retrieval fee"
   and "Soon to be an open database for everyone" next to a real-time hydrological data
   item. Every request made against the actual OData service during this research
   answered unauthenticated with no fee gate of any kind, which points to this page
   describing a different or superseded system rather than the service `fi_syke` would
   use. Treat this as an open discrepancy to flag in `fi_syke`'s user documentation
   (step 7), not as evidence against (1) and (2), and not silently dropped.

Use the attribution form from (1) ("Source: Finnish Environment Institute (Syke)")
for `fi_syke`'s provider documentation and catalogue terms, matching the agency's own
worked example rather than inventing new wording.

## Recorded unknowns

- Whether `Arvo` (the published value in `Virtaama`/`Vedenkorkeus`/`LampoPintavesi`) is
  a daily mean, a single instantaneous daily reading, or something else: no table
  description states this.
- The time zone of `Aika` timestamps: every tested row carries no offset and is stamped
  `00:00:00`.
- The stage vertical datum: `VedenkTasoTieto` gives each site its own height system
  (`N2000`, `NN`, `N60`, `N43` seen across an initial sample) and a numeric correction,
  but `Vedenkorkeus` publishes stage in the site's own uncorrected system, and neither
  reference implementation applies the correction. Heights are therefore not comparable
  across sites from `Vedenkorkeus` alone.
- The meaning of the 63 named `Lippu` flag codes beyond their Finnish description text,
  including whether a flagged value carries any reliability or redistribution
  implication.
- The "Information retrieval fee" discrepancy above.

## Required handoff

Maintain the continuing Finland research record in the private `verification-evidence`
repository (`research/fi-syke-source-access.md`) and retain non-measurement receipts
(status, byte size, SHA-256, row counts, first/last date labels) inline there. No
observation values are retained anywhere in this handoff.

The handoff establishes downstream responsibilities across the port:

- **[Catalogue #754](https://github.com/RivRetrieve/RivRetrieve/issues/754):** Build the
  river-gauge station catalogue from the union of sites across the three admitted
  `Suure_Id` values, using `Paikka`'s packed DDMMSS and ETRS-TM35FIN coordinates, and
  decide how (or whether) to expose each site's `Tila_Id` status (continuing,
  discontinued, occasional, fixed-term) as a catalogue fact.
- **[Series meaning #755](https://github.com/RivRetrieve/RivRetrieve/issues/755):** Map
  `Virtaama`, `Vedenkorkeus`, and `LampoPintavesi` to distinct `SourceIdentity` and
  `PhysicalFacts` records; resolve or explicitly carry forward as unknown whether `Arvo`
  is a daily mean; decide whether and how to surface the `VedenkTasoTieto` per-site datum
  correction; and record the 63 `Lippu` flag codes' Finnish text without inventing an
  English redistribution meaning the source does not state.
- **[Retrieval #756](https://github.com/RivRetrieve/RivRetrieve/issues/756):** Implement
  `fetch.py`/`parse.py` to follow `odata.nextLink` on every paged request, list and
  value alike, and never send `$top` on a request expected to return more than 500 rows.
- **[Integration #757](https://github.com/RivRetrieve/RivRetrieve/issues/757),
  [verification #758](https://github.com/RivRetrieve/RivRetrieve/issues/758), and
  [user documentation #759](https://github.com/RivRetrieve/RivRetrieve/issues/759):**
  Wire `fi_syke` into `LiveStages`, certify against retained evidence, and document the
  CC BY 4.0 attribution form, the unresolved "Information retrieval fee" discrepancy,
  the unapplied stage datum correction, and the excluded water-temperature profile and
  runoff series.

## Completion

Verify this vision's live findings are reproducible (a fresh `nextLink`-following
request against `Paikka` and at least one value entity set, re-checked independently)
before closing #753. Post a concise scope update on #353 and a completion summary on
#753. Keep #353 and Efforts #754 through #760 open, and do not assign final review
(#760) until Efforts #753 through #759 are complete.
