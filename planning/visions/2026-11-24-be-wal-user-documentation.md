# Belgium (Wallonia) SPW Hydrométrie user documentation

Author the user-facing provider guide (`docs/providers/be_wal.md`) and register
navigation and metadata cross-links for Belgium's *Service public de Wallonie
(SPW), Hydrométrie* (`be_wal`) on `port/be-wal`. Delivering this vision and its
documentation contract tests completes
[Effort #978](https://github.com/RivRetrieve/RivRetrieve/issues/978) under
[Program #350](https://github.com/RivRetrieve/RivRetrieve/issues/350).

Work targets `port/be-wal` and leaves `main` unchanged.
[Effort #979](https://github.com/RivRetrieve/RivRetrieve/issues/979) covers final
review and merge into `main` once Steps 1 through 7 and their controlled
verification receipts are complete.

## Scope

Follow [provider-port step 7](../../docs/maintenance/provider-ports.md#7-user-documentation)
and the [documentation language guidelines](../../docs/AGENTS.md):

- Add `docs/providers/be_wal.md` with the shared six-column retrieval table
  header (`| Quantity filter | Source field / \`variant\` | Frequency | Statistic | Source unit | Returned unit |`),
  a live- and replay-verified retrieval example at station `6228`
  (`CHAUDFONTAINE Pisc` on `Vesdre`, July 2021 flood), and clear explanations of
  `SPW MI DGH` vs. `SPW ARNE DCENN` (`145` numeric + `193` `L`-prefixed
  stations), the `338` flowing-water gauges including `4` cross-border French
  stations and `13` `STA_PUBINT="no"` gauges (excluding meteorological, zone
  shells, lakes/reservoirs, turbine `640C01`, zero-series `630201`, `9109`,
  `7326`, `7406`, and manual spot gaugings), all `62` products across five
  families (`8,198` active pairs, disjoint standard vs. ultrasonic `Q`, disjoint
  `gauge_zero` vs. `above_sea_level` stage, `05-*.Complet` variable spacing with
  unknown frequency/statistic), negative gauge-zero stages (`L8910`, `L8470`),
  `WGS 84` (`EPSG:4326`) coordinates, single-source metadata (`station_name`,
  `river_name`, `CATCHMENT_SIZE` in `km2` across `257` values + `81`
  `source_null`, omitted `elevation`), deep historical reach from `1929`,
  `365`/`3,650`-day chunking against HTTP 500 `DatasourceError`, fixed CET
  `+01:00` interval-start timestamps, `Value=null` / `Quality Code=-1` gaps,
  `be_wal.quality` annotations (`quality_code`, `quality_code_name`, code `200`
  `Unknown` preserved on peak flows), and SPW `mentions-legales.html` /
  `DataSPW-CGU.pdf` attribution (`Sources des données : Service public de
  Wallonie` / `SPW`), non-redistribution, and MIT software vs. source metadata
  boundary.
- Register `docs/providers/be_wal.md` in `docs/README.md`, `mkdocs.yml`, and
  `docs/station-metadata.md` (regenerating the `fields-by-provider` table via
  `docs/scripts/metadata_fields.py --write` and noting SPW's terms under
  `Data rights`), and update `docs/assets/coverage-map.png` via
  `docs/scripts/coverage_map.py`.
- Verify offline discovery claims, six-column table alignment against all `62`
  packaged products, zero em dashes, strict local link checks, and exact
  recorded example output in `tests/test_be_wal_documentation.py`.
