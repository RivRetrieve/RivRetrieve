# Germany PEGELONLINE (`de_pegelonline`) — station catalogue and metadata

Associated issue:
[#1017](https://github.com/RivRetrieve/RivRetrieve/issues/1017)
("PEGELONLINE provider port: 2. Station catalogue and metadata"). This
vision covers that issue's full outcome; closing it is left to the
implementing agent once the catalogue is verified built and merged.

Builds on step 1's published vision,
[`2026-11-24-de-pegelonline-source-scope-and-access.md`](2026-11-24-de-pegelonline-source-scope-and-access.md)
(merged via [#1025](https://github.com/RivRetrieve/RivRetrieve/pull/1025),
corrected via [#1030](https://github.com/RivRetrieve/RivRetrieve/pull/1030)),
and the continuing research record in the private
[verification-evidence](https://github.com/RivRetrieve/verification-evidence)
repository
(`research/de-pegelonline-source-access.md`). Both are the primary evidence
behind this vision and are not reproduced here beyond what's needed to act.

## Outcome

A reproducible catalogue builder for `de_pegelonline`
(`src/rivretrieve/_internal/providers/de_pegelonline/generate_catalogue.py`
or equivalent) that populates, via the shared
[catalogue schemas](../../src/rivretrieve/_internal/catalogues/schemas.py)
and [publication path](../../src/rivretrieve/_internal/catalogues/publication.py):

- `StationCatalog` — one row per PEGELONLINE station.
- `ProductCatalog` — one row per distinct quantity/variant this provider exposes.
- `StationProductCatalog` — availability of each product at each station.
- `ProviderInfoCatalog` — the single provider-level record, including licence.
- The source-view metadata table
  ([`SOURCE_METADATA_SCHEMA`](../../src/rivretrieve/_internal/station_metadata.py))
  carrying native per-station fields that have no dedicated catalogue column.

The [Lithuania builder](../../src/rivretrieve/_internal/providers/lt_lhmt/generate_catalogue.py)
is the closest existing illustration of provider/product/station/station-product
tables built together; inspect current code before copying its pattern, since
`de_pegelonline`'s source shape differs in several of the ways below.

Source: `GET https://www.pegelonline.wsv.de/webservices/rest-api/v2/stations.json?includeTimeseries=true&includeCharacteristicValues=true`
— the only request needed to build the whole catalogue. No authentication,
no documented rate limit; keep the shared transport's default pacing.

## Scope — all 787 stations, no exclusions

PEGELONLINE mixes several station groups into one flat catalogue; none are
excluded here:

- 718 WSV-operated stations.
- 13 domestic non-WSV stations across 7 institutions (Hamburg Port
  Authority, Regierungspräsidium Freiburg, Wasserwirtschaftsamt Ingolstadt,
  Wasserwirtschaftsamt Landshut, Ruhrverband, Deichinformationszentrum
  Neuwied, BfG Koblenz) — identifiable by the station's `agency` field.
- 26 foreign cross-border mirror stations (Rijkswaterstaat, Via Donau,
  Povodí Labe, Bundesamt für Umwelt).
- 63 open-sea/lagoon tide gauges (North Sea, Baltic Sea, Jade Bay, Kleines
  Haff), alongside the inland river/canal/estuarine gauges.

None of these groups gets different catalogue treatment from the others —
same station schema, same licence (below), same product mapping where the
underlying quantity matches.

## Station catalogue (`StationCatalog`)

- `station_id = uuid`. Address and key **only** by `uuid`; `shortname` has at
  least one real collision (two distinct `NEUSTADT` gauges on different
  rivers, different `uuid`s) and must never be used as a key.
- `latitude`/`longitude`: direct WGS84 passthrough from the API's
  `latitude`/`longitude` fields, no reprojection.
- 57 stations publish no coordinates at all. Keep them in the catalogue with
  `latitude`/`longitude = null` and `crs = "unknown"`. Do not exclude them
  and do not infer coordinates from any other field (e.g. `km` plus `water`
  is a linear-referencing position, not a coordinate).
- Everywhere else, `crs` is WGS84 (the API's native and only coordinate
  system).

## Source metadata (`SOURCE_METADATA_SCHEMA`)

Carry these native per-station API fields through verbatim as
`source_field`/`source_value` pairs, with no filtering of which ones are
"useful": `agency`, `number`, `water` (the water body's `shortname`), `km`
(river-kilometre position), and `shortname`/`longname` if not already
covered by a dedicated column. `gaugeZero` is per-timeseries, not
per-station — attach it at the product/station-product level (see below),
using the schema's secondary datum sub-value mechanism
(`source_datum`/`source_datum_field`/`datum_support_fact`).

## Products (`ProductCatalog`) and station-product associations

Five distinct `product_id`s, matching step 1's settled mapping — never
collapse any of these into another:

| Native shortname | `observed_property` | Stations | Notes |
|---|---|---|---|
| `W` | `stage` | 738 | see vertical-datum split below |
| `Q` | `discharge` | 96 | |
| `WT` | `water_temperature` | 142 (per 2026-11-24 independent re-check; step 1's original research recorded 141 — immaterial drift) | |
| `TRM` | `stage` (its own product, not folded into `W`) | 120 | scheduled (*Terminwerte*) reading variant of stage |
| `TRM_WT` | `water_temperature` (its own product, not folded into `WT`) | 2 | scheduled reading variant of water temperature |

`WV` (*Wasserstandvorhersage*, model forecast/estimate) and the navigational
`F`/`T` (channel depth/draft) are out of scope — do not create products for
them.

**Vertical datum on `W` — three regimes, keep distinct, never conflate:**

- `unit == "cm"` (669 series): relative to the station's gauge zero
  (*Pegelnullpunkt*). Convert `÷ 100` to metres at the retrieval/series-identity
  layer (not this catalogue step, but the regime must be recorded here so
  that layer can find it).
- `unit == "m+NN"` (67 series, canal/lock-pool gauges): **already in
  metres**, absolute elevation above sea level (*Normalnull*) — do not scale.
- `unit == "m+PNP"` (2 reservoir gauges): **already in metres**, but still
  gauge-zero-referenced (PNP = *Pegelnullpunkt*) despite numerically
  resembling sea level — do not scale, and do not treat as the same
  reference as `m+NN`. Scaling either already-metric unit by `÷ 100` is the
  exact bug present in the existing `wetterdienst` Python adapter.

Record each `W` series' regime and its `gaugeZero` value (object or `null`)
through the source-metadata datum mechanism referenced above, so the
series-identity step (`#1018`) has what it needs without re-fetching.

**`statistic = "unknown"`** for every product here. Whether a 15-minute or
60-minute reading is an instantaneous sample or an interval mean is
genuinely unresolved — neither the REST API documentation nor the SOS
service's `"Einzelwert"` label settles it. This follows existing
precedent (`ch_foen`, `dk_vanda`, `no_nve`, `pe_senamhi` all use the same
literal string for the same reason); do not guess a value.

**`StationProductCatalog.availability`:** `"available"` for every
station/product pair the source catalogue actually lists a timeseries for;
do not infer availability for a product a station doesn't list.

**`published_record_start_date`/`published_record_end_date`: both `null`,
always.** PEGELONLINE exposes only a rolling ~31-day window via this API,
never a fixed published historical start or end. Treating the probed window
or a station's operating period as a published record bound would be
wrong — same precedent as `ch_foen`
(`src/rivretrieve/_internal/providers/ch_foen/generate_catalogue.py:225-226`).

## Licence (`ProviderInfoCatalog`)

`license = "DL-DE->Zero-2.0"`, `citation` whatever PEGELONLINE's terms page
states beyond the licence name (verify its exact wording when building),
as a **single provider-level value covering all 787 stations** — no
per-station or per-issuer split, and no `withheld_facts` or special
provenance encoding for the 13 domestic non-WSV or 26 foreign-mirror
stations.

This is settled by step 1's corrected "Terms and attribution" section
(corrected via #1030): PEGELONLINE's terms page states the licence over
"Informationen, Produkte oder Dienste, die Sie von dieser Website
erhalten" with no origin-based exception, and the one sentence disclosing
third-party data only extends the *liability disclaimer* to it, not the
licence grant. Record the licence as the provider states it; take no view
on whether WSV/GDWS actually holds the right to licence data it doesn't
itself originate. Do not have the 26 foreign-mirror stations' licence here
depend on, or need to match, what `nl_rws`/`at_ehyd`/`cz_chmi`/`ch_foen`
separately established for their own direct channels — PEGELONLINE is its
own redistribution channel with its own stated terms.

`live_stations`, `live_products`, `live_station_products` are all `true`
(the REST API serves the full current catalogue live, every call). There is
no bulk-download route in scope for this provider (the undocumented
`/gast/download/prepare` async archive route is explicitly out of scope,
per step 1 and its own follow-up,
[#1024](https://github.com/RivRetrieve/RivRetrieve/issues/1024)); set
`bulk_observations` accordingly.

## Explicit exclusions from this vision's scope

- Defining `SourceIdentity`/`PhysicalFacts` records, units conversion
  logic, and annotation schemas is step 3's job
  ([#1018](https://github.com/RivRetrieve/RivRetrieve/issues/1018)). This
  vision only needs the catalogue-level product/station-product shape and
  the native facts (regime, `gaugeZero`) that step 3 will consume.
- Retrieval request behavior (explicit `start`/`end`, rolling-window empty
  responses, `.json` vs `.csv`) is step 4's job
  ([#1019](https://github.com/RivRetrieve/RivRetrieve/issues/1019)).
- No new schema fields, no new `SourceStatement.verification_status` enum
  value, and no new per-station licence mechanism are needed for this
  provider — the existing single-scalar `license`/`citation` design is
  sufficient once the licence question above is settled as a single
  provider-wide value.

## Verification before considering this complete

- Rebuild the catalogue from a fresh live fetch and confirm: 787 stations
  total; `W`/`Q`/`WT`/`TRM`/`TRM_WT` counts matching the table above (within
  immaterial drift, as already observed between the 2026-11-17 and
  2026-11-24 checks); the three `W` unit regimes present with their
  recorded counts (`cm` 669, `m+NN` 67, `m+PNP` 2); the `NEUSTADT`
  `shortname` collision resolved to two distinct `uuid`s; 57 stations with
  null coordinates.
- Run `validate_catalogue()` against all four schemas and fix any
  `FatalContractError` before packaging.
- Confirm the packaged/approved artifacts follow the existing publication
  path's reproducibility requirements (same tool used by other providers'
  step-2 deliveries).

## Material risk / residual uncertainty

- The 15-vs-60-minute `statistic` ambiguity is recorded as `unknown`
  deliberately, not a gap to close in this Effort.
- The licence reading above rests on this session's interpretation of
  German terms-of-use text, not a legal opinion; it is recorded as the
  provider's stated terms, which is all RivRetrieve's provenance model
  requires.
