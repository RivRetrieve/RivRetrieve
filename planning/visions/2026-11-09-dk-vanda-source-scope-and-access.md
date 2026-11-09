# Denmark VandA source, scope and access

Complete [Effort #796](https://github.com/RivRetrieve/RivRetrieve/issues/796) with an
evidence-backed source-and-access handoff for the Danish hydrometric provider
(`dk_vanda`). This Effort covers source consolidation, scope definition, and bounded
access verification, not provider implementation. Verified completion of this
vision completes #796; publishing this vision alone does not.

The port belongs to [Program #351](https://github.com/RivRetrieve/RivRetrieve/issues/351).
Follow [provider-port step 1](../../docs/maintenance/provider-ports.md) and the
[evidence process](../../docs/maintenance/evidence.md). Keep all provider port work
on the dedicated `port/dk-vanda` branch until the full port is complete and approved
in final review [#803](https://github.com/RivRetrieve/RivRetrieve/issues/803).

## Settled scope

Publish `dk_vanda` using direct, unauthenticated `LiveStages` retrieval from
Denmark's **Miljøstyrelsen** (Danish Environmental Protection Agency) VandA
service at `https://vandah.miljoeportal.dk/api`, the national hydrometric
database behind the Miljøportal platform. Stations are owned by
Miljøstyrelsen and several carry a separate `operatorName` (e.g. "DCE, Aarhus
Universitet"), a distinction preserved as station metadata, not collapsed.

This supersedes legacy `RivRetrieve-Python` PR #88 and hydrodownloadR's
`adapter_DK_VANDA.R` (see #351). Live re-verification on 2026-11-09 (recorded
in the private research record) reconfirmed the `GET /stations`,
`GET /water-flows` and `GET /water-levels` request shapes both references use,
found the catalogue has grown from 2,886 to 3,157 stations since #351's
2026-09-23 probe, and found two things neither reference nor #351 established:
the API's full `swagger.json` endpoint inventory, and a separate, explicitly
DVR90-labelled examination (`Vandstand DVR90`, `examinationTypeSc` 21) that
contradicts #351's claim that the API never names the datum anywhere.

Use `LiveStages`, not `BulkStore`: VandA answers per station and time window
through `GET /water-flows`/`GET /water-levels`, with no bulk archive file
comparable to Poland's or Canada's publications, and the catalogue can be
built from `GET /stations` directly.

Include:

1. **Discharge (`discharge`, native `l/s`, returned `m3/s`):** the continuous
   `Vandføring` series, `examinationTypeSc` 27, published at 277 stations per
   #351 (re-verification here did not repeat the per-series count, only the
   request shape; Effort #797 should recount against the now-3,157-station
   catalogue). VandA publishes no pre-aggregated hourly/daily/monthly variant
   of this series anywhere the two references or this pass found; it serves
   raw, irregular-cadence timestamped readings only (confirmed 15-minute
   cadence in the worked example, station 19000467). **Do not derive a daily
   mean inside RivRetrieve.** Both prior references compute one themselves
   from the 15-minute values; the provider-port guide explicitly warns
   against inferring a daily mean from cadence alone, and VandA does not
   publish one. Expose the native cadence as retrieved.
2. **Stage (`stage`):** the continuous `Vandstand` series, `examinationTypeSc`
   25, published at 1,135 stations per #351. Each reading carries two values:
   a raw `result` (native `cm`, returned `m`) and a `resultElevationCorrected`
   (native integer, unit unconfirmed; #351 treats it as mm, needs direct
   confirmation in Effort #798). The two prior references disagree on which
   one is "the" stage. Per the provider-port guide's rule against collapsing
   separate records, **expose both as distinct, independently selectable
   series** (e.g. `stage` for the raw reading and a second variant for the
   corrected value), matching how hydrodownloadR's `prefer` option keeps both
   rather than picking one, and matching the precedent in `au_bom`/`br_ana` of
   keeping genuinely different per-reading values as separate source
   identities instead of one assumed answer.
3. **Water temperature (`temperature`, native `°C`):** the continuous
   examination `examinationTypeSc` 29, published at 64 stations per #351,
   confirmed reachable through `/measurements/results/current` in #351's
   probe. Included on the same precedent as `au_bom`'s inclusion of water
   temperature alongside discharge and stage; Effort #799 should confirm it
   is reachable through the same `/water-flows`/`/water-levels`-style request
   shape or requires the general `/measurements/results/*` family instead.

### Documented upstream options excluded from `dk_vanda`

- **Field gaugings (`Vandføring Feltmåling`, `examinationTypeSc` 24):** manual
  spot measurements at 533 stations per #351, not a continuous automated
  series comparable to the admitted `Vandføring` product. Candidate for a
  future Effort, not this first port.
- **Levelling surveys (`Kotemåling`, `examinationTypeSc` 21, including the
  `Vandstand DVR90` examination found in this pass):** manual surveyed
  heights at 1,184 stations, a different measurement process from the
  continuous stage series, not a retrievable time series of the admitted
  kind. Kept as supporting evidence for the stage-datum question (Effort
  #798), not admitted as its own product here.
- **Instrument diagnostics** (`Batterispænding`/battery voltage,
  `examinationTypeSc` 42) and any other non-hydrological examination type:
  excluded as out of RivRetrieve's river-gauge scope.
- **Non-river station types** mixed into the unfiltered `/stations` response:
  `Grundvandsboring` (groundwater borehole, 1,436), `Sø` (lake, 94),
  `Pumpestation` (23), `Hav` (sea, 19), `Havn` (harbour, 9), `Dræn` (drain,
  9), `Brønd` (well, 2). The catalogue Effort (#797) filters to the
  `Vandløb` (river) subset, 1,565 of 3,157 stations as of 2026-11-09.
- **Write/mutation endpoints** (`/stations/update`, `/measurements/update`,
  `/measurements/correct`, `/measurements/delete*`, `/measurement-points/
  update`) found in `swagger.json`: not applicable to a read-only port.

## Access conditions and operational boundaries

- **Anonymous HTTPS access:** every request in this pass succeeded over
  standard HTTPS `GET` without credentials, cookies or session tokens.
- **No pagination mechanism exists.** `swagger.json` declares no page/offset/
  limit parameter on any endpoint, and a 109-year, 530,764-row request at one
  station returned the complete, untruncated result in one 122.8 MB response
  (57 seconds). A request spanning a station's full history is not capped by
  the source, but the shared engine's window-splitting (Effort #799) needs to
  bound request size deliberately rather than relying on the source to do it.
- **Clean, typed error for an unknown station:** `HTTP 400` with a structured
  JSON body naming the missing station, not a 500 or a silent empty 200.
- **Result-version duplication is unresolved, not refuted.** #351 reported
  `/measurements/results/all` returning double the rows of `/water-flows` for
  an equivalent window, evidence of multiple result versions per timestamp.
  Re-verification today did not reproduce that doubling at the same station
  for either stage or discharge. Retrieval code (Effort #799) must not assume
  single-version behaviour just because today's check shows it; see the
  research record for the full comparison.
- **No documented rate limit** was found in `swagger.json` or in response
  headers; hydrodownloadR's self-imposed 3 requests/second remains that
  adapter author's own choice, not a confirmed VandA rule.
- **Quality marks are a separate, per-year endpoint**
  (`/quality-assurance/quality-marks?stationId=`), not an inline field on each
  reading; confirmed working, returning one row per year of a station's
  record with a `level`/`reservation`/`allotmentDateTime`.

## Terms and attribution

**Not resolved by this pass.** `vandah.miljoeportal.dk` and
`www.miljoeportal.dk` are JavaScript-rendered applications; a plain HTTP
fetch of either site's root page returns no licence or terms text to grep.
This needs a browser-capable check or a documented API-docs/terms page in a
follow-up pass before Effort #802 (user documentation) can state terms with
confidence. Do not infer a licence from the data being reachable without
authentication.

## Recorded unknowns

Per step 1's guidance, these stay unknown rather than inferred:

- Terms of use, licence and required attribution for VandA/Miljøstyrelsen
  data (see above).
- The unit of `resultElevationCorrected` (treated as mm by #351 and as cm by
  neither reference's explicit statement; needs direct confirmation).
- Whether `resultElevationCorrected` uses the same DVR90 datum the catalogue's
  separate `Vandstand DVR90` (`examinationTypeSc` 21) examination names
  explicitly, or a different reference.
- Whether the result-version doubling #351 reported is a real, recurring
  VandA behaviour or specific to the station/window/day it checked.
- Whether `catchmentAreaKm2` (empty on every station checked) can be
  reliably recovered from free-text `description`, or must stay unresolved.

## Required handoff

The handoff establishes downstream responsibilities across the port:

- **[Catalogue #797](https://github.com/RivRetrieve/RivRetrieve/issues/797):**
  Build the station catalogue from `GET /stations` filtered to `Vandløb`
  (or via `examinationTypeSc`/`parameterSc` server-side filters), reconcile
  station identity (`stationId`, `stationUid`) and coordinates (SRID 25832,
  numerically confirmed against Denmark's bounding box in the research
  record), and resolve the `catchmentAreaKm2` gap.
- **[Series meaning #798](https://github.com/RivRetrieve/RivRetrieve/issues/798):**
  Map discharge, both stage variants, and water temperature to distinct
  `SourceIdentity`/`PhysicalFacts` records; confirm `resultElevationCorrected`'s
  unit and datum directly rather than assuming either reference's claim;
  record the per-year quality marks and the unresolved result-version
  question honestly.
- **[Retrieval #799](https://github.com/RivRetrieve/RivRetrieve/issues/799):**
  Implement `fetch.py`/`parse.py` against `GET /water-flows`/`GET
  /water-levels`, with deliberate request-size bounding (no source-side cap
  exists) and tolerance for more than one result per timestamp regardless of
  what today's check shows.
- **[Integration #800](https://github.com/RivRetrieve/RivRetrieve/issues/800),
  [verification #801](https://github.com/RivRetrieve/RivRetrieve/issues/801), and
  [user documentation #802](https://github.com/RivRetrieve/RivRetrieve/issues/802).**

## Completion

Maintain the continuing Denmark research record in the private
`verification-evidence` repository
(`research/dk-vanda-source-access.md`, branch
`effort-796-dk-vanda-source-access`), which retains exact request receipts
(UTC time, HTTP status, byte size, SHA-256) and the full re-verification
table this vision summarizes.
