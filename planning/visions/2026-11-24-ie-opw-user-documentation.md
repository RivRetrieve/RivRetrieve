# Ireland OPW user documentation

Author the user-facing provider guide (`docs/providers/ie_opw.md`) and register
navigation and metadata cross-links for Ireland's Office of Public Works (`ie_opw`)
on `port/ie-opw`. Delivering this vision and its documentation contract tests
completes [Effort #986](https://github.com/RivRetrieve/RivRetrieve/issues/986)
under [Program #354](https://github.com/RivRetrieve/RivRetrieve/issues/354).

Work targets `port/ie-opw` and leaves `main` unchanged.
[Effort #987](https://github.com/RivRetrieve/RivRetrieve/issues/987) covers final
review once Steps 1 through 7 and their controlled verification receipts are
complete.

## Scope

Follow [provider-port step 7](../../docs/maintenance/provider-ports.md#7-user-documentation)
and the [documentation language guidelines](../../docs/AGENTS.md):

- Add `docs/providers/ie_opw.md` with the shared six-column retrieval table
  header (`| Quantity filter | Source field / \`variant\` | Frequency | Statistic | Source unit | Returned unit |`),
  a live- and replay-verified retrieval example at station `01041` (`Sandy Mills`
  on the River Deele), and clear explanations of five-digit `00001..41000`
  identifiers, the `385` flowing river gauges out of `571` `stations.json`
  entries (excluding `76` `>41000` rain gauges and `110` tidal, coastal/estuarine,
  lake, reservoir/turlough, and canal/bog/landfill gauges including `30089`
  Angligham), five EPA-numbered river stations hosted on OPW (`09045`,
  `10047..10050`), `year.json` shared daily triplets vs. `*_complete.zip`
  instantaneous archives, `cumec -> m3/s` and `°C -> degC` unit normalization,
  stage above Ordnance Datum (`above_sea_level`, unknown `vertical_datum` mixing
  Malin Head OSGM15 and Poolbeg), uncalibrated `TWater` sensor caveats,
  overnight `*_complete.zip` rebuild lag, missing `-1`/`255` unmeasured handling,
  `ie_opw.series` (`quality_code`) and `ie_opw.daily_stage`
  (`aggregation_accuracy_pct`) annotations, `stations.json` single-source
  metadata (`station_name`, `WTO_OBJECT`, `CATCHMENT_SIZE` inline `km²`,
  withheld elevation), and CC BY 4.0 attribution and `waterlevel@opw.ie`
  operator courtesy notes.
- Register `docs/providers/ie_opw.md` in `docs/README.md`, `mkdocs.yml`, and
  `docs/station-metadata.md` (regenerating `fields-by-provider` via
  `docs/scripts/metadata_fields.py --write` and noting OPW's terms under
  `Data rights`), and regenerate `docs/assets/coverage-map.png` via
  `docs/scripts/coverage_map.py`.
- Verify offline discovery claims, six-column table alignment against all `12`
  packaged products, zero em dashes, strict MkDocs site build, and exact
  recorded example output in `tests/test_ie_opw_documentation.py`.
