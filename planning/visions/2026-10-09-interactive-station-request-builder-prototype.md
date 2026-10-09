# Interactive station request builder prototype

## Status and purpose

This vision defines a branch-only prototype and its review boundaries. The owner
authorizes publication, independent review and merge of this vision-only change.
That authorization does not extend to implementation PRs, prototype publication,
merging prototype code, or deployment. Verify this vision on the target branch
before handing it to an implementing agent.

Build an interactive prototype that helps people who do not write Python explore
RivRetrieve's station catalogue and generate the Python request they want. The map
should have a clear purpose: find matching gauges, inspect them, select them, and
obtain code for retrieving their observations.

The browser uses precomputed catalogue information. It does not retrieve observations
or execute generated Python. The user-facing handoff ends at runnable Python code.
Do not add instructions for installing Python, choosing an execution environment,
or running the generated request. Local preview instructions for prototype reviewers
are required and are separate from this user-facing boundary.

## Prototype and review workflow

This is prototype work, not authorization to replace the public map.

- Implement on a dedicated feature branch, preferably in an isolated worktree.
  Keep the prototype on that branch throughout the owner's and team's reviews.
- Provide a reproducible command and localhost URL for running the modified
  documentation. Reviewers must see the actual docs integration, not only a
  standalone map demo. Document any build or asset preparation steps.
- Build a usable iteration, perform appropriate checks, then stop. Report what can
  be tested and wait for the owner's hands-on feedback. Apply requested revisions,
  check them, and stop again. Do not autonomously proceed through review milestones.
- After the owner's feedback is exhausted, colleagues must be able to check out the
  same branch and run the docs on their own localhost. Push the prototype branch
  only after explicit permission. Include clear setup and preview instructions.
- Do not create a PR, merge into main, release to PyPI, deploy the site, or modify
  the public hosting repository without a separate explicit instruction.
- Finishing the owner's review does not authorize production integration. Keep the
  branch available for team feedback and blessing. Team approval alone is not an
  instruction for an agent to merge or deploy.

A permanent develop branch, branch-protection changes, and release-workflow changes
are outside this vision. The discussion of those topics did not authorize them.

## Map, filters, and selection

Use a full-width workspace inside the documentation, with explanatory text above
or below it. The map must not remain constrained to the normal article text column.
Preserve normal layout on other documentation pages. Include a side panel for the
selection and live code preview. Exact panel placement and responsive behavior are
open to prototype testing.

The experience has three distinct states:

1. Matches: gauges whose catalogue series match the current discovery filters.
2. Selection: gauges the user explicitly added to the request.
3. Request preview: generated Python reflecting the filters, selection and dates.

Expose the discovery filtering capabilities of rr.find and rr.pick. These include
provider and station identifiers; quantity, frequency, statistic, temporal support,
day definition, timestamp anchor, time zone, vertical reference and vertical datum;
and source variant and series identity. Less common controls may be grouped, but
must remain available. on_issue is error-handling policy, not a station filter.
Use the current public API as the authority for supported arguments and semantics.

Filtering highlights matching gauges. A prominent Add all matches action adds the
matching set. Users can also click a gauge, inspect its details, and add it
individually. Selected gauges look distinct from unselected matches. Allow explicit
removal. Panning, clicking to inspect, or changing filters must not silently add
stations. Preserve provider-qualified station identity, including leading zeros;
the same station ID in different providers is not automatically the same gauge.

The panel updates the generated request as selections and settings change. Keep
station IDs directly in Python. Do not create a separate station CSV or another
station-selection file. Long lists can be collapsed in the preview, while the
copied code contains the complete selection.

## Preserve selections and make conflicts visible

Changing filters preserves previously selected gauges. A selected gauge with no
matching catalogue series under the new filters becomes a visible conflict. Keep
it visible in the selection and distinguish it on the map where it can be plotted.
Use warning text and icons as well as color. Show matching and conflicting counts,
and explain the mismatch where the catalogue supports an explanation.

Users resolve conflicts by changing filters or removing gauges, individually or
with an action such as Remove non-matching gauges. Do not silently discard gauges,
broaden the filters, or generate code that quietly omits conflicting selections.

Keep the preview visible, but block code-copy and any code-export actions while
conflicts remain. Put the reason and resolution actions beside the blocked action.
The preview must clearly indicate that the request is unresolved.

When no gauges are selected, show an empty selection state and block executable
code-copy/export. Never translate an empty selection into an unrestricted request;
rr.pick with an empty station list does not mean select zero stations. Also block
executable output while required request settings are missing or invalid.

An unknown physical fact does not match an explicit filter on that fact. Explain
that the fact is not established rather than claiming the measurement is absent.
Unknown availability for a requested date range is not a selection conflict and
does not block code generation merely because availability is unknown.

## Generated request

The conceptual sequence is:

- selection = rr.find(...) represents the current discovery filters.
- gauges = rr.pick(selection, ...) represents explicit gauge selection.
- results = rr.fetch(gauges, start=..., end=...) retrieves the requested dates.

The discussion used rr.select informally. The current API is rr.pick; do not add
or invent a select API. Adapt the code to actual API constraints, including
provider-qualified selection and multi-provider requests. rr.fetch accepts one
provider; use rr.fetch_by_provider or valid provider-specific requests when needed.
Do not assume independently filtering provider and station lists preserves exact
provider/station pairings.

Dates belong to retrieval configuration, not catalogue coverage filters. The
complete generated code should be runnable once the user supplies required
credentials and runs it in a suitable environment. Do not invent required values;
make missing required request settings visible.

For selected bulk providers, include actual rr.download(provider) preparation steps,
not only a note that downloading is needed. Explain the archive download and its
potential bandwidth/storage cost in comments. Explain required credential names
where applicable, without asking the browser to collect secrets or embedding them
in code. Include appropriate issue inspection so returned rows do not hide failures.

Follow retrieval with an optional commented example:

    # To save the observations as CSV:
    # results.to_polars().write_csv("observations.csv")

Adapt that example for multi-provider return values. Do not automatically export
observations in the main request. This optional observation export is distinct from
the rejected station-selection file.

## Source fidelity and scope

Catalogue entries do not guarantee observations for a quantity or date range, and
counts do not necessarily describe unique physical sites across providers. Preserve
source facts, unknowns and supported distinctions in the UI and generated filters.
Do not infer complete records, scientific comparability, preferred source variants,
or unpublished products. Catalogue-only providers must not be presented as if
observation retrieval is supported. Keep them browsable. If explicitly selected,
preserve them with an unsupported-retrieval warning and block executable code-copy
and export until they are removed. Do not silently omit them or emit a mixed-provider
request that will fail on an unsupported provider. This access limitation is distinct
from a filter conflict or unknown availability for a requested period.

The catalogue snapshot drives browser discovery. Preserve the library's documented
retrieval semantics: source responses may reveal additional matching series unless
explicitly restricted. Do not promise that map counts predict returned series counts.

Do not add an observation service, time-series previews requiring live retrieval,
catchment modelling products, a station-file workflow, or an unrelated public API
redesign. This work does not require private source evidence to be copied into web
assets. Use approved public catalogue products only.

## Repository context and design reference

The source documentation lives in RivRetrieve. mkdocs.yml configures MkDocs Material.
docs/map.md currently embeds docs/assets/stations_map.html with width="100%" and a
720px height. That fills the article column rather than the available page width.
docs/scripts/generate_station_map.py generates a standalone Leaflet/MarkerCluster
map with provider toggles, station-ID search and a single-station find snippet.
Its compact station records do not contain all the series facts needed by the new
filters. Plan public metadata assets accordingly rather than treating existing
marker records as a complete discovery catalogue.

Consult docs/usage.md, docs/reference.md and the public API in
src/rivretrieve/_internal/discovery.py for filtering, date and provider behavior.
Canada and Poland currently require bulk preparation. Norway and Brazil require
credentials. Verify current capabilities rather than generalizing these examples.
The existing map documents an unknown-CRS plotting assumption; do not turn such
positions into certified coordinates or unsupported spatial claims.

The sibling rivretrieve.github.io repository contains the generated hosting site.
.github/workflows/deploy-docs.yml builds the source docs and deploys to that
repository's main branch. Qualifying pushes to RivRetrieve main can update public
documentation. Do not edit or deploy the hosting output as the prototype workflow.
The current docs build uses uv sync --all-extras --dev and
uv run mkdocs build --strict. Establish and test the actual localhost preview
command with any new frontend preparation, rather than merely assuming it works.

The reference app is /Users/nicolaslazaro/Desktop/thirdparty/estreams-react.
It uses React, Leaflet and MarkerCluster, with a precomputed station network,
provider/record-length filters, single-station focus and progressively disclosed
details. It does not already provide batch selection or Python generation. Its
useful inspiration is a responsive exploration experience and concise details.
Its performance has not been measured in this discovery. A React rewrite alone
is not proof of responsiveness; the current map already uses Leaflet. Do not copy
unsupported record-length filters, basin products, or data-download features from
eStreams.

## Agreed technology stack

Use React with TypeScript for the explorer, Vite for frontend development and static
builds, and Leaflet for the map. React coordinates filters, selections, conflicts
and the live code preview. TypeScript checks the shapes of catalogue data and
application state. Vite supplies frontend tooling; it does not replace the required
preview through the actual MkDocs documentation.

Keep the frontend source in web/station-explorer/, with its React and TypeScript
code under web/station-explorer/src/ and its package.json and Vite configuration
at the app root. Keep src/rivretrieve/ for the Python library. docs/map.md owns the
documentation integration; the frontend build supplies generated static assets to
the docs build. Exact build-output wiring remains an implementation detail. Do not
hand-edit generated bundles or include the browser app in the Python distribution.

Build static browser assets and integrate them into the full-width documentation
workspace. Load precomputed public catalogue assets. There is no application backend,
Python runtime in the browser, or browser observation retrieval. Python may remain
part of preparing catalogue assets during development and builds.

Test Leaflet rendering and filtering responsiveness against the full catalogue early.
The stack is settled; rendering strategy, asset loading and other reversible
implementation details remain open. Do not assume the reference app's full marker
rebuild strategy will meet the prototype's responsiveness needs.

## Evidence of a useful prototype

Before each review handoff, check the changed behavior at an appropriate level and
make the following interactions available for hands-on review:

- Start the actual modified documentation on localhost and open a full-width map.
- Change discovery filters, inspect gauges, add individual gauges and add all matches.
- Generate correct single- and multi-provider code with complete station identities.
- Change filters after selecting gauges, see preserved conflicts, observe blocked
  copy/export, resolve conflicts, and copy code again.
- Select enough gauges to exercise long lists without requiring a station file.
- Configure dates without implying verified observation coverage.
- See real bulk-download steps and relevant credential comments in generated code.
- Browse and select without browser observation requests, and without any deployment.

Use source-independent tests and synthetic inputs to protect filter parity,
selection identity, code generation and conflict behavior. Include regression cases
for zero selected gauges, removing the final gauge, and catalogue-only selections. Follow repository test
and evidence guidance. Do not trigger national downloads or credentialed observation
retrieval just to test generated code. Report checks, limitations and remaining
prototype rough edges honestly. Snappiness and usability require the owner's
interactive review; automated checks do not complete that review.

Keep further design choices reversible. The prototype, feedback and team review
will determine readiness for a separately authorized production integration.
