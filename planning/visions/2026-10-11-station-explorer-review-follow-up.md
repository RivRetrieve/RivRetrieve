# Station explorer review follow-up

Make the station explorer predictable when users collect gauges across searches.
Users should be able to inspect gauges, add them one by one or in groups, and copy
Python that requests the selected observations without depending on their last
station search.

## Implementation and mandatory human review

Continue the existing `feat/station-request-builder-prototype` branch, reviewed at
`8bb6524e`. Its existing checkout is
`.worktrees/visions/station-request-builder-prototype`. Preserve its source and
local configuration. This is a revision of the existing prototype, not a rewrite
or an instruction to implement from main without the prototype.

Publishing this vision authorizes only the documentation publication workflow.
It does not start implementation. A later implementation instruction authorizes
work on the prototype branch, with this mandatory stopping point:

1. Implement the agreed changes and run appropriate checks.
2. Start the updated documentation locally and give the owner a working localhost
   URL to the map, together with concise review instructions and known limitations.
   A standalone frontend preview is not the required handoff.
3. Stop for the owner's personal hands-on review and Thiago's hands-on review.
4. Apply requested revisions, verify them, and return to local review.
5. Do not merge implementation into main or deploy it until both reviewers are
   happy and the owner explicitly authorizes the merge. Passing tests, completion
   of implementation, or a colleague's approval is not authorization.

Do not create an implementation PR, push prototype revisions, release a package,
or modify the public hosting repository without separate explicit permission.
Keep the local preview available for review and report how to restart it if needed.
The documentation PR for this vision does not contain or approve prototype code.

This follow-up supersedes the original
[prototype vision](2026-10-09-interactive-station-request-builder-prototype.md)
where it couples browsing filters to the request or exposes a broader control set.
Keep the current reduced interface and the original source-fidelity, browser-only,
exact-identity and review boundaries otherwise.

## Separate browsing from the requested observations

The reviewed prototype uses one filter object both to find map matches and to
construct `rr.find(...)` in generated Python. Searching for station 2 after adding
station 1 therefore makes station 1 a conflict. Clearing filters can unblock copy
but also remove a discharge restriction and request other quantities.

Separate the two user intentions:

- Provider and station searches control which gauges the user is browsing.
  Changing or clearing them must not invalidate, remove or change gauges already
  selected, or alter the observations requested from those gauges.
- Quantity, frequency, statistic and temporal support are request settings shared
  by the selected gauges. They may also narrow map matches to help find suitable
  gauges, but their effect on the request must be clear. Do not store independent
  measurement settings for each gauge or each add operation.
- Dates configure retrieval only. They do not filter catalogue matches or imply
  verified observation coverage.

For example, set quantity to discharge, search for station 1 and add it, then
search for station 2 and add it. Both gauges remain selected without a conflict
caused by the search. Clearing the browsing search leaves the discharge request
unchanged. Browsing another provider likewise preserves previously added gauges.
Changing the requested quantity intentionally changes the request for the whole
selection.

Generate Python from the selected provider/station pairs and the request settings,
not the current provider/station search. Preserve leading zeros and exact pairs
when identifiers overlap across providers. Keep the library's documented source
series discovery and retrieval semantics; do not freeze series identities as an
incidental consequence of this change.

A selected gauge incompatible with the measurement settings remains visible and
blocks copying until the user changes those settings or removes the gauge. Explain
that mismatch as a request-setting problem, not a browsing conflict. Empty
selections, missing or invalid required dates, and catalogue-only selections still
block executable copying. Unknown date availability alone does not block it.
Never silently omit selected gauges or broaden requested measurements.

Keep unresolved states clear. Do not generate misleading previews that combine a
new browsing provider with gauges selected from another provider. An empty
selection must not display the leftover browsing search as though it were a
request. Leave the precise empty and invalid preview presentation to implementation.

## Keep explicit station selections

Keep station IDs in copied Python, including when the selection equals all current
matches. “Add all matches” adds those gauges; it does not create a dynamic query
that can add more gauges when a later catalogue changes. Do not remove `rr.pick`
merely because it appears redundant against today's snapshot.

Retain the shortened on-screen preview and complete copied code. No station CSV,
selection-file workflow, or new dynamic-selection mode is needed.

## One consistent water-body descriptor

Add **Water body** to individual gauge details, using the existing metadata behind
`rr.metadata()`. Use that same label for every provider. Do not attempt to infer or
classify river, lake or reservoir names, and do not extract a river name from a
station name.

Display distinct nonblank values from `water_body_name_value`, preserving source
spelling. Identical strings appear once in this display. Ignore null and
whitespace-only values for this compact presentation; show **Not available** when
no nonblank name exists. Do not rewrite the underlying metadata, collapse its
source-field distinctions, or treat this presentation as a new harmonized source
fact. Keep selection cards compact; their Inspect action reaches gauge details.
This descriptor is not a new filter.

Actual packaged metadata checked on the reviewed branch illustrates the display:

- `no_nve / 16.24.0`, station name `Mårvatn`: `lakeName`, `reservoirName`, and
  `riverName` contain `Mår`, `MÅRVATN`, and `Mår`. Display
  **Water body: Mår · MÅRVATN**.
- `ch_foen / 2004`, station name `Murten`: `data-hydro-body` contains `Murtensee`.
  Display **Water body: Murtensee**.

Do not add drainage-area descriptors or filters. A future delineation engine is
intended to supply delineated basin areas. Delineated area is distinct from an
agency's published drainage-area metadata. Pourpoint integration, shapefile
handling, catchment delineation and area calculation are outside this work.

## Finish the review's interface corrections

- Visually separate retrieval dates from browsing controls. Show date validation
  errors beside the inputs, as well as a clear reason when copy is blocked.
- Use consistent label capitalization and correct singular/plural counts.
- Replace provider-code-only choices with readable provider labels while retaining
  their codes and catalogue-only status. Existing exported provider names are
  available; do not redesign provider identity.
- Link credential guidance from generated credential comments rather than copying
  setup instructions into the interface. Keep actual credentials out of the browser.
- Check the map inside the documentation at narrow widths, including 390 px.
  Keep gauge inspection and add actions easy to reach without losing usable map
  space. The review reported a half-height panel and an add action below the fold;
  verify actual usability rather than treating an automated observation as final.

Preserve existing working behavior: documentation theme integration, the Swiss
opening view, map clustering and co-located gauge inspection, bulk preparation
steps, required credential names, issue inspection, and single- and multi-provider
Python generation. Do not add unrelated controls or rewrite the map architecture.
Exact tab names, control placement and reversible implementation details remain
open to the implementing agent.

## Repository context and verification

The app is in `web/station-explorer/`. `src/App.tsx` owns the current controls and
state, `src/domain.ts` implements matching and request generation, and
`src/catalogue.ts` expands the browser catalogue. The exporter at
`docs/scripts/generate_station_catalogue.py` already reads station metadata but
exports only identity, name, coordinates and series facts. Extend the public
browser snapshot for the agreed water-body display without changing source
metadata contracts or including private evidence.

Use the existing test-first and testing guidance. Extend focused source-independent
coverage for browsing across stations and providers, preserving measurement
settings when clearing searches, measurement incompatibility, exact copied gauge
sets, consistent water-body display, and date feedback. Reuse existing checks for
empty selections, unsupported retrieval and provider-qualified identities.

Follow [local preview instructions](../../docs/maintenance/station-explorer-preview.md)
on the prototype branch, updating them to describe the revised workflow. Check
inside the real documentation with the full public catalogue and temporary test
resources. Do not execute generated observation requests or national downloads as
UI verification. Keep local keys out of logs, commits and review artifacts.

The final implementation handoff reports checks and limitations, gives the owner
the running localhost URL, and stops. Automated checks do not replace the owner's
and Thiago's approval or authorize merging into main.
