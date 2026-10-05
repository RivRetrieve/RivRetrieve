# Complete evidence-backed Hub’Eau catalogue rebuild

Related bug: https://github.com/RivRetrieve/RivRetrieve/issues/522

Blocked work: https://github.com/RivRetrieve/RivRetrieve/issues/515 and its draft
implementation PR https://github.com/RivRetrieve/RivRetrieve/pull/521.

## Outcome

Restore the complete offline Hub’Eau catalogue rebuild from genuine retained
source responses. The maintained verification route must select the correct
inputs, verify their identities, supply them throughout the rebuild, and prove
that the resulting native table, capture record and catalogue match the approved
products, including station metadata.

The owner approved a comprehensive repair. There is no minimal-patch constraint
or time/resource shortcut. Investigate the complete path and repair related bugs
established during implementation, including both confirmed failures below.
Stopping after input selection succeeds does not meet this vision.

Use the genuine evidence. The publication check that requires original site
responses is a safeguard to preserve. The problem is that this rebuild route
fails to supply the required evidence; it is not a reason to publish without it.

## Established failures

### Input requests do not match the archive’s registered scopes

The affected test is
`tests/test_fr_hubeau_generate_catalogue.py::test_retained_station_responses_rebuild_exact_native_capture`.
Its governing marker calls `_catalogue_recording_paths("fr_hubeau")` without an
explicit directory scope. This expands packaged recording references into
individual body requests. The archive registers the relevant site responses as
a directory input, rather than registering each of those individual requests.

The archive intentionally matches requested scope names exactly. An unknown
file request does not inherit a parent directory’s binding. Consequently the
coordinator stops before retrieval with:

```text
archive.catalogue.EvidenceError: Selected test input scope has no exact archive binding.
```

The public helper already supports explicit scopes. The canonical catalogue
composition test in `tests/test_catalogue_origin_certification.py` uses
`maintenance/catalogue/station_metadata/sources/fr_hubeau`. The maintained
archive registers this provider scope as well as the narrower sites scope.
Requesting an explicit registered scope preserves exact matching. Once selected,
a directory binding composes its manifest-listed descendants and verifies their
identities; this is distinct from guessing parent bindings for unknown requests.

### The rebuild omits required metadata evidence

The affected test builds a catalogue without `metadata_sources`, then derives
its adopted build inputs from that incomplete provenance. The rebuild function
in `src/rivretrieve/_internal/providers/fr_hubeau/rebuild_catalogue.py` also calls
`build_catalogue` without metadata sources before calling `write_catalogue`.

Publication requires metadata and its selected original site responses. The
writer in `generate_catalogue.py` therefore raises:

```text
France metadata publication requires its selected original site responses
```

A synthetic probe confirmed that a metadata-free build reaches this refusal
before the writer emits catalogue files. The preceding rebuild stages can already
write native/capture outputs; the probe does not establish whole-rebuild atomicity.
Adding a scope to the marker alone cannot repair this path.

The shared catalogue composition test already reads metadata sources through an
explicit verified input receipt before building provenance. The build-input
fixture in `tests/conftest.py` adds dynamic site manifest, lineage and receipt
support for site recordings present in that provenance. Use these existing
contracts as evidence for a coherent repair rather than inventing a parallel
input-selection system.

## Investigation evidence and limits

The discovery used public revision
`64958d24b059f429986f096cab34fa8f462d1059` and archive code revision
`0585626ba2342c056064ae320d47ae498e751486`.

- Source-free collection selected 4,867 public non-live tests. Comparing their
  requirements with the exact archive bindings found 111 unmatched requests,
  all from the affected test and all site-response bodies.
- A source-free probe reproduced the exact selection error. Hypothetically
  replacing only that test’s descendant requests with the explicit sites scope,
  or the provider metadata scope, made exact selection succeed. Existing
  declared retained targets remained covered by the selected bindings.
- The affected test, recording helper, public selection code, shared fixture and
  Hub’Eau provider subtree were unchanged between that public revision and
  #515’s candidate `2621654d4e440c708a6c5d0d4b0dd6c7ba2aa310`.
- The affected public source-independent selections passed: 21 tests passed and
  120 source-dependent cases were deselected. Archive input-composition and
  metadata-review tooling tests passed: 56 tests.
- A separate synthetic probe reproduced the metadata-publication refusal using
  the existing public synthetic catalogue setup.

These findings establish the selection defect and missing metadata handoff.
They do not establish asset availability, retained member completeness, successful
source certification or full-suite acceptance. No retained source bodies were
fetched during discovery. The issue records an earlier full coordinator failure
at selection, after public and private source-free collection; that historical
run also did not reach retained-input acceptance.

## Repair responsibilities

Follow the complete flow from test declaration and archive binding through
verified input composition, metadata reading, provenance/build-input adoption,
source-response reconstruction and publication. Examine both the library entry
point and the maintained command-line route, together with their documentation.
A test-only injection that leaves the maintained rebuild command broken is not
sufficient.

Preserve the complete rebuild responsibility. Do not turn this into a native-only
operation or remove the metadata comparison to bypass publication. Supply the
verified metadata dependencies and all required supporting identities before
selecting adopted inputs and publishing. Resolve paths, receipts and resource
wiring at explicit composition boundaries; lower-level operations receive the
resolved dependencies they need.

Investigate additional related defects instead of treating the two known failures
as an exhaustive list. Correct related archive/input-handling defects if evidence
establishes them. The archive remains responsible for exact collection membership,
retrieval, source certification and reviewed declarations; RivRetrieve remains
responsible for catalogue transformations and library behavior. Changes spanning
both repositories require reviewed revisions and a clear delivery handoff.

#515 owns a separate cache-lifecycle implementation. Do not fold its unrelated
pending changes into this repair. This distinction does not exclude related
storage or evidence-handling bugs found in the rebuild path. The discovery has
not established that these failures are caused by #515’s storage changes.

Choose implementation mechanisms from evidence. Prefer existing contracts and
shared test infrastructure; avoid unnecessary frameworks, inventories and broad
rewrites that do not contribute to the complete outcome.

## Safeguards

- Retain exact binding validation, manifest membership, fingerprints, receipt
  checks, provenance identities and all governing prerequisites.
- Keep genuine original responses distinct from derived tables and synthetic
  controls. Do not substitute one for another, infer missing source facts or
  silently acquire fresh material under a historical acquisition identity.
- Preserve hydrological interpretation, approved source facts and output content.
  If genuine-input checks expose an additional defect in those outputs, establish
  the evidence and follow the applicable source-review/publication process rather
  than changing expected values merely to make a comparison pass.
- Keep the rebuild offline. Required missing or changed inputs must fail rather
  than trigger network access, defaults or publication without evidence.
- Review exact public/private executable and declaration revisions before
  controlled execution. Follow `docs/maintenance/evidence.md` and the maintained
  private archive README rather than reconstructing an acquisition route.
- Keep controlled bodies, private receipts, paths, logs, credentials and unreviewed
  products out of public repositories, issues, PRs, caches and distributions.
  Use restricted external evidence/output storage and share only reviewed summaries.
- Preserve source originals. Candidate products remain external until reviewed;
  the repair does not authorize automatic replacement of packaged catalogues.

## Acceptance

1. Protect the actual consumer declaration with source-independent coverage that
   detects this mismatch. Preserve the helper’s scope-boundary and uncovered-path
   behavior. Keep private binding authority in the archive; do not copy its
   inventory into public tests.
2. Add focused synthetic coverage for the metadata dependency flow through rebuild
   and publication, including the maintained CLI composition. The checks must
   detect the missing handoff, not merely show that the publication safeguard
   still raises. Protect failure on absent, changed or unadopted required evidence
   at the simplest sufficient existing contract boundaries.
3. Run affected source-independent tests and broader checks appropriate to the
   changed boundaries. Follow `docs/maintenance/testing.md`; use `uv` exclusively
   for project execution and temporary cache/store roots.
4. On the exact reviewed repaired revisions, run the maintained coordinator’s
   complete original non-live cohort in both repositories, with catalogue input
   mode and the required full governing checks. The historical command shape is:

   ```sh
   uv run --isolated --locked python -B verify.py \
     --reviewed-archive-sha "$ARCHIVE_SHA" \
     --code-checkout "$CLEAN_PUBLIC_CHECKOUT" \
     --reviewed-code-sha "$PUBLIC_SHA" \
     --catalogue-inputs \
     --reviewed-declaration-sha "$PUBLIC_SHA" \
     --output "$NEW_RESTRICTED_OUTPUT" \
     --tests -- tests -m "not live"
   ```

   Confirm the current maintained instructions before execution. Do not narrow
   the cohort, skip checks, weaken validation or count source-free collection as
   genuine-input acceptance. Unavailable mandatory evidence blocks delivery.
5. Demonstrate the retained-response rebuild completes offline and preserves
   exact native-table bytes and capture identity, and the approved catalogue
   tables including station metadata. Preserve complete input identities and
   source-fidelity checks throughout. Verify the maintained rebuild CLI with
   the reviewed genuine inputs as well as its source-independent wiring.
6. Report exact revisions, full cohort results, applicable governing outcomes,
   output comparisons and limitations in a disclosure-safe implementation PR
   summary. Update affected interface documentation with the delivered behavior.

## Delivery and resumption of #515

Publishing this vision leaves #522 open. It does not authorize implementation
within the vision-publication session or close the bug.

After implementation meets acceptance and its fix PR merges, #522 should be
closed through that delivery. The implementation PR must clearly identify #522
and provide the verified merged-fix handoff, including any required archive
revision or companion change. If acceptance is blocked, keep #522 open and
report the missing evidence or remaining failure.

The owner will give the merged fix PR to the #515 agents. Those agents must
independently verify that the merged fix addresses the blocker on their candidate
before resuming #515, following that issue’s existing pause rule. They must
complete its required verification rather than treating issue closure as a test
result. A remaining failure must be reported instead of resuming. This repair’s
merge does not deliver or close #515 and does not merge its draft PR #521.
