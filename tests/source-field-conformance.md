# Swiss, Bosnian and French source-series conformance

Scope: the supported `ch_foen`, `ba_fhmzbih` and `fr_hubeau` observation routes.
This account describes source evidence and executable conformance. It does not
assert national or historical inventory completeness.

## Switzerland

The exact parameter dictionary in
`test_data/ch_foen_parameters_2026-09-02.recording.json` publishes:

| Field | Source label | Source unit | Established meaning |
| --- | --- | --- | --- |
| `flow` | Abfluss m3/s | m3/s | discharge |
| `flow_ls` | Abfluss l/s | l/s | discharge, converted by 0.001 |
| `height` | Pegel m ü. M. | m | stage above sea level |
| `height_abs` | Pegel m | m | stage, reference unestablished |
| `temperature` | Wassertemperatur | °C | water temperature |

Fields keep separate source identities, including when numbers agree.
Neither height field establishes equivalence to the other. No gauge zero or
exact datum is inferred. The retained BAFU FAQ names LN02 for BAFU metre-above-sea-level
heights, but an exact binding to each intermediary representation is not established.

`ch_foen_bafu_hydrology_data_service.html` distinguishes support points,
5-minute means, 10-minute means and hourly means. `ch_foen_terms_bafu.html`
describes normal logger averaging and exceptions. These do not establish the
exact support of the intermediary fields. Frequency, statistic, support and anchor
remain unknown. Explicit Unix seconds and Flux UTC labels establish the time zone.

The retained Existenz API documentation limits REST history to 32 days and
provides an authenticated archive route. It also warns that locations do not
measure all parameters and that gaps occur. Absence of a field in a response is
not successful empty coverage or proof of historical absence.

### Exact public Flux capture

`test_data/ch_foen_2135_flux_engine_2020-01-01.recording.json` was acquired on
2026-09-20 through the existing recording entry point. The publisher's public
read-only archive credential was supplied through scoped authentication. The
recording retains credential header names, not values.

The public request is `2020-01-01T00:00:00` through `2020-01-01T00:50:00`.
The exact query uses normal engine padding and an exclusive stop:
`2019-12-30T00:00:00Z` through `2020-01-03T00:50:00.000001Z`.
Independent CSV inspection found six requested-window flow values:
67.6, 67.6, 67.6, 67.5, 67.5, 67.39 at ten-minute labels from 00:00 through 00:50.
This label spacing is not evidence of measurement support.

`test_source_field_public.py` replays the exact request through `rr.fetch`,
checks clipping, publisher receipts, credential exclusion, explicit flow cache
refresh/reuse, retrieval vintage and bundle identity. Existing representative
public tests preserve the actual `2251` litre-flow response and independent
height-field tests. New product catalogue rows list all route fields rather
than a preferred field. Active lineage describes identified observations,
not the superseded five-column output.

## Bosnia

The eight exact workbook recordings under `test_data/ba_fhmzbih_*recording.json`
(excluding the metadata recording) each contain one worksheet. Independent ZIP/XML
inspection found `#Timeseries Name = 81 Web Kontinuirani` in every workbook.
The observed worksheet names carry group, station and parameter coordinates,
not evidence of additional methods. The headers establish Proticaj in m³/s,
Vodostaj in cm, and Temperatura vode in °C. Workbook timestamps have no established
zone or temporal support. Empty workbooks remain distinct from blank value cells.

`ba_fhmzbih_metadata_index.recording.json` is a 60-row layer-20 acquisition.
All captured `L1_stationparameter_no` values are Q, all units m³/s, all names
`81 Web Kontinuirani`; there are 60 distinct `L1_ts_id` values. Packaged catalogue
claims retain these discharge identifiers and source coordinates, with normalized
lineage bound to this exact acquisition. They are not aliases for workbook
identities. The workbook does not publish that numeric ID. No H/WT numeric ID is
inferred from the discharge snapshot. Stable station metadata remains unchanged.

The supported workbook decoder requires one worksheet. A multi-worksheet response
has unestablished relationships and returns an identified unsupported outcome
instead of silently reading the first sheet. No alternative sheet identity is
invented. `test_source_field_boundaries.py` proves the previous omission by adding
a second sheet to an exact workbook as a negative structural mutation.

Malformed or unresolved layer-20 routing responses remain exact receipts with
station/product-scoped unsupported outcomes. They do not become internal contract
errors or successful empty coverage. Tests prove that an independent station
still returns rows and that all three issue policies preserve classification.
Unrepresentable workbook rows are unsupported rather than silently dropped into successful coverage. Meaningful native workbook parsing, null handling and source count checks remain.

The maintained workbook access ledger covers 180 station/product pairs. Its
private source corpus was not opened or published for this work. The public
corruption/verification tests do not certify unavailable private source bodies.
Existing recorded public tests cover 2101-B Q/H, 2010 Q with two blanks, 4024 H,
and an empty temperature workbook. Named-source cache and bundle tests exercise
`81 Web Kontinuirani` without a fabricated variant label.

## France

### Source identities and facts

HydroPortail uses the station route, not a shared site route. The retained
`fr_hydroportail_station_Q_padded.recording.json` publishes `series.title`
starting `Débit instantané`; `fr_hydroportail_H_padded.recording.json` starts
`Hauteur instantanée`. These direct response titles establish quantity and
instantaneous statistic/support for the exact route. The parser validates the
semantic title prefix before handling empty data. It does not match an entire
station-specific title. `timeStep=null` and observed spacing do not establish
frequency, which remains unknown. UTC is explicit in both the envelope and labels.

The Q source unit code `l` is defined as l/s by the exact retained publisher JS
unit-selector and localization captures (`fr_hydroportail_unit_definition_*`).
The existing context-bound source-unit definition remains in use. H uses mm.
Conversion happens once in the shared physical conversion stage.

HydroPortail requests `hydro_series[statusData]=raw`, and responses publish
`statuses=raw` and titles saying `Données brutes de l'entité`. `raw` is retained
as the evidenced source selector. Row `s`, `q`, `m`, and `c` flags are not series
identities or a harmonised quality feature. The retained localization also names
most-valid, validated and pre-validated/validated status options, but this does
not establish their exact selector behavior or separately accessible coexisting
series. Read-only station page, raw AJAX and JS requests returned HTTP 403 in this
investigation. No bypass was attempted. Alternative-selector inventory remains
explicitly incomplete; raw is not advertised as the only source series.

The retained Hub Eau OpenAPI defines QmnJ as daily mean discharge, QIXnJ as daily
maximum instantaneous discharge, and HIXnJ as daily maximum instantaneous height.
`fr_hubeau_hydrometrie.html`, section “Unités des observations”, establishes l/s
for discharge and mm for height on that API. Daily mean establishes interval
support, but no exact day definition or timestamp anchor. Daily maximum products
remain daily/max without an additional exact support claim. Date-only labels are
represented at midnight; a display label does not establish hydrological support.
No source zone is inferred from date-only daily values.

Temperature recordings publish parameter 1301, `symbole_unite=°C`, and
`code_unite=27`. These are checked at the response boundary. The published °C
spelling is retained; the normalized unit is degC. Contradictory metadata cannot
admit numbers under any issue policy. Exact temporal support and zone remain unknown.

### Public and failure proof

Recorded public tests cover station Q (282 rows), H (576 rows), daily
mean, two daily maxima, five-page temperature retrieval, clipping-to-empty,
nulls and exact publisher receipts. The new named raw cache/bundle test preserves
the response-owned identity and serves honest store excerpts on reuse.

Invalid pagination metadata or an out-of-domain next URL is retained as an
unsupported source response, not a fatal internal error. The request is never
sent to the foreign URL. An independent daily series survives. A late invalid
continuation after valid temperature pages retains partial rows and diagnostics,
but shared storage does not certify complete interval coverage; reuse must reacquire.
Tests use clearly labelled negative mutations of exact recorded responses.

## One authoritative fact declaration

France and Bosnia use the shared `SeriesMapping.physical_facts()` contract for
both runtime definitions and catalogue descriptions. Product catalogue columns
are projections of those same facts through `catalogues.products.product_row`;
source access coordinates remain separate. Facts cite retained publisher evidence,
not local configuration as scientific authority. Swiss field-owned facts remain
custom because each response field has its own identity and independent units/reference.

Superseded preferred-field declarations and obsolete output-shape lineage were
removed. Useful protocol decoders remain. No compatibility aliases, automatic
store migration, inferred variants or quality ranking were added.

## Regression and validation records

Fail-first proof is recorded under `.worktrees/evidence/effort-286/`:

- `source-fields-red.log`: eight failures through actual worksheet, fetch,
  catalogue and lineage paths; `source-fields-green.log`: the same eight pass.
- `source-fields-facts-red.log`: source unit spelling/contradiction and missing L1
  claims.
- `source-fields-title-red.log`: unvalidated contradictory publisher temporal title.
- `source-fields-projection-red.log`: divergent canonical product support/anchor.
- `source-fields-row-red.log`: unrepresentable workbook row still receiving successful coverage.
- `source-fields-lineage-red.log`: product physics attributed to metadata instead of Q/H/WT source headers.

The final checked-in tests preserve positive exact recordings and distinguish
negative authored mutations. Validation commands use the project `uv` environment. The final new conformance
slice passed 29 tests. The final public regression slice passed 27 tests. The
24-file owned-provider run passed 366 tests with one changed-output digest pin
failure; after updating only the generated provider/product pins, that independent
content-and-pin test passed. Native station and availability pins were unchanged.
`uv run ruff check`, `uv run ruff format --check`, and `uv run ty check src` passed.
No controlled source corpus, credential value, or colleague-owned provider narrative
was added or rewritten.
