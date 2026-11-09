# Consistent map cluster appearance

The interactive station explorer should show clusters in one consistent colour with a gauge count. Colour must not encode cluster size or gauge state. This avoids confusing the clustering library’s size-based colours with the Match, Selected, and Conflict legend.

Implementing this vision completes [#569](https://github.com/RivRetrieve/RivRetrieve/issues/569). Publishing the vision alone does not complete the issue.

## Scope

- Use the same colour for all clusters, regardless of gauge count.
- Keep the gauge count visible and readable against the cluster background, and keep clusters distinguishable against the map in supported themes.
- Preserve clustering behaviour, including clicking, zooming, and expanding overlapping markers.
- Preserve individual gauge symbols and the treatment of selected and conflicting gauges.
- Keep Leaflet.markercluster. Choose the exact colour and styling during implementation; no replacement library or broader map redesign is needed.

## Implementation context

`web/station-explorer/src/StationMap.tsx` imports Leaflet.markercluster’s default stylesheet and creates its cluster group without custom icons. The default colours indicate group size. The map legend instead describes Match, Selected, and Conflict. Selected gauges are drawn separately from clustered matches.

The library supports custom cluster icons through `iconCreateFunction`; CSS styling is also available. The implementing agent should choose the simplest sufficient approach.

## Evidence of completion

Show that clusters with different counts retain the same colour and readable numbers, including after zooming and filtering. Check the supported light and dark themes. Confirm that cluster interactions and individual gauge states remain unchanged. Use focused coverage and visual inspection appropriate to this appearance-only change; no clustering algorithm changes are intended.
