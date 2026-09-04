# Thirteen providers test the engine

Program: https://github.com/RivRetrieve/RivRetrieve/issues/6
Effort: https://github.com/RivRetrieve/RivRetrieve/issues/17

## Purpose

RivRetrieve promises faithful, traceable access through one consistent shape across every provider. The shared engine exists to place objectively common behavior in one central implementation, leaving each provider to state only what is true about its source.

This Effort tests that design against every existing source whose evidence can be recorded from the implementing environment: the eleven publicly routable sources plus Norway, whose authenticated adapter is complete and proven while its catalogue stays withheld by #90. South Africa and Brazil are deferred to Efforts #212 and #213 because their only blocker is external access (a network that DWS accepts, and ANA credentials), not engine friction; the draft adapter for South Africa in PR #210 belongs to #212. It is both delivery work and a falsification test. Repeated provider code is evidence that behavior belongs in the engine. A source that cannot cross the existing stage boundaries without losing information, duplicating engine behavior, or adding a provider-specific escape hatch is evidence that the engine is incomplete or its contract is too narrow. Such friction must cause the shared design to be reconsidered, not be hidden in a local workaround.

Centralization does not mean eliminating irreducible source behavior. Providers still own how their source is called, how its response is decoded, and the source facts declared for each product. The engine owns behavior that is the same in meaning across sources.

## Destination

Twelve of the thirteen existing sources have observation adapters represented and proven through the engine-owned provider kind that matches the source, and the thirteenth (South Africa) has its adapter written and reviewed but unevidenced under #212:

- a live HTTP provider contributes `fetch.py`, `parse.py`, and `config.py`;
- a bulk provider contributes `bulk.py` and `config.py`;
- `convert` and `assemble` have no provider implementation;
- catalogue generation, origin declarations, registration declarations, and packaged catalogue artifacts remain separate from the observation-adapter file rule; this Effort nevertheless owns the minimum certification needed to make the Bosnia, France, and Thailand adapters selectable.

The result is not twelve superficially similar pipelines. It is one pipeline whose source-facing edges are implemented once per source only where the sources genuinely differ.

Recording is a repeatable maintainer procedure, not a one-time campaign: an engine-owned composition root drives any live provider through the shared transport, applies caller-supplied credentials at the transport boundary, and writes secret-free recordings, with an explicit opt-in for documented non-2xx source answers and a distinct non-evidence name for every failed exchange.

## Starting point

The authoritative manifest names thirteen providers. On the confirmed starting revision:

- `usgs_nwis` is the only `LiveStages` provider and is the existing proof of the live `fetch` / `parse` / `config` shape;
- `ca_eccc` and `pl_imgw` are delivered `BulkStore` providers and remain on their distinct `bulk` / `config` shape;
- the other ten providers are registered as `CatalogueOnly`;
- five of those ten already have selectable certified packaged station-product facts and can become publicly routable when their live stages land;
- `ba_fhmzbih`, `fr_hubeau`, and `th_thaiwater` have source-backed catalogue material but still need the minimum native/origin/generator/canonical-artifact certification required for public selection; this Effort owns that work only for the products established by their observation-adapter evidence;
- `br_ana` and `no_nve` deliberately expose empty certified catalogues until Effort #90 establishes their credentialed native acquisition and origins;
- only one real HTTP boundary recording and probe exists, for one USGS instantaneous-discharge product;
- active runtime code contains no provider `transform.py` and no provider-owned date-range filter, but ten retired provider trees preserve the old multi-file pipelines as non-runtime evidence.

The original ticket's counts for duplicated transforms and date filters describe an earlier tree. Success is measured against the current architecture: duplication must not return to runtime code, and each retired tree is removed only after its replacement is proven.

## The engine boundary

The engine continues to own:

- the fetch → parse → convert → assemble order and the types at every boundary;
- request-window meaning, outward padding, decomposition vocabulary, rendering orchestration, and final clipping;
- transport and retry policy;
- canonical unit conversion;
- schema and contract enforcement;
- result ordering and assembly;
- provenance, structured issues, and receipts.

A live provider may own only irreducible source behavior:

- endpoint and request construction;
- the sequence or coalescing of source calls;
- applying credentials supplied through an engine-owned boundary;
- decoding source bytes into the shared row contract;
- typed source coordinates, native units, time semantics, and documented source issue conditions.

A bulk provider remains a source-specific download and compilation adapter behind the shared consent, store, conversion, receipt, and result machinery. Canada and Poland are regression dependencies, not candidates to be forced through the live three-file contract.

No provider may perform its own timezone arithmetic, unit conversion, requested-window clipping, generic retry loop, result assembly, or other engine behavior. No comparison against a literal provider identifier may escape that provider's directory. No provider reads environment variables, resolves user configuration, or hides mutable credential state below the composition root.

## Friction is evidence

The existing ports already identify likely pressure on the contracts:

- Brazil, Norway, and the Swiss query service require authentication flows or tokens without allowing secrets into recordings or receipts.
- Japan uses a chained discovery request followed by a data request, and both calls must remain traceable even though only the latter yields rows.
- Switzerland sends a source query rather than an ordinary parameterized GET.
- South Africa can return several requested products in one source response and must not duplicate identical calls.
- Bosnia exposes a source-fixed rolling workbook rather than a requested range.
- France mixes API families and has a limited real-time horizon.
- Japan, Norway, Czechia, Lithuania, South Africa, and other sources use different product-dependent request decompositions already covered in part by the shared planner.
- Poland's bulk acquisition has a known multi-year orchestration pressure point.

These are not advance permission for special cases. For each pressure point, the implementation must first attempt to express the source faithfully through the current contracts. If that cannot be done, the implementation stops at an inspectable failing example. The response is one shared engine capability, an explicit engine-owned provider kind when the semantics are genuinely different, or an evidence-backed revision of the contract. The response is never duplicated private machinery or silent loss of provenance.

A new source pattern earns a shared abstraction only when its semantics are understood. The Effort does not centralize code merely because two functions look similar, and it does not turn source-specific parsing into a configuration language with escape hatches.

## Correctness evidence

A retired implementation is historical evidence, not an oracle. Every active adapter is established from current source behavior and must preserve the Program's existing contracts.

Observation evidence must satisfy all of the following:

- A fixture used as source evidence records a real source interaction with the exact non-secret request, exact response bytes, and UTC retrieval instant.
- Replay resolves that exact request through `ReplayTransport`; an unconditional fake response cannot prove a port.
- Credentials and secret-bearing headers never enter committed recordings, receipts, logs, or provenance.
- Every declared observation product has an independently authored three-literal boundary proof over recorded source evidence at the source-facing boundary appropriate to its provider kind.
- The coverage obligation includes all six existing USGS products rather than accepting the current single probe as complete.
- Store-backed products receive equivalent boundary evidence, including the unpaid Poland/Warsaw case.
- Request rendering, stop conventions, source-fixed horizons, chained calls, coalesced calls, nulls, sentinels, timestamp labels, native units, and source issue conditions are checked against source facts rather than retired output.
- Unknown time zones and day definitions remain `unknown`. They are never inferred from country, coordinates, or legacy behavior.
- A source that cannot provide the evidence needed for a claimed product delays that claim; it does not receive a weaker test exception.

The previously unpaid `to_utc` path for `ch_foen` becomes executable when its observation adapter lands: rows whose zone remains `unknown` must still be refused atomically and identify the provider and affected-row count.

All existing bulk-store guarantees remain intact, including atomic publication and rollback, source-schema closure, retained native fields, sentinel states, disk consent, and store-excerpt receipt authorship.

## Norway, Brazil and South Africa

This Effort owns the authenticated observation adapter and source-backed conformance evidence for `no_nve`. Brazil (`br_ana`) is deferred to #213: no ANA credentials were available to the implementing environment and ADR 0024 forbids authoring payloads, so its adapter is not claimed here. South Africa (`za_dws`) is deferred to #212: the DWS host refused every request from the implementing network with HTTP 403 regardless of User-Agent or IP family, so its complete, independently reviewed adapter in draft PR #210 waits for recordings from an accepting network. Their retired legacy subtrees remain until those Efforts prove the replacements. This Effort does not absorb adjacent work:

- #90 owns their credentialed native catalogue acquisition, origins, and restoration of routable packaged station-product facts;
- #15 owns the public experience for loading credentials and reporting missing credentials;
- #92 owns general live-station querying.

The Norway adapter is therefore complete and proven while the provider remains unavailable through public catalogue selection. Its tests exercise the real source-facing stage behavior using credentials supplied outside committed evidence. Its provider code does not read `.env` or environment variables; only the maintainer recording entry point does, at the composition root.

This exception does not extend to Bosnia, France, or Thailand. This Effort must make each of those providers publicly selectable for every observation product established by current source evidence. It must not invent speculative cross-products or availability facts to fill a catalogue matrix. A product whose present evidence cannot establish the required native, origin, station, or station-product fact remains unclaimed until that evidence exists.

This intermediate Norway state is acceptable because the repository remains private until the Program closes. The Program, not #17 in isolation, proves the final end-to-end public path after #15, #90, #212 and #213 land.

## Faithfulness and scope boundaries

The following settled Program decisions remain unchanged:

- RivRetrieve exposes only products the source publishes; it never aggregates or recreates a product.
- The returned data shape, provenance, issues, receipts, and public selection model do not vary by provider.
- Quality codes, station identity, river naming, licences, record bounds, time zones, day definitions, and stage datums are not interpreted or inferred.
- A wall-clock request is closed at both ends; providers do not reinterpret it.
- Catalogue certification and canonical catalogue generation remain governed by the packaged catalogue rules in `AGENTS.md`; the Bosnia, France, and Thailand scope adds no fixture-backed or live canonical-generation exception.
- Provider discovery remains the explicit thirteen-line manifest with one declaration per provider directory. Filesystem discovery and provider import side effects do not return.
- Credential acquisition, general live-station querying (#92), general failure policy, caching, documentation-site construction, speculative cross-products, and providers beyond the existing thirteen are outside this Effort except where their already-settled contracts constrain a port.

## Attribution and retired code

The established `Contributed by:` documentation field is restored for every provider adapter using repository history rather than guesswork. The recorded introduction history attributes twelve provider contributions to Thiago von Däniken and `ch_foen` to Nicolas Lazaro. Attribution is documentation, not code ownership, and must not distort the provider layout.

After a provider's replacement passes its source-backed evidence, its corresponding `reference/legacy_observations/<provider>` subtree is deleted. No retired provider code is imported, executed, or retained as a baseline. The archive is removed provider by provider so historical evidence is not destroyed before the replacement is established.

## Acceptance evidence

The Effort is complete when the repository demonstrates all of the following:

1. Twelve of the thirteen manifest providers have an observation adapter appropriate to `LiveStages` or `BulkStore`; only Norway may remain unroutable, and only because #90 still withholds its certified catalogue facts. South Africa's adapter exists as reviewed draft PR #210 under #212, and Brazil is owned by #213.
2. Every other newly routable live provider, including Bosnia, France, and Thailand, is publicly selectable for its source-established observation products, passes through the same public engine path, and returns the fixed canonical result contract.
3. The Bosnia, France, and Thailand native tables, origins, generators, and canonical artifacts satisfy the packaged catalogue rules in `AGENTS.md`; unsupported products and cross-products remain absent rather than inferred.
4. Every declared product satisfies the real-recording and boundary-evidence obligations, including existing USGS and bulk products.
5. Active provider code contains no reintroduced transform layer, provider-owned clipping, unit conversion, generic retries, result assembly, hidden configuration reads, or provider-ID branches outside provider directories.
6. Chained, coalesced, authenticated, query-based, source-fixed-window, capped-window, and bulk behaviors retain complete provenance without leaking secrets.
7. Repeated port friction has either disappeared into one justified shared engine capability or remains as an explicit contract failure that prevents the affected claim from landing. No local workaround masks it.
8. Canada and Poland retain all delivered bulk-store guarantees while gaining complete boundary coverage.
9. Each proven replacement removes its retired legacy subtree and carries evidence-derived `Contributed by:` attribution.
10. The complete network-free test, formatting, lint, and type-check gates pass, and source-interaction evidence can be replayed from a fresh clone without live network access.

## Findings recorded at delivery

- ADR 0024's consequence that "South Africa's 403 is a User-Agent header" is falsified: browser, Chrome, python-requests and RivRetrieve User-Agents over IPv4 and IPv6 all received the same Apache 403 body on 2026-09-03. The ADR carries a dated note; no per-provider User-Agent escape hatch exists.
- A source that publishes a per-series method contradicting the product's declared statistic (NVE station 103.3.0 publishes hourly water temperature as `Instantaneous`) fails the whole result with a contract error rather than returning the other products with an issue. That is deliberate: per-station product unavailability belongs to the certified catalogue that #90 owns, not to a provider-local isolation point.
- NVE's documentation states daily values are computed on "Norwegian normal time" and writes it as UTC-1, contradicting CET. The day definition stays `unknown` with the published `11:00Z` label; the contradiction is quoted verbatim in the port notes.
- The bare-date public request shape and the inclusive stop convention were established by recordings, not assumed: HydAPI accepts an end rendered with microseconds, and a date-only end truncates to midnight and drops that day's `11:00Z` value.
- The live `fetch` grouping, 404, retry-exhausted and origin shape is now repeated near-verbatim across several providers. That is friction evidence for a future shared engine capability to be judged at Program level; it was not centralised here because the semantics were not yet shown to be identical.

Passing these criteria answers the Effort's question for the recordable sources. The engine supports the thirteen sources only if the providers remain small because shared logic truly has one home, not because duplicated behavior has been renamed or concealed.
