# Netherlands Rijkswaterstaat DDAPI 2.0 source, scope and access

Complete [Effort #1048](https://github.com/RivRetrieve/RivRetrieve/issues/1048)
with an evidence-backed Step 1 (source, scope and access) handoff for the
Netherlands hydrometric provider (`nl_rws`), backed by Rijkswaterstaat's
Waterwebservices DDAPI 2.0. This Effort establishes source facts, licensing,
scope boundaries, and retained genuine evidence; it does not build the station
catalogue, implement series mappings or retrieval code, or register the
provider. Verified completion of this vision completes `#1048`; publishing this
vision alone does not.

The port's coordination issue is
[#355](https://github.com/RivRetrieve/RivRetrieve/issues/355), tracked in
[#870](https://github.com/RivRetrieve/RivRetrieve/issues/870). Follow
[provider-port step 1](../../docs/maintenance/provider-ports.md) and the
[evidence guide](../../docs/maintenance/evidence.md). Keep all provider port
work on the dedicated `port/nl-rws` branch (and matching `port/nl-rws` branch
in `verification-evidence`) until the full port is complete and explicitly
approved in final review
[#1055](https://github.com/RivRetrieve/RivRetrieve/issues/1055). Never merge
into `main` before `#1055` is approved.

## Settled scope

- **Provider identity and access kind:** `nl_rws` (Rijkswaterstaat,
  Netherlands), using `LiveStages` against unauthenticated HTTP `POST` JSON
  endpoints on DDAPI 2.0
  (`https://ddapi20-waterwebservices.rijkswaterstaat.nl`), specifically
  `/METADATASERVICES/OphalenCatalogus` for station/product discovery and
  `/ONLINEWAARNEMINGENSERVICES/OphalenWaarnemingen` for observations.
- **Station / water-body scope:** Keep **all** surface-water
  (`Compartiment = OW`, *Oppervlaktewater*) locations that publish in-scope
  measured quantities. Rijkswaterstaat's `OW` network spans rivers, canals,
  lakes, tidal estuaries, and coastal/offshore locations; document this full
  surface-water scope honestly rather than applying heuristic spatial or name
  filters.
- **Quantities, units, and vertical references** (all within
  `Compartiment = OW` and `ProcesType = "meting"`):
  - **Discharge (`Q`):** include both `m3/s` and `m3/d` (both converting to
    canonical `m3/s`).
  - **Stage (`WATHTE`, `cm`):** convert to canonical `m`, preserving all four
    published vertical references (`NAP`, `MSL`, `TAW`, `PLAATSLR`) as distinct
    references without collapsing or falling back across datums (contingent on
    Step 1 confirming each datum's official definition).
  - **Water temperature (`T`, `oC`):** canonical `degC`.
- **Published aggregations (`WaardeBewerkingsMethode`):** Primary target is
  `NVT` (native cadence, e.g. 10-minute) and `GEM24H` (published 24-hour mean,
  *Etmaalgemiddelde*, which is also the sole historical discharge series for
  older decades). Step 1 must inventory any additional `WaardeBewerkingsMethode`
  values present for in-scope `OW` quantities with real location counts so
  downstream Efforts can decide whether to admit or explicitly defer them.

### Explicit exclusions and source-fidelity rules

- **Observations only (`ProcesType = "meting"`):** Every observation request
  must enforce `ProcesType = "meting"`. Exclude `verwachting` (forecasts) and
  `astronomisch` (astronomical tide), which share identical quantity, unit, and
  reference codes with measured series.
- **No collapsing of parallel measured series:** A single `meting` request can
  return multiple distinct series (for example, `WaardeBepalingsMethode` `F216`
  unchecked and `F230` checked 10-minute series alongside `GEM24H` daily means).
  Keep each distinct source series separate; never flatten parallel series or
  fabricate daily means from 10-minute readings.
- **Source annotations, not rankings or synthetic variants:** Preserve
  observation qualifiers such as `Statuswaarde` (`Gecontroleerd`,
  `Ongecontroleerd`, etc.) and `Kwaliteitswaardecode` through declared
  `AnnotationSchema` definitions with verified official descriptions and
  official `http`/`https` `reference_url` links.
- **Out of scope:** Non-surface-water compartments (e.g. groundwater, air,
  bottom sediment), regional Dutch *Waterschappen* (separate agencies), and
  silent fallback to deprecated legacy DDL v1 endpoints.
- **Leads, not authority:** Treat legacy PR
  [`kratzert/RivRetrieve-Python#98`](https://github.com/kratzert/RivRetrieve-Python/pull/98)
  and `hydrodownloadR`'s `adapter_NL_RWS.R` strictly as leads to recheck against
  live DDAPI 2.0 responses and official Rijkswaterstaat/Aquo documentation.

## Repository facts and known starting leads

From [#355](https://github.com/RivRetrieve/RivRetrieve/issues/355) (2026-09-23
live check):

- `POST /METADATASERVICES/OphalenCatalogus` returned HTTP 200 (~7.4 MB): 2,499
  locations, 2,151 metadata entries, and 102,339 location–metadata links. Each
  location carried `Code`, `Naam`, `Lat`, `Lon`, and `Coordinatenstelsel`.
- Measured `OW` location counts observed at that check: `Q` `m3/s` (199), `Q`
  `m3/d` (9), `WATHTE` `cm` against `NAP` (661) / `PLAATSLR` (23) / `MSL` (18)
  / `TAW` (8), and `T` `oC` (1,104).
- Observation entries carried `Tijdstip` with explicit offset (e.g. `+01:00`),
  `Meetwaarde.Waarde_Numeriek`, and `WaarnemingMetadata` with `Statuswaarde`
  and `Kwaliteitswaardecode` (e.g. `00`, `25`, `99`).
- Legacy PR #98 and RWS DDL documentation note numeric sentinel values (such as
  `999999999`) for missing values; exact DDAPI 2.0 sentinel behavior must be
  verified directly against live responses.

## Required Step 1 investigation and evidence of completion

An implementing agent completes `#1048` by establishing and recording the
following against genuine live DDAPI 2.0 responses and official documentation:

1. **Publisher, terms, licence, and attribution:** Verify Rijkswaterstaat's
   official terms of use, licence (expected CC0 1.0, must be confirmed directly
   from Rijkswaterstaat's official portal or data catalogue), and citation
   wording. If a terms page requires JavaScript or cannot be read by automated
   tools, ask the maintainer to open it directly before drafting any external
   correspondence.
2. **Access conditions and operational boundaries:** Confirm current DDAPI 2.0
   endpoint paths, authentication requirements (none expected), any published
   numeric rate limits (to determine whether RivRetrieve's default shared
   transport spacing suffices or a `ProviderRateLimit` is needed), request
   window/response limits, empty-response shapes, and error responses.
3. **Catalogue and coordinate inventory:** Capture a fresh genuine
   `OphalenCatalogus` response and inventory all `OW` (`ProcesType = "meting"`)
   combinations of `Grootheid`, `Eenheid`, `Hoedanigheid`,
   `WaardeBewerkingsMethode`, and `WaardeBepalingsMethode`, along with all
   `Coordinatenstelsel` values and whether `Lat`/`Lon` are directly WGS84 or
   require reprojection.
4. **Representative observation evidence and semantics:** Retain small genuine
   `OphalenWaarnemingen` responses covering:
   - Discharge `Q` in `m3/s` (including parallel `F216`/`F230` 10-minute series
     and `GEM24H` daily means, plus a historical `GEM24H`-only window such as
     March 1990) and `Q` in `m3/d`.
   - Stage `WATHTE` across `NAP`, `MSL`, `TAW`, and `PLAATSLR`.
   - Water temperature `T` in `oC`.
   - Verification of `ProcesType = "meting"` filtering, sentinel missing-value
     encodings, timestamp offset/DST behavior, `GEM24H` day-end timestamp
     semantics, and official definitions + `reference_url` links for
     `Statuswaarde`, `Kwaliteitswaardecode`, and the four vertical references.
5. **Continuing private research record and retained collection:** Retain the
   genuine Step 1 responses in `verification-evidence` under the established
   evidence intake process and document all dated findings, references, and
   explicitly unresolved unknowns in `research/nl-rws-source-access.md` on
   branch `port/nl-rws` in `verification-evidence`.
6. **Public handoff on `#1048`:** Post a concise, safe summary on `#1048`
   linking the retained evidence collection and research record (keeping
   private material out of public code, issues, and artifacts).

## Downstream handoff across the port

- **[Catalogue #1049](https://github.com/RivRetrieve/RivRetrieve/issues/1049):**
  Build the offline catalogue and approved packaged artifacts for all in-scope
  `OW` stations using the coordinate and metadata findings from Step 1.
- **[Series identity #1050](https://github.com/RivRetrieve/RivRetrieve/issues/1050):**
  Define `SourceIdentity`, `PhysicalFacts`, and declared `AnnotationSchema`
  mappings preserving parallel measured series, both `Q` units, all four
  `WATHTE` vertical references, and any admitted `WaardeBewerkingsMethode`
  values.
- **[Retrieval #1051](https://github.com/RivRetrieve/RivRetrieve/issues/1051),
  [Integration #1052](https://github.com/RivRetrieve/RivRetrieve/issues/1052),
  and [User documentation #1054](https://github.com/RivRetrieve/RivRetrieve/issues/1054):**
  Implement `ProcesType = "meting"` request planning, shared-engine
  integration, and `docs/providers/nl_rws.md` on `port/nl-rws`.
- **[Verification #1053](https://github.com/RivRetrieve/RivRetrieve/issues/1053):**
  Verify end-to-end against genuine retained DDAPI 2.0 inputs. **Pinned manual
  step:** external hydrograph sanity comparison will use **E-STREAMS** later
  when the maintainer is at the computer with the local dataset; **never
  download E-STREAMS automatically**.
- **[Final review #1055](https://github.com/RivRetrieve/RivRetrieve/issues/1055):**
  Blocked until `#1048`–`#1054` are closed. Merge `port/nl-rws` into `main`
  only after explicit maintainer approval, then mark `nl_rws` complete in
  `#870`.
