# Station explorer functionality rebuild

Rebuild the existing station explorer in `web/` with clearer responsibilities,
stronger behavioral tests, and better responsiveness. Keep the same feature and
user workflow. The owner wants more confidence in the quality and efficiency of
agent-assisted development, not a visual redesign or agents operating the product.

This vision defines the work for [issue #1092](https://github.com/RivRetrieve/RivRetrieve/issues/1092).
Completing the rebuild and the owner's review is intended to complete that issue,
even if UI SDK is not adopted. Publishing this document or completing an SDK
comparison alone does not complete the issue.

## Implementation branch and mandatory local review

Publication and merge of this vision-only documentation PR are authorized. That
authorization does not extend to implementation. Keep the rebuild on a dedicated
branch and do not merge its implementation PR into `main` before the owner's
hands-on local testing and subsequent explicit merge authorization.
A later implementation instruction authorizes the rebuild, checks, and this
required handoff:

1. Finish the implementation on a dedicated branch, preserving unrelated work.
2. Run the relevant checks and build the actual MkDocs documentation with the
   rebuilt explorer and full approved public catalogue.
3. Serve the documentation locally. Give the owner a working localhost map URL,
   short review instructions, measured performance comparisons, and known limits.
4. Stop for the owner's hands-on testing. Keep the preview available and provide
   reproducible restart instructions. A standalone Vite demo is not the handoff.
5. Apply requested revisions and return to local review when authorized.

Do not merge, deploy, release, or close #1092 merely because tests pass or the
implementation is finished. These require subsequent explicit authorization.
The present instruction is to publish the vision, not execute the rebuild.

## Scope and preserved behavior

Review all of `web/`, currently `web/station-explorer/`, as one application.
Substantial internal restructuring is allowed, but rewriting every file is not a
success criterion. Retain sound existing code and tests. Necessary integration
changes may touch the catalogue exporter, documentation embedding, build wiring,
and preview instructions; this is not a broader Python library or website redesign.

Preserve the existing workflow and its domain rules, including:

- Provider/station browsing remains separate from shared measurement settings.
  Browsing and clearing a search preserve selected gauges and their requested
  measurements. Dates configure retrieval, not catalogue availability.
- Exact provider/station identities, leading zeros, supported fact-segment
  matching, current frequency canonicalization and validation, and unknown facts
  keep their established meaning. Do not simplify away source distinctions.
- Incompatible selected gauges stay visible. Empty selections, invalid required
  inputs, conflicts, and catalogue-only selections cannot produce executable
  copied requests. Unknown availability alone is not a conflict.
- Copied Python retains every selected gauge and exact provider/station pairs.
  The shortened preview, multi-provider behavior, bulk preparation steps,
  credential-name guidance, and issue inspection retain their semantics.
- Map inspection, clustering and co-located gauge discovery, add/remove and bulk
  selection, selected/conflict symbols, and zoom-to-matches remain available.
  Preserve the opening view, documentation theme integration, and narrow-screen
  usability, including access to inspection and selection actions.
- The browser uses approved catalogue products. It neither collects credentials
  nor fetches observations nor executes generated Python.

The [preview guide](../../docs/maintenance/station-explorer-preview.md) describes
the current experience and build procedure. Existing tests and the public Python
API provide additional contracts. Fix regressions and defects that prevent the
preserved workflow, documenting any behavior correction. Record unrelated defects
for an owner decision rather than expanding the rebuild into general backlog
cleanup. No new user-facing feature, runtime agent integration, or visual redesign
is requested.

## Organisation and testability

Make catalogue loading and representation, domain rules, application state and
actions, map rendering, and reusable interaction behavior understandable as
separate responsibilities. State transitions should have a clear owner, without
duplicated sources of truth or unnecessary frameworks. Important rules should be
testable without constructing the entire map or documentation site.

Keep integration tests for the interactions between those responsibilities and
browser checks for actual user behavior. Testability means meaningful failures
when behavior breaks, not merely easier assertions against implementation details.
Follow the repository's test-first and testing guidance; retain useful coverage
and extend it for changed boundaries. Leave module layout, state-management
mechanisms, and other reversible choices to the implementing agent.

## Responsiveness is part of the outcome

The owner has heard that the map is slow and reports that catalogue loading is not
snappy. No browser benchmark was run during the discussion. Establish a baseline
before changing the relevant paths and demonstrate improvements to catalogue
startup and map responsiveness without sacrificing correctness or moving the same
cost into another ordinary action. If measurements do not reproduce a reported
problem or reveal a material performance trade-off, report the evidence and seek
an owner decision rather than claiming improvement or expanding scope to obtain
one.

Inspection identified plausible contributors, not diagnosed bottlenecks:

- `App.tsx` waits for the whole catalogue to be fetched, parsed, and expanded before
  mounting the map. Initial filtering and filter-option preparation also precede
  the loaded view.
- A local generated catalogue inspected during the discussion was approximately
  39 MB uncompressed, with 78,041 stations and 293,433 expanded series objects.
  This is an illustrative local snapshot, not a deployed transfer measurement,
  required count, or performance budget. Refresh it for the implementation.
- `StationMap.tsx` caches marker objects but clears and re-adds cluster membership
  when matches or selection change. Even adding one gauge can revisit all matches.
- Filtering scans catalogue entries on input changes. Large selections also incur
  request-generation work and map projection/drawing work.

Separate catalogue transfer, decoding/preparation, first useful station display,
and basemap tile loading. For ordinary interactions, distinguish updated count
text from a usable, painted map. Include filtering, single-gauge selection changes,
bulk selection, and pan/zoom where relevant. Compare equivalent catalogue content,
selections, and outputs; account for deferred work and cold versus warm loading.
Record baseline and candidate source revisions, browser/device and network
conditions, dataset revision and size, and measurement limitations. Use proportionate browser profiling and project-native
tools rather than inventing a benchmark platform.

The full-docs browser test currently logs initial/filter/cluster-zoom/add-all times,
but does not enforce a responsiveness budget; some completion checks observe
counts rather than final rendering. Improve evidence at the affected boundaries.
Choose justified regression checks from the baseline rather than inventing an
unsupported speed target. Automated measurements supplement the owner's review.

## Evaluate UI SDK without making adoption the goal

[Vercel UI SDK](https://github.com/vercel-labs/ui) is a candidate for organising
interaction behavior and supporting development and testing. It is not a required
dependency. Continue worthwhile refactoring if it proves unsuitable.

The current app uses React, TypeScript, Vite, Leaflet, and MarkerCluster. The SDK
provides interaction behaviors and framework adapters; it does not replace map
rendering, domain rules, or catalogue preparation. Tabs and the coordinate-warning
tooltip are plausible bounded comparisons. Compare useful behavior, clarity,
testability, dependency and bundle cost, and maintenance burden before expanding
adoption. Do not replace native controls solely for consistency with the SDK.

The SDK was in beta during research. Check the chosen release's APIs and terms,
and document the adoption or rejection rationale. Neither React nor Leaflet is
presumed to need replacement. Let evidence justify any dependency change.

SDK-assisted component tests may help, but API-driven actions do not prove actual
pointer, keyboard, focus, touch, and accessibility behavior. Retain real browser
checks. Its optional runtime agent bridge is not a product requirement; do not
add an agent backend or agent-operable product feature to justify adoption.

## Verification and handoff evidence

Use the frontend's documented npm commands and `uv` for Python/documentation work.
Run affected unit and browser tests, the frontend build/type checks, and the full
local documentation build. Extend Python/exporter checks if those boundaries
change. Use temporary test resources and approved public catalogue inputs.

Never execute generated observation requests or national downloads as UI tests.
Keep local basemap keys, keyed URLs, private source evidence, generated assets,
and credentials out of commits and review artifacts. Preserve attribution and
report unavailable services or validation blockers rather than hiding them.

The handoff should explain the new responsibility boundaries, SDK decision,
correctness checks, and before/after performance evidence with remaining limits.
Report assumptions and changed constants. Finish with the running local docs URL
and stop for the owner's testing. No implementation merge into `main` is authorized
until that review and subsequent explicit owner permission.
