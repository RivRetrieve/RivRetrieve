# Preview the station explorer locally

This branch contains a prototype for review. It does not authorize publication,
merging, or deployment. Review the explorer inside the documentation, where its
map fills the viewport below the documentation navigation. One compact panel holds
Filtering, Selection and Python tabs. Other documentation pages keep their normal layout.
The explorer uses the active documentation palette, including the existing scheme
toggle; it has no separate theme control. The map opens around Switzerland without
restricting provider filters or selecting gauges. Space beyond the basemap extent
uses the documentation background color.

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
  separate. At maximum zoom, use the small gauge chooser to inspect co-located
  members. Selected gauges and conflicts remain separate map symbols.
- Change discovery filters, inspect a gauge, and add it individually. Try **Add
  all matches** with a larger selection.
- Set retrieval dates in **Filtering**, then inspect single-provider and
  multi-provider requests in **Python**. Changing dates must not change matches.
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

The owner-requested reduced surface exposes provider, station, quantity, frequency,
statistic and temporal-support filters. Dates are retrieval settings, not catalogue
coverage filters. Advanced physical and source-identity controls, series-fact details,
and the general gauge list are not exposed in this iteration. Inspect individual
gauges on the map; only co-located groups have a direct member chooser.

The snapshot has 78,175 catalogue entries, of which 77,020 have matching series.
Entries without described series are not individually browsable in this reduced UI.
This catalogue limit does not establish absence of observations.

Python previews use syntax highlighting from the documentation palette. Copying
still returns the complete plain Python request, including when the visible preview
is shortened. Unresolved requests remain commented and cannot be copied.

The requested CARTO Positron/Dark Matter raster switch is blocked on a basemap key.
[Current CARTO guidance](https://docs.carto.com/faqs/carto-basemaps) requires a key
for raster tiles; anonymous requests no longer return a usable basemap. This local
iteration keeps OpenStreetMap tiles. It does not request a key, create an account,
or establish permission for production use.

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
