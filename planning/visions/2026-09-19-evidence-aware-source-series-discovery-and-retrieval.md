# Evidence-aware source-series discovery and retrieval

Program: https://github.com/RivRetrieve/RivRetrieve/issues/284
Effort: https://github.com/RivRetrieve/RivRetrieve/issues/285

## Outcome and authority

RivRetrieve harmonises established physical meaning and access while preserving separately published source-series identities. Users start with a physical quantity, narrow by additional established facts, and retrieve every matching supported series without a library-selected winner. Deliver a working public discovery-to-retrieval-to-cache workflow with real provider evidence, not an engine framework awaiting provider proof.

The repository is private and unreleased, with no users or backward-compatibility obligation. The user explicitly authorises a complete core redesign where needed. Do not preserve current schemas, product names, APIs, or abstractions merely to avoid breaking changes. There is no compatibility-period, legacy-alias, or automatic migration requirement. This authority does not permit silent reinterpretation of old observations or deletion of unrelated local evidence. Resource or schedule shortcuts do not justify unsupported source classifications.

This vision is the confirmed discovery outcome for the Effort. It settles the admission and compatibility questions left open in the Program. In particular, the earlier proposal to return unknown-unit numeric observations as a lower information tier was superseded by the admission rule below. Exact API spelling and reversible implementation mechanisms remain engineering decisions. The illustrative interface is not an already available API.

## Admission first, then information specificity

A supported observation series must have an established physical quantity and source unit, with an established conversion to RivRetrieve's harmonised unit. An identity conversion is sufficient where the source already uses that unit. Evidence may be in publisher documentation rather than repeated in each response. Do not infer quantity or unit from typical values, field-name guesses, or other providers.

Apply admission per series, not automatically to its entire provider. An unsupported parameter does not exclude independent supported series. Preserve an inspectable unsupported status and reason for series below the threshold; do not advertise them as supported, silently omit the limitation, or return their numbers as harmonised observations. Missing source unit, unresolved unit meaning, or an unestablished conversion cannot be bypassed by caller issue policy. Preserve exact published unit vocabulary where available: an unrecognised label and an absent label are different evidence states.

The physical quantity determines the target unit. Frequency and statistic do not change it: instantaneous and daily mean discharge both return m³/s. Known quantity alone cannot determine how to convert a publisher's number. Resolve unit facts at the concrete source-series or necessary segment granularity, validate dimensional compatibility, and do not apply a configured conversion to contradictory response metadata.

Above admission, information can be known independently. Frequency/resolution, statistic, temporal support, day definition, timestamp anchor, time zone, and vertical reference/datum are not a rigid ladder, quality score, confidence score, or universal completeness enum. A daily mean may have an unknown day definition. Known metres do not establish a water-level reference or datum. Publisher update cadence and regularly spaced labels do not establish interval support or averaging.

A broad quantity filter includes admitted series with incomplete temporal information. A precise predicate matches only an established fact: unknown temporal meaning cannot satisfy daily mean, and unknown reference cannot satisfy a named vertical reference. Keep source silence distinct from facts RivRetrieve has not yet established. Physical matches do not promise scientific interchangeability.

## One public workflow

The following expresses agreed behaviour, not frozen signatures:

```python
import rivretrieve as rr

# Every admitted discharge series; temporal facts may be unknown.
discharge = rr.find(quantity="discharge")

# Only established daily mean discharge.
daily = rr.pick(discharge, frequency="daily", statistic="mean")

# Both published daily consistency series match; no preference.
brazil = rr.pick(daily, provider="br_ana", station="15400000")
result = rr.fetch(brazil, start="2020-01-01", end="2020-12-31")

# Inspect identities, physical facts, inventory scope, and outcomes.
rr.series(result)

# Optional explicit narrowing, before or after retrieval.
reviewed_selection = rr.pick(brazil, variant="consistido")
reviewed_result = rr.pick(result, variant="consistido")
```

A provider with one matching series needs no extra choice. Preserve its published identifier even if its description is empty. When no distinction is published, describe it as unspecified instead of inventing a publisher label such as raw or standard. Unspecified identity is not proof that no alternatives exist.

The same discovery operation must accept physical filters directly, as in `rr.find(quantity="discharge", frequency="daily", statistic="mean")`. Product shorthand may remain as a convenience for established physical predicates, but cannot hide a preferred source series. Final names, inspection carrier, and identifier encoding must form one coherent interface rather than a collection of provider-specific workflows.

Inspection and explicit narrowing must work on selections and retrieved results, including response-discovered identities and successful empty series. A post-fetch restriction does not pretend a new source request occurred. Preserve relevant diagnostics, provenance, and receipts honestly when narrowing.

## Identity, physical facts, and inventory are separate

Keep these concepts distinct:

- The physical description and evidence for each known or unknown fact.
- The provider's published series identifier, selector, and description in its own vocabulary.
- The user's requested scope, including physical predicates and any explicit source restriction.
- The acquired inventory and its completeness, evidence, scope, and vintage.
- Each concrete series' retrieval outcome and successful observation-window coverage.

ANA consistency, USGS method identifiers, NVE versions, and Swiss fields do not have one harmonised substantive meaning. An internal key is allowed for stable identity, but must not masquerade as a publisher claim. Do not derive source identity from response order, numerical equality, or a fabricated preferred/singleton label. Distinct statistics and vertical references are physical differences, not harmless alternatives to conceal under a variant label.

Some identities are catalogue-known; others are discovered in a response. Preserve both evidence origins without assuming undocumented mappings between their identifiers. Selections are immutable descriptions of intent and known evidence. An unrestricted request retains its all-matching scope rather than silently freezing to the currently listed catalogue alternatives. A concrete user restriction remains concrete; late discoveries must be evaluated against the original physical and identity predicates.

Round-trips must preserve source identity, facts, explicit restrictions, and relevant inventory/diagnostic state. Do not reconstruct runtime-only identities solely from packaged station/product edges. Validate imported values at the boundary rather than trusting arbitrary frame columns as scientific evidence. Result and frame/export interfaces must retain enough identity and physical-unit context to interpret each value; do not erase distinctions in a five-column projection. Empty and failed series need inspectable outcomes outside observation rows.

Define “all matching supported source series” relative to the supported source access/mapping, station and physical scope, requested interval where relevant, and acquired inventory vintage. Catalogue inventory, scoped response inventory, and timeless exhaustive source discovery are not interchangeable. A static catalogue does not promise exhaustive current or historical inventory. A successful empty window does not prove that a series or alternative never exists. Known absence, unresolved discovery, unavailable retrieval, and absent identifiers remain distinct.

Incomplete inventory must be explicit. Preserve unresolved explicit restrictions until supported acquisition can settle them, or return an identified unresolved-inventory issue; never declare established no-match or choose a sibling merely because a catalogue lacks the identity. The implementing agent must define the acquisition boundary coherently without making ordinary offline discovery silently contact observation services.

## Issues, partial results, and fatal errors

Preserve the existing `on_issue` concept for recoverable selection and retrieval problems. For an established nonexistent variant:

| Policy | Observable outcome |
| --- | --- |
| `raise` | Exception |
| `warn` | Warning plus empty selection, with the issue retained |
| `ignore` | Empty selection with the issue retained |

No policy substitutes another variant. Ignore suppresses notification, not diagnostics. Under warn or ignore, supported source failures retain independent successful series together with the failing identity and reason. Informational facts do not automatically become policy-triggering failures. Caller reporting policy does not alter failure classification or admission.

Keep null values, absent rows, successful empty series, established no-match, unresolved inventory, unsupported source structures, and failed requests distinct. A lower-information but admitted series is not erroneous solely because optional facts are unknown. Below-admission series have an explicit unsupported outcome; the policy cannot authorise guessed conversion or an unknown-unit numeric output.

Invalid arguments and genuine internal stage-contract failures remain fatal regardless of issue policy. Do not blanket-catch FatalContractError or downgrade malformed internal output. Unsupported publisher structures belong at the established recoverable source-series boundary so unrelated successes survive. Where several series share one response, an isolated unsupported series must not discard representable siblings, while a wholly unreadable source response can identify all affected requests.

No provider-specific observation quality fields or harmonised quality score are added to observation output. Preserve existing provenance, optional receipts, and source-fidelity obligations. ANA consistency is series identity, not authorisation for a row-quality feature. Preserve native duplicate multiplicity where appropriate; never rank, average, or deduplicate across source identities, even when values agree.

## Storage, time, and receipts

Carry identity through catalogue evidence, requests, payload tags, parse output, conversion, assembly, live accumulation, compiled-store interfaces, exports, and provenance. Existing station/product-only coverage and replacement are insufficient.

Separate successful per-series interval coverage from inventory knowledge. Subset success cannot satisfy an all-series request. A recorded complete inventory and coverage of its required series may support reuse only for that scoped snapshot, not as a current-source freshness guarantee. Reuse serves its recorded vintage honestly; refresh reacquires the requested scope and updates inventory where required. Newly discovered identities do not acquire historical coverage by implication.

Refresh of one series replaces only its successfully retrieved interval and never erases siblings. Supported failures and admission/structure diagnostics must not become successful empty coverage or disappear on cache reuse. Successful empty series can establish scoped successful coverage when justified. Preserve independent successful writes and preserve existing cached observations for failed refreshes without presenting them as newly successful source responses.

Keep native values at rest and use the shared conversion path exactly once. Compiled Canada/Poland stores and live accumulation must obey the revised identity contract. Archive release vintage is not automatically a parallel hydrological variant or an obligation to acquire every historical archive release. Bulk retrieval remains explicit local-store access, not an implicit download.

Refuse incompatible old result/import/catalogue/store formats clearly before they can be misinterpreted. Old collapsed live rows cannot acquire fabricated source identity from today's catalogue. Explicit rebuild/refetch is acceptable; no dual-format compatibility or generic migration tooling is required. Preserve old files until an explicit destructive action, and never use package version alone as proof of format compatibility.

Preserve source wall-clock labels with their established zone or unknown marker, existing calendar-date versus source-timestamp clipping, and explicitly separate UTC conversion. Do not infer day support, zone, or datum. Receipts retain exact publisher bytes handed to parse when requested; cache/bulk receipts remain honestly labelled RivRetrieve-encoded store excerpts, with exact selected stored rows and source identity. Do not claim a cache excerpt reconstructs discarded publisher bytes. Source-call provenance survives without receipt retention. Exclude credentials and request headers from retained public provenance.

## Source evidence and representative proof

These observations guide implementation; they are not permission to infer all unobserved source behaviour. Inspect current code, publisher definitions, and exact bytes. Live discovery probes below were read-only and were not saved as portable fixtures. Capture their exact permitted response bytes and non-secret request provenance before changing the corresponding failing paths.

### Brazil

`tests/recordings/br_ana/daily-definitions-report.md`, retained daily recordings, and `tests/test_br_ana_public_daily.py` establish daily mean separately from Bruto/Consistido identity, including unknown exact day definition and zone, cm-to-m stage conversion, duplicates, nulls, and monthly expansion. The current suffixed physical products must no longer make generic daily-mean discovery exclude Brazil. Both daily consistency series match, with optional explicit restriction and no fallback. An unobserved variant's availability is unknown, not unavailable.

Telemetry cannot be defined as exhaustive solely because the old adapter selects adopted values. ANA's live OpenAPI at https://www.ana.gov.br/hidrowebservice/api-docs describes Detalhada/v1 and v2 as returning available raw data in addition to adopted data; Adotada returns adopted rain/level/discharge. The committed detailed recording contains 96 rows, 92 non-null sensor stages, and 20 sensor/adopted differences. Use it as a counterexample to hidden selection. Preserve adopted source identity and explicit incomplete telemetry inventory while detailed stage-channel mappings remain unestablished. Establish quantity/unit admission and independent reference/time facts for channels before enrolling them; neither infer equivalence nor hide them as nonexistent. Remaining provider work may complete definitions only if the core already represents this limitation honestly. This does not expand support to unrelated rainfall or temperature products.

### USGS

Related source problem: https://github.com/RivRetrieve/RivRetrieve/issues/281. Preserve the exact local response `.worktrees/evidence/pr255-validation/failure-response-next.json` as a portable regression fixture before changing the parser. It is 1,702,244 bytes with SHA-256 `92c43227ececed5373bc92abc4cbb19035dfc4b0ec7db736f2b4e443d8bf1275`. Exact request:

```text
https://waterservices.usgs.gov/nwis/dv/?format=json&sites=02196000&startDT=1979-12-30&endDT=2026-01-02&parameterCd=00060&statCd=00003
```

Station 02196000 has methods 126801 and 126805, 15,388 and 7,989 entries, 7,989 overlapping timestamps, and 777 numerical conflicts. The real parser still raises its exactly-one-values-object FatalContractError on these exact bytes. This must first be a failing regression through that actual path, not a mocked proxy. Do not substitute a new live response for the original capture or treat the local path as already durable repository evidence.

Native catalogue ts_id/loc_web_ds match those response methods for this station, but the builder collapses the distinction. Publisher Site Service calls ts_id an internal timeseries ID and loc_web_ds an additional measurement description; no global ts_id-to-methodID relation was established. Preserve response-owned method identity and catalogue claims without inventing their global equivalence. The capture and a later one-day response say methodIds=[ALL]; this supports their scoped request, not a perpetual completeness claim.

The publisher-linked WaterML 1.1 schema at https://his.cuahsi.org/documents/cuahsiTimeSeries_v1_1.xsd permits zero or multiple methods, optional methodID, and per-value method associations. Method ID zero is valid. Preserve explicit associations where established; ambiguous unidentified or multi-method structures need identified source limitations, not first-method selection, invented identities, or duplicated observations attributed to every method. Existing station 07374000 recordings provide singleton, daily/instantaneous, unit, zone, and clipping counterexamples; even singletons have real method IDs with empty descriptions.

### Norway

`tests/test_data/no_nve_stations_active_1.json` carries station/parameter versions and per-resolution methods. Its supported inventory has 122 multi-member keys across 34 stations and 327 nested members at 109 stations contradicting configured aggregation. These are captured inventory counts, not national failure prevalence.

`tests/test_data/no_nve_swagger.json` and https://hydapi.nve.no/UserDocumentation/ document an upstream selected version when VersionNumber is omitted. Read-only GET probes of `/api/v1/Observations` with StationId=109.42.0, Parameter=1001, ResolutionTime=1440, ReferenceTime=2024-01-01/2024-01-03 established separately retrievable VersionNumber=1,2,3. They return matching serieVersionNo, Mean, m³/s, and two 11:00Z labels: v1 has two nulls, v2 has 57.93944/74.33918, v3 has 20.30248/26.9778. Omitting version returned v2; version 99999 returned 404. Enumerate and request versions explicitly, verify returned identity, retain null series, and do not treat upstream defaults as all-series retrieval.

Facts can differ per version/resolution: catalogue station 1.46.0 parameter 1000 daily resolution has Mean v1 and Instantaneous v2. The real `no_nve_103.3.0_1003_60_2025-07-08_2025-07-14.recording.json` contains Instantaneous hourly-labelled temperature; the existing test expects the hard-coded Mean contract to fail. Correct the physical mapping with regression proof rather than renaming the mismatch a harmless variant. Resolution alone does not prove averaging or interval support.

### Switzerland

`ch_foen_parameters_2026-09-02.recording.json` establishes flow in m³/s and flow_ls in l/s. Both are discharge with established conversion; do not coalesce their identities on numerical agreement. A read-only `/apiv1/hydro/daterange` probe at https://api.existenz.ch for station 2251, parameters flow,flow_ls,height,height_abs, 2026-09-19 00:00:00 through 03:00:00, timeseriesformat=rows returned flow_ls [2.64,2.64,2.64,2.73] and height_abs [0.08,0.08,0.08,0.08], without flow or height. This demonstrates a real currently omitted discharge path.

The parameter dictionary labels height as “Pegel m ü. M.” and height_abs as “Pegel m”. Preserve the above-sea-level wording for height without inventing an exact vertical datum; height_abs does not establish a local gauge-zero reference. Field names alone cannot reverse these meanings. Distinct or unknown references must remain explicit.

Temporal meaning remains unestablished. Ten-minute publishing cadence does not establish a ten-minute mean or instantaneous support; source offerings and observed labels do not resolve the intermediary's exact mapping. Swiss admitted discharge belongs in broad discharge, not established daily mean. A latest inventory with no observed same-station field coexistence is not historical proof of no alternatives.

### Singleton and compiled counterexamples

Use real source recordings for an admitted singleton without requiring a variant choice or fabricating a label. Preserve any published ID. Canada/Poland compiled stores must retain their native physical cells and truthful store receipts while exposing the revised shared identity and conversion contract. Their archive vintage, source accounting columns, precision flags, or completeness markers are not automatically series alternatives. South Africa remains catalogue-only.

## Delivery evidence and boundaries

Delivery must exercise the public API, not only fabricated frames or isolated contract assertions. Demonstrate broad and precise filtering, both-series defaults, explicit before/after-fetch narrowing, singleton behaviour, immutable round-trips of late identities, and all three issue policies. Include admission failures with inspectable reasons, successful admitted series with unknown optional facts, empty/null/failed outcomes, and mixed representable/unsupported source responses.

Prove identity and physical facts survive conversion, unit/zone/clipping handling, exports, provenance, exact publisher receipts, and store excerpts. Prove bypass/reuse/refresh, all-versus-subset coverage, refresh without sibling erasure, newly discovered identities, diagnostics without false successful coverage, and honest inventory vintage. Cover equal/conflicting/disjoint source blocks and missing/malformed identities without using synthetic derivatives as a substitute for real end-to-end source recordings. Every bug fix starts with a failing regression through its real path; performance/path fixes instrument the actual path.

The current five-column result contract, triple-key selections, provider/product-level facts, and station/product-only accumulation require intentional revision. Relevant code is under `src/rivretrieve/_internal/`: `selection.py`, `discovery.py`, `engine.py`, `driver.py`, `conversion.py`, `observations.py`, `coverage.py`, `catalogues/{schemas,evidence}.py`, and `store/{accumulation,reader,validation,receipts}.py`. Inspect provider declarations, catalogue generators, config/fetch/parse, Canada/Poland bulk code, and current tests. Existing live accumulated stores are revision 4; compiled stores are revision 2. Existing selections rebuild metadata from packaged triple keys, conversion rebuilds five columns, and public results reject extra fields. A new parser column alone cannot satisfy this vision.

Representative provider adaptations and source research that can invalidate the shared model belong here. Mechanically adapt other registered paths as needed so the shared redesign does not silently break them or fabricate completeness. Do not use historical adapter enrolment to define away already evidenced hidden alternatives. Known incorrect mappings require a truthful correction or explicit supported-source limitation, not unchanged claims of correctness. This is not a requirement to rewrite and fully re-audit all thirteen providers here: Effort 286 owns completion of their source-specific migration and conformance, using the representative work rather than redoing it. No independent package release or change to release Program 6 is promised by this Effort.

Keep shipped software documentation truthful for changed behaviour. Effort 287 owns coherent comprehensive onboarding/reference/migration documentation. Provider narratives remain colleague-owned; do not rewrite them incidentally. Use concise reader-oriented prose, not audit transcripts or an ADR collection.

Excluded: quality ranking and new observation-quality fields, source judgement interpretation, inferred semantics, computed unpublished products, unrelated product expansion, new providers, modernised USGS API migration, South African observation activation, hosted CI, documentation hosting, ADR authoring, and release publication. Do not merge unrelated research or implementation PRs as part of vision publication.

Follow project boundaries: parse external facts where they arrive; resolve paths, credentials, environment, and resource wiring at explicit composition boundaries; use domain types where invariants or units matter, retaining library carriers for bulk data. Keep stable domain responsibilities rather than ticket-shaped architecture. Use `uv` for execution and local validation, including relevant recorded tests, `uv run ruff check`, `uv run ruff format --check`, and `uv run ty check src`; the intentional negative type fixture is not suppressed. Independent review must assess the full observable workflow and evidence, not merely schema conformance.
