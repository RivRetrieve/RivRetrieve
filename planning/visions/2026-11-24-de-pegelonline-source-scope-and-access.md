# Germany PEGELONLINE source, scope and access

Complete [Effort #1016](https://github.com/RivRetrieve/RivRetrieve/issues/1016)
with an evidence-backed source-and-access handoff for Germany's federal
waterways hydrometric provider (`de_pegelonline`). This Effort covers source,
scope and access only, not catalogue building, series mapping, retrieval
code or provider integration. Verified completion of this vision completes
#1016; publishing this vision alone does not.

The port's coordination issue is [#874](https://github.com/RivRetrieve/RivRetrieve/issues/874),
which holds most of the research record this vision draws on. One
additional check (terms and attribution, below) was performed during this
discussion and is recorded separately, in the private research record
referenced in "Completion". Follow
[provider-port step 1](../../docs/maintenance/provider-ports.md) and the
[evidence process](../../docs/maintenance/evidence.md). Keep all provider
port work on the dedicated `port/de-pegelonline` branch until the full port
is complete and approved in final review
[#1023](https://github.com/RivRetrieve/RivRetrieve/issues/1023).

## Settled scope

Publish `de_pegelonline` using unauthenticated, credential-free `LiveStages`
retrieval from **WSV/GDWS's PEGELONLINE** portal
(`https://www.pegelonline.wsv.de/`), specifically its documented **REST API
v2** (`https://www.pegelonline.wsv.de/webservices/rest-api/v2`). Gauges on
federal waterways are operated by the regional Wasserstraßen- und
Schifffahrtsämter (WSAs) under GDWS/WSV; PEGELONLINE additionally mirrors
gauges from other agencies (see provenance below).

- **Station identity:** `station_id = uuid`, WSV's own addressing guidance
  (its *User's Guide* explicitly warns against keying on `number` or name,
  which can change; six Dutch mirror stations also carry synthetic
  placeholder numbers). Retain `number` (*Pegelnummer*) as source metadata.
- **Access kind:** `LiveStages`, not `BulkStore` or `CatalogueOnly`. REST API
  v2 answers per station/timeseries over a rolling window; there is no bulk
  archive file.
- **Window:** REST API v2 serves a rolling **~31-day** retrieval horizon for
  `W` (stage), `Q` (discharge) and `WT` (water temperature). A request older
  than that returns `HTTP 200` with `[]`, meaning rolling retention has
  expired, not that the gauge went dry or offline. Omitting the `start`
  parameter silently truncates the response to the last 10 days; requests
  must always pass explicit `start`/`end`.
- **Catalogue scope: full catalogue, no RivRetrieve-side curation.** Include
  all three groups PEGELONLINE mixes into one catalogue, each carrying its
  own provenance rather than one combined WSV attribution:
  1. The 26 foreign cross-border mirror stations (Netherlands'
     Rijkswaterstaat, Austria's Via Donau, Czechia's Povodí Labe,
     Switzerland's Bundesamt für Umwelt) — these overlap `nl_rws`, `at_ehyd`,
     `cz_chmi` and `ch_foen`, which already carry their own established
     terms.
  2. The 13 domestic non-WSV stations across 7 German institutions (Hamburg
     Port Authority, Regierungspräsidium Freiburg, Wasserwirtschaftsamt
     Ingolstadt, Wasserwirtschaftsamt Landshut, Ruhrverband,
     Deichinformationszentrum Neuwied, BfG Koblenz) — see terms below.
  3. The 63 open-sea/lagoon tide gauges (North Sea, Baltic Sea, Jade Bay,
     Kleines Haff), which measure sea/lagoon level rather than river stage,
     alongside the inland river, canal and estuarine gauges.
- **Products:** the core quantities `W` → `stage`, `Q` → `discharge`, `WT` →
  `water_temperature`, plus the plausibilized *Terminwerte* scheduled
  readings as two distinct variants: `TRM` alongside raw `W` (stage, 120
  stations) and `TRM_WT` alongside raw `WT` (water temperature, 2
  stations) — `TRM` is not itself a stage reading plus a water-temperature
  reading combined; each variant attaches to its own quantity. `WV`
  (*Wasserstandvorhersage*, model forecasts/estimates) and navigational
  `F`/`T` (channel depth/draft) are excluded as out of RivRetrieve's
  observational scope.
- **Vertical datum on `W` — do not collapse these:** `unit == "cm"` (669
  series) is relative to the station's gauge zero (*Pegelnullpunkt*, PNP)
  and converts `÷ 100` to metres. `unit == "m+NN"` (67 series,
  canal/lock-pool gauges) is **already in metres** and reports absolute
  elevation above sea level (*Normalnull*) — a genuinely different vertical
  reference than gauge zero. `unit == "m+PNP"` (2 reservoir gauges) is also
  **already in metres**, but despite superficially resembling `m+NN`, it is
  still gauge-zero-referenced (PNP is literally *Pegelnullpunkt*): these two
  reservoirs' gauge zero happens to be set near `0 m. ü. NN`, so their
  readings numerically approximate sea-level elevation, but that is a
  coincidence of where their gauge zero was fixed, not what the quantity
  means. Scaling either `m+NN` or `m+PNP` by `÷ 100` is the exact 100× bug
  present in the existing `wetterdienst` Python adapter; keep both
  already-metric, but keep their differing references distinct.

### Deliberately out of scope for this port

- The undocumented `/gast/download/prepare` async archive route (reaches
  back to `2000-01-01` for `W`/`Q` on a subset of stations) is the mechanism
  behind a browser download button, not a documented, stable service. It
  stays out of `de_pegelonline` and has its own follow-up,
  [#1024](https://github.com/RivRetrieve/RivRetrieve/issues/1024), which
  decides separately whether and how RivRetrieve ever drives it
  programmatically.
- **HyDAS-API v1 (Beta)** and **OGC SOS 2.0/WFS/WMS** were investigated and
  dismissed: both are redundant with, or strictly worse than, REST API v2
  (HyDAS v1 holds the identical ~31-day window and is explicitly marked
  Beta/unstable by WSV; SOS 2.0 was found lagged ~13 days behind real time
  during verification).
- The static `/webservices/files/` daily file tree and the authenticated
  *Abo-Dienst* subscription service: both inferior to, or requiring
  credentials unlike, REST API v2.

## Access conditions and operational boundaries

- **No authentication, no API key, no documented numeric rate limit.** The
  shared transport's default pacing applies; no `ProviderRateLimit` override
  is needed.
- **Always parse `measurements.json`, never `.csv`.** The CSV variant uses
  German decimal commas and strips the UTC offset from timestamps, making
  the repeated local hour during the October DST fallback ambiguous.
  `measurements.json` keeps explicit ISO-8601 offsets (`+01:00`/`+02:00`)
  across that transition.
- **Address stations only by `uuid`.** Two stations can share a `shortname`
  (e.g. two different `NEUSTADT` gauges on different rivers); addressing by
  `shortname` silently returns the wrong one.
- **Missing values are absent rows, not `null`,** on raw `W`/`Q`/`WT`
  (`TRM` and `F`/`T` do publish JSON `null` for missing slots). Do not treat
  a reading of `0.0` as missing — `WT = 0.0 °C` and low/negative coastal `W`
  in `cm` are valid physical readings.
- **Errors:** a nonexistent station or an unserved timeseries on a valid
  station returns `HTTP 404`; a malformed `start`/`end` returns `HTTP 400`
  with a structured message; a station/timeseries outside the rolling
  window returns `HTTP 200` with `[]`.

## Terms and attribution

**Corrected 2026-11-24, after a closer re-reading of PEGELONLINE's terms
text; see below for what this section originally said.**

PEGELONLINE's terms page (`/gast/nutzungsbedingungen`) states, scoped to the
whole site and not to WSV-originated data specifically: "Informationen,
Produkte oder Dienste, die Sie von dieser Website erhalten, dürfen
übernommen werden. Dies geschieht auf der Grundlage der Lizenz
DL-DE->Zero-2.0" ("Information, products or services that you receive from
this website may be reused. This happens under the licence
`DL-DE->Zero-2.0`"). The preceding sentence — "PEGELONLINE additionally
displays third-party data from national and international authorities,
organisations and institutions, to which the above liability disclaimer
(*Haftungsausschluss*) also applies" — scopes only the liability/warranty
disclaimer (the section's own "Haftungsausschluss" heading) to that
third-party data. It does not say the licence grant is withheld from it, and
the licence paragraph that follows carries no origin-based exception.

RivRetrieve records the licence as the provider states it, without taking a
view on whether WSV/GDWS actually holds the right to license data it does
not itself originate — that is a question about the provider's own
authority, not about what its terms page says. `DL-DE->Zero-2.0` applies as
a single, provider-level licence across all 787 stations: the WSV-operated
stations, the 13 domestic non-WSV stations (7 institutions: Hamburg Port
Authority, Regierungspräsidium Freiburg, Wasserwirtschaftsamt Ingolstadt,
Wasserwirtschaftsamt Landshut, Ruhrverband, Deichinformationszentrum
Neuwied, BfG Koblenz), and the 26 foreign mirror stations (Rijkswaterstaat,
Via Donau, Povodí Labe, Bundesamt für Umwelt) alike. No per-station or
per-issuer split is needed, and the 26 foreign mirror stations' licence
here does not depend on, or need to match, what `nl_rws`/`at_ehyd`/
`cz_chmi`/`ch_foen` each separately established for their own direct
channels — PEGELONLINE is its own redistribution channel with its own
stated terms.

All stations stay in the catalogue, under this one licence.

<details>
<summary>Original 2026-11-24 text (superseded above)</summary>

WSV/GDWS's own data is published under **Datenlizenz Deutschland – Zero –
Version 2.0** (`DL-DE->Zero-2.0`), which permits unrestricted commercial and
non-commercial use, modification and redistribution without mandatory
attribution. The 26 foreign mirror stations inherit the terms already
established by their respective RivRetrieve providers (`nl_rws`, `at_ehyd`,
`cz_chmi`, `ch_foen`).

**The 13 domestic non-WSV stations' own terms are explicitly unverified and
must not default to `DL-DE->Zero-2.0`.** PEGELONLINE's terms page
(`/gast/nutzungsbedingungen`) states the licence applies to "information,
products or services you receive from this website," and separately says
copyright in the site's content lies with ITZBund/WSV "unless otherwise
stated" (*sofern nicht anders angegeben*) — but the same page already states
otherwise for this data: it explicitly discloses that PEGELONLINE "displays
third-party data from national and international authorities, organisations
and institutions" (*Daten Dritter*), and every one of these 13 stations
carries an `agency` field in the API naming its actual operator (e.g.
`RUHRVERBAND`), not WSV. Direct verification of the Ruhrverband station
`HATTINGEN` (`number 2769510000100`) confirmed neither the API nor its
human-readable station page carries any per-station licence text — the
site's copyright clause is never actually invoked for this data one way or
the other. (Recorded 2026-11-24 in the private research record; see
"Completion" below. This check covered only Ruhrverband; the other six
domestic non-WSV institutions were not individually checked.) Decisive beyond that textual reading:
[`docs/catalogue-provenance.md`](../../docs/catalogue-provenance.md)
already establishes the project-wide rule that "each issuing body's terms
stay on that body's material. A dataset with several issuing bodies does
not acquire a single combined licence or citation." Applying WSV's licence
to Ruhrverband's or Hamburg Port Authority's gauges would violate that rule
regardless of how PEGELONLINE's own text is parsed.

These 13 stations stay in the catalogue. Their terms are recorded as
genuinely unknown (not withheld, not guessed) until an institution-specific
check establishes otherwise — optional future thoroughness, not a blocker
for this Effort or any downstream one.

This reading turned out to be mistaken: it treated "der obige
Haftungsausschluss" (the liability disclaimer named just above) as if it
also scoped the licence grant, and applied `docs/catalogue-provenance.md`'s
rule against combining *separate* issuers' terms to a case where only one
issuer (WSV) is making one statement over everything the site serves — not
combining anyone else's terms into it.

</details>

## Recorded unknowns

Per step 1's guidance, this stays unknown rather than inferred:

- Whether a 15-minute or 60-minute reading is an instantaneous sample or an
  interval mean (`statistic`). Neither the REST API documentation nor the
  SOS service's `"Einzelwert"` label resolves this; it stays `unknown`
  rather than assumed.

(This section originally also listed the 13 domestic non-WSV stations'
terms as unknown, with a mechanical unknown-terms encoding left to the
catalogue Effort. That was resolved on 2026-11-24 — see "Terms and
attribution" above — and no longer needs an encoding.)

## Required handoff

The handoff establishes downstream responsibilities across the port:

- **[Catalogue #1017](https://github.com/RivRetrieve/RivRetrieve/issues/1017):**
  Build the station catalogue with `uuid` as `station_id`, `number` retained
  as source metadata, direct WGS84 coordinates (57 stations lack
  coordinates), the three `gaugeZero` datum regimes attached per-timeseries,
  and station-product associations across `W`, `Q`, `WT`, `TRM` and
  `TRM_WT`. Record `DL-DE->Zero-2.0` as the single provider-level licence
  (see "Terms and attribution" above); no per-station terms encoding is
  needed.
- **[Series identity #1018](https://github.com/RivRetrieve/RivRetrieve/issues/1018):**
  Map `W`/`Q`/`WT`/`TRM`/`TRM_WT` to distinct `SourceIdentity`/`PhysicalFacts`
  records with the `cm` vs `m+NN`/`m+PNP` vertical-datum split preserved
  exactly as scoped above, and `TRM_WT` kept attached to water temperature,
  not folded into the `TRM` stage variant.
- **[Retrieval #1019](https://github.com/RivRetrieve/RivRetrieve/issues/1019):**
  Implement request rules that always pass explicit `start`/`end`, address
  by `uuid`, and treat an out-of-window empty response as rolling retention,
  not failure.
- **[Integration #1020](https://github.com/RivRetrieve/RivRetrieve/issues/1020),
  [verification #1021](https://github.com/RivRetrieve/RivRetrieve/issues/1021), and
  [user documentation #1022](https://github.com/RivRetrieve/RivRetrieve/issues/1022).**
  Verification has no overlapping published benchmark dataset to compare
  against (CAMELS-DE ends 2020-12-31, before this source's rolling window) —
  confirmed with the maintainer, who will spot-check live values manually
  instead of requiring an automated bounded comparison.
- **[Final review #1023](https://github.com/RivRetrieve/RivRetrieve/issues/1023):**
  blocked until all of #1016–#1022 are closed. Merge into `main` only after
  explicit maintainer approval of the completed result.
- **[#1024](https://github.com/RivRetrieve/RivRetrieve/issues/1024)** is a
  related but separate decision (whether to ever drive the undocumented
  historical archive route) and is not required for this port's completion.

## Completion

The continuing PEGELONLINE research record lives in the private
`verification-evidence` repository, branch `research/de-pegelonline-source-access`
(`research/de-pegelonline-source-access.md`), which extends #874's findings
with the terms-and-attribution check this vision cites above. Later Efforts
should keep extending this same file, per
[the evidence workflow](../../docs/maintenance/evidence.md), rather than
starting a separate one.
