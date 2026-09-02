# Thirteen providers test the engine

Program: https://github.com/RivRetrieve/RivRetrieve/issues/6
Effort: https://github.com/RivRetrieve/RivRetrieve/issues/17

## Purpose

RivRetrieve promises faithful, traceable access through one consistent shape across every provider. The shared engine exists to place objectively common behavior in one central implementation, leaving each provider to state only what is true about its source.

This Effort tests that design against all thirteen existing sources. It is both delivery work and a falsification test. Repeated provider code is evidence that behavior belongs in the engine. A source that cannot cross the existing stage boundaries without losing information, duplicating engine behavior, or adding a provider-specific escape hatch is evidence that the engine is incomplete or its contract is too narrow. Such friction must cause the shared design to be reconsidered, not be hidden in a local workaround.

Centralization does not mean eliminating irreducible source behavior. Providers still own how their source is called, how its response is decoded, and the source facts declared for each product. The engine owns behavior that is the same in meaning across sources.

## Destination

All thirteen existing sources have observation adapters represented and proven through the engine-owned provider kind that matches the source:

- a live HTTP provider contributes `fetch.py`, `parse.py`, and `config.py`;
- a bulk provider contributes `bulk.py` and `config.py`;
- `convert` and `assemble` have no provider implementation;
- catalogue generation, origin declarations, registration declarations, and packaged catalogue artifacts remain separate concerns and do not count against the observation-adapter file rule.

The result is not thirteen superficially similar pipelines. It is one pipeline whose source-facing edges are implemented thirteen times only where the sources genuinely differ.

## Starting point

The authoritative manifest names thirteen providers. On the confirmed starting revision:

- `usgs_nwis` is the only `LiveStages` provider and is the existing proof of the live `fetch` / `parse` / `config` shape;
- `ca_eccc` and `pl_imgw` are delivered `BulkStore` providers and remain on their distinct `bulk` / `config` shape;
- the other ten providers are registered as `CatalogueOnly`;
- eight of those ten have certified packaged products and can become publicly routable when their live stages land;
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

## Brazil and Norway

This Effort owns authenticated observation adapters and source-backed conformance evidence for `br_ana` and `no_nve`. It does not absorb either adjacent Effort:

- #90 owns certified native catalogue acquisition, origins, and restoring routable packaged station-product facts;
- #15 owns the public experience for loading credentials and reporting missing credentials.

The adapters may therefore be complete and proven while those two providers remain unavailable through public catalogue selection. Their tests must exercise the real source-facing stage behavior using credentials supplied outside committed evidence. Their provider code must not read `.env` or environment variables directly.

This intermediate state is acceptable because the repository remains private until the Program closes. The Program, not #17 in isolation, proves the final end-to-end public path after #15 and #90 land.

## Faithfulness and scope boundaries

The following settled Program decisions remain unchanged:

- RivRetrieve exposes only products the source publishes; it never aggregates or recreates a product.
- The returned data shape, provenance, issues, receipts, and public selection model do not vary by provider.
- Quality codes, station identity, river naming, licences, record bounds, time zones, day definitions, and stage datums are not interpreted or inferred.
- A wall-clock request is closed at both ends; providers do not reinterpret it.
- Catalogue certification and canonical catalogue generation remain governed by the repository's native-table and origin rules.
- Provider discovery remains the explicit thirteen-line manifest with one declaration per provider directory. Filesystem discovery and provider import side effects do not return.
- Credential acquisition, general failure policy, caching, documentation-site construction, and providers beyond the existing thirteen are outside this Effort except where their already-settled contracts constrain a port.

## Attribution and retired code

The established `Contributed by:` documentation field is restored for every provider adapter using repository history rather than guesswork. The recorded introduction history attributes twelve provider contributions to Thiago von Däniken and `ch_foen` to Nicolas Lazaro. Attribution is documentation, not code ownership, and must not distort the provider layout.

After a provider's replacement passes its source-backed evidence, its corresponding `reference/legacy_observations/<provider>` subtree is deleted. No retired provider code is imported, executed, or retained as a baseline. The archive is removed provider by provider so historical evidence is not destroyed before the replacement is established.

## Acceptance evidence

The Effort is complete when the repository demonstrates all of the following:

1. Every one of the thirteen manifest providers has an observation adapter appropriate to `LiveStages` or `BulkStore`; Brazil and Norway may remain unroutable only because their certified catalogue facts are intentionally withheld by #90.
2. Every newly routable live provider passes through the same public engine path and returns the fixed canonical result contract.
3. Every declared product satisfies the real-recording and boundary-evidence obligations, including existing USGS and bulk products.
4. Active provider code contains no reintroduced transform layer, provider-owned clipping, unit conversion, generic retries, result assembly, hidden configuration reads, or provider-ID branches outside provider directories.
5. Chained, coalesced, authenticated, query-based, source-fixed-window, capped-window, and bulk behaviors retain complete provenance without leaking secrets.
6. Repeated port friction has either disappeared into one justified shared engine capability or remains as an explicit contract failure that prevents the affected claim from landing. No local workaround masks it.
7. Canada and Poland retain all delivered bulk-store guarantees while gaining complete boundary coverage.
8. Each proven replacement removes its retired legacy subtree and carries evidence-derived `Contributed by:` attribution.
9. The complete network-free test, formatting, lint, and type-check gates pass, and source-interaction evidence can be replayed from a fresh clone without live network access.

Passing these criteria answers the Effort's question. The engine supports the thirteen sources only if the providers remain small because shared logic truly has one home, not because duplicated behavior has been renamed or concealed.
