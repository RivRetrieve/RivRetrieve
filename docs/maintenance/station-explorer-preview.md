# Preview the station explorer locally

This branch contains a prototype for review. It does not authorize publication,
merging, or deployment. Review the explorer inside the documentation, where its
map fills the viewport below the documentation navigation. One compact panel holds
Discover, Selection and Python tabs. Other documentation pages keep their normal layout.

## Prepare and serve the documentation

Use the prototype branch with Python 3.13 or later, `uv`, and Node.js 22.12 or later with `npm`.
Run these commands from the repository root:

```sh
uv sync --all-extras --dev
uv run python docs/scripts/generate_station_catalogue.py
npm --prefix web/station-explorer ci
npm --prefix web/station-explorer run build
uv run mkdocs build --strict
uv run mkdocs serve -a 127.0.0.1:8000
```

Open <http://127.0.0.1:8000/map/>. Keep the final command running during review;
press Ctrl+C to stop it. These commands prepare and serve local files. They do
not deploy the documentation.

The catalogue exporter reads approved packaged catalogue products and writes
`web/station-explorer/public/catalogue.json`. It does not download national
archives, retrieve observations, or require source credentials. Vite builds the
browser app into `docs/assets/station-explorer/` and copies the catalogue there.
The documentation build requires both the prepared app and its catalogue. A
missing asset stops the build with a preparation message; the build hook does
not install frontend dependencies or run npm.

Repeat the catalogue export after catalogue changes. Repeat the frontend build
after changing the app or exported catalogue, then restart the documentation
preview if it has not reloaded. Generated catalogue files, browser bundles and
the built site are local outputs, not source files to commit or review evidence.

## Review the request workflow

- Click a count bubble to zoom into its gauges. Groups split as projected points
  separate. At maximum zoom, a group opens its individual gauges in the same panel.
  Selected gauges and conflicts remain separate map symbols.
- Change discovery filters, inspect a gauge, and add it individually. Try **Add
  all matches** with a larger selection.
- Configure dates and inspect single-provider and multi-provider Python requests.
  Station identifiers must stay complete in copied code, including leading zeros.
- Change filters after selecting gauges. Confirm that selected non-matching gauges
  remain visible and block copying until their conflicts are resolved.
- Remove the final gauge. Copying executable code must remain blocked for an empty
  selection or invalid dates.
- Browse a catalogue-only provider. Selecting it must show an unsupported-retrieval
  warning and block copying, without silently removing it from the selection.
- Inspect bulk-download steps and credential-name comments in generated code.
  Do not execute national downloads or observation requests as a prototype check.
- Compare this page with the Usage page to check that only the explorer uses the
  full-width layout. Try a narrow browser window and a long station selection.

Catalogue entries do not guarantee observations for a requested period, and counts
need not represent unique physical sites across providers. Unknown availability
is separate from a filter conflict. Unknown-CRS and NAD83 (EPSG:4269) coordinates
are displayed on the WGS84 basemap without datum transformation. These are
approximate display positions, not certified coordinates.

The snapshot has 78,175 catalogue entries. Of these, 77,020 have matching series.
The 1,155 entries with no described series remain available through **Browse gauge
list**, then **Include entries without matching series**. Selecting one preserves
it as an explained conflict; absence of catalogue series does not establish
absence of observations.

The browser handoff ends at Python code. It does not execute that code or collect
credentials. Background map tiles may use the basemap service; they are not
observation requests. Automated checks do not establish responsiveness or finish
the owner's hands-on review. Report usability problems and stop for feedback.

## Source-independent checks

```sh
npm --prefix web/station-explorer test
npm --prefix web/station-explorer exec -- playwright install chromium
npm --prefix web/station-explorer run test:browser
```

With the MkDocs preview running, check the full catalogue inside the docs:

```sh
DOCS_URL=http://127.0.0.1:8000 npm --prefix web/station-explorer run test:browser
```

The last command measures initial loading, filtering, and adding a long selection.
It checks that the explorer requests only localhost and basemap tiles. The existing
documentation theme also requests Google fonts and GitHub repository metadata.
It does not contact observation services or run generated retrieval code.
