# README and documentation review handoff

## Outcome and ownership

Finish the documentation work in [PR #249](https://github.com/RivRetrieve/RivRetrieve/pull/249)
and [PR #250](https://github.com/RivRetrieve/RivRetrieve/pull/250), validate it, and merge both
through the normal permitted process into `main`. The maintainer has taken responsibility
for implementing the remaining review concerns and merging the colleague's work.
This standalone vision is the implementation handoff, not an Effort or Program record.
Publishing this vision does not itself authorize its publishing agent to implement or merge
those two PRs; implementation begins only through a subsequent explicit instruction.

Read the current PR diffs, all review threads, and subsequent replies before editing.
The comments were gut reactions while reading, not a mechanical edit checklist. Evaluate
the reader problem behind each comment. Correct factual inconsistencies, inaccurate claims,
and broken links even when not explicitly called out. Preserve the colleague's contribution
and creative direction rather than undertaking a general rewrite. Treat the colleague as
creative director for this work: retain the approved catchy heading and count-shaded map.

## Settled README presentation

Use this approved coverage copy and heading:

> ## River data and where to find them
>
> RivRetrieve connects you to river data from over 67,000 gauging stations across 12 national agencies, through one Python interface. The map below shows where those providers are, with darker shading indicating more gauges.
>
> [Map]
>
> *Boundaries: Natural Earth. Their depiction implies no position on territorial status.*

Replace `[Map]` with the actual accessible Markdown image and link Natural Earth in the
caption. Integrate this passage into the existing README without duplicating the heading
or coverage introduction. The counts describe the reviewed PR snapshot; verify them against
the current catalogue and actual observation capability before publishing. Correct facts
if the snapshot has changed, while preserving the approved voice and meaning.

Recommend uv prominently for installation, with pip retained as a secondary alternative.
This intentionally balances the maintainer's preference for promoting uv in hydrology with
existing readers' familiarity with pip. It does not change the project's uv-only development
workflow.

Use one continuous quick-start code block, not alternating prose and small snippets:

```python
import rivretrieve as rr

# Find a gauge and choose daily mean streamflow.
gauges = rr.find(provider="usgs_nwis", product="discharge_daily_mean")
gauge = rr.pick(gauges, station="07374000")

# Download observations for January 2023.
result = rr.fetch(gauge, start="2023-01-01", end="2023-01-31")

print(result.data)
print(result.issues)
```

Follow it with the approved explanation:

> Find, select, retrieve. The same Python interface works across providers, returning consistent columns and units. This example downloads daily mean streamflow from a USGS gauge without credentials.

The selling point is a simple, consistent Python API, inspired by scikit-learn's ease of
use. The example completes one useful task. Keep discovery tables, pandas conversion, and
optional features out of this first example; link to the usage guide for detail. Describe
`result.data`, not the whole result object, as the Polars frame. Preserve visibility of
retrieval issues rather than suggesting returned rows guarantee a complete record.

Use general credential wording, not a sentence that implies only Brazil and Norway will
need credentials. Link to real instructions where available. The current usage guide covers
supplying credentials, not acquiring them from agencies; do not claim an acquisition guide
exists when it does not. New provider-specific documentation is not part of this work.

Omit the package-citation section until an actual package citation exists. Retain provider
attribution obligations and data-rights guidance. Preserve the active-development wording
and the statement that breaking changes should be expected between release versions.

## Approved map direction and reproducible reference

Use country shading by number of gauges, not uniform shading and not station dots. This
supersedes the earlier uniform-shading preference. Several providers have unknown coordinate
reference systems; do not assert EPSG:4326 merely to place their stations on this figure.
The map shows countries with supported providers, not complete national network coverage,
continuous observations, or a position on geopolitical boundaries.

The selected preview was a lean world map with no title, subtitle, or prose inside the image.
Its only text is a small horizontal count legend, needed to interpret the shading. Context
and the boundary statement belong in the README. Use the following preview specification
as the visual reference; the original temporary files are not required for implementation:

- Natural Earth 1:50m Admin 0 Countries:
  `https://naturalearth.s3.amazonaws.com/50m_cultural/ne_50m_admin_0_countries.zip`.
- Robinson projection (`ESRI:54030`), excluding Antarctica from the display.
- Country identity matched using `ADM0_A3`, not by blanket sovereign ownership of dependencies.
- Light background `#FBFCFD`, unsupported land `#E3E8EC`, very thin light outlines on shaded
  countries. Matplotlib `GnBu` sequential shading: darker means more gauges.
- Logarithmic colour normalization from 50 to 30,000 in the reviewed snapshot; legend ticks
  at 50, 100, 500, 1,000, 5,000, and 30,000. Label: `Gauging stations · logarithmic scale`.
  Adjust limits if verified counts require it; do not silently clip counts or disguise a
  logarithmic scale as linear.
- Wide, approximately 2:1 figure. The preview used a 14 × 7 inch canvas, with most of it
  devoted to the map and a compact horizontal legend underneath. No Europe inset was approved.

The preview used these PR table counts, not a fresh audited catalogue census:

| Country code | Provider | Gauges |
|---|---|---:|
| BIH | ba_fhmzbih | 60 |
| BRA | br_ana | 17,914 |
| CAN | ca_eccc | 8,057 |
| CZE | cz_chmi | 831 |
| FRA | fr_hubeau | 7,323 |
| JPN | jp_mlit | 1,023 |
| LTU | lt_lhmt | 97 |
| NOR | no_nve | 3,804 |
| POL | pl_imgw | 1,301 |
| CHE | ch_foen | 246 |
| THA | th_thaiwater | 825 |
| USA | usgs_nwis | 26,200 |

Verify gauge counts using unique provider/station identities rather than counting
station-product rows. South Africa (`za_dws`) was catalogue-only at discovery and must not
be shaded or included as retrievable coverage unless actual capability has changed.
Keep the country/provider table consistent with the map and coverage text. Do not extrapolate
support to dependencies merely because they share a sovereign state.

Replace or adapt the proposed `docs/scripts/coverage_map.py` and regenerate
`docs/assets/coverage-map.png`. The figure must be reproducible from a documented boundary
source and the catalogue, rather than requiring an undocumented local shapefile. Temporary
geopandas/matplotlib use through `uv run --with` is acceptable; avoid adding runtime package
dependencies solely for this documentation image. Keep boundary attribution concise and
neutral, as approved, without a long defensive disclaimer.

## Documentation index and scope boundaries

Retain PR #250's reader-oriented organization. Its review comment about a workflow vocabulary
artifact is not permission for broad historical cleanup. Keep the vocabulary link out of the
reader-facing index, but **do not modify or delete `CONTEXT.md`**, its instruction references,
or unrelated historical documents. The user will handle build noise in a dedicated effort.
Do not remove the entire Project records section merely because of that comment.

Do not create ADR documents, reintroduce ADR navigation, add hosted CI, or broaden this into
provider-documentation authoring. Do not change the public API to fit the example. Preserve
unrelated work and the colleague's authorship; update the existing PRs rather than replacing
their contribution with an unrelated rewrite.

## Repository evidence and completion

At discovery, both PRs targeted `main`, were open and mergeable, and had no resolved review
threads. PR #249 (`docs/readme-voice`) changes the root README and adds the map and renderer.
Its follow-up commit already addressed several concerns, including the 12-provider headline,
removal of the pandas example, and development-status wording. Other changes only partially
addressed comments: the citation TODO disappeared but the section remained; pip remained;
station dots remained; credentials still named Brazil and Norway. PR #250
(`docs/index-voice`) changes `docs/README.md`; its vocabulary link had already been removed.
An outdated thread is not proof that its underlying concern is satisfied.

Implementation is complete when:

1. Both PRs reflect the settled presentation and map direction, and all factual inconsistencies
   found within their scope are corrected. Links and examples agree across the README, index,
   and existing usage/reference documentation.
2. Every review concern has a recorded disposition against final changes: already satisfied,
   implemented, or intentionally superseded by the decisions in this vision. Resolve threads
   only after verifying the outcome. Do not claim the colleague approved subsequent changes.
3. Gauge counts, supported-provider selection, boundary matching, image regeneration, and
   example behavior have local validation evidence. Use repository-native checks with uv,
   including `uv run python scripts/generate_reference.py --check` and
   `uv run pytest -q tests/test_documentation.py`, plus relevant renderer/format/lint/type checks.
   For bug fixes, demonstrate a failing regression on the real path before the fix as required
   by repository instructions. Do not require bulk downloads or live agency availability merely
   to validate documentation; distinguish offline replay evidence from live service claims.
4. Independently review the final changes and visually inspect the rendered count-shaded map
   at README scale. Respect required checks and approvals; do not bypass branch protection.
5. Merge both existing PRs through the normal process and verify their intended changes on
   fetched `main`. Preserve their review history. Report any blocked merge rather than claiming
   completion. This vision publication alone does not satisfy any implementation criterion.
