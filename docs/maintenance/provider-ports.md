# Provider ports

Turn a source publication into a faithful RivRetrieve integration. Use the code
requirements to guide research: the catalogue supports selection, provider code
requests and reads source data, and the shared engine performs common operations.

Start from the relevant provider issue and current repository state. Treat earlier
research and third-party adapters as leads to recheck, not authority for source
meaning or current access. Identify the intended scope and the next unresolved
step before investigating. Use the [steps below](#provider-steps-and-their-code-targets) for concrete outcomes
and code references; read the references needed for the current work.

## Keep the provider ports tracker current

Check the [provider ports tracker](https://github.com/RivRetrieve/RivRetrieve/issues/870)
before selecting or starting a port. Confirm that the provider is not already
implemented on `main`, marked in progress (`🚧`) by another contributor or agent,
or listed in the externally blocked group awaiting an access or maintainer decision.

Update the tracker entry in place as work progresses. Fetch the latest issue body
immediately before editing (for example with `gh issue view 870 --json body`)
and change only that provider's line so concurrent updates are preserved:

1. **When starting work** (beginning Step 1 research or creating a `port/<provider>`
   branch): change `- [ ]` to `- [ ] 🚧` and append a short status note naming the
   active branch or Effort issue, such as `*(in progress on port/ee-est, #352)*`.
2. **When pausing on a blocker** (such as awaiting an agency reply or a maintainer
   scope decision): keep `🚧` or move the entry to the blocked group and state what
   it is waiting on in the status note.
3. **When merged into `main`** (after Step 8 final review is approved and the port
   pull request is merged into `main`, not when work finishes on a `port/<provider>`
   branch): remove `🚧`, tick `- [x]`, and record the merged pull request, such as
   `*(merged in #900)*`.

When opening a new provider-port issue that is not yet in the tracker, add a `- [ ]`
entry in the matching complexity group linking to the new issue.

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

A terms or licence page that automated tools cannot read, such as one requiring
JavaScript, is not the same as terms that do not exist. Ask a person to open it
directly before drafting external correspondence; a publisher's own data catalogue
often states a licence, in seconds, where a support request would take much
longer.

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

Preserve observation qualifiers, approval statuses, method notes, unmeasured source
slots, and non-identity series attributes through declared
[`AnnotationSchema`](../../src/rivretrieve/_internal/source_annotations.py) definitions
with plain Polars types, verified descriptions (never placeholders such as
`"unknown"`), and official `http` or `https` `reference_url` links. Do not alter
`ObservationResult.data`, create stream variants solely for annotation changes, or
emit per-row informational quality-code issues when annotations carry those source
fields.

Distinguish stream selectors, which belong in `SourceSeries.variant`, from
non-identity series attributes, exposed through `rr.series(result, annotations=...)`,
and observation annotations, exposed through `result.to_polars(annotations=...)`.

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
Use the shared [cursor pagination helper](../../src/rivretrieve/_internal/page_acquisition.py)
(`acquire_pages`) for cursor-paginated endpoints. When acquisition inspects a response
to follow pagination links, check completeness, validate a response envelope, or
resolve a prerequisite lookup, it can narrow each consumer context with
`narrow_payload_for_pair`, attach context-bound `InterpretedPayload` entries on
`SourceAcquisition.interpretations`, and release decoded source structures before
returning. The driver reuses the `ParsedSeries` when effective inputs match and falls
back to shared or per-pair parsing whenever context inputs change. The
[Lithuania fetcher](../../src/rivretrieve/_internal/providers/lt_lhmt/fetch.py),
[Peru SENAMHI fetcher](../../src/rivretrieve/_internal/providers/pe_senamhi/fetch.py),
[Austria eHYD fetcher](../../src/rivretrieve/_internal/providers/at_ehyd/fetch.py),
[Hub'Eau fetcher](../../src/rivretrieve/_internal/providers/fr_hubeau/fetch.py),
[USGS fetcher](../../src/rivretrieve/_internal/providers/usgs_nwis/fetch.py), and
[Argentina INA fetcher](../../src/rivretrieve/_internal/providers/ar_ina/fetch.py)
show these patterns as concrete examples.

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
registration. The [Lithuania parser](../../src/rivretrieve/_internal/providers/lt_lhmt/parse.py),
[Peru SENAMHI parser](../../src/rivretrieve/_internal/providers/pe_senamhi/parse.py),
[Austria eHYD parser](../../src/rivretrieve/_internal/providers/at_ehyd/parse.py),
[Hub'Eau parser](../../src/rivretrieve/_internal/providers/fr_hubeau/parse.py),
[USGS parser](../../src/rivretrieve/_internal/providers/usgs_nwis/parse.py), and
[Argentina INA parser](../../src/rivretrieve/_internal/providers/ar_ina/parse.py)
show native parsing connected to source-series mappings, single-pass shared response
decoding, and per-page memoization of repeated series and physical fact definitions
without retaining mutable state across pages. When multiple co-acquired products share
an undecoded response, implement `SharedParseProvider` (`parse_group`) in
[provider stages](../../src/rivretrieve/_internal/driver.py), or `parse_mapped_group`
in the [mapped series helper](../../src/rivretrieve/_internal/provider_series.py) for
mapped providers, so source bytes decode once into independent per-product
`ParsedSeries` results and drop intermediate decoded dictionaries immediately after
parsing so memory retains only per-product tables.
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

When a suitable published observational dataset is available, usually a regional
CAMELS dataset, require a bounded comparison with values retrieved through
RivRetrieve's public API. Match stations confidently and select overlapping dates.
Use a reproducible random sample without selecting for agreement; ten gauges is a
useful default, not a rigid requirement. Plot both hydrographs with explicit unit
conversion and preserved gaps. Inspect for obvious errors and investigate meaningful
discrepancies without filtering, shifting or fitting values to force agreement.

A comparison window bounded to a published dataset's coverage, such as a CAMELS
dataset's end date, is not evidence of the source's actual historical reach. Check
each sampled station's own earliest-available-result metadata where the source
publishes one, and test a genuine retrieval against a window near that claimed
depth for at least one long-running station, not only the modern comparison
window. A single failed attempt against a far-back window can be a transient,
cold-query response rather than an absence of data; retry before concluding the
data is not retrievable. Separately, a source may track an older, lower-frequency
product (for example, manually-taken spot measurements) alongside the continuous
product a provider retrieves, reaching further back than the continuous record
does; note this as an open scope question when found, rather than assuming the
continuous product's own history is the source's only route to older data.

Retain the dataset version, station and date selection, comparison method, figures,
findings and limitations through the existing evidence process. If no suitable
dataset is available, record why; that absence alone does not block the port.
This is a sanity check alongside source verification, not proof of identical source
definitions or independent measurement accuracy. Unresolved semantics remain
caveats unless they make the comparison misleading.

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
series distinctions, declared source-annotation schemas and fields where applicable,
time and units, availability limits, terms and unresolved facts that affect interpretation.
State consequences clearly rather than publishing the whole investigation. Keep detailed
research and correspondence in the private record.

Follow [documentation guidance](../AGENTS.md) and use existing
[provider pages](../providers/) for scope. Link general usage rather
than repeat it. Do not present a successful example as proof of continuous coverage.

Reuse shared layout verbatim rather than inventing a new shape per provider.
In particular, the "What you can retrieve" table uses this exact header, in
every provider page that has one, whether or not the data needs every column:

```
| Quantity filter | Source field / `variant` | Frequency | Statistic | Source unit | Returned unit |
```

Before writing a new provider page, grep the other pages in `../providers/`
for the section headers and table shapes you are about to use, and try hard
to follow them. Existing pages already show how to handle a column that does
not obviously apply: `ba_fhmzbih` fills `Frequency`/`Statistic` with
`Unknown` rather than dropping the column. Difficulty fitting one provider's
data into the shared shape is not by itself evidence that the shape is
wrong; look for how another page handled a similar gap before concluding the
table itself needs to change. If you still think it does, raise that for
review rather than quietly adding, removing, or renaming a column on just
the new page.

**Outcome:** users can understand the result and its limits without reconstructing
the investigation. Documentation and implemented behavior agree.
