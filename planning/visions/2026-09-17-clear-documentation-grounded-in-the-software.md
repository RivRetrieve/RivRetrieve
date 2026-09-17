# Clear documentation grounded in the software

Program: https://github.com/RivRetrieve/RivRetrieve/issues/6
Effort: https://github.com/RivRetrieve/RivRetrieve/issues/18

## Outcome

Write a coherent bundle of Markdown documentation for the current RivRetrieve software.
The immediate purpose is to let Nicolas review the structure, substance, and writing.
Readers should understand how to retrieve data, what the returned information means,
and why the software has its present architecture.

Do not build or host a documentation website in this Effort. Read the Docs is a possible
later destination, not a current deliverable. Do not choose or configure a site toolchain
merely to begin writing. Markdown pages must remain readable through repository links.

This scope supersedes the ticket's older hosting, eleven-provider snapshot, and
Nicolas-authored Norway onboarding requirements. Document the current supported surface,
not the historical release snapshot. This vision does not amend the Program's release
conditions or establish that its documentation-site condition has been satisfied.
Hosting remains deferred work, not a delivered outcome.

## Step 1: explore the code deeply

Before drafting documentation, inspect the current implementation, its tests, and accepted
architecture decisions. Do not treat the earlier interview investigation as sufficient.
Trace the public API through the real execution paths and establish which behaviours the
software actually provides. Use the project's uv environment for commands and checks.

The investigation must cover:

- Public exports, discovery, immutable selections, retrieval, and returned domain types.
- Catalogue identity, products, availability, evidence, and the limits of packaged snapshots.
- Engine and provider responsibilities across fetch, parse, convert, and assemble.
- Live, cached, and bulk retrieval paths, including download consent and credential handling.
- Units, source-native time, wall-clock request windows, and explicit unknown states.
- Issues, severity, caller policy, source-failure isolation, and fatal contract errors.
- Provenance, receipts, storage, and the evidence used to test these contracts.

Compare code with tests and documentation. Preserve disagreements for investigation rather
than copying an old assertion or treating current output as its own proof. Give Nicolas a
concise account of the findings and resulting page outline before writing the full set.
Keep investigation evidence in the normal Effort and review records, not a new tracking system.

Useful starting points include `src/rivretrieve/__init__.py`, `_internal/discovery.py`,
`_internal/driver.py`, `_internal/issues.py`, the provider declarations and tests,
`CONTEXT.md`, and `docs/adr/`. Resolve paths relative to the package where abbreviated.
`docs/design/provider-redesign-review.md` records important reasoning, especially the
access promise and harmonisation boundary, but contains superseded designs and APIs.
It is not a specification of the current package.

## Design philosophy

RivRetrieve provides a common interface for accessing river-gauge data. Its API should be
simple and intuitive while handling source-specific access and formats. Users should not
need a separate retrieval workflow for each agency.

RivRetrieve harmonises access and established physical representations. It does not analyse
observations, interpret source quality codes, or judge data quality or suitability for a
study. Those judgements belong to users. Unit conversion does not authorise computing a
hydrological product the source never published. Consistent columns and units do not
establish scientific comparability between series.

A transformation requires established source information. Unknown time zones, day
definitions, or other source facts must not become plausible assumptions. Explain what
can be established and what remains unknown without claiming that all absent information
has the same cause. Current catalogue evidence distinguishes source silence from gaps in
RivRetrieve's acquisition evidence.

Failures must remain visible. Explain the existing distinction between issue severity and
caller-selected handling rather than proposing a new failure policy. At discovery time,
issues carry `info`, `warning`, or `error`. `info` does not activate the caller policy.
Both retrieval functions default to `on_issue="warn"`, which emits warnings for warning
and error issues while returning results. `"raise"` raises `IssuePolicyError` for those
issues. `"ignore"` suppresses notifications, not the issues retained in a returned result.
Fatal contract errors raise independently of that policy. Verify these details in Step 1.
Do not describe an error severity as necessarily fatal or imply that missing data and a
failed request are equivalent.

Traceability means identifying the source and documenting the transformations applied.
It does not certify scientific quality. Explain provenance and optional receipts in terms
of the questions a user can answer with them, including the distinction between a
publisher payload and an excerpt authored from RivRetrieve's store.

The shared engine is an architectural consequence of these responsibilities. Explain
which behaviour is common and which depends on the source. Do not present generic
simplicity slogans as an independent philosophy or promise that every provider has an
identical execution path.

## Documentation structure

Use the following reader needs as the starting skeleton. Refine page boundaries after
code exploration without turning reversible file-layout choices into new scope decisions.

- Getting started: installation and a working first retrieval through the shipped API.
- Usage: discovery, selection, retrieval, returned data, issues, provenance, receipts,
  request windows, credentials, bulk consent, cache reuse and refresh, and optional mapping.
- Examples: one recent-streamflow retrieval example motivated by CAMELS-US.
- API reference: the current public functions and the types needed to understand their
  inputs and outputs. Use NumPy-style docstrings as the reference source. Repair missing
  or misleading public docstrings when needed, without changing runtime behaviour.
- Architecture: purpose and boundaries, design philosophy, a system overview, a traced
  request, data contracts, storage and reuse, and how those contracts are verified.
- Providers: a section skeleton for the colleague's descriptions, with a capability
  reference derived from shipped declarations or catalogue facts rather than manual claims.

The architecture should support a short first reading and deeper investigation. Explain
responsibilities before listing files. Use a concrete request to connect the API, catalogue,
engine, provider, and result. Explain how held observations and bulk stores differ from
live fetch and parse. Link accepted ADRs for detailed rationale rather than making the
historical decision log the main reading path. A diagram is useful only if it clarifies
relationships more directly than prose.

Nicolas owns the software-engineering documentation, architecture, API description, and
example. His colleague owns provider background, coverage, variables, time spans, and
instructions for obtaining credentials. Provide space and a consistent outline for those
pages, but do not author that colleague's full survey or make it block this draft.
Shared software guidance must still explain how supplied credentials are used safely.

Participation means suggesting potential providers and supplying source links or relevant
information. Nicolas intends to write the code. Do not invite code contributions or write
a provider-implementation tutorial, pull-request onboarding guide, or contributor workflow.
Architecture documentation is explanatory, not an invitation to implement adapters.

## The streamflow example

Motivate the example with a reader who wants to extend CAMELS-US to more recent years.
Show how RivRetrieve retrieves recent daily streamflow for a small selection of CAMELS-US
gauges. The result is a starting point for that exercise, not an extended CAMELS dataset.
Use a clearly stated request window reaching recent years such as 2025 or an explicitly
bounded part of 2026. Do not prescribe 2014 as the original dataset's final date or claim
that every gauge has a continuous record from 1980 through the example's endpoint.

The paper by Newman et al. (2015), DOI `10.5194/hess-19-209-2015`, describes 671 basins and
USGS daily streamflow for 1980–2010 in section 2.2. Its historical period must not be
confused with the endpoint of a later CAMELS-US release. The provided paper was read during
discovery. Verify source facts and gauge membership when writing the example.

The current candidate workflow is `find`, `pick`, and `fetch` with the USGS
`discharge_daily_mean` product. Preserve station identifiers as strings, including leading
zeros. Daily streamflow is source-published, not calculated from sub-daily observations.
Explain that RivRetrieve returns discharge in m³/s and uses native calendar dates with
explicit zone information, which can be unknown. Missing observations and source failures
must not be represented as a successful complete series.

Keep the example short and focused on obtaining and inspecting observations. Do not add
CAMELS archive ingestion, merging, a full-basin harvesting pipeline, basin-area conversion
to mm/day, quality-flag reconstruction, infilling, event detection, model training, forcing
extension, or a CAMELS-compatible exporter. Do not publish a derived observation dataset.
No notebooks are required or included.

## Writing requirements

Apply Nicolas's writing rules from
`/Users/nicolaslazaro/Desktop/grant-proposal-nik/agents.md`, adapted to software documentation.
The relevant rules are reproduced here so this vision remains usable without that file.
Do not import its grant structure, page limits, LaTeX citation machinery, or proposal-specific
first-person roles.

Write in active voice unless the actor is unknown or irrelevant. Prefer short sentences,
usually 25 words or fewer, but retain qualifications needed for precision. Give each
sentence one main claim and each paragraph one topic, with no more than six sentences.
Keep subjects, verbs, and logical relations explicit. Use verbs instead of nouns that hide
actions. Avoid long noun clusters.

Use no semicolons or em dashes in reader-facing prose. Remove unsupported praise,
intensifiers, generic transitions, and promotional language. Start with substance rather
than announcing a section's purpose. Do not preview, state, and then repeat the same claim.
Avoid staged contrasts, slogan-like headings, empty synthesis, rhetorical questions,
and mechanically symmetrical paragraphs. Use a contrast only when the distinction matters.

Every sentence must add a claim, evidence, reason, definition, example, qualification,
consequence, or necessary connection. Preserve uncertainty and scope. Do not turn a
conditional capability into a guarantee. Use the established terminology in `CONTEXT.md`,
checking it against current accepted contracts where historical wording has drifted.
Do not rotate technical synonyms to vary the prose.

Give each claim one primary home and link to it elsewhere. Use lists for actual finite sets
or ordered actions, tables for comparisons, and diagrams for relationships. Keep explanatory
reasoning in connected prose. Attribute design ownership only when it matters, and do not
invent first-person claims on Nicolas's behalf. Prefer the package or its functions as
subjects when describing behaviour. Verify cited sources and use ordinary documentation
links and citations rather than requiring a grant-specific bibliography system.

## Evidence of completion

The Markdown bundle has a navigable index and substantive software pages, not only empty
headings. Provider narrative placeholders are the explicit exception. Nicolas can review
the outline and representative writing before the full draft is completed. Incorporate
his feedback on clarity and voice rather than declaring prose acceptable solely because
it passed automated checks.

The README quickstart uses the current API. Remove obsolete calls such as `stations()`,
`provider()`, and `map_stations()`, and the stale claim that Swiss retrieval is unavailable.
The optional mapping dependency is explicit. Do not freeze the public reference at the ten
names in the older Effort comment. Discovery found additional public functions including
`download`, `describe`, `cache_status`, and `clear_cache`.

Check documented signatures, defaults, examples, links, and capability claims against the
explored revision. Exercise the examples through the public package interface. Use existing
source recordings where suitable for repeatable checks and distinguish them from any live
source check. Do not invent observation payloads or infer complete coverage from a passing
small request. Documentation validation must not require credentials or large downloads
merely to read or render the Markdown. No hosted-site build is an acceptance condition.

Preserve relevant limitations from the Effort comments and current evidence, including
France, Bosnia, and Thailand coverage accounting. Inventory accounting is not a claim of
countrywide completeness or continuous history. Existing provider notes can also be stale.
Do not rewrite all historical reports or erase the reasoning in older design documents.

This work changes documentation and, where needed, documentation-bearing docstrings.
It does not author new retrieval behaviour, add providers, redesign error handling, or
reopen completed architecture decisions. Report a discovered code defect separately
rather than expanding a documentation task into an unapproved software change.
