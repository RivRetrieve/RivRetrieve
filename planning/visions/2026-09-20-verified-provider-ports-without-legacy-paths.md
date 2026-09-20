# Verified provider ports without legacy paths

Program: https://github.com/RivRetrieve/RivRetrieve/issues/284
Effort: https://github.com/RivRetrieve/RivRetrieve/issues/286

## Destination

Complete and verify all thirteen existing providers against the fact-based source-series engine landed by Effort 285. Users discover established physical facts, inspect separately published source identities, and retrieve every matching supported series through one consistent public workflow. Port and improve the provider implementations rather than layering new adapters over superseded logic.

The core is already delivered on `main` through PR 298 at `7c683c42561ff1764d81a6e5306adc6cc3b0cd58`. Its interface, admission rules, identity model, partial outcomes, storage and export contracts are the starting point, not questions to reopen. Representative provider ports already exist. Verify and complete them rather than blindly reimplementing them. Source research and reversible engineering choices belong to implementation; ask for a boundary decision only if evidence establishes that the approved outcome requires changing the settled contract or expanding excluded scope.

The user explicitly requires removal of legacy implementation and no backward compatibility. Keep one authoritative implementation under the new contracts. Remove superseded provider paths, obsolete helpers and declarations, compatibility aliases, parallel legacy pipelines, and tests whose sole purpose is preserving obsolete behavior. Do not retain the old implementation behind the new API. This is a functional refactoring and improvement, not a cosmetic wrapper change.

Removal is about obsolete behavior, not the age or spelling of a symbol. Existing source access coordinates, product identifiers used internally, source-specific protocol handling, and useful shared code may remain when they serve the new contracts. Preserve exact source recordings and meaningful scientific regressions; rewrite their assertions around the new behavior when necessary. Preserve unrelated work and evidence. Old incompatible files must still be refused clearly and left intact until an explicit destructive action; no silent reinterpretation, fabricated identities, automatic migration, dual-format support or legacy API aliases are required.

## Intended public experience

This example communicates the confirmed destination using the landed public vocabulary. It is not authority for another API redesign. Final examples must be checked against the shipped interface and actual provider evidence.

```python
import rivretrieve as rr

# Admitted discharge, including series with unknown temporal meaning.
discharge = rr.find(quantity="discharge")

# Only independently established daily-mean facts match.
daily = rr.pick(discharge, frequency="daily", statistic="mean")
brazil = rr.pick(daily, provider="br_ana", station="15400000")
rr.series(brazil)

# All matching supported series, including Bruto and Consistido separately.
result = rr.fetch(
    brazil,
    start="2020-01-01",
    end="2020-12-31",
    receipts=True,
)
rr.series(result)      # Also exposes response-discovered source identities.
rr.as_frame(result)    # Retains observation identity and physical context.
result.issues         # Retained source failures and unresolved limitations.

# Optional explicit selection, never a library-selected winner.
consistido = rr.pick(result, variant="consistido")
selection = rr.pick(brazil, variant="consistido")
selected_result = rr.fetch(
    selection, start="2020-01-01", end="2020-12-31"
)

# Admitted Swiss discharge can have unknown temporal support.
swiss = rr.find(provider="ch_foen", quantity="discharge")
swiss_daily = rr.pick(swiss, frequency="daily", statistic="mean")
```

Unknown temporal facts cannot satisfy the Swiss daily-mean predicate. More specific filtering requires more established facts, not a quality ranking or rigid information-level ladder. A singleton needs no variant choice. Norway's matching published versions remain distinct. Canada and Poland use the same discovery and retrieval model after explicit preparation of their local compiled stores. South Africa supports discovery only. Multi-provider discovery does not require collapsing provider-specific retrieval results into one ambiguous result.

## Source fidelity under the landed contract

Admission is per series: established physical quantity, source unit and dimensionally valid conversion to the harmonised unit are required. Preserve exact source vocabulary and explicit unsupported reasons when admission cannot be established. Caller issue policy cannot admit unknown-unit numbers or override contradictory source metadata. Optional facts such as frequency, statistic, temporal support, day definition, timestamp anchor, zone and vertical reference remain independent knowns or unknowns. Do not infer them from cadence, field-name guesses, typical values or numerical agreement.

Keep source identity separate from physical facts and inventory knowledge. All matching supported source series are returned without preference, first-block selection, fallback, averaging or deduplication across identities. Explicit restrictions remain explicit; a nonexistent variant does not substitute a sibling. Preserve the established `on_issue` behavior: raise reports recoverable issues by exception, warn retains diagnostics with warnings, ignore retains diagnostics without notification. Established no-match and unresolved inventory are different outcomes. Fatal internal contract errors remain fatal under every policy.

Catalogue snapshots, response-scoped inventories, availability, retrieval success and cache coverage are distinct. Do not advertise a static catalogue as a timeless exhaustive inventory. Preserve successful empty series, null values, absent rows, unsupported structures and failed requests distinctly; retain independent successful series alongside identified source failures. Keep native duplicate multiplicity where appropriate and preserve source wall-clock labels, established zones or unknowns, calendar-date versus timestamp clipping, provenance and exact optional parse-boundary receipts.

The engine already carries identity through definitions, rows, conversion, result inspection, selection and bundle round-trips, receipts and stores. Complete provider use of those contracts. Prove all-versus-subset cache behavior, refresh without sibling erasure, diagnostics without false successful coverage and honest retrieval vintage. Bulk/native values remain at rest and use the shared conversion exactly once. Cache/store excerpts are not reconstructed publisher bytes. Archive vintage is not automatically a coexisting hydrological alternative.

## Complete provider coverage

Cover every active live path, both compiled-store providers, and the catalogue-only provider. The following are evidence leads and required areas of verification, not predetermined classifications or an assertion that the old audit remains current.

| Provider | Required account |
| --- | --- |
| `br_ana` | Verify the existing daily Bruto/Consistido port, physical daily meanings and explicit selection without preference. Complete telemetry selector research: adopted access must not imply exhaustive inventory. Establish detailed sensor/manual/display channel meanings and units before enrollment; do not invent equivalence or conceal evidenced alternatives. |
| `usgs_nwis` | Verify existing multi-method parsing, explicit per-value associations, mixed supported/unsupported blocks and native multiplicity. Preserve response-owned method identities and catalogue claims without assuming a globally established `ts_id` to `methodID` mapping. Cover equal, conflicting and disjoint blocks, missing/ambiguous associations, singleton IDs and empty descriptions. |
| `no_nve` | Verify explicit published-version retrieval, returned identities, null versions and version-specific physical facts. Do not rely on the upstream preferred/newest default. Complete the account of acquired catalogue versions versus current/historical retrievability and inventory limits. Preserve the demonstrated Instantaneous-versus-Mean correction; resolution is not evidence of averaging. |
| `ch_foen` | Verify both HTTP and authenticated Flux paths. Preserve separate `flow`/`flow_ls` identity and established conversion, and independently evidenced meanings of `height`/`height_abs`. Neither metres nor agreement establishes reference equivalence. Establish temporal support where possible; `_reported` and ten-minute cadence do not establish a ten-minute product. Do not infer a datum or gauge-zero reference. |
| `ba_fhmzbih` | Investigate first-worksheet selection, the required `81 Web Kontinuirani` series name and L1 source-series fields. Preserve genuine identities and account for actual supported sheets/series rather than guessing that additional methods exist. |
| `fr_hubeau` | Establish what `statusData=raw` selects and whether accessible coexisting alternatives exist in supported scope. Row status, method, qualification and production flags are not automatically series variants. Site/station and distinct temporal/statistical products remain distinct. |
| `jp_mlit` | Establish the meaning and effect of `KAWABOU=NO` across supported routes. Tentative/final cells, filenames and formats are not invented alternatives. Preserve source-defined physical and temporal distinctions. |
| `cz_chmi` | Verify configured physical mappings and repeated `tsConID` behavior using publisher definitions. Broader dictionaries, including QNEX/QNEY, do not alone establish supported variants or authorize new products. |
| `lt_lhmt` | Verify historical daily-mean facts, singleton identity and inventory limits. Measured observations and historical routes are not presumed equivalent alternatives. |
| `th_thaiwater` | Verify enrolled routes, fields, singleton mappings and governing acquisition evidence. Do not treat canal inside/outside channels, agencies, datum metadata or forecasts as alternatives of enrolled tele_waterlevel series without source evidence. Preserve controlled evidence and its access boundaries. |
| `ca_eccc` | Verify HYDAT daily-table mappings, admission and identity through compilation, native cells, public retrieval and truthful store receipts. Symbols, precision and completeness metadata do not establish parallel variants. Latest artifact selection is not an obligation to expose every archive release. |
| `pl_imgw` | Verify source physical facts, monthly/annual archive regimes, native cells and compiled-store/public behavior. Packaging, overlap rules, sentinels and acquisition identifiers are not automatically series identities. |
| `za_dws` | Remain `CatalogueOnly`. Account for published variable identity, including `100.00`, supported physical mappings and unresolved inventory. Verify discovery and explicit observation refusal; do not activate retrieval. |

Complete each lead using publisher definitions and exact source responses. A source may legitimately expose one supported series. Retain honest limits where meaning, access or completeness cannot be established after investigation; this is not permission to stop at old assumptions or label a known omitted alternative nonexistent. No resource or schedule shortcut justifies unsupported classification. Necessary excluded expansion or a genuine core-contract conflict must be escalated, not silently implemented or declared solved.

## Existing evidence and implementation context

Read the Program Map and landed core vision as durable context, but distinguish their historical descriptions from current code. Relevant current contracts are `source_series.py`, `provider_series.py`, `selection.py`, `discovery.py`, `engine.py`, `driver.py`, `conversion.py`, `observations.py`, catalogue schemas/evidence and `store/` under `src/rivretrieve/_internal/`. Inspect every provider's declaration, configuration, fetch/parse, catalogue builder, origins and bulk operations where present. Shared typed mappings are useful only when their claims have source evidence; a citation to local configuration alone does not prove publisher meaning or inventory completeness.

Representative tests already cover Brazil daily alternatives, Swiss litre flow, explicit NVE versions and physical corrections: `tests/test_representative_source_series.py` and `tests/test_public_representative_source_series.py`. `tests/test_source_series_usgs.py` exercises method identities, public transport, caches and receipts. The original USGS problem response is now portable evidence; preserve its exact bytes and SHA-256 `92c43227ececed5373bc92abc4cbb19035dfc4b0ec7db736f2b4e443d8bf1275`, rather than substituting a new capture. Canada/Poland already have shared identity integration and bulk tests, including `tests/test_source_series_bulk.py` and `tests/test_bulk_series_outcomes.py`.

Inspect retained recordings in `tests/test_data/`, `tests/recordings/br_ana/`, catalogue inputs under `maintenance/catalogue/`, and current publisher definitions. Existing source limitations include unestablished detailed ANA stage channels, NVE inventory completeness and Swiss temporal meaning. Non-representative providers already have mapped-series integration; integration tests alone do not prove those physical classifications. Do not redo already proven core work or present old bugs as still unfixed without checking their actual paths.

## Observable completion

Delivery includes a provider-by-provider evidence and conformance account covering all thirteen, including negative findings, supported access boundaries, explicit unknowns, unavailable access and unresolved limitations. Keep this technical evidence with appropriate tests, source evidence and delivery records, not a new discovery-record system or provider narrative rewrite.

Rebuild affected catalogues, lineage and machine-readable descriptors consistently with established source facts. Source identity and classifications must agree across discovery, requests, parser output, public results, exports and relevant stores. Do not silently project away identity or promote incomplete inventory to completeness.

Prove the public workflow using actual permitted recordings and artifacts, not only fabricated frames or mocked parser outcomes. Cover every active live route, both bulk paths and catalogue-only behavior. Exercise relevant cache modes and receipts, admission and unknowns, multi-series defaults, optional narrowing, singleton behavior, mixed success/failure and independent-series isolation. Use existing exact recordings where adequate and capture missing evidence with non-secret request provenance. Credentials and controlled private corpora must not be published.

Every newly repaired bug starts with a failing test through the real failing path. For path/performance bugs, instrument the actual path. Keep source-grounded regression proof and complex-data library assertions. Audit the final code and maintained tests for leftover superseded logic, dead compatibility paths and old selection/classification behavior. Removal must be supported by inspection and regression evidence; passing through a new wrapper is insufficient.

Use the project environment and local validation: `uv run pytest` with the relevant project extras/evidence setup where required, `uv run ruff check`, `uv run ruff format --check`, and `uv run ty check src`. Do not suppress the intentional negative type fixture or replace unavailable evidence with fabricated proof. Independent review must assess the complete provider outcome, legacy removal and scientific/source fidelity, not just type conformance.

## Boundaries

Keep current shipped software documentation truthful as behavior changes. Effort 287 owns coherent comprehensive onboarding, reference and migration guidance. Provider-specific narratives remain colleague-owned. Use reader-oriented explanations and ordinary citations, not internal audit transcripts or new ADRs.

No new providers, unrelated product expansion, modernized USGS API migration, South African observation activation, source-quality ranking, harmonised observation-quality fields, inferred scientific meaning, computed unpublished products, hosted CI, documentation hosting or release publication. Release Program 6 remains unchanged. Source-specific quality vocabulary may identify genuinely separate published series, but does not authorize a row-quality feature or a preferred-series rule.

Follow existing composition boundaries, domain types and typed stages. Parse external facts at their arrival boundaries. Retain library carriers for bulk arrays. Name production components for stable responsibilities, not this ticket or delivery phase. Limit legacy removal to the provider migration and its directly related shared paths; unrelated repository cleanup is not required. This vision authorizes implementation only through the separate implementation workflow, not as part of its publication.
