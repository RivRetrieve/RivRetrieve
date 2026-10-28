# Remove South Africa from the catalogue

Related issue: https://github.com/RivRetrieve/RivRetrieve/issues/555

South African stations still appear in RivRetrieve 0.1.2 and its public station
explorer, although observation retrieval is unsupported. Remove `za_dws` from
both package catalogue discovery and the public station explorer for v0.1.3.
Users should not be offered these stations until South African retrieval is
supported.

## Agreed scope

- Remove South Africa from the package's offered catalogues, not just the map UI.
  The generated explorer data must also omit its stations, series and provider
  entry. Keep the other providers available.
- Keep South Africa listed as **coming soon** in the README and country coverage
  map. That future-coverage listing is separate from the station explorer.
- Preserve the unfinished South African work and the deferred follow-up in
  [#212](https://github.com/RivRetrieve/RivRetrieve/issues/212). Repairing DWS
  access, implementing retrieval and deleting that research are out of scope.
- Use the existing release process. Do not introduce a separate docs deployment
  mechanism or patch generated website data as the source of truth.

## Current behavior and implementation context

At v0.1.2, `src/rivretrieve/_internal/provider_manifest.py` registers `za_dws`.
Its provider declaration uses `CatalogueOnly`: discovery is offered but
observation retrieval is not. The earlier retrieval work was deferred after DWS
HTTP 403 refusals.

`docs/scripts/generate_station_catalogue.py` exports registered catalogues to
`web/station-explorer/public/catalogue.json`, including catalogue-only providers.
The Vite build produces `docs/assets/station-explorer/`, embedded by `docs/map.md`.
The live explorer inspected during discovery contained 2,905 South African
stations and 8,715 series, marked as unsupported for retrieval. Those counts are
context, not fixed acceptance values. The old `generate_station_map.py` is not
the active explorer pipeline.

`docs/scripts/coverage_map.py` separately lists South Africa as a planned country;
retain that listing. Choose the smallest implementation that removes the offered
catalogue consistently while preserving deferred work. Exact code changes and
source-file organization remain implementation decisions.

## Verification and release

Verify that the resulting package does not offer `za_dws` through provider or
station discovery, and that regenerated explorer data and its displayed provider
list contain no South African entries. Verify that other providers remain
available and that the coming-soon listing remains. Cover the removal at the
relevant package and export boundaries using the repository's testing guidance.

Target v0.1.3. The existing `publish-pypi.yml` workflow publishes the package and
builds and deploys the docs on release publication. The docs-check workflow does
not deploy. Before publication, verify the built package and generated site;
after publication, verify the public explorer. Do not claim the live map is
corrected merely because the implementation merged. Existing 0.1.2 installations
remain unchanged.

An unpublished v0.1.3 release draft already exists, titled **RivRetrieve 0.1.3**,
with the approved minimal note:

> Remove unsupported South African stations from the catalogue and station map (#555).

Reuse that draft. Neither this vision nor its publication authorizes publishing
the release; that remains a separate action authorized by the maintainer.
