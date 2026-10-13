# Provider ports

Turn a source publication into a faithful RivRetrieve integration. Use the code
requirements to guide research: the catalogue supports selection, provider code
requests and reads source data, and the shared engine performs common operations.

Start from the relevant provider issue and current repository state. Treat earlier
research and third-party adapters as leads to recheck, not authority for source
meaning or current access. Identify the intended scope and the next unresolved
step before investigating. Use the [steps below](#provider-steps-and-their-code-targets) for concrete outcomes
and code references; read the references needed for the current work.

## Progress through evidence-backed steps

1. Establish source, scope and access.
2. Establish the station catalogue and metadata.
3. Establish series identity and physical meaning.
4. Establish retrieval behavior.
5. Integrate the supported scope with the shared engine.
6. Verify the complete integration against genuine source evidence.
7. Document supported behavior and limitations for users.

These steps organize progressive research and meaningful delivery outcomes. When
planning a Program, use them as candidate Effort boundaries, adapting them to the
actual provider rather than inventing work. Do not research or implement the whole
port simply because this guide was read. Follow the user's requested scope and
existing discovery, planning and review workflows. Reading this guide does not
publish issues, contact an agency or authorize implementation.

Research thoroughly enough to defend each adopted claim. Recheck documentation,
representative responses and relevant exceptions. Validate apparent inconsistencies
before escalating them. Later findings can reopen an earlier conclusion. Evidence
retention, tests and documentation develop throughout, not only in the final steps.

## Keep one continuing research record

Use the private [verification-evidence repository](https://github.com/RivRetrieve/verification-evidence)
for the provider's continuing research document and evidence. Find an existing
record before creating another. Keep established findings, dated checks, supporting
references, corrections, correspondence and open questions together across Efforts.
For each material unknown, explain which implementation or user claim it affects.

Use the archive's existing intake and verification process for original material.
The research document connects evidence; it does not replace original responses or
certify a claim by recording it. Public issues carry safe summaries and handoffs.
Keep private material and correspondence out of public code, issues and artifacts.
Private storage does not establish permission to retain or disclose source material.

## Resolve or expose missing information

Investigate material gaps and prepare focused questions for the institution. Record
what was checked, what was asked and any answer. Obtain authorization before sending
correspondence. Do not treat silence as confirmation or require an answer to every
question before any independent capability can proceed.

- Proceed when required facts are established.
- Preserve unknown facts when the engine can represent them honestly.
- Pause an affected capability when proceeding would require guessing, such as
  assigning an unestablished quantity or unit, or claiming incomplete data is complete.
- Distinguish a missing source fact from a limitation in the shared engine.

When investigation and correspondence cannot resolve a material blocker, present
its consequences to the maintainer. The maintainer decides whether to narrow the
scope, deliver a truthful limited capability, defer it or abandon it. Documentation
cannot make an unsafe interpretation acceptable.

## Finish with a defensible result

Account for the supported scope, evidence behind material claims, completed checks
and remaining limitations. Use the existing [testing guide](testing.md)
and [evidence guide](evidence.md), not a new verification
system. Missing mandatory evidence blocks acceptance; it is not a passing check.
Keep user documentation consistent with the delivered behavior. Stop at the requested
handoff or review boundary.

## Provider steps and their code targets

Paths below lead to the shared contracts and representative implementations. Inspect
current code before copying a pattern. A working adapter is not evidence that its
source interpretations apply to another publication.

### 1. Source, scope and access

**Build toward:** a provider declaration with the appropriate access kind,
credentials and publication identity.

Establish who measures and publishes the data, relevant products and geographical
scope, available routes, access conditions, terms and attribution. Obtain small
genuine examples of metadata and observations. Distinguish unavailable access from
an empty response and from evidence that has not yet been collected.

[`ProviderDeclaration`](../../src/rivretrieve/_internal/providers/registration.py)
selects `LiveStages` for on-demand acquisition, `BulkStore` for explicit download
and compilation, or `CatalogueOnly` for discovery without observation retrieval.
“Live” includes historical service requests; it does not mean only current readings.

**Outcome:** a justified source and integration scope, with access and terms questions
recorded. Reachability alone does not establish permission or physical meaning.

### 2. Station catalogue and metadata

**Build toward:** a reproducible catalogue builder and approved packaged artifacts
that support offline discovery.

Establish station identifiers and their connection to observations, coordinates and
reference systems, supported descriptive metadata and station-product associations.
Check whether a field describes a station, sensor or series. Do not infer observation
availability from a station listing or turn unknown coverage into a promise.

Use the [catalogue schemas](../../src/rivretrieve/_internal/catalogues/schemas.py)
and [publication path](../../src/rivretrieve/_internal/catalogues/publication.py).
The [Lithuania builder](../../src/rivretrieve/_internal/providers/lt_lhmt/generate_catalogue.py)
illustrates provider, product, station and station-product tables. Descriptive station
metadata and its supporting evidence are also published through the shared path.

**Outcome:** supported field mappings, catalogue coverage limits and original inputs
needed to reproduce and verify the build. Missing optional metadata need not block
retrieval; an unresolved station-to-observation relationship can.

### 3. Series identity and physical meaning

**Build toward:** definitions that connect source fields and published identities to
RivRetrieve's physical facts without collapsing separate records.

Establish quantities, native units, distinct series, frequency, statistic, time
information, vertical references, missing-value encodings and source statuses.
Look for parallel series and real exceptions to proposed mappings. Do not interpret
quality codes as a ranking or infer a daily mean from cadence or a field name alone.

[`SourceIdentity`, `PhysicalFacts` and admission](../../src/rivretrieve/_internal/source_series.py)
keep identity and physical interpretation separate.
[`SeriesMapping`](../../src/rivretrieve/_internal/provider_series.py)
can share supported mappings between catalogue publication and parsing; it is not
a substitute for response-specific identities when the source requires them.

**Outcome:** each adopted fact has supporting evidence, and remaining unknowns are
explicit. Admission requires established quantity, source unit and valid conversion.
Unknown time zone, temporal support or datum need not prohibit retrieval, but cannot
satisfy filters or claims requiring those facts.

### 4. Retrieval behavior

**Build toward:** request rules and source acquisition that do not silently lose data.

Establish selectors, date boundaries, pagination, response caps, request limits,
empty-response meanings, errors, rolling retention and revisions. Check that a
successful response actually supports the claimed coverage. Preserve differences
between published nulls, absent rows, empty answers and failed requests.

Providers declare windows through [engine types](../../src/rivretrieve/_internal/engine.py).
The [shared planner](../../src/rivretrieve/_internal/window_planning.py)
prepares bounds; providers consume those bounds without shifting them.
[Provider stages](../../src/rivretrieve/_internal/driver.py) exchange bytes,
source-call origins, rows, identities, inventories, outcomes and issues.
The [Lithuania fetcher](../../src/rivretrieve/_internal/providers/lt_lhmt/fetch.py)
is a concrete example, not a universal source policy.

**Outcome:** a defensible acquisition contract, including failure and completeness
limits. Identify necessary shared-engine changes rather than hiding them in source code.

### 5. Provider integration

**Build toward:** the agreed scope working through the public discovery and retrieval APIs.

Connect catalogue artifacts, configuration, request declarations, fetch/parse stages
or bulk download/compile operations, and the provider declaration. Start with a
representative end-to-end path and extend to the agreed products and real source
differences. Develop focused tests alongside implementation. Return to research when
code would otherwise encode an unsupported assumption.

The [declaration example](../../src/rivretrieve/_internal/providers/lt_lhmt/declaration.py)
and [manifest](../../src/rivretrieve/_internal/provider_manifest.py) show
registration. The [parser example](../../src/rivretrieve/_internal/providers/lt_lhmt/parse.py)
shows native parsing connected to source-series mappings.
[Canada's declaration](../../src/rivretrieve/_internal/providers/ca_eccc/declaration.py)
shows the bulk alternative. Reuse shared conversion, clipping, assembly and storage.

**Outcome:** working provider behavior, including supported source failures alongside
independent successful results. Registration alone is not a completed provider.

### 6. Verification

**Build toward:** evidence that both the code behavior and the adopted source meanings
are correct within the stated scope.

Extend shared contracts and the [all-provider catalogue rebuild](../../tests/test_catalogue_origin_certification.py).
Use genuine retained responses for distinct supported routes and independently
established expected results. Check identities, timestamps and values together.
Verify relevant cache/store behavior, catalogue lineage and distribution contents.

Follow the [testing](testing.md) and
[evidence](evidence.md) guides. The private archive
owns intake, retained inputs and source-certification tooling. Review exact code
revisions before execution with private evidence. Synthetic tests, replay, derived
rebuilds and live checks establish different things; none silently replaces another.

**Outcome:** an account of completed checks, exact supporting evidence and remaining
limits. Missing mandatory genuine inputs block acceptance.

### 7. User documentation

**Build toward:** a provider page that explains the delivered capability with a
verified practical example.

Explain who publishes the data, what users can retrieve, access requirements, source
series distinctions, time and units, availability limits, terms and unresolved facts
that affect interpretation. State consequences clearly rather than publishing the
whole investigation. Keep detailed research and correspondence in the private record.

Follow [documentation guidance](../AGENTS.md) and use existing
[provider pages](../providers/) for scope. Link general usage rather
than repeat it. Do not present a successful example as proof of continuous coverage.

**Outcome:** users can understand the result and its limits without reconstructing
the investigation. Documentation and implemented behavior agree.
