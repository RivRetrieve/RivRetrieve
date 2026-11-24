# Germany PEGELONLINE source, scope and access

Complete [Effort #1016](https://github.com/RivRetrieve/RivRetrieve/issues/1016)
with an evidence-backed source-and-access handoff for Germany's federal
waterways hydrometric provider (`de_pegelonline`). This Effort covers source,
scope and access only, not catalogue building, series mapping, retrieval
code or provider integration. Verified completion of this vision completes
#1016; publishing this vision alone does not.

The port's coordination issue is [#874](https://github.com/RivRetrieve/RivRetrieve/issues/874),
which holds the full research record this vision draws on. Follow
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
  `water_temperature`, plus the plausibilized `TRM`/`TRM_WT` (*Terminwerte*)
  scheduled readings as a distinct stage variant. `WV`
  (*Wasserstandvorhersage*, model forecasts/estimates) and navigational
  `F`/`T` (channel depth/draft) are excluded as out of RivRetrieve's
  observational scope.
- **Vertical datum on `W` — do not collapse these:** `unit == "cm"` (669
  series) is relative to the station's gauge zero (*Pegelnullpunkt*) and
  converts `÷ 100` to metres. `unit == "m+NN"` (67 series, canal/lock-pool
  gauges) and `unit == "m+PNP"` (2 reservoir gauges) are **already in
  metres**, report absolute elevation above sea level (a different vertical
  reference than gauge zero), and must **not** be scaled — this is the exact
  100× bug present in the existing `wetterdienst` Python adapter.

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
the other. Decisive beyond that textual reading:
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

## Recorded unknowns

Per step 1's guidance, these stay unknown rather than inferred:

- Terms of use, licence and required attribution for the 13 domestic
  non-WSV stations (7 institutions; see above).
- Whether a 15-minute or 60-minute reading is an instantaneous sample or an
  interval mean (`statistic`). Neither the REST API documentation nor the
  SOS service's `"Einzelwert"` label resolves this; it stays `unknown`
  rather than assumed.
- The exact mechanical encoding of the unknown-terms status for the 13
  stations (for example, a `withheld_facts`-style provenance record) is left
  to the catalogue Effort, not decided here.

## Required handoff

The handoff establishes downstream responsibilities across the port:

- **[Catalogue #1017](https://github.com/RivRetrieve/RivRetrieve/issues/1017):**
  Build the station catalogue with `uuid` as `station_id`, `number` retained
  as source metadata, direct WGS84 coordinates (57 stations lack
  coordinates), the three `gaugeZero` datum regimes attached per-timeseries,
  and station-product associations across `W`, `Q`, `WT`, `TRM` and
  `TRM_WT`. Encode the 13 domestic non-WSV stations' unresolved terms as an
  explicit provenance fact, per the convention above.
- **[Series identity #1018](https://github.com/RivRetrieve/RivRetrieve/issues/1018):**
  Map `W`/`Q`/`WT`/`TRM` to distinct `SourceIdentity`/`PhysicalFacts`
  records with the `cm` vs `m+NN`/`m+PNP` vertical-datum split preserved
  exactly as scoped above.
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

Keep the continuing PEGELONLINE research record in the private
`verification-evidence` repository under the established evidence process;
no dedicated research branch exists there yet at the time of this vision, so
the Effort that creates or extends it should follow
[the evidence workflow](../../docs/maintenance/evidence.md) to establish one
rather than assume a prior path.
